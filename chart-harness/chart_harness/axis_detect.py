"""Deterministic axis-line and tick detection used to cross-check model anchors.

A tick-residual check only proves that model anchors are mutually consistent. A
reader that misplaces every anchor by the same offset, or that reports anchors
for a differently scaled rendering, still produces a perfectly linear fit. The
detector below measures axis lines and tick marks from the original pixels so
that such globally shifted calibrations become visible.
"""
from pathlib import Path

import numpy as np
from PIL import Image

DARK_THRESHOLD = 128
MIN_AXIS_COVERAGE = 0.25
TICK_BAND_PX = 16
TICK_MIN_LENGTH = 4


def _binary(image_path):
    with Image.open(image_path) as source:
        return np.asarray(source.convert('L')) < DARK_THRESHOLD


def _runs(mask):
    """Contiguous True runs as (start, stop) half-open index pairs."""
    padded = np.concatenate(([False], mask, [False]))
    edges = np.flatnonzero(padded[1:] != padded[:-1])
    return list(zip(edges[0::2].tolist(), edges[1::2].tolist()))


def _axis_line(counts, extent):
    """Index of the longest straight rule, or None when nothing spans the frame."""
    best = int(np.argmax(counts))
    if counts[best] < MIN_AXIS_COVERAGE * extent:
        return None
    return best


def _tick_centers(band, minimum_length):
    lengths = band.sum(axis=0)
    return [(start + stop - 1) / 2.0 for start, stop in _runs(lengths >= minimum_length)]


def detect_ticks(image_path):
    """Locate the x and y axis rules and the tick centers printed against them."""
    mask = _binary(image_path)
    height, width = mask.shape
    x_axis_row = _axis_line(mask.sum(axis=1), width)
    y_axis_col = _axis_line(mask.sum(axis=0), height)
    detected = {'image_size': [int(width), int(height)],
                'x_axis_row': None if x_axis_row is None else int(x_axis_row),
                'y_axis_col': None if y_axis_col is None else int(y_axis_col),
                'x_tick_pixels': [], 'y_tick_pixels': []}
    if x_axis_row is not None:
        below = mask[x_axis_row + 3:min(height, x_axis_row + 3 + TICK_BAND_PX), :]
        above = mask[max(0, x_axis_row - 2 - TICK_BAND_PX):max(0, x_axis_row - 2), :]
        outward = _tick_centers(below, TICK_MIN_LENGTH)
        detected['x_tick_pixels'] = outward or _tick_centers(above, TICK_MIN_LENGTH)
        detected['x_ticks_outward'] = bool(outward)
    if y_axis_col is not None:
        left = mask[:, max(0, y_axis_col - 2 - TICK_BAND_PX):max(0, y_axis_col - 2)]
        right = mask[:, y_axis_col + 3:min(width, y_axis_col + 3 + TICK_BAND_PX)]
        outward = _tick_centers(left.T, TICK_MIN_LENGTH)
        detected['y_tick_pixels'] = outward or _tick_centers(right.T, TICK_MIN_LENGTH)
        detected['y_ticks_outward'] = bool(outward)
    return detected


def _match(anchors, tick_pixels, tolerance):
    if not anchors:
        return {'checked': False, 'reason': 'no model anchors'}
    if not tick_pixels:
        return {'checked': False, 'reason': 'no ticks detected'}
    offsets = []
    for anchor in anchors:
        pixel = float(anchor['pixel'])
        nearest = min(tick_pixels, key=lambda t: abs(t - pixel))
        offsets.append({'anchor_pixel': pixel, 'value': anchor.get('value'),
                        'nearest_tick_pixel': nearest, 'offset_px': nearest - pixel})
    worst = max(abs(o['offset_px']) for o in offsets)
    return {'checked': True, 'agrees': worst <= tolerance, 'max_offset_px': worst,
            'tolerance_px': tolerance, 'detected_tick_pixels': tick_pixels,
            'offsets': offsets}


def crosscheck(image_path, interpretation, tolerance_px):
    """Compare model axis anchors against detected tick positions."""
    detected = detect_ticks(Path(image_path))
    axes = {'x_axis': detected['x_tick_pixels'], 'y_axis': detected['y_tick_pixels']}
    report = {'detected': detected, 'axes': {}, 'tolerance_px': tolerance_px}
    for name, ticks in axes.items():
        anchors = (interpretation.get(name) or {}).get('anchors', [])
        report['axes'][name] = _match(anchors, ticks, tolerance_px)
    checked = [v for v in report['axes'].values() if v.get('checked')]
    report['agrees'] = bool(checked) and all(v['agrees'] for v in checked)
    report['inconclusive'] = not checked
    return report


