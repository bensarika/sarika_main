"""Pull the words a document says about a figure out of the document itself.

A caption states what was measured, how many curves there are, and often when
samples were taken. Without it a reader invents structure: it looks for six
curves in a figure that plots one curve and a confidence band, or for marks at
times nobody sampled. The text is evidence, so it is extracted deterministically
and handed over with the image.
"""
import re

from . import ingest

FIGURE_PATTERN = re.compile(r'\bfig(?:ure)?\.?\s*([0-9]+[A-Za-z]?)\b', re.IGNORECASE)
NEIGHBOURHOOD = 1


def figure_tokens(query):
    """Figure identifiers named in the request, e.g. FIG. 7 -> {'7'}."""
    return {m.group(1).lower() for m in FIGURE_PATTERN.finditer(query or '')}


def _pages(source):
    with ingest._fitz().open(source) as document:
        return [page.get_text() for page in document]


def _paragraphs(text):
    return [p.strip() for p in re.split(r'\n\s*\n|\n(?=\s*\[?\d{4}\]?)', text)
            if p.strip()]


def figure_context(source, query, page=None, limit=6000):
    """Caption and description paragraphs for the requested figure.

    Paragraphs naming the figure come first because a patent describes a figure
    in its brief description and again in the examples; both are wanted, and the
    page the figure is drawn on usually holds only the drawing.
    """
    tokens = figure_tokens(query)
    try:
        pages = _pages(source)
    except Exception:
        return ''
    selected, seen = [], set()
    for index, text in enumerate(pages):
        for paragraph in _paragraphs(text):
            names = {m.group(1).lower() for m in FIGURE_PATTERN.finditer(paragraph)}
            near_page = page is not None and abs(index + 1 - page) <= NEIGHBOURHOOD
            if not (names & tokens) and not (near_page and not tokens):
                continue
            key = paragraph[:120]
            if key in seen:
                continue
            seen.add(key)
            selected.append({'page': index + 1, 'text': paragraph,
                             'names_figure': bool(names & tokens)})
    selected.sort(key=lambda p: (not p['names_figure'], p['page']))
    out, total = [], 0
    for entry in selected:
        chunk = entry['text'][:max(0, limit - total)]
        if not chunk:
            break
        out.append(f"[page {entry['page']}] {chunk}")
        total += len(chunk)
        if total >= limit:
            break
    return '\n\n'.join(out)
