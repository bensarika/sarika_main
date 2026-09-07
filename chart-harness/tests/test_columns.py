import unittest

from chart_harness import columns


class RunsTests(unittest.TestCase):
    def test_a_single_stroke_reads_as_one_strand(self):
        line = [False] * 10 + [True] * 2 + [False] * 10
        self.assertEqual(len(columns._runs(line, 12, 6.)), 1)

    def test_two_curves_lying_over_one_another_read_as_two(self):
        line = [False] * 10 + [True] * 7 + [False] * 10
        found = columns._runs(line, 12, 6.)
        self.assertEqual(len(found), 2)
        self.assertLess(found[0], found[1])

    def test_a_deep_stretch_is_one_strand_when_no_doubling_is_asked_for(self):
        line = [False] * 10 + [True] * 7 + [False] * 10
        self.assertEqual(len(columns._runs(line, 12)), 1)

    def test_a_stretch_wider_than_allowed_is_not_a_strand(self):
        line = [True] * 20
        self.assertEqual(columns._runs(line, 12, 6.), [])

    def test_ink_running_to_the_end_of_the_column_still_counts(self):
        line = [False] * 10 + [True] * 2
        self.assertEqual(len(columns._runs(line, 12, 6.)), 1)


if __name__ == '__main__':
    unittest.main()
