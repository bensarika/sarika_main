"""Reviewer work split into small, separately bounded calls on single crops.

One review call over every candidate is slow and all-or-nothing: a stalled
response loses the whole stage, and a whole-figure image forces the reader to
hunt for tiny markers. Each batch here is a handful of neighbouring candidates
shown as one crop of the ORIGINAL pixels at native scale, so coordinates map
back by translation alone and no generated overlay is ever measured.
"""
import json
from pathlib import Path

from PIL import Image

BATCH_SIZE = 8
PADDING_PX = 48
MIN_SIDE = 360


def _box(points, size, padding_px, min_side):
    width, height = size
    left = min(p['x'] for p in points) - padding_px
    right = max(p['x'] for p in points) + padding_px
    top = min(p['y'] for p in points) - padding_px
    bottom = max(p['y'] for p in points) + padding_px
    left, right = _widen(left, right, min_side, width)
    top, bottom = _widen(top, bottom, min_side, height)
    return [left, top, right, bottom]


def _widen(low, high, min_side, extent):
    """Grow a span to a readable width, then slide it inside the image."""
    if high - low < min_side:
        center = (low + high) / 2
        low, high = center - min_side / 2, center + min_side / 2
    low, high = round(low), round(high)
    if high - low > extent:
        return 0, extent
    if low < 0:
        low, high = 0, high - low
    if high > extent:
        low, high = low - (high - extent), extent
    return low, high


def plan(candidates, size, batch_size=BATCH_SIZE, padding_px=PADDING_PX,
         min_side=MIN_SIDE):
    """Group candidates into spatially local batches, one crop each."""
    ordered = sorted(candidates, key=lambda c: (c['pixel']['x'], c['pixel']['y']))
    batches = []
    for start in range(0, len(ordered), batch_size):
        group = ordered[start:start + batch_size]
        box = _box([c['pixel'] for c in group], size, padding_px, min_side)
        batches.append({
            'index': len(batches),
            'box': box,
            'candidates': [{
                'candidate_id': c['candidate_id'],
                'pixel': {'x': c['pixel']['x'] - box[0],
                          'y': c['pixel']['y'] - box[1]},
            } for c in group],
        })
    return batches


def crop(image_path, batch, outdir):
    """Cut the batch window at native resolution; no resampling of measurables."""
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    target = outdir / f"batch_{batch['index']:03d}.png"
    with Image.open(image_path) as im:
        im.convert('RGB').crop(tuple(int(v) for v in batch['box'])).save(target)
    return target


def _shift(point, box):
    return {'x': point['x'] + box[0], 'y': point['y'] + box[1]}


def merge(axes_review, parts, batches):
    """Reassemble batch decisions in whole-image coordinates.

    A batch that fails to decide a candidate leaves it absent; the geometry
    stage treats absent decisions as unresolved rather than accepted.
    """
    decisions, missing, notes, statuses = [], [], [], []
    # Decisions stay free of extra fields: geometry rejects any decision that
    # carries anything beyond its verdict, so provenance is kept alongside.
    origin = {}
    for batch, part in zip(batches, parts):
        box = batch['box']
        for decision in part.get('decisions', []):
            entry = dict(decision)
            center = entry.get('marker_center')
            if isinstance(center, dict) and all(
                    isinstance(center.get(k), (int, float)) for k in 'xy'):
                entry['marker_center'] = _shift(center, box)
            origin[entry.get('candidate_id')] = batch['index']
            decisions.append(entry)
        for point in part.get('missing_points', []):
            if all(isinstance(point.get(k), (int, float)) for k in 'xy'):
                missing.append({**point, **_shift(point, box)})
            else:
                missing.append(dict(point))
        notes += [f"batch {batch['index']}: {n}" for n in part.get('notes', [])]
        statuses.append(part.get('status'))
    review = {
        'axis_check': axes_review.get('axis_check', {}),
        'series_labels': axes_review.get('series_labels', {}),
        'decisions': decisions,
        'missing_points': missing + list(axes_review.get('missing_points', [])),
        'notes': list(axes_review.get('notes', [])) + notes,
        'status': ('accepted'
                   if statuses and all(s == 'accepted' for s in statuses)
                   and axes_review.get('status') == 'accepted'
                   else 'review_required'),
        'decision_batches': origin,
        'review_batches': [
            {'index': b['index'], 'box': b['box'],
             'candidate_ids': [c['candidate_id'] for c in b['candidates']],
             'status': s}
            for b, s in zip(batches, statuses)
        ],
    }
    checks = [p['_visual_check'] for p in (axes_review, *parts)
              if isinstance(p.get('_visual_check'), dict)]
    if checks:
        # A concern raised by any batch is a concern about the whole review.
        concerned = [c for c in checks if c.get('assessment') == 'concerns']
        review['_visual_check'] = (concerned or checks)[0]
        review['review_visual_checks'] = [c.get('image_path') for c in checks]
    return review


def summary(batches):
    return json.dumps([{'index': b['index'], 'box': b['box'],
                        'candidates': len(b['candidates'])} for b in batches])
