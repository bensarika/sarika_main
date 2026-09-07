"""Find the plotted marks by the one thing a chart guarantees: they repeat.

A data mark is drawn from a stamp. Whatever it is - a hollow circle, a hatched
disc, a triangle, a filled dot on a line - the same stamp is pressed once per
observation, so the figure contains one size that occurs many times over. That
is what is measured here, and it is measured twice because a mark can be drawn
in two ways:

* standing free, where it is its own island of ink once the rules and gridlines
  are lifted off, and every island of the repeated size is a mark;
* sitting on a curve, where it is not an island at all but a swelling in a line,
  found as the places where the ink runs thicker than the figure's own pen.

Nothing here is a tuned pixel threshold: the pen width, the stamp size and the
spacing between marks are all measured off the figure being read.
"""
import numpy as np
from scipy import ndimage

from . import markers
from . import plot_frame

# A rule is a stroke crossing this much of the plot in one go; those are the
# frame and the gridlines, which are not marks and are lifted off first.
RULE_SHARE_OF_PLOT = .5
# Islands are the same stamp when their sizes agree this closely. A stamp
# printed at 300 dpi varies by a pixel or two on the scan, not by half.
SAME_STAMP = .45
# An island that big is not a mark; it is the curve network or the legend block.
STAMP_SHARE_OF_PLOT = .2
# Islands are compared shape to shape on a grid this many cells on a side, which
# is fine enough to tell a ring from a diamond and coarse enough that a pixel of
# scanner noise does not matter.
SHAPE_GRID = 12
# Two islands are the same stamp when their inked cells agree this well, and a
# stamp is only believed once this many islands agree with each other - a chart
# prints its marks over and over, a broken curve prints each fragment once.
SHAPE_AGREEMENT = .8
STAMPS_SEEN = 3
# A stamp is about as tall as it is wide and it is either solid or closed around
# something. A dash of a broken connector line repeats just as faithfully as a
# mark does, and this is what separates them: a dash lying flat is far wider than
# it is tall, and a dash lying at an angle fills almost none of its own box.
STAMP_SQUARENESS = .5
STAMP_SOLIDITY = .5
# Ink swells into a mark where it stands this many times further from the paper
# than the figure's own strokes do. A line cannot reach that on its own, not even
# where it doubles back on itself; a stamp printed on the line does.
SWELL_IN_STROKES = 3.
# Two marks printed over each other are told apart when their middles stand this
# much of a stamp's width away; a clump wider than this many stamps is a drawing,
# not a few marks that happen to overlap.
TOUCHING_APART = .5
MOST_IN_A_CLUMP = 3.
# A knot of ink where two rules cross is mostly made of the rules themselves; a
# mark that happens to sit on a gridline is mostly made of its own ink.
MOSTLY_RULE = .5
# Scaffolding drawn around the marks - a box round a group, a whisker - runs
# straight for this many stamps in a row, which no stamp does.
STRAIGHT_IN_STAMPS = 2.
MOSTLY_WHOLE = .5


def _rules_off(ink, straight=None):
    """The plot's ink with its frame and gridlines lifted off, and what was lifted.

    Whatever was drawn across a gridline is put back together afterwards: the
    gridline is a thin thing, so anything the lift interrupted is rejoined across
    it, and a curve stays one long curve instead of shattering into dozens of
    fragments that each look like a mark.

    A rule is a stroke that runs dead straight for longer than anything the plot
    draws. Before the figure has said how big its marks are that can only be
    judged against the plot's own width; once it has, a box drawn round a group
    or a whisker standing behind the marks is a rule too, and lifting those is
    what leaves the marks standing free.
    """
    kept = ink.copy()
    lifted = np.zeros_like(ink)
    height, width = ink.shape
    for axis, extent in ((1, width), (0, height)):
        least = (min(RULE_SHARE_OF_PLOT * extent, straight) if straight
                 else RULE_SHARE_OF_PLOT * extent)
        lines = ink if axis == 1 else ink.T
        for index, line in enumerate(lines):
            for start, stop in _long_runs(line, least):
                if axis == 1:
                    kept[index, start:stop] = False
                    lifted[index, start:stop] = True
                else:
                    kept[start:stop, index] = False
                    lifted[start:stop, index] = True
    if lifted.any() and kept.any():
        thickness = _thickness(lifted) or 1
        reached = ndimage.binary_dilation(kept, np.ones((3, 3), bool),
                                          iterations=int(thickness))
        kept = kept | (lifted & reached)
    return kept, lifted


def _long_runs(line, least):
    """Every unbroken stretch of ink in one line that runs at least that far."""
    edges = np.diff(np.concatenate(([0], line.view(np.int8), [0])))
    starts = np.flatnonzero(edges == 1)
    stops = np.flatnonzero(edges == -1)
    return [(int(start), int(stop)) for start, stop in zip(starts, stops)
            if stop - start >= least]


