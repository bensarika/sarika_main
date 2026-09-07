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


if __name__ == '__main__':
    unittest.main()
