"""Numbers cross-checked against the design package's planning example (docs/05-planning-example.md)."""

import pytest

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

BASE = BinaryInputs(p_active=0.60, p_control=0.30, alpha=0.05, sidedness="two_sided", power=0.90)


@pytest.mark.parametrize(
    ("ratio", "active_ev", "control_ev", "active_enr", "control_enr"),
    [(1.0, 56, 56, 63, 63), (2.0, 84, 42, 94, 47), (3.0, 111, 37, 126, 42)],
)
def test_binary_matches_planning_example(
    ratio: float, active_ev: int, control_ev: int, active_enr: int, control_enr: int
) -> None:
    res = binary_sample_size(BinaryInputs(0.60, 0.30, 0.05, "two_sided", 0.90, ratio, 0.90))
    assert (res.active_evaluable, res.control_evaluable) == (active_ev, control_ev)
    assert (res.active_enrolled, res.control_enrolled) == (active_enr, control_enr)


def test_allocation_sensitivity_totals() -> None:
    rows = allocation_sensitivity(BinaryInputs(0.60, 0.30, 0.05, "two_sided", 0.90, 1.0, 0.90))
    assert [r.total_enrolled for r in rows] == [126, 141, 168]
    assert [r.ratio for r in rows] == [1.0, 2.0, 3.0]


def test_continuous_matches_planning_example() -> None:
    res = continuous_sample_size(ContinuousInputs(-20, 30, 0.05, "two_sided", 0.90, 1.0, 0.90))
    assert res.control_evaluable == 48
    assert res.total_enrolled == 108


def test_one_sided_needs_fewer() -> None:
    two = binary_sample_size(BASE)
    one = binary_sample_size(BinaryInputs(0.60, 0.30, 0.05, "one_sided", 0.90))
    assert one.total_evaluable < two.total_evaluable


def test_power_roundtrip() -> None:
    res = binary_sample_size(BASE)
    assert binary_power(BASE, res.control_evaluable) >= 0.90
    assert binary_power(BASE, res.control_evaluable - 5) < 0.90


@pytest.mark.parametrize(
    "bad",
    [
        BinaryInputs(0.5, 0.5),
        BinaryInputs(1.2, 0.3),
        BinaryInputs(0.6, 0.3, ratio=0),
        BinaryInputs(0.6, 0.3, evaluable_fraction=0),
        BinaryInputs(0.6, 0.3, alpha=1.5),
    ],
)
def test_binary_rejects_invalid(bad: BinaryInputs) -> None:
    with pytest.raises(ValueError):
        binary_sample_size(bad)


def test_explorer_matches_planning_example() -> None:
    scenarios = [
        EndpointScenario("easi90", "EASI-90", "Week 16", "binary", p_active=0.60, p_control=0.25),
        EndpointScenario(
            "easi_pct", "EASI percent change from baseline", "Week 16", "continuous", difference=-20, sd=30
        ),
        EndpointScenario("easi90_w12", "EASI-90", "Week 12", "binary", p_active=0.50, p_control=0.20),
        EndpointScenario("nrs4", "NRS-4", "Week 16", "binary", p_active=0.70, p_control=0.40),
        EndpointScenario("easi75", "EASI-75", "Week 16", "binary", p_active=0.75, p_control=0.50),
    ]
    rows = explore_endpoints(scenarios, evaluable_fraction=0.90)
    got = [(r.scenario.endpoint_id, r.evaluable_per_arm, r.total_randomized) for r in rows]
    assert got == [
        ("easi90", 40, 90),
        ("easi_pct", 48, 108),
        ("easi90_w12", 52, 116),
        ("nrs4", 56, 126),
        ("easi75", 77, 172),
    ]


def test_explorer_rejects_incomplete_scenario() -> None:
    with pytest.raises(ValueError):
        explore_endpoints([EndpointScenario("x", "X", "Week 1", "binary", p_active=0.5)])
