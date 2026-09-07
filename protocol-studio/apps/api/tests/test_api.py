"""API: auth/ACL, commands + stale rejection, claims, adjudication, versions, export, admin."""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.conftest import login_as


def _work(admin: TestClient, starter: str = "example:SYN.protocol.v1") -> str:
    r = admin.post("/api/works", json={"title": "SRK-201 Phase 2b", "starter": starter})
    assert r.status_code == 201, r.text
    wid: str = r.json()["id"]
    return wid


def _cmd(c: TestClient, wid: str, **cmd: object) -> object:
    return c.post(f"/api/works/{wid}/commands", json=cmd)


# ----------------------------------------------------------------------------- auth / acl


def test_unauthenticated_is_401(client: TestClient) -> None:
    assert client.get("/api/works").status_code == 401
    assert client.get("/auth/me").status_code == 401
    assert client.get("/healthz").status_code == 200


def test_unknown_account_is_denied_until_admin_activates(admin: TestClient) -> None:
    wid = _work(admin)
    admin.cookies.clear()
    r = admin.post("/auth/dev-login", params={"email": "new@sarika.com"})
    assert r.status_code == 403
    # admin authorises them as viewer
    admin.post("/auth/dev-login")
    r = admin.post("/api/admin/users", json={"email": "new@sarika.com", "role": "viewer"})
    assert r.status_code == 201
    login_as(admin, "new@sarika.com")
    assert admin.get("/api/works").json() == []  # no per-work permission yet
    assert admin.get(f"/api/works/{wid}/draft").status_code == 403
    login_as(admin, "ben@sarika.com")
    assert (
        admin.put(f"/api/works/{wid}/permissions", json={"email": "new@sarika.com", "level": "view"}).status_code == 200
    )
    login_as(admin, "new@sarika.com")
    assert admin.get(f"/api/works/{wid}/draft").status_code == 200
    r = _cmd(admin, wid, type="set_field", base_revision=0, path="protocol.phase", value="2b")
    assert r.status_code == 403  # view-only cannot edit
    assert admin.get("/api/admin/users").status_code == 403


# ----------------------------------------------------------------------------- commands


def test_command_revisions_and_stale_rejection(admin: TestClient) -> None:
    wid = _work(admin)
    r = _cmd(admin, wid, type="set_field", base_revision=0, path="protocol.phase", value="2b")
    assert r.status_code == 200 and r.json()["revision"] == 1
    stale = _cmd(admin, wid, type="set_field", base_revision=0, path="protocol.phase", value="3")
    assert stale.status_code == 409 and stale.json()["detail"]["head"] == 1
    bad = _cmd(admin, wid, type="set_field", base_revision=1, path="protocol.phase", value=5)
    assert bad.status_code == 422
    assert admin.get(f"/api/works/{wid}/draft").json()["revision"] == 1  # rejected commands leave no trace
    hist = admin.get(f"/api/works/{wid}/history").json()
    assert [h["revision"] for h in hist] == [1]


def test_blank_starter_and_entities(admin: TestClient) -> None:
    wid = _work(admin, starter="blank")
    ev = admin.get(f"/api/works/{wid}/evaluation").json()
    assert ev["completion"]["overall"]["pct"] < 10
    r = _cmd(
        admin,
        wid,
        type="add_entity",
        base_revision=0,
        collection="endpoints",
        entity={"id": "easi75", "name": "EASI-75", "variable_type": "binary"},
    )
    assert r.status_code == 200, r.text
    dup = _cmd(
        admin, wid, type="add_entity", base_revision=1, collection="endpoints", entity={"id": "easi75", "name": "again"}
    )
    assert dup.status_code == 422
    r = _cmd(admin, wid, type="remove_entity", base_revision=1, collection="endpoints", entity_id="easi75")
    assert r.status_code == 200 and "endpoints" not in r.json()["state"]["model"]


def test_claim_mismatch_and_resolution(admin: TestClient) -> None:
    wid = _work(admin)
    r = _cmd(
        admin,
        wid,
        type="upsert_block",
        base_revision=0,
        section_id="section.3",
        subsection_id="section.3.3",
        text="Primary endpoint assessed at Week 12.",
    )
    bid = r.json()["state"]["blocks"][-1]["id"]
    r = _cmd(
        admin,
        wid,
        type="set_claim",
        base_revision=1,
        block_id=bid,
        path="endpoints[easi75].time.offset.value",
        value=12,
        text="Week 12",
    )
    claim = r.json()["state"]["blocks"][-1]["claims"][0]
    assert claim["state"] == "mismatch" and claim["model_value"] == 16
    assert any(f["rule_id"] == "CL01" for f in r.json()["evaluation"]["findings"])
    r = _cmd(
        admin, wid, type="resolve_claim", base_revision=2, block_id=bid, claim_id=claim["id"], resolution="revert_text"
    )
    blk = r.json()["state"]["blocks"][-1]
    assert blk["text"] == "Primary endpoint assessed at Week 16." and blk["claims"][0]["state"] == "checked"
    assert not any(f["rule_id"] == "CL01" for f in r.json()["evaluation"]["findings"])
    # the other way round: text wins, model changes
    r = _cmd(
        admin,
        wid,
        type="set_claim",
        base_revision=3,
        block_id=bid,
        claim_id=blk["claims"][0]["id"],
        path="endpoints[easi75].time.offset.value",
        value=12,
        text="Week 12",
    )
    r = _cmd(
        admin,
        wid,
        type="resolve_claim",
        base_revision=4,
        block_id=bid,
        claim_id=blk["claims"][0]["id"],
        resolution="update_model",
    )
    easi75 = next(e for e in r.json()["state"]["model"]["endpoints"] if e["id"] == "easi75")
    assert (
        easi75["time"]["offset"]["value"] == 12 and r.json()["state"]["blocks"][-1]["claims"][0]["state"] == "checked"
    )


