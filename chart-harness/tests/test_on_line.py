import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

from chart_harness import on_line


def figure(path, curves=((120, 60), (150, 100)), marks=True):
    """Two drawn curves with dots printed on them, plus an axis frame."""
    image = Image.new('RGB', (300, 200), 'white')
    draw = ImageDraw.Draw(image)
    draw.line((20, 180, 280, 180), fill='black', width=1)
    draw.line((20, 20, 20, 180), fill='black', width=1)
    for start, end in curves:
        draw.line((40, start, 260, end), fill='black', width=1)
    if marks:
        for start, end in curves[:1]:
            for step in range(5):
                x = 40 + step * 55
                y = start + (end - start) * step / 4.
                draw.ellipse((x - 4, y - 4, x + 4, y + 4), fill='black')
    image.save(path)
    return path


class OnCurveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = figure(Path(self.temp.name) / 'fig.png')

    def tearDown(self):
        self.temp.cleanup()

    def test_a_mark_on_the_curve_passes_and_one_in_open_paper_does_not(self):
        report = on_line.check(self.path, [20, 20, 280, 180], [
            {'candidate_id': 'on', 'pixel_x': 95, 'pixel_y': 105},
            {'candidate_id': 'off', 'pixel_x': 250, 'pixel_y': 40}], mark_width=8)
        by_id = {m['candidate_id']: m for m in report['points']}
        self.assertTrue(by_id['on']['on_curve'])
        self.assertFalse(by_id['off']['on_curve'])
        self.assertGreater(by_id['off']['distance_px'], by_id['on']['distance_px'])
        self.assertEqual(1, report['off_curve'])

    def test_a_drawn_curve_nobody_sampled_is_reported_not_passed_over(self):
        report = on_line.check(self.path, [20, 20, 280, 180], [
            {'candidate_id': 'a', 'pixel_x': 95, 'pixel_y': 105}], mark_width=8)
        self.assertTrue(report['unsampled_curves'], 'the second curve carries no mark')
        self.assertIn('carries no mark', on_line.advice(report))

    def test_the_axis_rules_are_not_mistaken_for_unsampled_series(self):
        report = on_line.check(self.path, [20, 20, 280, 180], [], mark_width=8)
        for curve in report['curves']:
            self.assertLess(curve['bbox'][2] - curve['bbox'][0], 260,
                            'the frame rule should not be counted as a curve')


class ColumnTests(unittest.TestCase):
    def points(self, rows):
        return [{'candidate_id': f'c{i}', 'series': s, 'pixel_x': x, 'pixel_y': y}
                for i, (s, x, y) in enumerate(rows)]

    def test_marks_at_the_same_sampling_time_stand_in_one_column(self):
        columns = on_line.columns(self.points([
            ('a', 100, 50), ('b', 102, 80), ('a', 200, 60), ('b', 201, 90)]), 8)
        self.assertEqual(2, len(columns))
        self.assertEqual([['a', 'b'], ['a', 'b']], [c['series_order'] for c in columns])

    def test_one_series_twice_in_a_column_is_reported_as_doubled(self):
        columns = on_line.columns(self.points([
            ('a', 100, 50), ('a', 103, 80), ('b', 101, 120)]), 8)
        self.assertEqual([['a']], [c['doubled'] for c in columns])

    def test_a_series_missing_from_a_column_is_bracketed_by_its_neighbours(self):
        columns = on_line.columns(self.points([
            ('a', 100, 50), ('b', 101, 80), ('c', 102, 110),
            ('a', 200, 55), ('c', 202, 115)]), 8)
        holes = on_line.gaps_in_columns(columns, ['a', 'b', 'c'])
        self.assertEqual(1, len(holes))
        self.assertEqual('b', holes[0]['series'])
        self.assertEqual({'above': 'a', 'below': 'c', 'pixel_y_above': 55, 'pixel_y_below': 115},
                         holes[0]['between'])

    def test_where_two_series_cross_their_order_is_not_used_to_place_a_gap(self):
        columns = on_line.columns(self.points([
            ('a', 100, 50), ('b', 101, 80), ('c', 102, 110),
            ('a', 200, 90), ('b', 201, 60),
            ('a', 300, 95), ('c', 302, 115)]), 8)
        self.assertIn(('a', 'b'), [tuple(p) for p in on_line.crossings(columns)])
        holes = {h['series']: h for h in on_line.gaps_in_columns(columns, ['a', 'b', 'c'])}
        self.assertIsNone(holes['b']['between'], 'a crossing series has no reliable place')


if __name__ == '__main__':
    unittest.main()
