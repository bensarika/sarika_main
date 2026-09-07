"""Read a series plot at the times it was sampled, by following its curves.

Where a study samples every antibody at the same hours, the figure stacks all of
that hour's marks into one narrow column, and the marks in a column are printed
on top of one another and welded together by their error bars. Nothing can be
told apart inside such a column by looking at it.

What can be told apart is what happens between two columns: there the curves run
in open paper, one strand of ink each. So the strands are followed through the
clear stretch and carried into the column they are heading for, and where the
strand arrives there is a mark - confirmed on the figure's own ink before it is
kept. One strand per series per column is exactly the reading the chart states,
and it comes with the series identity attached, since the strand that leaves a
column is the strand that arrived.

Every length here is measured off the figure: the pen it is drawn with, the
spacing of its own columns, the length of the clear stretch between them.
"""
import numpy as np

from . import glyphs
from . import markers

# A sampling column carries the marks of every series at once plus their error
# bars, so it holds this many times the ink an ordinary column of the plot does.
COLUMN_INK = 3.
# Columns nearer than this share of the plot's width are one column drawn wide.
COLUMNS_APART = .01
# The clear stretch between two columns is entered this far in, to stand clear
# of the error-bar caps, measured as a share of the distance between them.
CLEAR_OF_A_COLUMN = .2
# A strand is followed from one pixel column to the next while it stays within
# this many pen widths, and it survives this share of the stretch being blank -
# a dashed curve is blank for a good part of its length.
STRAND_STEP_IN_PENS = 4.
STRAND_MAY_BE_BLANK = .15
# A strand is believed once it has been followed across this much of the clear
# stretch; anything shorter is a fragment of an error bar or a label.
STRAND_SPAN = .5
# The strand is carried into the column along the direction of its last stretch,
# measured over this share of it.
STRAND_AIM = .3
# Two strands arriving at the same place are one series: the curves have merged.
ARRIVE_APART_IN_PENS = 2.
# A mark is only kept where the column has ink within this many pens of where
# the strand says it should be.
CONFIRM_IN_PENS = 3.


def _runs(line, most):
    """The middles of the unbroken stretches of ink in one pixel column."""
    found, start = [], None
    for index, on in enumerate(line):
        if on and start is None:
            start = index
        elif not on and start is not None:
            if index - start <= most:
                found.append((start + index - 1) / 2.)
            start = None
    if start is not None and len(line) - start <= most:
        found.append((start + len(line) - 1) / 2.)
    return found


def sampling_columns(ink):
    """Where the figure stacks every series' mark: its sampling times."""
    profile = ink.sum(0)
    ordinary = float(np.median(profile))
    if ordinary <= 0:
        return []
    apart = max(2, int(COLUMNS_APART * ink.shape[1]))
    standing = np.nonzero(profile >= ordinary * COLUMN_INK)[0]
    grouped = []
    for index in standing:
        if grouped and index - grouped[-1][-1] <= apart:
            grouped[-1].append(index)
        else:
            grouped.append([index])
    return [float(np.mean(group)) for group in grouped]


def follow(ink, first, last, pen):
    """Every strand of ink running through a clear stretch of the plot."""
    step = max(2., pen * STRAND_STEP_IN_PENS)
    blank = max(2, int((last - first) * STRAND_MAY_BE_BLANK))
    most = max(3, int(pen * 6))
    live, done = [], []
    for x in range(first, last):
        centres = _runs(ink[:, x], most)
        taken = set()
        for strand in live:
            if not centres:
                continue
            near = min(range(len(centres)),
                       key=lambda i: abs(centres[i] - strand['at']))
            if near in taken or abs(centres[near] - strand['at']) > step:
                continue
            taken.add(near)
            strand['points'].append((float(x), centres[near]))
            strand['at'] = centres[near]
        for strand in list(live):
            if strand['points'][-1][0] != x:
                if x - strand['points'][-1][0] > blank:
                    live.remove(strand)
                    done.append(strand)
        for index, centre in enumerate(centres):
            if index not in taken:
                live.append({'at': centre, 'points': [(float(x), centre)]})
    spanning = [s for s in done + live
                if s['points'][-1][0] - s['points'][0][0]
                >= (last - first) * STRAND_SPAN]
    # A rule the lift could not take off - a baseline, a frame drawn inside the
    # plot - runs dead level all the way across. A curve does not.
    return [s for s in spanning
            if np.ptp([y for _, y in s['points']]) > pen or len(spanning) == 1]


