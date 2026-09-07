"""Starter completeness, adaptation proposals/decisions, key inputs, text proposals, Trial Lab routes."""

from __future__ import annotations

from fastapi.testclient import TestClient

from protocol_studio.engine.adaptation import adaptation_summary, build_adaptation
from protocol_studio.engine.evaluation import evaluate
from protocol_studio.engine.key_inputs import answer, questionnaire
from protocol_studio.engine.state import DraftState, DrugSpec, refresh_claims
from protocol_studio.engine.textcheck import factual_changes
from protocol_studio.library import list_starters, starter_state
from protocol_studio.starters import AD_ANTIBODY_ID
from ps_model.schema import validate_model

TARGET = DrugSpec(name="SRK-201", mechanism="anti-OX40L monoclonal antibody")
SAME_CLASS = DrugSpec(name="SRK-301", mechanism="anti-IL-13 antibody")


def _template() -> DraftState:
    st = starter_state(AD_ANTIBODY_ID, protocol_id="W-1", title="SRK-201 in AD", indication="atopic dermatitis")
    refresh_claims(st)
    return st


# ----------------------------------------------------------------------------- starter


def test_template_is_schema_valid_complete_and_unreviewed() -> None:
    st = _template()
    assert validate_model(st.model, strict=True) == []
    ev = evaluate(st)
    assert ev["counts"] == {"error": 0, "warning": 0, "incomplete": 0, "info": 0, "candidate": 0}
    # model slots are all filled and every narrative slot is drafted, but nothing counts as *complete*
    # until a human approves the prose — so a fresh work is never export-ready on creation.
    overall = ev["completion"]["overall"]
    assert overall["drafted_pct"] == 100 and overall["pct"] < 100
    assert ev["readiness"]["ready"] is False and "below 100%" in ev["readiness"]["blockers"][0]
    assert {b.section_id for b in st.blocks} == {f"section.{i}" for i in range(1, 15)}
    assert all(b.approval == "unreviewed" for b in st.blocks)  # approvals never inherit
    assert all(c.state == "checked" for b in st.blocks for c in b.claims)  # bound prose agrees with model
    meta = next(s for s in list_starters() if s["id"] == AD_ANTIBODY_ID)
    assert meta["source_drug"].startswith("ADX-101") and meta["reviewed"] is True


# ----------------------------------------------------------------------------- adaptation


def test_adaptation_classifies_and_never_edits_until_accepted() -> None:
    st = _template()
    before = {b.id: b.text for b in st.blocks}
    a = build_adaptation(
        st,
        source_drug="ADX-101",
        source_mechanism="anti-IL-13 monoclonal antibody",
        targets=[TARGET],
        actor="t",
        now="n",
    )
    assert {b.id: b.text for b in st.blocks} == before  # proposals only
    cats = {c.category for c in a.changes}
    assert {"rewrite", "evidence", "remove"} <= cats
    # different mechanism → the IL-13 rationale paragraph is proposed for removal, dose statements need evidence
    removes = [c for c in a.changes if c.category == "remove"]
    assert removes and "IL-13" in removes[0].source_text
    assert any(c.category == "evidence" and "mg" in c.source_text for c in a.changes)
    # every rewrite has the target name and no source name left
    for c in a.changes:
        if c.category == "rewrite":
            assert "ADX-101" not in c.proposed_text and "SRK-201" in c.proposed_text
    assert {r.id for r in a.requirements} >= {"req-dose-srk201", "req-mechanism-srk201", "req-clinical_evidence-srk201"}
    assert {r.kind for r in a.requirements} == {"clinical", "nonclinical", "investigator_brochure"}
    assert all(r.status == "open" for r in a.requirements)
    assert adaptation_summary(a)["complete"] is False


def test_same_class_target_retains_mechanism_text() -> None:
    st = _template()
    a = build_adaptation(
        st,
        source_drug="ADX-101",
        source_mechanism="anti-IL-13 monoclonal antibody",
        targets=[SAME_CLASS],
        actor="t",
        now="n",
    )
    # same target pathway: the mechanism paragraph is kept for evidence review rather than proposed for removal
    assert not [c for c in a.changes if c.category == "remove"]
    mech = [c for c in a.changes if "IL-13" in c.source_text and c.kind == "block"]
    assert mech and all(c.category == "evidence" and "SRK-301" in c.proposed_text for c in mech)


def test_second_drug_becomes_add_with_regimen_question() -> None:
    st = _template()
    a = build_adaptation(
        st,
        source_drug="ADX-101",
        source_mechanism="anti-IL-13 monoclonal antibody",
        targets=[TARGET, DrugSpec(name="SRK-202", mechanism="anti-IL-31 antibody")],
        actor="t",
        now="n",
    )
    adds = [c for c in a.changes if c.category == "add"]
    assert len(adds) == 1 and adds[0].path == "products[srk_202]" and "regimen" in adds[0].clinical_question.lower()


