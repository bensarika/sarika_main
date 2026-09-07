"""The master sheet: every study we know about for an indication, one row each.

Three tiers, merged in this order (later never overrides earlier):

1. **Parsed** seeded records in ``reference/evidence/<indication>/*.json`` — facts
   quoted from pages or cited to a registry.
2. **User** records in ``study_records`` (added through Upload Study → Review).
3. **Registered** inventory entries from ``reference/source_inventory.json`` —
   protocols we hold but have not parsed; they appear with no endpoints so the
   sheet is honest about coverage.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from protocol_studio.db import StudyRecordRow
from protocol_studio.evidence.schema import StudyDocument, StudyRecord
from ps_model.schema import reference_dir

INDICATION_LABELS = {"atopic-dermatitis": "Atopic Dermatitis"}


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _evidence_dir() -> Path:
    return reference_dir() / "evidence"


@lru_cache(maxsize=1)
def seeded() -> tuple[StudyRecord, ...]:
    out: list[StudyRecord] = []
    root = _evidence_dir()
    if root.is_dir():
        for path in sorted(root.glob("*/*.json")):
            with path.open(encoding="utf-8") as fh:
                out.append(StudyRecord.model_validate(json.load(fh)))
    return tuple(out)


@lru_cache(maxsize=1)
def inventory() -> tuple[StudyRecord, ...]:
    """Retrieved-but-unparsed protocols from the toolkit inventory, as thin records."""
    with (reference_dir() / "source_inventory.json").open(encoding="utf-8") as fh:
        inv = json.load(fh)
    out: list[StudyRecord] = []
    for p in inv.get("retrieved_protocols", []):
        ident = str(p.get("protocol_identifier", "")).split("/")[0].strip()
        out.append(
            StudyRecord(
                id=slug(f"{p['intervention']}-{ident or p['study_id']}"),
                indication="atopic-dermatitis",
                title=f"{str(p['intervention']).capitalize()} {p.get('phase_scope', '')} · {ident}".strip(),
                intervention=str(p["intervention"]),
                phase=str(p.get("phase_scope", "")).replace("phase ", ""),
                registry_ids=[str(p["study_id"])],
                protocol_identifier=str(p.get("protocol_identifier", "")),
                documents=[
                    StudyDocument(
                        source_id=str(p["source_id"]),
                        kind="protocol",
                        title=f"Protocol {p.get('protocol_version_label', '')}".strip(),
                        version_label=str(p.get("protocol_version_label", "")),
                        date=str(p.get("date", {}).get("value", "")),
                        url=str(p.get("document_url", "")),
                        sha256=str(p.get("sha256", "")),
                        bytes=int(p.get("bytes", 0) or 0),
                        pages=p.get("physical_pdf_pages"),
                    )
                ],
                review_scope=(
                    f"Retrieved; toolkit review scope: {p.get('review_scope', '')} "
                    f"(sections {', '.join(p.get('selected_sections_reviewed', []))}). Not yet parsed into endpoints."
                ),
                notes=str(p.get("limitations_or_identity_notes", "")),
            )
        )
    return tuple(out)


def all_records(db: Session, indication: str | None = None) -> list[StudyRecord]:
    seen: dict[str, StudyRecord] = {}
    for r in seeded():
        seen[r.id] = r
    for row in db.scalars(select(StudyRecordRow)).all():
        if row.id not in seen:
            seen[row.id] = StudyRecord.model_validate(row.canonical)
    for r in inventory():
        seen.setdefault(r.id, r)
    recs = list(seen.values())
    if indication:
        recs = [r for r in recs if r.indication == indication]
    return sorted(recs, key=lambda r: (r.synthetic, r.intervention.lower(), r.phase, r.id))


def find(db: Session, study_id: str) -> StudyRecord | None:
    return next((r for r in all_records(db) if r.id == study_id), None)


def tier(db: Session, rec: StudyRecord) -> str:
    if rec in seeded():
        return "parsed"
    if db.get(StudyRecordRow, rec.id) is not None:
        return "user"
    return "registered"


def row(db: Session, rec: StudyRecord) -> dict[str, Any]:
    """One master-sheet row: Study | Primary endpoint | Timepoint | Source."""
    p = rec.primary()
    doc = rec.documents[0] if rec.documents else None
    return {
        "id": rec.id,
        "title": rec.title,
        "intervention": rec.intervention,
        "mechanism": rec.mechanism,
        "phase": rec.phase,
        "protocol_identifier": rec.protocol_identifier,
        "registry_ids": rec.registry_ids,
        "primary_endpoint": p.label if p else None,
        "primary_transformation": p.transformation if p else None,
        "primary_instrument": p.instrument if p else None,
        "timepoint": f"Week {p.timepoint_weeks:g}" if p and p.timepoint_weeks is not None else None,
        "provenance_status": p.provenance.status if p else None,
        "source": {"kind": doc.kind, "title": doc.title, "url": doc.url} if doc else None,
        "documents": len(rec.documents),
        "endpoints": len(rec.endpoints),
        "criteria": len(rec.criteria),
        "results": len(rec.results),
        "synthetic": rec.synthetic,
        "tier": tier(db, rec),
        "review_scope": rec.review_scope,
    }


def endpoint_matrix(recs: list[StudyRecord]) -> dict[str, Any]:
    """Which instruments × transformations each study measured — the 'what endpoints they measured' view."""
    columns: list[str] = []
    cells: dict[str, dict[str, list[str]]] = {}
    for r in recs:
        cells[r.id] = {}
        for e in r.endpoints:
            key = f"{e.instrument or '?'} · {e.transformation}"
            if key not in columns:
                columns.append(key)
            cells[r.id].setdefault(key, []).append(e.role)
    return {"columns": sorted(columns), "cells": cells}


def indication_summary(db: Session) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for ind in sorted({r.indication for r in all_records(db)}):
        recs = all_records(db, ind)
        parsed = [r for r in recs if r.endpoints and not r.synthetic]
        out.append(
            {
                "id": ind,
                "label": INDICATION_LABELS.get(ind, ind.replace("-", " ").title()),
                "studies": len([r for r in recs if not r.synthetic]),
                "parsed": len(parsed),
                "registered": len([r for r in recs if not r.endpoints and not r.synthetic]),
                "synthetic": len([r for r in recs if r.synthetic]),
                "with_results": len([r for r in recs if r.results and not r.synthetic]),
                "interventions": sorted({r.intervention for r in recs if not r.synthetic}),
            }
        )
    return out
