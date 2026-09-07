"""Deterministic marker work: legend glyphs, scanning, and patch verification.

A legend states what a series' mark looks like, so the mark itself is measurable
evidence rather than something to be described in words. Python cuts each glyph
out of the legend, scans the plot for it, and re-inspects the pixels under every
coordinate anyone proposes. A reader may name and assign; it may not assert that
a mark exists where the pixels hold none.
"""
import json
import math
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage, signal

INK_LEVEL = .5
GLYPH_HEIGHT_FRACTION = .6
MIN_ROW_ASPECT = 1.8
PITCH_TOLERANCE = .35
SIDE_TOLERANCE = 1.8
DEFAULT_MATCH_THRESHOLD = .55
# Lengths are stated as fractions of the figure's own short side, because a
# legend row, a glyph and a marker are all drawn in proportion to the plate they
# are printed on: the same figure at 150 and at 600 dpi must read identically,
# and a fixed pixel count reads only one of them.
ROW_INK_SIDE_FRACTION = .002
GLYPH_SIDE_FRACTION = .045
COLUMN_ALIGNMENT_FRACTION = .007
ROW_WIDTH_FRACTION = .01
GLYPH_PAD_FRACTION = .003
PLOT_MARKER_SIDE_FRACTION = .02
# Windows for judging how crowded a spot is, measured in marker widths.
OVERLAP_WINDOWS_IN_MARKS = (5, 8, 11)


def figure_scale(gray):
    """The figure's short side: the length everything else is a fraction of."""
    return float(min(gray.shape))


def _length(gray, fraction, floor=1):
    return max(floor, int(round(figure_scale(gray) * fraction)))


def load_gray(image_path):
    with Image.open(image_path) as im:
        return np.asarray(im.convert('L'), dtype=float) / 255.


def _ink(gray):
    return gray < INK_LEVEL


def _rows(mask, plot_bbox, min_ink):
    """Connected ink outside the plot, grouped into horizontal bands."""
    left, top, right, bottom = [int(v) for v in plot_bbox]
    outside = mask.copy()
    outside[max(top, 0):bottom, max(left, 0):right] = False
    labels, count = ndimage.label(outside)
    bands = []
    for index, window in enumerate(ndimage.find_objects(labels), 1):
        size = int(np.count_nonzero(labels[window] == index))
        if size < min_ink:
            continue
        bands.append({'x0': window[1].start, 'x1': window[1].stop,
                      'y0': window[0].start, 'y1': window[0].stop, 'ink': size})
    return bands


def _glyph(mask, band, pad, max_side):
    """The thick part of a legend row: a line with a mark sitting on it."""
    y0, y1 = max(0, band['y0'] - pad), min(mask.shape[0], band['y1'] + pad)
    strip = mask[y0:y1, band['x0']:band['x1']]
    heights = strip.sum(axis=0)
    if heights.size == 0 or heights.max() < 3:
        return None
    columns = np.where(heights >= max(3., heights.max() * GLYPH_HEIGHT_FRACTION))[0]
    if columns.size == 0:
        return None
    x0, x1 = int(columns.min()), int(columns.max()) + 1
    rows = np.where(strip[:, x0:x1].any(axis=1))[0]
    if rows.size == 0:
        return None
    box = [band['x0'] + x0, y0 + int(rows.min()),
           band['x0'] + x1, y0 + int(rows.max()) + 1]
    if not (2 < box[2] - box[0] <= max_side and 2 < box[3] - box[1] <= max_side):
        return None
    return box


