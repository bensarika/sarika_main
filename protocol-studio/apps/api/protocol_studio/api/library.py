"""Library and reference endpoints (read-only).

GET /api/library/starters        what a new work can be seeded from
GET /api/reference/outline       the 15-entry canonical outline
GET /api/reference/rules         the R01–R22 catalogue (for the Findings inspector's help text)
GET /api/reference/schema        the trial-model JSON Schema (for form generation in the editor)
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from protocol_studio.auth.session import current_user
from protocol_studio.library import list_starters
from ps_model.outline import OUTLINE
from ps_model.schema import load_schema
from ps_rules import catalogue
from ps_rules.registry import registered_rule_ids

router = APIRouter(tags=["library"], dependencies=[Depends(current_user)])


@router.get("/api/library/starters")
def starters() -> list[dict[str, Any]]:
    return list_starters()


@router.get("/api/reference/outline")
def outline() -> list[dict[str, Any]]:
    return [
        {
            "id": s.id,
            "number": s.number,
            "title": s.title,
            "generated": s.generated_view,
            "collections": list(s.collections),
            "object_summary": s.object_summary,
            "subsections": [{"id": x.id, "title": x.title} for x in s.subsections],
        }
        for s in OUTLINE
    ]


@router.get("/api/reference/rules")
def rules() -> list[dict[str, Any]]:
    implemented = set(registered_rule_ids())
    return [
        {
            "id": r.id,
            "status": "implemented" if r.id in implemented else "planned",
            "name": r.name,
            "check_type": r.check_type,
            "default_result": r.default_result,
            "check": r.check,
            "inline": r.inline,
        }
        for r in catalogue().values()
    ]


@router.get("/api/reference/schema")
def schema() -> dict[str, Any]:
    return load_schema()
