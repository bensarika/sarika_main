import argparse
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageDraw

from chart_harness import duel
from chart_harness.cli import duel_run
from chart_harness.visual_check import VisualCheckProvider


def reflection(notes=(), failed=0, review_status='accepted'):
    return {'run': 'r', 'panels': [{'panel': 'one', 'review_status': review_status,
                                    'notes': list(notes), 'visual_check': 'concerns',
                                    'screen': {'checked': 3, 'failed': failed,
                                               'corrected': 0, 'reasons': []}}]}


class WeighTests(unittest.TestCase):
    def test_finding_the_run_already_admits_outranks_one_it_never_mentioned(self):
        judgment = {'findings': [
            {'issue': 'points_on_a_confidence_band', 'severity': 'medium'},
            {'issue': 'missing_series_labels', 'severity': 'medium'}]}
        weighed = duel.weigh(judgment, reflection(
            notes=['several points sit on a confidence band edge']))
        self.assertEqual(weighed[0]['issue'], 'points_on_a_confidence_band')
        self.assertTrue(weighed[0]['corroborated_by_self_review'])
        self.assertFalse(weighed[1]['corroborated_by_self_review'])

    def test_a_finding_the_run_denies_is_kept_not_dropped(self):
        weighed = duel.weigh({'findings': [{'issue': 'invented_points', 'severity': 'high'}]},
                             reflection(notes=['every point was verified']))
        self.assertEqual(len(weighed), 1)
        self.assertFalse(weighed[0]['corroborated_by_self_review'])

    def test_screen_failure_reasons_count_as_the_run_admitting_the_problem(self):
        r = reflection(failed=2)
        r['panels'][0]['screen']['reasons'] = ['window_is_mostly_empty']
        weighed = duel.weigh({'findings': [{'issue': 'window_is_mostly_empty',
                                            'severity': 'low'}]}, r)
        self.assertTrue(weighed[0]['corroborated_by_self_review'])


class DecideTests(unittest.TestCase):
    def test_a_sound_verdict_with_a_clean_screen_earns_no_second_pass(self):
        decision = duel.decide({'verdict': 'sound', 'findings': []}, reflection(),
                               {'disagreements': []})
        self.assertFalse(decision['iterate'])
        self.assertEqual(decision['reasons'], [])

    def test_failed_pixel_screen_forces_another_pass_even_if_the_judge_is_happy(self):
        decision = duel.decide({'verdict': 'sound', 'findings': []},
                               reflection(failed=2), {'disagreements': []})
        self.assertTrue(decision['iterate'])
        self.assertIn('candidates_failed_the_pixel_screen',
                      [r['code'] for r in decision['reasons']])

    def test_high_severity_cross_judge_finding_drives_an_iteration(self):
        judgment = {'verdict': 'needs_another_pass', 'worst_problem': 'band sampled',
                    'findings': [{'issue': 'points_on_a_confidence_band',
                                  'severity': 'high', 'fix': 'drop them'}]}
        decision = duel.decide(judgment, reflection(failed=1), {'disagreements': []})
        self.assertTrue(decision['iterate'])
        self.assertEqual(decision['act_on'][0]['issue'], 'points_on_a_confidence_band')

    def test_cross_run_disagreements_are_recorded_as_reasons(self):
        decision = duel.decide({'verdict': 'sound', 'findings': []}, reflection(failed=1),
                               {'disagreements': [{'code': 'series_labels_differ'}]})
        self.assertIn('cross_run_series_labels_differ',
                      [r['code'] for r in decision['reasons']])

    def test_feedback_names_the_fix_and_the_measured_reason(self):
        judgment = {'verdict': 'needs_another_pass', 'worst_problem': 'band sampled',
                    'findings': [{'issue': 'points_on_a_confidence_band', 'series': 'bbmAb1',
                                  'severity': 'high', 'evidence': 'pixels are grey',
                                  'fix': 'keep only the marked curve'}]}
        decision = duel.decide(judgment, reflection(failed=1), {'disagreements': []})
        text = duel.feedback_text(decision, judgment)
        self.assertIn('points_on_a_confidence_band', text)
        self.assertIn('keep only the marked curve', text)
        self.assertIn('candidates_failed_the_pixel_screen', text)
        self.assertIn('band sampled', text)


class SummaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.run = Path(self.temp.name) / 'run'
        panel = self.run / 'panels' / 'IV'
        panel.mkdir(parents=True)
        (panel / 'result.json').write_text(json.dumps({'status': 'review_required',
            'counts': {'observed': 2, 'unresolved': 1},
            'rows': [{'series_label': 'bbmAb1', 'x': 1., 'y': 10., 'status': 'observed'},
                     {'series_label': 'bbmAb1', 'x': 2., 'y': 8., 'status': 'observed'},
                     {'series_label': 'bbmAb1', 'x': None, 'y': None,
                      'status': 'unresolved'}]}))
        (panel / 'review.json').write_text(json.dumps(
            {'status': 'review_required', 'notes': ['a note'],
             '_visual_check': {'assessment': 'concerns'}}))
        (panel / 'candidate_screen.json').write_text(json.dumps(
            [{'candidate_id': 'c1', 'passed': True},
             {'candidate_id': 'c2', 'passed': False, 'reason': 'window_is_mostly_empty'}]))

    def tearDown(self):
        self.temp.cleanup()

    def test_summary_counts_only_observed_points_per_series(self):
        summary = duel.summarize(self.run)
        self.assertEqual(summary['panels'][0]['points_per_series'], {'bbmAb1': 2})
        self.assertEqual(summary['panels'][0]['counts']['unresolved'], 1)

    def test_reflection_carries_the_measured_screen_failures(self):
        reflected = duel.self_reflection(self.run)['panels'][0]
        self.assertEqual(reflected['screen']['failed'], 1)
        self.assertEqual(reflected['screen']['reasons'], ['window_is_mostly_empty'])
        self.assertEqual(reflected['visual_check'], 'concerns')

    def test_screen_digest_names_the_panel_of_each_measurement(self):
        self.assertEqual(duel.screen_digest(self.run)[0]['panel'], 'IV')

    def test_a_run_without_panels_summarizes_to_nothing_rather_than_failing(self):
        empty = Path(self.temp.name) / 'empty'
        empty.mkdir()
        self.assertEqual(duel.summarize(empty)['panels'], [])
        self.assertEqual(duel.self_reflection(empty)['panels'], [])


class DuelRunTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / 'chart.png'
        im = Image.new('RGB', (200, 160), 'white')
        ImageDraw.Draw(im).ellipse((93, 73, 107, 87), outline='black', width=2)
        im.save(self.source)
        self.configs = []
        for name in ('grok', 'muse'):
            path = self.root / f'{name}.json'
            path.write_text(json.dumps({'provider_label': name, 'recheck_axes': False,
                                        'model': {'name': 'fixture',
                                                  'base_url': 'http://localhost:1'}}))
            self.configs.append(str(path))
        self.interpretation = {'plot_bbox': [10, 10, 190, 150],
            'x_axis': {'scale': 'linear', 'unit': 'h',
                       'anchors': [{'pixel': 10, 'value': 0}, {'pixel': 190, 'value': 18}]},
            'y_axis': {'scale': 'log', 'unit': 'ug/mL',
                       'anchors': [{'pixel': 10, 'value': 1000}, {'pixel': 150, 'value': 1}]},
            'series': [{'id': 'drug', 'label': 'Drug', 'marker': 'ring', 'radius': 6.5,
                        'seeds': [{'x': 102, 'y': 78}]}]}
        self.verdicts = {}
        self.judged = []

    def tearDown(self):
        self.temp.cleanup()

    def provider(self, config, out, role, not_after=None):
        parent = self
        label = config['provider_label']

        class Fixture:
            def complete(self, stage, prompt, images=(), schema=None):
                if stage.endswith('_visual_check'):
                    points = json.loads(prompt.split('Fixed anchors: ', 1)[1]
                                        .split('\nYour result:', 1)[0])
                    return {'annotations': [{'id': p['id'], 'label': 'x',
                                             'status': 'unresolved'} for p in points],
                            'assessment': 'concerns', 'notes': []}
                if stage == 'interpret':
                    return copy.deepcopy(parent.interpretation)
                if stage == 'layout':
                    return {'panels': [{'id': 'one', 'label': 'one',
                                        'crop_bbox': [0, 0, 200, 160]}]}
                if stage == 'review_axes':
                    return {'axis_check': {k: copy.deepcopy(parent.interpretation[k])
                                           for k in ('x_axis', 'y_axis')},
                            'series_labels': {'Drug': 'Drug'}, 'status': 'accepted',
                            'missing_points': []}
                if stage.startswith('review_batch_'):
                    supplied = json.loads(prompt.split('Candidate locations: ', 1)[1]
                                          .split('\n', 1)[0])
                    return {'decisions': [{'candidate_id': c['candidate_id'],
                                           'series_id': 'Drug', 'role': 'observed',
                                           'reason': 'Visible ring.',
                                           'marker_center': dict(c['pixel'])}
                                          for c in supplied],
                            'status': 'accepted', 'missing_points': []}
                if stage.startswith('cross_judge_'):
                    authored = prompt.split('produced by ', 1)[1].split('.', 1)[0]
                    parent.judged.append((label, authored))
                    return parent.verdicts.get(authored,
                                               {'verdict': 'sound', 'findings': []})
                raise AssertionError(stage)

        return VisualCheckProvider(Fixture(), out / 'visual_checks' / role)

    def args(self, name='duel'):
        return argparse.Namespace(source=str(self.source), config=list(self.configs),
                                  out=str(self.root / name), query='Observed measurements',
                                  page=None, rotate=0, context_file=None)

    def test_each_provider_judges_the_other_and_agreement_is_reported(self):
        with patch('chart_harness.cli.make_provider', side_effect=self.provider):
            report = duel_run(self.args())
        self.assertEqual(sorted(self.judged), [('grok', 'muse'), ('muse', 'grok')])
        self.assertTrue(report['agrees'])
        self.assertEqual(report['iterations'], {})
        self.assertTrue((self.root / 'duel/duel_report.json').exists())

    def test_only_the_provider_judged_unsound_gets_a_second_pass(self):
        self.verdicts['grok'] = {'verdict': 'needs_another_pass',
                                 'worst_problem': 'sampled the band',
                                 'findings': [{'issue': 'points_on_a_confidence_band',
                                               'severity': 'high',
                                               'fix': 'drop band samples'}]}
        with patch('chart_harness.cli.make_provider', side_effect=self.provider):
            report = duel_run(self.args())
        self.assertEqual(sorted(report['iterations']), ['grok'])
        feedback = (self.root / 'duel/feedback_grok.md').read_text()
        self.assertIn('drop band samples', feedback)
        self.assertTrue((self.root / 'duel/grok_pass2/batch_result.json').exists())


if __name__ == '__main__':
    unittest.main()
