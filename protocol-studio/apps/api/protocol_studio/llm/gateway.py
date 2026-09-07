"""The single choke point for sending text to a model provider.

    resolve(db, provider_id) -> Resolved          config + key (DB, else env), enabled check
    allowed(db, provider_id, data_class) -> bool  fail-closed policy
    call(db, ...) -> Result                       policy → provider → AiCall row (never prompt text)

``PolicyBlockedError`` and ``ProviderError`` are the only exceptions callers must map
to HTTP; both messages are safe to display.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from protocol_studio.db import AiCall, ProviderConfig, ProviderPolicy, User
from protocol_studio.llm import keys
from protocol_studio.llm.providers import (
    PROVIDERS,
    Provider,
    ProviderError,
    ProviderSpec,
    Request,
    Result,
    make_provider,
)

OPEN_DATA_CLASSES = frozenset({"public"})


class PolicyBlockedError(PermissionError):
    """The provider is not approved for this data class (or not configured). Nothing was sent."""


@dataclass
class Resolved:
    spec: ProviderSpec
    model: str
    base_url: str
    api_key: str
    key_source: str  # db | env
    enabled: bool


def config_row(db: Session, provider_id: str) -> ProviderConfig | None:
    return db.get(ProviderConfig, provider_id)


def resolve(db: Session, provider_id: str) -> Resolved:
    spec = PROVIDERS.get(provider_id)
    if spec is None:
        raise PolicyBlockedError(f"unknown provider {provider_id!r}")
    row = config_row(db, provider_id)
    api_key, source = "", "env"
    if row is not None and row.api_key_enc:
        api_key, source = keys.decrypt(row.api_key_enc), "db"
    elif os.environ.get(spec.env_key):
        api_key = os.environ[spec.env_key]
    return Resolved(
        spec=spec,
        model=(row.model if row and row.model else spec.default_model),
        base_url=(row.base_url if row else ""),
        api_key=api_key,
        key_source=source,
        enabled=bool(row and row.enabled and api_key),
    )


def approved_classes(db: Session, provider_id: str) -> set[str]:
    rows = db.scalars(
        select(ProviderPolicy).where(ProviderPolicy.provider == provider_id, ProviderPolicy.approved.is_(True))
    ).all()
    return set(OPEN_DATA_CLASSES) | {r.data_class for r in rows}


def allowed(db: Session, provider_id: str, data_class: str) -> bool:
    return data_class in approved_classes(db, provider_id)


def default_provider(db: Session) -> str | None:
    """First enabled provider (admin order = PROVIDERS order). None → AI features are off."""
    for pid in PROVIDERS:
        if resolve(db, pid).enabled:
            return pid
    return None


def provider_for(resolved: Resolved) -> Provider:
    return make_provider(resolved.spec, resolved.api_key, resolved.base_url)


def call(
    db: Session,
    *,
    provider_id: str,
    data_class: str,
    purpose: str,
    system: str,
    user_text: str,
    actor: User | None,
    work_id: str | None,
    model: str | None = None,
    max_output_tokens: int = 1200,
) -> Result:
    res = resolve(db, provider_id)
    rec = AiCall(
        user_id=actor.id if actor else None,
        work_id=work_id,
        provider=provider_id,
        model=model or res.model,
        purpose=purpose,
        data_class=data_class,
    )
    if not res.enabled:
        rec.status, rec.error = "blocked", "provider not enabled or no API key"
        db.add(rec)
        db.commit()
        raise PolicyBlockedError(
            f"{res.spec.label} is not enabled — an administrator must configure it in Admin › Models"
        )
    if not allowed(db, provider_id, data_class):
        rec.status, rec.error = "blocked", f"data class {data_class} not approved"
        db.add(rec)
        db.commit()
        raise PolicyBlockedError(
            f"{res.spec.label} is not approved for {data_class} content; the text stayed on this server. "
            "An administrator can approve the provider for this data class in Admin › Models."
        )
    try:
        out = provider_for(res).complete(
            Request(system=system, user=user_text, model=rec.model, max_output_tokens=max_output_tokens)
        )
    except ProviderError as e:
        rec.status, rec.error = "error", str(e)[:400]
        db.add(rec)
        db.commit()
        raise
    rec.input_tokens, rec.output_tokens, rec.latency_ms, rec.model = (
        out.input_tokens,
        out.output_tokens,
        out.latency_ms,
        out.model,
    )
    db.add(rec)
    db.commit()
    return out
