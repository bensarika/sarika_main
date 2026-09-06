"""Screen every accepted decision against the pixels under it.

Whether a mark exists is measurable, so it is measured. A decision that claims
an observation where the window holds no matching ink is demoted here, in
Python, before calibration turns pixels into numbers; the reader is told by how
many pixels and in which direction it was wrong, from the same measurement.
"""
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


SNAP_LIMIT_PX = 12.


def apply(image_path, interpretation, proposals, review, min_ncc=None,
          min_ink_ratio=.5, snap_limit_px=SNAP_LIMIT_PX):
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
        if not result['passed']:
            advice = markers.correction(gray, template, pixel['x'], pixel['y'])
            if advice:
                entry['correction'] = advice
                moved = markers.patch_report(gray, template, advice['x'], advice['y'])
                recheck = markers.verdict(moved, min_ncc=threshold,
                                          min_ink_ratio=min_ink_ratio)
                if recheck['passed'] and advice['distance_px'] <= snap_limit_px:
                    candidate['pixel'] = {'x': advice['x'], 'y': advice['y']}
                    candidate.setdefault('diagnostics', {})['snapped_to_glyph_match'] = {
                        'from': pixel, 'distance_px': advice['distance_px']}
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
    if any(e.get('demoted') for e in screens):
        review['status'] = 'review_required'
        review.setdefault('notes', []).append(
            'decisions demoted by the deterministic legend glyph screen; '
            'see candidate_screen.json')
    review['candidate_screen'] = screens
    return screens
