import unittest

from chart_harness import coverage


def mark(x, y, width=10, found_by=('thickness',), count=1):
    return {'x': x, 'y': y, 'width': width, 'height': width,
            'found_by': list(found_by), 'method_count': count}


def candidate(cid, x, y):
    return {'candidate_id': cid, 'pixel': {'x': x, 'y': y},
            'possible_series': ['s1'], 'marker': 'ring', 'support': 'supported',
            'diagnostics': {}}


def reading_over(xs):
    """A reading with a point in each of the given sampling columns."""
    return [candidate('p%04d' % (i + 1), x, 100 + i) for i, x in enumerate(xs)]


class CoverageTests(unittest.TestCase):
    def test_the_distance_that_counts_as_covering_comes_from_the_marks(self):
        self.assertEqual(coverage.reach([mark(0, 0, 10), mark(1, 1, 14)]), 6)
        # No measured marks: the legend glyph the reader pointed at says how big
        # a mark is instead, and only if neither exists is there no answer.
        self.assertEqual(coverage.reach([], [{'template_bbox': [0, 0, 20, 12]}]), 10)
        self.assertIsNone(coverage.reach([], []))

    def test_points_sharing_a_timepoint_gather_into_one_column(self):
        found = coverage.columns([100, 104, 97, 300, 302, 700], 10)
        self.assertEqual(found, [100, 301, 700])
        self.assertEqual(coverage.step(found), 300)
        self.assertIsNone(coverage.step([100]))

    def test_only_marks_in_columns_the_reading_never_reached_are_unexamined(self):
        # A reading that stops a third of the way across: the columns beyond it
        # were never looked at, while the ones it did read are its own business.
        marks = [mark(100, 110), mark(100, 300), mark(300, 120), mark(500, 130),
                 mark(700, 140), mark(900, 150)]
        missed = coverage.unexamined(marks, reading_over([100, 300]), 10)
        self.assertEqual([m['x'] for m in missed], [500, 700, 900])

    def test_a_body_beside_a_point_already_proposed_is_not_carried_in_again(self):
        # Error-bar caps and crossing ink sit in columns the reading did read;
        # filling in from those would inflate the reading, not complete it.
        marks = [mark(100, 110), mark(103, 180), mark(300, 120)]
        self.assertEqual(coverage.unexamined(marks, reading_over([100, 300]), 10), [])

    def test_a_reading_with_nothing_at_all_leaves_the_whole_plot_unexamined(self):
        marks = [mark(100, 110), mark(700, 140)]
        self.assertEqual(len(coverage.unexamined(marks, [], 10)), 2)
        self.assertEqual(coverage.unexamined(marks, [], None), [])

    def test_where_finders_agree_the_agreed_bodies_are_the_ones_carried_in(self):
        marks = [mark(500, 130, count=2), mark(510, 400, count=1)]
        self.assertEqual([m['x'] for m in coverage.corroborated(marks)], [500])
        lone = [mark(500, 130), mark(700, 140)]
        self.assertEqual(len(coverage.corroborated(lone)), 2)

    def test_marks_in_unreached_columns_become_candidates_with_open_groups(self):
        proposals = {'candidates': reading_over([100, 300]),
                     'diagnostics': [], 'status': 'review_required'}
        added = coverage.add(proposals, [mark(100, 110), mark(700, 140), mark(900, 150)],
                             10, ['s1', 's2'])
        self.assertEqual([a['pixel']['x'] for a in added], [700, 900])
        self.assertEqual(added[0]['possible_series'], ['s1', 's2'])
        self.assertEqual(added[0]['support'], 'unrefined')
        self.assertEqual(added[0]['pixel_uncertainty']['kind'], 'half_the_measured_mark_body')
        self.assertTrue(added[0]['diagnostics']['requires_visual_review'])
        self.assertEqual([c['pixel']['x'] for c in proposals['candidates']],
                         [100, 300, 700, 900])
        self.assertEqual(len({c['candidate_id'] for c in proposals['candidates']}), 4)
        self.assertEqual(proposals['diagnostics'][0]['code'],
                         'columns_the_reading_never_reached')

    def test_nothing_is_added_when_the_reading_reached_every_column(self):
        proposals = {'candidates': reading_over([100, 300, 700]), 'diagnostics': []}
        self.assertEqual(coverage.add(proposals, [mark(101, 110), mark(699, 140)],
                                      10, ['s1']), [])
        self.assertEqual(proposals['diagnostics'], [])

    def test_a_reading_that_found_nothing_is_no_longer_called_unsupported(self):
        proposals = {'candidates': [], 'diagnostics': [], 'status': 'unsupported'}
        coverage.add(proposals, [mark(400, 120)], 6, ['s1'])
        self.assertEqual(proposals['status'], 'review_required')

    def test_marks_outside_the_plot_the_reader_settled_on_are_not_its_data(self):
        box = [50, 50, 500, 400]
        self.assertTrue(coverage.inside(mark(100, 100), box))
        self.assertFalse(coverage.inside(mark(900, 100), box))
        self.assertTrue(coverage.inside(mark(900, 100), None))

    def test_the_span_is_stated_against_the_ink_not_against_the_box(self):
        marks = [mark(100, 100), mark(400, 120), mark(700, 140)]
        spanned = coverage.span(marks, reading_over([100, 340]), [0, 0, 1000, 500])
        self.assertEqual(spanned['ink_from'], 100)
        self.assertEqual(spanned['ink_to'], 700)
        self.assertEqual(spanned['share_of_the_ink_covered'], 0.4)
        self.assertIsNone(coverage.span([], reading_over([1]), None))

    def test_what_the_pass_did_is_said_in_words(self):
        marks = [mark(100, 100), mark(700, 140)]
        spanned = coverage.span(marks, reading_over([100]), None)
        said = coverage.sentence([{'candidate_id': 'm0002'}], spanned)
        self.assertIn('0%', said)
        self.assertIn('1 measured mark(s)', said)
        self.assertIn('group left open', said)
        self.assertIn('every column', coverage.sentence([], None))


if __name__ == '__main__':
    unittest.main()
