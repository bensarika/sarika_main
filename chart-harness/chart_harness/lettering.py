"""Find the writing printed inside a plot, so it is not read as data.

Figures label their own plots: a note beside an arm of the study, the name of a
series written next to its curve, a panel letter in a corner. Those letters are
small dark shapes standing in open paper, which is exactly what a marker is, and
the mark finders pick them up.

Writing gives itself away by how it is set rather than by what it says. Letters
stand in a row on a common baseline, they are packed closer together than marks
on a plot ever are, and - unlike a stamp, which is one shape printed over and
over - they are all different sizes. A row with those three properties is read
as writing and whatever stands in it is not data.
"""
import numpy as np
from scipy import ndimage

from . import glyphs, markers

# A row has to hold this many shapes to be writing rather than a few marks that
# happen to line up.
LETTERS_IN_A_ROW = 4
# Letters sit within this share of their own height of one another, measured
# from the middle of each shape.
ALIGNED = .6
# Neighbouring letters stand no further apart than this many of their own widths.
LETTERS_APART = 1.5
# Writing is set in shapes of differing size; a stamp repeats one size. Spread is
# measured as the range of the shapes' sizes over their usual size.
SIZES_DIFFER = .5
# A shape taller than this share of the plot is drawing, not writing.
TALL = .25
# Ink joined up across this share of the plot is a curve, and whatever hangs off
# it - a marker, an error bar - is part of the drawing however letter-like it looks.
DRAWN_ACROSS = .2


def _drawing(ink):
    """The ink belonging to something drawn right across the plot.

    Writing stands free on the paper; a marker is welded to its curve and its
    error bar, and that whole run of ink reaches across the plate. So anything
    joined to a long run is drawing, whatever its own shape looks like.
    """
    labelled, count = ndimage.label(ink, structure=np.ones((3, 3), bool))
    if not count:
        return np.zeros(ink.shape, bool)
    reach = DRAWN_ACROSS * max(ink.shape[1], ink.shape[0])
    long_runs = [
        index for index, box in enumerate(ndimage.find_objects(labelled), start=1)
        if max(box[1].stop - box[1].start, box[0].stop - box[0].start) >= reach
    ]
    if not long_runs:
        return np.zeros(ink.shape, bool)
    return np.isin(labelled, long_runs)


def _shapes(ink):
    """Every separate shape in the ink, as (left, top, right, bottom)."""
    labelled, count = ndimage.label(ink, structure=np.ones((3, 3), bool))
    if not count:
        return []
    return [(columns.start, rows.start, columns.stop, rows.stop)
            for rows, columns in ndimage.find_objects(labelled)]


def _rows(shapes):
    """The shapes gathered into the rows they are set in.

    Gathered on where each shape sits rather than on its baseline: a marker's
    error bar hangs below it, so bottoms wander, while everything in one line of
    a plot's writing stands at much the same height on the plate.
    """
    standing = sorted(shapes, key=lambda s: ((s[1] + s[3]) / 2., s[0]))
    rows, current = [], []
    for shape in standing:
        if current:
            last = current[-1]
            near = ALIGNED * max(shape[3] - shape[1], last[3] - last[1])
            if (shape[1] + shape[3]) / 2. - (last[1] + last[3]) / 2. > near:
                rows.append(current)
                current = []
        current.append(shape)
    if current:
        rows.append(current)
    return [sorted(row, key=lambda s: s[0]) for row in rows]


def _is_writing(row, plot_height):
    """Whether a row of shapes reads as writing."""
    if len(row) < LETTERS_IN_A_ROW:
        return False
    widths = [s[2] - s[0] for s in row]
    heights = [s[3] - s[1] for s in row]
    if max(heights) > TALL * plot_height:
        return False
    sizes = [max(w, h) for w, h in zip(widths, heights)]
    usual = float(np.median(sizes))
    if usual <= 0 or (max(sizes) - min(sizes)) < SIZES_DIFFER * usual:
        return False
    gaps = [row[i + 1][0] - row[i][2] for i in range(len(row) - 1)]
    return bool(gaps) and float(np.median(gaps)) <= LETTERS_APART * float(np.median(widths))


def blocks(image_path, plot_bbox):
    """The boxes of the letters printed inside the plot.

    One box per letter rather than one per line of writing: a note written across
    a plot is mostly the white space between its words, and a mark standing in
    that white space is a mark like any other.
    """
    gray = markers.load_gray(image_path)
    left, top, right, bottom = (int(round(v)) for v in plot_bbox)
    inside = gray[max(0, top):bottom, max(0, left):right]
    if inside.size == 0:
        return []
    ink = inside < markers.INK_LEVEL
    bare, _ = glyphs._rules_off(ink)
    drawn = _drawing(ink)
    offset = (float(max(0, left)), float(max(0, top)))
    standing = [shape for shape in _shapes(bare)
                if not drawn[shape[1]:shape[3], shape[0]:shape[2]].any()]
    found = []
    for row in _rows(standing):
        if not _is_writing(row, inside.shape[0]):
            continue
        found.extend([offset[0] + shape[0], offset[1] + shape[1],
                      offset[0] + shape[2], offset[1] + shape[3]]
                     for shape in row)
    return found


def clear_of(marks, written):
    """The marks that do not stand in a letter."""
    return [mark for mark in marks
            if not any(box[0] <= mark['x'] <= box[2] and box[1] <= mark['y'] <= box[3]
                       for box in written)]
