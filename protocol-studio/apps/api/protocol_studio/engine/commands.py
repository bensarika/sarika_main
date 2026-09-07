"""The edit/commit contract (docs/01_architecture.md §6.2).

Every semantic change is a *command* applied to a ``DraftState`` at a known
``base_revision``. ``apply_command``:

1. rejects the command if ``base_revision != state.revision`` (optimistic
   concurrency — a stale editor must reload before it can write);
2. validates the command against the model schema in draft mode (structure,
   enums, patterns; missing-required is allowed while drafting);
3. mutates a *copy* of the state, increments the revision, refreshes claim
   states (a text claim can only be checked against the model it names);
4. returns the new state plus a one-line human summary for the revision log.

Commands are Pydantic models discriminated on ``type`` so the API, the log
and the tests share one definition.
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field

from protocol_studio.engine import adaptation as adapt
from protocol_studio.engine import key_inputs
from protocol_studio.engine.state import Block, Claim, DraftState, DrugSpec, Proposal
from protocol_studio.engine.textcheck import factual_changes
from ps_model.paths import PathError, delete_path, get_path, set_path
from ps_model.schema import validate_model
from ps_rules.rules_claims import check_claims


class ConflictError(Exception):
    """base_revision is behind the head; the client must reload."""


class CommandError(ValueError):
    """The command is well-formed but cannot be applied (bad path, schema violation…)."""


# ----------------------------------------------------------------------------- command types


class _Cmd(BaseModel):
    base_revision: int
    note: str = ""  # optional author note, shown in history


class SetField(_Cmd):
    type: Literal["set_field"] = "set_field"
    path: str  # dotted path, e.g. "protocol.phase" or "endpoints[easi75].time.offset.value"
    value: Any


class AddEntity(_Cmd):
    type: Literal["add_entity"] = "add_entity"
    collection: str  # "endpoints"
    entity: dict[str, Any]  # must carry "id" and "name"


class RemoveEntity(_Cmd):
    type: Literal["remove_entity"] = "remove_entity"
    collection: str
    entity_id: str


class UpsertBlock(_Cmd):
    type: Literal["upsert_block"] = "upsert_block"
    block_id: str | None = None  # None → create
    section_id: str
    subsection_id: str
    text: str
    kind: str = "paragraph"
    order: int | None = None
    provenance: str = "author"


class DeleteBlock(_Cmd):
    type: Literal["delete_block"] = "delete_block"
    block_id: str


class SetBlockApproval(_Cmd):
    type: Literal["set_block_approval"] = "set_block_approval"
    block_id: str
    approval: Literal["unreviewed", "approved", "rejected"]


class SetClaim(_Cmd):
    """Bind a phrase in a block to a model path (or update/remove a binding)."""

    type: Literal["set_claim"] = "set_claim"
    block_id: str
    claim_id: str | None = None
    path: str
    value: Any = None
    text: str = ""
    remove: bool = False


class ResolveClaim(_Cmd):
    """Mismatch resolution: push the text value into the model, or rewrite the text to the model."""

    type: Literal["resolve_claim"] = "resolve_claim"
    block_id: str
    claim_id: str
    resolution: Literal["update_model", "revert_text"]


class SetNotApplicable(_Cmd):
    type: Literal["set_not_applicable"] = "set_not_applicable"
    slot_id: str
    reason: str | None = None  # None → clear


class StartAdaptation(_Cmd):
    """Generate adaptation proposals for the target drug(s); replaces any unfinished adaptation."""

    type: Literal["start_adaptation"] = "start_adaptation"
    source_drug: str
    source_mechanism: str = ""
    target_drugs: list[DrugSpec]


class DecideAdaptationChange(_Cmd):
    type: Literal["decide_adaptation_change"] = "decide_adaptation_change"
    change_id: str
    decision: Literal["accepted", "rejected", "pending"]


class SetEvidenceRequirement(_Cmd):
    type: Literal["set_evidence_requirement"] = "set_evidence_requirement"
    requirement_id: str
    status: Literal["open", "linked", "waived"]
    source_id: str | None = None
    note: str = ""


class AnswerKeyInput(_Cmd):
    type: Literal["answer_key_input"] = "answer_key_input"
    question_id: str
    value: Any


class ProposeText(_Cmd):
    """Attach a pending replacement to a block (AI revision, reviewer suggestion, tracked change)."""

    type: Literal["propose_text"] = "propose_text"
    block_id: str
    text: str
    origin: Literal["author", "ai", "suggestion"] = "author"
    instruction: str = ""


class ResolveProposal(_Cmd):
    """Accept replaces the block text with the proposal; discard leaves the original untouched."""

    type: Literal["resolve_proposal"] = "resolve_proposal"
    block_id: str
    accept: bool


Command = Annotated[
    SetField
    | AddEntity
    | RemoveEntity
    | UpsertBlock
    | DeleteBlock
    | SetBlockApproval
    | SetClaim
    | ResolveClaim
    | SetNotApplicable
    | StartAdaptation
    | DecideAdaptationChange
    | SetEvidenceRequirement
    | AnswerKeyInput
    | ProposeText
    | ResolveProposal,
    Field(discriminator="type"),
]


class CommandEnvelope(BaseModel):
    command: Command


# ----------------------------------------------------------------------------- apply


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _new_id(prefix: str) -> str:
    return f"{prefix}-{secrets.token_hex(3)}"


def _check_schema(model: dict[str, Any]) -> None:
    issues = validate_model(model, strict=False)
    if issues:
        first = issues[0]
        raise CommandError(f"schema: {first.path or '<root>'}: {first.message}")


def apply_command(state: DraftState, cmd: Command, *, actor: str) -> tuple[DraftState, str]:
    if cmd.base_revision != state.revision:
        raise ConflictError(f"base_revision {cmd.base_revision} != head {state.revision}")
    new = state.model_copy(deep=True)
    summary = _dispatch(new, cmd, actor)
    new.revision += 1
    _refresh_claims(new)
    return new, summary


def _dispatch(s: DraftState, cmd: Command, actor: str) -> str:
    if isinstance(cmd, SetField):
        try:
            old = get_path(s.model, cmd.path, None)
            if cmd.value is None:
                delete_path(s.model, cmd.path)
            else:
                set_path(s.model, cmd.path, cmd.value)
        except PathError as e:
            raise CommandError(str(e)) from e
        _check_schema(s.model)
        return f"Set {cmd.path}: {old!r} → {cmd.value!r}"

    if isinstance(cmd, AddEntity):
        ent = dict(cmd.entity)
        if "id" not in ent or "name" not in ent:
            raise CommandError("entity needs 'id' and 'name'")
        coll = s.model.setdefault(cmd.collection, [])
        if not isinstance(coll, list):
            raise CommandError(f"{cmd.collection} is not a collection")
        if any(x.get("id") == ent["id"] for x in coll if isinstance(x, dict)):
            raise CommandError(f"{cmd.collection} already has id '{ent['id']}'")
        coll.append(ent)
        _check_schema(s.model)
        return f"Added {cmd.collection[:-1]} '{ent['name']}' ({ent['id']})"

    if isinstance(cmd, RemoveEntity):
        coll = s.model.get(cmd.collection)
        if not isinstance(coll, list):
            raise CommandError(f"{cmd.collection} is not a collection")
        before = len(coll)
        coll[:] = [x for x in coll if not (isinstance(x, dict) and x.get("id") == cmd.entity_id)]
        if len(coll) == before:
            raise CommandError(f"{cmd.collection} has no '{cmd.entity_id}'")
        if not coll:
            del s.model[cmd.collection]
        return f"Removed {cmd.collection[:-1]} '{cmd.entity_id}'"

    if isinstance(cmd, UpsertBlock):
        if cmd.block_id is None:
            siblings = [b for b in s.blocks if b.subsection_id == cmd.subsection_id]
            order = cmd.order if cmd.order is not None else (max((b.order for b in siblings), default=-1) + 1)
            b = Block(
                id=_new_id("b"),
                section_id=cmd.section_id,
                subsection_id=cmd.subsection_id,
                order=order,
                kind=cmd.kind,
                text=cmd.text,
                provenance=cmd.provenance,
                updated_by=actor,
                updated_at=_now(),
            )
            s.blocks.append(b)
            return f"Added block in {cmd.subsection_id}"
        b = _block(s, cmd.block_id)
        changed = b.text != cmd.text
        b.text, b.kind, b.updated_by, b.updated_at = cmd.text, cmd.kind, actor, _now()
        if cmd.order is not None:
            b.order = cmd.order
        # Editing approved text demotes it to unreviewed: approval is of a specific wording.
        if changed and b.approval == "approved":
            b.approval = "unreviewed"
        return f"Edited block {b.id} in {b.subsection_id}"

    if isinstance(cmd, DeleteBlock):
        _block(s, cmd.block_id)
        s.blocks = [b for b in s.blocks if b.id != cmd.block_id]
        return f"Deleted block {cmd.block_id}"

    if isinstance(cmd, SetBlockApproval):
        b = _block(s, cmd.block_id)
        b.approval = cmd.approval
        return f"Block {b.id} marked {cmd.approval}"

    if isinstance(cmd, SetClaim):
        b = _block(s, cmd.block_id)
        if cmd.remove:
            b.claims = [c for c in b.claims if c.id != cmd.claim_id]
            return f"Unbound claim on block {b.id}"
        if cmd.claim_id:
            for c in b.claims:
                if c.id == cmd.claim_id:
                    c.path, c.value, c.text = cmd.path, cmd.value, cmd.text
                    return f"Rebound claim {c.id} → {cmd.path}"
            raise CommandError(f"no claim {cmd.claim_id}")
        b.claims.append(Claim(id=_new_id("c"), path=cmd.path, value=cmd.value, text=cmd.text))
        return f"Bound “{cmd.text or cmd.value}” → {cmd.path}"

    if isinstance(cmd, ResolveClaim):
        b = _block(s, cmd.block_id)
        found = next((x for x in b.claims if x.id == cmd.claim_id), None)
        if found is None:
            raise CommandError(f"no claim {cmd.claim_id}")
        c = found
        if cmd.resolution == "update_model":
            try:
                set_path(s.model, c.path, c.value)
            except PathError as e:
                raise CommandError(str(e)) from e
            _check_schema(s.model)
            return f"Updated model {c.path} to {c.value!r} from text"
        model_value = get_path(s.model, c.path, None)
        if model_value is None:
            raise CommandError("model has no value to revert to")
        # Keep the phrase's wording ("Week 12" → "Week 16"); fall back to the bare value.
        old_phrase = c.text or str(c.value)
        new_phrase = (
            old_phrase.replace(str(c.value), str(model_value)) if str(c.value) in old_phrase else str(model_value)
        )
        if old_phrase in b.text:
            b.text = b.text.replace(old_phrase, new_phrase, 1)
        c.text, c.value = new_phrase, model_value
        b.updated_by, b.updated_at = actor, _now()
        if b.approval == "approved":
            b.approval = "unreviewed"
        return f"Reverted text to model value {model_value!r} for {c.path}"

    if isinstance(cmd, SetNotApplicable):
        if cmd.reason:
            s.not_applicable[cmd.slot_id] = cmd.reason
            return f"Marked {cmd.slot_id} not applicable: {cmd.reason}"
        s.not_applicable.pop(cmd.slot_id, None)
        return f"Cleared not-applicable on {cmd.slot_id}"

    if isinstance(cmd, StartAdaptation):
        try:
            s.adaptation = adapt.build_adaptation(
                s,
                source_drug=cmd.source_drug,
                source_mechanism=cmd.source_mechanism,
                targets=cmd.target_drugs,
                actor=actor,
                now=_now(),
            )
        except ValueError as e:
            raise CommandError(str(e)) from e
        names = ", ".join(d.name for d in cmd.target_drugs)
        return f"Started adaptation {cmd.source_drug} → {names}: {len(s.adaptation.changes)} proposed changes"

    if isinstance(cmd, DecideAdaptationChange):
        try:
            summary = adapt.apply_decision(s, cmd.change_id, cmd.decision, actor=actor, now=_now())
        except KeyError as e:
            raise CommandError(str(e)) from e
        _check_schema(s.model)
        return summary

    if isinstance(cmd, SetEvidenceRequirement):
        if s.adaptation is None:
            raise CommandError("no adaptation in progress")
        try:
            r = s.adaptation.requirement(cmd.requirement_id)
        except KeyError as e:
            raise CommandError(str(e)) from e
        r.status, r.source_id, r.note = cmd.status, cmd.source_id, cmd.note
        return f"Evidence requirement '{r.label}' marked {cmd.status}"

    if isinstance(cmd, AnswerKeyInput):
        try:
            written, sections = key_inputs.answer(s, cmd.question_id, cmd.value, actor=actor, now=_now())
        except (KeyError, PathError, ValueError) as e:
            raise CommandError(str(e)) from e
        _check_schema(s.model)
        return f"Key input {cmd.question_id} = {cmd.value!r} → {len(written)} fields; review {', '.join(sections)}"

    if isinstance(cmd, ProposeText):
        b = _block(s, cmd.block_id)
        b.proposal = Proposal(
            text=cmd.text,
            origin=cmd.origin,
            instruction=cmd.instruction,
            factual_changes=factual_changes(b.text, cmd.text, [c.model_dump() for c in b.claims]),
            proposed_by=actor,
            proposed_at=_now(),
        )
        return f"Proposed {cmd.origin} revision for block {b.id}"

    if isinstance(cmd, ResolveProposal):
        b = _block(s, cmd.block_id)
        if b.proposal is None:
            raise CommandError(f"block {b.id} has no pending proposal")
        p = b.proposal
        b.proposal = None
        if not cmd.accept:
            return f"Discarded {p.origin} revision for block {b.id}"
        b.text, b.updated_by, b.updated_at = p.text, actor, _now()
        b.provenance = "generated" if p.origin == "ai" else b.provenance
        if b.approval == "approved":
            b.approval = "unreviewed"
        return f"Accepted {p.origin} revision for block {b.id}"

    raise CommandError(f"unknown command {type(cmd).__name__}")  # pragma: no cover


def _block(s: DraftState, block_id: str) -> Block:
    try:
        return s.block(block_id)
    except KeyError as e:
        raise CommandError(f"no block {block_id}") from e


def _refresh_claims(s: DraftState) -> None:
    for b in s.blocks:
        if not b.claims:
            continue
        fresh = check_claims(s.model, [c.model_dump() for c in b.claims])
        b.claims = [Claim(**{k: v for k, v in f.items() if k in Claim.model_fields}) for f in fresh]
