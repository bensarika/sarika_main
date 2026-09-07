import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

from chart_harness import plot_frame


def chart(path, box=(40, 30, 160, 120), gridlines=False, framed=False):
    """A plot drawn with axis rules, optionally gridded and fully boxed."""
    image = Image.new('RGB', (200, 160), 'white')
    drawn = ImageDraw.Draw(image)
    left, top, right, bottom = box
    drawn.line([(left, top), (left, bottom)], fill='black', width=2)
    drawn.line([(left, bottom), (right, bottom)], fill='black', width=2)
    if framed:
        drawn.line([(left, top), (right, top)], fill='black', width=2)
        drawn.line([(right, top), (right, bottom)], fill='black', width=2)
    if gridlines:
        for y in range(top + 20, bottom, 20):
            drawn.line([(left, y), (right, y)], fill='black', width=1)
    # Heavy axis labels, the thing the tick-counting box used to mistake for an axis.
    for y in range(top, bottom, 10):
        drawn.rectangle([left - 30, y, left - 12, y + 6], fill='black')
    image.save(path)
    return path


class PlotFrameTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_an_l_of_two_rules_gives_the_whole_box(self):
        found = plot_frame.frame(chart(self.root / 'l.png'))
        left, top, right, bottom = found['box']
        self.assertAlmostEqual(left, 40, delta=3)
        self.assertAlmostEqual(bottom, 120, delta=3)
        self.assertAlmostEqual(right, 160, delta=3)
        self.assertAlmostEqual(top, 30, delta=3)

    def test_the_label_column_is_not_taken_for_an_axis(self):
        box = plot_frame.box(chart(self.root / 'labelled.png'))
        self.assertGreater(box[0], 30)

    def test_gridlines_do_not_move_the_frame(self):
        plain = plot_frame.box(chart(self.root / 'plain.png'))
        gridded = plot_frame.box(chart(self.root / 'gridded.png', gridlines=True))
        for one, other in zip(plain, gridded):
            self.assertAlmostEqual(one, other, delta=3)

    def test_a_boxed_plot_is_measured_from_all_four_rules(self):
        found = plot_frame.frame(chart(self.root / 'boxed.png', framed=True))
        for measured, drawn in zip(found['box'], (40, 30, 160, 120)):
            self.assertAlmostEqual(measured, drawn, delta=3)

    def test_blank_paper_has_no_frame(self):
        Image.new('RGB', (60, 60), 'white').save(self.root / 'blank.png')
        self.assertIsNone(plot_frame.frame(self.root / 'blank.png'))
        self.assertIsNone(plot_frame.box(self.root / 'blank.png'))
