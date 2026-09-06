import json
import tempfile
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from chart_harness import progress
from chart_harness.server import Handler, Harness


def config(path, label):
    path.write_text(json.dumps({'provider_label': label,
                                'model': {'name': 'fixture',
                                          'base_url': 'http://localhost:1'}}))
    return str(path)


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.configs = [config(self.root / 'grok.json', 'grok'),
                        config(self.root / 'muse.json', 'muse')]
        self.harness = Harness(self.configs, self.root / 'runs', 'Observed points')
        self.started = threading.Event()
        Handler.harness = self.harness
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = 'http://127.0.0.1:%d' % self.server.server_port

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.temp.cleanup()

    def fake_batch(self, args):
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        progress.emit('legend_glyphs', glyphs=[])
        progress.emit('result', status='review_required', counts={'observed': 1},
                      rows=[], output_dir=str(out))
        return {'status': 'review_required', 'panels': []}

    def get(self, path):
        with urllib.request.urlopen(self.base + path) as response:
            return response.status, response.read()

    def post(self, path, data):
        request = urllib.request.Request(self.base + path, data=data, method='POST')
        try:
            with urllib.request.urlopen(request) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read())

    def run_upload(self, name='figure.png'):
        with patch('chart_harness.server.batch', side_effect=self.fake_batch), \
             patch('chart_harness.server.adjudicate') as adjudicated, \
             patch('chart_harness.server.source_context', return_value='context'):
            status, body = self.post('/runs?filename=' + name, b'not-a-real-png')
            if status == 200:
                run = self.harness.runs[body['run']]
                for _ in range(200):
                    if run.done:
                        break
                    threading.Event().wait(0.02)
            return status, body, adjudicated

    def test_the_page_and_the_side_names_are_served(self):
        self.assertIn(b'chart harness', self.get('/')[1])
        self.assertEqual(json.loads(self.get('/config')[1])['sides'], ['grok', 'muse'])

    def test_an_upload_runs_every_side_and_then_adjudicates(self):
        status, body, adjudicated = self.run_upload()
        self.assertEqual(status, 200)
        run = self.harness.runs[body['run']]
        self.assertTrue(run.done)
        self.assertEqual(adjudicated.call_count, 1)
        kinds = {(e.get('side'), e['kind']) for e in run.events}
        self.assertIn(('grok', 'result'), kinds)
        self.assertIn(('muse', 'result'), kinds)
        self.assertEqual(run.events[-1]['kind'], 'run_finished')
        self.assertEqual(run.events[-1]['statuses'],
                         {'grok': 'review_required', 'muse': 'review_required'})

    def test_events_are_numbered_so_a_reload_replays_them_in_order(self):
        _, body, _ = self.run_upload()
        run = self.harness.runs[body['run']]
        self.assertEqual([e['seq'] for e in run.events], list(range(len(run.events))))
        backlog, listener = run.subscribe()
        self.assertEqual(len(backlog), len(run.events))
        run.unsubscribe(listener)

    def test_a_failing_side_is_reported_without_stopping_the_other(self):
        def half_failing(args):
            if 'grok' in args.out:
                raise RuntimeError('provider exploded')
            return self.fake_batch(args)
        with patch('chart_harness.server.batch', side_effect=half_failing), \
             patch('chart_harness.server.adjudicate') as adjudicated:
            status, body = self.post('/runs?filename=figure.png', b'bytes')
            run = self.harness.runs[body['run']]
            for _ in range(200):
                if run.done:
                    break
                threading.Event().wait(0.02)
        failures = [e for e in run.events if e['kind'] == 'failed']
        self.assertEqual(failures[0]['side'], 'grok')
        self.assertIn('provider exploded', failures[0]['error'])
        self.assertEqual(adjudicated.call_count, 0)
        self.assertEqual(run.events[-1]['statuses']['muse'], 'review_required')

    def test_unsupported_uploads_are_refused_before_any_model_is_called(self):
        status, body, adjudicated = self.run_upload('notes.txt')
        self.assertEqual(status, 400)
        self.assertIn('unsupported file type', body['error'])
        self.assertEqual(self.harness.runs, {})

    def test_artifacts_are_served_only_from_inside_the_run_directory(self):
        _, body, _ = self.run_upload()
        run = self.harness.runs[body['run']]
        (run.dir / 'note.txt').write_text('hello')
        self.assertEqual(self.get('/file?run=%s&path=note.txt' % run.id)[1], b'hello')
        secret = self.root / 'secret.txt'
        secret.write_text('no')
        for path in ('../secret.txt', str(secret)):
            request = '/file?run=%s&path=%s' % (run.id, urllib.parse.quote(path))
            with self.assertRaises(urllib.error.HTTPError) as refused:
                self.get(request)
            self.assertEqual(refused.exception.code, 403)

    def test_a_watcher_note_is_kept_and_only_model_notes_reach_the_next_pass(self):
        _, body, _ = self.run_upload()
        run = self.harness.runs[body['run']]
        self.post('/notes?run=%s&side=grok&target=model' % run.id, b'six points, not three')
        self.post('/notes?run=%s&side=grok&target=harness' % run.id, b'the bars flicker')
        logged = [json.loads(line) for line in (run.dir / 'notes.jsonl').read_text().splitlines()]
        self.assertEqual(['model', 'harness'], [n['target'] for n in logged])
        self.assertEqual(['six points, not three'], run.notes_for('grok'))
        self.assertEqual([], run.notes_for('muse'))
        self.assertIn('six points', (run.dir / 'notes' / 'grok.md').read_text())
        self.assertEqual('note', run.events[-1]['kind'])

    def test_a_model_note_is_appended_to_the_corrections_the_second_pass_reads(self):
        _, body, _ = self.run_upload()
        run = self.harness.runs[body['run']]
        run.note('grok', 'model', 'the SC curve is one line plus a band')
        corrections = run.dir / 'feedback.md'
        corrections.write_text('measured corrections')
        self.harness._with_notes(run, run.sides[0], str(corrections))
        handed = corrections.read_text()
        self.assertIn('measured corrections', handed)
        self.assertIn('one line plus a band', handed)
        self.assertIn('weigh them against the pixels', handed)

    def test_empty_and_misaddressed_notes_are_refused(self):
        _, body, _ = self.run_upload()
        run = self.harness.runs[body['run']]
        self.assertEqual(400, self.post('/notes?run=%s&side=grok&target=model' % run.id, b'  ')[0])
        self.assertEqual(400, self.post('/notes?run=%s&side=nobody&target=model' % run.id, b'hi')[0])
        self.assertEqual(404, self.post('/notes?run=nope&side=grok&target=model', b'hi')[0])
        self.assertEqual([], run.notes)

    def test_an_unknown_run_has_no_event_stream(self):
        with self.assertRaises(urllib.error.HTTPError) as missing:
            self.get('/events?run=nope')
        self.assertEqual(missing.exception.code, 404)


if __name__ == '__main__':
    unittest.main()
