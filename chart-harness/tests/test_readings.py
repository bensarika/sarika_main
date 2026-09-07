import unittest

from chart_harness import progress
from chart_harness.cli import race_readings, with_reasoning_effort


def reading(series, box=(10, 10, 90, 90)):
    return {'plot_bbox': list(box),
            'series': [{'id': f's{i}', 'label': f'series {i}'} for i in range(series)]}


class Reader:
    """Stands in for a provider: answers with whatever the depth was told to say."""

    def __init__(self, answer):
        self.answer = answer
        self.asked = 0

    def complete(self, *args, **kwargs):
        self.asked += 1
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


def race(answers, size=(100, 100)):
    readers = {effort: Reader(answer) for effort, answer in answers.items()}
    said = []
    with progress.listening(said.append):
        kept = race_readings(list(answers), readers,
                             lambda effort, provider: provider.complete(), size, 'reader')
    return kept, readers, [e['text'] for e in said if e['kind'] == 'say']


class RaceTests(unittest.TestCase):
    def test_asks_every_depth_and_keeps_the_deepest(self):
        kept, readers, _ = race({'low': reading(1), 'high': reading(3)})
        self.assertEqual([r.asked for r in readers.values()], [1, 1])
        self.assertEqual(kept['reasoning_effort'], 'high')
        self.assertEqual(len(kept['series']), 3)

    def test_reports_each_reading_as_it_lands(self):
        _, _, said = race({'low': reading(1), 'high': reading(3)})
        self.assertTrue(any('low-reasoning reading is in' in s for s in said))
        self.assertTrue(any('high-reasoning reading is in' in s for s in said))

    def test_a_disagreement_is_reported_not_hidden(self):
        _, _, said = race({'low': reading(1), 'high': reading(3)})
        self.assertTrue(any('disagree on how many series' in s for s in said))
        self.assertEqual(race({'low': reading(1), 'high': reading(3)})[0]['other_readings'],
                         {'low': {'series': 1}})

    def test_the_quick_reading_carries_the_run_when_the_deep_one_fails(self):
        kept, _, said = race({'low': reading(2), 'high': RuntimeError('gateway timeout')})
        self.assertEqual(kept['reasoning_effort'], 'low')
        self.assertTrue(any('unusable' in s for s in said))

    def test_a_frame_past_the_page_edge_is_held_to_the_page_not_thrown_away(self):
        kept, _, said = race({'low': reading(2), 'high': reading(3, box=(0, 0, 500, 500))})
        self.assertEqual(kept['reasoning_effort'], 'high')
        self.assertEqual([0, 0, 100, 100], kept['plot_bbox'])
        self.assertTrue(any('held it to the image' in s for s in said))

    def test_a_reading_with_no_frame_on_the_page_is_rejected(self):
        kept, _, _ = race({'low': reading(2), 'high': reading(3, box=(400, 400, 500, 500))})
        self.assertEqual(kept['reasoning_effort'], 'low')

    def test_a_reading_that_found_series_beats_a_deeper_one_that_gave_up(self):
        empty = reading(1)
        empty['series'] = []
        empty['unsupported'] = True
        kept, _, said = race({'low': reading(2), 'high': empty})
        self.assertEqual(kept['reasoning_effort'], 'low')
        self.assertTrue(any('found something' in s for s in said))

    def test_no_sound_reading_is_an_error(self):
        with self.assertRaises(ValueError):
            race({'low': RuntimeError('nope'), 'high': RuntimeError('nope')})


class EffortTests(unittest.TestCase):
    def test_only_the_effort_changes(self):
        config = {'model': {'name': 'm', 'reasoning_effort': 'high'}, 'limits': {'max_calls': 3}}
        deeper = with_reasoning_effort(config, 'low')
        self.assertEqual(deeper['model']['reasoning_effort'], 'low')
        self.assertEqual(deeper['limits'], config['limits'])
        self.assertEqual(config['model']['reasoning_effort'], 'high')

    def test_a_role_specific_reader_is_changed_too(self):
        config = {'model': {'name': 'm'}, 'reviewer': {'name': 'r', 'reasoning_effort': 'high'}}
        self.assertEqual(with_reasoning_effort(config, 'low')['reviewer']['reasoning_effort'], 'low')


if __name__ == '__main__':
    unittest.main()
