import json
import tempfile
import unittest
from pathlib import Path

from chart_harness.consensus import compare


def write_run(root, name, rows, anchors=(0, 100), status='review_required'):
    run = Path(root) / name
    run.mkdir(parents=True)
    (run / 'result.json').write_text(json.dumps({'status': status, 'rows': rows}))
    (run / 'interpretation.json').write_text(json.dumps({
        'x_axis': {'scale': 'linear', 'unit': 'h',
                   'anchors': [{'pixel': anchors[0], 'value': 0}, {'pixel': anchors[1], 'value': 100}]},
        'y_axis': {'scale': 'log', 'unit': 'ug/mL',
                   'anchors': [{'pixel': 10, 'value': 1000}, {'pixel': 210, 'value': 1}]}}))
    return run


def row(label, x, y, status='observed'):
    return {'series_label': label, 'series_id': label, 'x': x, 'y': y, 'status': status}


class ConsensusTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = self.temp.name

    def tearDown(self):
        self.temp.cleanup()

    def test_matching_runs_agree(self):
        left = write_run(self.root, 'left', [row('bbmAb1', 24, 100), row('bbmAb1', 168, 60)])
        right = write_run(self.root, 'right', [row('bbmAb1', 24.3, 101), row('bbmAb1', 168, 59)])
        report = compare(left, right)
        self.assertTrue(report['agrees'])
        self.assertEqual(len(report['points']['matched']), 2)

    def test_value_and_axis_disagreement_are_reported_separately(self):
        left = write_run(self.root, 'left', [row('bbmAb1', 24, 100)])
        right = write_run(self.root, 'right', [row('bbmAb1', 24, 250)], anchors=(0, 140))
        report = compare(left, right)
        codes = sorted({d['code'] for d in report['disagreements']})
        self.assertEqual(codes, ['axis_calibration_disagreement', 'point_value_disagreement'])
        self.assertFalse(report['agrees'])

    def test_withheld_rows_never_count_as_agreement(self):
        left = write_run(self.root, 'left', [row('bbmAb1', 24, 100)])
        right = write_run(self.root, 'right', [row('bbmAb1', 24, 100, status='unresolved')])
        report = compare(left, right)
        self.assertEqual(report['points']['matched'], [])
        self.assertEqual(len(report['points']['accepted_only_by_left']), 1)
        self.assertIn('accepted_point_coverage_disagreement', {d['code'] for d in report['disagreements']})

    def test_series_label_disagreement_is_reported(self):
        left = write_run(self.root, 'left', [row('bbmAb1', 24, 100)])
        right = write_run(self.root, 'right', [row('bbmAb2', 24, 100)])
        report = compare(left, right)
        self.assertIn('series_label_disagreement', {d['code'] for d in report['disagreements']})


if __name__ == '__main__':
    unittest.main()
