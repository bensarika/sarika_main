"""Independent ways of finding the plotted marks, all run side by side.

No one rule finds the marks in every figure. Colour separates the series in a
printed patent plate and says nothing about a black-and-white one; a template
pass finds repeated glyphs and misses a bar chart entirely; a bar chart states
its values with the top edge of each bar; a line chart's markers must sit on the
curve, so following the curve reaches them even where a template match is
ambiguous. Rather than betting the run on whichever rule the harness happens to
prefer, every method that can speak here is run in parallel, keeps its own
evidence, and the results are pooled: a location several independent methods
agree on is corroborated, and one only a single method saw is reported as such.

Nothing in this module decides what a point means. It reports where ink of a
given description is, with the measurements behind each claim, so the screening
and calibration stages can accept or reject it on the pixels.

Every length is derived from the figure - its short side, its own pen thickness,
the size of the bodies it draws - never from a pixel count fixed in advance.
"""
import math
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from PIL import Image
from scipy import ndimage

from . import glyphs
from . import markers
from . import progress

# A hue is quantised to one degree, which is the resolution of the measurement
# itself rather than a chosen bucket size.
HUE_STEPS = 360
# A body is corroborated by another method when the two sit within this share of
# a mark's own width of each other: the same mark, seen twice.
CORROBORATION_FRACTION_OF_MARK = .75
# A column of ink counts as a marker sitting on a curve when it runs this many
# times longer than the figure's own pen stroke. Two strokes cannot stack into
# this by accident; a dot on a line does.
CURVE_BODY_IN_STROKES = 3.
# A run of columns is a bar when it is at least this many strokes wide, so a
# thick axis or an error bar's whisker is not read as a bar.
BAR_WIDTH_IN_STROKES = 2.


def _crop(array, plot_bbox):
    left, top, right, bottom = (int(round(v)) for v in plot_bbox)
    left, top = max(0, left), max(0, top)
    return array[top:bottom, left:right], left, top


def _bodies(mask, offset, method, minimum_area):
    """Connected ink in a mask, as marks with their measured extent."""
    labelled, count = ndimage.label(mask)
    if not count:
        return []
    left, top = offset
    found = []
    for index, (rows, columns) in enumerate(ndimage.find_objects(labelled), start=1):
        area = int(np.count_nonzero(labelled[rows, columns] == index))
        if area < minimum_area:
            continue
        box = [float(left + columns.start), float(top + rows.start),
               float(left + columns.stop), float(top + rows.stop)]
        found.append({'x': (box[0] + box[2]) / 2, 'y': (box[1] + box[3]) / 2,
                      'bbox': box, 'width': box[2] - box[0], 'height': box[3] - box[1],
                      'area': area, 'method': method})
    found.sort(key=lambda m: (m['x'], m['y']))
    return found


def by_colour(image_path, plot_bbox):
    """Split the plot by printed colour and return each colour's bodies.

    Where a legend says a series is red, the red pixels are that series and
    nothing else is: the separation is exact and needs no matching. Hues are
    grouped by where the figure's own colours fall - contiguous occupied hues
    form one group - so a plate using two reds is not forced into one bin, and a
    grey figure simply reports no colour groups at all.
    """
    with Image.open(image_path) as source:
        rgb = np.asarray(source.convert('RGB'), dtype=float) / 255.
    inside, left, top = _crop(rgb, plot_bbox)
    if inside.size == 0:
        return []
    high, low = inside.max(axis=2), inside.min(axis=2)
    saturation = high - low
    if not saturation.size or saturation.max() <= 0:
        return []
    # Colour is present where saturation stands out against the page: half of the
    # strongest colour the figure itself prints.
    coloured = saturation >= saturation.max() / 2
    if not coloured.any():
        return []
    with np.errstate(invalid='ignore', divide='ignore'):
        hsv = np.asarray(Image.fromarray(
            (inside * 255).astype(np.uint8), 'RGB').convert('HSV'), dtype=float)
    hue = hsv[:, :, 0] * (HUE_STEPS / 256.)
    occupied = np.zeros(HUE_STEPS, bool)
    occupied[np.clip(hue[coloured].astype(int), 0, HUE_STEPS - 1)] = True
    groups, run = [], []
    for degree in range(HUE_STEPS):
        if occupied[degree]:
            run.append(degree)
        elif run:
            groups.append(run)
            run = []
    if run:
        groups.append(run)
    # The hue circle wraps, so a red group split across 0 degrees is one group.
    if len(groups) > 1 and groups[0][0] == 0 and groups[-1][-1] == HUE_STEPS - 1:
        groups[0] = groups[-1] + groups[0]
        groups.pop()
    pen = markers.stroke_radius(coloured) or 1.
    minimum = max(2, int(round(pen * pen)))
    marks = []
    for group in groups:
        band = np.isin(np.clip(hue.astype(int), 0, HUE_STEPS - 1), group) & coloured
        centre = int(np.median(group) % HUE_STEPS)
        for mark in _bodies(band, (left, top), 'colour', minimum):
            mark['colour_hue'] = centre
            mark['colour_group_size'] = int(np.count_nonzero(band))
            marks.append(mark)
    marks.sort(key=lambda m: (m['x'], m['y']))
    return marks


