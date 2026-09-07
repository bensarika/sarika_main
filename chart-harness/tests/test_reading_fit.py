import unittest

from chart_harness import reading_fit


def grid(columns=6, rows=5, left=300., top=250., across=300., down=140.):
    """A plot's worth of marks: sampling columns crossed with series rows."""
    return [(left + i * across, top + j * down)
            for i in range(columns) for j in range(rows)]


def drawn_in(marks, x_scale, y_scale, x_shift=0., y_shift=0.):
    """The same marks as a reader would give them in a frame of its own."""
    return [((x - x_shift) / x_scale, (y - y_shift) / y_scale) for x, y in marks]


class RegisterTests(unittest.TestCase):
    def test_a_reading_drawn_in_a_smaller_frame_is_carried_onto_the_marks(self):
        marks = grid()
        frame = reading_fit.register(drawn_in(marks, .68, .47), marks, tolerance=20.)
        self.assertIsNotNone(frame)
        self.assertAlmostEqual(.68, frame['x_scale'], places=2)
        self.assertAlmostEqual(.47, frame['y_scale'], places=2)
        self.assertEqual(len(marks), frame['landed_on_marks'])

    def test_a_reading_that_reads_high_is_carried_down_onto_them(self):
        marks = grid()
        reading = [(x, y - 90.) for x, y in marks]
        frame = reading_fit.register(reading, marks, tolerance=20.)
        self.assertIsNotNone(frame)
        self.assertAlmostEqual(90., frame['y_shift'], places=0)
        self.assertAlmostEqual(1., frame['y_scale'], places=2)

    def test_a_reading_already_on_the_marks_is_left_alone(self):
        marks = grid()
        self.assertIsNone(reading_fit.register(marks, marks, tolerance=20.))

    def test_a_reading_of_nothing_in_particular_is_not_stretched_onto_them(self):
        marks = grid(columns=3, rows=3)
        scattered = [(311., 902.), (1290., 268.), (640., 1502.), (1701., 77.),
                     (95., 1188.)]
        frame = reading_fit.register(scattered, marks, tolerance=4.)
        self.assertIsNone(frame)

    def test_a_frame_that_would_carry_the_reading_off_the_plot_is_refused(self):
        marks = grid()
        reading = drawn_in(marks, .68, .47)
        inside = reading_fit.register(reading, marks, tolerance=20.,
                                      bounds=[0., 0., 2000., 1000.])
        self.assertIsNotNone(inside)
        self.assertIsNone(reading_fit.register(reading, marks, tolerance=20.,
                                               bounds=[0., 0., 700., 400.]))

    def test_too_little_to_measure_a_frame_from_says_so(self):
        marks = grid()
        self.assertIsNone(reading_fit.register(marks[:3], marks, tolerance=20.))
        self.assertIsNone(reading_fit.register(marks, marks[:3], tolerance=20.))
        self.assertIsNone(reading_fit.register(marks, marks, tolerance=0))

    def test_the_move_is_reported_in_words_and_can_be_applied(self):
        marks = grid()
        frame = reading_fit.register(drawn_in(marks, .68, .47), marks, tolerance=20.)
        self.assertIn('frame', frame['reading'])
        carried = reading_fit.carry(frame, marks[0][0] / .68, marks[0][1] / .47)
        self.assertAlmostEqual(marks[0][0], carried[0], places=0)
        self.assertAlmostEqual(marks[0][1], carried[1], places=0)


if __name__ == '__main__':
    unittest.main()
