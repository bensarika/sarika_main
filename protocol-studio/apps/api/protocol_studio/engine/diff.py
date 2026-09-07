"""Deterministic diff between two draft states (a frozen version vs head, or two versions).

Two layers, because the two halves of a draft change differently:

* **Model diff** — the canonical JSON is flattened to dotted paths (the same
  path syntax commands use, e.g. ``endpoints[easi75].time.offset.value``) and
  compared leaf by leaf. Entities are matched by their stable ``id`` so a
  reordered list does not read as a rewrite.
* **Narrative diff** — blocks are matched by ``id``; changed blocks carry a
  word-level opcode list (``equal`` / ``insert`` / ``delete``) that the UI can
  render as tracked changes without re-diffing client-side.

Everything here is pure and side-effect free; it never touches the database.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any

from protocol_studio.engine.state import Block, DraftState

_WORD_RE = re.compile(r"\s+|[^\s]+")


# ----------------------------------------------------------------------------- model


def flatten(model: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    """Flatten to ``{dotted_path: leaf}``; lists of ``{"id": …}`` entities become ``coll[id]`` segments."""
    out: dict[str, Any] = {}
    for key, value in model.items():
        path = f"{prefix}.{key}" if prefix else key
        _flatten_value(value, path, out)
    return out


def _flatten_value(value: Any, path: str, out: dict[str, Any]) -> None:
    if isinstance(value, dict):
        if not value:
            out[path] = {}
        for k, v in value.items():
            _flatten_value(v, f"{path}.{k}", out)
    elif isinstance(value, list):
        if not value:
            out[path] = []
            return
        if all(isinstance(v, dict) and isinstance(v.get("id"), str) for v in value):
            for v in value:
                _flatten_value(v, f"{path}[{v['id']}]", out)
        else:
            for i, v in enumerate(value):
                _flatten_value(v, f"{path}[{i}]", out)
    else:
        out[path] = value


def model_diff(old: dict[str, Any], new: dict[str, Any]) -> list[dict[str, Any]]:
    a, b = flatten(old), flatten(new)
    rows: list[dict[str, Any]] = []
    for path in sorted(set(a) | set(b)):
        if path in a and path not in b:
            rows.append({"path": path, "change": "removed", "old": a[path], "new": None})
        elif path in b and path not in a:
            rows.append({"path": path, "change": "added", "old": None, "new": b[path]})
        elif a[path] != b[path]:
            rows.append({"path": path, "change": "changed", "old": a[path], "new": b[path]})
    return rows


# ----------------------------------------------------------------------------- narrative


def word_ops(old: str, new: str) -> list[dict[str, str]]:
    """Word-level opcodes preserving whitespace tokens, merged into runs."""
    a, b = _WORD_RE.findall(old), _WORD_RE.findall(new)
    ops: list[dict[str, str]] = []

    def push(kind: str, text: str) -> None:
        if not text:
            return
        if ops and ops[-1]["op"] == kind:
            ops[-1]["text"] += text
        else:
            ops.append({"op": kind, "text": text})

    for tag, i1, i2, j1, j2 in SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag == "equal":
            push("equal", "".join(a[i1:i2]))
        else:
            push("delete", "".join(a[i1:i2]))
            push("insert", "".join(b[j1:j2]))
    return ops


def block_diff(old: list[Block], new: list[Block]) -> list[dict[str, Any]]:
    a, b = {x.id: x for x in old}, {x.id: x for x in new}
    rows: list[dict[str, Any]] = []
    for bid in list(a) + [bid for bid in b if bid not in a]:
        oa, nb = a.get(bid), b.get(bid)
        if oa is not None and nb is None:
            rows.append(_row(bid, oa, "removed", oa.text, ""))
        elif oa is None and nb is not None:
            rows.append(_row(bid, nb, "added", "", nb.text))
        elif oa is not None and nb is not None:
            if oa.text != nb.text:
                rows.append({**_row(bid, nb, "changed", oa.text, nb.text), "ops": word_ops(oa.text, nb.text)})
            elif oa.approval != nb.approval:
                rows.append({**_row(bid, nb, "approval", oa.text, nb.text), "approval": [oa.approval, nb.approval]})
    return rows


def _row(bid: str, b: Block, change: str, old: str, new: str) -> dict[str, Any]:
    return {
        "block_id": bid,
        "section_id": b.section_id,
        "subsection_id": b.subsection_id,
        "change": change,
        "old": old,
        "new": new,
    }


# ----------------------------------------------------------------------------- state


def diff_states(old: DraftState, new: DraftState) -> dict[str, Any]:
    model = model_diff(old.model, new.model)
    blocks = block_diff(old.blocks, new.blocks)
    na_old, na_new = old.not_applicable, new.not_applicable
    not_applicable = [
        {"slot_id": k, "change": "removed" if k not in na_new else "added" if k not in na_old else "changed"}
        for k in sorted(set(na_old) | set(na_new))
        if na_old.get(k) != na_new.get(k)
    ]
    sections = sorted({str(r["section_id"]) for r in blocks})
    return {
        "from_revision": old.revision,
        "to_revision": new.revision,
        "model": model,
        "blocks": blocks,
        "not_applicable": not_applicable,
        "summary": {
            "model_changes": len(model),
            "blocks_added": sum(r["change"] == "added" for r in blocks),
            "blocks_removed": sum(r["change"] == "removed" for r in blocks),
            "blocks_changed": sum(r["change"] == "changed" for r in blocks),
            "approval_changes": sum(r["change"] == "approval" for r in blocks),
            "sections_touched": sections,
        },
    }
