import tempfile,unittest
from pathlib import Path
from test_provider import stub_server
from chart_harness.provider import Provider,ModelConfig,InvalidResponse,_response_data
class ResponsesTests(unittest.TestCase):
 def test_wire_and_completion(self):
  response={'object':'response','status':'completed','output':[{'type':'reasoning'},{'type':'message','content':[{'type':'output_text','text':'{"ok":true}'}]}]}
  with tempfile.TemporaryDirectory() as tmp,stub_server([(200,response)]) as (url,received):
   result=Provider(ModelConfig(name='stub',base_url=url,wire_api='responses',json_mode=True),Path(tmp)).complete('test','Read')
   self.assertTrue(result['ok']);body=received[0]['body'];self.assertIn('input',body);self.assertNotIn('messages',body);self.assertFalse(body['store']);self.assertIn('max_output_tokens',body)
 def test_incomplete_rejected(self):
  with self.assertRaises(InvalidResponse):_response_data({'object':'response','status':'incomplete','output':[]})
