"""DraftState: everything mutable about a work, as one JSON-serialisable object.

    model            the trial model (validated against reference/protocol_model.schema.json)
    blocks           authored narrative blocks, each bound to a subsection
    not_applicable   slot id -> reason, declared by the author, reviewed later
    revision         monotonic; every accepted command increments it

Blocks carry their own claims (text -> model path bindings) so a block moves
with its evidence. Block shape::

    {"id": "b-3f9a", "section_id": "section.3", "subsection_id": "section.3.2",
     "order": 2, "kind": "paragraph" | "bullets", "text": "...",
     "provenance": "author" | "generated" | "proposed" | "imported",
     "approval": "unreviewed" | "approved" | "rejected",
     "claims": [{"id": "c1", "path": "endpoints[easi75].time.offset.value",
                 "value": 16, "text": "Week 16", "state": "checked"}],
     "updated_by": "ben@sarika.com", "updated_at": "2026-09-07T00:00:00Z"}
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from ps_model.completion import NarrativeState


class Claim(BaseModel):
    id: str
    path: str
    value: Any = None
    text: str = ""
    state: str = "unbound"  # checked | mismatch | unbound | unsupported | stale
    model_value: Any = None


class Proposal(BaseModel):
    """A pending replacement for a block's text. The original stays live until accepted."""

    text: str
    origin: str = "author"  # author | ai | suggestion
    instruction: str = ""  # what the author asked for (AI) or the suggester's note
    factual_changes: list[dict[str, Any]] = Field(default_factory=list)  # deterministic checks, see engine/textcheck
    proposed_by: str = ""
    proposed_at: str = ""


class Block(BaseModel):
    id: str
    section_id: str
    subsection_id: str
    order: int = 0
    kind: str = "paragraph"  # paragraph | bullets | heading | table
    text: str = ""
    provenance: str = "author"  # author | generated | proposed | imported
    approval: str = "unreviewed"  # unreviewed | approved | rejected
    claims: list[Claim] = Field(default_factory=list)
    proposal: Proposal | None = None
    updated_by: str = ""
    updated_at: str = ""


class DrugSpec(BaseModel):
    name: str
    mechanism: str = ""
    role: str = "investigational"  # investigational | comparator
    ib_source_id: str | None = None


class AdaptationChange(BaseModel):
    """One proposed edit produced by adapting a starter to the target drug(s)."""

    id: str
    kind: str  # block | model
    category: str  # retain | rewrite | remove | add | evidence
    section_id: str
    subsection_id: str = ""
    block_id: str | None = None
    path: str | None = None  # model path for kind == "model"
    source_text: str
    proposed_text: str
    proposed_value: Any = None
    clinical_question: str = ""
    evidence_needed: list[str] = Field(default_factory=list)
    requirement_ids: list[str] = Field(default_factory=list)
    drug_names: list[str] = Field(default_factory=list)
    decision: str = "pending"  # pending | accepted | rejected
    decided_by: str = ""


class EvidenceRequirement(BaseModel):
    id: str
    label: str
    drug_name: str
    kind: str = "investigator_brochure"  # investigator_brochure | nonclinical | clinical | label | other
    status: str = "open"  # open | linked | waived
    source_id: str | None = None
    note: str = ""


class Adaptation(BaseModel):
    source_drug: str
    source_mechanism: str = ""
    target_drugs: list[DrugSpec] = Field(default_factory=list)
    changes: list[AdaptationChange] = Field(default_factory=list)
    requirements: list[EvidenceRequirement] = Field(default_factory=list)
    started_by: str = ""
    started_at: str = ""

    def change(self, change_id: str) -> AdaptationChange:
        for c in self.changes:
            if c.id == change_id:
                return c
        raise KeyError(change_id)

    def requirement(self, req_id: str) -> EvidenceRequirement:
        for r in self.requirements:
            if r.id == req_id:
                return r
        raise KeyError(req_id)


class KeyInputAnswer(BaseModel):
    question_id: str
    value: Any
    answered_by: str = ""
    answered_at: str = ""


class DraftState(BaseModel):
    model: dict[str, Any]
    blocks: list[Block] = Field(default_factory=list)
    not_applicable: dict[str, str] = Field(default_factory=dict)
    adaptation: Adaptation | None = None
    key_inputs: dict[str, KeyInputAnswer] = Field(default_factory=dict)
    revision: int = 0

    # ---- derived views used by rules/completion -----------------------------------
    def narrative_states(self) -> dict[str, NarrativeState]:
        out: dict[str, NarrativeState] = {}
        for b in self.blocks:
            if not b.text.strip() or b.approval == "rejected" or b.provenance == "proposed":
                continue
            prev = out.get(b.subsection_id, NarrativeState(False, False))
            out[b.subsection_id] = NarrativeState(True, prev.approved or b.approval == "approved")
        return out

    def all_claims(self) -> list[dict[str, Any]]:
        return [{**c.model_dump(), "block_id": b.id} for b in self.blocks for c in b.claims]

    def block(self, block_id: str) -> Block:
        for b in self.blocks:
            if b.id == block_id:
                return b
        raise KeyError(block_id)
