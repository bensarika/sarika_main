"""A watcher must not go blind exactly when the run fans out into threads."""
import unittest
from concurrent.futures import ThreadPoolExecutor

from chart_harness import progress


class Threads(unittest.TestCase):
    def test_events_from_worker_threads_reach_the_listener(self):
        seen = []
        with progress.listening(seen.append):
            with ThreadPoolExecutor(max_workers=3) as pool:
                list(pool.map(progress.bound(lambda n: progress.emit('step', n=n)),
                              range(3)))
        self.assertEqual({0, 1, 2}, {event['n'] for event in seen})

    def test_an_unbound_worker_is_silent_rather_than_crashing(self):
        seen = []
        with progress.listening(seen.append):
            with ThreadPoolExecutor(max_workers=1) as pool:
                list(pool.map(lambda n: progress.emit('step', n=n), range(2)))
        self.assertEqual([], seen)


class Sentences(unittest.TestCase):
    """A watcher is told what is happening, not only which stage is running."""

    def test_a_sentence_carries_who_said_it(self):
        seen = []
        with progress.listening(seen.append):
            progress.say('reads this as three series', source='grok')
        self.assertEqual([('say', 'reads this as three series', 'grok')],
                         [(e['kind'], e['text'], e['source']) for e in seen])

    def test_the_harness_speaks_for_itself_by_default(self):
        seen = []
        with progress.listening(seen.append):
            progress.say('measured 7 ticks across')
        self.assertEqual('harness', seen[0]['source'])

    def test_nothing_is_said_when_there_is_nothing_to_say(self):
        seen = []
        with progress.listening(seen.append):
            progress.say('')
            progress.say(None)
        self.assertEqual([], seen)

    def test_a_long_sentence_is_cut_rather_than_flooding_the_watcher(self):
        seen = []
        with progress.listening(seen.append):
            progress.say('x' * 5000)
        self.assertEqual(600, len(seen[0]['text']))


if __name__ == '__main__':
    unittest.main()
