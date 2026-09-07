"""Canonical outline: Section 0 (identity/document control) + ICH M11 sections 1–14.

Loaded from ``reference/canonical_outline.json`` (application-oriented synthesis)
and cross-referenced to ``reference/ich_m11_outline.json`` (pinned Nov-2025
template headings) so the renderer can label each section with its M11 number.
Section 1 is a *generated view*: its content is derived from the model and is
read-only in the editor.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache

from ps_model.schema import reference_dir


@dataclass(frozen=True)
class Subsection:
    id: str  # "section.3.2"
    title: str


@dataclass(frozen=True)
class Section:
    id: str  # "section.3"
    number: int  # 0..14
    title: str
    subsections: tuple[Subsection, ...]
    object_summary: str
    generated_view: bool
    # Entity collections that *primarily* live in this section. Used by the UI
    # to offer "add entity" actions and by completion to scope required slots.
    collections: tuple[str, ...] = field(default_factory=tuple)


# Which top-level model collections belong to which section. This mapping is the
# bridge between the flat toolkit schema and the outline the author sees.
_SECTION_COLLECTIONS: dict[int, tuple[str, ...]] = {
    0: ("protocol", "roles", "dependencies", "sources"),
    1: (),
    2: (),
    3: ("objectives", "endpoints", "estimands"),
    4: ("periods", "paths", "allocations", "transitions"),
    5: ("populations", "criteria"),
    6: ("products", "regimens"),
    7: ("events", "rules"),
    8: ("assessments", "encounters", "scheduled_activities"),
    9: (),
    10: ("analysis_sets", "analyses", "testing_families"),
    11: ("governance",),
    12: (),
    13: (),
    14: (),
}


@lru_cache(maxsize=1)
def _load() -> tuple[Section, ...]:
    with (reference_dir() / "canonical_outline.json").open(encoding="utf-8") as fh:
        raw = json.load(fh)
    sections: list[Section] = []
    for s in raw["sections"]:
        subs = tuple(Subsection(id=x["id"], title=_title_case(x["title"])) for x in s["subsections"])
        sections.append(
            Section(
                id=s["id"],
                number=int(s["number"]),
                title=s["title"],
                subsections=subs,
                object_summary=s.get("object_summary", ""),
                generated_view=bool(s.get("generated_view", False)),
                collections=_SECTION_COLLECTIONS.get(int(s["number"]), ()),
            )
        )
    sections.sort(key=lambda x: x.number)
    return tuple(sections)


def _title_case(t: str) -> str:
    """The reference file mixes 'Synopsis' and 'phase'; normalise the first letter only."""
    return t[:1].upper() + t[1:] if t else t


OUTLINE: tuple[Section, ...] = _load()


def section_by_id(section_id: str) -> Section:
    for s in OUTLINE:
        if s.id == section_id:
            return s
    raise KeyError(section_id)


def section_for_collection(collection: str) -> Section | None:
    for s in OUTLINE:
        if collection in s.collections:
            return s
    return None
