"""Finding: the single output type of every rule."""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


class Severity(StrEnum):
    ERROR = "error"  # blocks version freeze
    WARNING = "warning"
    INCOMPLETE = "incomplete"  # feeds completion; not a defect
    INFO = "info"
    CANDIDATE = "candidate"  # cross-view / semantic: a human accepts or dismisses


@dataclass
class Finding:
    rule_id: str  # "R01" … or "CL01" for claim checks
    severity: Severity
    message: str
    targets: list[str] = field(default_factory=list)  # dotted model paths or block ids
    section_id: str | None = None
    explanation: str = ""
    suggested_fix: str | None = None
    needs_adjudication: bool = False
    revision: int | None = None  # set by the caller; findings from older revisions are stale
    data: dict[str, Any] = field(default_factory=dict)

    @property
    def key(self) -> str:
        """Stable identity across re-runs so adjudications survive a recompute."""
        raw = f"{self.rule_id}|{'|'.join(sorted(self.targets))}|{self.message}"
        return hashlib.sha1(raw.encode()).hexdigest()[:16]

    def as_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["severity"] = str(self.severity)
        d["key"] = self.key
        return d
