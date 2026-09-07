"""Hold the kept marks against the curves they are supposed to be printed on.

A marker on a line chart is drawn on its curve. Two things follow, and both are
measurable on the page without asking anyone: a mark that sits on no drawn
stroke is probably a tick label or a stray body rather than an observation, and
a curve that carries no mark at all means a whole group went unread.

Neither is decided by argument. The pen's own thickness sets what "on" means,
the strokes are the ink the page actually contains, and what this module reports
is a measurement with the distance that produced it, for the run to hold itself
to review on.
"""
import math

import numpy as np
from scipy import ndimage

from . import markers

# A stroke has to run this many times its own thickness before it is a curve
# rather than a letter, a tick or a whisker. It is stated in strokes because
# that is the only length the page itself supplies.
CURVE_LENGTH_IN_STROKES = 6.
# A frame rule spans nearly the whole plot in one direction and stays a stroke
# deep in the other. Anything that fills this much of the box that way is the
# axis, not a series.
FRAME_SPAN_FRACTION = .9


def _series(point):
    """Whatever the stage that made this point called its group."""
    return point.get('series') if point.get('series') is not None else point.get('series_id')


def _strokes(image_path, plot_bbox):
    gray = markers.load_gray(image_path)
    left, top, right, bottom = (int(round(v)) for v in plot_bbox)
    left, top = max(0, left), max(0, top)
    inside = gray[top:bottom, left:right]
    if inside.size == 0:
        return None, None, 0., (left, top)
    ink = inside < markers.INK_LEVEL
    if not ink.any():
        return None, None, 0., (left, top)
    pen = float(markers.stroke_radius(ink) or 1.) * 2
    labelled, count = ndimage.label(ink, structure=np.ones((3, 3)))
    return labelled, count, pen, (left, top)


def check(image_path, plot_bbox, points, mark_width=None):
    """Measure each point's distance to the nearest drawn curve, and each curve's marks.

    ``points`` are dicts carrying ``pixel_x``/``pixel_y`` in the working image's
    pixels. The tolerance is the mark's own width where one was measured, and the
    pen's thickness otherwise: a mark is on its curve when its body touches it.
    """
    labelled, count, pen, (left, top) = _strokes(image_path, plot_bbox)
    if labelled is None or not count:
        return {'available': False, 'reason': 'no ink inside the plot box',
                'points': [], 'curves': [], 'off_curve': 0, 'unsampled_curves': []}
    height, width = labelled.shape
    tolerance = float(mark_width) if mark_width else pen
    curves = {}
    for index, (rows, columns) in enumerate(ndimage.find_objects(labelled), start=1):
        span_x, span_y = columns.stop - columns.start, rows.stop - rows.start
        long_side, short_side = max(span_x, span_y), min(span_x, span_y)
        if long_side < pen * CURVE_LENGTH_IN_STROKES:
            continue  # a letter, a tick, a whisker: too short to be a series
        frame = (short_side <= pen * 2 and
                 (span_x >= width * FRAME_SPAN_FRACTION or span_y >= height * FRAME_SPAN_FRACTION))
        if frame:
            continue  # the axis rules are drawn, but nothing is sampled off them
        curves[index] = {'curve_id': int(index),
                         'bbox': [float(left + columns.start), float(top + rows.start),
                                  float(left + columns.stop), float(top + rows.stop)],
                         'length_px': float(long_side), 'points': 0}
    # Distance from every pixel to the nearest curve ink, and which curve that is.
    wanted = np.isin(labelled, list(curves)) if curves else np.zeros_like(labelled, dtype=bool)
    if wanted.any():
        distance, nearest = ndimage.distance_transform_edt(~wanted, return_indices=True)
    else:
        distance, nearest = None, None
    measured = []
    for point in points:
        x, y = point.get('pixel_x'), point.get('pixel_y')
        if x is None or y is None or distance is None:
            measured.append({'candidate_id': point.get('candidate_id'),
                             'series': _series(point),
                             'on_curve': None, 'reason': 'no pixels to measure against'})
            continue
        column = min(max(int(round(x)) - left, 0), width - 1)
        row = min(max(int(round(y)) - top, 0), height - 1)
        gap = float(distance[row, column])
        curve_id = int(labelled[nearest[0][row, column], nearest[1][row, column]])
        on = gap <= tolerance
        if on and curve_id in curves:
            curves[curve_id]['points'] += 1
        measured.append({'candidate_id': point.get('candidate_id'), 'series': _series(point),
                         'on_curve': on, 'distance_px': gap,
                         'curve_id': curve_id if on else None,
                         'tolerance_px': tolerance})
    unsampled = [c for c in curves.values() if not c['points']]
    return {'available': True, 'points': measured, 'curves': sorted(
                curves.values(), key=lambda c: -c['length_px']),
            'off_curve': sum(1 for m in measured if m.get('on_curve') is False),
            'unsampled_curves': sorted(unsampled, key=lambda c: -c['length_px']),
            'tolerance_px': tolerance, 'stroke_px': pen,
            'basis': "the figure's own pen thickness and the measured width of its marks"}


