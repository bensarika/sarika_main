"""Screen every accepted decision against the pixels under it.

Whether a mark exists is measurable, so it is measured. A decision that claims
an observation where the window holds no matching ink is demoted here, in
Python, before calibration turns pixels into numbers; the reader is told by how
many pixels and in which direction it was wrong, from the same measurement.
"""
import statistics

from . import markers


def _series_templates(interpretation):
    return {s['id']: s['template_bbox'] for s in interpretation.get('series', [])
            if s.get('template_bbox')}


def batch_feedback(gray, templates, batch, by_id, min_ncc=None, min_ink_ratio=.5):
    """Per-candidate pixel measurements for one review crop, in crop coordinates."""
    box = batch['box']
    entries = []
    for candidate in batch['candidates']:
        source = by_id.get(candidate['candidate_id'])
        if source is None:
            continue
        template = next((templates[s] for s in source.get('possible_series', [])
                         if s in templates), None)
        if template is None:
            continue
        x, y = source['pixel']['x'], source['pixel']['y']
        report = markers.patch_report(gray, template, x, y)
        result = markers.verdict(
            report,
            min_ncc=markers.DEFAULT_MATCH_THRESHOLD if min_ncc is None else min_ncc,
            min_ink_ratio=min_ink_ratio)
        entry = {'candidate_id': candidate['candidate_id'],
                 'glyph_match': round(report['ncc'], 3) if report.get('ncc') is not None else None,
                 'ink_fraction': round(report['ink_fraction'], 3),
                 'legend_ink_fraction': round(report['template_ink_fraction'], 3),
                 'passed': result['passed']}
        if not result['passed']:
            entry['failure'] = result['reason']
            advice = markers.correction(gray, template, x, y)
            if advice:
                entry['nearest_match'] = {
                    'crop_x': round(advice['x'] - box[0], 1),
                    'crop_y': round(advice['y'] - box[1], 1),
                    'dx': round(advice['dx'], 1), 'dy': round(advice['dy'], 1),
                    'glyph_match': round(advice['score'], 3),
                    'advice': advice['advice']}
            entry['crowding'] = markers.crowding(
                gray, x, y, glyph_ink=_glyph_ink(gray, template))
        entries.append(entry)
    return entries


def _glyph_ink(gray, template_bbox):
    box = [int(v) for v in template_bbox]
    patch = gray[box[1]:box[3], box[0]:box[2]]
    return max(1, int((patch < markers.INK_LEVEL).sum()))


# How far a coordinate may be moved onto the match python found is measured in
# glyphs, not pixels: a correction shorter than the mark itself is the same mark
# read slightly off centre, while a longer one is a different mark. The glyph is
# cut from this figure's own legend, so the limit follows the figure's scale.
SNAP_LIMIT_IN_GLYPHS = 1.
# A reader that reads one point high has read them all high: the same eye made
# every guess. An offset shared by this share of the points, in the same
# direction and bigger than this much of a glyph, is the reader's bias rather
# than a scatter of small misses, and it is worth taking off all of them.
BIAS_AGREEMENT_FRACTION = .6
BIAS_SIZE_IN_GLYPHS = .25
BIAS_MINIMUM_POINTS = 4


def systematic_offset(screens, glyph_size):
    """The offset the whole reading is out by, where its misses all lean one way.

    Each point's distance to the nearest matching window is already measured. If
    most of those distances point the same way and are bigger than a quarter of
    a glyph, the reading is displaced as a whole - the thing to say about a
    reader whose points all sit above the marks - and the shift is measured, not
    guessed at.
    """
    offsets = [e['offset_to_nearest_match'] for e in screens
               if e.get('offset_to_nearest_match')]
    if len(offsets) < BIAS_MINIMUM_POINTS or not glyph_size:
        return None
    found = {}
    for axis in ('dx', 'dy'):
        deltas = [o[axis] for o in offsets]
        middle = float(statistics.median(deltas))
        if abs(middle) < glyph_size * BIAS_SIZE_IN_GLYPHS:
            continue
        agreeing = sum(1 for d in deltas if d * middle > 0) / len(deltas)
        if agreeing < BIAS_AGREEMENT_FRACTION:
            continue
        found[axis] = {'median_px': middle, 'share_agreeing': round(agreeing, 2)}
    if not found:
        return None
    direction = []
    if 'dx' in found:
        direction.append('right' if found['dx']['median_px'] > 0 else 'left')
    if 'dy' in found:
        direction.append('below' if found['dy']['median_px'] > 0 else 'above')
    return {'dx': found.get('dx', {}).get('median_px', 0.),
            'dy': found.get('dy', {}).get('median_px', 0.),
            'points_measured': len(offsets),
            'axes': found, 'glyph_size_px': glyph_size,
            'basis': 'median distance from each point to the window that matches its glyph',
            'reading': 'the marks lie {d} the reading, by {x:.0f}px across and {y:.0f}px up '
                       'or down'.format(d=' and '.join(direction),
                                        x=abs(found.get('dx', {}).get('median_px', 0.)),
                                        y=abs(found.get('dy', {}).get('median_px', 0.)))}


def _glyph_size(template_bbox):
    box = [float(v) for v in template_bbox]
    return max(box[2] - box[0], box[3] - box[1])


