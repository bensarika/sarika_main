import argparse
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageDraw
from chart_harness.cli import run, batch
from chart_harness.visual_check import VisualCheckProvider
from chart_harness.audit import usage_report


class CLITests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.source=self.root/'chart.png'
        im=Image.new('RGB',(200,160),'white')
        ImageDraw.Draw(im).ellipse((93,73,107,87),outline='black',width=2)
        im.save(self.source)
        self.config=self.root/'config.json'
        self.config.write_text(json.dumps({'model':{'name':'fixture','base_url':'http://localhost:1'},'recheck_axes':False}))
        self.interpretation={'plot_bbox':[10,10,190,150],
            'x_axis':{'scale':'linear','unit':'h','anchors':[{'pixel':10,'value':0},{'pixel':190,'value':18}]},
            'y_axis':{'scale':'log','unit':'ug/mL','anchors':[{'pixel':10,'value':1000},{'pixel':150,'value':1}]},
            'series':[{'id':'drug','label':'Drug','marker':'ring','radius':6.5,'seeds':[{'x':102,'y':78}]}],
            'unresolved_regions':[{'reason':'A second observation is occluded.'}]}
        self.calls=[]

    def tearDown(self):
        self.temp.cleanup()

    def provider(self,config,out,role,not_after=None):
        parent=self
        class Fixture:
            def complete(self,stage,prompt,images=(),schema=None):
                parent.calls.append(stage)
                if stage.endswith('_visual_check'):
                    points=json.loads(prompt.split('Fixed anchors: ',1)[1].split('\nYour result:',1)[0])
                    return {'annotations':[{'id':p['id'],'label':'Fixture annotation','status':'unresolved'} for p in points],'assessment':'concerns','notes':[]}
                if stage=='interpret':return copy.deepcopy(parent.interpretation)
                if stage=='layout':return {'panels':[{'id':'one','label':'one','crop_bbox':[0,0,200,160]}]}
                if stage=='review_axes':return {'axis_check':{k:copy.deepcopy(parent.interpretation[k]) for k in ('x_axis','y_axis')},
                    'series_labels':{'Drug':'Drug'},'status':'accepted','missing_points':[]}
                if stage.startswith('review_batch_'):
                    # Crop-local candidate coordinates come back in crop-local pixels.
                    supplied=json.loads(prompt.split('Candidate locations: ',1)[1].split('\n',1)[0])
                    return {'decisions':[{'candidate_id':c['candidate_id'],'series_id':'Drug','role':'observed',
                        'reason':'Visible ring.','marker_center':dict(c['pixel'])} for c in supplied],
                        'status':'accepted','missing_points':[]}
                raise AssertionError(stage)
        return VisualCheckProvider(Fixture(),out/"visual_checks"/role)

    def args(self,name='result'):
        return argparse.Namespace(source=str(self.source),config=str(self.config),out=str(self.root/name),
            query='Observed measurements',page=None,rotate=0,crop=None,context_file=None,reference_image=None)

    def test_resume_skips_model_stages_and_both_results_preserve_incompleteness(self):
        args=self.args()
        with patch('chart_harness.cli.make_provider',side_effect=self.provider):
            first=run(args)
            second=run(args)
        self.assertEqual(self.calls,['interpret','interpret_visual_check','review_axes','review_axes_visual_check',
            'review_batch_000','review_batch_000_visual_check','final_output_visual_check'])
        self.assertEqual(first['counts']['observed'],1)
        self.assertEqual(second['status'],'review_required')
        for path in (self.root/'result/result.json',self.root/'result/final/result.json'):
            self.assertEqual(json.loads(path.read_text())['status'],'review_required')
        self.config.write_text(self.config.read_text().replace('fixture','different'))
        with self.assertRaisesRegex(ValueError,'different input/config'):
            run(args)

    def test_a_spent_time_budget_stops_asking_and_the_reading_is_not_accepted(self):
        """A dozen calls of 300s each is not a five-minute run."""
        self.config.write_text(json.dumps({'model':{'name':'fixture','base_url':'http://localhost:1'},
            'recheck_axes':False,'run_budget_s':0}))
        with patch('chart_harness.cli.make_provider',side_effect=self.provider):
            result=run(self.args('outoftime'))
        self.assertEqual('review_required',result['status'])
        self.assertEqual(0,result['counts']['observed'])
        self.assertIn('review_batch_000',result['time_budget']['stages_skipped'])
        self.assertIn('final_visual_check',result['time_budget']['stages_skipped'])
        self.assertIn({'code':'run_time_budget_spent','stages_skipped':result['time_budget']['stages_skipped']},
                      result['diagnostics'])
        self.assertNotIn('review_batch_000',self.calls)

    def test_batch_exports_source_pixels_and_refuses_reuse_for_changed_request(self):
        args=self.args('batch')
        with patch('chart_harness.cli.make_provider',side_effect=self.provider):
            result=batch(args)
            row=result['panels'][0]['rows'][0]
            self.assertAlmostEqual(row['page_pixel_x'],100,delta=1.)
            self.assertAlmostEqual(row['page_pixel_y'],80,delta=1.)
            self.assertTrue(Path(result['exports']['observed_csv']).exists())
            args.query='Different figure'
            with self.assertRaisesRegex(ValueError,'different input/config'):
                batch(args)

    def test_a_panel_box_running_off_the_sheet_is_trimmed_not_abandoned(self):
        """A box past the paper's edge still names a panel; the page is not thrown away."""
        original = self.provider
        def provider(config, out, role, not_after=None):
            made = original(config, out, role, not_after)
            inner = made.provider
            complete = inner.complete
            def wider(stage, prompt, images=(), schema=None):
                if stage == 'layout':
                    return {'panels': [{'id': 'one', 'label': 'one', 'crop_bbox': [50, 0, 4000, 4000]}]}
                return complete(stage, prompt, images, schema)
            inner.complete = wider
            return made
        with patch('chart_harness.cli.make_provider', side_effect=provider):
            result = batch(self.args('trimmed'))
        self.assertEqual(1, len(result['panels']))
        self.assertEqual('review_required', result['status'])

    def test_an_empty_legend_box_means_no_legend_not_a_dead_page(self):
        """Readers answer 'no legend' with a zero-area box; the page still runs."""
        original = self.provider
        def provider(config, out, role, not_after=None):
            made = original(config, out, role, not_after)
            inner = made.provider
            complete = inner.complete
            def with_empty_legend(stage, prompt, images=(), schema=None):
                if stage == 'layout':
                    return {'panels': [{'id': 'one', 'label': 'one', 'crop_bbox': [0, 0, 200, 160]}],
                            'legend_bbox': [0, 0, 0, 0]}
                return complete(stage, prompt, images, schema)
            inner.complete = with_empty_legend
            return made
        with patch('chart_harness.cli.make_provider', side_effect=provider):
            result = batch(self.args('nolegend'))
        self.assertEqual(1, len(result['panels']))

    def test_a_reader_declining_the_page_still_reports_the_ink_it_can_measure(self):
        """A reader's refusal is an opinion about the page, not the end of the run."""
        image=Image.open(self.source)
        draw=ImageDraw.Draw(image)
        draw.line((20,140,180,140),fill='black',width=1)
        draw.line((20,20,20,140),fill='black',width=1)
        for index,x in enumerate((40,70,100,130,160)):
            y=120-index*15
            draw.ellipse((x-4,y-4,x+4,y+4),fill='black')
        image.save(self.source)
        self.interpretation={'unsupported':True,'reason':'no legend and I am unsure',
                             'series':[]}
        with patch('chart_harness.cli.make_provider',side_effect=self.provider):
            result=run(self.args('declined'))
        self.assertEqual('review_required',result['status'])
        self.assertEqual([{'code':'reader_declined_the_page','reason':'no legend and I am unsure',
                           'carried_on':'marks measured on the pixels, reported without axis values'}],
                         result['diagnostics'])
        self.assertTrue(result['points'],'the printed ring is still on the page')
        for point in result['points']:
            self.assertIsNone(point['x'],'no reading means no axis values are invented')
            self.assertIsNotNone(point['pixel_x'])

    def test_a_loose_tick_fit_holds_the_run_to_review_instead_of_ending_it(self):
        """Anchors off one line make a scan hard to trust, not impossible to read."""
        self.interpretation['y_axis']={'scale':'log','unit':'ug/mL','anchors':[
            {'pixel':10,'value':1000},{'pixel':40,'value':30},{'pixel':150,'value':1}]}
        with patch('chart_harness.cli.make_provider',side_effect=self.provider):
            result=run(self.args('loose'))
        self.assertEqual('review_required',result['status'])
        loose=[d for d in result['diagnostics'] if d['code']=='axis_anchors_do_not_sit_on_one_line']
        self.assertTrue(loose)
        self.assertTrue(any('closest tick spacing' in c for c in loose[0]['detail']))

    def test_unrefined_model_coordinates_cannot_be_auto_exported(self):
        self.interpretation['series'][0]['marker']='point'
        with patch('chart_harness.cli.make_provider',side_effect=self.provider):
            result=run(self.args())
        self.assertEqual(result['counts']['observed'],0)
        self.assertEqual(result['status'],'review_required')

    def test_usage_deduplicates_historical_exchange_resume_events_and_keeps_unknown(self):
        p=self.root/'usage.jsonl'
        event={'event':'external_exchange','cache_key':'same','raw_artifact':'same.response.json'}
        p.write_text(json.dumps(event)+'\n'+json.dumps(event)+'\n')
        result=usage_report(self.root)
        self.assertEqual(result['external_exchange_packets_consumed'],1)
        self.assertEqual(result['duplicate_exchange_consumption_events'],1)
        self.assertIsNone(result['total_cost_usd'])
        self.assertEqual(result['unknown_usage_counts']['input_tokens'],1)


if __name__=='__main__':unittest.main()
