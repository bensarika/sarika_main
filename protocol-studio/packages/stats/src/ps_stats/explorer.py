"""Endpoint Explorer: rank candidate endpoint × timepoint rows by required size.

An *efficacy profile* ("JAK-like efficacy") is an editable planning scenario:
a set of assumed active-arm values against a comparator, per endpoint and
timepoint. It is never a property of the new molecule. The explorer applies the
same alpha / power / allocation / evaluability assumptions to every row and
returns rows sorted by total randomized, together with the comparability notes
(scale, absolute vs percent change, population, rescue handling) that make the
smallest number *not* automatically the right confirmatory choice.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from ps_stats.sample_size import (
    BinaryInputs,
    ContinuousInputs,
    Sidedness,
    binary_sample_size,
    continuous_sample_size,
)


@dataclass(frozen=True)
class EndpointScenario:
    endpoint_id: str
    endpoint_label: str
    timepoint_label: str  # "Week 16"
    variable_type: Literal["binary", "continuous"]
    # binary
    p_active: float | None = None
    p_control: float | None = None
    # continuous
    difference: float | None = None
    sd: float | None = None
    # provenance
    assumption_source: str = "synthetic"  # synthetic | observed:<source id> | edited
    comparability_notes: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ExplorerRow:
    scenario: EndpointScenario
    evaluable_per_arm: int
    total_randomized: int
    assumption_text: str
    method: str

    def as_dict(self) -> dict[str, object]:
        s = self.scenario
        return {
            "endpoint_id": s.endpoint_id,
            "endpoint_label": s.endpoint_label,
            "timepoint_label": s.timepoint_label,
            "variable_type": s.variable_type,
            "p_active": s.p_active,
            "p_control": s.p_control,
            "difference": s.difference,
            "sd": s.sd,
            "assumption_source": s.assumption_source,
            "comparability_notes": list(s.comparability_notes),
            "assumption_text": self.assumption_text,
            "evaluable_per_arm": self.evaluable_per_arm,
            "total_randomized": self.total_randomized,
            "method": self.method,
        }


def explore_endpoints(
    scenarios: list[EndpointScenario],
    *,
    alpha: float = 0.05,
    sidedness: Sidedness = "two_sided",
    power: float = 0.9,
    evaluable_fraction: float = 0.9,
) -> list[ExplorerRow]:
    """Equal allocation (r = 1) for every row so rows are comparable with each other."""
    rows: list[ExplorerRow] = []
    for s in scenarios:
        if s.variable_type == "binary":
            if s.p_active is None or s.p_control is None:
                raise ValueError(f"{s.endpoint_id}: binary scenario needs p_active and p_control")
            res = binary_sample_size(
                BinaryInputs(s.p_active, s.p_control, alpha, sidedness, power, 1.0, evaluable_fraction)
            )
            text = f"{s.p_active:.0%} vs {s.p_control:.0%}"
        else:
            if s.difference is None or s.sd is None:
                raise ValueError(f"{s.endpoint_id}: continuous scenario needs difference and sd")
            res = continuous_sample_size(
                ContinuousInputs(s.difference, s.sd, alpha, sidedness, power, 1.0, evaluable_fraction)
            )
            text = f"Difference {s.difference:g}; SD {s.sd:g}"
        rows.append(
            ExplorerRow(
                scenario=s,
                evaluable_per_arm=res.control_evaluable,
                total_randomized=res.total_enrolled,
                assumption_text=text,
                method=res.method,
            )
        )
    rows.sort(key=lambda r: (r.total_randomized, r.scenario.endpoint_label))
    return rows