def by_shape(image_path, plot_bbox, template_bbox=None, outdir=None):
    """Sweep a mark-shaped window over the whole plot and keep every match.

    This is the passthrough: the shape and size of one mark is known - either
    from the legend glyph or mined from the plot - and the same window is
    correlated at every position, so a mark is found wherever it is printed
    rather than only where somebody looked.
    """
    gray = markers.load_gray(image_path)
    if template_bbox is None:
        mined = markers.mine_from_plot(image_path, plot_bbox, outdir) if outdir else None
        if not mined:
            return []
        template_bbox = mined['template_bbox']
    hits = markers.scan(gray, template_bbox, plot_bbox)
    box = [int(v) for v in template_bbox]
    width, height = box[2] - box[0], box[3] - box[1]
    for hit in hits:
        hit.update({'method': 'shape', 'width': float(width), 'height': float(height),
                    'bbox': [hit['x'] - width / 2., hit['y'] - height / 2.,
                             hit['x'] + width / 2., hit['y'] + height / 2.]})
    return hits


def bar_tops(image_path, plot_bbox):
    """Read a bar chart where it states its values: the top edge of each bar.

    A bar is ink that runs unbroken from the baseline upwards, so the columns
    that do that are the bars and the height at which each stops is the datum.
    Nothing needs to be matched or recognised, and a figure with no such columns
    - every line chart - simply yields nothing here.
    """
    gray = markers.load_gray(image_path)
    inside, left, top = _crop(gray, plot_bbox)
    if inside.size == 0:
        return []
    ink = inside < markers.INK_LEVEL
    if not ink.any():
        return []
    pen = markers.stroke_radius(ink) or 1.
    height = ink.shape[0]
    # The baseline is the plot's own floor; a bar is ink standing on it.
    floor = height - 1
    while floor > 0 and not ink[floor].any():
        floor -= 1
    standing = np.zeros(ink.shape[1], int)
    for column in range(ink.shape[1]):
        row = floor
        while row >= 0 and ink[row, column]:
            row -= 1
        standing[column] = floor - row
    minimum_width = max(1, int(round(pen * 2 * BAR_WIDTH_IN_STROKES)))
    # A bar is taller than it is thick; ink only as tall as the pen is the axis.
    tall = standing > pen * 2 * BAR_WIDTH_IN_STROKES
    labelled, count = ndimage.label(tall)
    bars = []
    for index in range(1, count + 1):
        columns = np.where(labelled == index)[0]
        if columns.size < minimum_width:
            continue
        heights = standing[columns]
        # A drawn bar has one flat top; a ragged run of columns is a curve.
        if heights.max() - heights.min() > pen * 2:
            continue
        centre = float(left + columns.mean())
        crest = float(top + floor - float(np.median(heights)))
        bars.append({'x': centre, 'y': crest, 'method': 'bar_top',
                     'width': float(columns.size), 'height': float(np.median(heights)),
                     'bbox': [float(left + columns.min()), crest,
                              float(left + columns.max() + 1), float(top + floor)],
                     'bar_height_px': float(np.median(heights))})
    bars.sort(key=lambda b: b['x'])
    return bars


