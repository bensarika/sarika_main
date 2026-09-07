import json
import tempfile
import unittest
from pathlib import Path

from chart_harness import figure_tools, markers, provider

from tests.test_markers import MARKS, PLOT, chart


def tools(directory):
    image = chart(directory / 'chart.png')
    gray = markers.load_gray(image)
    template = markers.legend_glyphs(gray, PLOT, 3)[0]['glyph_bbox']
    return figure_tools.FigureTools(
        image, PLOT, {'s1': template},
        detected_marks=[{'x': float(x), 'y': float(y), 'methods': ['thickness']}
                        for x, y in MARKS],
        ticks={'x_pixels': [200., 380., 560.], 'y_pixels': [40., 200., 360.]})


class Measuring(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.tools = tools(self.dir)

    def test_a_real_mark_measures_as_keepable(self):
        answer = self.tools.run('measure_ink_at', {'x': MARKS[0][0], 'y': MARKS[0][1], 'series_id': 's1'})
        self.assertTrue(answer['would_be_kept'])
        self.assertTrue(answer['inside_plot'])

    def test_bare_paper_measures_as_no_mark_and_says_so_plainly(self):
        answer = self.tools.run('measure_ink_at', {'x': 300., 'y': 60., 'series_id': 's1'})
        self.assertFalse(answer['would_be_kept'])
        self.assertIn('no mark', answer['reading'])

    def test_a_point_off_the_plot_is_reported_as_off_the_plot(self):
        answer = self.tools.run('measure_ink_at', {'x': 20., 'y': 380., 'series_id': 's1'})
        self.assertFalse(answer['inside_plot'])

    def test_a_point_beside_a_mark_is_snapped_onto_it(self):
        x, y = MARKS[1]
        answer = self.tools.run('snap_to_nearest_mark', {'x': x + 6., 'y': y - 9., 'series_id': 's1'})
        self.assertTrue(answer['found'])
        self.assertAlmostEqual(x, answer['x'], delta=2)
        self.assertAlmostEqual(y, answer['y'], delta=2)
        self.assertIn('down', answer['reading'])

    def test_marks_can_be_listed_within_a_region(self):
        answer = self.tools.run('list_detected_marks', {'region': [240., 200., 360., 320.]})
        self.assertEqual(2, answer['count'])

    def test_the_ticks_and_the_plot_box_come_back_measured(self):
        answer = self.tools.run('read_axis_ticks', {})
        self.assertEqual(PLOT, answer['plot_bbox'])
        self.assertEqual(3, len(answer['ticks']['x_pixels']))

    def test_zoom_draws_the_ink_of_a_mark_as_a_readable_map(self):
        x, y = MARKS[0]
        answer = self.tools.run('zoom', {'region': [x - 12, y - 12, x + 12, y + 12]})
        self.assertTrue(any('@' in line for line in answer['ink_map']))

    def test_axis_units_are_refused_plainly_before_calibration(self):
        answer = self.tools.run('value_at_pixel', {'x': 300., 'y': 200.})
        self.assertIn('not calibrated', answer['error'])

    def test_an_unknown_measurement_is_answered_not_raised(self):
        answer = self.tools.run('read_my_mind', {})
        self.assertIn('no measurement', answer['error'])
        self.assertIn('measure_ink_at', answer['available'])

    def test_every_measurement_asked_for_is_kept_as_evidence(self):
        self.tools.run('measure_ink_at', {'x': MARKS[0][0], 'y': MARKS[0][1], 'series_id': 's1'})
        self.assertEqual('measure_ink_at', self.tools.calls[0]['name'])

    def test_the_offered_measurements_name_the_series_of_this_figure(self):
        names = [t['function']['name'] for t in self.tools.schemas()]
        self.assertIn('snap_to_nearest_mark', names)
        measure = next(t for t in self.tools.schemas() if t['function']['name'] == 'measure_ink_at')
        self.assertEqual(['s1'], measure['function']['parameters']['properties']['series_id']['enum'])


class AnsweringWhatWasAsked(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.tools = tools(self.dir)

    def call(self, name, arguments):
        return {'id': 'call-1', 'type': 'function',
                'function': {'name': name, 'arguments': arguments}}

    def test_a_measurement_comes_back_as_a_tool_message(self):
        message = provider.answer_of_a_measurement(
            self.call('measure_ink_at', json.dumps({'x': MARKS[0][0], 'y': MARKS[0][1], 'series_id': 's1'})),
            self.tools)
        self.assertEqual('tool', message['role'])
        self.assertEqual('call-1', message['tool_call_id'])
        self.assertTrue(json.loads(message['content'])['would_be_kept'])

    def test_unreadable_arguments_are_answered_rather_than_ending_the_run(self):
        message = provider.answer_of_a_measurement(
            self.call('measure_ink_at', 'not json at all'), self.tools)
        self.assertIn('error', json.loads(message['content']))

    def test_a_measurement_that_throws_is_reported_as_a_fact(self):
        class Breaks:
            def run(self, name, arguments):
                raise RuntimeError('the page went missing')
        message = provider.answer_of_a_measurement(
            self.call('measure_ink_at', '{}'), Breaks())
        self.assertIn('the page went missing', json.loads(message['content'])['error'])

    def test_a_reply_with_no_asks_is_not_mistaken_for_one(self):
        self.assertEqual([], provider.asked_to_measure(
            {'choices': [{'message': {'content': '{}'}}]}))
        self.assertEqual(1, len(provider.asked_to_measure(
            {'choices': [{'message': {'tool_calls': [self.call('zoom', '{}')]}}]})))


if __name__ == '__main__':
    unittest.main()
