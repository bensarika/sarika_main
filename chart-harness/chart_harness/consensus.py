"""Deterministic comparison of two independent runs over the same figure.

Agreement is evidence for review, never proof: two readers can share a bias, and
this module therefore reports disagreement rather than electing a winner. Nothing
here merges values or promotes a row that either run withheld.
"""
import json
import math
from pathlib import Path

VALUE_TOLERANCE = 0.05
# Two readers' anchors agree when they name the same tick, so the question is
# always "closer than a fraction of a tick apart?" - a length the figure states
# itself through its own anchor spacing, rather than a pixel count that means
# different things on a thumbnail and on a plate scan.
ANCHOR_AGREEMENT_FRACTION_OF_SPACING = 0.25


def _load(run_dir):
    run = Path(run_dir)
    result = json.loads((run / 'result.json').read_text())
    interpretation_path = run / 'interpretation.json'
    interpretation = json.loads(interpretation_path.read_text()) if interpretation_path.exists() else {}
    return {'dir': str(run), 'result': result, 'interpretation': interpretation}


def _relative_difference(a, b):
    if a is None or b is None or not math.isfinite(a) or not math.isfinite(b):
        return None
    scale = max(abs(a), abs(b))
    return 0.0 if scale == 0 else abs(a - b) / scale


def _axis_summary(interpretation, name):
    axis = interpretation.get(name) or {}
    anchors = [a for a in axis.get('anchors', []) if isinstance(a.get('pixel'), (int, float))]
    return {'scale': axis.get('scale'), 'unit': axis.get('unit'),
            'anchor_pixels': [float(a['pixel']) for a in anchors],
            'anchor_values': [a.get('value') for a in anchors]}


def _spacing(pixels):
    """The closest two anchors on this axis: the length the axis is drawn in."""
    ordered = sorted(pixels)
    gaps = [b - a for a, b in zip(ordered, ordered[1:]) if b > a]
    return min(gaps) if gaps else None


def _compare_axes(left, right, pixel_tolerance):
    axes = {}
    for name in ('x_axis', 'y_axis'):
        a, b = _axis_summary(left['interpretation'], name), _axis_summary(right['interpretation'], name)
        offsets = [min((abs(p - q) for q in b['anchor_pixels']), default=None) for p in a['anchor_pixels']]
        measured = [o for o in offsets if o is not None]
        spacings = [s for s in (_spacing(a['anchor_pixels']), _spacing(b['anchor_pixels'])) if s]
        spacing = min(spacings) if spacings else None
        tolerance = pixel_tolerance if pixel_tolerance is not None else (
            None if spacing is None else spacing * ANCHOR_AGREEMENT_FRACTION_OF_SPACING)
        agrees = (a['scale'] == b['scale'] and bool(measured) and tolerance is not None
                  and max(measured) <= tolerance and a['anchor_values'] == b['anchor_values'])
        axes[name] = {'left': a, 'right': b, 'agrees': agrees,
                      'max_anchor_offset_px': max(measured) if measured else None,
                      'anchor_spacing_px': spacing, 'tolerance_px': tolerance}
    return axes


def _accepted_rows(entry):
    return [r for r in entry['result'].get('rows', []) if r.get('status') == 'observed']


def _key(row):
    return row.get('series_label') or row.get('series_id')


def _compare_points(left, right, value_tolerance):
    unmatched_right = _accepted_rows(right)
    matches, only_left = [], []
    for row in _accepted_rows(left):
        pool = [r for r in unmatched_right if _key(r) == _key(row) and r.get('x') is not None and row.get('x') is not None]
        best = min(pool, key=lambda r: abs(r['x'] - row['x']), default=None)
        if best is None or _relative_difference(row['x'], best['x']) is None or _relative_difference(row['x'], best['x']) > value_tolerance:
            only_left.append(row)
            continue
        unmatched_right.remove(best)
        difference = _relative_difference(row.get('y'), best.get('y'))
        matches.append({'series': _key(row), 'left': {'x': row.get('x'), 'y': row.get('y')},
                        'right': {'x': best.get('x'), 'y': best.get('y')},
                        'relative_y_difference': difference,
                        'agrees': difference is not None and difference <= value_tolerance})
    return {'matched': matches,
            'accepted_only_by_left': [{'series': _key(r), 'x': r.get('x'), 'y': r.get('y')} for r in only_left],
            'accepted_only_by_right': [{'series': _key(r), 'x': r.get('x'), 'y': r.get('y')} for r in unmatched_right]}


def compare(left_dir, right_dir, value_tolerance=VALUE_TOLERANCE, pixel_tolerance=None):
    left, right = _load(left_dir), _load(right_dir)
    points = _compare_points(left, right, value_tolerance)
    axes = _compare_axes(left, right, pixel_tolerance)
    series = {'left': sorted({_key(r) for r in left['result'].get('rows', []) if _key(r)}),
              'right': sorted({_key(r) for r in right['result'].get('rows', []) if _key(r)})}
    disagreements = []
    for name, axis in axes.items():
        if not axis['agrees']:
            disagreements.append({'code': 'axis_calibration_disagreement', 'axis': name,
                                  'max_anchor_offset_px': axis['max_anchor_offset_px'],
                                  'tolerance_px': axis['tolerance_px'],
                                  'anchor_spacing_px': axis['anchor_spacing_px']})
    if series['left'] != series['right']:
        disagreements.append({'code': 'series_label_disagreement', **series})
    for match in points['matched']:
        if not match['agrees']:
            disagreements.append({'code': 'point_value_disagreement', 'series': match['series'],
                                  'x': match['left']['x'], 'relative_y_difference': match['relative_y_difference']})
    for side in ('accepted_only_by_left', 'accepted_only_by_right'):
        if points[side]:
            disagreements.append({'code': 'accepted_point_coverage_disagreement', 'side': side,
                                  'count': len(points[side])})
    return {'schema_version': 1,
            'runs': {'left': left['dir'], 'right': right['dir']},
            'status': {'left': left['result'].get('status'), 'right': right['result'].get('status')},
            'counts': {'left': left['result'].get('counts'), 'right': right['result'].get('counts')},
            'axes': axes, 'series': series, 'points': points,
            'disagreements': disagreements,
            'agrees': not disagreements,
            'tolerances': {'relative_value': value_tolerance,
                           'anchor_pixels': pixel_tolerance,
                           'anchor_fraction_of_spacing': (
                               None if pixel_tolerance is not None
                               else ANCHOR_AGREEMENT_FRACTION_OF_SPACING)},
            'note': ('Agreement between independent readers is evidence for review only. '
                     'Shared bias, shared source degradation, and identical misreadings are not detected here.')}
