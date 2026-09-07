"""Evaluate a draft: findings + completion + formal-review readiness.

Readiness (docs/01_architecture.md §6.5) is a predicate, not a percentage:

    ready  <=>  no ERROR findings
            and no CANDIDATE finding left un-adjudicated
            and every "not applicable" declaration has a reason
            and completion.pct == 100 for every applicable section

Findings computed at revision N are stamped with N; the API refuses to
adjudicate a finding whose key was computed at an older revision than the
head, which is how stale results are rejected.
"""

from __future__ import annotations

from typing import Any

from protocol_studio.engine.state import DraftState
from ps_model.completion import completion_for_model, overall_completion
from ps_rules import Finding, Severity, run_rules


def evaluate(state: DraftState, adjudications: dict[str, str] | None = None) -> dict[str, Any]:
    adj = adjudications or {}
    findings: list[Finding] = run_rules(
        state.model,
        revision=state.revision,
        claims=state.all_claims(),
        narrative=state.narrative_states(),
        not_applicable=state.not_applicable,
    )
    sections = completion_for_model(
        state.model, narrative=state.narrative_states(), not_applicable=state.not_applicable
    )
    overall = overall_completion(sections)

    out_findings: list[dict[str, Any]] = []
    for f in findings:
        d = f.as_dict()
        d["adjudication"] = adj.get(f.key)
        out_findings.append(d)

    errors = [f for f in findings if f.severity == Severity.ERROR]
    open_candidates = [f for f in findings if f.severity == Severity.CANDIDATE and adj.get(f.key) is None]
    blockers: list[str] = []
    if errors:
        blockers.append(f"{len(errors)} error finding(s) must be resolved")
    if open_candidates:
        blockers.append(f"{len(open_candidates)} candidate finding(s) need a decision")
    incomplete = [s for s in sections if s.section_id != "section.1" and s.pct < 100]
    if incomplete:
        blockers.append(f"{len(incomplete)} section(s) below 100% complete")
    for slot_id, reason in state.not_applicable.items():
        if not reason.strip():
            blockers.append(f"{slot_id} is marked not applicable without a reason")

    counts = {str(sev): 0 for sev in Severity}
    for f in findings:
        counts[str(f.severity)] += 1

    return {
        "revision": state.revision,
        "findings": out_findings,
        "counts": counts,
        "completion": {"overall": overall, "sections": [s.as_dict() for s in sections]},
        "readiness": {"ready": not blockers, "blockers": blockers},
    }
