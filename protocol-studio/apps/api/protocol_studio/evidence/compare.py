"""Side-by-side comparisons over StudyRecords. Pure functions; the router only picks records.

* ``compare_endpoints``   — the definition of one endpoint role (default: primary) across studies,
                            with explicit *difference flags* (absolute vs percent change, timepoint,
                            instrument, responder threshold). "Absolute change and percent change are
                            different measures" is a flag, not prose the reader has to infer.
* ``compare_eligibility`` — for a chosen criterion category (e.g. ``age``) and the new study's own
                            requirement, every source's wording plus a structured difference
                            (same minimum age / upper limit / regional minimums).
* ``compare_results``     — one endpoint × timepoint across studies and arms, each row carrying its
                            provenance status so synthetic never masquerades as reported; also emits
                            the Trial Lab hand-off (active/control rates) when a placebo arm exists.
"""

from __future__ import annotations

from typing import Any

from protocol_studio.evidence.schema import Criterion, Endpoint, StudyRecord

_TRANSFORMATION_LABEL = {
    "absolute_change": "Absolute change",
    "percent_change": "Percent change",
    "responder": "Responder",
    "score": "Score",
    "time_to_event": "Time to event",
    "other": "Other",
}


def _endpoint_json(rec: StudyRecord, e: Endpoint) -> dict[str, Any]:
    return {
        "study_id": rec.id,
        "study_title": rec.title,
        "version_label": rec.documents[0].version_label if rec.documents else "",
        "endpoint_id": e.id,
        "role": e.role,
        "label": e.label,
        "instrument": e.instrument,
        "transformation": e.transformation,
        "transformation_label": _TRANSFORMATION_LABEL.get(e.transformation, e.transformation),
        "responder_threshold": e.responder_threshold,
        "timepoint_weeks": e.timepoint_weeks,
        "population": e.population,
        "provenance": e.provenance.model_dump(),
    }


def compare_endpoints(recs: list[StudyRecord], role: str = "primary") -> dict[str, Any]:
    cols: list[dict[str, Any]] = []
    for rec in recs:
        eps = [e for e in rec.endpoints if e.role == role]
        if not eps:
            cols.append(
                {"study_id": rec.id, "study_title": rec.title, "missing": True, "review_scope": rec.review_scope}
            )
            continue
        cols += [_endpoint_json(rec, e) for e in eps]
    present = [c for c in cols if not c.get("missing")]
    flags: list[dict[str, str]] = []
    trs = {c["transformation"] for c in present}
    if {"absolute_change", "percent_change"} <= trs:
        flags.append(
            {
                "kind": "transformation",
                "text": "Absolute change and percent change are different measures; effect sizes are not interchangeable.",
            }
        )
    if {"responder"} & trs and trs - {"responder"}:
        flags.append(
            {"kind": "transformation", "text": "Responder and continuous endpoints need different sample-size methods."}
        )
    tps = {c["timepoint_weeks"] for c in present if c["timepoint_weeks"] is not None}
    if len(tps) > 1:
        flags.append(
            {"kind": "timepoint", "text": "Timepoints differ: " + ", ".join(f"Week {t:g}" for t in sorted(tps)) + "."}
        )
    inst = {c["instrument"] for c in present if c["instrument"]}
    if len(inst) > 1:
        flags.append({"kind": "instrument", "text": "Instruments differ: " + ", ".join(sorted(inst)) + "."})
    if any(c["provenance"]["status"] != "quoted" for c in present):
        flags.append(
            {
                "kind": "provenance",
                "text": "At least one definition is not quoted from a document page — confirm before citing.",
            }
        )
    return {"role": role, "columns": cols, "flags": flags}


