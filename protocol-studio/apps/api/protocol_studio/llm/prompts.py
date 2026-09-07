"""Prompt builders. Deterministic, so tests can pin exactly what would leave the box.

Only the selected block (plus the model facts its claims bind to) is sent for a
revision; a question sends the section's approved narrative. Nothing else from
the document, and never other works.
"""

from __future__ import annotations

import json
from typing import Any

from protocol_studio.engine.state import Block, DraftState
from ps_model.paths import get_path

SYSTEM_REVISE = (
    "You are a medical writer revising one paragraph of a clinical trial protocol that follows the "
    "ICH M11 structure. Rewrite the paragraph according to the instruction. Preserve every factual "
    "value (numbers, units, timepoints, treatment names, populations) exactly as given in FACTS unless "
    "the instruction explicitly asks to change it. Do not add claims that are not in the paragraph or "
    "FACTS. Return only the revised paragraph text, no preamble, no markdown."
)

SYSTEM_ASK = (
    "You are a clinical development expert answering a question about one section of a draft clinical "
    "trial protocol (ICH M11 structure, ICH E9(R1) estimand framework). Answer concisely and concretely, "
    "grounded in the CONTEXT given; say so when the context does not settle the question. Your answer is "
    "advisory: it is not a regulatory determination."
)


def facts_for(block: Block, model: dict[str, Any]) -> dict[str, Any]:
    return {c.path: get_path(model, c.path, c.value) for c in block.claims}


def revise_user(block: Block, model: dict[str, Any], instruction: str) -> str:
    facts = facts_for(block, model)
    return (
        f"INSTRUCTION:\n{instruction.strip()}\n\n"
        f"FACTS (model values the paragraph must agree with):\n{json.dumps(facts, indent=2, default=str)}\n\n"
        f"PARAGRAPH:\n{block.text.strip()}"
    )


def ask_user(state: DraftState, section_id: str, question: str) -> str:
    ctx = "\n\n".join(
        b.text.strip()
        for b in state.blocks
        if (not section_id or b.section_id == section_id) and b.text.strip() and b.approval != "rejected"
    )
    return f"QUESTION:\n{question.strip()}\n\nCONTEXT ({section_id or 'whole draft'}):\n{ctx[:12000]}"
