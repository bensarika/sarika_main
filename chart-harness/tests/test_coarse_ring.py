import unittest,numpy as np
from PIL import Image,ImageDraw
from chart_harness.geometry import _ring_refine
class CoarseRingTests(unittest.TestCase):
 def test_offset_ring_and_blank(self):
  image=Image.new('L',(160,160),255);ImageDraw.Draw(image).ellipse((68,68,92,92),outline=0,width=3)
  series={'radius':11,'radius_range':[8,14],'search_radius':30,'coarse_ring_search':True}
  x,y,support,_=_ring_refine(np.asarray(image,dtype=float)/255,{'x':62,'y':65},series,[5,5,155,155])
  self.assertEqual(support,'supported');self.assertLess(np.hypot(x-80,y-80),2)
  self.assertEqual(_ring_refine(np.ones((160,160)),{'x':62,'y':65},series,[5,5,155,155])[2],'unsupported')
