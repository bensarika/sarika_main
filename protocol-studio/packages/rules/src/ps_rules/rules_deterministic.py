"""Deterministic rules: R01, R03, R07, R09, R10, R16.

Each function is pure. Messages are written for the author ("Endpoint
'EASI-75' points at assessment 'easi2' which does not exist"), not for the
developer; the target path lets the UI jump to the offending field.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from ps_model.outline import section_for_collection
from ps_model.refs import iter_references
from ps_rules.catalogue import expression_contract
from ps_rules.finding import Finding, Severity
from ps_rules.registry import RuleContext, rule


def _section(path: str) -> str | None:
    coll = path.split(".")[0].split("[")[0]
    sec = section_for_collection(coll)
    return sec.id if sec else None


def _items(model: dict[str, Any], coll: str) -> list[dict[str, Any]]:
    return [x for x in (model.get(coll) or []) if isinstance(x, dict) and "id" in x]


# --------------------------------------------------------------------------- R01
@rule("R01")
def reference_integrity(model: dict[str, Any], ctx: RuleContext) -> list[Finding]:
    out: list[Finding] = []
    for coll, eid in ctx.index.duplicates:
        out.append(
            Finding(
                "R01",
                Severity.ERROR,
                f"Duplicate id '{eid}' in {coll}",
                targets=[f"{coll}[{eid}]"],
                section_id=_section(coll),
                explanation="Ids must be unique within a model; every reference would be ambiguous.",
            )
        )
    for ref in iter_references(model):
        if not ctx.index.exists(ref.target_collection, ref.target_id):
            out.append(
                Finding(
                    "R01",
                    Severity.ERROR,
                    f"'{ref.path}' refers to {ref.target_collection} '{ref.target_id}', which does not exist",
                    targets=[ref.path],
                    section_id=_section(ref.path),
                    explanation="Schema validation does not check foreign keys; a dangling reference "
                    "means a rule, schedule or analysis points at nothing.",
                    suggested_fix=f"Create {ref.target_collection[:-1]} '{ref.target_id}' or re-link the field.",
                )
            )
    return out


# --------------------------------------------------------------------------- R03
def _iter_expressions(node: Any, path: str) -> Iterator[tuple[dict[str, Any], str]]:
    if isinstance(node, dict):
        if node.get("kind") == "call" and "operator" in node:
            yield node, path
        for k, v in node.items():
            yield from _iter_expressions(v, f"{path}.{k}" if path else k)
    elif isinstance(node, list):
        for i, x in enumerate(node):
            key = f"{path}[{x['id']}]" if isinstance(x, dict) and "id" in x else f"{path}.{i}"
            yield from _iter_expressions(x, key)


def _arity_ok(spec: Any, n: int) -> bool:
    if isinstance(spec, int):
        return n == spec
    if isinstance(spec, str) and spec.endswith("+"):
        return n >= int(spec[:-1])
    return True


@rule("R03")
def expression_arithmetic(model: dict[str, Any], ctx: RuleContext) -> list[Finding]:
    arity = expression_contract().get("arity", {})
    assert isinstance(arity, dict)
    out: list[Finding] = []
    for expr, path in _iter_expressions(model, ""):
        op = expr.get("operator")
        args = expr.get("arguments") or []
        spec = arity.get(op)
        if spec is not None and not _arity_ok(spec, len(args)):
            out.append(
                Finding(
                    "R03",
                    Severity.ERROR,
                    f"Operator '{op}' at '{path}' has {len(args)} argument(s); expects {spec}",
                    targets=[path],
                    section_id=_section(path),
                    explanation="Undefined arithmetic must not silently produce a response value.",
                )
            )
        if op == "divide" and len(args) == 2 and args[1].get("kind") == "literal" and args[1].get("value") == 0:
            out.append(
                Finding(
                    "R03",
                    Severity.ERROR,
                    f"Division by literal zero at '{path}'",
                    targets=[path],
                    section_id=_section(path),
                )
            )
    return out


# --------------------------------------------------------------------------- R07
@rule("R07")
def dose_calendar(model: dict[str, Any], ctx: RuleContext) -> list[Finding]:
    out: list[Finding] = []
    for r in _items(model, "regimens"):
        rid = r["id"]
        for adm in r.get("administrations") or []:
            aid = adm.get("id", "?")
            base = f"regimens[{rid}].administrations[{aid}]"
            rep_every, rep_until, rep_count = adm.get("repeat_every"), adm.get("repeat_until"), adm.get("repeat_count")
            if rep_every and not (rep_until or rep_count):
                out.append(
                    Finding(
                        "R07",
                        Severity.ERROR,
                        f"Administration '{aid}' of regimen '{r.get('name', rid)}' repeats every "
                        f"{rep_every.get('value')} {rep_every.get('unit')} but has no end (repeat_until / repeat_count)",
                        targets=[base],
                        section_id="section.6",
                        explanation="An open-ended repeat cannot be placed on the dosing calendar.",
                    )
                )
            if rep_until and rep_count:
                out.append(
                    Finding(
                        "R07",
                        Severity.WARNING,
                        f"Administration '{aid}' declares both repeat_until and repeat_count",
                        targets=[base],
                        section_id="section.6",
                    )
                )
            dose = adm.get("dose")
            if (
                dose
                and dose.get("kind") == "literal"
                and isinstance(dose.get("value"), int | float)
                and dose["value"] < 0
            ):
                out.append(
                    Finding(
                        "R07",
                        Severity.ERROR,
                        f"Negative dose in administration '{aid}'",
                        targets=[f"{base}.dose"],
                        section_id="section.6",
                    )
                )
    return out


# --------------------------------------------------------------------------- R09
@rule("R09")
def participant_transition_coverage(model: dict[str, Any], ctx: RuleContext) -> list[Finding]:
    """Every path must be able to end: a transition out of it, or a terminal transition."""
    out: list[Finding] = []
    transitions = _items(model, "transitions")
    if not transitions:
        return out  # nothing modelled yet — completeness, not conflict
    for p in _items(model, "paths"):
        pid = p["id"]
        exits = [
            t
            for t in transitions
            if t.get("from_path_id") == pid or (t.get("from_period_id") in (p.get("period_ids") or []))
        ]
        if not exits:
            out.append(
                Finding(
                    "R09",
                    Severity.CANDIDATE,
                    f"Path '{p.get('name', pid)}' has no transition out of it (no discontinuation, completion or escape route)",
                    targets=[f"paths[{pid}]"],
                    section_id="section.4",
                    needs_adjudication=True,
                    explanation="Participants on this path have no modelled way to leave the trial.",
                )
            )
    return out


# --------------------------------------------------------------------------- R10
def _iter_time_refs(node: Any, path: str) -> Iterator[tuple[dict[str, Any], str]]:
    if isinstance(node, dict):
        if "anchor_id" in node and (
            "offset" in node or "window" in node or path.endswith(".time") or path.endswith(".start")
        ):
            yield node, path
        for k, v in node.items():
            yield from _iter_time_refs(v, f"{path}.{k}" if path else k)
    elif isinstance(node, list):
        for i, x in enumerate(node):
            key = f"{path}[{x['id']}]" if isinstance(x, dict) and "id" in x else f"{path}.{i}"
            yield from _iter_time_refs(x, key)


@rule("R10")
def time_anchor_and_boundary(model: dict[str, Any], ctx: RuleContext) -> list[Finding]:
    out: list[Finding] = []
    for tr, path in _iter_time_refs(model, ""):
        off = tr.get("offset")
        if off is not None and (not isinstance(off, dict) or "unit" not in off):
            out.append(
                Finding(
                    "R10",
                    Severity.ERROR,
                    f"Time offset at '{path}' has no unit",
                    targets=[path],
                    section_id=_section(path),
                )
            )
        win = tr.get("window")
        if isinstance(win, dict):
            lo, hi = win.get("earlier"), win.get("later")
            if _negative_window(lo, hi):
                out.append(
                    Finding(
                        "R10",
                        Severity.ERROR,
                        f"Visit window at '{path}' has a negative width",
                        targets=[path],
                        section_id=_section(path),
                    )
                )
    return out


def _negative_window(lo: Any, hi: Any) -> bool:
    """Both window bounds are magnitudes (“3 days earlier / 3 days later”); a negative bound is a modelling error."""
    if not (isinstance(lo, dict) and isinstance(hi, dict)):
        return False
    lv, hv = lo.get("value"), hi.get("value")
    return isinstance(lv, int | float) and isinstance(hv, int | float) and (lv < 0 or hv < 0)


# --------------------------------------------------------------------------- R16
def _has_cycle(hyps: dict[str, Any]) -> str | None:
    """Return the id of a hypothesis on a circular prerequisite chain, or None (iterative DFS)."""
    WHITE, GREY, BLACK = 0, 1, 2  # noqa: N806 - conventional DFS colour names
    colour: dict[str, int] = dict.fromkeys(hyps, WHITE)
    for root in hyps:
        if colour[root] != WHITE:
            continue
        stack: list[tuple[str, Iterator[str]]] = [(root, iter(hyps[root].get("prerequisite_ids") or []))]
        colour[root] = GREY
        while stack:
            node, children = stack[-1]
            nxt = next((c for c in children if c in hyps), None)
            if nxt is None:
                colour[node] = BLACK
                stack.pop()
            elif colour[nxt] == GREY:
                return nxt
            elif colour[nxt] == WHITE:
                colour[nxt] = GREY
                stack.append((nxt, iter(hyps[nxt].get("prerequisite_ids") or [])))
    return None


@rule("R16")
def testing_dependency_graph(model: dict[str, Any], ctx: RuleContext) -> list[Finding]:
    out: list[Finding] = []
    for fam in _items(model, "testing_families"):
        fid = fam["id"]
        hyps: dict[str, Any] = {
            str(h["id"]): h for h in fam.get("hypotheses") or [] if isinstance(h, dict) and h.get("id")
        }
        # prerequisites must exist within the family
        for hid, h in hyps.items():
            for pre in h.get("prerequisite_ids") or []:
                if pre not in hyps:
                    out.append(
                        Finding(
                            "R16",
                            Severity.ERROR,
                            f"Hypothesis '{hid}' in family '{fam.get('name', fid)}' requires unknown hypothesis '{pre}'",
                            targets=[f"testing_families[{fid}].hypotheses[{hid}]"],
                            section_id="section.10",
                        )
                    )
            if h.get("analysis_id") and not ctx.index.exists("analyses", h["analysis_id"]):
                out.append(
                    Finding(
                        "R16",
                        Severity.ERROR,
                        f"Hypothesis '{hid}' points at analysis '{h['analysis_id']}', which does not exist",
                        targets=[f"testing_families[{fid}].hypotheses[{hid}].analysis_id"],
                        section_id="section.10",
                    )
                )
        cyc = _has_cycle(hyps)
        if cyc is not None:
            out.append(
                Finding(
                    "R16",
                    Severity.ERROR,
                    f"Testing family '{fam.get('name', fid)}' has a circular prerequisite chain involving '{cyc}'",
                    targets=[f"testing_families[{fid}]"],
                    section_id="section.10",
                )
            )
        if fam.get("framework") == "frequentist" and fam.get("alpha") is not None:
            a = fam["alpha"]
            if not (isinstance(a, int | float) and 0 < a < 1):
                out.append(
                    Finding(
                        "R16",
                        Severity.ERROR,
                        f"Alpha {a!r} in family '{fam.get('name', fid)}' is not in (0, 1)",
                        targets=[f"testing_families[{fid}].alpha"],
                        section_id="section.10",
                    )
                )
    return out
