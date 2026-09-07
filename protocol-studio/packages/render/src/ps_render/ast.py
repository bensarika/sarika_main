"""Render AST: the small, exporter-neutral document tree.

Deliberately tiny — headings, paragraphs, bullet lists, tables, notes. Anything
richer (figures, cross-references) is added here first, then to both writers.
Inline text is plain; emphasis is expressed with ``**bold**`` / ``*italic*``
markers that each writer interprets.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Heading:
    level: int  # 1 = section, 2 = subsection, 3 = sub-subsection
    number: str  # "3.2"
    text: str
    anchor: str  # stable id, e.g. "section.3.2"


@dataclass(frozen=True)
class Paragraph:
    text: str
    block_id: str | None = None  # source editor block
    annotation: str | None = None  # "generated" | "unbound" | "mismatch" | None


@dataclass(frozen=True)
class BulletList:
    items: tuple[str, ...]


@dataclass(frozen=True)
class Table:
    caption: str
    header: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]
    footnotes: tuple[str, ...] = ()


@dataclass(frozen=True)
class Note:
    """A rendered margin/box note, e.g. 'Section not yet written'."""

    text: str
    kind: str = "info"  # info | warning


Block = Heading | Paragraph | BulletList | Table | Note


@dataclass
class Document:
    title: str
    subtitle: str
    identifiers: tuple[tuple[str, str], ...]  # (label, value) for the title page
    blocks: list[Block] = field(default_factory=list)
    footer: str = ""
