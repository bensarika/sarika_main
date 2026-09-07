"""Deterministic axis-line and tick detection used to cross-check model anchors.

A tick-residual check only proves that model anchors are mutually consistent. A
reader that misplaces every anchor by the same offset, or that reports anchors
for a differently scaled rendering, still produces a perfectly linear fit. The
detector below measures axis lines and tick marks from the original pixels so
that such globally shifted calibrations become visible.
"""
import itertools
import math
from pathlib import Path

import numpy as np
from PIL import Image

DARK_THRESHOLD = 128
MIN_AXIS_COVERAGE = 0.25
# Nothing here is measured in absolute pixels: a tick is a short stroke drawn
# against the rule, and how many pixels short means depends entirely on how large
# the figure was rendered. The band searched for ticks, the stroke length that
# counts as one, and the gap skipped over the rule itself are all fractions of
# the figure's own dimensions or of the measured thickness of the rule.
TICK_BAND_FRACTION = 0.02
TICK_MIN_LENGTH_FRACTION = 0.25
# Anchors are compared against the printed ticks at a fraction of the spacing
# between those ticks, so the same criterion holds for a thumbnail and a poster.
TICK_AGREEMENT_FRACTION_OF_SPACING = 0.25


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


def _rule_span(counts, index):
    """Extent of the rule at index: the neighbouring lines that are nearly as inked."""
    peak = counts[index]
    low, high = index, index
    while low > 0 and counts[low - 1] >= peak * 0.5:
        low -= 1
    while high + 1 < len(counts) and counts[high + 1] >= peak * 0.5:
        high += 1
    return low, high


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
        band = max(2, int(round(height * TICK_BAND_FRACTION)))
        minimum = max(1, int(round(band * TICK_MIN_LENGTH_FRACTION)))
        top, bottom = _rule_span(mask.sum(axis=1), x_axis_row)
        below = mask[bottom + 1:min(height, bottom + 1 + band), :]
        above = mask[max(0, top - band):max(0, top), :]
        outward = _tick_centers(below, minimum)
        detected['x_tick_pixels'] = outward or _tick_centers(above, minimum)
        detected['x_ticks_outward'] = bool(outward)
        detected['x_tick_band_px'] = band
    if y_axis_col is not None:
        band = max(2, int(round(width * TICK_BAND_FRACTION)))
        minimum = max(1, int(round(band * TICK_MIN_LENGTH_FRACTION)))
        first, last = _rule_span(mask.sum(axis=0), y_axis_col)
        left = mask[:, max(0, first - band):max(0, first)]
        right = mask[:, last + 1:min(width, last + 1 + band)]
        outward = _tick_centers(left.T, minimum)
        detected['y_tick_pixels'] = outward or _tick_centers(right.T, minimum)
        detected['y_ticks_outward'] = bool(outward)
        detected['y_tick_band_px'] = band
    return detected


def spacing(tick_pixels):
    """The closest distance between two printed ticks: this axis's resolution."""
    ordered = sorted(float(t) for t in tick_pixels)
    gaps = [b - a for a, b in zip(ordered, ordered[1:]) if b > a]
    return min(gaps) if gaps else None


def _match(anchors, tick_pixels, tolerance=None):
    if not anchors:
        return {'checked': False, 'reason': 'no model anchors'}
    if not tick_pixels:
        return {'checked': False, 'reason': 'no ticks detected'}
    gap = spacing(tick_pixels)
    if tolerance is None:
        if gap is None:
            return {'checked': False, 'reason': 'a single tick gives no spacing to judge against'}
        tolerance = gap * TICK_AGREEMENT_FRACTION_OF_SPACING
    offsets = []
    for anchor in anchors:
        pixel = float(anchor['pixel'])
        nearest = min(tick_pixels, key=lambda t: abs(t - pixel))
        offsets.append({'anchor_pixel': pixel, 'value': anchor.get('value'),
                        'nearest_tick_pixel': nearest, 'offset_px': nearest - pixel})
    worst = max(abs(o['offset_px']) for o in offsets)
    return {'checked': True, 'agrees': worst <= tolerance, 'max_offset_px': worst,
            'tolerance_px': tolerance, 'tick_spacing_px': gap,
            'offset_fraction_of_spacing': None if not gap else worst / gap,
            'detected_tick_pixels': tick_pixels, 'offsets': offsets}


def crosscheck(image_path, interpretation, tolerance_px=None):
    """Compare model axis anchors against detected tick positions.

    With no tolerance given, each axis is judged against its own printed tick
    spacing, which is what the figure itself can resolve.
    """
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


def plot_bbox_from_ticks(detected):
    """Build the plot box from measured axis rules and outermost ticks.

    A reader shown a downscaled rendering returns a box in that frame, which is
    a scaled version of the truth and therefore invisible to any self-consistency
    check. Where both rules and their ticks were measured, the box is geometry,
    not interpretation.
    """
    col, row = detected.get('y_axis_col'), detected.get('x_axis_row')
    x_ticks = detected.get('x_tick_pixels') or []
    y_ticks = detected.get('y_tick_pixels') or []
    if col is None or row is None or len(x_ticks) < 2 or len(y_ticks) < 2:
        return None
    right = max(max(x_ticks), float(col))
    top = min(min(y_ticks), float(row))
    if right <= col or top >= row:
        return None
    return [float(col), float(top), float(right), float(row)]


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


