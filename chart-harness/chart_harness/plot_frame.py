"""Measure the plot frame from the straight rules the figure prints.

The tick-based box asked which single row and column carried the most ink, which
on a gridded chart is a gridline in the middle of the plot and on a chart whose
labels are heavy is the label column. What a plot actually stands in is its
rules: long unbroken strokes, one or two horizontal and one or two vertical. A
rule's own length says how far the plot runs the other way, so an L-shaped pair
of axes gives the whole box without any tick reading at all.
"""
import numpy as np
from PIL import Image

DARK = 128
# A rule is one of the longest strokes the figure draws in that direction. The
# comparison is against the figure's own longest stroke, because a sheet holding
# a legend and a caption gives the plot only part of its width, and against the
# page as well, so a letter's stem in a figure with no axes is not promoted.
RULE_SHARE_OF_LONGEST = 0.6
RULE_MIN_SHARE_OF_EXTENT = 0.2


def _binary(image_path):
    with Image.open(image_path) as source:
        return np.asarray(source.convert('L')) < DARK


def _longest_run(line):
    """Length and bounds of the longest unbroken dark stretch in one line."""
    padded = np.concatenate(([False], line, [False]))
    edges = np.flatnonzero(padded[1:] != padded[:-1])
    if not len(edges):
        return 0, 0, 0
    starts, stops = edges[0::2], edges[1::2]
    lengths = stops - starts
    best = int(np.argmax(lengths))
    return int(lengths[best]), int(starts[best]), int(stops[best])


def _rules(mask, along):
    """Straight rules running along an axis, merged where they are drawn thick.

    Returns (position, start, stop) with position the middle of the stroke and
    start/stop its reach in the other direction.
    """
    lines = mask if along == 'rows' else mask.T
    extent = lines.shape[1]
    runs = [_longest_run(line) for line in lines]
    longest = max((r[0] for r in runs), default=0)
    if longest < RULE_MIN_SHARE_OF_EXTENT * extent:
        return []
    minimum = RULE_SHARE_OF_LONGEST * longest
    measured = [(index, start, stop) for index, (length, start, stop) in enumerate(runs)
                if length >= minimum]
    grouped, run = [], []
    for entry in measured:
        if run and entry[0] - run[-1][0] > 1:
            grouped.append(run)
            run = []
        run.append(entry)
    if run:
        grouped.append(run)
    return [((group[0][0] + group[-1][0]) / 2.0,
             min(g[1] for g in group), max(g[2] for g in group))
            for group in grouped]


def frame(image_path, mask=None):
    """The box the plot is drawn in, measured from its rules.

    None when the figure prints no rule long enough to be an axis, which is the
    honest answer for a drawing with no axes at all.
    """
    mask = _binary(image_path) if mask is None else mask
    across = _rules(mask, 'rows')
    upright = _rules(mask, 'cols')
    if not across and not upright:
        return None
    top = bottom = left = right = None
    if across:
        top, bottom = across[0][0], across[-1][0]
        left, right = min(a[1] for a in across), max(a[2] for a in across)
    if upright:
        first, last = upright[0][0], upright[-1][0]
        left = first if left is None else min(left, first)
        right = last if right is None else max(right, last)
        reach_top = min(u[1] for u in upright)
        reach_bottom = max(u[2] for u in upright)
        top = reach_top if top is None else min(top, reach_top)
        bottom = reach_bottom if bottom is None else max(bottom, reach_bottom)
    if right - left < 2 or bottom - top < 2:
        return None
    return {'box': [float(left), float(top), float(right), float(bottom)],
            'rules_across': len(across), 'rules_upright': len(upright),
            'measured_from': 'the straight rules printed on the figure'}


def box(image_path, mask=None):
    found = frame(image_path, mask)
    return found['box'] if found else None
