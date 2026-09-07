import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

from chart_harness import box_check, evaluate


def page(path, box=(40, 30, 160, 120), dots=((60, 60), (100, 80), (140, 100))):
    """A small plot: axis rules, ticks against them, and a few round marks."""
    im = Image.new('RGB', (200, 160), 'white')
    d = ImageDraw.Draw(im)
    left, top, right, bottom = box
    d.line([(left, top), (left, bottom)], fill='black', width=2)
    d.line([(left, bottom), (right, bottom)], fill='black', width=2)
    for x in range(left, right + 1, 20):
        d.line([(x, bottom), (x, bottom + 5)], fill='black', width=2)
    for y in range(top, bottom + 1, 15):
        d.line([(left - 5, y), (left, y)], fill='black', width=2)
    for x, y in dots:
        d.ellipse([x - 3, y - 3, x + 3, y + 3], fill='black')
    im.save(path)
    return path


class BoxCheckTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.image = page(self.root / 'chart.png')

    def tearDown(self):
        self.temp.cleanup()

    def test_a_box_standing_in_blank_paper_holds(self):
        said = box_check.score(self.image, [20, 15, 180, 140])
        self.assertTrue(said['holds'])
        self.assertEqual(said['edges_cutting_ink'], [])
        self.assertGreater(said['share_of_the_page_ink_inside'], 0.9)

    def test_an_edge_standing_in_the_middle_of_the_drawing_is_named(self):
        # Right edge drawn through the middle of a mark, bottom through the rule.
        cut = box_check.score(self.image, [20, 15, 101, 90])['edges_cutting_ink']
        self.assertIn('right', cut)
        self.assertIn('bottom', cut)

    def test_the_loop_moves_the_box_off_the_ink_and_says_it_did(self):
        settled, attempts = box_check.settle(self.image, [20, 15, 120, 90])
        self.assertTrue(attempts[-1]['holds'])
        self.assertGreater(settled[2], 120)
        self.assertGreater(len(attempts), 1)
        self.assertIn('carried off the ink', box_check.sentence(attempts))
        # Scoring a box that was already right leaves it alone.
        again, once = box_check.settle(self.image, settled)
        self.assertEqual(again, settled)
        self.assertEqual(len(once), 1)
        self.assertIn('blank paper on all four sides', box_check.sentence(once))

    def test_a_box_that_leaves_measured_marks_outside_says_so_in_numbers(self):
        marks = [{'x': 60, 'y': 60}, {'x': 100, 'y': 80}, {'x': 900, 'y': 80}]
        held = box_check.holds_marks([40, 30, 160, 120], marks)
        self.assertEqual(held['inside'], 2)
        self.assertEqual(held['share_of_the_marks_inside'], 0.667)
        self.assertEqual(held['outside'], [{'x': 900., 'y': 80.}])
        self.assertIsNone(box_check.holds_marks([0, 0, 1, 1], []))

    def test_a_box_too_small_to_measure_is_reported_not_settled(self):
        self.assertEqual(box_check.score(self.image, [10, 10, 11, 11])['edges_cutting_ink'],
                         ['degenerate'])
        settled, attempts = box_check.settle(self.image, [10, 10, 11, 11])
        self.assertEqual(len(attempts), 1)
        self.assertEqual(settled, [10., 10., 11., 11.])


class EvaluateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.image = page(self.root / 'chart.png')

    def tearDown(self):
        self.temp.cleanup()

    def test_a_figure_is_scored_without_asking_any_reader(self):
        said = evaluate.look(self.image)
        self.assertGreater(said['ticks']['across'], 1)
        self.assertIsNotNone(said['plot_bbox'])
        self.assertIn('holds', said['box'])
        self.assertIn('found', said['marks'])
        self.assertNotIn('against_the_count_a_person_made', said)

    def test_a_count_written_beside_the_figure_is_what_we_are_scored_against(self):
        Path(str(self.image).replace('.png', '.expected.json')).write_text(
            json.dumps({'marks': 3, 'plot_bbox': [40, 30, 160, 120]}))
        said = evaluate.look(self.image)
        against = said['against_the_count_a_person_made']
        self.assertEqual(against['expected'], 3)
        self.assertEqual(against['off_by'], said['marks']['found'] - 3)
        self.assertEqual(len(said['against_the_box_a_person_drew']['moved']), 4)

    def test_the_report_is_written_and_summarised(self):
        out = self.root / 'report.json'
        report = evaluate.run([self.image], out)
        self.assertEqual(report['summary']['figures'], 1)
        self.assertEqual(report['summary']['boxes_measured'], 1)
        self.assertEqual(json.loads(out.read_text())['summary'], report['summary'])

    def test_a_page_with_no_measurable_axes_is_reported_not_skipped(self):
        blank = self.root / 'blank.png'
        Image.new('RGB', (60, 60), 'white').save(blank)
        said = evaluate.look(blank)
        self.assertIsNone(said['plot_bbox'])
        self.assertIn('no plot box', said['note'])


if __name__ == '__main__':
    unittest.main()
