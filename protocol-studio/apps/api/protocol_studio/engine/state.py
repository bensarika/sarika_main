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


class Block(BaseModel):
    id: str
    section_id: str
    subsection_id: str
    order: int = 0
    kind: str = "paragraph"  # paragraph | bullets
    text: str = ""
    provenance: str = "author"  # author | generated | proposed | imported
    approval: str = "unreviewed"  # unreviewed | approved | rejected
    claims: list[Claim] = Field(default_factory=list)
    updated_by: str = ""
    updated_at: str = ""


class DraftState(BaseModel):
    model: dict[str, Any]
    blocks: list[Block] = Field(default_factory=list)
    not_applicable: dict[str, str] = Field(default_factory=dict)
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
