"""Rule registry and runner.

A rule is a plain function ``(model, ctx) -> list[Finding]`` registered with
``@rule("R01")``. Registration is validated against the catalogue. ``run_rules``
runs every inline rule (or a subset) and stamps the revision on each finding.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from ps_model.refs import EntityIndex, index_entities
from ps_rules.catalogue import catalogue
from ps_rules.finding import Finding

# Claim-check rules live outside the toolkit catalogue but follow the same shape.
_EXTRA_RULES: dict[str, str] = {
    "CL01": "Narrative claim contradicts the model",
    "CL02": "Narrative claim has no model target",
}


@dataclass
class RuleContext:
    """Inputs beyond the model that a rule may consult."""

    revision: int
    index: EntityIndex
    claims: list[dict[str, Any]] = field(default_factory=list)  # from the draft
    narrative: Mapping[str, Any] = field(default_factory=dict)  # subsection id -> NarrativeState
    not_applicable: Mapping[str, str] = field(default_factory=dict)  # slot id -> reason


RuleFn = Callable[[dict[str, Any], RuleContext], list[Finding]]
_REGISTRY: dict[str, RuleFn] = {}


def rule(rule_id: str) -> Callable[[RuleFn], RuleFn]:
    if rule_id not in catalogue() and rule_id not in _EXTRA_RULES:
        raise KeyError(f"{rule_id} is not in reference/validation_rules.json")

    def deco(fn: RuleFn) -> RuleFn:
        if rule_id in _REGISTRY:
            raise KeyError(f"{rule_id} registered twice")
        _REGISTRY[rule_id] = fn
        return fn

    return deco


def registered_rule_ids() -> list[str]:
    return sorted(_REGISTRY)


def run_rules(
    model: dict[str, Any],
    *,
    revision: int,
    claims: list[dict[str, Any]] | None = None,
    narrative: Mapping[str, Any] | None = None,
    not_applicable: Mapping[str, str] | None = None,
    only: Iterable[str] | None = None,
) -> list[Finding]:
    # Import implementations lazily so registering is a side effect of use, not of import order.
    from ps_rules import rules_claims, rules_completeness, rules_deterministic  # noqa: F401

    ctx = RuleContext(
        revision=revision,
        index=index_entities(model),
        claims=list(claims or []),
        narrative=narrative or {},
        not_applicable=not_applicable or {},
    )
    ids = sorted(set(only) if only else set(_REGISTRY))
    findings: list[Finding] = []
    for rid in ids:
        fn = _REGISTRY.get(rid)
        if fn is None:
            continue
        for f in fn(model, ctx):
            f.revision = revision
            findings.append(f)
    return findings
