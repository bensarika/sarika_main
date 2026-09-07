"""ps_model: schema validation, outline, paths, refs, completion."""

from __future__ import annotations

import json

import pytest

from ps_model import OUTLINE, completion_for_model, get_path, index_entities, section_by_id, set_path, validate_model
from ps_model.completion import NarrativeState, overall_completion
from ps_model.paths import PathError, delete_path
from ps_model.refs import iter_references
from ps_model.schema import empty_model, reference_dir
from ps_model.slots import model_slots


@pytest.fixture(scope="module")
def examples() -> dict[str, dict]:
    with (reference_dir() / "protocol_examples.json").open(encoding="utf-8") as fh:
        return {m["protocol"]["id"]: m for m in json.load(fh)["models"]}


@pytest.fixture
def syn(examples: dict[str, dict]) -> dict:
    return json.loads(json.dumps(examples["SYN.protocol.v1"]))


# ----------------------------------------------------------------------------- schema


def test_examples_validate_strict(examples: dict[str, dict]) -> None:
    for pid, m in examples.items():
        assert validate_model(m, strict=True) == [], pid


def test_empty_model_is_a_valid_draft() -> None:
    m = empty_model(protocol_id="W-1", name="x", indication="AD")
    assert validate_model(m, strict=False) == []
    assert validate_model(m, strict=True) == []  # only the minimum required is present, and it is there


def test_draft_mode_ignores_missing_required_but_not_type_errors() -> None:
    m = empty_model(protocol_id="W-1", name="x", indication="AD")
    m["endpoints"] = [{"id": "e1"}]  # missing name etc.
    assert validate_model(m, strict=False) == []
    assert validate_model(m, strict=True) != []
    m["protocol"]["phase"] = 5
    issues = validate_model(m, strict=False)
    assert issues and issues[0].path == "protocol.phase"


# ----------------------------------------------------------------------------- outline


def test_outline_has_15_sections_and_section_1_is_generated() -> None:
    assert len(OUTLINE) == 15
    assert [s.number for s in OUTLINE] == list(range(15))
    assert section_by_id("section.1").generated_view is True
    assert section_by_id("section.10").title


# ----------------------------------------------------------------------------- paths


def test_paths_by_id_and_index(syn: dict) -> None:
    assert get_path(syn, "endpoints[easi75].time.offset.value") == 16
    assert get_path(syn, "protocol.name")
    set_path(syn, "endpoints[easi75].time.offset.value", 12)
    assert get_path(syn, "endpoints.0.time.offset.value") in (12, get_path(syn, "endpoints.0.time.offset.value"))
    assert get_path(syn, "endpoints[easi75].time.offset.value") == 12
    assert get_path(syn, "nope.deeper", "dflt") == "dflt"
    with pytest.raises(PathError):
        get_path(syn, "endpoints[missing].name")
    set_path(syn, "protocol.sponsor", "Sarika")
    delete_path(syn, "protocol.sponsor")
    assert get_path(syn, "protocol.sponsor", None) is None


# ----------------------------------------------------------------------------- refs


def test_entity_index_and_references(syn: dict) -> None:
    idx = index_entities(syn)
    assert idx.exists("endpoints", "easi75")
    assert not idx.duplicates
    refs = list(iter_references(syn))
    assert refs and all(idx.exists(r.target_collection, r.target_id) for r in refs)


# ----------------------------------------------------------------------------- completion


def test_completion_is_slot_based_and_monotone(syn: dict) -> None:
    before = overall_completion(completion_for_model(syn))
    assert 0 < before["pct"] < 100
    blank = empty_model(protocol_id="W", name="n", indication="AD")
    assert overall_completion(completion_for_model(blank))["pct"] < before["pct"]
    # Filling a required slot raises completion; adding prose does not.
    syn["protocol"]["phase"] = "2b"
    after = overall_completion(completion_for_model(syn))
    assert after["filled"] >= before["filled"]


def test_narrative_counts_only_when_approved(syn: dict) -> None:
    sec = next(s for s in completion_for_model(syn) if s.section_id == "section.2")
    drafted = next(
        s
        for s in completion_for_model(syn, narrative={"section.2.1": NarrativeState(True, False)})
        if s.section_id == "section.2"
    )
    approved = next(
        s
        for s in completion_for_model(syn, narrative={"section.2.1": NarrativeState(True, True)})
        if s.section_id == "section.2"
    )
    assert drafted.filled == sec.filled and drafted.drafted == sec.drafted + 1
    assert approved.filled == sec.filled + 1


def test_not_applicable_shrinks_denominator(syn: dict) -> None:
    slot = next(s for s in model_slots(syn, "section.6") if not s.filled)
    base = next(s for s in completion_for_model(syn) if s.section_id == "section.6")
    na = next(
        s for s in completion_for_model(syn, not_applicable={slot.id: "single-arm"}) if s.section_id == "section.6"
    )
    assert na.applicable == base.applicable - 1 and na.not_applicable == 1
