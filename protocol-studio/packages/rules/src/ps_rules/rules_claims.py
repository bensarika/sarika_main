"""Claim checks: narrative text that asserts a model value.

A *claim* (docs/01_architecture.md §6.3) is stored on a block:

    {"id": "c1", "block_id": "b-12", "path": "endpoints[easi75].time.offset.value",
     "value": 16, "text": "Week 16", "state": "checked"}

``check_claims`` recomputes the state of every claim against the current model:

    checked     value == model value
    mismatch    both present but differ            -> CL01 error (Update model / Revert text)
    unbound     the entity/container the path names does not exist   -> CL02 warning
    unsupported the entity exists but the field is missing or empty   -> CL02 warning

Claims are never auto-repaired; the two fixes are explicit commands.
"""

from __future__ import annotations

from typing import Any

from ps_model.paths import PathError, get_path
from ps_rules.finding import Finding, Severity
from ps_rules.registry import RuleContext, rule

_MISSING = object()


def _norm(v: Any) -> Any:
    """Loose comparison: '16' == 16, 'Week 16' is not normalised (that is the claim's job)."""
    if isinstance(v, str):
        s = v.strip()
        try:
            return float(s)
        except ValueError:
            return s.casefold()
    if isinstance(v, bool):
        return v
    if isinstance(v, int | float):
        return float(v)
    return v


def _parent_exists(model: dict[str, Any], path: str) -> bool:
    parent = path.rsplit(".", 1)[0] if "." in path else ""
    if not parent:
        return True
    try:
        return get_path(model, parent, _MISSING) is not _MISSING
    except PathError:
        return False


def claim_state(model: dict[str, Any], claim: dict[str, Any]) -> str:
    path = claim["path"]
    try:
        actual = get_path(model, path, _MISSING)
    except PathError:
        return "unsupported" if _parent_exists(model, path) else "unbound"
    if actual is _MISSING:
        return "unsupported" if _parent_exists(model, path) else "unbound"
    if actual is None or actual == "" or actual == []:
        return "unsupported"
    return "checked" if _norm(actual) == _norm(claim.get("value")) else "mismatch"


def check_claims(model: dict[str, Any], claims: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return claims with a fresh ``state`` and the current ``model_value``."""
    out: list[dict[str, Any]] = []
    for c in claims:
        st = claim_state(model, c)
        mv = get_path(model, c["path"], None) if st in {"checked", "mismatch"} else None
        out.append({**c, "state": st, "model_value": mv})
    return out


@rule("CL01")
def claim_mismatch(model: dict[str, Any], ctx: RuleContext) -> list[Finding]:
    out: list[Finding] = []
    for c in check_claims(model, ctx.claims):
        if c["state"] == "mismatch":
            out.append(
                Finding(
                    "CL01",
                    Severity.ERROR,
                    f"Text says “{c.get('text', c.get('value'))}” but the model has {c['model_value']!r} at {c['path']}",
                    targets=[c["path"], c.get("block_id", "")],
                    explanation="Narrative and model disagree. Choose “Update model” (the text is right) or “Revert text” (the model is right).",
                    suggested_fix="Update model | Revert text",
                    data={
                        "claim_id": c.get("id"),
                        "block_id": c.get("block_id"),
                        "claim_value": c.get("value"),
                        "model_value": c["model_value"],
                    },
                    needs_adjudication=True,
                )
            )
    return out


@rule("CL02")
def claim_unbound(model: dict[str, Any], ctx: RuleContext) -> list[Finding]:
    out: list[Finding] = []
    for c in check_claims(model, ctx.claims):
        if c["state"] in {"unbound", "unsupported"}:
            out.append(
                Finding(
                    "CL02",
                    Severity.WARNING,
                    f"Text “{c.get('text', c.get('value'))}” claims {c['path']}, which is {c['state']} in the model",
                    targets=[c["path"], c.get("block_id", "")],
                    explanation="Uninterpreted text does not pass validation by default.",
                    data={"claim_id": c.get("id"), "block_id": c.get("block_id")},
                )
            )
    return out
