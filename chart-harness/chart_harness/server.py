"""Optional watcher: upload a figure, see both readers work on it side by side.

Nothing in the pipeline depends on this process. It uploads a file, starts the
same `batch` run per provider in its own thread, forwards `progress` events to
the browser as they happen, and serves the artifacts those events name. Stopping
it mid-run loses the view, not the work: every stage is already on disk and the
run resumes from there.

    python -m chart_harness.server --config configs/grok.json \
        --config configs/meta.json --runs ~/runs --port 8000

Serve it on a trusted interface only. It runs models against files it is handed
and exposes the run directory, so it has no place on a public address.
"""
import argparse
import contextvars
import json
import mimetypes
import queue
import threading
import time
import traceback
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from . import placed
from . import progress
from .cli import adjudicate, batch, duel_sides, source_context

PAGE = Path(__file__).parent / 'web' / 'index.html'
MAX_UPLOAD_BYTES = 64 * 1024 * 1024
ALLOWED_SUFFIXES = {'.pdf', '.png', '.jpg', '.jpeg', '.tif', '.tiff', '.webp', '.bmp'}
KEEPALIVE_SECONDS = 15.


class Run:
    """One uploaded figure being read; events are kept so a reload replays them."""

    def __init__(self, run_id, directory, source, sides):
        self.id = run_id
        self.dir = directory
        self.source = source
        self.sides = sides
        self.events = []
        self.listeners = []
        self.done = False
        self.lock = threading.Lock()
        self.notes = []
        self.placed = []

    def publish(self, event):
        with self.lock:
            event = {'seq': len(self.events), **event}
            self.events.append(event)
            listeners = list(self.listeners)
        for listener in listeners:
            listener.put(event)

    def subscribe(self):
        listener = queue.Queue()
        with self.lock:
            backlog = list(self.events)
            self.listeners.append(listener)
        return backlog, listener

    def note(self, side, target, text):
        """A watcher's remark: to the reader for its next pass, or about the harness.

        Both are kept with the run. Only the ones addressed to a reader are handed
        to it, and they arrive as context alongside the measurements, so a remark
        can be weighed and contradicted by the pixels rather than obeyed.
        """
        text = (text or '').strip()
        if not text:
            raise ValueError('empty note')
        if target not in ('model', 'harness'):
            raise ValueError('note target must be model or harness')
        if side != 'harness' and side not in [s['name'] for s in self.sides]:
            raise ValueError('unknown side: ' + side)
        note = {'side': side, 'target': target, 'text': text[:4000], 'at': time.time()}
        self.notes.append(note)
        with (self.dir / 'notes.jsonl').open('a') as log:
            log.write(json.dumps(note) + '\n')
        if target == 'model':
            path = self.dir / 'notes' / (side + '.md')
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open('a') as handed:
                handed.write('- ' + note['text'].replace('\n', ' ') + '\n')
        self.publish({'kind': 'note', **note})
        return note

    def notes_for(self, side):
        return [n['text'] for n in self.notes
                if n['target'] == 'model' and n['side'] == side] + [
                placed.sentence(m) for m in self.placed
                if m['side'] in (side, 'both')]

    def place(self, side, image, x, y, group=None, kind='data'):
        """A mark a watcher put on the figure: measured, kept, and handed on.

        The click is checked against the pixels under it rather than taken on
        trust - carried onto the ink body it was aimed at, or recorded as
        pointing at blank paper - and then travels to the reader as a correction
        for its next pass, the same way a written remark does.
        """
        if side != 'both' and side not in [s['name'] for s in self.sides]:
            raise ValueError('unknown side: ' + side)
        target = self._within(image)
        mark = placed.place(target, x, y, group, kind,
                            reach=self._mark_size(target))
        mark['side'] = side
        mark['image'] = str(Path(image))
        self.placed.append(mark)
        placed.record(self.dir, mark)
        self.publish({'kind': 'placed_mark', 'at': mark['at'], 'side': side,
                      'mark': mark})
        return mark

    def _within(self, image):
        """An image path is only ever one inside this run's own directory."""
        target = (self.dir / image).resolve()
        target.relative_to(self.dir.resolve())
        if not target.is_file():
            raise ValueError('no such image in this run: ' + str(image))
        return target

    def _mark_size(self, image):
        """How big a mark is on this figure, from what python already measured."""
        sizes = []
        for found in self.dir.rglob('detected_marks.json'):
            try:
                marks = json.loads(found.read_text()).get('pooled') or []
            except (OSError, ValueError):
                continue
            sizes += [m.get('width') for m in marks if m.get('width')]
        return placed.reach_from(sizes)

    def unsubscribe(self, listener):
        with self.lock:
            if listener in self.listeners:
                self.listeners.remove(listener)


