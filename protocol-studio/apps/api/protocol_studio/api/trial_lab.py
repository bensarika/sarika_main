"""Trial Lab: sample size, allocation sensitivity and endpoint exploration.

    POST /api/trial-lab/sample-size          binary or continuous two-arm superiority
    GET  /api/trial-lab/profiles             editable efficacy-profile scenarios (synthetic defaults)
    POST /api/trial-lab/explore              rank endpoint × timepoint rows for a scenario set

All arithmetic lives in ``ps_stats``; this module only validates input shapes
and labels provenance. Default profile values are *synthetic planning
assumptions* (the design package's example) until an observed results source is
linked from Evidence; the response says so on every row.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from protocol_studio.auth.session import current_user
from ps_stats import (
    BinaryInputs,
    ContinuousInputs,
    EndpointScenario,
    allocation_sensitivity,
    binary_power,
    binary_sample_size,
    continuous_sample_size,
    explore_endpoints,
)

router = APIRouter(prefix="/api/trial-lab", tags=["trial-lab"], dependencies=[Depends(current_user)])


class SampleSizeRequest(BaseModel):
    variable_type: Literal["binary", "continuous"] = "binary"
    p_active: float | None = None
    p_control: float | None = None
    difference: float | None = None
    sd: float | None = None
    alpha: float = 0.05
    sidedness: Literal["one_sided", "two_sided"] = "two_sided"
    power: float = 0.9
    ratio: float = 1.0
    evaluable_fraction: float = Field(default=0.9, description="1 - expected non-evaluability")
    sensitivity_ratios: list[float] = Field(default_factory=lambda: [1.0, 2.0, 3.0])


@router.post("/sample-size")
def sample_size(body: SampleSizeRequest) -> dict[str, Any]:
    try:
        if body.variable_type == "binary":
            if body.p_active is None or body.p_control is None:
                raise ValueError("p_active and p_control are required for a binary endpoint")
            binary = BinaryInputs(
                body.p_active,
                body.p_control,
                body.alpha,
                body.sidedness,
                body.power,
                body.ratio,
                body.evaluable_fraction,
            )
            inp: BinaryInputs | ContinuousInputs = binary
            primary = binary_sample_size(binary)
            curve = [
                {"control_evaluable": n, "power": binary_power(binary, n)}
                for n in range(
                    max(5, primary.control_evaluable // 3),
                    primary.control_evaluable * 2,
                    max(1, primary.control_evaluable // 12),
                )
            ]
        else:
            if body.difference is None or body.sd is None:
                raise ValueError("difference and sd are required for a continuous endpoint")
            inp = ContinuousInputs(
                body.difference, body.sd, body.alpha, body.sidedness, body.power, body.ratio, body.evaluable_fraction
            )
            primary = continuous_sample_size(inp)
            curve = []
        sens = allocation_sensitivity(inp, tuple(body.sensitivity_ratios))
    except ValueError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e)) from e
    return {
        "result": primary.as_dict(),
        "sensitivity": [r.as_dict() for r in sens],
        "power_curve": curve,
        "assumptions": [
            "Independent parallel groups; single unadjusted comparison.",
            f"{'Two' if body.sidedness == 'two_sided' else 'One'}-sided alpha {body.alpha:g}; power {body.power:.0%}.",
            f"Non-evaluability inflation {1 - body.evaluable_fraction:.0%}, applied to the control arm and carried through the allocation ratio.",
            "Exact methods, covariate adjustment, multiplicity, interim analyses and the estimand's rescue strategy can change the number.",
        ],
    }


# ----------------------------------------------------------------------------- profiles / explorer

_PROFILE_ROWS: list[dict[str, Any]] = [
    {
        "endpoint_id": "easi90",
        "endpoint_label": "EASI-90",
        "timepoint_label": "Week 16",
        "variable_type": "binary",
        "p_active": 0.60,
        "p_control": 0.25,
        "comparability_notes": [
            "Responder threshold on EASI percent reduction",
            "Population and rescue strategy must match the comparator source",
        ],
    },
    {
        "endpoint_id": "easi_pct_change",
        "endpoint_label": "EASI percent change from baseline",
        "timepoint_label": "Week 16",
        "variable_type": "continuous",
        "difference": -20,
        "sd": 30,
        "comparability_notes": [
            "Percent change, not absolute change",
            "SD depends on baseline severity and analysis model",
        ],
    },
    {
        "endpoint_id": "easi90_w12",
        "endpoint_label": "EASI-90",
        "timepoint_label": "Week 12",
        "variable_type": "binary",
        "p_active": 0.50,
        "p_control": 0.20,
        "comparability_notes": ["Earlier timepoint; fewer sources report Week 12"],
    },
    {
        "endpoint_id": "nrs4",
        "endpoint_label": "NRS-4 (≥4-point itch improvement)",
        "timepoint_label": "Week 16",
        "variable_type": "binary",
        "p_active": 0.70,
        "p_control": 0.40,
        "comparability_notes": ["Eligible subset: baseline NRS ≥ 4", "Scale version and aggregation must be specified"],
    },
    {
        "endpoint_id": "easi75",
        "endpoint_label": "EASI-75",
        "timepoint_label": "Week 16",
        "variable_type": "binary",
        "p_active": 0.75,
        "p_control": 0.50,
        "comparability_notes": ["Most commonly reported responder endpoint"],
    },
]

PROFILES: dict[str, dict[str, Any]] = {
    "jak_like": {
        "id": "jak_like",
        "label": "JAK-Like Efficacy",
        "description": "Editable planning profile approximating oral JAK-inhibitor-like response against an active antibody comparator. Synthetic; not an inference about any new molecule.",
        "comparator": "Active comparator",
        "rows": _PROFILE_ROWS,
    },
    "placebo_controlled": {
        "id": "placebo_controlled",
        "label": "Antibody vs Placebo",
        "description": "Editable placebo-controlled planning profile using the Trial Calculator defaults.",
        "comparator": "Placebo",
        "rows": [
            {
                "endpoint_id": "easi75",
                "endpoint_label": "EASI-75",
                "timepoint_label": "Week 16",
                "variable_type": "binary",
                "p_active": 0.60,
                "p_control": 0.30,
                "comparability_notes": [],
            },
            {
                "endpoint_id": "easi90",
                "endpoint_label": "EASI-90",
                "timepoint_label": "Week 16",
                "variable_type": "binary",
                "p_active": 0.40,
                "p_control": 0.12,
                "comparability_notes": [],
            },
            {
                "endpoint_id": "iga01",
                "endpoint_label": "IGA 0/1 with ≥2-point improvement",
                "timepoint_label": "Week 16",
                "variable_type": "binary",
                "p_active": 0.40,
                "p_control": 0.15,
                "comparability_notes": ["Requires the 2-point improvement component"],
            },
            {
                "endpoint_id": "nrs4",
                "endpoint_label": "NRS-4 (≥4-point itch improvement)",
                "timepoint_label": "Week 16",
                "variable_type": "binary",
                "p_active": 0.50,
                "p_control": 0.20,
                "comparability_notes": ["Eligible subset: baseline NRS ≥ 4"],
            },
            {
                "endpoint_id": "easi_pct_change",
                "endpoint_label": "EASI percent change from baseline",
                "timepoint_label": "Week 16",
                "variable_type": "continuous",
                "difference": -30,
                "sd": 35,
                "comparability_notes": ["Percent change, not absolute change"],
            },
        ],
    },
}


@router.get("/profiles")
def profiles() -> list[dict[str, Any]]:
    return [{**p, "assumption_source": "synthetic"} for p in PROFILES.values()]


class ScenarioIn(BaseModel):
    endpoint_id: str
    endpoint_label: str
    timepoint_label: str
    variable_type: Literal["binary", "continuous"]
    p_active: float | None = None
    p_control: float | None = None
    difference: float | None = None
    sd: float | None = None
    assumption_source: str = "synthetic"
    comparability_notes: list[str] = Field(default_factory=list)


class ExploreRequest(BaseModel):
    scenarios: list[ScenarioIn] = Field(default_factory=list)
    profile: str | None = None  # shortcut: use a named profile's rows (scenarios, if given, are appended)
    alpha: float = 0.05
    sidedness: Literal["one_sided", "two_sided"] = "two_sided"
    power: float = 0.9
    evaluable_fraction: float = 0.9


@router.post("/explore")
def explore(body: ExploreRequest) -> dict[str, Any]:
    inputs = list(body.scenarios)
    if body.profile is not None:
        if body.profile not in PROFILES:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"unknown profile {body.profile}")
        inputs = [ScenarioIn(**row) for row in PROFILES[body.profile]["rows"]] + inputs
    if not inputs:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "provide scenarios or a profile")
    scenarios = [
        EndpointScenario(
            s.endpoint_id,
            s.endpoint_label,
            s.timepoint_label,
            s.variable_type,
            s.p_active,
            s.p_control,
            s.difference,
            s.sd,
            s.assumption_source,
            tuple(s.comparability_notes),
        )
        for s in inputs
    ]
    try:
        rows = explore_endpoints(
            scenarios,
            alpha=body.alpha,
            sidedness=body.sidedness,
            power=body.power,
            evaluable_fraction=body.evaluable_fraction,
        )
    except ValueError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e)) from e
    return {
        "rows": [r.as_dict() for r in rows],
        "caveats": [
            "Rows are independent, unadjusted calculations at 1:1 allocation.",
            "Multiplicity, joint endpoint behaviour, eligible-subset size and cross-trial comparability are not resolved here.",
            "The smallest total is not automatically the preferred confirmatory endpoint.",
        ],
    }