def legend_glyphs(gray, plot_bbox, count):
    """Glyph boxes for the legend rows, ordered as the legend reads, top to bottom.

    Legend rows are the only marks that are guaranteed unobstructed, so their
    pixels define what a series looks like. Rows are accepted only when their
    spacing is regular; an irregular set is text or stray ink, not a legend.
    """
    mask = _ink(gray)
    side = _length(gray, ROW_INK_SIDE_FRACTION, floor=2)
    min_ink, min_width = side * side, _length(gray, ROW_WIDTH_FRACTION, floor=4)
    pad, max_side = _length(gray, GLYPH_PAD_FRACTION), _length(gray, GLYPH_SIDE_FRACTION, floor=8)
    alignment = figure_scale(gray) * COLUMN_ALIGNMENT_FRACTION
    candidates = []
    for band in _rows(mask, plot_bbox, min_ink):
        width, height = band['x1'] - band['x0'], band['y1'] - band['y0']
        # A legend row is a mark sitting on a sample line, so it is wide and
        # short; glyph-shaped ink inside a tall band is a letter.
        if width < min_width or width < MIN_ROW_ASPECT * height:
            continue
        glyph = _glyph(mask, band, pad, max_side)
        if glyph:
            candidates.append({'glyph_bbox': glyph, 'row_bbox':
                               [band['x0'], band['y0'], band['x1'], band['y1']]})
    if len(candidates) < count:
        return []
    candidates.sort(key=lambda e: e['glyph_bbox'][0])
    columns = []
    for entry in candidates:
        centre = (entry['glyph_bbox'][0] + entry['glyph_bbox'][2]) / 2
        if columns and centre - columns[-1][0] <= alignment:
            columns[-1][1].append(entry)
        else:
            columns.append((centre, [entry]))
    best, best_cost = None, None
    for _, group in columns:
        group.sort(key=lambda e: e['glyph_bbox'][1])
        for start in range(len(group) - count + 1):
            window = group[start:start + count]
            cost = _irregularity(window)
            if cost is None:
                continue
            if best_cost is None or cost < best_cost:
                best, best_cost = window, cost
    return best or []


def _irregularity(window):
    """How unlike an evenly spaced, uniformly sized legend column this run is."""
    centres = [(e['glyph_bbox'][1] + e['glyph_bbox'][3]) / 2 for e in window]
    gaps = np.diff(centres)
    if gaps.size and (gaps.max() - gaps.min()) > PITCH_TOLERANCE * gaps.mean():
        return None
    sides = [max(e['glyph_bbox'][2] - e['glyph_bbox'][0],
                 e['glyph_bbox'][3] - e['glyph_bbox'][1]) for e in window]
    if max(sides) > SIDE_TOLERANCE * min(sides):
        return None
    spread = float(np.std(gaps) / gaps.mean()) if gaps.size else 0.
    return spread + (max(sides) / min(sides) - 1)


def extract_templates(image_path, plot_bbox, labels, outdir):
    """Cut one small glyph image per legend label; these are the search targets."""
    gray = load_gray(image_path)
    glyphs = legend_glyphs(gray, plot_bbox, len(labels))
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    entries = []
    with Image.open(image_path) as source:
        image = source.convert('RGB')
    for label, found in zip(labels, glyphs):
        box = found['glyph_bbox']
        path = outdir / f"legend_{len(entries):02d}.png"
        image.crop(tuple(box)).save(path)
        patch = gray[box[1]:box[3], box[0]:box[2]]
        entries.append({'label': label, 'template_bbox': [float(v) for v in box],
                        'template_path': str(path),
                        'width': box[2] - box[0], 'height': box[3] - box[1],
                        'ink_fraction': float(np.count_nonzero(patch < INK_LEVEL) / patch.size),
                        'row_bbox': [float(v) for v in found['row_bbox']]})
    if entries:
        (outdir / 'legend_templates.json').write_text(json.dumps(entries, indent=2))
    return entries


MIN_REPEATS = 4


def stroke_radius(ink):
    """Half the thickness of the lines drawn here, measured from the ink itself.

    A curve, an axis and an error bar are strokes of the pen the figure was drawn
    with; a marker is a body. The distance from an ink pixel to the nearest white
    pixel is at most half the stroke width for a stroke, and larger inside a body,
    so the typical such distance over all the ink is this figure's pen.
    """
    if not ink.any():
        return None
    distances = ndimage.distance_transform_edt(ink)
    return float(np.median(distances[ink]))


# A marker is a body: at its middle it stands this many times further from the
# paper than the figure's own pen does at the middle of a stroke. The comparison
# is to the pen the figure was drawn with, so it holds for a thumbnail and for a
# plate scan, and for a 4-pixel dot as much as a 40-pixel one.
BODY_IN_PEN_RADII = 1.5


