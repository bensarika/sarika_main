"""Move a reader's panel box off the ink it cuts through.

A panel box is marked on a downscaled view, so its edges land a few pixels
inside the drawing and clip the last tick, the axis rule, or the final sampling
column - and everything downstream then works on a plot with a piece missing.
Where an edge cuts printed ink it is not a boundary at all, so each edge is
carried outward until it stands in blank paper. Blank runs no wider than the
widest one the box already contains are the figure's own white space and are
crossed; anything wider is the gutter that separates this panel from the rest of
the sheet, and the edge stops there.
"""
import numpy as np

from . import markers


def _widest_blank(flags) -> int:
    """The widest run of empty lines inside the box: this figure's white space."""
    if not len(flags):
        return 0
    padded = np.concatenate(([False], ~np.asarray(flags, dtype=bool), [False]))
    edges = np.flatnonzero(padded[1:] != padded[:-1])
    runs = list(zip(edges[0::2].tolist(), edges[1::2].tolist()))
    return max((stop - start for start, stop in runs), default=0)


def _outward(flags, edge: int, tolerance: int) -> int:
    """An edge that cuts ink, carried forward to the far side of that ink."""
    count = len(flags)
    if not 0 < edge < count or not (flags[edge] and flags[edge - 1]):
        return edge
    position, settled, blank = edge, edge, 0
    while position < count:
        if flags[position]:
            position += 1
            settled = position
            blank = 0
            continue
        blank += 1
        if blank > tolerance:
            break
        position += 1
    return settled


def widen(image_path, box):
    """The box grown off the ink, and a note when it had to move."""
    left, top, right, bottom = (int(round(float(v))) for v in box)
    mask = markers.load_gray(image_path) < markers.INK_LEVEL
    height, width = mask.shape
    left, top = max(0, left), max(0, top)
    right, bottom = min(width, right), min(height, bottom)
    if right - left < 2 or bottom - top < 2:
        return [float(v) for v in box], None
    columns = mask[top:bottom].any(axis=0)
    rows = mask[:, left:right].any(axis=1)
    across = _widest_blank(columns[left:right])
    down = _widest_blank(rows[top:bottom])
    grown = [
        width - _outward(columns[::-1], width - left, across),
        height - _outward(rows[::-1], height - top, down),
        _outward(columns, right, across),
        _outward(rows, bottom, down),
    ]
    if grown == [left, top, right, bottom]:
        return [float(v) for v in box], None
    note = {'code': 'panel_box_grown_off_the_ink',
            'from': [left, top, right, bottom], 'to': grown,
            'moved': [left - grown[0], top - grown[1],
                      grown[2] - right, grown[3] - bottom],
            'white_space_px': {'across': across, 'down': down}}
    return [float(v) for v in grown], note