def advice(report):
    """What to say to a reader about the marks that missed and the curves that got none."""
    if not report.get('available'):
        return ''
    said = []
    off = [m for m in report['points'] if m.get('on_curve') is False]
    if off:
        said.append('{n} kept mark(s) sit off every drawn curve by up to {d:.0f}px '
                    '(a mark is drawn on its curve, so these are likely labels or '
                    'stray bodies)'.format(n=len(off),
                                           d=max(m['distance_px'] for m in off)))
    for curve in report['unsampled_curves'][:6]:
        said.append('a curve {l:.0f}px long between x={a:.0f} and x={b:.0f} carries no '
                    'mark at all; look along it'.format(l=curve['length_px'],
                                                        a=curve['bbox'][0], b=curve['bbox'][2]))
    return '; '.join(said)


def columns(points, tolerance):
    """Group kept marks into the sampling times they share.

    Every series is measured at the same times, so the marks stand in columns.
    Grouping them says two useful things about a crowded plot: two marks of one
    series in a single column cannot both be right, and a series missing from a
    column that the others all appear in is a place to look.
    """
    ordered = sorted((p for p in points if p.get('pixel_x') is not None),
                     key=lambda p: p['pixel_x'])
    groups = []
    for point in ordered:
        if groups and point['pixel_x'] - groups[-1]['members'][-1]['pixel_x'] <= tolerance:
            groups[-1]['members'].append(point)
        else:
            groups.append({'members': [point]})
    out = []
    for index, group in enumerate(groups):
        members = sorted(group['members'], key=lambda p: p.get('pixel_y') or 0.)
        seen = {}
        for member in members:
            seen.setdefault(_series(member), []).append(member)
        out.append({'column': index,
                    'pixel_x': float(np.mean([m['pixel_x'] for m in members])),
                    'members': members,
                    'series_order': [_series(m) for m in members],
                    'doubled': sorted(s for s, m in seen.items() if s is not None and len(m) > 1)})
    return out


def crossings(columns_report):
    """Series pairs whose vertical order swaps from one sampling time to the next."""
    swapped = set()
    for first, second in zip(columns_report, columns_report[1:]):
        a = [s for s in first['series_order'] if s in second['series_order']]
        b = [s for s in second['series_order'] if s in first['series_order']]
        for i, left in enumerate(a):
            for right in a[i + 1:]:
                if b.index(left) > b.index(right):
                    swapped.add(tuple(sorted((str(left), str(right)))))
    return sorted(swapped)


def gaps_in_columns(columns_report, expected_series):
    """Where a series is absent from a column its neighbours all appear in.

    Where no two series cross, the vertical order holds from one column to the
    next, so the missing mark's neighbours in that order say between which two
    marks it must lie. That is a place to look on the page - never a point.
    """
    crossed = set(s for pair in crossings(columns_report) for s in pair)
    holes = []
    for column in columns_report:
        present = [s for s in column['series_order'] if s is not None]
        missing = [s for s in expected_series if s not in present]
        if not missing or not present:
            continue
        for series in missing:
            entry = {'column': column['column'], 'pixel_x': column['pixel_x'],
                     'series': series, 'between': None}
            if str(series) not in crossed:
                # Its place in the order elsewhere brackets where it belongs here.
                order = _typical_order(columns_report)
                if series in order:
                    at = order.index(series)
                    above = next((s for s in reversed(order[:at]) if s in present), None)
                    below = next((s for s in order[at + 1:] if s in present), None)
                    ys = {_series(m): m.get('pixel_y') for m in column['members']}
                    entry['between'] = {'above': above, 'below': below,
                                        'pixel_y_above': ys.get(above),
                                        'pixel_y_below': ys.get(below)}
            holes.append(entry)
    return holes


def _typical_order(columns_report):
    """The vertical order the series keep across the columns, top to bottom."""
    rank = {}
    for column in columns_report:
        for position, series in enumerate(column['series_order']):
            if series is None:
                continue
            rank.setdefault(series, []).append(position / max(1, len(column['series_order']) - 1))
    return [s for s, _ in sorted(rank.items(), key=lambda kv: sum(kv[1]) / len(kv[1]))]


def column_tolerance(points, mark_width=None):
    """How close two marks must stand in x to be the same sampling time.

    Half the smallest step between distinct columns of marks, or the mark's own
    width where the marks give no spacing to measure.
    """
    xs = sorted({round(float(p['pixel_x']), 3) for p in points if p.get('pixel_x') is not None})
    steps = [b - a for a, b in zip(xs, xs[1:]) if b - a > 0]
    if mark_width and steps:
        wide = [s for s in steps if s > mark_width]
        if wide:
            return float(min(min(wide) / 2., max(mark_width, min(steps))))
    if mark_width:
        return float(mark_width)
    return float(np.median(steps) / 2.) if steps else 1.
