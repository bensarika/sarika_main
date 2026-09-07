"""Library of starters: things a new work can be seeded from.

Pilot 1 ships two kinds:

* ``blank``                 an empty authored draft (protocol id/name/indication only)
* ``example:<protocol id>`` the models in ``reference/protocol_examples.json``
                            (a synthetic AD example and partial extractions of
                            two lebrikizumab protocols)

Pilot 2 adds ``study:<source id>`` (ingested PDFs → canonical JSON) and
``template:<id>`` (saved conversion templates). Starter ids are opaque to the
API; ``starter_state`` is the only place that interprets them.
"""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

from protocol_studio.engine.state import Block, DraftState
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
            "id": "blank",
            "title": "Blank protocol",
            "kind": "blank",
            "indication": "",
            "description": "Empty trial model; you fill every slot.",
        }
    ]
    for pid, m in _examples().items():
        p = m["protocol"]
        out.append(
            {
                "id": f"example:{pid}",
                "title": p.get("name", pid),
                "kind": m.get("document_kind", "example"),
                "indication": p.get("indication", ""),
                "description": f"{m.get('document_kind', '').replace('_', ' ')} · {len(m.get('endpoints') or [])} endpoints · {len(m.get('criteria') or [])} criteria",
                "protocol_id": pid,
            }
        )
    return out


def starter_state(starter: str, *, protocol_id: str, title: str, indication: str) -> DraftState:
    if starter == "blank":
        return DraftState(model=empty_model(protocol_id=protocol_id, name=title, indication=indication))
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
        # Provenance of extraction runs is kept for Pilot 2; drop review scaffolding the editor does not own.
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
