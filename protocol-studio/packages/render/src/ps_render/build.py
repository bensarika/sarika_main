"""Build the Render AST from the model, the editor blocks and version metadata.

For each of the 15 outline entries we emit the heading, then per subsection:

1. the *generated view* for that subsection if the model can produce one
   (synopsis, objectives/endpoints table, design summary, criteria list,
   products & regimens, schedule of activities, analysis tables);
2. the authored blocks (paragraphs / bullet lists) in order, annotated when
   they carry unbound or mismatched claims;
3. a *Note* when a subsection has neither, so a reviewer sees the gap in the
   PDF instead of silently missing text.

This module knows nothing about LaTeX or DOCX.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from ps_model.outline import OUTLINE, Section
from ps_render.ast import Block, BulletList, Document, Heading, Note, Paragraph, Table


@dataclass(frozen=True)
class RenderMeta:
    version_label: str  # "v0.3 (frozen 2026-09-07)" or "Working draft, revision 42"
    generated_at: str  # ISO date
    engine_version: str = "ps-render 0.1.0"
    watermark: str | None = None  # "DRAFT" for working copies


# ----------------------------------------------------------------------------- helpers


def _s(v: Any, default: str = "—") -> str:
    if v is None or v == "" or v == []:
        return default
    if isinstance(v, list):
        return ", ".join(_s(x) for x in v)
    if isinstance(v, dict):
        if "value" in v and "unit" in v:
            return f"{v['value']} {v['unit']}"
        if "value" in v:
            return str(v["value"])
        if "kind" in v and v.get("kind") == "literal":
            return _s(v.get("value"))
        if "text" in v:
            return str(v["text"])
    return str(v)


def _items(model: dict[str, Any], coll: str) -> list[dict[str, Any]]:
    return [x for x in (model.get(coll) or []) if isinstance(x, dict)]


def _by_id(model: dict[str, Any], coll: str) -> dict[str, dict[str, Any]]:
    return {x["id"]: x for x in _items(model, coll) if "id" in x}


def _name(model: dict[str, Any], coll: str, eid: str | None) -> str:
    if not eid:
        return "—"
    ent = _by_id(model, coll).get(eid)
    return ent.get("name", eid) if ent else f"{eid} (missing)"


def _time(model: dict[str, Any], t: dict[str, Any] | None) -> str:
    if not t:
        return "—"
    anchor = _name(model, "anchors", t.get("anchor_id"))
    off = t.get("offset")
    return f"{_s(off)} after {anchor}" if off else anchor


# ----------------------------------------------------------------------------- generated views


def _synopsis(model: dict[str, Any]) -> Iterable[Block]:
    p = model.get("protocol") or {}
    rows: list[tuple[str, str]] = [
        ("Title", _s(p.get("name"))),
        ("Sponsor", _s(p.get("sponsor"))),
        ("Phase", _s(p.get("phase"))),
        ("Indication", _s(p.get("indication"))),
        ("Intent", _s(p.get("intent"))),
        ("Planned enrolment", _s(p.get("planned_enrollment"))),
    ]
    prim = [o for o in _items(model, "objectives") if o.get("role") == "primary"]
    rows.append(("Primary objective(s)", _s([o.get("name") for o in prim])))
    prim_ep = [e for e in _items(model, "endpoints") if any(e["id"] in (o.get("endpoint_ids") or []) for o in prim)]
    rows.append(("Primary endpoint(s)", _s([f"{e.get('name')} at {_time(model, e.get('time'))}" for e in prim_ep])))
    rows.append(("Design", _s([f"{x.get('name')}" for x in _items(model, "paths")])))
    yield Table("Protocol synopsis (generated from the trial model)", ("Item", "Value"), tuple(rows))


def _objectives(model: dict[str, Any]) -> Iterable[Block]:
    objs = _items(model, "objectives")
    if not objs:
        return
    rows = []
    for o in objs:
        eps = [_name(model, "endpoints", e) for e in o.get("endpoint_ids") or []]
        rows.append((_s(o.get("role")).title(), _s(o.get("name")), _s(o.get("clinical_question")), _s(eps)))
    yield Table(
        "Objectives and linked endpoints", ("Role", "Objective", "Clinical question", "Endpoint(s)"), tuple(rows)
    )


def _endpoints(model: dict[str, Any]) -> Iterable[Block]:
    eps = _items(model, "endpoints")
    if not eps:
        return
    rows = []
    for e in eps:
        rows.append(
            (
                _s(e.get("name")),
                _s([_name(model, "assessments", a) for a in e.get("assessment_ids") or []]),
                _s(e.get("variable_type")),
                _s(e.get("transformation")),
                _time(model, e.get("time")),
            )
        )
    yield Table("Endpoint definitions", ("Endpoint", "Assessment", "Type", "Transformation", "Timepoint"), tuple(rows))
    ests = _items(model, "estimands")
    if ests:
        rows2 = []
        for s in ests:
            ies = (
                "; ".join(
                    f"{_name(model, 'events', x.get('event_id'))}: {x.get('strategy', '—')}"
                    for x in s.get("intercurrent_event_strategies") or []
                )
                or "—"
            )
            rows2.append(
                (
                    _s(s.get("role")).title(),
                    _s(s.get("name")),
                    _name(model, "populations", s.get("population_id")),
                    _name(model, "endpoints", s.get("endpoint_id")),
                    _s(s.get("contrast")),
                    ies,
                )
            )
        yield Table(
            "Estimands (ICH E9(R1) attributes)",
            ("Role", "Estimand", "Population", "Variable", "Summary measure", "Intercurrent events"),
            tuple(rows2),
        )


def _design(model: dict[str, Any]) -> Iterable[Block]:
    periods = _items(model, "periods")
    if periods:
        yield Table(
            "Trial periods",
            ("Period", "Kind", "Duration"),
            tuple((_s(p.get("name")), _s(p.get("kind")), _s(p.get("duration"))) for p in periods),
        )
    paths = _items(model, "paths")
    if paths:
        yield Table(
            "Participant paths",
            ("Path", "Regimen(s)", "Periods"),
            tuple(
                (
                    _s(p.get("name")),
                    _s(
                        [
                            _name(model, "regimens", ra.get("regimen_id"))
                            for ra in p.get("regimen_assignments") or []
                            if isinstance(ra, dict)
                        ]
                    ),
                    _s([_name(model, "periods", x) for x in p.get("period_ids") or []]),
                )
                for p in paths
            ),
        )
    for a in _items(model, "allocations"):
        choices = a.get("choices") or []
        yield Table(
            f"Allocation: {_s(a.get('name'))} ({_s(a.get('method'))})",
            ("Path", "Ratio"),
            tuple(
                (_name(model, "paths", c.get("path_id")), _s(c.get("weight"))) for c in choices if isinstance(c, dict)
            ),
        )


def _criteria(model: dict[str, Any]) -> Iterable[Block]:
    crit = _items(model, "criteria")
    for kind, title in (("inclusion", "Inclusion criteria"), ("exclusion", "Exclusion criteria")):
        items = [c for c in crit if c.get("type") == kind]
        if items:
            yield Paragraph(f"**{title}**", annotation="generated")
            yield BulletList(tuple(_s(c.get("name")) for c in items))


def _products(model: dict[str, Any]) -> Iterable[Block]:
    prods = _items(model, "products")
    if prods:
        yield Table(
            "Trial products",
            ("Product", "Role", "Substance", "Formulation", "Route"),
            tuple(
                (
                    _s(p.get("name")),
                    _s(p.get("role")),
                    _s(p.get("substance")),
                    _s(p.get("formulation")),
                    _s(p.get("route")),
                )
                for p in prods
            ),
        )
    regs = _items(model, "regimens")
    if regs:
        rows = []
        for r in regs:
            for adm in r.get("administrations") or []:
                rep = f"every {_s(adm.get('repeat_every'))}" if adm.get("repeat_every") else "once"
                rows.append(
                    (
                        _s(r.get("name")),
                        _name(model, "products", r.get("product_id")),
                        _s(adm.get("dose")),
                        _s(adm.get("route")),
                        _time(model, adm.get("time")),
                        rep,
                    )
                )
        yield Table("Dosing regimens", ("Regimen", "Product", "Dose", "Route", "Start", "Repeat"), tuple(rows))


def _soa(model: dict[str, Any]) -> Iterable[Block]:
    """Schedule of activities: rows = assessments, columns = encounters."""
    encs = _items(model, "encounters")
    acts = _items(model, "scheduled_activities")
    if not encs or not acts:
        return
    assess = _by_id(model, "assessments")
    enc_ids = [e["id"] for e in encs]
    header = ("Assessment", *[_s(e.get("name")) for e in encs])
    grid: dict[str, set[str]] = {}
    for a in acts:
        grid.setdefault(a.get("assessment_id", "?"), set()).add(a.get("encounter_id", ""))
    rows = tuple(
        (assess.get(aid, {}).get("name", aid), *["X" if eid in encset else "" for eid in enc_ids])
        for aid, encset in grid.items()
    )
    foot = tuple(f"{_s(e.get('name'))}: {_time(model, e.get('time'))}" for e in encs)
    yield Table("Schedule of activities (generated)", header, rows, footnotes=foot)


def _analysis(model: dict[str, Any]) -> Iterable[Block]:
    sets = _items(model, "analysis_sets")
    if sets:
        yield Table(
            "Analysis sets", ("Set", "Definition"), tuple((_s(s.get("name")), _s(s.get("definition"))) for s in sets)
        )
    an = _items(model, "analyses")
    if an:
        yield Table(
            "Planned analyses",
            ("Role", "Analysis", "Estimand", "Analysis set", "Method", "Missing data"),
            tuple(
                (
                    _s(a.get("role")).title(),
                    _s(a.get("name")),
                    _name(model, "estimands", a.get("estimand_id")),
                    _name(model, "analysis_sets", a.get("analysis_set_id")),
                    _s(a.get("method")),
                    _s(a.get("missing_measurement_handling")),
                )
                for a in an
            ),
        )
    for t in _items(model, "testing_families"):
        yield Paragraph(
            f"**Testing family {_s(t.get('name'))}** — framework {_s(t.get('framework'))}, alpha {_s(t.get('alpha'))}, {_s(t.get('sidedness'))}-sided.",
            annotation="generated",
        )


# Which generator feeds which subsection. Everything else is authored prose.
_GENERATED: dict[str, Any] = {
    "section.1.1": _synopsis,
    "section.3.1": _objectives,
    "section.3.2": _endpoints,
    "section.4.1": _design,
    "section.5.2": _criteria,
    "section.6.1": _products,
    "section.8.1": _soa,
    "section.10.1": _analysis,
}


# ----------------------------------------------------------------------------- authored blocks


def _authored(blocks: list[dict[str, Any]], sub_id: str) -> Iterable[Block]:
    mine = sorted((b for b in blocks if b.get("subsection_id") == sub_id), key=lambda b: b.get("order", 0))
    for b in mine:
        if b.get("approval") == "rejected":
            continue
        text = (b.get("text") or "").strip()
        if not text:
            continue
        states = {c.get("state") for c in b.get("claims") or []}
        ann = "mismatch" if "mismatch" in states else ("unbound" if states & {"unbound", "unsupported"} else None)
        if b.get("kind") == "bullets":
            yield BulletList(tuple(line.lstrip("-• ").strip() for line in text.splitlines() if line.strip()))
        else:
            for para in [p for p in text.split("\n\n") if p.strip()]:
                yield Paragraph(para.strip(), block_id=b.get("id"), annotation=ann)


# ----------------------------------------------------------------------------- entry point


def build_ast(model: dict[str, Any], blocks: list[dict[str, Any]], meta: RenderMeta) -> Document:
    p = model.get("protocol") or {}
    ids: list[tuple[str, str]] = [("Protocol identifier", _s(p.get("id")))]
    for si in p.get("study_identifiers") or []:
        if isinstance(si, dict):
            ids.append((_s(si.get("system", "Identifier")), _s(si.get("value"))))
    ids += [
        ("Version", meta.version_label),
        ("Sponsor", _s(p.get("sponsor"))),
        ("Indication", _s(p.get("indication"))),
        ("Phase", _s(p.get("phase"))),
    ]
    doc = Document(
        title=_s(p.get("name"), "Untitled protocol"),
        subtitle="Clinical Trial Protocol",
        identifiers=tuple(ids),
        footer=f"{meta.version_label} · rendered {meta.generated_at} · {meta.engine_version}",
    )

    for sec in OUTLINE:
        doc.blocks.append(Heading(1, str(sec.number), sec.title, sec.id))
        if not sec.subsections:
            doc.blocks.extend(_subsection_body(model, blocks, sec, sec.id))
        for sub in sec.subsections:
            num = sub.id.removeprefix("section.")
            doc.blocks.append(Heading(2, num, sub.title, sub.id))
            doc.blocks.extend(_subsection_body(model, blocks, sec, sub.id))
    return doc


def _subsection_body(model: dict[str, Any], blocks: list[dict[str, Any]], sec: Section, sub_id: str) -> list[Block]:
    out: list[Block] = []
    gen = _GENERATED.get(sub_id)
    if gen:
        out.extend(gen(model))
    out.extend(_authored(blocks, sub_id))
    if not out:
        out.append(
            Note(
                "Not yet written."
                if not sec.generated_view
                else "Generated view: complete the trial model to populate.",
                kind="warning",
            )
        )
    return out
