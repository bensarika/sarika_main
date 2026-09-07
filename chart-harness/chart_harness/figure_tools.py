"""Measurements a reader can ask Python for while it reads a figure.

A reader guessing a coordinate off a picture is the weakest part of this harness:
it cannot count pixels, and it has no way to check itself. So it does not have to
work alone. Every question worth asking about the page - is there ink here, where
is the nearest mark, where did the ticks land, what does this pixel mean in the
axis units, what is inside this patch - is answered here from the source pixels,
the same numbers the screen later holds the reading to. A reader that measures
before it answers and a reader that is checked afterwards are then measuring the
same figure with the same ruler, so its answer and its verdict cannot diverge.

Nothing here invents a point. Every answer is a measurement or a plain statement
that there is nothing there.
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from . import markers

# How much bigger than the figure's own mark the readable patch grid is allowed
# to get before it is summarised more coarsely: a reader reads a small grid, and
# a grid finer than the page's own marks describes paper, not marks.
PATCH_GRID_SIDE = 12
# The most marks worth listing in one answer. A list longer than the figure has
# marks is noise, and the reader has the picture for the rest.
MOST_MARKS_LISTED = 60


def _finite(value: Any, name: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f'{name} must be a finite number')
    return number


def _window(gray: np.ndarray, box: Sequence[float]) -> np.ndarray:
    left, top, right, bottom = (int(round(v)) for v in box)
    left, top = max(0, left), max(0, top)
    right, bottom = min(gray.shape[1], right), min(gray.shape[0], bottom)
    if right <= left or bottom <= top:
        return np.empty((0, 0), dtype=bool)
    return gray[top:bottom, left:right] < markers.INK_LEVEL


def _ink_share(gray: np.ndarray, box: Sequence[float]) -> float:
    patch = _window(gray, box)
    return float(patch.mean()) if patch.size else 0.


def _ink_grid(gray: np.ndarray, box: Sequence[float]) -> list[str]:
    """A patch written out as coarse ink density, so a reader can read pixels."""
    patch = _window(gray, box)
    if patch.size == 0:
        return []
    rows = min(PATCH_GRID_SIDE, patch.shape[0])
    cols = min(PATCH_GRID_SIDE, patch.shape[1])
    ys = np.linspace(0, patch.shape[0], rows + 1).astype(int)
    xs = np.linspace(0, patch.shape[1], cols + 1).astype(int)
    shades = ' .:-=+*#%@'
    lines = []
    for r in range(rows):
        line = ''
        for c in range(cols):
            cell = patch[ys[r]:ys[r + 1], xs[c]:xs[c + 1]]
            share = float(cell.mean()) if cell.size else 0.
            line += shades[min(len(shades) - 1, int(share * len(shades)))]
        lines.append(line)
    return lines


class FigureTools:
    """The deterministic measurements, bound to one figure.

    `templates` maps a series id to the pixel box of its own glyph, so ink is
    judged against the mark that series actually uses. Without one, a question
    about a point is answered with plain ink density instead of a match.
    """

    def __init__(self, image_path: Path | str, plot_bbox: Sequence[float] | None = None,
                 templates: Mapping[str, Sequence[float]] | None = None,
                 detected_marks: Sequence[Mapping[str, Any]] = (),
                 ticks: Mapping[str, Any] | None = None,
                 axes: Mapping[str, Any] | None = None) -> None:
        self.image_path = Path(image_path)
        self.gray = markers.load_gray(self.image_path)
        height, width = self.gray.shape
        self.image_size = {'width': int(width), 'height': int(height)}
        self.plot_bbox = [float(v) for v in plot_bbox] if plot_bbox else [0., 0., float(width), float(height)]
        self.templates = {str(k): [float(v) for v in box] for k, box in (templates or {}).items()}
        self.detected_marks = [dict(m) for m in detected_marks]
        self.ticks = dict(ticks) if ticks else {}
        self.axes = axes
        self.calls: list[dict[str, Any]] = []

    # -- what the reader is told it can ask -------------------------------
    def schemas(self) -> list[dict[str, Any]]:
        series = sorted(self.templates) or None
        of_a_series = {'type': 'string', 'description': 'which series to measure against'}
        if series:
            of_a_series['enum'] = series
        return [
            {'type': 'function', 'function': {
                'name': 'measure_ink_at',
                'description': ('Measure the pixels at a point before you claim a mark is there. '
                                'Returns how much of a mark-sized window is inked, how much of its '
                                'middle is inked, how well it matches the series glyph, and whether '
                                'that is enough to be kept. An empty window means no mark, whatever it looks like.'),
                'parameters': {'type': 'object', 'additionalProperties': False,
                               'required': ['x', 'y'],
                               'properties': {'x': {'type': 'number'}, 'y': {'type': 'number'},
                                              'series_id': of_a_series}}}},
            {'type': 'function', 'function': {
                'name': 'snap_to_nearest_mark',
                'description': ('Find the nearest window that actually matches the series glyph and '
                                'return the offset from your point to it. Use it to correct a point '
                                'you are unsure of; if the offset repeats, your whole reading is shifted.'),
                'parameters': {'type': 'object', 'additionalProperties': False,
                               'required': ['x', 'y'],
                               'properties': {'x': {'type': 'number'}, 'y': {'type': 'number'},
                                              'series_id': of_a_series}}}},
            {'type': 'function', 'function': {
                'name': 'list_detected_marks',
                'description': ('List the marks Python already found in the plot, optionally inside a '
                                'region. These are locations of ink, not attributed to any series - '
                                'that attribution is your job.'),
                'parameters': {'type': 'object', 'additionalProperties': False, 'required': [],
                               'properties': {'region': {'type': 'array', 'items': {'type': 'number'},
                                                         'minItems': 4, 'maxItems': 4,
                                                         'description': '[left, top, right, bottom] in pixels'}}}}},
            {'type': 'function', 'function': {
                'name': 'read_axis_ticks',
                'description': ('The tick marks Python measured on this page, in pixels, with the plot '
                                'box and image size. Use it to place your reading against the real axes '
                                'and to reach the first and last column of marks.'),
                'parameters': {'type': 'object', 'additionalProperties': False, 'required': [], 'properties': {}}}},
            {'type': 'function', 'function': {
                'name': 'value_at_pixel',
                'description': ('Convert a pixel to the figure\'s own axis units using the calibration '
                                'in force. Available once the axes are calibrated.'),
                'parameters': {'type': 'object', 'additionalProperties': False, 'required': ['x', 'y'],
                               'properties': {'x': {'type': 'number'}, 'y': {'type': 'number'}}}}},
            {'type': 'function', 'function': {
                'name': 'zoom',
                'description': ('Read a small region of the page as an ink map, one character per cell, '
                                'from blank to solid. Use it where marks overlap and the picture is too '
                                'coarse to separate them.'),
                'parameters': {'type': 'object', 'additionalProperties': False, 'required': ['region'],
                               'properties': {'region': {'type': 'array', 'items': {'type': 'number'},
                                                         'minItems': 4, 'maxItems': 4,
                                                         'description': '[left, top, right, bottom] in pixels'}}}}},
        ]

    # -- running one ------------------------------------------------------
    def run(self, name: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
        handlers = {'measure_ink_at': self._measure_ink_at,
                    'snap_to_nearest_mark': self._snap,
                    'list_detected_marks': self._list_marks,
                    'read_axis_ticks': self._read_ticks,
                    'value_at_pixel': self._value_at_pixel,
                    'zoom': self._zoom}
        handler = handlers.get(name)
        if handler is None:
            return {'error': f'no measurement called {name}',
                    'available': sorted(handlers)}
        try:
            answer = handler(dict(arguments))
        except (KeyError, TypeError, ValueError) as exc:
            answer = {'error': f'{type(exc).__name__}: {exc}'}
        self.calls.append({'name': name, 'arguments': dict(arguments), 'answer': answer})
        return answer

    def _template_for(self, arguments: Mapping[str, Any]) -> list[float] | None:
        wanted = arguments.get('series_id')
        if wanted is not None and str(wanted) in self.templates:
            return self.templates[str(wanted)]
        if len(self.templates) == 1:
            return next(iter(self.templates.values()))
        return None

    def _measure_ink_at(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
        x, y = _finite(arguments['x'], 'x'), _finite(arguments['y'], 'y')
        inside = (self.plot_bbox[0] <= x <= self.plot_bbox[2]
                  and self.plot_bbox[1] <= y <= self.plot_bbox[3])
        template = self._template_for(arguments)
        if template is None:
            side = markers.mark_side(self.gray)
            box = [x - side / 2., y - side / 2., x + side / 2., y + side / 2.]
            grid = _ink_grid(self.gray, box)
            return {'x': x, 'y': y, 'inside_plot': inside,
                    'ink_fraction': round(_ink_share(self.gray, box), 4),
                    'matched_against': 'no series glyph is known yet, so this is plain ink density',
                    'ink_map': grid}
        report = markers.patch_report(self.gray, template, x, y)
        decision = markers.verdict(report)
        return {'x': x, 'y': y, 'inside_plot': inside,
                'measured': report, 'would_be_kept': decision['passed'],
                'reason': decision.get('reason'),
                'reading': self._say(inside, decision)}

    @staticmethod
    def _say(inside: bool, decision: Mapping[str, Any]) -> str:
        if decision['passed']:
            return 'there is a mark here that matches this series'
        reason = decision.get('reason')
        said = {'outside_image': 'that point is off the page',
                'window_is_mostly_empty': 'that window is bare paper; there is no mark here',
                'window_middle_is_empty_where_the_glyph_is_solid':
                    'that is a circle drawn around nothing: the middle is empty where this glyph is solid',
                'window_does_not_match_legend_glyph':
                    'there is ink here but it is not this series\' mark - it may be a line, a bar or another series'}
        text = said.get(str(reason), 'that window does not hold a mark of this series')
        return text if inside else text + ', and it is outside the plot box'

    def _snap(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
        x, y = _finite(arguments['x'], 'x'), _finite(arguments['y'], 'y')
        template = self._template_for(arguments)
        if template is None:
            return {'error': 'no glyph is known for that series yet, so there is nothing to snap to'}
        advice = markers.correction(self.gray, template, x, y)
        if advice is None:
            return {'found': False,
                    'reading': 'no window near that point matches this series'}
        return {'found': True, 'x': advice['x'], 'y': advice['y'],
                'dx': advice['dx'], 'dy': advice['dy'],
                'distance_px': advice['distance_px'], 'match': advice['score'],
                'reading': advice['advice']}

    def _list_marks(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
        region = arguments.get('region')
        marks = self.detected_marks
        if region is not None:
            left, top, right, bottom = (_finite(v, 'region') for v in region)
            marks = [m for m in marks
                     if left <= float(m.get('x', m.get('pixel', {}).get('x', float('nan')))) <= right
                     and top <= float(m.get('y', m.get('pixel', {}).get('y', float('nan')))) <= bottom]
        listed = [{'x': float(m.get('x', m.get('pixel', {}).get('x'))),
                   'y': float(m.get('y', m.get('pixel', {}).get('y'))),
                   'found_by': m.get('methods', m.get('method'))}
                  for m in marks[:MOST_MARKS_LISTED]]
        return {'count': len(marks), 'listed': listed,
                'truncated': len(marks) > len(listed),
                'reading': ('these are places with mark-like ink; which series each belongs to '
                            'is not measured, and some may be error bars or line joints')}

    def _read_ticks(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
        return {'image_size': self.image_size, 'plot_bbox': self.plot_bbox,
                'ticks': self.ticks or {'measured': False},
                'reading': ('the plot box is the full extent your reading should cover; '
                            'marks exist right out to its first and last columns')}

    def _value_at_pixel(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
        x, y = _finite(arguments['x'], 'x'), _finite(arguments['y'], 'y')
        if self.axes is None:
            return {'error': 'the axes are not calibrated yet; work in pixels for now'}
        x_axis, y_axis = self.axes.get('x'), self.axes.get('y')
        if x_axis is None or y_axis is None:
            return {'error': 'the axes are not calibrated yet; work in pixels for now'}
        return {'x_value': x_axis.value(x), 'y_value': y_axis.value(y),
                'x_unit': getattr(x_axis, 'unit', ''), 'y_unit': getattr(y_axis, 'unit', '')}

    def _zoom(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
        region = [_finite(v, 'region') for v in arguments['region']]
        grid = _ink_grid(self.gray, region)
        if not grid:
            return {'error': 'that region is empty or off the page'}
        return {'region': region, 'ink_map': grid,
                'legend': "' ' is blank paper and '@' is solid ink; each row of "
                          'characters spans the region evenly'}
