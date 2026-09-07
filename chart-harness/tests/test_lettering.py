import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

from chart_harness import lettering

BOX = (20, 20, 380, 280)


def blank():
    image = Image.new('RGB', (400, 300), 'white')
    return image, ImageDraw.Draw(image)


def write(drawn, at, word='Placebo'):
    """A word set in the middle of a plot: small shapes of differing size, close
    together, standing free of anything drawn."""
    drawn.text(at, word, fill='black')


class LetteringTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def save(self, image, name):
        path = self.root / name
        image.save(path)
        return path

    def test_a_word_written_in_the_plot_is_found(self):
        image, drawn = blank()
        write(drawn, (150, 140))
        found = lettering.blocks(self.save(image, 'word.png'), BOX)
        self.assertTrue(found)
        self.assertTrue(all(150 <= box[0] <= 250 and 130 <= box[1] <= 160
                            for box in found))

    def test_bare_paper_carries_no_writing(self):
        image, _ = blank()
        self.assertEqual(lettering.blocks(self.save(image, 'bare.png'), BOX), [])

    def test_marks_stamped_along_a_curve_are_not_read_as_writing(self):
        image, drawn = blank()
        drawn.line([(40, 250), (360, 80)], fill='black', width=3)
        for step in range(6):
            x = 60 + step * 55
            y = 250 - step * 29
            drawn.ellipse([x - 6, y - 6, x + 6, y + 6], fill='black')
        found = lettering.blocks(self.save(image, 'marks.png'), BOX)
        self.assertEqual(found, [])

    def test_a_mark_standing_in_open_paper_beside_a_word_is_kept(self):
        image, drawn = blank()
        write(drawn, (150, 140))
        written = lettering.blocks(self.save(image, 'beside.png'), BOX)
        marks = [{'x': 60., 'y': 60.}, {'x': written[0][0] + .5,
                                        'y': (written[0][1] + written[0][3]) / 2.}]
        kept = lettering.clear_of(marks, written)
        self.assertEqual(kept, [marks[0]])

    def test_no_writing_leaves_every_mark_alone(self):
        marks = [{'x': 10., 'y': 10.}, {'x': 20., 'y': 30.}]
        self.assertEqual(lettering.clear_of(marks, []), marks)


if __name__ == '__main__':
    unittest.main()
