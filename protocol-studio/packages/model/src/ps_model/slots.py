"""Required-slot map.

A *slot* is one thing a section needs before it can be considered complete:
either a model field (``protocol.phase``), a collection-level requirement
("at least one primary objective") or, for every entity in a collection, a
per-entity field ("every endpoint has a time reference"). Narrative sections
have *narrative slots*: one per subsection, satisfied by an approved block.

Slots are the denominator of completion (docs/01_architecture.md §6.5) and
the source of ``incomplete`` findings for conditional-completeness rules
(R02, R12, R15, R17). Keeping them in one table means the percentage and the
findings can never disagree about what is required.

Conditional slots carry an ``applies_when`` predicate; when it is false the
slot leaves the denominator instead of counting as unfilled.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

from ps_model.paths import get_path

Predicate = Callable[[dict[str, Any]], bool]
EntityPredicate = Callable[[dict[str, Any], dict[str, Any]], bool]


@dataclass(frozen=True)
class Slot:
    """A concrete requirement evaluated against one model."""

    id: str  # stable id, e.g. "s3.endpoints[easi75].time" or "s0.protocol.phase"
    section_id: str
    label: str  # human wording shown in "what remains"
    kind: str  # "field" | "collection" | "entity_field" | "narrative"
    filled: bool
    target_path: str | None = None  # dotted model path the UI should focus
    rule_id: str | None = None  # which catalogue rule owns the finding, if any


def _present(v: Any) -> bool:
    if v is None:
        return False
    if isinstance(v, str):
        return v.strip() != ""
    if isinstance(v, list | dict):
        return len(v) > 0
    return True


def _field(model: dict[str, Any], path: str) -> bool:
    return _present(get_path(model, path, None))


def _items(model: dict[str, Any], coll: str) -> list[dict[str, Any]]:
    return [x for x in (model.get(coll) or []) if isinstance(x, dict)]


def _has(model: dict[str, Any], coll: str, pred: Predicate | None = None) -> bool:
    return any(pred(x) if pred else True for x in _items(model, coll))


# ---------------------------------------------------------------------------
# Slot generators, one per section. Each yields Slot objects for a given model.
# ---------------------------------------------------------------------------


def _s0(model: dict[str, Any]) -> Iterator[Slot]:
    for f, label in [
        ("name", "Protocol title"),
        ("version_label", "Version label"),
        ("phase", "Trial phase"),
        ("indication", "Indication"),
        ("sponsor", "Sponsor"),
        ("intent", "Trial intent (exploratory / confirmatory)"),
    ]:
        yield Slot(f"s0.protocol.{f}", "section.0", label, "field", _field(model, f"protocol.{f}"), f"protocol.{f}")
    yield Slot(
        "s0.protocol.study_identifiers",
        "section.0",
        "At least one study identifier (sponsor code, NCT, EudraCT…)",
        "field",
        _field(model, "protocol.study_identifiers"),
        "protocol.study_identifiers",
    )
    yield Slot("s0.roles", "section.0", "Responsible roles defined", "collection", _has(model, "roles"), "roles")


def _s3(model: dict[str, Any]) -> Iterator[Slot]:
    yield Slot(
        "s3.objectives.primary",
        "section.3",
        "At least one primary objective",
        "collection",
        _has(model, "objectives", lambda o: o.get("role") == "primary"),
        "objectives",
    )
    for o in _items(model, "objectives"):
        oid = o["id"]
        yield Slot(
            f"s3.objectives[{oid}].clinical_question",
            "section.3",
            f"Objective “{o.get('name', oid)}”: clinical question",
            "entity_field",
            _present(o.get("clinical_question")),
            f"objectives[{oid}].clinical_question",
        )
        yield Slot(
            f"s3.objectives[{oid}].endpoint_ids",
            "section.3",
            f"Objective “{o.get('name', oid)}”: linked endpoint(s)",
            "entity_field",
            _present(o.get("endpoint_ids")),
            f"objectives[{oid}].endpoint_ids",
        )
    for e in _items(model, "endpoints"):
        eid = e["id"]
        nm = e.get("name", eid)
        base = f"endpoints[{eid}]"
        yield Slot(
            f"s3.{base}.assessment_ids",
            "section.3",
            f"Endpoint “{nm}”: measurement (assessment)",
            "entity_field",
            _present(e.get("assessment_ids")),
            f"{base}.assessment_ids",
            "R02",
        )
        yield Slot(
            f"s3.{base}.variable_type",
            "section.3",
            f"Endpoint “{nm}”: variable type",
            "entity_field",
            _present(e.get("variable_type")),
            f"{base}.variable_type",
            "R02",
        )
        yield Slot(
            f"s3.{base}.transformation",
            "section.3",
            f"Endpoint “{nm}”: transformation",
            "entity_field",
            _present(e.get("transformation")),
            f"{base}.transformation",
            "R02",
        )
        yield Slot(
            f"s3.{base}.time",
            "section.3",
            f"Endpoint “{nm}”: time reference (anchor + offset)",
            "entity_field",
            _present((e.get("time") or {}).get("anchor_id")),
            f"{base}.time",
            "R02",
        )
        # Change-from-baseline endpoints need a baseline definition; responders need a predicate.
        if e.get("transformation") in {"absolute_change", "percent_change", "percent_reduction"}:
            yield Slot(
                f"s3.{base}.baseline_definition",
                "section.3",
                f"Endpoint “{nm}”: baseline definition",
                "entity_field",
                _present(e.get("baseline_definition")),
                f"{base}.baseline_definition",
                "R02",
            )
        if e.get("transformation") == "responder" or e.get("variable_type") == "binary":
            yield Slot(
                f"s3.{base}.response_predicate",
                "section.3",
                f"Endpoint “{nm}”: responder rule",
                "entity_field",
                _present(e.get("response_predicate")),
                f"{base}.response_predicate",
                "R02",
            )
        yield Slot(
            f"s3.{base}.aggregation",
            "section.3",
            f"Endpoint “{nm}”: aggregation (e.g. proportion, mean change)",
            "entity_field",
            _present(e.get("aggregation")),
            f"{base}.aggregation",
            "R02",
        )
    yield Slot(
        "s3.estimands.primary",
        "section.3",
        "At least one primary estimand",
        "collection",
        _has(model, "estimands", lambda x: x.get("role") == "primary"),
        "estimands",
        "R12",
    )
    for s in _items(model, "estimands"):
        sid = s["id"]
        nm = s.get("name", sid)
        base = f"estimands[{sid}]"
        for f, label in [
            ("population_id", "population"),
            ("endpoint_id", "endpoint (variable)"),
            ("treatment_conditions", "treatment conditions"),
            ("contrast", "population-level summary / contrast"),
        ]:
            yield Slot(
                f"s3.{base}.{f}",
                "section.3",
                f"Estimand “{nm}”: {label}",
                "entity_field",
                _present(s.get(f)),
                f"{base}.{f}",
                "R12",
            )
        ies_ok = _present(s.get("intercurrent_event_strategies")) or _present(
            s.get("no_relevant_intercurrent_events_rationale")
        )
        yield Slot(
            f"s3.{base}.intercurrent_event_strategies",
            "section.3",
            f"Estimand “{nm}”: intercurrent-event strategies (or rationale for none)",
            "entity_field",
            ies_ok,
            f"{base}.intercurrent_event_strategies",
            "R12",
        )


def _s4(model: dict[str, Any]) -> Iterator[Slot]:
    yield Slot(
        "s4.periods",
        "section.4",
        "Trial periods (screening, treatment, follow-up…)",
        "collection",
        _has(model, "periods"),
        "periods",
    )
    yield Slot("s4.paths", "section.4", "Participant paths (arms)", "collection", _has(model, "paths"), "paths")
    yield Slot(
        "s4.allocations",
        "section.4",
        "Allocation (randomisation) defined",
        "collection",
        _has(model, "allocations"),
        "allocations",
    )
    for a in _items(model, "allocations"):
        aid = a["id"]
        yield Slot(
            f"s4.allocations[{aid}].method",
            "section.4",
            f"Allocation “{a.get('name', aid)}”: method",
            "entity_field",
            _present(a.get("method")),
            f"allocations[{aid}].method",
        )
        yield Slot(
            f"s4.allocations[{aid}].choices",
            "section.4",
            f"Allocation “{a.get('name', aid)}”: choices / ratio",
            "entity_field",
            _present(a.get("choices")),
            f"allocations[{aid}].choices",
        )
    for p in _items(model, "periods"):
        pid = p["id"]
        yield Slot(
            f"s4.periods[{pid}].duration",
            "section.4",
            f"Period “{p.get('name', pid)}”: duration",
            "entity_field",
            _present(p.get("duration")),
            f"periods[{pid}].duration",
            "R10",
        )


def _s5(model: dict[str, Any]) -> Iterator[Slot]:
    yield Slot(
        "s5.populations", "section.5", "Target population", "collection", _has(model, "populations"), "populations"
    )
    yield Slot(
        "s5.criteria.inclusion",
        "section.5",
        "At least one inclusion criterion",
        "collection",
        _has(model, "criteria", lambda c: c.get("type") == "inclusion"),
        "criteria",
    )
    yield Slot(
        "s5.criteria.exclusion",
        "section.5",
        "At least one exclusion criterion",
        "collection",
        _has(model, "criteria", lambda c: c.get("type") == "exclusion"),
        "criteria",
    )
    for c in _items(model, "criteria"):
        cid = c["id"]
        yield Slot(
            f"s5.criteria[{cid}].type",
            "section.5",
            f"Criterion “{c.get('name', cid)}”: type",
            "entity_field",
            _present(c.get("type")),
            f"criteria[{cid}].type",
        )


def _s6(model: dict[str, Any]) -> Iterator[Slot]:
    yield Slot(
        "s6.products.investigational",
        "section.6",
        "Investigational product",
        "collection",
        _has(model, "products", lambda p: p.get("role") == "investigational"),
        "products",
    )
    yield Slot("s6.regimens", "section.6", "Dosing regimen(s)", "collection", _has(model, "regimens"), "regimens")
    for p in _items(model, "products"):
        pid = p["id"]
        for f in ("substance", "formulation", "route"):
            yield Slot(
                f"s6.products[{pid}].{f}",
                "section.6",
                f"Product “{p.get('name', pid)}”: {f}",
                "entity_field",
                _present(p.get(f)),
                f"products[{pid}].{f}",
            )
    for r in _items(model, "regimens"):
        rid = r["id"]
        yield Slot(
            f"s6.regimens[{rid}].product_id",
            "section.6",
            f"Regimen “{r.get('name', rid)}”: product",
            "entity_field",
            _present(r.get("product_id")),
            f"regimens[{rid}].product_id",
            "R07",
        )
        yield Slot(
            f"s6.regimens[{rid}].administrations",
            "section.6",
            f"Regimen “{r.get('name', rid)}”: administrations (dose, route, timing)",
            "entity_field",
            _present(r.get("administrations")),
            f"regimens[{rid}].administrations",
            "R07",
        )


def _s7(model: dict[str, Any]) -> Iterator[Slot]:
    yield Slot(
        "s7.rules.discontinuation",
        "section.7",
        "Treatment discontinuation rule",
        "collection",
        _has(model, "rules", lambda r: r.get("domain") in {"treatment", "follow_up"}),
        "rules",
        "R18",
    )
    yield Slot(
        "s7.events.discontinuation",
        "section.7",
        "Discontinuation / withdrawal events defined",
        "collection",
        _has(
            model,
            "events",
            lambda e: e.get("kind") in {"treatment_discontinuation", "study_withdrawal", "treatment_interruption"},
        ),
        "events",
        "R18",
    )


def _s8(model: dict[str, Any]) -> Iterator[Slot]:
    yield Slot(
        "s8.assessments", "section.8", "Assessments defined", "collection", _has(model, "assessments"), "assessments"
    )
    yield Slot(
        "s8.encounters",
        "section.8",
        "Visits / encounters defined",
        "collection",
        _has(model, "encounters"),
        "encounters",
    )
    yield Slot(
        "s8.scheduled_activities",
        "section.8",
        "Schedule of activities populated",
        "collection",
        _has(model, "scheduled_activities"),
        "scheduled_activities",
        "R04",
    )
    for a in _items(model, "assessments"):
        aid = a["id"]
        yield Slot(
            f"s8.assessments[{aid}].kind",
            "section.8",
            f"Assessment “{a.get('name', aid)}”: kind",
            "entity_field",
            _present(a.get("kind")),
            f"assessments[{aid}].kind",
        )
    for e in _items(model, "encounters"):
        eid = e["id"]
        yield Slot(
            f"s8.encounters[{eid}].time",
            "section.8",
            f"Encounter “{e.get('name', eid)}”: time reference",
            "entity_field",
            _present((e.get("time") or {}).get("anchor_id")),
            f"encounters[{eid}].time",
            "R10",
        )


def _s9(model: dict[str, Any]) -> Iterator[Slot]:
    yield Slot(
        "s9.events.adverse_event",
        "section.9",
        "Adverse-event definitions",
        "collection",
        _has(model, "events", lambda e: e.get("kind") == "adverse_event"),
        "events",
        "R17",
    )
    yield Slot(
        "s9.rules.safety",
        "section.9",
        "Safety reporting rule(s)",
        "collection",
        _has(model, "rules", lambda r: r.get("domain") == "safety"),
        "rules",
        "R17",
    )


def _s10(model: dict[str, Any]) -> Iterator[Slot]:
    yield Slot(
        "s10.analysis_sets", "section.10", "Analysis sets", "collection", _has(model, "analysis_sets"), "analysis_sets"
    )
    yield Slot(
        "s10.analyses.primary",
        "section.10",
        "Primary analysis",
        "collection",
        _has(model, "analyses", lambda a: a.get("role") == "primary"),
        "analyses",
    )
    yield Slot(
        "s10.protocol.sample_size",
        "section.10",
        "Sample-size rationale",
        "field",
        _field(model, "protocol.sample_size.calculation"),
        "protocol.sample_size",
    )
    yield Slot(
        "s10.protocol.planned_enrollment",
        "section.10",
        "Planned enrolment",
        "field",
        _field(model, "protocol.planned_enrollment"),
        "protocol.planned_enrollment",
    )
    for s in _items(model, "analysis_sets"):
        sid = s["id"]
        yield Slot(
            f"s10.analysis_sets[{sid}].definition",
            "section.10",
            f"Analysis set “{s.get('name', sid)}”: definition",
            "entity_field",
            _present(s.get("definition")),
            f"analysis_sets[{sid}].definition",
        )
    for a in _items(model, "analyses"):
        aid = a["id"]
        nm = a.get("name", aid)
        for f, label in [
            ("estimand_id", "estimand"),
            ("analysis_set_id", "analysis set"),
            ("method", "method"),
            ("missing_measurement_handling", "missing-data handling"),
        ]:
            yield Slot(
                f"s10.analyses[{aid}].{f}",
                "section.10",
                f"Analysis “{nm}”: {label}",
                "entity_field",
                _present(a.get(f)),
                f"analyses[{aid}].{f}",
                "R15",
            )
    # Frequentist confirmatory trials need a testing family with alpha and sidedness.
    if (model.get("protocol") or {}).get("intent") == "confirmatory":
        yield Slot(
            "s10.testing_families",
            "section.10",
            "Testing family (multiplicity) for confirmatory trial",
            "collection",
            _has(model, "testing_families"),
            "testing_families",
            "R16",
        )
    for t in _items(model, "testing_families"):
        tid = t["id"]
        if t.get("framework") == "frequentist":
            yield Slot(
                f"s10.testing_families[{tid}].alpha",
                "section.10",
                f"Testing family “{t.get('name', tid)}”: alpha",
                "entity_field",
                _present(t.get("alpha")),
                f"testing_families[{tid}].alpha",
                "R15",
            )
            yield Slot(
                f"s10.testing_families[{tid}].sidedness",
                "section.10",
                f"Testing family “{t.get('name', tid)}”: sidedness",
                "entity_field",
                _present(t.get("sidedness")),
                f"testing_families[{tid}].sidedness",
                "R15",
            )


def _s11(model: dict[str, Any]) -> Iterator[Slot]:
    yield Slot(
        "s11.governance",
        "section.11",
        "Governance policies (ethics, monitoring, data)",
        "collection",
        _has(model, "governance"),
        "governance",
    )


_MODEL_SLOT_GENERATORS: dict[str, Callable[[dict[str, Any]], Iterator[Slot]]] = {
    "section.0": _s0,
    "section.3": _s3,
    "section.4": _s4,
    "section.5": _s5,
    "section.6": _s6,
    "section.7": _s7,
    "section.8": _s8,
    "section.9": _s9,
    "section.10": _s10,
    "section.11": _s11,
}

# Subsections whose content is narrative (authored prose) rather than a model
# collection. A narrative slot is filled by an approved block in that subsection.
# Section 1 is generated and has no slots of its own (see completion.py).
NARRATIVE_SUBSECTIONS: dict[str, tuple[str, ...]] = {
    "section.2": (
        "section.2.1",
        "section.2.2",
        "section.2.3",
        "section.2.4",
        "section.2.5",
        "section.2.6",
        "section.2.7",
    ),
    "section.4": ("section.4.7",),
    "section.5": ("section.5.1",),
    "section.6": ("section.6.2",),
    "section.9": ("section.9.1", "section.9.3", "section.9.4", "section.9.5"),
    "section.10": ("section.10.10",),
    "section.11": ("section.11.1", "section.11.2", "section.11.3", "section.11.5", "section.11.8"),
    "section.12": ("section.12.4",),
    "section.13": ("section.13.1",),
    "section.14": ("section.14.1",),
}


def model_slots(model: dict[str, Any], section_id: str) -> list[Slot]:
    gen = _MODEL_SLOT_GENERATORS.get(section_id)
    return list(gen(model)) if gen else []


def narrative_slot_ids(section_id: str) -> tuple[str, ...]:
    return NARRATIVE_SUBSECTIONS.get(section_id, ())