def test_adaptation_via_commands(admin: TestClient) -> None:
    r = admin.post(
        "/api/works",
        json={
            "title": "SRK-201 Phase 2b",
            "starter": AD_ANTIBODY_ID,
            "study_code": "SRK-201-201",
            "phase": "2b",
            "drugs": [{"name": "SRK-201", "mechanism": "anti-OX40L monoclonal antibody"}],
            "data_class": "confidential",
        },
    )
    assert r.status_code == 201, r.text
    wid = r.json()["id"]
    assert r.json()["data_class"] == "confidential" and r.json()["drugs"][0]["name"] == "SRK-201"

    r = admin.post(
        f"/api/works/{wid}/commands",
        json={
            "type": "start_adaptation",
            "base_revision": 0,
            "source_drug": "ADX-101",
            "source_mechanism": "anti-IL-13 monoclonal antibody",
            "target_drugs": [TARGET.model_dump()],
        },
    )
    assert r.status_code == 200, r.text
    a = admin.get(f"/api/works/{wid}/adaptation").json()
    assert a["summary"]["pending"] == a["summary"]["total"] > 10
    changes = a["adaptation"]["changes"]
    rewrite = next(c for c in changes if c["category"] == "rewrite" and c["kind"] == "block")
    remove = next(c for c in changes if c["category"] == "remove")
    model_rw = next(c for c in changes if c["kind"] == "model" and c["path"] == "products[adx101].name")

    rev = 1
    for cid, decision in ((rewrite["id"], "accepted"), (remove["id"], "rejected"), (model_rw["id"], "accepted")):
        r = admin.post(
            f"/api/works/{wid}/commands",
            json={"type": "decide_adaptation_change", "base_revision": rev, "change_id": cid, "decision": decision},
        )
        assert r.status_code == 200, r.text
        rev = r.json()["revision"]
    state = admin.get(f"/api/works/{wid}/draft").json()
    blocks = {b["id"]: b for b in state["blocks"]}
    assert blocks[rewrite["block_id"]]["text"] == rewrite["proposed_text"]
    assert blocks[remove["block_id"]]["text"] == remove["source_text"]  # rejected → untouched
    assert next(p for p in state["model"]["products"] if p["id"] == "adx101")["name"] == "SRK-201"
    s = admin.get(f"/api/works/{wid}/adaptation").json()["summary"]
    assert (s["accepted"], s["rejected"]) == (2, 1)

    req = a["adaptation"]["requirements"][0]["id"]
    r = admin.post(
        f"/api/works/{wid}/commands",
        json={
            "type": "set_evidence_requirement",
            "base_revision": rev,
            "requirement_id": req,
            "status": "linked",
            "source_id": "src-ib-1",
        },
    )
    assert r.status_code == 200
    assert (
        admin.get(f"/api/works/{wid}/adaptation").json()["summary"]["open_requirements"]
        == len(a["adaptation"]["requirements"]) - 1
    )

    # status gate: cannot approve while blockers exist
    r = admin.patch(f"/api/works/{wid}", json={"status": "approved"})
    assert r.status_code == 409 and r.json()["detail"]["error"] == "not_ready"
    assert admin.patch(f"/api/works/{wid}", json={"status": "review"}).json()["status"] == "review"
    assert admin.get("/api/works").json()[0]["completion_pct"] > 50


# ----------------------------------------------------------------------------- key inputs


def test_key_inputs_write_through_and_flag_claims() -> None:
    st = _template()
    q = questionnaire(st)
    assert q["pct"] == 100 and {g["name"] for g in q["groups"]} >= {"Design", "Estimand", "Statistics"}
    assert "composite_events" in {x["id"] for g in q["groups"] for x in g["questions"]}  # composite is current
    written, sections = answer(st, "primary_timepoint_weeks", 12, actor="t", now="n")
    assert "periods[treatment].duration.value" in written and len(written) >= 6
    assert "section.10" in sections
    refresh_claims(st)
    ev = evaluate(st)
    assert any("Week 16" in f["message"] for f in ev["findings"])  # bound prose now disagrees
    answer(st, "rescue_strategy", "hypothetical", actor="t", now="n")
    ids = {x["id"] for g in questionnaire(st)["groups"] for x in g["questions"]}
    assert "imputation_assumption" in ids and "composite_events" not in ids
    assert st.model["analyses"][0]["post_event_handling"][0]["action"] == "replace_value"