def test_approval_drives_completion_and_edit_demotes(admin: TestClient) -> None:
    wid = _work(admin, starter="blank")
    r = _cmd(
        admin,
        wid,
        type="upsert_block",
        base_revision=0,
        section_id="section.2",
        subsection_id="section.2.1",
        text="Background.",
    )
    bid = r.json()["state"]["blocks"][-1]["id"]
    sec2 = lambda resp: next(s for s in resp["evaluation"]["completion"]["sections"] if s["section_id"] == "section.2")  # noqa: E731
    drafted = sec2(r.json())
    r = _cmd(admin, wid, type="set_block_approval", base_revision=1, block_id=bid, approval="approved")
    approved = sec2(r.json())
    assert approved["filled"] == drafted["filled"] + 1
    r = _cmd(
        admin,
        wid,
        type="upsert_block",
        base_revision=2,
        block_id=bid,
        section_id="section.2",
        subsection_id="section.2.1",
        text="Background, revised.",
    )
    assert r.json()["state"]["blocks"][-1]["approval"] == "unreviewed"


def test_not_applicable_and_adjudication_stale(admin: TestClient) -> None:
    wid = _work(admin)
    ev = admin.get(f"/api/works/{wid}/evaluation").json()
    slot_finding = next(f for f in ev["findings"] if f["severity"] == "incomplete")
    r = admin.post(
        f"/api/works/{wid}/adjudications",
        json={"finding_key": slot_finding["key"], "decision": "dismissed", "revision": 99},
    )
    assert r.status_code == 409
    r = admin.post(
        f"/api/works/{wid}/adjudications",
        json={"finding_key": slot_finding["key"], "decision": "dismissed", "revision": ev["revision"]},
    )
    assert r.status_code == 200
    assert next(f for f in r.json()["findings"] if f["key"] == slot_finding["key"])["adjudication"] == "dismissed"
    r = _cmd(
        admin,
        wid,
        type="set_not_applicable",
        base_revision=0,
        slot_id=slot_finding["targets"][0] if slot_finding["targets"] else "x",
        reason="single-arm study",
    )
    assert r.status_code == 200


# ----------------------------------------------------------------------------- versions / export


def test_freeze_and_export(admin: TestClient) -> None:
    wid = _work(admin)
    r = admin.post(f"/api/works/{wid}/versions", json={"label": "v0.1", "render_pdf": False})
    assert r.status_code == 201, r.text
    v = r.json()
    assert v["revision"] == 0 and v["artifacts"]["docx"]["available"] and v["readiness"]["ready"] is False
    assert admin.post(f"/api/works/{wid}/versions", json={"label": "v0.1"}).status_code == 409
    assert admin.post(f"/api/works/{wid}/versions", json={"label": "bad label!"}).status_code == 422
    f = admin.get(f"/api/works/{wid}/versions/v0.1/file/docx")
    assert f.status_code == 200 and f.content[:2] == b"PK"
    tex = admin.get(f"/api/works/{wid}/export/tex")
    assert tex.status_code == 200 and b"\\begin{document}" in tex.content
    full = admin.get(f"/api/works/{wid}/versions/v0.1").json()
    assert full["snapshot"]["revision"] == 0 and "findings" in full["evaluation"]


# ----------------------------------------------------------------------------- admin


def test_admin_usage_and_audit(admin: TestClient) -> None:
    wid = _work(admin)
    _cmd(admin, wid, type="set_field", base_revision=0, path="protocol.phase", value="2b")
    usage = admin.get("/api/admin/usage").json()
    assert usage[0]["email"] == "ben@sarika.com" and usage[0]["commands"] == 1 and usage[0]["logins"] == 1
    log = admin.get("/api/admin/audit", params={"work_id": wid}).json()
    assert {e["action"] for e in log} >= {"work.create", "command.set_field"}
    me = admin.get("/api/admin/users").json()[0]
    r = admin.patch(f"/api/admin/users/{me['id']}", json={"active": False})
    assert r.status_code == 422  # primary admin cannot lock themselves out
