"""ps_rules: positive/negative fixtures per implemented rule, claim states, revision stamping."""

from __future__ import annotations

import json
from typing import Any

import pytest

from ps_model.schema import empty_model, reference_dir
from ps_rules import Severity, catalogue, run_rules
from ps_rules.registry import registered_rule_ids
from ps_rules.rules_claims import claim_state


@pytest.fixture
def syn() -> dict[str, Any]:
    with (reference_dir() / "protocol_examples.json").open(encoding="utf-8") as fh:
        raw = json.load(fh)
    return json.loads(json.dumps(next(m for m in raw["models"] if m["protocol"]["id"] == "SYN.protocol.v1")))


def _ids(findings: list[Any], rule: str) -> list[Any]:
    return [f for f in findings if f.rule_id == rule]


def test_catalogue_loads_all_22_rules() -> None:
    assert len(catalogue()) == 22
    assert set(registered_rule_ids()) <= set(catalogue()) | {"CL01", "CL02"}


def test_clean_example_has_no_errors(syn: dict[str, Any]) -> None:
    findings = run_rules(syn, revision=7)
    assert not [f for f in findings if f.severity == Severity.ERROR]
    assert all(f.revision == 7 for f in findings)


def test_r01_duplicate_and_dangling(syn: dict[str, Any]) -> None:
    syn["endpoints"].append(dict(syn["endpoints"][0]))  # duplicate id
    syn["objectives"][0]["endpoint_ids"] = ["ghost"]
    f = _ids(run_rules(syn, revision=1, only=["R01"]), "R01")
    msgs = " ".join(x.message for x in f)
    assert "Duplicate" in msgs and "ghost" in msgs
    assert all(x.severity == Severity.ERROR for x in f)


def test_r03_expression_arity_and_zero_division() -> None:
    m = empty_model(protocol_id="W", name="n", indication="AD")
    m["endpoints"] = [
        {
            "id": "e",
            "name": "bad",
            "variable_type": "continuous",
            "expression": {
                "kind": "call",
                "operator": "divide",
                "arguments": [{"kind": "literal", "value": 1}, {"kind": "literal", "value": 0}],
            },
        },
        {
            "id": "f",
            "name": "arity",
            "variable_type": "continuous",
            "expression": {"kind": "call", "operator": "not", "arguments": []},
        },
    ]
    f = _ids(run_rules(m, revision=1, only=["R03"]), "R03")
    assert any("zero" in x.message.lower() for x in f)
    assert any("argument" in x.message.lower() for x in f)


def test_r10_offset_units_and_windows() -> None:
    m = empty_model(protocol_id="W", name="n", indication="AD")
    m["anchors"] = [{"id": "a0", "name": "Baseline"}]
    m["endpoints"] = [
        {
            "id": "e",
            "name": "x",
            "variable_type": "binary",
            "time": {
                "anchor_id": "a0",
                "offset": {"value": 16, "unit": "week"},
                "window": {"earlier": {"value": 3, "unit": "day"}, "later": {"value": -1, "unit": "day"}},
            },
        },
    ]
    f = _ids(run_rules(m, revision=1, only=["R10"]), "R10")
    assert f and "negative" in f[0].message
    m["endpoints"][0]["time"] = {"anchor_id": "a0", "offset": {"value": 16}}
    assert "unit" in _ids(run_rules(m, revision=1, only=["R10"]), "R10")[0].message


def test_r16_cycle_and_alpha() -> None:
    m = empty_model(protocol_id="W", name="n", indication="AD")
    m["testing_families"] = [
        {
            "id": "tf",
            "name": "primary",
            "framework": "frequentist",
            "alpha": 1.5,
            "hypotheses": [
                {"id": "h1", "analysis_id": "a1", "prerequisite_ids": ["h2"]},
                {"id": "h2", "analysis_id": "ghost", "prerequisite_ids": ["h1"]},
            ],
        }
    ]
    m["analyses"] = [{"id": "a1", "name": "a1"}, {"id": "a2", "name": "a2"}]
    f = _ids(run_rules(m, revision=1, only=["R16"]), "R16")
    msgs = " ".join(x.message.lower() for x in f)
    assert "circular" in msgs and "alpha" in msgs and "ghost" in msgs


def test_completeness_rules_are_incomplete_not_error(syn: dict[str, Any]) -> None:
    syn.pop("estimands", None)
    f = _ids(run_rules(syn, revision=1, only=["R12"]), "R12")
    assert f and all(x.severity == Severity.INCOMPLETE for x in f)


def test_not_applicable_suppresses_completeness_finding(syn: dict[str, Any]) -> None:
    syn.pop("estimands", None)
    all_f = _ids(run_rules(syn, revision=1, only=["R12"]), "R12")
    na = {x.data["slot_id"]: "reviewed: not applicable" for x in all_f}
    fewer = _ids(run_rules(syn, revision=1, only=["R12"], not_applicable=na), "R12")
    assert all_f and fewer == []


# ----------------------------------------------------------------------------- claims


def test_claim_states(syn: dict[str, Any]) -> None:
    ok = {"id": "c", "path": "endpoints[easi75].time.offset.value", "value": 16}
    bad = {**ok, "value": 12}
    unbound = {**ok, "path": "endpoints[nope].time.offset.value"}
    unsupported = {**ok, "path": "protocol.sponsor"}
    assert claim_state(syn, ok) == "checked"
    assert claim_state(syn, bad) == "mismatch"
    assert claim_state(syn, unbound) == "unbound"
    assert claim_state(syn, unsupported) == "unsupported"


def test_claim_findings_have_stable_keys(syn: dict[str, Any]) -> None:
    claims = [
        {"id": "c", "path": "endpoints[easi75].time.offset.value", "value": 12, "text": "Week 12", "block_id": "b1"}
    ]
    a = _ids(run_rules(syn, revision=1, claims=claims), "CL01")
    b = _ids(run_rules(syn, revision=2, claims=claims), "CL01")
    assert a and a[0].key == b[0].key and a[0].revision == 1 and b[0].revision == 2
    assert "Update model" in a[0].explanation and "Revert text" in a[0].explanation