def detect_marks(image_path, plot_bbox, radius=None):
    """Find the plotted marks by thickness, without a legend and without a reader.

    Curves, error bars and axes are one pen stroke deep; a plotted marker is a
    body, so its middle lies further from the white page than any point of a
    stroke can. Measuring that distance for every ink pixel and keeping the ones
    that stand out against this figure's own pen leaves one core per marker,
    whatever shape each series uses and whatever the marker touches. Cores far
    larger than the rest are overlapping markers printed on top of one another:
    they are returned as crowded, with how many marks their area suggests,
    because splitting them is not something the pixels settle alone.
    """
    gray = load_gray(image_path)
    left, top, right, bottom = (int(round(v)) for v in plot_bbox)
    inside = gray[max(0, top):bottom, max(0, left):right]
    if inside.size == 0:
        return []
    ink = inside < INK_LEVEL
    if not ink.any():
        return []
    distances = ndimage.distance_transform_edt(ink)
    pen = float(np.median(distances[ink]))
    if radius is not None:
        # An explicitly given radius keeps the older, coarser erosion behaviour.
        cores_mask = ndimage.binary_erosion(ink, np.ones((2 * radius + 1,) * 2, bool))
        grow = radius
    else:
        if pen <= 0:
            return []
        cores_mask = distances >= pen * BODY_IN_PEN_RADII
        grow = pen
    labelled, count = ndimage.label(cores_mask)
    if not count:
        return []
    cores = []
    for index, (rows, columns) in enumerate(ndimage.find_objects(labelled), start=1):
        area = int(np.count_nonzero(labelled[rows, columns] == index))
        cores.append({'area': area, 'rows': rows, 'columns': columns})
    # What a thickened line or a dash leaves behind is a sliver thinner than the
    # pen itself, while a marker leaves a core at least the pen's own footprint.
    floor = max(2, int(round(grow * grow)))
    bodies = [c for c in cores if c['area'] >= floor]
    if not bodies:
        return []
    radius = grow
    # One marker printed alone is the smallest body on the sheet; the median body
    # in a crowded figure is already a stack, so it cannot set the unit.
    unit = float(np.percentile([c['area'] for c in bodies], 20))
    marks = []
    for core in bodies:
        rows, columns = core['rows'], core['columns']
        box = [float(left + columns.start - radius), float(top + rows.start - radius),
               float(left + columns.stop + radius), float(top + rows.stop + radius)]
        width, height = box[2] - box[0], box[3] - box[1]
        crowded = core['area'] > 1.8 * unit or max(width, height) > 1.8 * min(width, height)
        marks.append({'x': (box[0] + box[2]) / 2, 'y': (box[1] + box[3]) / 2,
                      'bbox': box, 'width': width, 'height': height,
                      'core_area': core['area'], 'crowded': crowded,
                      'marks_suggested': max(1, int(round(core['area'] / unit))) if crowded else 1})
    marks.sort(key=lambda m: (m['x'], m['y']))
    return marks