def _thickness(lifted):
    """How many pixels thick the removed rules are drawn.

    Measured across each rule rather than along it: a rule is a long thin thing,
    so its short side is the pen that drew it. The usual rule is taken, not the
    thickest, so one heavy axis does not speak for a plate of hairlines.
    """
    labelled, count = ndimage.label(lifted, structure=np.ones((3, 3), bool))
    if not count:
        return 0
    across = [min(rows.stop - rows.start, columns.stop - columns.start)
              for rows, columns in ndimage.find_objects(labelled)]
    return int(np.median(across))


def _stamp(sizes):
    """The size that repeats: the largest group of islands that agree in size.

    Ties go to the smaller group's size, since a chart's marks are smaller than
    its labels and the label block would otherwise win on a sparse plot.
    """
    ordered = sorted(sizes)
    best = None
    for size in ordered:
        group = [s for s in ordered if abs(s - size) <= SAME_STAMP * size]
        key = (len(group), -float(np.median(group)))
        if best is None or key > best[0]:
            best = (key, float(np.median(group)))
    return None if best is None else best[1]


def _print_of(patch):
    """An island reduced to a small grid, so two can be compared shape to shape."""
    rows = np.array_split(patch, min(SHAPE_GRID, patch.shape[0]), axis=0)
    cells = [np.array_split(r, min(SHAPE_GRID, patch.shape[1]), axis=1) for r in rows]
    grid = np.array([[c.any() for c in row] for row in cells], bool)
    padded = np.zeros((SHAPE_GRID, SHAPE_GRID), bool)
    padded[:grid.shape[0], :grid.shape[1]] = grid
    return padded


def shaped_like_a_stamp(patch):
    """Whether one island is shaped like something stamped, not like a dash."""
    height, width = patch.shape
    if min(height, width) < STAMP_SQUARENESS * max(height, width):
        return False
    if patch.mean() >= STAMP_SOLIDITY:
        return True
    # Closed around paper: the hollow circles, squares, diamonds and triangles.
    framed = np.zeros((height + 2, width + 2), bool)
    framed[1:-1, 1:-1] = patch
    outside = ndimage.binary_fill_holes(framed) & ~framed
    return bool(outside.any())


def repeated(marks):
    """Only the islands whose shape is printed again elsewhere on the plot.

    A stamp is used once per observation, so its shape recurs; a fragment of a
    curve left behind when the gridlines were lifted off is a one-off.
    """
    prints = [m['print'] for m in marks]
    agreement = np.zeros((len(marks), len(marks)))
    for i, first in enumerate(prints):
        for j, second in enumerate(prints):
            agreement[i, j] = (first == second).mean()
    kept = [m for m, row in zip(marks, agreement)
            if int((row >= SHAPE_AGREEMENT).sum()) >= STAMPS_SEEN]
    return kept


def islands(ink, offset, pen, lifted=None):
    """Free-standing marks: islands of ink of the size and shape that repeat.

    What was cut when the gridlines were lifted off is left behind as fragments
    of curve, and a fragment is recognisable by where it was cut: it ends on a
    line that was removed. A stamp printed in open paper does not.
    """
    labelled, count = ndimage.label(ink, structure=np.ones((3, 3), bool))
    if not count:
        return [], None
    height, width = ink.shape
    limit = STAMP_SHARE_OF_PLOT * max(height, width)
    # A stamp is several pen widths across; anything thinner is a crumb of a
    # stroke that a lifted gridline cut in two.
    floor = max(3., (pen or 1.) * 4.)
    cut = (ndimage.binary_dilation(lifted, np.ones((3, 3), bool))
           if lifted is not None else None)
    seen, clumps = [], []
    for index, (rows, columns) in enumerate(ndimage.find_objects(labelled), start=1):
        size = max(columns.stop - columns.start, rows.stop - rows.start)
        if size > limit or size < floor:
            continue
        patch = labelled[rows, columns] == index
        clumps.append((rows, columns, patch))
        if not shaped_like_a_stamp(patch):
            continue
        # A mark that a lifted gridline ran through is still a mark, but a stroke
        # cut by one is not: what tells them apart is that the mark is whole
        # everywhere else, which the shape test above has already asked.
        was_cut = bool(cut is not None and (patch & cut[rows, columns]).any())
        seen.append({'x': offset[0] + (columns.start + columns.stop) / 2.,
                     'y': offset[1] + (rows.start + rows.stop) / 2.,
                     'width': float(columns.stop - columns.start),
                     'height': float(rows.stop - rows.start), 'size': float(size),
                     'area': int(patch.sum()), 'cut_by_a_gridline': was_cut,
                     'print': _print_of(patch),
                     'method': 'stamp'})
    if not seen:
        return [], None
    stamp = _stamp([m['size'] for m in seen])
    if stamp is None:
        return [], None
    sized = [m for m in seen if abs(m['size'] - stamp) <= SAME_STAMP * stamp]
    kept = repeated(sized)
    # A size that repeats among crumbs is not a stamp: a stamp is a shape the
    # figure prints again and again, so unless whole islands of it were found the
    # plate is taken to have no stamp at all.
    if not kept:
        return [], None
    for mark in kept:
        mark.pop('print', None)
    kept.extend(touching_stamps(clumps, offset, stamp, lifted))
    return kept, stamp


