"""LLM gateway: provider config + encrypted keys, fail-closed data-class policy, /ai/revise → proposal, /ai/ask.

The upstream call is faked; the OpenAI adapter's response parsing is tested on its own.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from protocol_studio.llm import gateway, keys
from protocol_studio.llm.providers import PROVIDERS, ProviderError, ProviderSpec, Request, Result, _output_text
from protocol_studio.starters import AD_ANTIBODY_ID
from tests.conftest import login_as


class FakeProvider:
    def __init__(self, reply: str = "", fail: bool = False) -> None:
        self.reply, self.fail, self.requests = reply, fail, []

    def complete(self, req: Request) -> Result:
        self.requests.append(req)
        if self.fail:
            raise ProviderError("openai: HTTP 429: rate limited")
        return Result(text=self.reply or req.user, model=req.model, input_tokens=120, output_tokens=40, latency_ms=5)

    def ping(self) -> str:
        return "ok — fake"


def _install_fake(monkeypatch: pytest.MonkeyPatch, fake: FakeProvider) -> None:
    def factory(spec: ProviderSpec, api_key: str, base_url: str = "") -> FakeProvider:
        assert api_key, "gateway must never call a provider without a key"
        return fake

    monkeypatch.setattr(gateway, "make_provider", factory)


def _work(admin: TestClient, data_class: str = "confidential") -> str:
    r = admin.post("/api/works", json={"title": "SRK-201", "starter": AD_ANTIBODY_ID, "data_class": data_class})
    assert r.status_code == 201, r.text
    wid: str = r.json()["id"]
    return wid


def _enable_openai(admin: TestClient) -> None:
    r = admin.put("/api/admin/providers/openai", json={"api_key": "sk-test-1234abcd", "enabled": True})
    assert r.status_code == 200, r.text
    assert r.json()["ready"] is True and r.json()["key_hint"] == "abcd" and r.json()["has_key"] is True


def test_key_roundtrip_and_hint() -> None:
    tok = keys.encrypt("sk-live-abcdef")
    assert tok != "sk-live-abcdef" and keys.decrypt(tok) == "sk-live-abcdef"
    assert keys.hint("sk-live-abcdef") == "cdef" and keys.hint("short") == ""


def test_output_text_parsing() -> None:
    assert _output_text({"output_text": "Hi"}) == "Hi"
    data = {
        "output": [
            {"type": "reasoning", "summary": []},
            {
                "type": "message",
                "content": [{"type": "output_text", "text": "Part A "}, {"type": "output_text", "text": "B"}],
            },
        ]
    }
    assert _output_text(data) == "Part A B"
    assert _output_text({"output": []}) == ""


def test_provider_admin_surface(admin: TestClient) -> None:
    rows = admin.get("/api/admin/providers").json()
    assert [r["id"] for r in rows] == list(PROVIDERS)
    oa = rows[0]
    assert oa["model"] == "gpt-6-astra" and oa["has_key"] is False and oa["ready"] is False
    assert oa["policy"] == {"public": True, "internal": False, "confidential": False, "restricted": False}
    assert admin.put("/api/admin/providers/nope", json={"enabled": True}).status_code == 404
    assert admin.put("/api/admin/providers/openai", json={"model": "gpt-3"}).status_code == 422
    # enabling without a key is stored but not "ready"
    assert admin.put("/api/admin/providers/openai", json={"enabled": True}).json()["ready"] is False
    _enable_openai(admin)
    # the key never comes back
    assert "sk-test" not in admin.get("/api/admin/providers").text
    assert (
        admin.put("/api/admin/providers/openai/policy", json={"data_class": "public", "approved": True}).status_code
        == 422
    )
    r = admin.put("/api/admin/providers/openai/policy", json={"data_class": "confidential", "approved": True})
    assert r.status_code == 200 and r.json()["policy"]["confidential"] is True
    r = admin.put("/api/admin/providers/openai", json={"api_key": ""})
    assert r.json()["has_key"] is False and r.json()["ready"] is False
    acts = [e["action"] for e in admin.get("/api/admin/audit", params={"action": "admin.provider"}).json()]
    assert "admin.provider.policy" in acts and "admin.provider.put" in acts
    admin.post("/api/admin/users", json={"email": "someone@sarika.com", "role": "author"})
    login_as(admin, "someone@sarika.com")
    assert admin.get("/api/admin/providers").status_code == 403


def test_env_key_is_used_when_no_db_key(admin: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env-zzzz9999")
    assert admin.put("/api/admin/providers/openai", json={"enabled": True}).json()["key_source"] == "env"
    assert admin.get("/api/admin/providers").json()[0]["ready"] is True


def test_revise_fails_closed_then_proposes(admin: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeProvider(
        reply="Approximately 126 participants will be randomized 1:1:1 to ADX-101 300 mg every 2 weeks."
    )
    _install_fake(monkeypatch, fake)
    wid = _work(admin, "confidential")
    blk = admin.get(f"/api/works/{wid}/draft").json()["blocks"][0]
    body = {"block_id": blk["id"], "instruction": "Make it one sentence.", "base_revision": 0}

    # 1. no provider enabled at all
    r = admin.post(f"/api/works/{wid}/ai/revise", json=body)
    assert r.status_code == 503 and fake.requests == []
    st = admin.get(f"/api/works/{wid}/ai/status").json()
    assert st["provider"] is None and st["allowed"] is False

    # 2. provider enabled but confidential not approved → 403, nothing sent, blocked call recorded
    _enable_openai(admin)
    r = admin.post(f"/api/works/{wid}/ai/revise", json=body)
    assert r.status_code == 403 and "stayed on this server" in r.json()["detail"] and fake.requests == []
    st = admin.get(f"/api/works/{wid}/ai/status").json()
    assert st["provider"] == "openai" and st["model"] == "gpt-6-astra" and st["allowed"] is False
    usage = admin.get("/api/admin/ai-usage").json()
    assert usage["totals"] == {"calls": 1, "input_tokens": 0, "output_tokens": 0, "blocked": 1, "errors": 0}

    # 3. approve confidential → the call goes out with only this block + its facts
    admin.put("/api/admin/providers/openai/policy", json={"data_class": "confidential", "approved": True})
    assert admin.get(f"/api/works/{wid}/ai/status").json()["allowed"] is True
    r = admin.post(f"/api/works/{wid}/ai/revise", json=body)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["revision"] == 1 and out["provider"] == "openai" and out["model"] == "gpt-6-astra"
    assert out["usage"]["input_tokens"] == 120
    sent = fake.requests[-1]
    assert sent.model == "gpt-6-astra" and blk["text"] in sent.user and "Make it one sentence." in sent.user
    assert '"protocol.phase"' in sent.user  # claim-bound facts travel with the paragraph
    other = admin.get(f"/api/works/{wid}/draft").json()["blocks"][5]["text"]
    assert other not in sent.user  # nothing beyond the selected block
    # the live text is untouched; the proposal is pending with factual checks
    live = next(b for b in admin.get(f"/api/works/{wid}/draft").json()["blocks"] if b["id"] == blk["id"])
    assert live["text"] == blk["text"]
    prop = out["proposal"]
    assert prop["origin"] == "ai" and prop["proposed_by"] == "openai:gpt-6-astra"
    kinds = {fc["kind"] for fc in prop["factual_changes"]}
    assert "claim" in kinds or "quantity" in kinds  # dropped "Phase 2b" / "16 weeks"
    # a second revise on the same block must resolve the first proposal
    assert admin.post(f"/api/works/{wid}/ai/revise", json={**body, "base_revision": 1}).status_code == 409
    r = admin.post(
        f"/api/works/{wid}/commands",
        json={"type": "resolve_proposal", "base_revision": 1, "block_id": blk["id"], "accept": True},
    )
    assert r.status_code == 200
    live = next(b for b in r.json()["state"]["blocks"] if b["id"] == blk["id"])
    assert live["text"] == fake.reply and live["provenance"] == "generated"
    usage = admin.get("/api/admin/ai-usage").json()
    assert usage["totals"]["calls"] == 2 and usage["totals"]["input_tokens"] == 120
    assert any(e["action"] == "ai.revise" for e in admin.get("/api/admin/audit", params={"work_id": wid}).json())
    assert admin.get("/api/admin/usage").json()[0]["ai_calls"] == 1


def test_public_work_needs_no_policy_and_ask(admin: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeProvider(reply="EASI-75 at Week 16 is standard for AD Phase 2b.")
    _install_fake(monkeypatch, fake)
    _enable_openai(admin)
    wid = _work(admin, "public")
    r = admin.post(
        f"/api/works/{wid}/ai/ask", json={"question": "Is the primary endpoint standard?", "section_id": "section.3"}
    )
    assert r.status_code == 200, r.text
    assert r.json()["answer"] == fake.reply and r.json()["advisory"] is True
    sent = fake.requests[-1]
    assert "CONTEXT (section.3)" in sent.user and "Is the primary endpoint standard?" in sent.user
    assert admin.post(f"/api/works/{wid}/ai/ask", json={"question": "  "}).status_code == 422
    # a confidential work on the same provider is still blocked
    wid2 = _work(admin, "confidential")
    assert admin.post(f"/api/works/{wid2}/ai/ask", json={"question": "x?"}).status_code == 403


def test_provider_error_is_recorded(admin: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake(monkeypatch, FakeProvider(fail=True))
    _enable_openai(admin)
    wid = _work(admin, "public")
    r = admin.post(f"/api/works/{wid}/ai/ask", json={"question": "x?"})
    assert r.status_code == 502 and "429" in r.json()["detail"]
    assert admin.get("/api/admin/ai-usage").json()["totals"]["errors"] == 1
    assert admin.post("/api/admin/providers/openai/test").json() == {
        "ok": True,
        "message": "ok — fake",
        "model": "gpt-6-astra",
    }


def test_viewer_cannot_revise(admin: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake(monkeypatch, FakeProvider(reply="x"))
    _enable_openai(admin)
    wid = _work(admin, "public")
    blk = admin.get(f"/api/works/{wid}/draft").json()["blocks"][0]
    admin.post("/api/admin/users", json={"email": "v@sarika.com", "role": "viewer"})
    admin.put(f"/api/works/{wid}/permissions", json={"email": "v@sarika.com", "level": "view"})
    login_as(admin, "v@sarika.com")
    body = {"block_id": blk["id"], "instruction": "shorten", "base_revision": 0}
    assert admin.post(f"/api/works/{wid}/ai/revise", json=body).status_code == 403
    assert admin.post(f"/api/works/{wid}/ai/ask", json={"question": "why?"}).status_code == 200
