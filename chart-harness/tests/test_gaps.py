import unittest

from chart_harness import gaps


def row(cid, x, y, status='observed', series='a'):
    return {'candidate_id': cid, 'series_id': series, 'pixel_x': x, 'pixel_y': y,
            'status': status}


class SpacingTests(unittest.TestCase):
    def test_step_is_the_typical_distance_not_the_average_of_the_gaps(self):
        points = [0., 10., 20., 100.]
        self.assertEqual(10., gaps.step(points))

    def test_no_step_from_a_single_mark(self):
        self.assertIsNone(gaps.step([5.]))

    def test_a_jump_reports_how_many_marks_belong_in_it(self):
        points = [{'x': 0, 'y': 0}, {'x': 10, 'y': 10},
                  {'x': 40, 'y': 40}, {'x': 50, 'y': 50}]
        found = gaps.holes(points)
        self.assertEqual(1, len(found))
        self.assertEqual(2, found[0]['missing'])
        self.assertEqual([20., 30.], [round(p['x'], 1) for p in found[0]['predicted']])
        self.assertEqual([20., 30.], [round(p['y'], 1) for p in found[0]['predicted']])

    def test_an_even_series_is_not_short(self):
        points = [{'x': x, 'y': 5} for x in (0, 10, 20, 30)]
        self.assertEqual([], gaps.holes(points))
        self.assertEqual(4, gaps.expected(points))

    def test_uneven_sampling_within_half_a_step_is_not_a_hole(self):
        points = [{'x': x, 'y': 0} for x in (0, 10, 21, 33, 44)]
        self.assertEqual([], gaps.holes(points))

    def test_a_predicted_place_becomes_a_point_only_where_a_finder_saw_ink(self):
        points = [{'x': 0, 'y': 0}, {'x': 10, 'y': 0}, {'x': 40, 'y': 0}]
        marks = [{'x': 21., 'y': 1., 'found_by': ['thickness']}]
        out = gaps.recover(points, marks, radius=4.)
        self.assertEqual(1, len(out['recovered']))
        self.assertEqual((21., 1.), (out['recovered'][0]['x'], out['recovered'][0]['y']))
        self.assertEqual(1, len(out['unfilled']))
        self.assertEqual(30., out['unfilled'][0]['predicted']['x'])

    def test_a_mark_further_than_the_search_radius_is_not_claimed(self):
        points = [{'x': 0, 'y': 0}, {'x': 10, 'y': 0}, {'x': 30, 'y': 0}]
        out = gaps.recover(points, [{'x': 20., 'y': 40.}], radius=3.)
        self.assertEqual([], out['recovered'])
        self.assertEqual(1, len(out['unfilled']))

    def test_report_counts_per_series_and_ignores_unexported_rows(self):
        rows = [row('a1', 0, 0), row('a2', 10, 0), row('a3', 40, 0),
                row('a4', 50, 0, status='reject'),
                row('b1', 0, 9, series='b'), row('b2', 10, 9, series='b')]
        out = gaps.report(rows, [], radius=2., labels={'a': '10 mg/kg'})
        self.assertEqual('10 mg/kg', out['a']['label'])
        self.assertEqual(3, out['a']['kept'])
        self.assertEqual(5, out['a']['expected'])
        self.assertEqual(2, out['a']['missing'])
        self.assertEqual(0, out['b']['missing'])

    def test_advice_names_the_series_and_where_to_look(self):
        rows = [row('a1', 0, 0), row('a2', 10, 0), row('a3', 40, 0)]
        text = gaps.advice(gaps.report(rows, [], radius=2., labels={'a': '3 mg/kg'}))
        self.assertIn('3 mg/kg', text)
        self.assertIn('2 more mark', text)
        self.assertIn('x=20', text)

    def test_advice_is_silent_when_nothing_is_missing(self):
        rows = [row('a1', 0, 0), row('a2', 10, 0), row('a3', 20, 0)]
        self.assertEqual('', gaps.advice(gaps.report(rows, [], radius=2.)))


if __name__ == '__main__':
    unittest.main()
