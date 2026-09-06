import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

from chart_harness import axis_detect


def chart(path):
    """Axes at x=40..340 (row 260) with ticks every 60 px, y ticks every 50 px."""
    image = Image.new('RGB', (400, 300), 'white')
    draw = ImageDraw.Draw(image)
    draw.line((40, 260, 340, 260), fill='black', width=2)
    draw.line((40, 40, 40, 260), fill='black', width=2)
    for x in range(40, 341, 60):
        draw.line((x, 262, x, 272), fill='black', width=2)
    for y in range(60, 261, 50):
        draw.line((28, y, 38, y), fill='black', width=2)
    image.save(path)


class AxisDetectTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'chart.png'
        chart(self.path)

    def tearDown(self):
        self.temp.cleanup()

    def test_detects_axis_rules_and_tick_centers(self):
        detected = axis_detect.detect_ticks(self.path)
        self.assertAlmostEqual(detected['x_axis_row'], 260, delta=1)
        self.assertAlmostEqual(detected['y_axis_col'], 40, delta=1)
        self.assertEqual(len(detected['x_tick_pixels']), 6)
        self.assertAlmostEqual(detected['x_tick_pixels'][0], 40.5, delta=1.)
        self.assertEqual(len(detected['y_tick_pixels']), 5)

    def test_consistent_but_globally_shifted_anchors_are_rejected(self):
        good = {'x_axis': {'anchors': [{'pixel': 40, 'value': 0}, {'pixel': 340, 'value': 500}]},
                'y_axis': {'anchors': [{'pixel': 60, 'value': 100}, {'pixel': 260, 'value': 1}]}}
        shifted = {'x_axis': {'anchors': [{'pixel': 20, 'value': 0}, {'pixel': 320, 'value': 500}]},
                   'y_axis': good['y_axis']}
        self.assertTrue(axis_detect.crosscheck(self.path, good, 6.)['agrees'])
        report = axis_detect.crosscheck(self.path, shifted, 6.)
        self.assertFalse(report['agrees'])
        self.assertFalse(report['inconclusive'])
        self.assertGreater(report['axes']['x_axis']['max_offset_px'], 6.)

    def test_blank_image_is_inconclusive_rather_than_disagreeing(self):
        blank = Path(self.temp.name) / 'blank.png'
        Image.new('RGB', (400, 300), 'white').save(blank)
        report = axis_detect.crosscheck(blank, {'x_axis': {'anchors': [{'pixel': 1, 'value': 0}]}}, 6.)
        self.assertTrue(report['inconclusive'])
        self.assertFalse(report['agrees'])

    def test_repair_snaps_reader_values_onto_detected_ticks(self):
        detected = axis_detect.detect_ticks(self.path)
        interpretation = {'x_axis': {'scale': 'linear', 'unit': 'h',
                                     'anchors': [{'pixel': 20, 'value': 0}, {'pixel': 320, 'value': 500}]}}
        repaired = {'x_axis': {'scale': 'linear', 'unit': 'h',
                               'anchors': [{'pixel': 42, 'value': 0}, {'pixel': 339, 'value': 500}]},
                    'status': 'readable'}
        applied = axis_detect.apply_repair(interpretation, repaired, detected, 6.)
        self.assertEqual(sorted(applied), ['x_axis'])
        self.assertEqual([a['pixel'] for a in interpretation['x_axis']['anchors']],
                         [detected['x_tick_pixels'][0], detected['x_tick_pixels'][-1]])
        self.assertTrue(axis_detect.crosscheck(self.path, interpretation, 6.)['agrees'])

    def test_repair_ignores_values_that_match_no_detected_tick(self):
        detected = axis_detect.detect_ticks(self.path)
        interpretation = {'x_axis': {'anchors': []}}
        repaired = {'x_axis': {'anchors': [{'pixel': 200, 'value': 1}, {'pixel': 205, 'value': 2}]}}
        self.assertEqual(axis_detect.apply_repair(interpretation, repaired, detected, 2.), {})

    def test_clamp_plot_bbox_trims_to_measured_axis_rules(self):
        detected = axis_detect.detect_ticks(self.path)
        clamped, changed = axis_detect.clamp_plot_bbox([10, 30, 340, 290], detected)
        self.assertTrue(changed)
        self.assertEqual(clamped[0], float(detected['y_axis_col']))
        self.assertEqual(clamped[3], float(detected['x_axis_row']))
        inside = [float(detected['y_axis_col']), 30., 340., float(detected['x_axis_row'])]
        self.assertEqual(axis_detect.clamp_plot_bbox(inside, detected), (inside, False))

    def test_repair_packet_supplies_measured_geometry_and_label_strips(self):
        detected = axis_detect.detect_ticks(self.path)
        prompt, images = axis_detect.repair_packet(self.path, detected, Path(self.temp.name) / 'repair')
        self.assertIn('Do NOT move, re-estimate or invent them', prompt)
        self.assertIn('Detected x tick pixel columns', prompt)
        self.assertEqual(images[0], self.path)
        self.assertEqual(len(images), 3)
        for image in images[1:]:
            self.assertTrue(image.exists())


if __name__ == '__main__':
    unittest.main()