def on_curve(image_path, plot_bbox):
    """Follow the drawn curves and stop where they thicken: the markers sit there.

    A marker on a line chart is printed on its curve, so the curve leads to it.
    Scanning column by column, the ink of a curve is one pen stroke deep; where a
    marker is printed the same column is a body several strokes deep. Those
    thickenings are the marks, found without knowing their shape and without a
    legend, and they are reported with the curve they were found on.
    """
    gray = markers.load_gray(image_path)
    inside, left, top = _crop(gray, plot_bbox)
    if inside.size == 0:
        return []
    ink = inside < markers.INK_LEVEL
    if not ink.any():
        return []
    pen = markers.stroke_radius(ink) or 1.
    thick = np.zeros_like(ink)
    for column in range(ink.shape[1]):
        rows = np.where(ink[:, column])[0]
        if rows.size == 0:
            continue
        runs = np.split(rows, np.where(np.diff(rows) > 1)[0] + 1)
        for run in runs:
            if run.size >= pen * 2 * CURVE_BODY_IN_STROKES:
                thick[run, column] = True
    if not thick.any():
        return []
    minimum = max(2, int(round((pen * 2) ** 2)))
    found = []
    for mark in _bodies(thick, (left, top), 'curve', minimum):
        short, long = sorted((mark['width'], mark['height']))
        # A frame rule, an axis and an error bar's whisker are deep in one
        # direction and one stroke wide in the other; a mark is a body in both.
        if short < pen * 2 or long > short * CURVE_BODY_IN_STROKES:
            continue
        mark['stroke_px'] = float(pen * 2)
        found.append(mark)
    return found


def _cluster(pool, radius):
    """Group marks from different methods that landed on the same body."""
    clusters = []
    for mark in sorted(pool, key=lambda m: (m['x'], m['y'])):
        for cluster in clusters:
            if math.hypot(mark['x'] - cluster['x'], mark['y'] - cluster['y']) <= radius:
                cluster['members'].append(mark)
                count = len(cluster['members'])
                cluster['x'] += (mark['x'] - cluster['x']) / count
                cluster['y'] += (mark['y'] - cluster['y']) / count
                break
        else:
            clusters.append({'x': mark['x'], 'y': mark['y'], 'members': [mark]})
    out = []
    for cluster in clusters:
        methods = sorted({m['method'] for m in cluster['members']})
        sizes = [max(m.get('width', 0.), m.get('height', 0.)) for m in cluster['members']]
        out.append({'x': cluster['x'], 'y': cluster['y'], 'found_by': methods,
                    'method_count': len(methods),
                    'corroborated': len(methods) > 1,
                    'width': float(np.median(sizes)) if sizes else None,
                    'evidence': cluster['members']})
    out.sort(key=lambda m: (m['x'], m['y']))
    return out


def run_all(image_path, plot_bbox, template_bbox=None, outdir=None, methods=None):
    """Run every finder over the same plot at once and pool what they saw.

    The methods are independent and none is trusted over another here: each is
    given the same figure, and the report says which of them found each body.
    They are run in parallel because they share no state and the run is under a
    wall-clock budget.
    """
    work = {
        'thickness': lambda: markers.detect_marks(image_path, plot_bbox),
        'colour': lambda: by_colour(image_path, plot_bbox),
        'shape': lambda: by_shape(image_path, plot_bbox, template_bbox, outdir),
        'bar_top': lambda: bar_tops(image_path, plot_bbox),
        'curve': lambda: on_curve(image_path, plot_bbox),
        'glyph': lambda: glyphs.find(image_path, plot_bbox)['marks'],
    }
    if methods:
        work = {name: call for name, call in work.items() if name in methods}

    def attempt(name):
        try:
            found = work[name]()
        except Exception as error:  # a method that cannot read this figure is not fatal
            progress.emit('detector_method', method=name, count=0,
                          error=f'{type(error).__name__}: {error}')
            return name, {'marks': [], 'error': f'{type(error).__name__}: {error}'}
        for mark in found:
            mark.setdefault('method', name)
        progress.emit('detector_method', method=name, count=len(found),
                      marks=[{k: m.get(k) for k in ('x', 'y', 'width', 'height')}
                             for m in found[:400]])
        return name, {'marks': found, 'count': len(found)}

    with ThreadPoolExecutor(max_workers=len(work) or 1) as pool:
        reports = dict(pool.map(progress.bound(attempt), list(work)))
    everything = [m for report in reports.values() for m in report['marks']]
    sizes = [max(m.get('width') or 0., m.get('height') or 0.) for m in everything]
    sizes = [s for s in sizes if s > 0]
    mark_width = float(np.median(sizes)) if sizes else None
    radius = ((mark_width * CORROBORATION_FRACTION_OF_MARK) if mark_width
              else markers._length(markers.load_gray(image_path),
                                   markers.PLOT_MARKER_SIDE_FRACTION, floor=4))
    pooled = _cluster(everything, radius)
    return {'methods': reports, 'pooled': pooled,
            'mark_width_px': mark_width, 'corroboration_radius_px': float(radius),
            'counts': {name: len(report['marks']) for name, report in reports.items()},
            'corroborated': sum(1 for m in pooled if m['corroborated'])}
