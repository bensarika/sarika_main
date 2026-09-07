"""How many marks a series is missing, judged by the spacing of the ones it kept.

A sampled series is printed at a rhythm: the observations sit at the times the
study measured, so along the axis the accepted marks fall roughly a step apart.
Where two neighbours sit several steps apart, the figure almost certainly prints
marks in between that the run failed to keep, and the count of them follows from
the jump divided by the step. That estimate is what turns a short series into a
correctable one: the run can say where it expects a mark, look there in the
pixels, and either recover it or report the hole instead of passing silently.

Nothing here invents an observation. A predicted position is a place to look; it
only becomes a point if a finder already located ink there, and the caller still
puts anything recovered through the same screen as every other candidate.
"""
import numpy as np

# A jump counts as a hole once it is at least this many steps long. Half a step
# of slack absorbs the ordinary unevenness of a sampling schedule (a 4 h and a
# 6 h draw are not the same distance apart) without swallowing a missing mark.
HOLE_IN_STEPS = 1.5


def step(positions):
    """The rhythm of this series: the distance one sampling interval spans.

    Averaging the neighbour distances would fold the very jumps this exists to
    find into the step and so hide them. Instead every observed distance is a
    candidate rhythm, and the one kept is the rhythm that explains all the others
    as whole numbers of itself - which is what a sampling schedule with marks
    missing from it looks like. Ties go to the longest such rhythm, so a series
    read cleanly is not credited with marks between the ones it has.
    """
    ordered = sorted(float(p) for p in positions)
    if len(ordered) < 2:
        return None
    deltas = [d for d in np.diff(ordered) if d > 0]
    if not deltas:
        return None
    best, best_score = None, None
    for candidate in sorted(set(deltas)):
        multiples = [d / candidate for d in deltas]
        if any(round(m) < 1 for m in multiples):
            continue  # a rhythm longer than a distance the series actually shows
        score = float(np.mean([abs(m - round(m)) for m in multiples]))
        if best_score is None or score < best_score or (
                score == best_score and candidate > best):
            best, best_score = candidate, score
    return best if best is not None else float(min(deltas))


def holes(points, spacing=None):
    """Where this series looks short, and how many marks each hole should hold.

    Points are dicts with 'x' and 'y' in pixels. Each hole reports the neighbours
    it lies between, how many steps wide it is, and one predicted position per
    missing mark, interpolated along the segment the two neighbours define.
    """
    ordered = sorted(({'x': float(p['x']), 'y': float(p['y'])} for p in points),
                     key=lambda p: p['x'])
    spacing = spacing or step([p['x'] for p in ordered])
    if not spacing:
        return []
    found = []
    for before, after in zip(ordered, ordered[1:]):
        span = after['x'] - before['x']
        steps = span / spacing
        if steps < HOLE_IN_STEPS:
            continue
        missing = int(round(steps)) - 1
        if missing < 1:
            continue
        predicted = []
        for index in range(1, missing + 1):
            share = index / (missing + 1)
            predicted.append({'x': before['x'] + span * share,
                              'y': before['y'] + (after['y'] - before['y']) * share})
        found.append({'after': before, 'before': after, 'span_px': span,
                      'steps': round(steps, 2), 'missing': missing,
                      'predicted': predicted})
    return found


def expected(points, spacing=None):
    """How many marks the series should hold if its rhythm continued unbroken."""
    return len(points) + sum(hole['missing'] for hole in holes(points, spacing))


def _nearest(position, marks, radius):
    best, distance = None, None
    for mark in marks:
        gap = float(np.hypot(mark['x'] - position['x'], mark['y'] - position['y']))
        if gap <= radius and (distance is None or gap < distance):
            best, distance = mark, gap
    return best, distance


def recover(points, marks, radius, spacing=None):
    """Match each predicted position against marks the finders already located.

    A prediction that lands on a located mark is returned as a recovery, carrying
    the mark's own coordinates rather than the predicted ones - the pixels decide
    where it is, the rhythm only decided where to look. A prediction with no mark
    under it is returned as an unfilled hole, which is what the readers are told
    to go back and look at.
    """
    recovered, unfilled = [], []
    taken = set()
    for hole in holes(points, spacing):
        for position in hole['predicted']:
            mark, distance = _nearest(position, [m for m in marks
                                                 if (m['x'], m['y']) not in taken], radius)
            if mark is None:
                unfilled.append({'predicted': position, 'between': [hole['after'], hole['before']]})
                continue
            taken.add((mark['x'], mark['y']))
            recovered.append({'x': mark['x'], 'y': mark['y'], 'predicted': position,
                              'offset_px': round(distance, 2),
                              'found_by': mark.get('found_by')})
    return {'recovered': recovered, 'unfilled': unfilled}


def report(rows, marks, radius, labels=None):
    """Per series: what it kept, what its rhythm implies, and what is missing.

    `rows` are finalized result rows; only the ones exported as observations set
    the rhythm, because a rejected coordinate is not evidence of a sampling time.
    """
    labels = labels or {}
    by_series = {}
    for row in rows:
        if row.get('status') != 'observed':
            continue
        series = row.get('series_id') or 'unattributed'
        by_series.setdefault(series, []).append({'x': float(row['pixel_x']), 'y': float(row['pixel_y'])})
    out = {}
    for series, points in by_series.items():
        spacing = step([p['x'] for p in points])
        found = holes(points, spacing)
        filled = recover(points, marks, radius, spacing)
        out[series] = {'label': labels.get(series, series), 'kept': len(points),
                       'step_px': round(spacing, 2) if spacing else None,
                       'expected': len(points) + sum(h['missing'] for h in found),
                       'missing': sum(h['missing'] for h in found),
                       'holes': found, **filled}
    return out


def advice(report_by_series):
    """Plain instructions naming where to look, for the readers' next pass."""
    lines = []
    for series, entry in sorted(report_by_series.items()):
        if not entry['missing']:
            continue
        where = ', '.join(f"near x={hole['predicted'][0]['x']:.0f} y={hole['predicted'][0]['y']:.0f}"
                          for hole in entry['holes'][:6])
        lines.append(f"Series {entry['label']}: kept {entry['kept']} marks spaced about "
                     f"{entry['step_px']:.0f} px apart, so the jumps in it imply "
                     f"{entry['missing']} more mark(s) the run has not accounted for "
                     f"({where}). Look there and either read the mark or say the figure "
                     f"prints none.")
    return '\n'.join(lines)