def mine_from_plot(image_path, plot_bbox, outdir):
    """Find the repeated mark the plot is drawn with, without asking anyone where it is.

    A figure can label its groups in running text beside the curves and carry no
    legend column at all, and a reader's guessed coordinates can be wrong
    everywhere; the marks are still printed. Every isolated blob inside the plot
    is measured, and the size that recurs most is taken as the marker: axes,
    curves and text are long or unique, so they do not form a tight cluster of
    equal-sized isolated blobs. It is weaker evidence than a legend glyph and is
    recorded as mined.
    """
    gray = load_gray(image_path)
    left, top, right, bottom = (int(round(v)) for v in plot_bbox)
    inside = gray[max(0, top):bottom, max(0, left):right]
    if inside.size == 0:
        return None
    labelled, count = ndimage.label(inside < INK_LEVEL)
    if not count:
        return None
    biggest = _length(gray, PLOT_MARKER_SIDE_FRACTION, floor=8)
    blobs = []
    for index, (rows, columns) in enumerate(ndimage.find_objects(labelled), start=1):
        width, height = columns.stop - columns.start, rows.stop - rows.start
        side = max(width, height)
        if side < 4 or side > biggest or min(width, height) < 3:
            continue
        if max(width, height) > 2.5 * min(width, height):
            continue
        patch = inside[rows, columns]
        ink = float(np.count_nonzero((labelled[rows, columns] == index)) / patch.size)
        if ink < .35:
            continue
        blobs.append({'box': [left + columns.start, top + rows.start,
                              left + columns.stop, top + rows.stop],
                      'side': side, 'ink_fraction': ink})
    if len(blobs) < MIN_REPEATS:
        return None
    sides = np.array([b['side'] for b in blobs], dtype=float)
    typical = float(np.median(sides))
    # The marker is whatever size repeats; a blob of a one-off size is a stray.
    repeated = [b for b in blobs if abs(b['side'] - typical) <= max(1., .25 * typical)]
    if len(repeated) < MIN_REPEATS:
        return None
    pick = max(repeated, key=lambda b: b['ink_fraction'])
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    path = outdir / 'mined_template.png'
    with Image.open(image_path) as source:
        source.convert('RGB').crop(tuple(pick['box'])).save(path)
    box = pick['box']
    return {'template_bbox': [float(v) for v in box], 'template_path': str(path),
            'width': box[2] - box[0], 'height': box[3] - box[1],
            'ink_fraction': pick['ink_fraction'], 'mined_from_plot': True,
            'repeats_found': len(repeated), 'typical_side': typical}


