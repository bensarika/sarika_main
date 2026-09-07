"""Deterministic factual-change detection between a block's text and a proposed rewrite.

Model-assisted rewriting is allowed to improve wording; it is *not* allowed to
silently change facts. Before a proposal is shown, this module diffs the two
texts on the dimensions the architecture names — quantities and units,
negation, modal strength (must/should/may), actors and bound claim phrases —
and lists every difference so the reviewer sees "changes 16 weeks → 12 weeks"
next to the Accept button. Nothing here calls a model.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

_QTY = re.compile(
    r"(?<![\w.])(\d+(?:\.\d+)?)\s*(%|mg/mL|mg|mL|kg|weeks?|days?|hours?|months?|years?|points?|percentage points?)?",
    re.IGNORECASE,
)
_NEGATION = re.compile(r"\b(not|no|never|neither|nor|without|prohibited|excluded|unless)\b", re.IGNORECASE)
_MODALS = {
    "must": 3,
    "shall": 3,
    "required": 3,
    "will": 2,
    "should": 2,
    "recommended": 2,
    "may": 1,
    "can": 1,
    "permitted": 1,
    "optional": 1,
    "discouraged": 1,
}
_MODAL_RE = re.compile(r"\b(" + "|".join(_MODALS) + r")\b", re.IGNORECASE)
_ACTORS = re.compile(
    r"\b(investigator|sponsor|participant|patient|subject|data monitoring committee|DMC|IRB|IEC|monitor|pharmacist|statistician)s?\b",
    re.IGNORECASE,
)


def _quantities(text: str) -> list[str]:
    out = []
    for m in _QTY.finditer(text):
        num, unit = m.group(1), (m.group(2) or "").lower()
        unit = re.sub(r"s$", "", unit) if unit not in {"%", "mg", "ml"} else unit
        out.append(f"{num}{(' ' + unit) if unit else ''}")
    return out


def _multiset_diff(a: list[str], b: list[str]) -> tuple[list[str], list[str]]:
    ca, cb = Counter(x.lower() for x in a), Counter(x.lower() for x in b)
    removed = sorted((ca - cb).elements())
    added = sorted((cb - ca).elements())
    return removed, added


def _modal_strength(text: str) -> int:
    hits = [_MODALS[m.lower()] for m in _MODAL_RE.findall(text)]
    return max(hits) if hits else 0


def factual_changes(original: str, proposed: str, claims: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return a list of ``{"kind", "detail", "severity"}`` entries; empty means wording-only."""
    out: list[dict[str, Any]] = []

    removed, added = _multiset_diff(_quantities(original), _quantities(proposed))
    if removed or added:
        out.append(
            {
                "kind": "quantity",
                "severity": "error",
                "detail": f"quantities changed: removed {removed or '—'}, added {added or '—'}",
                "removed": removed,
                "added": added,
            }
        )

    n_orig, n_prop = len(_NEGATION.findall(original)), len(_NEGATION.findall(proposed))
    if n_orig != n_prop:
        out.append({"kind": "negation", "severity": "error", "detail": f"negation count {n_orig} → {n_prop}"})

    s_orig, s_prop = _modal_strength(original), _modal_strength(proposed)
    if s_orig != s_prop:
        names = {0: "none", 1: "permissive (may)", 2: "advisory (should/will)", 3: "mandatory (must)"}
        out.append(
            {"kind": "modal", "severity": "warning", "detail": f"obligation strength {names[s_orig]} → {names[s_prop]}"}
        )

    a_rem, a_add = _multiset_diff(
        [m.lower() for m in _ACTORS.findall(original)], [m.lower() for m in _ACTORS.findall(proposed)]
    )
    if a_rem or a_add:
        out.append(
            {
                "kind": "actor",
                "severity": "warning",
                "detail": f"responsible actors changed: removed {a_rem or '—'}, added {a_add or '—'}",
            }
        )

    for c in claims:
        phrase = str(c.get("text") or c.get("value") or "")
        if phrase and phrase in original and phrase not in proposed:
            out.append(
                {
                    "kind": "claim",
                    "severity": "error",
                    "detail": f"bound phrase “{phrase}” ({c.get('path')}) no longer present",
                    "claim_id": c.get("id"),
                    "path": c.get("path"),
                }
            )
    return out