def _take_off_the_bias(gray, templates, by_id, review, screens, bias, threshold,
                       min_ink_ratio):
    """Move the points the whole reading missed by, where the move lands on ink.

    Only a point that failed on its own pixels is moved, and only if the shifted
    window then passes the same check every other point had to pass. A demotion
    that survives the correction stays a demotion.
    """
    recovered = []
    by_candidate = {e['candidate_id']: e for e in screens}
    for decision in review.get('decisions', []):
        entry = by_candidate.get(decision.get('candidate_id'))
        if entry is None or entry.get('passed') or entry.get('corrected'):
            continue
        candidate = by_id.get(decision.get('candidate_id'))
        template = templates.get(entry['series_id'])
        if candidate is None or template is None:
            continue
        x = candidate['pixel']['x'] + bias['dx']
        y = candidate['pixel']['y'] + bias['dy']
        moved = markers.patch_report(gray, template, x, y)
        recheck = markers.verdict(moved, min_ncc=threshold, min_ink_ratio=min_ink_ratio)
        if not recheck['passed']:
            continue
        was = dict(candidate['pixel'])
        candidate['pixel'] = {'x': x, 'y': y}
        candidate.setdefault('diagnostics', {})['moved_by_the_readings_own_offset'] = {
            'from': was, 'dx': bias['dx'], 'dy': bias['dy'],
            'basis': bias['basis']}
        entry.update({'pixel': candidate['pixel'], 'corrected': True,
                      'corrected_by': 'the reading\'s measured displacement',
                      'measurements': moved, **recheck})
        if entry.pop('demoted', None) and decision.get('role') == 'unresolved':
            decision['role'] = 'observed'
            decision['reason'] = ('moved onto the mark by the displacement measured '
                                  'across the whole reading; ' +
                                  str(decision.get('reason', '')))[:900]
        recovered.append(entry['candidate_id'])
    return recovered


def apply(image_path, interpretation, proposals, review, min_ncc=None,
          min_ink_ratio=.5, snap_limit_px=None,
          snap_limit_in_glyphs=SNAP_LIMIT_IN_GLYPHS):
    """Correct or demote decisions whose window fails the legend glyph check.

    A near miss is moved onto the measured match by Python and re-verified; a
    coordinate with no matching pixels nearby stops being an observation. Both
    mutate `review` (and, for a correction, the candidate) in place: a rule that
    only reports itself is advice, and the next stage would proceed regardless.
    """
    gray = markers.load_gray(image_path)
    templates = _series_templates(interpretation)
    by_id = {c['candidate_id']: c for c in proposals.get('candidates', [])}
    label_to_id = {s['label']: s['id'] for s in interpretation.get('series', [])}
    screens = []
    for decision in review.get('decisions', []):
        series_id = label_to_id.get(decision.get('series_id'), decision.get('series_id'))
        candidate = by_id.get(decision.get('candidate_id'))
        template = templates.get(series_id)
        if candidate is None or template is None:
            continue
        pixel = candidate['pixel']
        report = markers.patch_report(gray, template, pixel['x'], pixel['y'])
        result = markers.verdict(
            report,
            min_ncc=markers.DEFAULT_MATCH_THRESHOLD if min_ncc is None else min_ncc,
            min_ink_ratio=min_ink_ratio)
        entry = {'candidate_id': decision.get('candidate_id'), 'series_id': series_id,
                 'role': decision.get('role'), 'pixel': pixel, **result,
                 'measurements': report}
        threshold = markers.DEFAULT_MATCH_THRESHOLD if min_ncc is None else min_ncc
        # Measured for every point, passing or not: one point's small miss is
        # noise, but the same miss on all of them is the reader's own bias.
        advice = markers.correction(gray, template, pixel['x'], pixel['y'])
        if advice and advice['score'] >= threshold:
            entry['offset_to_nearest_match'] = {'dx': advice['dx'], 'dy': advice['dy'],
                                                'score': advice['score'],
                                                'glyph_size_px': _glyph_size(template)}
        if not result['passed']:
            if advice:
                entry['correction'] = advice
                moved = markers.patch_report(gray, template, advice['x'], advice['y'])
                recheck = markers.verdict(moved, min_ncc=threshold,
                                          min_ink_ratio=min_ink_ratio)
                limit = (snap_limit_px if snap_limit_px is not None
                         else _glyph_size(template) * snap_limit_in_glyphs)
                if recheck['passed'] and advice['distance_px'] <= limit:
                    candidate['pixel'] = {'x': advice['x'], 'y': advice['y']}
                    candidate.setdefault('diagnostics', {})['snapped_to_glyph_match'] = {
                        'from': pixel, 'distance_px': advice['distance_px'],
                        'limit_px': limit, 'glyph_size_px': _glyph_size(template)}
                    entry.update({'pixel': candidate['pixel'], 'corrected': True,
                                  'measurements': moved, **recheck})
                    screens.append(entry)
                    continue
                entry['recheck_at_correction'] = recheck
            entry['crowding'] = markers.crowding(
                gray, pixel['x'], pixel['y'], glyph_ink=_glyph_ink(gray, template))
            if decision.get('role') == 'observed':
                decision['role'] = 'unresolved'
                decision['reason'] = (
                    f"pixels at this coordinate fail the legend glyph check "
                    f"({result['reason']}); " + str(decision.get('reason', '')))[:900]
                entry['demoted'] = True
        screens.append(entry)
    sizes = [e['offset_to_nearest_match']['glyph_size_px'] for e in screens
             if e.get('offset_to_nearest_match')]
    bias = systematic_offset(screens, statistics.median(sizes) if sizes else None)
    if bias:
        review['systematic_offset'] = bias
        review.setdefault('notes', []).append(
            'the reading is displaced as a whole: ' + bias['reading'])
        bias['recovered'] = _take_off_the_bias(
            gray, templates, by_id, review, screens, bias,
            markers.DEFAULT_MATCH_THRESHOLD if min_ncc is None else min_ncc,
            min_ink_ratio)
    if any(e.get('demoted') for e in screens):
        review['status'] = 'review_required'
        review.setdefault('notes', []).append(
            'decisions demoted by the deterministic legend glyph screen; '
            'see candidate_screen.json')
    review['candidate_screen'] = screens
    return screens
