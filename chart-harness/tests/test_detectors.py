"""Each finder is exercised on the kind of figure it exists for, and on one it
cannot read, because a method that invents marks in a figure it does not
understand is worse than one that stays silent."""
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

from chart_harness import detectors

PLOT = [60., 40., 560., 360.]
DOTS = [(150, 300), (250, 240), (350, 180), (450, 120)]


def line_chart(path, colour='black', radius=6):
    image = Image.new('RGB', (600, 400), 'white')
    draw = ImageDraw.Draw(image)
    draw.rectangle(PLOT, outline='black')
    draw.line(DOTS, fill=colour, width=2)
    for x, y in DOTS:
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=colour)
    image.save(path)
    return path


def bar_chart(path, heights=(80, 140, 200, 260)):
    image = Image.new('RGB', (600, 400), 'white')
    draw = ImageDraw.Draw(image)
    draw.rectangle(PLOT, outline='black')
    for index, height in enumerate(heights):
        left = 120 + index * 100
        draw.rectangle([left, 360 - height, left + 40, 360], fill='black')
    image.save(path)
    return path


class Colour(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())

    def test_a_coloured_series_is_separated_by_its_own_hue(self):
        image = Image.new('RGB', (600, 400), 'white')
        draw = ImageDraw.Draw(image)
        draw.rectangle(PLOT, outline='black')
        for x, y in DOTS:
            draw.ellipse((x - 6, y - 6, x + 6, y + 6), fill='red')
        for x, y in DOTS:
            draw.ellipse((x - 6, y + 44, x + 6, y + 56), fill='blue')
        path = self.dir / 'colour.png'
        image.save(path)
        found = detectors.by_colour(path, PLOT)
        hues = {m['colour_hue'] for m in found}
        self.assertEqual(2, len(hues))
        self.assertEqual(2 * len(DOTS), len(found))

    def test_a_grey_figure_reports_no_colour_groups_rather_than_guessing(self):
        self.assertEqual([], detectors.by_colour(line_chart(self.dir / 'grey.png'), PLOT))


class BarTops(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())

    def test_each_bar_is_read_at_its_top_edge(self):
        heights = (80, 140, 200, 260)
        found = detectors.bar_tops(bar_chart(self.dir / 'bars.png', heights), PLOT)
        self.assertEqual(len(heights), len(found))
        for bar, height in zip(found, heights):
            self.assertAlmostEqual(360 - height, bar['y'], delta=3)

    def test_a_line_chart_yields_no_bars(self):
        self.assertEqual([], detectors.bar_tops(line_chart(self.dir / 'line.png'), PLOT))


class Curve(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())

    def test_following_the_curve_reaches_the_marks_printed_on_it(self):
        found = detectors.on_curve(line_chart(self.dir / 'line.png'), PLOT)
        self.assertEqual(len(DOTS), len(found))
        for (x, y), mark in zip(DOTS, found):
            self.assertLess(abs(mark['x'] - x), 4)
            self.assertLess(abs(mark['y'] - y), 4)

    def test_a_bare_curve_holds_no_marks(self):
        image = Image.new('RGB', (600, 400), 'white')
        draw = ImageDraw.Draw(image)
        draw.rectangle(PLOT, outline='black')
        draw.line(DOTS, fill='black', width=2)
        path = self.dir / 'bare.png'
        image.save(path)
        self.assertEqual([], detectors.on_curve(path, PLOT))


class Pool(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())

    def test_every_method_runs_and_agreements_are_recorded(self):
        report = detectors.run_all(line_chart(self.dir / 'line.png'), PLOT,
                                   outdir=self.dir / 'mined')
        self.assertEqual({'thickness', 'colour', 'shape', 'bar_top', 'curve',
                          'glyph'}, set(report['methods']))
        self.assertGreaterEqual(report['corroborated'], len(DOTS))
        for mark in report['pooled']:
            if mark['corroborated']:
                self.assertGreater(len(mark['found_by']), 1)
        agreed = [m for m in report['pooled'] if 'curve' in m['found_by']
                  and 'thickness' in m['found_by']]
        self.assertEqual(len(DOTS), len(agreed))

    def test_a_method_that_fails_does_not_end_the_run(self):
        report = detectors.run_all(line_chart(self.dir / 'line.png'),
                                   [0., 0., 0., 0.], outdir=self.dir / 'mined')
        self.assertEqual([], report['pooled'])
        self.assertEqual(0, report['corroborated'])

    def test_a_bar_chart_is_read_by_the_bar_method_the_others_stay_quiet(self):
        report = detectors.run_all(bar_chart(self.dir / 'bars.png'), PLOT,
                                   methods=('bar_top', 'colour'))
        self.assertEqual(4, report['counts']['bar_top'])
        self.assertEqual(0, report['counts']['colour'])


if __name__ == '__main__':
    unittest.main()
