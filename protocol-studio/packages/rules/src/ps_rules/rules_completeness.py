"""Conditional-completeness rules: R02, R12, R15, R17, R18 (+ generic slots).

These rules do not invent their own requirements: they read the shared slot
map (``ps_model.slots``) so the "% complete" number and the "incomplete"
findings always agree. Each unfilled, applicable slot that names a rule id
becomes one ``incomplete`` finding under that rule; unfilled slots without a
rule id are surfaced by the completion panel alone (they are "not yet
written", not a defect).
"""

from __future__ import annotations

from typing import Any

from ps_model.completion import completion_for_model
from ps_rules.finding import Finding, Severity
from ps_rules.registry import RuleContext, rule

_SLOT_RULES = ("R02", "R12", "R15", "R17", "R18")


def _incomplete_for(rule_id: str, model: dict[str, Any], ctx: RuleContext) -> list[Finding]:
    out: list[Finding] = []
    for sec in completion_for_model(model, narrative=ctx.narrative, not_applicable=ctx.not_applicable):
        for slot in sec.remaining:
            if slot.rule_id == rule_id:
                out.append(
                    Finding(
                        rule_id,
                        Severity.INCOMPLETE,
                        f"Missing: {slot.label}",
                        targets=[slot.target_path or slot.id],
                        section_id=sec.section_id,
                        data={"slot_id": slot.id},
                    )
                )
    return out


@rule("R02")
def endpoint_definition(model: dict[str, Any], ctx: RuleContext) -> list[Finding]:
    return _incomplete_for("R02", model, ctx)


@rule("R12")
def estimand_completeness(model: dict[str, Any], ctx: RuleContext) -> list[Finding]:
    return _incomplete_for("R12", model, ctx)


@rule("R15")
def framework_specific_inputs(model: dict[str, Any], ctx: RuleContext) -> list[Finding]:
    return _incomplete_for("R15", model, ctx)


@rule("R17")
def safety_instruction_completeness(model: dict[str, Any], ctx: RuleContext) -> list[Finding]:
    return _incomplete_for("R17", model, ctx)


@rule("R18")
def discontinuation_and_follow_up(model: dict[str, Any], ctx: RuleContext) -> list[Finding]:
    return _incomplete_for("R18", model, ctx)
