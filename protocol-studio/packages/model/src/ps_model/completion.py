"""Completion = filled required slots / applicable required slots, per section.

Rules (docs/01_architecture.md §6.5):

* slots marked *not applicable* (with a reason) leave the denominator;
* narrative slots count as filled only when the subsection has an **approved**
  block (``drafted`` is reported separately so authors see progress before
  review);
* findings are never blended into the percentage;
* Section 1 (generated views) reports the mean of the sections it is derived
  from (3, 4, 8) because it has no inputs of its own.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from ps_model.outline import OUTLINE
from ps_model.slots import Slot, model_slots, narrative_slot_ids


@dataclass(frozen=True)
class NarrativeState:
    """What the editor knows about a subsection's authored blocks."""

    drafted: bool  # at least one non-empty block whose provenance is not 'proposed'
    approved: bool  # at least one such block with approval == 'approved'


@dataclass
class SectionCompletion:
    section_id: str
    number: int
    title: str
    filled: int
    applicable: int
    drafted: int  # filled OR drafted narrative (progress before approval)
    not_applicable: int
    remaining: list[Slot] = field(default_factory=list)  # unfilled, applicable slots

    @property
    def pct(self) -> int:
        return round(100 * self.filled / self.applicable) if self.applicable else 100

    @property
    def drafted_pct(self) -> int:
        return round(100 * self.drafted / self.applicable) if self.applicable else 100

    def as_dict(self) -> dict[str, Any]:
        return {
            "section_id": self.section_id,
            "number": self.number,
            "title": self.title,
            "pct": self.pct,
            "drafted_pct": self.drafted_pct,
            "filled": self.filled,
            "applicable": self.applicable,
            "not_applicable": self.not_applicable,
            "remaining": [
                {
                    "id": s.id,
                    "label": s.label,
                    "kind": s.kind,
                    "target_path": s.target_path,
                    "rule_id": s.rule_id,
                }
                for s in self.remaining
            ],
        }


def completion_for_model(
    model: dict[str, Any],
    *,
    narrative: Mapping[str, NarrativeState] | None = None,
    not_applicable: Mapping[str, str] | None = None,
) -> list[SectionCompletion]:
    """Compute completion for all 15 sections.

    ``narrative`` maps subsection id → NarrativeState (from the draft's blocks).
    ``not_applicable`` maps slot id → reason (author-declared, reviewed later).
    """
    narrative = narrative or {}
    na = not_applicable or {}
    out: dict[str, SectionCompletion] = {}

    for sec in OUTLINE:
        slots: list[Slot] = model_slots(model, sec.id)
        for sub_id in narrative_slot_ids(sec.id):
            st = narrative.get(sub_id, NarrativeState(False, False))
            slots.append(
                Slot(
                    id=f"narrative:{sub_id}",
                    section_id=sec.id,
                    label=f"Narrative for {_sub_title(sec.id, sub_id)}",
                    kind="narrative",
                    filled=st.approved,
                    target_path=sub_id,
                )
            )
        filled = applicable = drafted = na_count = 0
        remaining: list[Slot] = []
        for s in slots:
            if s.id in na:
                na_count += 1
                continue
            applicable += 1
            if s.filled:
                filled += 1
                drafted += 1
            else:
                if s.kind == "narrative" and narrative.get(s.target_path or "", NarrativeState(False, False)).drafted:
                    drafted += 1
                remaining.append(s)
        out[sec.id] = SectionCompletion(sec.id, sec.number, sec.title, filled, applicable, drafted, na_count, remaining)

    # Section 1 is derived from 3, 4 and 8.
    gen = out["section.1"]
    srcs = [out["section.3"], out["section.4"], out["section.8"]]
    gen.filled = sum(s.filled for s in srcs)
    gen.applicable = sum(s.applicable for s in srcs)
    gen.drafted = sum(s.drafted for s in srcs)
    gen.remaining = []
    return [out[s.id] for s in OUTLINE]


def overall_completion(sections: list[SectionCompletion]) -> dict[str, int]:
    """Whole-protocol number: slot-weighted, excluding the derived Section 1."""
    own = [s for s in sections if s.section_id != "section.1"]
    filled = sum(s.filled for s in own)
    applicable = sum(s.applicable for s in own)
    drafted = sum(s.drafted for s in own)
    return {
        "pct": round(100 * filled / applicable) if applicable else 100,
        "drafted_pct": round(100 * drafted / applicable) if applicable else 100,
        "filled": filled,
        "applicable": applicable,
    }


def _sub_title(section_id: str, sub_id: str) -> str:
    for sec in OUTLINE:
        if sec.id == section_id:
            for sub in sec.subsections:
                if sub.id == sub_id:
                    return f"§{sub_id.removeprefix('section.')} {sub.title}"
    return sub_id