def touching_stamps(clumps, offset, stamp, lifted=None):
    """Marks read out of a clump of marks printed on top of one another.

    Two marks that overlap make one island too big to be a stamp, but each still
    has a middle of its own: a point further from the clump's edge than anything
    around it, and the stamp's own width away from its neighbour's middle.
    """
    apart = max(2, int(stamp * TOUCHING_APART))
    found = []
    for rows, columns, patch in clumps:
        # Two rules crossing leave a knot of ink of about a mark's size with two
        # middles in it, which is a gridline junction and not a pair of marks.
        if lifted is not None and ((patch & lifted[rows, columns]).sum()
                                   > MOSTLY_RULE * patch.sum()):
            continue
        width = columns.stop - columns.start
        height = rows.stop - rows.start
        if max(width, height) <= stamp * (1 + SAME_STAMP):
            continue
        if max(width, height) > stamp * MOST_IN_A_CLUMP:
            continue
        solid = ndimage.binary_fill_holes(patch)
        deep = ndimage.distance_transform_edt(solid)
        middles = (deep == ndimage.maximum_filter(deep, apart)) & (deep >= stamp / 4.)
        if lifted is not None:
            # The middle of a knot of ink where two rules cross lies on the rules.
            middles &= ~lifted[rows, columns]
        marked, count = ndimage.label(middles, structure=np.ones((3, 3), bool))
        if count < 2:
            continue
        for row, column in ndimage.center_of_mass(middles, marked,
                                                  range(1, count + 1)):
            found.append({'x': offset[0] + columns.start + float(column),
                          'y': offset[1] + rows.start + float(row),
                          'width': stamp, 'height': stamp, 'size': float(stamp),
                          'area': int(solid.sum() / count), 'method': 'clump'})
    return found


def stroke_clearance(clearance, ink):
    """How far the middle of an ordinary stroke stands from the paper.

    Measured on the figure being read, from the ridge running down the middle of
    its own ink, so a thumbnail and a 300 dpi scan are judged the same way.
    """
    ridge = (clearance == ndimage.maximum_filter(clearance, 3)) & ink
    return float(np.median(clearance[ridge])) if ridge.any() else None


def swellings(ink, offset, lifted=None):
    """Marks drawn onto a curve: where the ink stands clear of the paper.

    A stroke is everywhere one pen wide, so its middle stands a fixed distance
    from the white. A mark stamped on top of it stands much further, and each
    mark gives one such place. As with free-standing marks, a swelling is only
    believed where the same swelling is printed again elsewhere: one lone thick
    spot is a line doubling back, not an observation.
    """
    if not ink.any():
        return []
    clearance = ndimage.distance_transform_edt(ink)
    stroke = stroke_clearance(clearance, ink)
    if not stroke:
        return []
    swollen = clearance >= stroke * SWELL_IN_STROKES
    if not swollen.any():
        return []
    labelled, count = ndimage.label(swollen, structure=np.ones((3, 3), bool))
    found = []
    across = stroke * SWELL_IN_STROKES * 2
    for index, (rows, columns) in enumerate(ndimage.find_objects(labelled), start=1):
        patch = labelled[rows, columns] == index
        # A mark that stands three strokes clear of the paper is at least six
        # strokes across; a shorter thick spot is a corner of the curve itself.
        if max(columns.stop - columns.start, rows.stop - rows.start) < across:
            continue
        # Where a gridline was rejoined to the curve crossing it, the join is
        # thick for the same reason a mark is, so a thick spot standing on a rule
        # is not read as a mark. A mark that happens to sit on a gridline is read
        # as an island instead, once the rule is lifted off it.
        if lifted is not None and (patch & lifted[rows, columns]).any():
            continue
        ys, xs = np.nonzero(patch)
        found.append({'x': offset[0] + columns.start + float(xs.mean()),
                      'y': offset[1] + rows.start + float(ys.mean()),
                      'width': float(columns.stop - columns.start),
                      'height': float(rows.stop - rows.start),
                      'size': float(max(columns.stop - columns.start,
                                        rows.stop - rows.start)),
                      'area': int(patch.sum()), 'method': 'swell'})
    # One thick spot is a line doubling back on itself; a plot's marks come in
    # numbers. Sizes are not compared here because a legend of six shapes prints
    # six different swellings, all of them marks.
    return found if len(found) >= STAMPS_SEEN else []


