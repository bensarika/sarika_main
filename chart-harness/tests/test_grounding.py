import unittest
from chart_harness.grounding import pixel,to_native
class GroundingTests(unittest.TestCase):
 def test_non_square_and_edge(self):
  self.assertEqual(pixel(500,1440),720);self.assertEqual(pixel(500,1320),660)
  self.assertEqual(pixel(1001,1440),1439)
  with self.assertRaises(ValueError):pixel(1440,1440)
 def test_conversion_preserves_values(self):
  d={'plot_bbox':[0,0,1000,1000],'x_axis':{'anchors':[{'pixel':500,'value':10}]},'y_axis':{'anchors':[{'pixel':250,'value':100}]},'series':[{'seeds':[{'x':500,'y':250}]}]}
  o=to_native(d,1440,1320)
  self.assertEqual(o['series'][0]['seeds'][0],{'x':720,'y':330});self.assertEqual(o['y_axis']['anchors'][0]['value'],100)
  self.assertEqual(d['series'][0]['seeds'][0]['x'],500)
