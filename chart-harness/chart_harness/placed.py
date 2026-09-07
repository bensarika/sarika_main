"""Marks a person puts on the figure by hand, measured like any other mark.

A watcher can see in a moment what a reader argues about for a minute: this dot
belongs to that group, that ring is an error bar cap. A placed mark is that
knowledge written onto the pixels - but it is still checked against them, so a
click a little off the mark is carried onto the ink body underneath it and a
click on blank paper is recorded as pointing at nothing rather than inventing a
datapoint. The marks are handed to the reader as a watcher's corrections for its
next pass and kept with the run, so a figure the harness reads badly leaves
behind the reading it should have produced.
"""
import json
import time
from pathlib import Path

import numpy as np
from scipy import ndimage

from . import markers


def measure(image_path, x, y):
    """What the pixels say about the spot a person pointed at."""
    gray = markers.load_gray(image_path)
    height, width = gray.shape
    x, y = float(x), float(y)
    if not (0 <= x < width and 0 <= y < height):
        return {'on_the_page': False,
                'reading': 'that spot is off the image'}
    mask = gray < markers.INK_LEVEL
    if not mask.any():
        return {'on_the_page': True, 'on_ink': False,
                'reading': 'there is no ink anywhere on this image'}
    distance, nearest = ndimage.distance_transform_edt(~mask, return_indices=True)
    row, column = int(round(y)), int(round(x))
    gap = float(distance[row, column])
    ink_row, ink_column = int(nearest[0][row, column]), int(nearest[1][row, column])
    labelled, count = ndimage.label(mask)
    body = int(labelled[ink_row, ink_column])
    where = ndimage.find_objects(labelled, count)[body - 1]
    pixels = int((labelled[where] == body).sum())
    centre = ndimage.center_of_mass(labelled[where] == body)
    centre = (centre[0] + where[0].start, centre[1] + where[1].start)
    return {
        'on_the_page': True,
        'on_ink': gap == 0.,
        'distance_to_ink_px': round(gap, 2),
        'ink_body': {
            'x': float(centre[1]), 'y': float(centre[0]),
            'width': int(where[1].stop - where[1].start),
            'height': int(where[0].stop - where[0].start),
            'pixels': pixels},
        'reading': ('the ink under that spot is a body {w}x{h} pixels'
                    if gap == 0. else
                    'the nearest ink is {d:.0f}px away, a body {w}x{h} pixels').format(
                        w=int(where[1].stop - where[1].start),
                        h=int(where[0].stop - where[0].start), d=gap)}


def _snap(mark, measured, reach):
    """A click carried onto the body it was aimed at, when it plainly was."""
    body = measured.get('ink_body')
    if not body or measured.get('distance_to_ink_px', 0.) > (reach or 0.):
        return None
    if max(body['width'], body['height']) > (reach or 0) * 2:
        # A long thin body is a curve or an error bar, not a mark: the click
        # stays where the person put it and the body is only reported.
        return None
    return {'x': body['x'], 'y': body['y']}


def place(image_path, x, y, group=None, kind='data', reach=None):
    """One hand-placed mark, with what the pixels there actually hold."""
    if kind not in ('data', 'not_data'):
        raise ValueError('a placed mark is data or not_data')
    measured = measure(image_path, x, y)
    mark = {'x': float(x), 'y': float(y), 'group': (group or None),
            'kind': kind, 'placed_by': 'watcher', 'at': time.time(),
            'image': str(image_path), 'measured': measured}
    carried = _snap(mark, measured, reach)
    if carried:
        mark['clicked'] = {'x': mark['x'], 'y': mark['y']}
        mark['x'], mark['y'] = carried['x'], carried['y']
        mark['carried_onto_the_ink'] = True
    return mark


def reach_from(marks_or_glyphs):
    """How far a click may be carried: the figure's own mark, not a number."""
    sizes = [float(s) for s in marks_or_glyphs if s]
    if not sizes:
        return None
    return float(np.median(sizes))


def sentence(mark):
    """The correction as the reader will be told it."""
    where = 'x={x:.0f}, y={y:.0f} pixels'.format(x=mark['x'], y=mark['y'])
    if mark['kind'] == 'not_data':
        return ('a person looking at this figure says there is no datapoint at '
                + where + ' - do not report one there')
    group = mark.get('group')
    return ('a person looking at this figure marked a datapoint at ' + where
            + (' belonging to ' + group if group else ' (group not stated)')
            + '; ' + str(mark['measured'].get('reading', '')))


def record(directory, mark):
    """Keep it with the run: corrections are the harness's own training data."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / 'placed_marks.jsonl').open('a') as log:
        log.write(json.dumps(mark) + '\n')
    return mark


def held(directory):
    """Every mark placed on this run so far."""
    path = Path(directory) / 'placed_marks.jsonl'
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
