"""Batched review: local coordinates, translation-only mapping, no silent merges."""
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from chart_harness import review_batches


def candidates(points):
    return [{'candidate_id': f'p{i:04d}', 'pixel': {'x': float(x), 'y': float(y)}}
            for i, (x, y) in enumerate(points)]


class ReviewBatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.image = self.root / 'chart.png'
        Image.new('RGB', (900, 700), 'white').save(self.image)

    def tearDown(self):
        self.temp.cleanup()

    def test_batches_stay_inside_the_image_and_carry_local_coordinates(self):
        batches = review_batches.plan(
            candidates([(5, 5), (12, 40), (860, 690), (400, 350)]),
            (900, 700),
            batch_size=2,
        )
        self.assertEqual([len(b['candidates']) for b in batches], [2, 2])
        for batch in batches:
            left, top, right, bottom = batch['box']
            self.assertGreaterEqual(left, 0)
            self.assertGreaterEqual(top, 0)
            self.assertLessEqual(right, 900)
            self.assertLessEqual(bottom, 700)
            self.assertGreaterEqual(right - left, review_batches.MIN_SIDE)
            for candidate in batch['candidates']:
                self.assertGreaterEqual(candidate['pixel']['x'], 0)
                self.assertLess(candidate['pixel']['x'], right - left)
                self.assertGreaterEqual(candidate['pixel']['y'], 0)
                self.assertLess(candidate['pixel']['y'], bottom - top)

    def test_every_candidate_appears_in_exactly_one_batch(self):
        given = candidates([(x * 7 % 880, x * 13 % 680) for x in range(37)])
        batches = review_batches.plan(given, (900, 700), batch_size=5)
        seen = [c['candidate_id'] for b in batches for c in b['candidates']]
        self.assertEqual(sorted(seen), sorted(c['candidate_id'] for c in given))
        self.assertEqual(len(seen), len(set(seen)))

    def test_crop_is_native_resolution_so_mapping_is_a_translation(self):
        batch = review_batches.plan(
            candidates([(300, 300)]), (900, 700))[0]
        path = review_batches.crop(self.image, batch, self.root / 'crops')
        with Image.open(path) as im:
            self.assertEqual(
                im.size,
                (batch['box'][2] - batch['box'][0],
                 batch['box'][3] - batch['box'][1]),
            )

    def test_merge_restores_whole_image_coordinates(self):
        batches = review_batches.plan(
            candidates([(120, 130), (700, 600)]), (900, 700), batch_size=1)
        parts = []
        for batch in batches:
            local = batch['candidates'][0]['pixel']
            parts.append({
                'status': 'accepted',
                'decisions': [{
                    'candidate_id': batch['candidates'][0]['candidate_id'],
                    'series_id': 'Drug',
                    'role': 'observed',
                    'marker_center': {'x': local['x'] + 1, 'y': local['y'] - 1},
                }],
                'missing_points': [{'x': local['x'], 'y': local['y'],
                                    'series_label': 'Drug', 'reason': 'faint'}],
            })
        review = review_batches.merge(
            {'status': 'accepted', 'axis_check': {'x_axis': {}}}, parts, batches)
        centers = {d['candidate_id']: d['marker_center'] for d in review['decisions']}
        self.assertEqual(centers['p0000'], {'x': 121, 'y': 129})
        self.assertEqual(centers['p0001'], {'x': 701, 'y': 599})
        self.assertEqual(
            sorted((p['x'], p['y']) for p in review['missing_points']),
            [(120, 130), (700, 600)],
        )
        self.assertEqual(review['status'], 'accepted')

    def test_one_unaccepted_batch_blocks_whole_review_acceptance(self):
        batches = review_batches.plan(candidates([(120, 130), (700, 600)]),
                                      (900, 700), batch_size=1)
        parts = [{'status': 'accepted', 'decisions': []},
                 {'status': 'review_required', 'decisions': []}]
        review = review_batches.merge({'status': 'accepted', 'axis_check': {}},
                                      parts, batches)
        self.assertEqual(review['status'], 'review_required')
        self.assertEqual(
            [b['status'] for b in review['review_batches']],
            ['accepted', 'review_required'],
        )

    def test_axis_reader_disagreement_alone_blocks_acceptance(self):
        batches = review_batches.plan(candidates([(120, 130)]), (900, 700))
        review = review_batches.merge(
            {'status': 'review_required', 'axis_check': {}},
            [{'status': 'accepted', 'decisions': []}], batches)
        self.assertEqual(review['status'], 'review_required')

    def test_a_batch_concern_becomes_the_review_concern(self):
        batches = review_batches.plan(candidates([(120, 130)]), (900, 700))
        review = review_batches.merge(
            {'status': 'accepted', 'axis_check': {},
             '_visual_check': {'assessment': 'consistent', 'image_path': 'a.png'}},
            [{'status': 'accepted', 'decisions': [],
              '_visual_check': {'assessment': 'concerns', 'image_path': 'b.png'}}],
            batches)
        self.assertEqual(review['_visual_check']['assessment'], 'concerns')
        self.assertEqual(review['review_visual_checks'], ['a.png', 'b.png'])


if __name__ == '__main__':
    unittest.main()