def _age_difference(ours: Criterion | None, theirs: Criterion) -> dict[str, Any]:
    parts: list[str] = []
    highlight = False
    if ours is not None and ours.min_age is not None and theirs.min_age is not None:
        if ours.min_age == theirs.min_age:
            parts.append("Same minimum age.")
        else:
            parts.append(f"Minimum age {theirs.min_age:g} (ours {ours.min_age:g}).")
            highlight = True
    elif theirs.min_age is not None:
        parts.append(f"Minimum age {theirs.min_age:g}.")
    if theirs.max_age is not None and (ours is None or ours.max_age != theirs.max_age):
        parts.append(f"Upper limit {theirs.max_age:g}.")
        highlight = True
    if theirs.regional_exceptions:
        parts.append("Regional exceptions: " + "; ".join(theirs.regional_exceptions) + ".")
        highlight = True
    return {"text": " ".join(parts) or "Wording differs; no structured difference detected.", "highlight": highlight}


def compare_eligibility(recs: list[StudyRecord], category: str, ours: Criterion | None = None) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for rec in recs:
        for c in rec.criteria:
            if c.category != category:
                continue
            diff = _age_difference(ours, c) if category == "age" else {"text": "Compare wording.", "highlight": False}
            rows.append(
                {
                    "study_id": rec.id,
                    "study_title": rec.title,
                    "version_label": rec.documents[0].version_label if rec.documents else "",
                    "criterion_id": c.id,
                    "kind": c.kind,
                    "text": c.text,
                    "min_age": c.min_age,
                    "max_age": c.max_age,
                    "regional_exceptions": c.regional_exceptions,
                    "provenance": c.provenance.model_dump(),
                    "difference": diff,
                }
            )
    return {
        "category": category,
        "ours": ours.model_dump() if ours else None,
        "rows": rows,
        "note": "Regional exceptions remain part of the source requirement."
        if any(r["regional_exceptions"] for r in rows)
        else "",
    }


def compare_results(
    recs: list[StudyRecord], instrument: str, transformation: str, threshold: str, timepoint_weeks: float
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for rec in recs:
        for e in rec.endpoints:
            if (
                e.instrument != instrument
                or e.transformation != transformation
                or (threshold and e.responder_threshold != threshold)
            ):
                continue
            for r in rec.results:
                if r.endpoint_id != e.id or r.timepoint_weeks != timepoint_weeks:
                    continue
                arm = rec.arm(r.arm_id)
                rows.append(
                    {
                        "study_id": rec.id,
                        "study_title": rec.title,
                        "synthetic": rec.synthetic,
                        "arm_id": r.arm_id,
                        "treatment": arm.label if arm else r.arm_id,
                        "arm_role": arm.role if arm else "other",
                        "value": r.value,
                        "unit": r.unit,
                        "n": r.n,
                        "ci": [r.ci_low, r.ci_high] if r.ci_low is not None else None,
                        "source_status": "Simulation"
                        if r.provenance.status == "synthetic"
                        else r.provenance.status.capitalize(),
                        "provenance": r.provenance.model_dump(),
                        "context": {
                            "background_therapy": rec.background_therapy,
                            "rescue_policy": rec.rescue_policy,
                            "population": rec.population_summary,
                        },
                    }
                )
    handoff = None
    placebo = [r for r in rows if r["arm_role"] == "placebo"]
    actives = [r for r in rows if r["arm_role"] == "investigational"]
    if placebo and actives and transformation == "responder":
        best = max(actives, key=lambda r: float(r["value"]))
        handoff = {
            "p_active": best["value"],
            "p_control": placebo[0]["value"],
            "label": f"{instrument}-{threshold.rstrip('%')} · Week {timepoint_weeks:g}"
            if threshold
            else f"{instrument} · Week {timepoint_weeks:g}",
            "assumption_source": "synthetic" if best["synthetic"] else f"observed:{best['study_id']}",
        }
    return {
        "endpoint": {
            "instrument": instrument,
            "transformation": transformation,
            "threshold": threshold,
            "timepoint_weeks": timepoint_weeks,
        },
        "rows": rows,
        "all_synthetic": bool(rows) and all(r["synthetic"] for r in rows),
        "trial_lab": handoff,
        "caveats": [
            "Same endpoint, timepoint and treatment context are required for a like-for-like comparison.",
            "Background therapy, rescue handling and analysis population differ across studies.",
        ],
    }
