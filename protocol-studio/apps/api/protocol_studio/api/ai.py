"""On-demand model reasoning inside a work.

    GET  /api/works/{id}/ai/status              which provider would be used and whether this work's
                                                data class is approved for it (drives the editor UI)
    POST /api/works/{id}/ai/revise              {block_id, instruction, base_revision, provider?}
                                                → propose_text (origin=ai) with factual-change checks
    POST /api/works/{id}/ai/ask                 {question, section_id?, provider?} → advisory answer

Both routes go through ``llm.gateway.call`` and therefore fail closed on data
class. A revision is *never* applied: it lands as a pending proposal that the
author accepts or rejects (``resolve_proposal``), exactly like a reviewer's
suggestion. Model output is advisory and not a regulatory determination.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from protocol_studio.api.works import load_state, persist_revision
from protocol_studio.auth.session import audit, current_user, require_work
from protocol_studio.db import User, Work, get_session
from protocol_studio.engine.commands import CommandError, ConflictError, ProposeText, apply_command
from protocol_studio.llm import gateway, prompts
from protocol_studio.llm.providers import ProviderError

router = APIRouter(prefix="/api/works", tags=["ai"])


def _pick(db: Session, requested: str | None) -> str:
    pid = requested or gateway.default_provider(db)
    if pid is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "no model provider is enabled — configure one in Admin › Models"
        )
    return pid


@router.get("/{work_id}/ai/status")
def ai_status(work: Work = Depends(require_work("view")), db: Session = Depends(get_session)) -> dict[str, Any]:
    pid = gateway.default_provider(db)
    if pid is None:
        return {
            "provider": None,
            "model": None,
            "allowed": False,
            "reason": "no provider enabled",
            "data_class": work.data_class,
        }
    res = gateway.resolve(db, pid)
    ok = gateway.allowed(db, pid, work.data_class)
    return {
        "provider": pid,
        "label": res.spec.label,
        "model": res.model,
        "data_class": work.data_class,
        "allowed": ok,
        "reason": "" if ok else f"{res.spec.label} is not approved for {work.data_class} content",
    }


class Revise(BaseModel):
    block_id: str
    instruction: str
    base_revision: int
    provider: str | None = None


@router.post("/{work_id}/ai/revise")
def revise(
    body: Revise,
    work: Work = Depends(require_work("edit")),
    user: User = Depends(current_user),
    db: Session = Depends(get_session),
) -> dict[str, Any]:
    if not body.instruction.strip():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "instruction is empty")
    state = load_state(db, work.id)
    if body.base_revision != state.revision:
        raise HTTPException(status.HTTP_409_CONFLICT, {"error": "stale", "head": state.revision})
    blk = next((b for b in state.blocks if b.id == body.block_id), None)
    if blk is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no block {body.block_id}")
    if blk.proposal is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "block already has a pending proposal; resolve it first")
    pid = _pick(db, body.provider)
    try:
        out = gateway.call(
            db,
            provider_id=pid,
            data_class=work.data_class,
            purpose="revise",
            system=prompts.SYSTEM_REVISE,
            user_text=prompts.revise_user(blk, state.model, body.instruction),
            actor=user,
            work_id=work.id,
        )
    except gateway.PolicyBlockedError as e:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(e)) from e
    except ProviderError as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(e)) from e
    text = out.text.strip()
    if not text:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "the model returned no text")
    cmd = ProposeText(
        base_revision=state.revision, block_id=blk.id, text=text, origin="ai", instruction=body.instruction.strip()
    )
    try:
        new_state, summary = apply_command(state, cmd, actor=f"{pid}:{out.model}")
    except ConflictError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, {"error": "stale", "head": state.revision}) from e
    except CommandError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e)) from e
    audit(db, actor=user, action="ai.revise", work_id=work.id, block_id=blk.id, provider=pid, model=out.model)
    res = persist_revision(db, work, user, new_state, command=cmd.model_dump(), summary=summary)
    proposal = next(b for b in new_state.blocks if b.id == blk.id).proposal
    return {
        **res,
        "block_id": blk.id,
        "proposal": proposal.model_dump() if proposal else None,
        "provider": pid,
        "model": out.model,
        "usage": {"input_tokens": out.input_tokens, "output_tokens": out.output_tokens, "latency_ms": out.latency_ms},
    }


class Ask(BaseModel):
    question: str
    section_id: str = ""
    provider: str | None = None


@router.post("/{work_id}/ai/ask")
def ask(
    body: Ask,
    work: Work = Depends(require_work("view")),
    user: User = Depends(current_user),
    db: Session = Depends(get_session),
) -> dict[str, Any]:
    if not body.question.strip():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "question is empty")
    state = load_state(db, work.id)
    pid = _pick(db, body.provider)
    try:
        out = gateway.call(
            db,
            provider_id=pid,
            data_class=work.data_class,
            purpose="ask",
            system=prompts.SYSTEM_ASK,
            user_text=prompts.ask_user(state, body.section_id, body.question),
            actor=user,
            work_id=work.id,
        )
    except gateway.PolicyBlockedError as e:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(e)) from e
    except ProviderError as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(e)) from e
    audit(db, actor=user, action="ai.ask", work_id=work.id, section_id=body.section_id, provider=pid, model=out.model)
    db.commit()
    return {
        "answer": out.text.strip(),
        "provider": pid,
        "model": out.model,
        "section_id": body.section_id,
        "advisory": True,
        "usage": {"input_tokens": out.input_tokens, "output_tokens": out.output_tokens, "latency_ms": out.latency_ms},
    }