def gathered(swollen, apart):
    """One mark per group of thick spots, where a mark can raise more than one.

    A mark with a pattern printed in it - a cross-hatched circle, a square with a
    line through it - stands clear of the paper in several places at once, all of
    them within the mark's own width.
    """
    waiting = list(swollen)
    marks = []
    while waiting:
        group = [waiting.pop()]
        joined = True
        while joined:
            joined = False
            for other in list(waiting):
                if any(abs(other['x'] - m['x']) <= apart
                       and abs(other['y'] - m['y']) <= apart for m in group):
                    group.append(other)
                    waiting.remove(other)
                    joined = True
        marks.append({'x': float(np.mean([m['x'] for m in group])),
                      'y': float(np.mean([m['y'] for m in group])),
                      'width': float(np.mean([m['width'] for m in group])),
                      'height': float(np.mean([m['height'] for m in group])),
                      'size': float(max(m['size'] for m in group)),
                      'area': int(sum(m['area'] for m in group)),
                      'method': 'swell'})
    return marks


def _whole(marks):
    """How many of these marks stand clear of anything that was lifted off."""
    return sum(1 for mark in marks if not mark.get('cut_by_a_gridline'))


def find(image_path, plot_bbox):
    """Every mark the figure repeats, however it was drawn."""
    gray = markers.load_gray(image_path)
    left, top, right, bottom = (int(round(v)) for v in plot_bbox)
    inside = gray[max(0, top):bottom, max(0, left):right]
    if inside.size == 0:
        return {'marks': [], 'stamp_px': None, 'pen_px': None}
    return in_ink(inside < markers.INK_LEVEL,
                  (float(max(0, left)), float(max(0, top))))


def in_ink(ink, offset):
    """Every mark repeated in one sheet of ink, wherever that ink came from.

    Taken apart from find() so that a plate printed in colour can be read one
    colour at a time: a series' own ink is a sheet of its own, and read on its
    own it is not welded to the series drawn across it.
    """
    if not ink.any():
        return {'marks': [], 'stamp_px': None, 'pen_px': None,
                'free_standing': 0, 'on_a_curve': 0}
    pen = markers.stroke_radius(ink)
    bare, lifted = _rules_off(ink)
    free, stamp = islands(bare, offset, pen, lifted)
    # Once the figure has stated the size of its stamp, anything drawn straight
    # for several stamps in a row is scaffolding - the box round a group, a
    # whisker, a connector - and lifting that as well frees the marks welded to
    # it. Kept only where it finds more of the same stamp than the first pass:
    # on a plot with no scaffolding it has nothing to lift.
    straight = max(4., (pen or 1.) * STRAIGHT_IN_STAMPS * 4)
    best = _whole(free)
    while straight < RULE_SHARE_OF_PLOT * max(ink.shape):
        again, gone = _rules_off(ink, straight=straight)
        more, its_stamp = islands(again, offset, pen, gone)
        # Lifting shorter and shorter strokes eventually cuts the curves
        # themselves into look-alike crumbs, and a crumb betrays itself: it ends
        # where the stroke was cut. A pass is believed only while most of what it
        # finds stands whole in the paper, and only while it finds more of that
        # than the pass before it.
        whole = _whole(more)
        if whole > best and whole >= MOSTLY_WHOLE * len(more):
            bare, lifted, free, stamp, best = again, gone, more, its_stamp, whole
        straight *= STRAIGHT_IN_STAMPS
    # Thick spots belonging to one mark stand within the mark's own width of each
    # other. Where the figure prints a stamp somewhere, that width is known; where
    # it does not, the pen says how wide a mark has to be to swell at all.
    joined = gathered(swellings(bare, offset, lifted),
                      stamp / 2. if stamp else max(3., (pen or 1.) * 3.))
    # A mark found both ways is one mark: the swelling inside an island is that
    # island, so islands win where the two coincide.
    apart = stamp or (pen * 2 if pen else 1.)
    marks = list(free)
    for mark in joined:
        if all(abs(mark['x'] - m['x']) > apart or abs(mark['y'] - m['y']) > apart
               for m in free):
            marks.append(mark)
    marks.sort(key=lambda m: (m['x'], m['y']))
    return {'marks': marks, 'stamp_px': stamp, 'pen_px': pen,
            'free_standing': len(free), 'on_a_curve': len(marks) - len(free)}