INDEX_SEARCH = 3
# A tick assignment is straight enough when its worst residual is small next to
# the spacing of the ticks it is assigning, which is the only length in the
# figure that means anything here.
FIT_RESIDUAL_FRACTION_OF_SPACING = 0.05


def _fit_residual(anchors, scale):
    """Worst pixel residual of a straight line through (value, pixel) anchors."""
    values = []
    for anchor in anchors:
        value = float(anchor['value'])
        if scale == 'log':
            if value <= 0:
                return None
            value = math.log10(value)
        values.append(value)
    pixels = [float(a['pixel']) for a in anchors]
    if len(set(values)) < 2:
        return None
    slope, intercept = np.polyfit(values, pixels, 1)
    return max(abs(slope * v + intercept - p) for v, p in zip(values, pixels))


def _refit_indices(anchors, ticks, scale, span, limit):
    """Search near the reader's tick indices for a collinear assignment.

    Readers miscount long tick lists by an index or two, which is a large pixel
    error but a small combinatorial one, so the printed values stay usable when
    exactly one nearby assignment is straight. Equally straight assignments are
    settled by staying closest to what the reader actually named.
    """
    best = None
    for offsets in itertools.product(range(-span, span + 1), repeat=len(anchors)):
        picked = []
        for anchor, offset in zip(anchors, offsets):
            index = anchor['index'] + offset
            if not 0 <= index < len(ticks):
                break
            picked.append({'pixel': ticks[index], 'value': anchor['value']})
        else:
            if len({p['pixel'] for p in picked}) < len(picked):
                continue
            residual = _fit_residual(picked, scale)
            if residual is None:
                continue
            key = (round(residual, 6), sum(abs(o) for o in offsets))
            if best is None or key < best[0]:
                best = (key, picked)
    if best is None or best[0][0] > limit:
        return None
    return best[1]


def resolve_tick_indices(axis_check, detected, tolerance_px=None):
    """Turn reviewer anchors that name measured ticks into measured pixels.

    A reader reports coordinates in whatever rendering it was shown, so its raw
    pixels can be uniformly scaled away from the source. Naming a tick by index
    keeps the reader's contribution (the printed value) and Python's (the
    position); a reader that still returns a pixel is snapped only if it already
    lands on a measured tick.
    """
    resolved = {}
    dropped = []
    for name in ('x_axis', 'y_axis'):
        axis = axis_check.get(name)
        ticks = detected.get('x_tick_pixels' if name == 'x_axis' else 'y_tick_pixels') or []
        if not isinstance(axis, dict):
            continue
        resolved[name] = axis
        if not ticks:
            continue
        gap = spacing(ticks)
        snap = tolerance_px if tolerance_px is not None else (
            None if gap is None else gap * TICK_AGREEMENT_FRACTION_OF_SPACING)
        straight = None if gap is None else gap * FIT_RESIDUAL_FRACTION_OF_SPACING
        anchors = []
        named = []
        for anchor in axis.get('anchors', []):
            index, pixel, value = anchor.get('tick_index'), anchor.get('pixel'), anchor.get('value')
            if not isinstance(value, (int, float)):
                continue
            if isinstance(index, int) and 0 <= index < len(ticks):
                anchors.append({'pixel': ticks[index], 'value': value})
                named.append({'index': index, 'value': value})
                continue
            if isinstance(pixel, (int, float)):
                nearest = min(ticks, key=lambda t: abs(t - pixel))
                if snap is not None and abs(nearest - pixel) <= snap:
                    anchors.append({'pixel': nearest, 'value': value})
                    continue
                dropped.append({'axis': name, 'pixel': float(pixel), 'value': value,
                                'nearest_tick_pixel': nearest})
            else:
                dropped.append({'axis': name, 'tick_index': index, 'value': value})
        if len(named) == len(anchors) >= 2 and straight is not None:
            residual = _fit_residual(anchors, axis.get('scale'))
            if residual is None or residual > straight:
                refit = _refit_indices(named, ticks, axis.get('scale'), INDEX_SEARCH, straight)
                if refit is None:
                    dropped.append({'axis': name, 'reason': 'named ticks do not fit the stated scale',
                                    'anchors': anchors})
                    continue
                if refit != anchors:
                    dropped.append({'axis': name, 'reason': 'reader tick indices refitted',
                                    'from': anchors, 'to': refit})
                anchors = refit
        unique = {a['pixel']: a for a in anchors}
        if len(unique) >= 2:
            resolved[name] = {**axis, 'anchors': sorted(unique.values(), key=lambda a: a['pixel'])}
    return {**axis_check, **resolved}, dropped


def apply_repair(interpretation, repaired, detected, tolerance_px=None):
    """Replace anchors with detected-tick anchors the reader could label."""
    applied = {}
    for name in ('x_axis', 'y_axis'):
        proposed = repaired.get(name)
        ticks = detected['x_tick_pixels' if name == 'x_axis' else 'y_tick_pixels']
        if not isinstance(proposed, dict) or not ticks:
            continue
        gap = spacing(ticks)
        snap = tolerance_px if tolerance_px is not None else (
            None if gap is None else gap * TICK_AGREEMENT_FRACTION_OF_SPACING)
        if snap is None:
            continue
        anchors = []
        for anchor in proposed.get('anchors', []):
            pixel = anchor.get('pixel')
            value = anchor.get('value')
            if not isinstance(pixel, (int, float)) or not isinstance(value, (int, float)):
                continue
            nearest = min(ticks, key=lambda t: abs(t - pixel))
            if abs(nearest - pixel) <= snap:
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
