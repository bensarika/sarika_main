import argparse
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from PIL import Image
from chart_harness.cli import run
from chart_harness.visual_check import VisualCheckProvider

class ReviewContextTest(unittest.TestCase):
    def test_reviewer_receives_neutral_context_without_primary_axis_definition(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            Image.new('RGB',(100,100),'white').save(root/'image.png')
            (root/'config.json').write_text(json.dumps({'model':{'name':'stub','base_url':'http://localhost:1'},'recheck_axes':False}))
            (root/'context.txt').write_text('Neutral protocol excerpt: observed circles and predicted line.')
            axis={'scale':'linear','unit':'h','anchors':[{'pixel':10,'value':0},{'pixel':90,'value':8}]}
            seen={}
            def factory(config,out,role,not_after=None):
                class Stub:
                    def complete(self,stage,prompt,images=(),schema=None):
                        seen[stage]=prompt
                        if stage.endswith('_visual_check'):
                            points=json.loads(prompt.split('Fixed anchors: ',1)[1].split('\nYour result:',1)[0])
                            return {'annotations':[{'id':p['id'],'label':'Fixture','status':'unresolved'} for p in points],'assessment':'concerns'}
                        if stage=='interpret':
                            return {'plot_bbox':[10,10,90,90],'x_axis':copy.deepcopy(axis),'y_axis':copy.deepcopy(axis),'series':[{'id':'s1','label':'Fixture','marker':'point','seeds':[{'x':50,'y':50}]}]}
                        return {'axis_check':{'x_axis':axis,'y_axis':axis},'decisions':[],'status':'review_required','missing_points':[]}
                return VisualCheckProvider(Stub(),out/"visual_checks"/role)
            args=argparse.Namespace(source=str(root/'image.png'),config=str(root/'config.json'),out=str(root/'result'),query='observed',page=None,rotate=0,crop=None,context_file=str(root/'context.txt'),reference_image=None)
            with patch('chart_harness.cli.make_provider',side_effect=factory): run(args)
            self.assertIn('Neutral protocol excerpt',seen['review_axes'])
            self.assertNotIn('"pixel": 90',seen['review_axes'])

if __name__=='__main__': unittest.main()
