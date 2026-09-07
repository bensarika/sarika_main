import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

from chart_harness import panel_fit


def page(marks=(), size=(200, 160)):
    """A sheet of paper with black rectangles printed on it."""
    canvas = np.full((size[1], size[0]), 255, dtype=np.uint8)
    for left, top, right, bottom in marks:
        canvas[top:bottom, left:right] = 0
    path = Path(tempfile.mkdtemp()) / 'page.png'
    Image.fromarray(canvas).save(path)
    return path


class PanelBoxesThatCutTheFigure(unittest.TestCase):
    def test_an_edge_through_the_drawing_is_carried_out_to_blank_paper(self):
        drawn = page([(40, 30, 150, 120)])
        box, note = panel_fit.widen(drawn, [40, 30, 120, 120])
        self.assertEqual([40., 30., 150., 120.], box)
        self.assertEqual('panel_box_grown_off_the_ink', note['code'])
        self.assertEqual([0, 0, 30, 0], note['moved'])

    def test_a_box_shifted_left_of_the_plot_recovers_both_sides(self):
        drawn = page([(60, 30, 150, 120)])
        box, _ = panel_fit.widen(drawn, [50, 30, 140, 120])
        self.assertEqual([50., 30., 150., 120.], box)

    def test_a_box_already_standing_in_white_space_is_left_alone(self):
        drawn = page([(60, 40, 120, 100)])
        box, note = panel_fit.widen(drawn, [50, 30, 140, 110])
        self.assertEqual([50., 30., 140., 110.], box)
        self.assertIsNone(note)

    def test_the_gap_the_box_already_spans_is_crossed_but_the_gutter_is_not(self):
        # Two panels: the box cuts the left one, whose own internal gap is wider
        # than nothing but far narrower than the blank gutter between panels.
        drawn = page([(20, 30, 60, 120), (64, 30, 90, 120), (150, 30, 190, 120)])
        box, note = panel_fit.widen(drawn, [20, 30, 70, 120])
        self.assertEqual([20., 30., 90., 120.], box)
        self.assertEqual(4, note['white_space_px']['across'])

    def test_a_box_running_to_the_edge_of_the_sheet_stops_there(self):
        drawn = page([(150, 30, 200, 120)])
        box, _ = panel_fit.widen(drawn, [140, 30, 180, 120])
        self.assertEqual(200., box[2])

    def test_a_box_with_no_area_is_returned_untouched(self):
        drawn = page([(40, 30, 150, 120)])
        box, note = panel_fit.widen(drawn, [40, 30, 41, 120])
        self.assertEqual([40., 30., 41., 120.], box)
        self.assertIsNone(note)

    def test_a_top_edge_through_the_drawing_moves_up(self):
        drawn = page([(40, 20, 150, 120)])
        box, note = panel_fit.widen(drawn, [40, 60, 150, 120])
        self.assertEqual([40., 20., 150., 120.], box)
        self.assertEqual(40, note['moved'][1])


if __name__ == '__main__':
    unittest.main()
