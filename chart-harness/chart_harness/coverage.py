"""Columns of the plot the reading never proposed anything in.

A candidate is only searched for beside a seed the reader gave, so a reading that
lists the first few sampling columns and stops leaves the rest of the plot
unexamined however well the points it did give sit on their marks. Python has
already measured mark-shaped bodies right across the plot box, and the ones
standing in a column no candidate occupies are places nobody looked.

Only those are carried in. Every measured body is not a datapoint - the finders
also catch error-bar caps and the ink where curves cross - so filling in from all
of them would trade a short reading for an inflated one. A column the reading
never reached is a hole in the work; a body inside a column it did read has
already been considered, and the screen and the reviewer own that decision.
"""
import statistics


def reach(marks, series=None):
    """How close a candidate must be to count as standing on a mark.

    The figure's own marks say how big a mark is; half that body is the distance
    within which one point and one mark are the same point, so a wider glyph on a
    larger scan carries a wider reach without anybody choosing a number.
    """
    widths = [float(m['width']) for m in marks or []
              if isinstance(m.get('width'), (int, float)) and m['width'] > 0]
    if not widths:
        boxes = [max(float(s['template_bbox'][2]) - float(s['template_bbox'][0]),
                     float(s['template_bbox'][3]) - float(s['template_bbox'][1]))
                 for s in series or [] if s.get('template_bbox')]
        if not boxes:
            return None
        return statistics.median(boxes) / 2.
    return statistics.median(widths) / 2.


def inside(mark, box):
    """Marks measured outside the plot the reader settled on are not its data."""
    if not box:
        return True
    left, top, right, bottom = [float(v) for v in box]
    return left <= float(mark['x']) <= right and top <= float(mark['y']) <= bottom


def columns(points, width):
    """Where the reading proposed anything, gathered into sampling columns.

    Marks of one timepoint share an x within a mark's own body; a wider gap than
    that is the next column, so the figure's own geometry sets the grouping.
    """
    xs = sorted(float(x) for x in points)
    if not xs or not width:
        return []
    found, run = [], [xs[0]]
    for x in xs[1:]:
        if x - run[-1] <= width:
            run.append(x)
        else:
            found.append(statistics.median(run))
            run = [x]
    found.append(statistics.median(run))
    return found


def step(found):
    """The reading's own column spacing, which says how wide a column is."""
    if len(found) < 2:
        return None
    return statistics.median([b - a for a, b in zip(found, found[1:])])


def unexamined(marks, candidates, width):
    """Measured marks standing where the reading proposed nothing at all.

    A mark nearer to some proposed column than to the middle of the gap between
    columns was inside work already done. Anything further out stands in a column
    of its own that nobody looked at.
    """
    if width is None:
        return []
    if not candidates:
        return list(marks or [])
    read = columns([c['pixel']['x'] for c in candidates], width)
    wide = step(read) or width
    return [m for m in marks or []
            if min(abs(float(m['x']) - c) for c in read) > wide / 2.]


def corroborated(marks):
    """More than one independent finder standing on the same body, where there is any."""
    agreed = [m for m in marks if (m.get('method_count') or 1) > 1]
    return agreed or list(marks)


def _extent(values):
    return (min(values), max(values)) if values else None


def span(marks, candidates, box=None):
    """How far across the plot the reading reached, against how far the ink goes.

    Stated as a share of the ink's own extent rather than of the box, because a
    plot box holds axis margins the data never occupies.
    """
    ink = _extent([float(m['x']) for m in marks or []])
    read = _extent([float(c['pixel']['x']) for c in candidates or []])
    if not ink or not read or ink[1] <= ink[0]:
        return None
    width = ink[1] - ink[0]
    return {'ink_from': ink[0], 'ink_to': ink[1],
            'proposals_from': read[0], 'proposals_to': read[1],
            'share_of_the_ink_covered': round(
                max(0., min(read[1], ink[1]) - max(read[0], ink[0])) / width, 3),
            'plot_bbox': [float(v) for v in box] if box else None}


def add(proposals, marks, within, series_ids):
    """Carry marks from unexamined columns into the candidates, group left open."""
    missed = corroborated(unexamined(marks, proposals.get('candidates'), within))
    if not missed:
        return []
    start = len(proposals.get('candidates') or [])
    added = []
    for index, mark in enumerate(sorted(missed, key=lambda m: (m['x'], m['y'])), start + 1):
        added.append({
            'candidate_id': 'm{n:04d}'.format(n=index),
            'pixel': {'x': float(mark['x']), 'y': float(mark['y'])},
            'possible_series': list(series_ids),
            'marker': 'blob', 'support': 'unrefined',
            'pixel_uncertainty': {'x': within, 'y': within,
                                  'kind': 'half_the_measured_mark_body',
                                  'confidence_interval': False},
            'diagnostics': {'method': 'detector_bank_coverage',
                            'found_by': mark.get('found_by'),
                            'method_count': mark.get('method_count'),
                            'width': mark.get('width'),
                            'reason': 'measured ink in a column the reading never reached',
                            'requires_visual_review': True}})
    proposals['candidates'] = (proposals.get('candidates') or []) + added
    proposals['candidates'].sort(key=lambda c: (c['pixel']['x'], c['pixel']['y']))
    if proposals.get('status') == 'unsupported':
        proposals['status'] = 'review_required'
    proposals.setdefault('diagnostics', []).append({
        'code': 'columns_the_reading_never_reached',
        'count': len(added), 'within_px': within})
    return added


def sentence(added, spanned):
    """What the coverage pass did, for the watcher's feed."""
    said = ''
    if spanned is not None:
        said = ('the reading\'s own points cover {p:.0%} of the width the ink occupies'
                .format(p=spanned['share_of_the_ink_covered']))
    if not added:
        return (said + '; it proposed something in every column ink was measured in') if said \
            else 'the reading proposed something in every column ink was measured in'
    more = ('{n} measured mark(s) stand in columns it never reached and were added as '
            'candidates, group left open for the reviewer'.format(n=len(added)))
    return said + '; ' + more if said else more
