import tempfile
import unittest
from pathlib import Path

import fitz

from chart_harness import doc_context

BRIEF = ('[0012] FIG. 7 shows mean serum concentration versus time after a '
         'single intravenous dose, with the shaded area giving the 90% '
         'confidence interval around the fitted curve.')
EXAMPLE = ('[0104] Samples were drawn at 0, 24, 168, 336 and 672 hours. In '
           'FIG. 7 the observed means are plotted as filled circles.')
OTHER = '[0013] FIG. 8 shows a schematic of the manufacturing process.'


def document(path, pages):
    doc = fitz.open()
    for text in pages:
        page = doc.new_page()
        page.insert_textbox(fitz.Rect(40, 40, 550, 700), text, fontsize=10)
    doc.save(path)
    doc.close()
    return path


class FigureContext(unittest.TestCase):
    def setUp(self):
        self.pdf = document(Path(tempfile.mkdtemp()) / 'patent.pdf',
                            [BRIEF + '\n\n' + OTHER, EXAMPLE])

    def test_paragraphs_naming_the_figure_are_collected_across_pages(self):
        context = doc_context.figure_context(self.pdf, 'digitize FIG. 7')
        self.assertIn('confidence interval', context)
        self.assertIn('336', context)
        self.assertNotIn('manufacturing process', context)

    def test_context_is_bounded(self):
        context = doc_context.figure_context(self.pdf, 'FIG. 7', limit=60)
        self.assertLessEqual(len(context), 60 + len('[page 1] '))

    def test_a_figure_with_no_description_yields_nothing(self):
        self.assertEqual('', doc_context.figure_context(self.pdf, 'FIG. 41'))

    def test_an_unreadable_source_is_not_fatal(self):
        self.assertEqual('', doc_context.figure_context('/nonexistent.pdf', 'FIG. 7'))

    def test_figure_tokens_read_several_spellings(self):
        self.assertEqual({'7'}, doc_context.figure_tokens('FIG. 7'))
        self.assertEqual({'7a'}, doc_context.figure_tokens('figure 7A'))
        self.assertEqual(set(), doc_context.figure_tokens('the second panel'))

    def test_without_a_named_figure_the_page_itself_supplies_context(self):
        context = doc_context.figure_context(self.pdf, 'the PK panel', page=2)
        self.assertIn('336', context)


if __name__ == '__main__':
    unittest.main()
