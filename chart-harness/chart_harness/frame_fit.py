"""Map model-reported pixels back into source pixels.

Providers resize images before a model ever sees them, so a reader returns
coordinates in that rendering's frame. Those numbers are internally consistent,
which is exactly why no self-check catches them. The measured plot box gives the
one correspondence needed to undo the resize: fit the reader's plot box onto the
measured one and every other coordinate it reported moves with it.
"""
import math

MIN_SCALE = .2
MAX_SCALE = 5.
ASPECT_TOLERANCE = .08
UNITY = 1e-3


def fit(model_bbox, measured_bbox):
    """Axis-aligned scale/offset taking the reader's frame to source pixels."""
    if not model_bbox or not measured_bbox:
        return None
    ml, mt, mr, mb = [float(v) for v in model_bbox]
    sl, st, sr, sb = [float(v) for v in measured_bbox]
    if mr - ml <= 1 or mb - mt <= 1:
        return None
    sx = (sr - sl) / (mr - ml)
    sy = (sb - st) / (mb - mt)
    if not (MIN_SCALE <= sx <= MAX_SCALE and MIN_SCALE <= sy <= MAX_SCALE):
        return None
    # A resize is uniform; wildly different axis scales mean the reader's box is
    # simply wrong, and stretching everything onto it would hide that.
    if abs(sx - sy) > ASPECT_TOLERANCE * max(sx, sy):
        return None
    return {'scale_x': sx, 'scale_y': sy,
            'offset_x': sl - sx * ml, 'offset_y': st - sy * mt}


def is_identity(transform):
    return (transform is not None
            and abs(transform['scale_x'] - 1) < UNITY
            and abs(transform['scale_y'] - 1) < UNITY
            and abs(transform['offset_x']) < .5
            and abs(transform['offset_y']) < .5)


def point(transform, x, y):
    return (transform['scale_x'] * float(x) + transform['offset_x'],
            transform['scale_y'] * float(y) + transform['offset_y'])


def box(transform, values):
    left, top = point(transform, values[0], values[1])
    right, bottom = point(transform, values[2], values[3])
    return [left, top, right, bottom]


def apply(interpretation, transform, size):
    """Rewrite every reader-supplied pixel; returns the rewritten copy and a note."""
    width, height = size
    moved = {'seeds': 0, 'template_boxes': 0, 'regions': 0}

    def clamp(x, y):
        return min(max(x, 0.), width - 1.), min(max(y, 0.), height - 1.)

    result = dict(interpretation)
    series = []
    for entry in interpretation.get('series', []):
        entry = dict(entry)
        seeds = []
        for seed in entry.get('seeds', []):
            x, y = clamp(*point(transform, seed['x'], seed['y']))
            seeds.append({**seed, 'x': x, 'y': y})
        if seeds:
            entry['seeds'] = seeds
            moved['seeds'] += len(seeds)
        if entry.get('template_bbox'):
            mapped = box(transform, entry['template_bbox'])
            left, top = clamp(mapped[0], mapped[1])
            right, bottom = clamp(mapped[2], mapped[3])
            if right - left >= 3 and bottom - top >= 3:
                entry['template_bbox'] = [left, top, right, bottom]
                moved['template_boxes'] += 1
        series.append(entry)
    result['series'] = series
    regions = []
    for region in interpretation.get('unresolved_regions', []):
        if isinstance(region, dict) and region.get('bbox'):
            region = {**region, 'bbox': box(transform, region['bbox'])}
            moved['regions'] += 1
        regions.append(region)
    if regions:
        result['unresolved_regions'] = regions
    note = {'code': 'model_frame_rescaled', 'transform': transform,
            'scale': round(math.hypot(transform['scale_x'], transform['scale_y'])
                           / math.sqrt(2), 4), **moved}
    return result, note
