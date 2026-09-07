"""Put a reader's coordinates back on the frame the marks were printed in.

A reader answers in whatever pixel space it saw the page in: an endpoint that
shrinks a large scan before the model looks at it hands back coordinates that
start near the plot's corner and then fall short of it, so every point reads
high and nothing reaches the right-hand edge. Corrected point by point that
looks like dozens of independent misses; measured across the whole reading it is
one stretch of the frame.

So the reading is registered onto the marks Python found on the source pixels:
the stretch and shift per axis that lands the most of the reading on distinct
measured marks. Two points from the reading and the two marks they are supposed
to be name a candidate frame, every candidate is scored on how many points it
lands on ink, and the winner is refit on its own agreeing points. Nothing is
moved unless the measured marks agree with the move more than they agreed with
the reading as it stood, and a frame that would fold the reading onto a handful
of marks or carry it off the plot is not a reading of anything.
"""
import math

import numpy as np


def _pairs(points, rng, wanted):
    """Index pairs far enough apart that the span between them fixes a scale."""
    count = len(points)
    if count < 2:
        return np.empty((0, 2), dtype=int)
    every = np.array([(i, j) for i in range(count) for j in range(i + 1, count)],
                     dtype=int)
    spans = np.abs(points[every[:, 0]] - points[every[:, 1]])
    # A pair whose span is a fraction of the cloud's own width measures the
    # stretch badly, so the wide half of the pairs is what gets sampled.
    wide = spans.max(axis=1)
    every = every[wide >= np.median(wide)]
    if len(every) > wanted:
        every = every[rng.choice(len(every), size=wanted, replace=False)]
    return every


def _frames(reading, marks, rng, samples):
    """Candidate stretch-and-shift frames, one per pairing of reading to marks."""
    here = _pairs(reading, rng, samples)
    there = _pairs(marks, rng, samples)
    if not len(here) or not len(there):
        return np.empty((0, 4))
    took = min(samples, len(here) * len(there))
    which = rng.choice(len(here) * len(there), size=took, replace=False)
    a, b = reading[here[which // len(there)][:, 0]], reading[here[which // len(there)][:, 1]]
    c, d = marks[there[which % len(there)][:, 0]], marks[there[which % len(there)][:, 1]]
    span, target = b - a, d - c
    with np.errstate(divide='ignore', invalid='ignore'):
        scale = np.where(np.abs(span) > 0, target / span, np.nan)
    shift = c - scale * a
    frames = np.hstack([scale, shift])
    return frames[np.isfinite(frames).all(axis=1) & (scale > 0).all(axis=1)]


def _landed(reading, marks, frame, tolerance):
    """Which reading points land on a mark under this frame, and on which mark."""
    moved = reading * frame[:2] + frame[2:]
    gaps = np.hypot(moved[:, None, 0] - marks[None, :, 0],
                    moved[:, None, 1] - marks[None, :, 1])
    nearest = gaps.argmin(axis=1)
    close = gaps[np.arange(len(moved)), nearest] <= tolerance
    return close, nearest


def _score(reading, marks, frame, tolerance):
    """A frame is worth the number of distinct marks the reading lands on."""
    close, nearest = _landed(reading, marks, frame, tolerance)
    return len(set(nearest[close].tolist())), close, nearest


def _refit(reading, marks, close, nearest):
    """The frame the agreeing points themselves ask for, axis by axis."""
    here, there = reading[close], marks[nearest[close]]
    frame = []
    for axis in (0, 1):
        span = here[:, axis]
        if span.max() - span.min() <= 0:
            return None
        scale, shift = np.polyfit(span, there[:, axis], 1)
        if not (math.isfinite(scale) and math.isfinite(shift)) or scale <= 0:
            return None
        frame.append((scale, shift))
    return np.array([frame[0][0], frame[1][0], frame[0][1], frame[1][1]])


def register(reading, marks, tolerance, bounds=None, samples=2000, seed=0):
    """The frame that best carries this reading onto the marks Python measured.

    `reading` and `marks` are (x, y) pixels, `tolerance` the distance within
    which a moved point counts as landing on a mark - the figure's own glyph,
    not a number chosen here. Returns None when the reading already sits on the
    marks as well as any stretch of it would.
    """
    reading = np.asarray([[float(p[0]), float(p[1])] for p in reading], dtype=float)
    marks = np.asarray([[float(m[0]), float(m[1])] for m in marks], dtype=float)
    if len(reading) < 4 or len(marks) < 4 or not tolerance:
        return None
    stood = np.array([1., 1., 0., 0.])
    stood_score = _score(reading, marks, stood, tolerance)[0]
    best_score = stood_score
    rng = np.random.default_rng(seed)
    best = None
    for frame in _frames(reading, marks, rng, samples):
        score, close, nearest = _score(reading, marks, frame, tolerance)
        # Two points name the frame, so two landing on marks is the pairing
        # itself and says nothing; a frame is only evidence once the rest of the
        # reading corroborates the two it was built from.
        if score <= best_score or score <= 2:
            continue
        closer = _refit(reading, marks, close, nearest)
        if closer is not None:
            score_again = _score(reading, marks, closer, tolerance)[0]
            if score_again >= score:
                frame, score = closer, score_again
        if bounds is not None:
            moved = reading * frame[:2] + frame[2:]
            left, top, right, bottom = (float(v) for v in bounds)
            if (moved[:, 0].min() < left - tolerance or moved[:, 0].max() > right + tolerance
                    or moved[:, 1].min() < top - tolerance or moved[:, 1].max() > bottom + tolerance):
                continue
        best, best_score = frame, score
    if best is None:
        return None
    close, nearest = _landed(reading, marks, best, tolerance)
    return {
        'x_scale': float(best[0]), 'y_scale': float(best[1]),
        'x_shift': float(best[2]), 'y_shift': float(best[3]),
        'landed_on_marks': int(len(set(nearest[close].tolist()))),
        'landed_before': int(stood_score),
        'points': int(len(reading)), 'tolerance_px': float(tolerance),
        'basis': 'the stretch and shift that lands the most of the reading on '
                 'distinct marks measured in the source pixels',
        'reading': 'the reading is drawn in a frame {x:.0%} across and {y:.0%} '
                   'down the size of the page it was measured on'.format(
                       x=1 / float(best[0]) if best[0] else 0.,
                       y=1 / float(best[1]) if best[1] else 0.)}


def carry(frame, x, y):
    """One coordinate, moved into the frame the marks are printed in."""
    return (x * frame['x_scale'] + frame['x_shift'],
            y * frame['y_scale'] + frame['y_shift'])
