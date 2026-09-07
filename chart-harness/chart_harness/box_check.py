"""Judge a plot box against the ink, correct it, and judge it again.

A box is only right if no printed ink runs across its edges: an edge standing in
the middle of the drawing has cut the plot in half, and everything downstream
then reads a figure with a piece missing. That is measurable without asking
anybody - the ink either continues past the edge or it does not - so the box can
be scored, moved off the ink, and scored again until the score stops improving.

The loop keeps every attempt so a box that could not be settled says so with its
own numbers rather than passing silently.
"""
from . import markers
from . import panel_fit


def _mask(image_path):
    return markers.load_gray(image_path) < markers.INK_LEVEL


def edges_cutting_ink(image_path, box, mask=None):
    """Which edges have printed ink running straight through them."""
    mask = _mask(image_path) if mask is None else mask
    height, width = mask.shape
    left, top, right, bottom = (int(round(float(v))) for v in box)
    left, top = max(0, left), max(0, top)
    right, bottom = min(width, right), min(height, bottom)
    if right - left < 2 or bottom - top < 2:
        return ['degenerate']
    columns = mask[top:bottom].any(axis=0)
    rows = mask[:, left:right].any(axis=1)
    cut = []
    if left > 0 and columns[left] and columns[left - 1]:
        cut.append('left')
    if top > 0 and rows[top] and rows[top - 1]:
        cut.append('top')
    if right < width and columns[right - 1] and columns[right]:
        cut.append('right')
    if bottom < height and rows[bottom - 1] and rows[bottom]:
        cut.append('bottom')
    return cut


def score(image_path, box, mask=None):
    """What is wrong with this box, in the figure's own measurements."""
    mask = _mask(image_path) if mask is None else mask
    height, width = mask.shape
    left, top, right, bottom = (float(v) for v in box)
    cut = edges_cutting_ink(image_path, box, mask)
    inside = mask[max(0, int(top)):int(bottom), max(0, int(left)):int(right)]
    ink = int(mask.sum())
    return {'box': [left, top, right, bottom],
            'edges_cutting_ink': cut,
            'holds': not cut,
            'share_of_the_page_ink_inside': round(float(inside.sum()) / ink, 3) if ink else 0.,
            'share_of_the_page_area': round(
                ((right - left) * (bottom - top)) / float(width * height), 3)}


def settle(image_path, box):
    """Move the box off the ink until scoring it stops finding an edge to move.

    Each round is the previous round's box widened off whatever ink it still cut,
    so a box that clipped two sides is corrected on both without anyone choosing
    how many rounds to run: growth is bounded by the page, so it converges.
    """
    mask = _mask(image_path)
    attempts = [score(image_path, box, mask)]
    settled = [float(v) for v in box]
    while not attempts[-1]['holds'] and 'degenerate' not in attempts[-1]['edges_cutting_ink']:
        grown, note = panel_fit.widen(image_path, settled)
        if note is None or [float(v) for v in grown] == settled:
            break
        settled = [float(v) for v in grown]
        attempts.append({**score(image_path, settled, mask), 'moved': note['moved']})
    return settled, attempts


def holds_marks(box, marks):
    """How much of what the finders measured stands inside this box.

    Reported, not acted on: outside a plot box sits the axis text and the legend,
    which the finders also measure, so a box carried out to every measured body
    would swallow the labels. What it is for is saying, in numbers, when a box
    has left real marks outside it.
    """
    bodies = list(marks or [])
    if not bodies:
        return None
    left, top, right, bottom = (float(v) for v in box)
    inside = [m for m in bodies
              if left <= float(m['x']) <= right and top <= float(m['y']) <= bottom]
    return {'marks': len(bodies), 'inside': len(inside),
            'share_of_the_marks_inside': round(len(inside) / float(len(bodies)), 3),
            'outside': [{'x': float(m['x']), 'y': float(m['y'])}
                        for m in bodies if m not in inside][:20]}


def sentence(attempts):
    """What the loop found and whether it fixed it."""
    first, last = attempts[0], attempts[-1]
    if first['holds']:
        return 'the plot box stands in blank paper on all four sides'
    if last['holds']:
        return ('the plot box cut the drawing on its {sides} side(s); carried off the ink '
                'over {n} round(s) it now stands in blank paper'.format(
                    sides='/'.join(first['edges_cutting_ink']), n=len(attempts) - 1))
    return ('the plot box still cuts printed ink on its {sides} side(s) after {n} round(s) '
            'of carrying it outward; the reading inside it is short by whatever falls '
            'outside'.format(sides='/'.join(last['edges_cutting_ink']), n=len(attempts) - 1))