def clamp_plot_bbox(bbox, detected):
    """Trim a plot box to the measured axis rules.

    Tick labels outside the frame are otherwise matched as markers: a box whose
    left edge sits left of the y-axis rule turns the y tick labels into
    candidates.
    """
    left, top, right, bottom = (float(v) for v in bbox)
    col, row = detected.get('y_axis_col'), detected.get('x_axis_row')
    if col is not None and left < col <= right:
        left = float(col)
    if row is not None and top <= row < bottom:
        bottom = float(row)
    clamped = [left, top, right, bottom]
    return clamped, clamped != [float(v) for v in bbox]


def repair_packet(image_path, detected, outdir):
    """Prompt and images asking a reader to name the values of detected ticks.

    Python supplies the tick geometry; the model only reads printed digits, so a
    globally shifted anchor set cannot survive the repair.
    """
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    with Image.open(image_path) as source:
        image = source.convert('RGB')
        width, height = image.size
        row, col = detected.get('x_axis_row'), detected.get('y_axis_col')
        images = []
        if row is not None:
            box = (0, min(height, row + 1), width, min(height, row + 90))
            tile = image.crop(box)
            path = outdir / 'x_tick_labels.png'
            tile.resize((tile.width * 2, tile.height * 2), Image.Resampling.NEAREST).save(path)
            images.append((path, 'x_tick_labels', box))
        if col is not None:
            box = (max(0, col - 220), 0, max(1, col), height)
            tile = image.crop(box)
            path = outdir / 'y_tick_labels.png'
            tile.resize((tile.width * 2, tile.height * 2), Image.Resampling.NEAREST).save(path)
            images.append((path, 'y_tick_labels', box))
    described = [{'image_index': index + 2, 'region': name, 'source_crop_box': list(box),
                  'scale': 2, 'pixel_mapping': 'original = crop_origin + (tile_pixel + 0.5)/2 - 0.5'}
                 for index, (_, name, box) in enumerate(images)]
    prompt = f'''Assign printed values to tick marks that were measured from the raw pixels.
Image 1 is the unannotated chart, {width}x{height}, top-left pixel center (0,0).
Later images are nearest-neighbour enlargements of the raw label strips: {described}.
Detected x-axis rule row: {detected.get('x_axis_row')}. Detected y-axis rule column: {detected.get('y_axis_col')}.
Detected x tick pixel columns: {[round(p, 1) for p in detected.get('x_tick_pixels', [])]}.
Detected y tick pixel rows: {[round(p, 1) for p in detected.get('y_tick_pixels', [])]}.
These pixel positions are measurements. Do NOT move, re-estimate or invent them.
Return JSON {{"x_axis":{{"scale":"linear or log","unit":"printed unit",
"anchors":[{{"pixel":one of the detected x tick pixels,"value":printed value}},...]}},
"y_axis":{{"scale":"linear or log","unit":"printed unit","anchors":[...]}},
"status":"readable or unresolved","notes":[]}}.
Include only ticks whose printed label you can actually read; omit unlabeled ticks.
Read the digits that are printed, not a conventional or expected sampling schedule.
A log axis must be reported as log with the printed decade values, never relabelled.
If the labels are unreadable, status must be unresolved. Do not guess or run code.'''
    return prompt, [Path(image_path)] + [path for path, _, _ in images]


def apply_repair(interpretation, repaired, detected, tolerance_px):
    """Replace anchors with detected-tick anchors the reader could label."""
    applied = {}
    for name in ('x_axis', 'y_axis'):
        proposed = repaired.get(name)
        ticks = detected['x_tick_pixels' if name == 'x_axis' else 'y_tick_pixels']
        if not isinstance(proposed, dict) or not ticks:
            continue
        anchors = []
        for anchor in proposed.get('anchors', []):
            pixel = anchor.get('pixel')
            value = anchor.get('value')
            if not isinstance(pixel, (int, float)) or not isinstance(value, (int, float)):
                continue
            nearest = min(ticks, key=lambda t: abs(t - pixel))
            if abs(nearest - pixel) <= tolerance_px:
                anchors.append({'pixel': nearest, 'value': value})
        unique = {a['pixel']: a for a in anchors}
        if len(unique) < 2:
            continue
        axis = dict(interpretation.get(name) or {})
        axis['anchors'] = sorted(unique.values(), key=lambda a: a['pixel'])
        if proposed.get('scale'):
            axis['scale'] = proposed['scale']
        if proposed.get('unit'):
            axis['unit'] = proposed['unit']
        interpretation[name] = axis
        applied[name] = axis['anchors']
    return applied
