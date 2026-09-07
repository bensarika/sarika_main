import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from chart_harness import marker_screen, markers

LEGEND_X = 40
PLOT = [200., 40., 560., 360.]
MARKS = [(260, 300), (340, 220), (420, 150), (500, 90)]


def chart(path, marker_radius=7):
    """A plot with four filled marks and a three-row legend to the left."""
    image = Image.new('RGB', (600, 400), 'white')
    draw = ImageDraw.Draw(image)
    draw.rectangle(PLOT, outline='black')
    for index in range(3):
        y = 60 + index * 40
        draw.line((LEGEND_X, y, LEGEND_X + 60, y), fill='black', width=2)
        cx = LEGEND_X + 30
        draw.ellipse((cx - marker_radius, y - marker_radius,
                      cx + marker_radius, y + marker_radius), fill='black')
    for x, y in MARKS:
        draw.ellipse((x - marker_radius, y - marker_radius,
                      x + marker_radius, y + marker_radius), fill='black')
    image.save(path)
    return path


class LegendGlyphs(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.image = chart(self.dir / 'chart.png')
        self.gray = markers.load_gray(self.image)

    def test_extracts_one_small_template_per_label(self):
        entries = markers.extract_templates(
            self.image, PLOT, ['a', 'b', 'c'], self.dir / 'legend')
        self.assertEqual(['a', 'b', 'c'], [e['label'] for e in entries])
        for entry in entries:
            self.assertLess(entry['width'], 100)
            self.assertLess(entry['height'], 100)
            self.assertTrue(Path(entry['template_path']).exists())
            self.assertGreater(entry['ink_fraction'], .2)

    def test_glyphs_read_down_the_legend_column(self):
        glyphs = markers.legend_glyphs(self.gray, PLOT, 3)
        tops = [g['glyph_bbox'][1] for g in glyphs]
        self.assertEqual(tops, sorted(tops))

    def test_no_glyphs_when_the_legend_has_fewer_rows_than_series(self):
        self.assertEqual([], markers.legend_glyphs(self.gray, PLOT, 6))

    def test_scan_finds_the_plotted_marks_and_no_others(self):
        template = markers.legend_glyphs(self.gray, PLOT, 3)[0]['glyph_bbox']
        hits = markers.scan(self.gray, template, PLOT, threshold=.6)
        found = {(round(h['x']), round(h['y'])) for h in hits}
        for x, y in MARKS:
            self.assertTrue(any(abs(x - hx) <= 3 and abs(y - hy) <= 3
                                for hx, hy in found), f'missed {(x, y)}')
        self.assertLessEqual(len(hits), len(MARKS) + 2)

    def test_scan_can_be_restricted_to_known_sample_columns(self):
        template = markers.legend_glyphs(self.gray, PLOT, 3)[0]['glyph_bbox']
        hits = markers.scan(self.gray, template, PLOT, threshold=.6,
                            columns=[MARKS[0][0]], column_tolerance=5)
        self.assertEqual(1, len(hits))
        self.assertAlmostEqual(MARKS[0][0], hits[0]['x'], delta=3)


class PatchVerification(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.image = chart(self.dir / 'chart.png')
        self.gray = markers.load_gray(self.image)
        self.template = markers.legend_glyphs(self.gray, PLOT, 3)[0]['glyph_bbox']

    def test_a_real_mark_passes(self):
        report = markers.patch_report(self.gray, self.template, *MARKS[0])
        self.assertTrue(markers.verdict(report)['passed'])

    def test_empty_space_fails_as_mostly_empty(self):
        report = markers.patch_report(self.gray, self.template, 250, 100)
        result = markers.verdict(report)
        self.assertFalse(result['passed'])
        self.assertEqual('window_is_mostly_empty', result['reason'])

    def test_a_coordinate_off_the_image_fails(self):
        report = markers.patch_report(self.gray, self.template, 2, 2)
        self.assertFalse(markers.verdict(report)['passed'])
        self.assertEqual('outside_image', report['status'])

    def test_correction_measures_the_offset_back_to_the_mark(self):
        x, y = MARKS[1][0] + 9, MARKS[1][1] - 4
        advice = markers.correction(self.gray, self.template, x, y)
        self.assertAlmostEqual(MARKS[1][0], advice['x'], delta=2)
        self.assertAlmostEqual(MARKS[1][1], advice['y'], delta=2)
        self.assertLess(advice['dx'], 0)
        self.assertGreater(advice['dy'], 0)
        self.assertIn('left', advice['advice'])
        self.assertIn('down', advice['advice'])
        self.assertAlmostEqual(9.85, advice['distance_px'], delta=2)

    def test_crowding_counts_ink_in_widening_windows(self):
        # The windows are so many marks wide, so they follow the figure's scale
        # instead of asking every plate the same question in pixels.
        report = markers.crowding(self.gray, *MARKS[0], glyph_ink=100, mark_side=20)
        self.assertEqual(['100x100', '160x160', '220x220'], list(report))
        sizes = [report[k]['ink_pixels'] for k in report]
        self.assertEqual(sizes, sorted(sizes))
        self.assertIn('glyph_equivalents', report['100x100'])
        wider = markers.crowding(self.gray, *MARKS[0], mark_side=40)
        self.assertEqual(['200x200', '320x320', '440x440'], list(wider))


def interpretation(template):
    return {'series': [{'id': 's1', 'label': 'a', 'template_bbox': template}],
            'plot_bbox': PLOT}


class Screen(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.image = chart(self.dir / 'chart.png')
        self.gray = markers.load_gray(self.image)
        self.template = markers.legend_glyphs(self.gray, PLOT, 3)[0]['glyph_bbox']

    def screen(self, pixel, **kwargs):
        proposals = {'candidates': [{'candidate_id': 'c1', 'pixel': pixel,
                                     'possible_series': ['s1']}]}
        review = {'status': 'accepted', 'decisions': [
            {'candidate_id': 'c1', 'series_id': 's1', 'role': 'observed'}]}
        screens = marker_screen.apply(self.image, interpretation(self.template),
                                      proposals, review, **kwargs)
        return proposals, review, screens

    def test_empty_window_demotes_the_decision_and_blocks_acceptance(self):
        _, review, screens = self.screen({'x': 250., 'y': 100.})
        self.assertFalse(screens[0]['passed'])
        self.assertTrue(screens[0]['demoted'])
        self.assertEqual('unresolved', review['decisions'][0]['role'])
        self.assertEqual('review_required', review['status'])
        self.assertIn('crowding', screens[0])

    def test_a_near_miss_is_moved_onto_the_mark_and_rechecked(self):
        x, y = MARKS[2][0] + 6, MARKS[2][1] + 3
        proposals, review, screens = self.screen({'x': float(x), 'y': float(y)})
        self.assertTrue(screens[0]['corrected'])
        self.assertTrue(screens[0]['passed'])
        self.assertEqual('observed', review['decisions'][0]['role'])
        self.assertAlmostEqual(MARKS[2][0], proposals['candidates'][0]['pixel']['x'], delta=2)
        self.assertAlmostEqual(MARKS[2][1], proposals['candidates'][0]['pixel']['y'], delta=2)

    def test_a_distant_match_is_not_snapped(self):
        x, y = MARKS[3][0] + 30, MARKS[3][1]
        proposals, review, screens = self.screen({'x': float(x), 'y': float(y)},
                                                 snap_limit_px=4.)
        self.assertNotIn('corrected', screens[0])
        self.assertEqual('unresolved', review['decisions'][0]['role'])
        self.assertEqual(float(x), proposals['candidates'][0]['pixel']['x'])

    def test_batch_feedback_reports_crop_local_offsets(self):
        candidate = {'candidate_id': 'c1',
                     'pixel': {'x': MARKS[0][0] + 8., 'y': MARKS[0][1] + 0.},
                     'possible_series': ['s1']}
        batch = {'index': 0, 'box': [200, 240, 400, 380],
                 'candidates': [{'candidate_id': 'c1', 'pixel': {'x': 68., 'y': 60.}}]}
        entries = marker_screen.batch_feedback(
            self.gray, {'s1': self.template}, batch, {'c1': candidate})
        self.assertFalse(entries[0]['passed'])
        nearest = entries[0]['nearest_match']
        self.assertAlmostEqual(MARKS[0][0] - 200, nearest['crop_x'], delta=2)
        self.assertAlmostEqual(MARKS[0][1] - 240, nearest['crop_y'], delta=2)
        self.assertIn('left', nearest['advice'])

    def test_batch_feedback_skips_candidates_without_a_legend_template(self):
        batch = {'index': 0, 'box': [0, 0, 100, 100],
                 'candidates': [{'candidate_id': 'c1', 'pixel': {'x': 5., 'y': 5.}}]}
        self.assertEqual([], marker_screen.batch_feedback(
            self.gray, {}, batch, {'c1': {'candidate_id': 'c1',
                                          'pixel': {'x': 5., 'y': 5.},
                                          'possible_series': ['s1']}}))


class MinedTemplates(unittest.TestCase):
    """A figure can carry no legend at all; the marks are still measurable."""

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.image = chart(self.dir / 'chart.png')

    def test_a_target_is_cut_from_the_typical_mark_under_the_proposals(self):
        points = [{'x': float(x), 'y': float(y)} for x, y in MARKS]
        mined = markers.mine_templates(self.image, points, self.dir / 'mined')
        self.assertTrue(mined['mined_from_plot'])
        self.assertEqual(len(MARKS), mined['candidates_measured'])
        self.assertTrue(Path(mined['template_path']).exists())
        self.assertLess(max(mined['width'], mined['height']), markers._length(markers.load_gray(self.image), markers.GLYPH_SIDE_FRACTION, floor=8))
        self.assertGreater(mined['ink_fraction'], .5)

    def test_a_mined_target_screens_the_other_proposals_like_a_legend_glyph(self):
        gray = markers.load_gray(self.image)
        mined = markers.mine_templates(
            self.image, [{'x': float(MARKS[0][0]), 'y': float(MARKS[0][1])}],
            self.dir / 'mined')
        box = mined['template_bbox']
        on_a_mark = markers.verdict(markers.patch_report(gray, box, *MARKS[2]))
        on_blank = markers.verdict(markers.patch_report(gray, box, 300., 100.))
        self.assertTrue(on_a_mark['passed'])
        self.assertFalse(on_blank['passed'])

    def test_proposals_over_blank_paper_mine_nothing_rather_than_noise(self):
        self.assertIsNone(markers.mine_templates(
            self.image, [{'x': 300., 'y': 100.}], self.dir / 'mined'))

    def test_no_proposals_at_all_mines_nothing(self):
        self.assertIsNone(markers.mine_templates(self.image, [], self.dir / 'mined'))


class NccMap(unittest.TestCase):
    def test_flat_template_has_no_correlation_to_report(self):
        gray = np.ones((40, 40))
        self.assertIsNone(markers._ncc_map(gray, np.ones((5, 5))))

    def test_template_larger_than_the_image_is_rejected(self):
        self.assertIsNone(markers._ncc_map(np.ones((4, 4)), np.zeros((10, 10))))


if __name__ == '__main__':
    unittest.main()


class ThicknessMarks(unittest.TestCase):
    """A figure whose groups are named beside the curves has no glyph to copy."""

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())

    def unlabelled(self, path, marks=MARKS, radius=7):
        image = Image.new('RGB', (600, 400), 'white')
        draw = ImageDraw.Draw(image)
        draw.rectangle(PLOT, outline='black')
        draw.line([(210, 340)] + list(marks) + [(550, 60)], fill='black', width=2)
        draw.text((430, 260), '10 mg/kg', fill='black')
        for x, y in marks:
            draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill='black')
        image.save(path)
        return path

    def test_marks_are_found_by_thickness_when_no_legend_exists(self):
        found = markers.detect_marks(self.unlabelled(self.dir / 'plain.png'), PLOT)
        self.assertEqual(len(MARKS), len(found))
        for (x, y), mark in zip(MARKS, sorted(found, key=lambda m: m['x'])):
            self.assertLess(abs(mark['x'] - x), 3)
            self.assertLess(abs(mark['y'] - y), 3)
            self.assertFalse(mark['crowded'])
            self.assertEqual(1, mark['marks_suggested'])

    def test_lines_axes_and_running_text_alone_are_not_marks(self):
        image = Image.new('RGB', (600, 400), 'white')
        draw = ImageDraw.Draw(image)
        draw.rectangle(PLOT, outline='black')
        draw.line([(210, 340), (550, 60)], fill='black', width=2)
        draw.text((430, 260), '10 mg/kg', fill='black')
        image.save(self.dir / 'bare.png')
        self.assertEqual([], markers.detect_marks(self.dir / 'bare.png', PLOT))

    def test_overlapping_marks_are_reported_as_one_crowded_body(self):
        stacked = [(300, 200), (300, 208), (300, 216), (420, 150)]
        found = markers.detect_marks(self.unlabelled(self.dir / 'stack.png', stacked), PLOT)
        crowded = [m for m in found if m['crowded']]
        self.assertEqual(1, len(crowded))
        self.assertGreater(crowded[0]['marks_suggested'], 1)
        self.assertLess(abs(crowded[0]['x'] - 300), 4)

    def test_an_empty_plot_yields_nothing_rather_than_a_guess(self):
        blank = Image.new('RGB', (600, 400), 'white')
        blank.save(self.dir / 'blank.png')
        self.assertEqual([], markers.detect_marks(self.dir / 'blank.png', PLOT))
        self.assertEqual([], markers.detect_marks(self.dir / 'blank.png', [10., 10., 10., 10.]))