def test_key_inputs_after_adaptation_need_confirmation() -> None:
    st = _template()
    st.adaptation = build_adaptation(
        st,
        source_drug="ADX-101",
        source_mechanism="anti-IL-13 monoclonal antibody",
        targets=[TARGET],
        actor="t",
        now="n",
    )
    q = questionnaire(st)
    dose = next(x for g in q["groups"] for x in g["questions"] if x["id"] == "dose_high_mg")
    assert dose["source"] == "placeholder" and dose["answered"] is False and q["pct"] < 100
    answer(st, "dose_high_mg", 200, actor="t", now="n")
    assert st.model["regimens"][0]["administrations"][1]["dose"]["value"] == 200
    assert "200 mg" in st.model["regimens"][0]["name"]


def test_key_input_validation() -> None:
    st = _template()
    for qid, bad in (("allocation_ratio", "5:5"), ("primary_timepoint_weeks", 2), ("alpha", 0.2)):
        try:
            answer(st, qid, bad, actor="t", now="n")
        except ValueError:
            continue
        raise AssertionError(f"{qid}={bad!r} should be rejected")


# ----------------------------------------------------------------------------- proposals / tracked changes


def test_factual_changes_detects_numbers_negation_modals_and_claims() -> None:
    orig = (
        "Participants must not receive systemic steroids for 4 weeks before Day 1; 126 participants will be randomized."
    )
    same = "Before Day 1, participants must not receive systemic steroids for 4 weeks; 126 participants will be randomized."
    assert factual_changes(orig, same, []) == []
    changed = (
        "Participants may receive systemic steroids for 2 weeks before Day 1; 120 participants will be randomized."
    )
    kinds = {
        c["kind"]
        for c in factual_changes(orig, changed, [{"text": "126 participants", "path": "protocol.planned_enrollment"}])
    }
    assert kinds == {"quantity", "negation", "modal", "claim"}


def test_propose_and_resolve_via_api(admin: TestClient) -> None:
    r = admin.post("/api/works", json={"title": "T", "starter": AD_ANTIBODY_ID})
    wid = r.json()["id"]
    blk = admin.get(f"/api/works/{wid}/draft").json()["blocks"][0]
    r = admin.post(
        f"/api/works/{wid}/commands",
        json={
            "type": "propose_text",
            "base_revision": 0,
            "block_id": blk["id"],
            "text": blk["text"].replace("126", "120"),
            "origin": "ai",
            "instruction": "tighten",
        },
    )
    assert r.status_code == 200, r.text
    props = admin.get(f"/api/works/{wid}/proposals").json()["proposals"]
    assert len(props) == 1 and any(c["kind"] == "quantity" for c in props[0]["proposal"]["factual_changes"])
    r = admin.post(
        f"/api/works/{wid}/commands",
        json={"type": "resolve_proposal", "base_revision": 1, "block_id": blk["id"], "accept": False},
    )
    assert r.status_code == 200
    b = next(x for x in admin.get(f"/api/works/{wid}/draft").json()["blocks"] if x["id"] == blk["id"])
    assert b["text"] == blk["text"] and b["proposal"] is None
    r = admin.post(
        f"/api/works/{wid}/commands",
        json={"type": "propose_text", "base_revision": 2, "block_id": blk["id"], "text": "New text.", "origin": "ai"},
    )
    r = admin.post(
        f"/api/works/{wid}/commands",
        json={"type": "resolve_proposal", "base_revision": 3, "block_id": blk["id"], "accept": True},
    )
    b = next(x for x in r.json()["state"]["blocks"] if x["id"] == blk["id"])
    assert b["text"] == "New text." and b["provenance"] == "generated"


# ----------------------------------------------------------------------------- trial lab


def test_trial_lab_routes(admin: TestClient) -> None:
    admin.cookies.clear()
    assert admin.post("/api/trial-lab/sample-size", json={"p_active": 0.6, "p_control": 0.3}).status_code == 401
    admin.post("/auth/dev-login")
    r = admin.post(
        "/api/trial-lab/sample-size",
        json={"p_active": 0.6, "p_control": 0.3, "power": 0.9, "alpha": 0.05, "evaluable_fraction": 0.9},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["result"]["control_evaluable"] == 56 and body["result"]["control_enrolled"] == 63
    assert [s["ratio"] for s in body["sensitivity"]] == [1.0, 2.0, 3.0]
    assert body["power_curve"] and 0 < body["power_curve"][0]["power"] < 1
    assert admin.post("/api/trial-lab/sample-size", json={"variable_type": "binary"}).status_code == 422
    profiles = admin.get("/api/trial-lab/profiles").json()
    assert {p["id"] for p in profiles} >= {"jak_like", "placebo_controlled"}
    assert admin.post("/api/trial-lab/explore", json={}).status_code == 422
    r = admin.post("/api/trial-lab/explore", json={"profile": "jak_like", "power": 0.9})
    assert r.status_code == 200, r.text
    rows = r.json()["rows"]
    assert rows == sorted(rows, key=lambda x: x["total_randomized"])
    assert all(row["assumption_source"] == "synthetic" for row in rows)
