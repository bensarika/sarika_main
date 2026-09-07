import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

from chart_harness import placed


def figure(path, dots=((40, 30),), radius=4, size=(120, 90), bar=None):
    """A blank sheet with filled dots on it, and optionally a thin vertical bar."""
    page = np.ones((size[1], size[0]), dtype=np.uint8) * 255
    ys, xs = np.mgrid[:size[1], :size[0]]
    for x, y in dots:
        page[((xs - x) ** 2 + (ys - y) ** 2) <= radius ** 2] = 0
    if bar:
        x, top, bottom = bar
        page[top:bottom, x - 1:x + 2] = 0
    Image.fromarray(page).save(path)
    return path


class PlacedTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.dir = Path(self.temp.name)
        self.image = figure(self.dir / 'figure.png')

    def tearDown(self):
        self.temp.cleanup()

    def test_a_click_on_a_mark_reports_the_body_it_landed_on(self):
        measured = placed.measure(self.image, 40, 30)
        self.assertTrue(measured['on_ink'])
        self.assertEqual(measured['distance_to_ink_px'], 0)
        self.assertGreater(measured['ink_body']['pixels'], 20)
        self.assertAlmostEqual(measured['ink_body']['x'], 40, delta=1)

    def test_a_click_on_blank_paper_says_so_and_invents_no_datapoint(self):
        mark = placed.place(self.image, 100, 80, 'series a', reach=9)
        self.assertFalse(mark['measured']['on_ink'])
        self.assertGreater(mark['measured']['distance_to_ink_px'], 9)
        self.assertNotIn('carried_onto_the_ink', mark)
        self.assertEqual((mark['x'], mark['y']), (100, 80))
        self.assertIn('away', mark['measured']['reading'])

    def test_a_click_beside_a_mark_is_carried_onto_the_body_it_was_aimed_at(self):
        mark = placed.place(self.image, 43, 32, 'series a', reach=9)
        self.assertTrue(mark['carried_onto_the_ink'])
        self.assertAlmostEqual(mark['x'], 40, delta=1)
        self.assertAlmostEqual(mark['y'], 30, delta=1)
        self.assertEqual(mark['clicked'], {'x': 43., 'y': 32.})

    def test_a_click_near_a_line_is_left_where_the_person_put_it(self):
        # A long thin body is a curve or an error bar; snapping to its centre of
        # mass would move the mark somewhere nobody pointed at.
        image = figure(self.dir / 'bar.png', dots=(), bar=(60, 10, 80))
        mark = placed.place(image, 61, 20, 'series a', reach=9)
        self.assertNotIn('carried_onto_the_ink', mark)
        self.assertEqual((mark['x'], mark['y']), (61., 20.))
        self.assertGreater(mark['measured']['ink_body']['height'], 9)

    def test_a_click_off_the_page_is_refused_rather_than_measured(self):
        measured = placed.measure(self.image, 500, 500)
        self.assertFalse(measured['on_the_page'])
        self.assertNotIn('ink_body', measured)

    def test_the_reach_a_click_may_be_carried_comes_from_the_measured_marks(self):
        self.assertEqual(placed.reach_from([4, 6, 8]), 6)
        self.assertIsNone(placed.reach_from([]))
        self.assertIsNone(placed.reach_from([None, 0]))

    def test_a_mark_is_only_data_or_not_data(self):
        with self.assertRaises(ValueError):
            placed.place(self.image, 40, 30, 'series a', kind='maybe')

    def test_the_sentence_handed_to_the_reader_states_the_group_and_the_pixels(self):
        mark = placed.place(self.image, 40, 30, 'bbmAb2', reach=9)
        said = placed.sentence(mark)
        self.assertIn('bbmAb2', said)
        self.assertIn('x=40', said)
        self.assertIn('body', said)
        refused = placed.sentence(placed.place(self.image, 100, 80, None, 'not_data', reach=9))
        self.assertIn('no datapoint', refused)
        self.assertIn('do not report one there', refused)

    def test_marks_are_kept_with_the_run_so_corrections_outlive_it(self):
        placed.record(self.dir / 'run', placed.place(self.image, 40, 30, 'a', reach=9))
        placed.record(self.dir / 'run', placed.place(self.image, 100, 80, 'b',
                                                     'not_data', reach=9))
        held = placed.held(self.dir / 'run')
        self.assertEqual(['a', 'b'], [m['group'] for m in held])
        self.assertEqual(['data', 'not_data'], [m['kind'] for m in held])
        self.assertEqual([], placed.held(self.dir / 'nothing-here'))
        lines = (self.dir / 'run' / 'placed_marks.jsonl').read_text().splitlines()
        self.assertEqual(2, len(lines))
        self.assertEqual('watcher', json.loads(lines[0])['placed_by'])


if __name__ == '__main__':
    unittest.main()
