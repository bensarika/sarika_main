"""Comments/suggestions, presence, access requests, version diff + restore, usage periods/CSV."""

from __future__ import annotations

from fastapi.testclient import TestClient

from protocol_studio.engine.diff import model_diff, word_ops
from protocol_studio.starters import AD_ANTIBODY_ID
from tests.conftest import login_as

REVIEWER = "rev@sarika.com"


def _work(admin: TestClient) -> str:
    r = admin.post("/api/works", json={"title": "SRK-201", "starter": AD_ANTIBODY_ID})
    assert r.status_code == 201, r.text
    wid: str = r.json()["id"]
    return wid


def _add_reviewer(admin: TestClient, wid: str, level: str = "view") -> None:
    assert admin.post("/api/admin/users", json={"email": REVIEWER, "role": "reviewer"}).status_code == 201
    assert admin.put(f"/api/works/{wid}/permissions", json={"email": REVIEWER, "level": level}).status_code == 200


# ----------------------------------------------------------------------------- comments


def test_comment_threads_and_suggestion_apply(admin: TestClient) -> None:
    wid = _work(admin)
    _add_reviewer(admin, wid)
    blk = admin.get(f"/api/works/{wid}/draft").json()["blocks"][0]

    login_as(admin, REVIEWER)  # view-only reviewer can comment and suggest, not edit
    r = admin.post(f"/api/works/{wid}/comments", json={"body": "Clarify the primary timepoint.", "block_id": blk["id"]})
    assert r.status_code == 201, r.text
    root = r.json()
    assert root["section_id"] == blk["section_id"] and root["resolved"] is False
    r = admin.post(f"/api/works/{wid}/comments", json={"body": "Agreed.", "parent_id": root["id"]})
    assert r.status_code == 201 and r.json()["block_id"] == blk["id"]
    r = admin.post(
        f"/api/works/{wid}/comments",
        json={"kind": "suggestion", "block_id": blk["id"], "suggested_text": blk["text"] + " (Illustrative.)"},
    )
    assert r.status_code == 201
    sugg = r.json()
    assert (
        admin.post(f"/api/works/{wid}/comments", json={"kind": "suggestion", "block_id": blk["id"]}).status_code == 422
    )
    assert admin.post(f"/api/works/{wid}/comments", json={"body": "   "}).status_code == 422
    # reviewer cannot apply (needs edit) but can resolve their own thread
    assert admin.post(f"/api/works/{wid}/comments/{sugg['id']}/apply", json={"base_revision": 0}).status_code == 403
    assert admin.patch(f"/api/works/{wid}/comments/{root['id']}", json={"resolved": True}).json()["resolved"] is True

    login_as(admin, "ben@sarika.com")
    threads = admin.get(f"/api/works/{wid}/comments").json()
    assert [len(t["replies"]) for t in threads] == [1, 0]
    assert len(admin.get(f"/api/works/{wid}/comments", params={"resolved": "false"}).json()) == 1
    # only the author may edit a body
    assert admin.patch(f"/api/works/{wid}/comments/{root['id']}", json={"body": "x"}).status_code == 403

    r = admin.post(f"/api/works/{wid}/comments/{sugg['id']}/apply", json={"base_revision": 0})
    assert r.status_code == 200, r.text
    assert r.json()["revision"] == 1 and r.json()["comment"]["resolved"] is True
    props = admin.get(f"/api/works/{wid}/proposals").json()["proposals"]
    assert (
        len(props) == 1
        and props[0]["proposal"]["origin"] == "suggestion"
        and REVIEWER in props[0]["proposal"]["instruction"]
    )
    live = next(b for b in admin.get(f"/api/works/{wid}/draft").json()["blocks"] if b["id"] == blk["id"])
    assert live["text"] == blk["text"]  # still a proposal, not applied
    assert admin.post(f"/api/works/{wid}/comments/{sugg['id']}/apply", json={"base_revision": 0}).status_code == 409
    hist = admin.get(f"/api/works/{wid}/history").json()
    assert hist[0]["type"] == "propose_text"


def test_presence_heartbeat(admin: TestClient) -> None:
    wid = _work(admin)
    rows = admin.put(f"/api/works/{wid}/presence", json={"section_id": "section.4"}).json()
    assert rows == admin.get(f"/api/works/{wid}/presence").json()
    assert rows[0]["email"] == "ben@sarika.com" and rows[0]["section_id"] == "section.4"


# ----------------------------------------------------------------------------- access requests


def test_access_request_flow(admin: TestClient) -> None:
    wid = _work(admin)
    assert admin.post("/api/admin/users", json={"email": REVIEWER, "role": "author"}).status_code == 201
    login_as(admin, REVIEWER)
    assert admin.get(f"/api/works/{wid}/draft").status_code == 403
    r = admin.post(f"/api/works/{wid}/access-requests", json={"level": "edit", "message": "Co-authoring §10."})
    assert r.status_code == 201, r.text
    rid = r.json()["id"]
    assert admin.post(f"/api/works/{wid}/access-requests", json={"level": "view"}).status_code == 409  # pending
    assert admin.get(f"/api/works/{wid}/access-requests").status_code == 403  # not a work admin
    assert admin.get("/api/access-requests/mine").json()[0]["status"] == "pending"

    login_as(admin, "ben@sarika.com")
    pending = admin.get("/api/admin/access-requests").json()
    assert pending[0]["id"] == rid and pending[0]["work_title"] == "SRK-201"
    r = admin.post(
        f"/api/works/{wid}/access-requests/{rid}", json={"approve": True, "level": "view", "note": "view first"}
    )
    assert r.status_code == 200 and r.json()["status"] == "approved" and r.json()["level"] == "view"
    assert admin.post(f"/api/works/{wid}/access-requests/{rid}", json={"approve": False}).status_code == 409
    assert admin.get("/api/admin/access-requests").json() == []

    login_as(admin, REVIEWER)
    assert admin.get(f"/api/works/{wid}/draft").status_code == 200
    assert admin.post(f"/api/works/{wid}/access-requests", json={"level": "view"}).status_code == 409  # already have
    assert admin.post(f"/api/works/{wid}/access-requests", json={"level": "edit"}).status_code == 201  # upgrade ok
    assert admin.get("/api/access-requests/mine").json()[0]["level"] == "edit"


