import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

from chart_harness import glyphs

BOX = (20, 20, 380, 280)


def blank():
    image = Image.new('RGB', (400, 300), 'white')
    return image, ImageDraw.Draw(image)


def dashed(drawn, start, end, on=8, off=8):
    """A broken connector line: the thing that repeats as faithfully as a mark."""
    x, y = start
    step = (end[0] - start[0]) / 40., (end[1] - start[1]) / 40.
    for piece in range(40):
        head = (x + step[0] * piece, y + step[1] * piece)
        tail = (head[0] + step[0] * .5, head[1] + step[1] * .5)
        drawn.line([head, tail], fill='black', width=2)


class GlyphTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def save(self, image, name):
        path = self.root / name
        image.save(path)
        return path

    def test_hollow_rings_are_found_and_counted(self):
        image, drawn = blank()
        places = [(60, 80), (120, 140), (200, 100), (260, 200), (320, 60)]
        for x, y in places:
            drawn.ellipse([x - 12, y - 12, x + 12, y + 12], outline='black', width=3)
        found = glyphs.find(self.save(image, 'rings.png'), BOX)
        self.assertEqual(len(found['marks']), len(places))

    def test_a_broken_connector_line_is_not_read_as_marks(self):
        image, drawn = blank()
        dashed(drawn, (40, 250), (360, 60))
        found = glyphs.find(self.save(image, 'dashes.png'), BOX)
        self.assertEqual(found['marks'], [])

    def test_marks_stamped_on_a_curve_are_found_and_the_curve_is_not(self):
        image, drawn = blank()
        drawn.line([(40, 250), (360, 80)], fill='black', width=2)
        places = [(80, 228), (160, 185), (240, 143), (320, 100)]
        for x, y in places:
            drawn.ellipse([x - 7, y - 7, x + 7, y + 7], fill='black')
        found = glyphs.find(self.save(image, 'curve.png'), BOX)
        self.assertEqual(len(found['marks']), len(places))

    def test_a_bare_curve_yields_nothing(self):
        image, drawn = blank()
        drawn.line([(40, 250), (200, 80), (360, 240)], fill='black', width=2)
        found = glyphs.find(self.save(image, 'bare.png'), BOX)
        self.assertEqual(found['marks'], [])

    def test_two_marks_printed_over_each_other_are_read_as_two(self):
        image, drawn = blank()
        for x, y in [(60, 80), (200, 100), (320, 60), (150, 220)]:
            drawn.ellipse([x - 12, y - 12, x + 12, y + 12], outline='black', width=3)
        drawn.ellipse([150 + 14 - 12, 220 - 12, 150 + 14 + 12, 220 + 12],
                      outline='black', width=3)
        found = glyphs.find(self.save(image, 'clump.png'), BOX)
        self.assertEqual(len(found['marks']), 5)

    def test_a_gridline_through_a_plot_leaves_no_marks_behind(self):
        image, drawn = blank()
        drawn.line([(40, 250), (360, 80)], fill='black', width=2)
        for y in (100, 160, 220):
            drawn.line([(20, y), (380, y)], fill='black', width=1)
        found = glyphs.find(self.save(image, 'grid.png'), BOX)
        self.assertEqual(found['marks'], [])

    def test_a_dash_is_told_from_a_stamp_by_its_shape(self):
        import numpy as np
        dash = np.zeros((3, 14), bool)
        dash[:] = True
        ring = np.zeros((14, 14), bool)
        ring[0, :] = ring[-1, :] = ring[:, 0] = ring[:, -1] = True
        self.assertFalse(glyphs.shaped_like_a_stamp(dash))
        self.assertTrue(glyphs.shaped_like_a_stamp(ring))