def mine_templates(image_path, points, outdir, window=None):
    """Cut a search target from the plot itself, for figures printed with no legend.

    Some figures carry no legend at all, and some legends are drawn as text
    only. The marks are still on the page, so one of the proposed coordinates is
    made to serve as the target: each is measured, and the isolated blob of the
    most typical size is kept. It is weaker evidence than a legend glyph — it
    assumes one proposal was right — so it is labelled as mined wherever it is
    recorded.
    """
    gray = load_gray(image_path)
    outdir = Path(outdir)
    height, width = gray.shape
    # The window has to hold one mark with room around it, and a mark is drawn in
    # proportion to the figure, so the window is too.
    if window is None:
        window = 2 * _length(gray, PLOT_MARKER_SIDE_FRACTION, floor=8)
    biggest = _length(gray, GLYPH_SIDE_FRACTION, floor=8)
    found = []
    for point in points:
        x, y = int(round(point['x'])), int(round(point['y']))
        left, top = max(0, x - window // 2), max(0, y - window // 2)
        right, bottom = min(width, left + window), min(height, top + window)
        patch = gray[top:bottom, left:right]
        if patch.size == 0:
            continue
        labelled, count = ndimage.label(patch < INK_LEVEL)
        if not count:
            continue
        centre = labelled[min(patch.shape[0] - 1, y - top), min(patch.shape[1] - 1, x - left)]
        if not centre:
            continue
        rows, columns = np.nonzero(labelled == centre)
        box = [left + int(columns.min()), top + int(rows.min()),
               left + int(columns.max()) + 1, top + int(rows.max()) + 1]
        side = max(box[2] - box[0], box[3] - box[1])
        if side < 3 or side > biggest:
            continue
        touches_edge = (rows.min() == 0 or columns.min() == 0
                        or rows.max() == patch.shape[0] - 1
                        or columns.max() == patch.shape[1] - 1)
        found.append({'box': box, 'area': int(rows.size), 'touches_edge': touches_edge})
    clean = [f for f in found if not f['touches_edge']] or found
    if not clean:
        return None
    typical = float(np.median([f['area'] for f in clean]))
    pick = min(clean, key=lambda f: abs(f['area'] - typical))
    outdir.mkdir(parents=True, exist_ok=True)
    path = outdir / 'mined_template.png'
    with Image.open(image_path) as source:
        source.convert('RGB').crop(tuple(pick['box'])).save(path)
    box = pick['box']
    patch = gray[box[1]:box[3], box[0]:box[2]]
    return {'template_bbox': [float(v) for v in box], 'template_path': str(path),
            'width': box[2] - box[0], 'height': box[3] - box[1],
            'ink_fraction': float(np.count_nonzero(patch < INK_LEVEL) / patch.size),
            'mined_from_plot': True, 'candidates_measured': len(found)}


def _ncc_map(gray, template):
    """Zero-mean normalized cross correlation of the template over every window."""
    h, w = template.shape
    if h < 3 or w < 3 or h > gray.shape[0] or w > gray.shape[1]:
        return None
    centered = template - template.mean()
    energy = float(np.sum(centered ** 2))
    if energy < 1e-8:
        return None
    ones = np.ones((h, w))
    sums = signal.fftconvolve(gray, ones, mode='valid')
    squares = signal.fftconvolve(gray * gray, ones, mode='valid')
    numerator = signal.fftconvolve(gray, centered[::-1, ::-1], mode='valid')
    denominator = np.sqrt(np.maximum(squares - sums * sums / (h * w), 0) * energy)
    result = np.zeros_like(numerator)
    np.divide(numerator, denominator, out=result, where=denominator > 1e-10)
    return np.clip(result, -1., 1.)


def scan(gray, template_bbox, plot_bbox, threshold=DEFAULT_MATCH_THRESHOLD,
         max_hits=400, columns=None, column_tolerance=None):
    """Sweep the glyph across the plot; peaks are marker locations, in reading order.

    Restricting to known sample columns is what makes a dense chart tractable:
    where the document states when samples were taken, a peak away from those
    times is a line crossing, not an observation.
    """
    box = [int(v) for v in template_bbox]
    template = gray[box[1]:box[3], box[0]:box[2]]
    left, top, right, bottom = [int(v) for v in plot_bbox]
    height, width = template.shape
    region = gray[top:bottom, left:right]
    correlation = _ncc_map(region, template)
    if correlation is None:
        return []
    peaks = correlation == ndimage.maximum_filter(
        correlation, size=max(3, min(height, width) // 2))
    ys, xs = np.where(peaks & (correlation >= threshold))
    hits = []
    for y, x in zip(ys, xs):
        cx = left + x + (width - 1) / 2.
        cy = top + y + (height - 1) / 2.
        if columns is not None:
            near = min(columns, key=lambda c: abs(c - cx))
            if abs(near - cx) > (column_tolerance if column_tolerance is not None else width):
                continue
        hits.append({'x': float(cx), 'y': float(cy),
                     'score': float(correlation[y, x])})
    hits.sort(key=lambda h: -h['score'])
    kept = []
    for hit in hits:
        if any(math.hypot(hit['x'] - k['x'], hit['y'] - k['y']) < min(width, height) * .5
               for k in kept):
            continue
        kept.append(hit)
        if len(kept) >= max_hits:
            break
    kept.sort(key=lambda h: (h['x'], h['y']))
    return kept


def patch_report(gray, template_bbox, x, y):
    """Inspect the pixels a proposed coordinate actually sits on.

    An empty or near-empty window is the signature of a hallucinated point, and
    it is measurable, so no reader is asked to be honest about it.
    """
    box = [int(v) for v in template_bbox]
    template = gray[box[1]:box[3], box[0]:box[2]]
    h, w = template.shape
    left = int(round(x - (w - 1) / 2.))
    top = int(round(y - (h - 1) / 2.))
    right, bottom = left + w, top + h
    if left < 0 or top < 0 or bottom > gray.shape[0] or right > gray.shape[1]:
        return {'status': 'outside_image', 'ink_fraction': 0., 'ncc': None,
                'template_ink_fraction': float(np.count_nonzero(template < INK_LEVEL) / template.size)}
    patch = gray[top:bottom, left:right]
    template_ink = float(np.count_nonzero(template < INK_LEVEL) / template.size)
    patch_ink = float(np.count_nonzero(patch < INK_LEVEL) / patch.size)
    centered = template - template.mean()
    window = patch - patch.mean()
    energy = math.sqrt(float(np.sum(centered ** 2)) * float(np.sum(window ** 2)))
    ncc = float(np.sum(centered * window) / energy) if energy > 1e-8 else None
    return {'status': 'measured', 'ink_fraction': patch_ink,
            'template_ink_fraction': template_ink, 'ncc': ncc,
            'patch_bbox': [left, top, right, bottom]}


def verdict(report, min_ncc=DEFAULT_MATCH_THRESHOLD, min_ink_ratio=.5):
    """Pass or fail a proposed coordinate on measured pixels alone."""
    if report['status'] != 'measured':
        return {'passed': False, 'reason': report['status']}
    if report['ink_fraction'] < min_ink_ratio * report['template_ink_fraction']:
        return {'passed': False, 'reason': 'window_is_mostly_empty',
                'ink_fraction': report['ink_fraction'],
                'expected_ink_fraction': report['template_ink_fraction']}
    if report['ncc'] is None or report['ncc'] < min_ncc:
        return {'passed': False, 'reason': 'window_does_not_match_legend_glyph',
                'ncc': report['ncc'], 'min_ncc': min_ncc}
    return {'passed': True, 'ncc': report['ncc'],
            'ink_fraction': report['ink_fraction']}


def _words(delta, axis):
    if abs(delta) < 1:
        return None
    size = ('a little' if abs(delta) <= 5 else
            'moderately' if abs(delta) <= 20 else 'a lot')
    direction = ('right' if delta > 0 else 'left') if axis == 'x' else (
        'down' if delta > 0 else 'up')
    return f'{size} {direction} ({abs(round(delta))} px)'


def correction(gray, template_bbox, x, y, search_px=None):
    """Nearest better-matching window, expressed as a measured pixel offset.

    Feedback is generated from correlation, not from a reader's impression, and
    the same numbers are what Python applies, so accepting the advice and acting
    on it cannot diverge.
    """
    box = [int(v) for v in template_bbox]
    template = gray[box[1]:box[3], box[0]:box[2]]
    h, w = template.shape
    reach = int(search_px if search_px is not None else max(h, w) * 1.5)
    left = max(0, int(round(x)) - reach - w)
    top = max(0, int(round(y)) - reach - h)
    right = min(gray.shape[1], int(round(x)) + reach + w)
    bottom = min(gray.shape[0], int(round(y)) + reach + h)
    correlation = _ncc_map(gray[top:bottom, left:right], template)
    if correlation is None or correlation.size == 0:
        return None
    iy, ix = np.unravel_index(int(np.argmax(correlation)), correlation.shape)
    cx = left + ix + (w - 1) / 2.
    cy = top + iy + (h - 1) / 2.
    dx, dy = cx - x, cy - y
    advice = [t for t in (_words(dx, 'x'), _words(dy, 'y')) if t]
    return {'x': float(cx), 'y': float(cy), 'dx': float(dx), 'dy': float(dy),
            'distance_px': float(math.hypot(dx, dy)),
            'score': float(correlation[iy, ix]),
            'advice': 'move ' + ' and '.join(advice) if advice else 'already centred'}


def crowding(gray, x, y, windows=None, glyph_ink=None, mark_side=None):
    """How much ink surrounds a point, as a bound on how many marks could hide there.

    The windows are counted in marks, not pixels: how many marks could hide in a
    given patch depends on how big a mark is here, so a patch worth asking about
    on one figure is a whole panel on another.
    """
    mask = _ink(gray)
    if windows is None:
        if mark_side is None:
            mark_side = _length(gray, PLOT_MARKER_SIDE_FRACTION, floor=8)
        windows = [max(3, int(round(mark_side * n))) for n in OVERLAP_WINDOWS_IN_MARKS]
    report = {}
    for side in windows:
        half = side // 2
        left, top = max(0, int(x) - half), max(0, int(y) - half)
        window = mask[top:top + side, left:left + side]
        ink = int(np.count_nonzero(window))
        entry = {'ink_pixels': ink}
        if glyph_ink:
            entry['glyph_equivalents'] = round(ink / glyph_ink, 2)
        report[f'{side}x{side}'] = entry
    return report
