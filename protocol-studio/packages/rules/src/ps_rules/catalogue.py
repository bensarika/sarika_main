"""The rule catalogue (R01–R22) as shipped in ``reference/validation_rules.json``.

The catalogue is the source of truth for *classification*: whether a rule is
deterministic, conditional completeness, cross-view, semantic or evidence
review decides where it runs (inline vs worker) and what its default result
is. Implementations register against a catalogue id; the registry refuses an
unknown id so the docs and the code cannot drift apart silently.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache

from ps_model.schema import reference_dir


@dataclass(frozen=True)
class RuleSpec:
    id: str
    name: str
    check_type: str  # deterministic | conditional_completeness | cross_view | ...
    default_result: str  # error | incomplete | candidate_conflict | review_task
    applies_when: str
    check: str
    qualification: str

    @property
    def inline(self) -> bool:
        """Runs on every model change (deterministic / completeness) vs in the worker."""
        return self.check_type in {"deterministic", "conditional_completeness", "graph_traversal"}


@lru_cache(maxsize=1)
def catalogue() -> dict[str, RuleSpec]:
    with (reference_dir() / "validation_rules.json").open(encoding="utf-8") as fh:
        raw = json.load(fh)
    out: dict[str, RuleSpec] = {}
    for r in raw["rules"]:
        out[r["id"]] = RuleSpec(
            id=r["id"],
            name=r["name"],
            check_type=r["check_type"],
            default_result=r["default_result"],
            applies_when=r.get("applies_when", ""),
            check=r.get("check", ""),
            qualification=r.get("qualification", ""),
        )
    return out


@lru_cache(maxsize=1)
def expression_contract() -> dict[str, object]:
    with (reference_dir() / "validation_rules.json").open(encoding="utf-8") as fh:
        raw = json.load(fh)
    contract: dict[str, object] = raw["expression_contract"]
    return contract
