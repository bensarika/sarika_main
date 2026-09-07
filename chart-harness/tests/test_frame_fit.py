import unittest

from chart_harness import frame_fit


class Fit(unittest.TestCase):
    def test_uniform_resize_is_recovered(self):
        transform = frame_fit.fit([10, 10, 110, 60], [20, 20, 220, 120])
        self.assertAlmostEqual(2., transform['scale_x'])
        self.assertAlmostEqual(2., transform['scale_y'])
        self.assertAlmostEqual(0., transform['offset_x'])
        self.assertAlmostEqual(0., transform['offset_y'])
        self.assertEqual((40., 40.), frame_fit.point(transform, 20, 20))

    def test_a_pure_shift_keeps_unit_scale(self):
        transform = frame_fit.fit([10, 10, 110, 60], [30, 15, 130, 65])
        self.assertAlmostEqual(1., transform['scale_x'])
        self.assertAlmostEqual(20., transform['offset_x'])
        self.assertAlmostEqual(5., transform['offset_y'])

    def test_a_nonuniform_stretch_is_refused(self):
        # Fitting it would disguise a wrong model box as a resize.
        self.assertIsNone(frame_fit.fit([10, 10, 110, 60], [10, 10, 410, 70]))

    def test_degenerate_boxes_are_refused(self):
        self.assertIsNone(frame_fit.fit([10, 10, 10, 60], [10, 10, 110, 60]))
        self.assertIsNone(frame_fit.fit(None, [10, 10, 110, 60]))

    def test_identity_is_recognised(self):
        self.assertTrue(frame_fit.is_identity(frame_fit.fit([0, 0, 100, 50], [0, 0, 100, 50])))
        self.assertFalse(frame_fit.is_identity(frame_fit.fit([0, 0, 100, 50], [0, 0, 200, 100])))


class Apply(unittest.TestCase):
    def setUp(self):
        self.transform = frame_fit.fit([0, 0, 100, 100], [0, 0, 200, 200])

    def test_seeds_and_template_boxes_move_together(self):
        interpretation = {'plot_bbox': [0, 0, 100, 100], 'series': [
            {'id': 's1', 'template_bbox': [10, 10, 20, 20], 'seeds': [{'x': 30, 'y': 40}]}]}
        moved, note = frame_fit.apply(interpretation, self.transform, (400, 400))
        series = moved['series'][0]
        self.assertEqual([20., 20., 40., 40.], series['template_bbox'])
        self.assertEqual({'x': 60., 'y': 80.}, series['seeds'][0])
        self.assertIn('scale', note)

    def test_moved_coordinates_stay_inside_the_image(self):
        interpretation = {'plot_bbox': [0, 0, 100, 100], 'series': [
            {'id': 's1', 'seeds': [{'x': 99, 'y': 99}]}]}
        moved, _ = frame_fit.apply(interpretation, self.transform, (150, 150))
        seed = moved['series'][0]['seeds'][0]
        self.assertLessEqual(seed['x'], 149)
        self.assertLessEqual(seed['y'], 149)


if __name__ == '__main__':
    unittest.main()
