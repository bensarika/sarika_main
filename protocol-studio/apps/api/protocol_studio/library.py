"""Library of starters: things a new study can be seeded from.

Starter ids are opaque to the API; ``starter_state`` is the only place that
interprets them:

* ``blank``                   an empty authored draft (protocol id/name/indication only)
* ``template:<id>``           a reviewed, complete synthetic template shipped with the app
                              (``protocol_studio.starters``); narrative arrives *unreviewed*
                              so a new study never inherits approvals
* ``example:<protocol id>``   the models in ``reference/protocol_examples.json``
                              (partial extractions; useful for endpoint wording)
* ``source:<source id>``      a canonical study record produced by ingestion (Evidence)

Every starter carries the metadata the Starter Library screen shows:
therapeutic area, source version, review state and whether an adaptation
template is cached (so the next author skips the question round-trip).
"""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

from protocol_studio.engine.state import Block, DraftState, refresh_claims
from protocol_studio.starters import AD_ANTIBODY_ID, ad_antibody_blocks, ad_antibody_model
from ps_model.schema import empty_model, reference_dir

_SEED_BLOCKS: list[dict[str, str]] = [
    {
        "subsection_id": "section.2.1",
        "text": "Atopic dermatitis (AD) is a chronic, relapsing inflammatory skin disease characterised by pruritus and eczematous lesions. Moderate-to-severe disease substantially impairs sleep and quality of life, and a proportion of patients respond inadequately to topical therapy.",
    },
    {
        "subsection_id": "section.2.3",
        "text": "The investigational product is hypothesised to reduce type-2 inflammation. The primary objective is to compare the proportion of participants achieving EASI-75 at Week 16 versus placebo.",
    },
]


@lru_cache(maxsize=1)
def _examples() -> dict[str, dict[str, Any]]:
    with (reference_dir() / "protocol_examples.json").open(encoding="utf-8") as fh:
        raw = json.load(fh)
    return {m["protocol"]["id"]: m for m in raw["models"]}


def list_starters() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = [
        {
            "id": AD_ANTIBODY_ID,
            "title": "Anti-IL-13 antibody, Phase 2b, 16-week placebo-controlled",
            "kind": "template",
            "therapeutic_area": "Dermatology",
            "indication": "atopic dermatitis",
            "source_drug": "ADX-101 (synthetic)",
            "source_version": "Template v1 · reviewed",
            "reviewed": True,
            "cached_adaptation": True,
            "sections": 14,
            "description": "Complete synthetic design: three arms, EASI-75 composite primary estimand, rescue rules, SoA, SAP fields. Illustrative values only.",
        },
        {
            "id": "blank",
            "title": "Blank protocol",
            "kind": "blank",
            "therapeutic_area": "Any",
            "indication": "",
            "source_drug": "",
            "source_version": "",
            "reviewed": False,
            "cached_adaptation": False,
            "sections": 14,
            "description": "Empty trial model; you fill every slot.",
        },
    ]
    for pid, m in _examples().items():
        p = m["protocol"]
        out.append(
            {
                "id": f"example:{pid}",
                "title": p.get("name", pid),
                "kind": m.get("document_kind", "example"),
                "therapeutic_area": "Dermatology",
                "indication": p.get("indication", ""),
                "source_drug": "",
                "source_version": p.get("version_label", ""),
                "reviewed": False,
                "cached_adaptation": False,
                "sections": 14,
                "description": f"{m.get('document_kind', '').replace('_', ' ')} · {len(m.get('endpoints') or [])} endpoints · {len(m.get('criteria') or [])} criteria",
                "protocol_id": pid,
            }
        )
    return out


def starter_state(starter: str, *, protocol_id: str, title: str, indication: str) -> DraftState:
    if starter == "blank":
        return DraftState(model=empty_model(protocol_id=protocol_id, name=title, indication=indication))
    if starter == AD_ANTIBODY_ID:
        model = ad_antibody_model(protocol_id=protocol_id, name=title, indication=indication)
        blocks = ad_antibody_blocks()
        for b in blocks:
            b.approval = "unreviewed"  # approvals belong to a study, never to a template
        st = DraftState(model=model, blocks=blocks)
        refresh_claims(st)
        return st
    if starter.startswith("example:"):
        src = _examples().get(starter.removeprefix("example:"))
        if src is None:
            raise KeyError(starter)
        model = json.loads(json.dumps(src))  # deep copy; the library is read-only
        model["document_kind"] = "authored_draft"
        model["protocol"]["id"] = protocol_id
        model["protocol"]["name"] = title
        model["protocol"]["indication"] = indication or model["protocol"].get("indication", "")
        model["protocol"].setdefault("version_label", "0.1")
        # Provenance of extraction runs is kept for ingestion; drop review scaffolding the editor does not own.
        for k in ("collection_status", "unresolved"):
            model.pop(k, None)
        blocks = [
            Block(
                id=f"b-seed{i}",
                section_id=".".join(b["subsection_id"].split(".")[:2]),
                subsection_id=b["subsection_id"],
                order=0,
                text=b["text"],
                provenance="imported",
                approval="unreviewed",
            )
            for i, b in enumerate(_SEED_BLOCKS)
        ]
        return DraftState(model=model, blocks=blocks)
    raise KeyError(starter)