# ----------------------------------------------------------------------------- diff / restore


def test_word_ops_and_model_diff() -> None:
    ops = word_ops("Participants will receive 200 mg.", "Participants will receive 300 mg weekly.")
    assert [o["op"] for o in ops] == ["equal", "delete", "insert", "equal", "insert", "equal"] or any(
        o["op"] == "delete" and "200" in o["text"] for o in ops
    )
    assert "".join(o["text"] for o in ops if o["op"] != "delete") == "Participants will receive 300 mg weekly."
    rows = model_diff(
        {"endpoints": [{"id": "a", "n": 1}, {"id": "b", "n": 2}], "x": 1},
        {"endpoints": [{"id": "b", "n": 2}, {"id": "a", "n": 3}], "y": 2},
    )
    assert {(r["path"], r["change"]) for r in rows} == {("endpoints[a].n", "changed"), ("x", "removed"), ("y", "added")}


def test_version_diff_and_restore(admin: TestClient) -> None:
    wid = _work(admin)
    blk = admin.get(f"/api/works/{wid}/draft").json()["blocks"][0]
    assert admin.post(f"/api/works/{wid}/versions", json={"label": "v0.1", "render_pdf": False}).status_code == 201
    r = admin.post(
        f"/api/works/{wid}/commands",
        json={"type": "set_field", "base_revision": 0, "path": "protocol.phase", "value": "3"},
    )
    assert r.status_code == 200
    r = admin.post(
        f"/api/works/{wid}/commands",
        json={
            "type": "upsert_block",
            "base_revision": 1,
            "block_id": blk["id"],
            "section_id": blk["section_id"],
            "subsection_id": blk["subsection_id"],
            "text": blk["text"] + " Added sentence.",
        },
    )
    assert r.status_code == 200, r.text
    r = admin.post(
        f"/api/works/{wid}/commands",
        json={"type": "set_block_approval", "base_revision": 2, "block_id": blk["id"], "approval": "approved"},
    )
    assert r.status_code == 200, r.text

    d = admin.get(f"/api/works/{wid}/versions/v0.1/diff").json()
    assert (d["from"], d["to"], d["from_revision"], d["to_revision"]) == ("v0.1", "head", 0, 3)
    assert {(m["path"], m["change"]) for m in d["model"]} == {("protocol.phase", "changed")}
    changed = [b for b in d["blocks"] if b["change"] == "changed"]
    assert len(changed) == 1 and changed[0]["block_id"] == blk["id"]
    assert any(o["op"] == "insert" and "Added sentence." in o["text"] for o in changed[0]["ops"])
    assert d["summary"]["blocks_changed"] == 1 and d["summary"]["sections_touched"] == [blk["section_id"]]
    assert admin.get(f"/api/works/{wid}/versions/v0.1/diff", params={"against": "nope"}).status_code == 404

    assert admin.post(f"/api/works/{wid}/versions", json={"label": "v0.2", "render_pdf": False}).status_code == 201
    d2 = admin.get(f"/api/works/{wid}/versions/v0.1/diff", params={"against": "v0.2"}).json()
    assert d2["to_revision"] == 3 and d2["summary"]["blocks_changed"] == 1

    # restore v0.1 → new head revision 4, nothing rewound
    assert admin.post(f"/api/works/{wid}/versions/v0.1/restore", json={"base_revision": 2}).status_code == 409
    r = admin.post(f"/api/works/{wid}/versions/v0.1/restore", json={"base_revision": 3})
    assert r.status_code == 200, r.text
    assert r.json()["revision"] == 4 and "Restored version v0.1" in r.json()["summary"]
    st = r.json()["state"]
    assert st["model"]["protocol"]["phase"] != "3"
    live = next(b for b in st["blocks"] if b["id"] == blk["id"])
    assert live["text"] == blk["text"] and live["approval"] == "unreviewed"
    assert admin.get(f"/api/works/{wid}/history").json()[0]["type"] == "restore_version"
    assert admin.get(f"/api/works/{wid}/versions/v0.1/diff").json()["summary"]["blocks_changed"] == 0


# ----------------------------------------------------------------------------- usage


def test_usage_periods_and_csv(admin: TestClient) -> None:
    wid = _work(admin)
    admin.post(f"/api/works/{wid}/comments", json={"body": "hi"})
    for period in ("7d", "30d", "90d", "all"):
        rows = admin.get("/api/admin/usage", params={"period": period}).json()
        assert rows[0]["email"] == "ben@sarika.com" and rows[0]["comments"] == 1 and rows[0]["role"] == "admin"
    assert admin.get("/api/admin/usage", params={"period": "2d"}).status_code == 422
    r = admin.get("/api/admin/usage.csv", params={"period": "30d"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    lines = r.text.strip().splitlines()
    assert lines[0] == "email,role,commands,exports,freezes,ai_calls,comments,logins,other"
    assert lines[1].startswith("ben@sarika.com,admin,")
