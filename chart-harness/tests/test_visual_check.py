import json,tempfile,unittest
from pathlib import Path
from PIL import Image
from chart_harness.visual_check import VisualCheckProvider,VisualCheckError
from chart_harness.review_validation import enforce_marker_centers
class VisualTests(unittest.TestCase):
 def test_same_provider_fixed_anchors_and_required_completeness(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);im=root/'input.png';Image.new('RGB',(100,80),'white').save(im)
   class Stub:
    calls=[]
    def complete(self,stage,prompt,images=(),schema=None):
     self.calls.append(stage)
     if stage=='interpret':return {'series':[{'id':'s','seeds':[{'x':50,'y':40}]}]}
     return {'annotations':[{'id':'s:1','label':'my measurement','status':'unresolved','x':9999}],'assessment':'concerns'}
   stub=Stub();p=VisualCheckProvider(stub,root/'checks');result=p.complete('interpret','read',[im])
   self.assertEqual(stub.calls,['interpret','interpret_visual_check'])
   self.assertEqual(result['_visual_check']['anchors'][0]['x'],50)
   self.assertTrue(Path(result['_visual_check']['image_path']).exists())
   self.assertEqual(Image.open(im).getpixel((50,40)),(255,255,255))
 def test_missing_annotation_does_not_pass(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);im=root/'input.png';Image.new('RGB',(100,80),'white').save(im)
   class Stub:
    def complete(self,stage,*args):
     return {'annotations':[],'assessment':'consistent'} if stage.endswith('visual_check') else {'series':[{'id':'s','seeds':[{'x':50,'y':40}]}]}
   with self.assertRaises(VisualCheckError):VisualCheckProvider(Stub(),root).complete('interpret','read',[im])
   self.assertTrue((root/'interpret.primary.json').exists());self.assertTrue((root/'interpret.failure.json').exists())
 def test_unstrict_check_keeps_the_stage_but_records_a_concern(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);im=root/'input.png';Image.new('RGB',(100,80),'white').save(im)
   class Stub:
    def complete(self,stage,*args):
     return {'annotations':[],'assessment':'consistent'} if stage.endswith('visual_check') else {'series':[{'id':'s','seeds':[{'x':50,'y':40}]}]}
   result=VisualCheckProvider(Stub(),root,strict=False).complete('interpret','read',[im])
   self.assertEqual(result['_visual_check']['assessment'],'concerns')
   self.assertEqual(result['_visual_check']['status'],'unavailable')
   self.assertEqual(result['series'][0]['seeds'],[{'x':50,'y':40}])
   self.assertTrue((root/'interpret.failure.json').exists())
 def test_independent_center_disagreement_and_missing_center(self):
  # Agreement is judged against the measured size of this mark, so the same
  # code holds a 3 px dot and a 40 px ring to proportionate standards.
  proposals={'candidates':[{'candidate_id':'p','pixel':{'x':300.46,'y':513.10},
    'diagnostics':{'rx':4.,'ry':4.}}]}
  for center in [None,{'x':318.04,'y':538.10}]:
   d={'candidate_id':'p','role':'observed','reason':'visible'}
   if center:d['marker_center']=center
   r=enforce_marker_centers({'status':'accepted','decisions':[d]},proposals)
   self.assertEqual(r['decisions'][0]['role'],'unresolved')
  r=enforce_marker_centers({'status':'accepted','decisions':[{'candidate_id':'p','role':'observed','marker_center':{'x':300.5,'y':513.1}}]},proposals)
  self.assertEqual(r['decisions'][0]['role'],'observed')
 def test_a_mark_of_unknown_size_cannot_be_agreed_with(self):
  # Nothing measured the mark, so there is no scale to judge the reader's
  # centre against and the decision is not allowed to stand as an observation.
  proposals={'candidates':[{'candidate_id':'p','pixel':{'x':10.,'y':10.}}]}
  r=enforce_marker_centers({'status':'accepted','decisions':[
    {'candidate_id':'p','role':'observed','marker_center':{'x':10.,'y':10.}}]},proposals)
  self.assertEqual(r['decisions'][0]['role'],'unresolved')
  self.assertIsNone(r['marker_center_checks'][0]['tolerance_px'])