class Harness:
    """Runs uploads through the same CLI stages the command line uses."""

    def __init__(self, config_paths, runs_root, query, page=None):
        self.config_paths = [str(Path(p).resolve()) for p in config_paths]
        self.root = Path(runs_root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.query = query
        self.page = page
        self.runs = {}

    def sides(self):
        return duel_sides(self.config_paths)

    def start(self, filename, data, query=None, page=None):
        suffix = Path(filename).suffix.lower()
        if suffix not in ALLOWED_SUFFIXES:
            raise ValueError(f'unsupported file type: {suffix or filename}')
        run_id = time.strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:6]
        directory = self.root / run_id
        (directory / 'input').mkdir(parents=True)
        source = directory / 'input' / ('figure' + suffix)
        source.write_bytes(data)
        run = Run(run_id, directory, source, self.sides())
        self.runs[run_id] = run
        threading.Thread(target=self._execute, name='run-' + run_id, daemon=True,
                         args=(run, query or self.query,
                               self.page if page is None else page)).start()
        return run

    def _args(self, run, side, directory, query, page, context_file=None):
        return argparse.Namespace(source=str(run.source), config=side['config_path'],
                                  out=str(directory), query=query, page=page, rotate=0,
                                  crop=None, context_file=context_file,
                                  reference_image=None, reference_images=[])

    def _with_notes(self, run, side, context_file):
        """Hand the watcher's remarks to the next pass along with the corrections."""
        watching = run.notes_for(side['name'])
        # A correction is worth nothing if it only reaches the log; it is handed
        # to the next pass as context, to be weighed against the pixels.
        if not watching or not context_file:
            return context_file
        path = Path(context_file)
        path.write_text(path.read_text() + '\n\nWatcher notes (a person looking at '
                        'this figure; weigh them against the pixels, they are not '
                        'measurements):\n' + '\n'.join('- ' + n for n in watching))
        return context_file

    def _side_thread(self, run, side, query, page):
        def body():
            with progress.listening(lambda event: run.publish({'side': side['name'],
                                                               **event})):
                try:
                    side['dir'] = run.dir / side['name']
                    side['result'] = batch(self._args(run, side, side['dir'], query, page))
                except Exception as error:
                    side['error'] = str(error)
                    run.publish({'side': side['name'], 'kind': 'failed',
                                 'at': time.time(), 'error': str(error),
                                 'detail': traceback.format_exc()[-2000:]})
        return threading.Thread(target=contextvars.copy_context().run, args=(body,),
                                name=f"{run.id}-{side['name']}", daemon=True)

    def _rerun(self, run, side, directory, query, page, context_file):
        """A second pass belongs to its side's column, not to the adjudication."""
        with progress.listening(lambda event: run.publish({'side': side['name'], **event})):
            return batch(self._args(run, side, directory, query, page,
                                    self._with_notes(run, side, context_file)))

    def _execute(self, run, query, page):
        run.publish({'kind': 'run_started', 'at': time.time(), 'run': run.id,
                     'sides': [s['name'] for s in run.sides],
                     'source': str(run.source), 'query': query})
        threads = [self._side_thread(run, side, query, page) for side in run.sides]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        try:
            if all(side.get('dir') and not side.get('error') for side in run.sides):
                with progress.listening(lambda event: run.publish({'side': 'both',
                                                                   **event})):
                    context = source_context(
                        self._args(run, run.sides[0], run.dir, query, page),
                        run.sides[0]['config'], run.source)
                    adjudicate(run.sides, run.dir, context,
                               lambda side, directory, context_file: self._rerun(
                                   run, side, directory, query, page, context_file))
        except Exception as error:
            run.publish({'kind': 'failed', 'side': 'both', 'at': time.time(),
                         'error': str(error), 'detail': traceback.format_exc()[-2000:]})
        run.done = True
        run.publish({'kind': 'run_finished', 'at': time.time(),
                     'statuses': {s['name']: (s.get('error') or
                                              (s.get('result') or {}).get('status'))
                                  for s in run.sides}})


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    harness = None

    def log_message(self, fmt, *args):
        pass

    def _send(self, code, body, content_type='application/json', extra=()):
        self.send_response(code)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        for key, value in extra:
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code, payload):
        self._send(code, json.dumps(payload).encode())

    def do_GET(self):
        url = urlsplit(self.path)
        params = {k: v[0] for k, v in parse_qs(url.query).items()}
        if url.path in ('/', '/index.html'):
            return self._send(200, PAGE.read_bytes(), 'text/html; charset=utf-8')
        if url.path == '/config':
            return self._json(200, {'sides': [s['name'] for s in self.harness.sides()],
                                    'query': self.harness.query})
        if url.path == '/events':
            return self._events(params.get('run', ''))
        if url.path == '/file':
            return self._file(params.get('run', ''), params.get('path', ''))
        self._json(404, {'error': 'not found'})

    def do_POST(self):
        url = urlsplit(self.path)
        params = {k: v[0] for k, v in parse_qs(url.query).items()}
        if url.path == '/marks':
            run = self.harness.runs.get(params.get('run', ''))
            if run is None:
                return self._json(404, {'error': 'unknown run'})
            length = int(self.headers.get('Content-Length') or 0)
            body = self.rfile.read(min(length, 8192)).decode('utf-8', 'replace')
            try:
                asked = json.loads(body or '{}')
                return self._json(200, run.place(
                    params.get('side', 'both'), asked['image'],
                    float(asked['x']), float(asked['y']),
                    asked.get('group'), asked.get('kind', 'data')))
            except (ValueError, KeyError, TypeError) as error:
                return self._json(400, {'error': str(error)})
        if url.path == '/notes':
            run = self.harness.runs.get(params.get('run', ''))
            if run is None:
                return self._json(404, {'error': 'unknown run'})
            length = int(self.headers.get('Content-Length') or 0)
            text = self.rfile.read(min(length, 8192)).decode('utf-8', 'replace')
            try:
                return self._json(200, run.note(params.get('side', 'harness'),
                                                params.get('target', 'harness'), text))
            except ValueError as error:
                return self._json(400, {'error': str(error)})
        if url.path != '/runs':
            return self._json(404, {'error': 'not found'})
        length = int(self.headers.get('Content-Length') or 0)
        if not 0 < length <= MAX_UPLOAD_BYTES:
            return self._json(413, {'error': 'upload must be 1 byte to 64 MB'})
        data = self.rfile.read(length)
        page = params.get('page')
        try:
            run = self.harness.start(params.get('filename', 'figure.png'), data,
                                     params.get('query') or None,
                                     int(page) if page else None)
        except ValueError as error:
            return self._json(400, {'error': str(error)})
        self._json(200, {'run': run.id})

    def _events(self, run_id):
        run = self.harness.runs.get(run_id)
        if run is None:
            return self._json(404, {'error': 'unknown run'})
        backlog, listener = run.subscribe()
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Connection', 'close')
        self.end_headers()
        try:
            for event in backlog:
                self._event(event)
            while True:
                try:
                    self._event(listener.get(timeout=KEEPALIVE_SECONDS))
                except queue.Empty:
                    if run.done:
                        break
                    self.wfile.write(b': keepalive\n\n')
                    self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            run.unsubscribe(listener)

    def _event(self, event):
        self.wfile.write(b'data: ' + json.dumps(event).encode() + b'\n\n')
        self.wfile.flush()

    def _file(self, run_id, path):
        run = self.harness.runs.get(run_id)
        if run is None:
            return self._json(404, {'error': 'unknown run'})
        try:
            target = (run.dir / path).resolve() if not Path(path).is_absolute() \
                else Path(path).resolve()
            target.relative_to(run.dir.resolve())
        except ValueError:
            return self._json(403, {'error': 'path outside the run directory'})
        if not target.is_file():
            return self._json(404, {'error': 'no such artifact'})
        kind = mimetypes.guess_type(target.name)[0] or 'application/octet-stream'
        self._send(200, target.read_bytes(), kind)


def serve(config_paths, runs_root, query, port=8000, host='127.0.0.1', page=None):
    Handler.harness = Harness(config_paths, runs_root, query, page)
    server = ThreadingHTTPServer((host, port), Handler)
    print(f'watching on http://{host}:{port} (runs in {Handler.harness.root})')
    server.serve_forever()


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--config', action='append', required=True,
                        help='Provider config; give it twice for a side-by-side duel')
    parser.add_argument('--runs', default='runs', help='Where run directories are written')
    parser.add_argument('--query',
                        default='Extract all observed PK concentration-versus-time data points')
    parser.add_argument('--page', type=int, help='Fix the PDF page instead of locating it')
    parser.add_argument('--port', type=int, default=8000)
    parser.add_argument('--host', default='127.0.0.1')
    args = parser.parse_args()
    serve(args.config, args.runs, args.query, args.port, args.host, args.page)


if __name__ == '__main__':
    main()
