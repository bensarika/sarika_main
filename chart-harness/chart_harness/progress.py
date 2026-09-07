"""Stage events for an optional observer; the pipeline never depends on one.

The harness is a batch program: every stage already writes its artifact to disk,
and that file, not an event, is the record. Events exist only so a watcher can
see the work happen in the order it happens — which glyph was cut out of the
legend, which candidate the pixels rejected and by how far. Nothing reads them
back, so a missing or slow listener cannot change a result.
"""
import contextvars
import time
from contextlib import contextmanager

_sink = contextvars.ContextVar('progress_sink', default=None)


@contextmanager
def listening(sink):
    """Route events emitted in this context (and threads copied from it) to sink."""
    token = _sink.set(sink)
    try:
        yield
    finally:
        _sink.reset(token)


def bound(function):
    """Carry the current listener into a worker thread.

    A thread starts with an empty context, so work handed to a pool would emit
    into nothing and the watcher would see a run go silent exactly while the
    parallel stages are the busiest. The sink is captured here and re-set inside
    the worker; copying the whole context instead would fail, because one context
    cannot be entered by two threads at once.
    """
    sink = _sink.get()

    def run(*args, **kwargs):
        token = _sink.set(sink)
        try:
            return function(*args, **kwargs)
        finally:
            _sink.reset(token)
    return run


def say(text, source='harness'):
    """A sentence about what is happening, for a person watching the run.

    Stage events say which stage ran; they do not say what the reader concluded
    or what the pixels showed, and a watcher staring at a spinner has no way to
    tell a slow call from a stuck one. This carries the readers' own words and
    the harness's measurements in plain language, alongside the machine events
    rather than instead of them.
    """
    if text:
        emit('say', text=str(text)[:600], source=source)


def emit(kind, **fields):
    """Report that something happened. Never raises into the pipeline."""
    sink = _sink.get()
    if sink is None:
        return
    try:
        sink({'kind': kind, 'at': time.time(), **fields})
    except Exception:  # an observer's failure is not the run's failure
        pass
