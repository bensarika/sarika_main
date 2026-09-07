"""Admin › Models & providers.

    GET   /api/admin/providers                    every known provider: config (no key), policy per data class
    PUT   /api/admin/providers/{id}               {enabled?, model?, base_url?, api_key?}  (api_key "" clears)
    PUT   /api/admin/providers/{id}/policy        {data_class, approved}   fail-closed default
    POST  /api/admin/providers/{id}/test          connectivity + auth check with the stored/env key
    GET   /api/admin/ai-usage?period=30d          per-user/provider call counts + tokens (no prompt text)

Keys are stored encrypted (llm/keys.py) and never returned; the API exposes
``has_key`` and a 4-character hint. Approving a data class is an explicit,
audited admin action — nothing is approved by default except ``public``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from protocol_studio.auth.session import audit, require_admin
from protocol_studio.db import AiCall, ProviderConfig, ProviderPolicy, User, get_session
from protocol_studio.llm import gateway, keys
from protocol_studio.llm.providers import PROVIDERS, ProviderError

router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_admin)])

DATA_CLASSES = ("public", "internal", "confidential", "restricted")


def _spec_or_404(provider_id: str) -> None:
    if provider_id not in PROVIDERS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"unknown provider {provider_id}")


def _provider_json(db: Session, provider_id: str, users: dict[int, str]) -> dict[str, Any]:
    spec = PROVIDERS[provider_id]
    row = db.get(ProviderConfig, provider_id)
    res = gateway.resolve(db, provider_id)
    approved = gateway.approved_classes(db, provider_id)
    return {
        "id": spec.id,
        "label": spec.label,
        "models": list(spec.models),
        "default_model": spec.default_model,
        "docs_url": spec.docs_url,
        "enabled": bool(row and row.enabled),
        "model": res.model,
        "base_url": res.base_url,
        "has_key": bool(res.api_key),
        "key_source": res.key_source if res.api_key else None,
        "key_hint": (row.key_hint if row and row.api_key_enc else ""),
        "ready": res.enabled,
        "policy": {c: c in approved for c in DATA_CLASSES},
        "updated_by": users.get(row.updated_by) if row and row.updated_by else None,
        "updated_at": row.updated_at.isoformat() if row else None,
    }


@router.get("/providers")
def list_providers(db: Session = Depends(get_session)) -> list[dict[str, Any]]:
    users = {u.id: u.email for u in db.scalars(select(User)).all()}
    return [_provider_json(db, pid, users) for pid in PROVIDERS]


class PutProvider(BaseModel):
    enabled: bool | None = None
    model: str | None = None
    base_url: str | None = None
    api_key: str | None = None  # None = unchanged; "" = clear


@router.put("/providers/{provider_id}")
def put_provider(
    provider_id: str, body: PutProvider, admin: User = Depends(require_admin), db: Session = Depends(get_session)
) -> dict[str, Any]:
    _spec_or_404(provider_id)
    spec = PROVIDERS[provider_id]
    row = db.get(ProviderConfig, provider_id)
    if row is None:
        row = ProviderConfig(provider=provider_id, model=spec.default_model)
        db.add(row)
    changed: dict[str, Any] = {}
    if body.model is not None:
        if body.model not in spec.models:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"model must be one of {list(spec.models)}")
        row.model, changed["model"] = body.model, body.model
    if body.base_url is not None:
        row.base_url, changed["base_url"] = body.base_url.strip(), body.base_url.strip()
    if body.api_key is not None:
        key = body.api_key.strip()
        row.api_key_enc = keys.encrypt(key) if key else ""
        row.key_hint = keys.hint(key)
        changed["api_key"] = "set" if key else "cleared"
    if body.enabled is not None:
        row.enabled, changed["enabled"] = body.enabled, body.enabled
    row.updated_by, row.updated_at = admin.id, datetime.now(UTC)
    audit(db, actor=admin, action="admin.provider.put", provider=provider_id, **changed)
    db.commit()
    users = {u.id: u.email for u in db.scalars(select(User)).all()}
    return _provider_json(db, provider_id, users)


class PutPolicy(BaseModel):
    data_class: str
    approved: bool


@router.put("/providers/{provider_id}/policy")
def put_policy(
    provider_id: str, body: PutPolicy, admin: User = Depends(require_admin), db: Session = Depends(get_session)
) -> dict[str, Any]:
    _spec_or_404(provider_id)
    if body.data_class not in DATA_CLASSES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"data_class must be one of {DATA_CLASSES}")
    if body.data_class in gateway.OPEN_DATA_CLASSES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"{body.data_class} content is always allowed")
    pol = db.scalar(
        select(ProviderPolicy).where(
            ProviderPolicy.provider == provider_id, ProviderPolicy.data_class == body.data_class
        )
    )
    if pol is None:
        pol = ProviderPolicy(provider=provider_id, data_class=body.data_class)
        db.add(pol)
    pol.approved, pol.approved_by, pol.updated_at = body.approved, admin.id, datetime.now(UTC)
    audit(
        db,
        actor=admin,
        action="admin.provider.policy",
        provider=provider_id,
        data_class=body.data_class,
        approved=body.approved,
    )
    db.commit()
    users = {u.id: u.email for u in db.scalars(select(User)).all()}
    return _provider_json(db, provider_id, users)


@router.post("/providers/{provider_id}/test")
def test_provider(
    provider_id: str, admin: User = Depends(require_admin), db: Session = Depends(get_session)
) -> dict[str, Any]:
    _spec_or_404(provider_id)
    res = gateway.resolve(db, provider_id)
    if not res.api_key:
        return {"ok": False, "message": f"no API key stored and {res.spec.env_key} is not set"}
    try:
        msg = gateway.provider_for(res).ping()
    except ProviderError as e:
        audit(db, actor=admin, action="admin.provider.test", provider=provider_id, ok=False)
        db.commit()
        return {"ok": False, "message": str(e)}
    audit(db, actor=admin, action="admin.provider.test", provider=provider_id, ok=True)
    db.commit()
    return {"ok": True, "message": msg, "model": res.model}


_PERIODS = {"7d": 7, "30d": 30, "90d": 90, "all": None}


@router.get("/ai-usage")
def ai_usage(db: Session = Depends(get_session), period: str = "30d") -> dict[str, Any]:
    if period not in _PERIODS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"period must be one of {sorted(_PERIODS)}")
    q = select(
        AiCall.user_id,
        AiCall.provider,
        AiCall.model,
        AiCall.status,
        func.count(),
        func.sum(AiCall.input_tokens),
        func.sum(AiCall.output_tokens),
        func.avg(AiCall.latency_ms),
    ).group_by(AiCall.user_id, AiCall.provider, AiCall.model, AiCall.status)
    days = _PERIODS[period]
    if days is not None:
        q = q.where(AiCall.created_at >= datetime.now(UTC) - timedelta(days=days))
    users = {u.id: u.email for u in db.scalars(select(User)).all()}
    rows = [
        {
            "email": users.get(uid) if uid else None,
            "provider": provider,
            "model": model,
            "status": st,
            "calls": int(n),
            "input_tokens": int(tin or 0),
            "output_tokens": int(tout or 0),
            "avg_latency_ms": int(lat or 0),
        }
        for uid, provider, model, st, n, tin, tout, lat in db.execute(q).all()
    ]
    totals = {
        "calls": sum(r["calls"] for r in rows),
        "input_tokens": sum(r["input_tokens"] for r in rows),
        "output_tokens": sum(r["output_tokens"] for r in rows),
        "blocked": sum(r["calls"] for r in rows if r["status"] == "blocked"),
        "errors": sum(r["calls"] for r in rows if r["status"] == "error"),
    }
    return {"period": period, "rows": sorted(rows, key=lambda r: -r["calls"]), "totals": totals}