def aim(strand, towards):
    """Where a strand is heading when it reaches the column in front of it."""
    points = strand['points']
    if towards >= points[-1][0]:
        stretch = points[max(0, int(len(points) * (1 - STRAND_AIM))):]
    else:
        stretch = points[:max(2, int(len(points) * STRAND_AIM))]
    xs = np.array([x for x, _ in stretch])
    ys = np.array([y for _, y in stretch])
    if len(xs) < 2 or np.ptp(xs) == 0:
        return float(ys.mean())
    slope, intercept = np.polyfit(xs, ys, 1)
    return float(slope * towards + intercept)


def _confirm(ink, x, y, pen):
    """The ink nearest a place a strand points at, if the column has any there."""
    reach = max(2, int(pen * CONFIRM_IN_PENS))
    column = int(round(x))
    if not 0 <= column < ink.shape[1]:
        return None
    low = max(0, int(round(y)) - reach)
    high = min(ink.shape[0], int(round(y)) + reach + 1)
    there = np.nonzero(ink[low:high, column])[0]
    return float(low + there[int(len(there) / 2)]) if len(there) else None


def crossing(image_path, plot_bbox):
    """How many strands of ink run right across the plot: how many curves it draws.

    A plate that stamps a glyph per observation draws none; a study's time course
    draws one per series, and that is what says the marks in its columns belong
    to curves rather than standing on their own.
    """
    gray = markers.load_gray(image_path)
    left, top, right, bottom = (int(round(v)) for v in plot_bbox)
    inside = gray[max(0, top):bottom, max(0, left):right]
    if inside.size == 0:
        return 0
    ink = inside < markers.INK_LEVEL
    pen = markers.stroke_radius(ink) or 1.
    bare, _ = glyphs._rules_off(ink)
    return len(follow(bare, 0, bare.shape[1], pen))


def read(image_path, plot_bbox):
    """The marks of a series plot, read where its curves meet its sampling times."""
    gray = markers.load_gray(image_path)
    left, top, right, bottom = (int(round(v)) for v in plot_bbox)
    inside = gray[max(0, top):bottom, max(0, left):right]
    if inside.size == 0:
        return {'marks': [], 'columns': [], 'series': 0}
    ink = inside < markers.INK_LEVEL
    pen = markers.stroke_radius(ink) or 1.
    bare, _ = glyphs._rules_off(ink)
    columns = sampling_columns(bare)
    if len(columns) < 2:
        return {'marks': [], 'columns': columns, 'series': 0}
    offset = (float(max(0, left)), float(max(0, top)))
    arrivals = {column: [] for column in columns}
    counted = []
    for before, after in zip(columns, columns[1:]):
        clear = (after - before) * CLEAR_OF_A_COLUMN
        first, last = int(before + clear), int(after - clear)
        if last - first < 4:
            continue
        strands = follow(bare, first, last, pen)
        counted.append(len(strands))
        for strand in strands:
            for column in (before, after):
                arrivals[column].append(aim(strand, column))
    marks = []
    apart = max(2., pen * ARRIVE_APART_IN_PENS)
    for column, wanted in arrivals.items():
        kept = []
        for y in sorted(wanted):
            here = _confirm(bare, column, y, pen)
            if here is None or any(abs(here - k) <= apart for k in kept):
                continue
            kept.append(here)
            marks.append({'x': offset[0] + column, 'y': offset[1] + here,
                          'width': pen * 2, 'height': pen * 2,
                          'size': float(pen * 2), 'area': int(pen * pen),
                          'method': 'column'})
    marks.sort(key=lambda mark: (mark['x'], mark['y']))
    return {'marks': marks, 'columns': [offset[0] + c for c in columns],
            'series': int(max(counted)) if counted else 0}
