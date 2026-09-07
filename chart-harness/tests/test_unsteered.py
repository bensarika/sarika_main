import json
import tempfile
import unittest
from pathlib import Path

from chart_harness import unsteered


class Reader:
    def __init__(self, answer):
        self.answer = answer
        self.asked = []

    def complete(self, name, text, images=None, schema=None, **kwargs):
        self.asked.append({'name': name, 'text': text, 'images': list(images or []),
                           'schema': schema, 'extra': kwargs})
        return self.answer


READING = {'x_axis': {'label': 'Time', 'unit': 'h'},
           'y_axis': {'label': 'Concentration', 'unit': 'ug/mL', 'scale': 'log'},
           'series': [{'label': 'a', 'points': [{'x': 0, 'y': 100}, {'x': 100, 'y': 50}]},
                      {'label': 'b', 'points': [{'x': 0, 'y': 10}]}]}


class UnsteeredTests(unittest.TestCase):
    def test_the_lane_is_one_call_with_the_image_and_nothing_else(self):
        reader = Reader(READING)
        unsteered.ask(reader, Path('/tmp/figure.png'))
        asked = reader.asked[0]
        self.assertEqual(asked['images'], [Path('/tmp/figure.png')])
        self.assertEqual(asked['extra'], {})
        self.assertNotIn('measure_ink_at', asked['text'])
        self.assertIn('coordinates', asked['text'])
        self.assertIn('legend', asked['text'])

    def test_the_prompt_asks_for_marks_and_not_for_bars_or_lines(self):
        self.assertIn('error bars', unsteered.PROMPT)
        self.assertIn('best reading', unsteered.PROMPT)
        self.assertNotIn('unsupported', unsteered.PROMPT)

    def test_points_are_read_out_of_whatever_shape_the_answer_took(self):
        self.assertEqual(unsteered.points(READING),
                         [('a', 0., 100.), ('a', 100., 50.), ('b', 0., 10.)])
        self.assertEqual(unsteered.points({'series': [{'id': 's1', 'seeds': [{'x': 1, 'y': 2}]}]}),
                         [('s1', 1., 2.)])
        self.assertEqual(unsteered.points({'series': [{'points': [{'x': 'n/a', 'y': 2}]}]}), [])
        self.assertEqual(unsteered.points(None), [])

    def test_the_separation_is_a_share_of_the_data_span_not_a_pixel_count(self):
        rows = [{'series_label': 'a', 'x': 0, 'y': 100}, {'series_label': 'a', 'x': 100, 'y': 50},
                {'series_label': 'b', 'x': 0, 'y': 10}]
        exact = unsteered.compare(READING, rows)
        self.assertEqual(exact['separation_as_a_share_of_the_span']['median'], 0)
        self.assertEqual(exact['groups_both_named'], ['a', 'b'])
        # Stated against a reading whose x span is ten times wider, the same
        # answer's separation is still a share of that span rather than a raw
        # distance, so the number means the same thing on either axis.
        wide = [{'series_label': 'a', 'x': 0, 'y': 100}, {'series_label': 'a', 'x': 1000, 'y': 50},
                {'series_label': 'b', 'x': 0, 'y': 10}]
        off = unsteered.compare(READING, wide)
        self.assertGreater(off['separation_as_a_share_of_the_span']['worst'], 0)
        self.assertEqual(off['separation_as_a_share_of_the_span']['x_span'], 1000)

    def test_a_comparison_states_the_counts_and_passes_no_judgment(self):
        report = unsteered.compare(READING, [{'series_label': 'a', 'x': 0, 'y': 100}])
        self.assertEqual(report['points_unaided'], 3)
        self.assertEqual(report['points_kept_by_the_harness'], 1)
        self.assertNotIn('pass', report)
        self.assertNotIn('status', report)
        self.assertIn('median', report['reading'])

    def test_nothing_on_one_side_is_reported_rather_than_scored(self):
        empty = unsteered.compare({'series': []}, [{'series_label': 'a', 'x': 1, 'y': 2}])
        self.assertIn('nothing to compare', empty['reading'])
        self.assertNotIn('separation_as_a_share_of_the_span', empty)
        self.assertIn('nothing to compare', unsteered.compare(READING, [])['reading'])

    def test_rows_without_axis_values_are_left_out_of_the_comparison(self):
        report = unsteered.compare(READING, [{'series_label': 'a', 'x': None, 'y': None},
                                             {'series_label': 'a', 'x': 0, 'y': 100}])
        self.assertEqual(report['points_kept_by_the_harness'], 1)

    def test_the_summary_names_what_the_unaided_reader_saw(self):
        said = unsteered.summary(READING)
        self.assertIn('3 points', said)
        self.assertIn('2 series', said)
        self.assertIn('no tools', said)

    def test_the_answer_is_kept_beside_the_reading_not_inside_it(self):
        with tempfile.TemporaryDirectory() as temp:
            path = unsteered.write(Path(temp) / 'unsteered_reading.json', READING)
            self.assertEqual(json.loads(path.read_text())['series'][0]['label'], 'a')


if __name__ == '__main__':
    unittest.main()
