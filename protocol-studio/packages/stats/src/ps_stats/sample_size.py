"""Sample size for two-arm superiority comparisons.

Notation (control = placebo or active comparator, ``r`` = active:control ratio):

    pbar = (r*p1 + p0) / (r + 1)
    n0   = [ z_a * sqrt(pbar*(1-pbar)*(1 + 1/r)) + z_b * sqrt(p1*(1-p1)/r + p0*(1-p0)) ]^2 / (p1 - p0)^2
    n1   = r * n0

``n0`` is rounded *up* first, then ``n1 = r * n0`` so the allocation ratio is
exact. Enrollment inflates the control arm by ``ceil(n0 / evaluable_fraction)``
and again multiplies by ``r``. Inflation is a planning convenience for
non-evaluability, not a substitute for a missing-data strategy.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from statistics import NormalDist
from typing import Literal

Sidedness = Literal["one_sided", "two_sided"]

_N = NormalDist()


def z_alpha(alpha: float, sidedness: Sidedness) -> float:
    """Critical value for the type I error rate. Two-sided splits alpha across both tails."""
    if not 0 < alpha < 1:
        raise ValueError("alpha must be in (0, 1)")
    return _N.inv_cdf(1 - alpha / 2) if sidedness == "two_sided" else _N.inv_cdf(1 - alpha)


def z_power(power: float) -> float:
    if not 0 < power < 1:
        raise ValueError("power must be in (0, 1)")
    return _N.inv_cdf(power)


def _ceil_pos(x: float) -> int:
    # Guard against float noise turning 56.0000000001 into 57.
    return math.ceil(round(x, 9))


@dataclass(frozen=True)
class BinaryInputs:
    p_active: float
    p_control: float
    alpha: float = 0.05
    sidedness: Sidedness = "two_sided"
    power: float = 0.9
    ratio: float = 1.0  # active : control
    evaluable_fraction: float = 1.0  # e.g. 0.9 for 10% non-evaluability

    def validate(self) -> None:
        for name, p in (("p_active", self.p_active), ("p_control", self.p_control)):
            if not 0 < p < 1:
                raise ValueError(f"{name} must be in (0, 1)")
        if self.p_active == self.p_control:
            raise ValueError("response rates must differ for a superiority calculation")
        if self.ratio <= 0:
            raise ValueError("ratio must be positive")
        if not 0 < self.evaluable_fraction <= 1:
            raise ValueError("evaluable_fraction must be in (0, 1]")


@dataclass(frozen=True)
class ContinuousInputs:
    difference: float  # active minus control, in endpoint units
    sd: float  # common standard deviation
    alpha: float = 0.05
    sidedness: Sidedness = "two_sided"
    power: float = 0.9
    ratio: float = 1.0
    evaluable_fraction: float = 1.0

    def validate(self) -> None:
        if self.difference == 0:
            raise ValueError("difference must be non-zero")
        if self.sd <= 0:
            raise ValueError("sd must be positive")
        if self.ratio <= 0:
            raise ValueError("ratio must be positive")
        if not 0 < self.evaluable_fraction <= 1:
            raise ValueError("evaluable_fraction must be in (0, 1]")


@dataclass(frozen=True)
class SampleSizeResult:
    ratio: float
    active_evaluable: int
    control_evaluable: int
    active_enrolled: int
    control_enrolled: int
    z_alpha: float
    z_power: float
    method: str

    @property
    def total_evaluable(self) -> int:
        return self.active_evaluable + self.control_evaluable

    @property
    def total_enrolled(self) -> int:
        return self.active_enrolled + self.control_enrolled

    def as_dict(self) -> dict[str, float | int | str]:
        d: dict[str, float | int | str] = dict(asdict(self))
        d["total_evaluable"] = self.total_evaluable
        d["total_enrolled"] = self.total_enrolled
        return d


def _inflate(n_control: int, ratio: float, evaluable_fraction: float) -> tuple[int, int]:
    control_enrolled = _ceil_pos(n_control / evaluable_fraction)
    active_enrolled = _ceil_pos(control_enrolled * ratio)
    return active_enrolled, control_enrolled


def binary_sample_size(inp: BinaryInputs) -> SampleSizeResult:
    inp.validate()
    r = inp.ratio
    p1, p0 = inp.p_active, inp.p_control
    za, zb = z_alpha(inp.alpha, inp.sidedness), z_power(inp.power)
    pbar = (r * p1 + p0) / (r + 1)
    num = za * math.sqrt(pbar * (1 - pbar) * (1 + 1 / r)) + zb * math.sqrt(p1 * (1 - p1) / r + p0 * (1 - p0))
    n0 = _ceil_pos(num**2 / (p1 - p0) ** 2)
    n1 = _ceil_pos(n0 * r)
    a_enr, c_enr = _inflate(n0, r, inp.evaluable_fraction)
    return SampleSizeResult(
        ratio=r,
        active_evaluable=n1,
        control_evaluable=n0,
        active_enrolled=a_enr,
        control_enrolled=c_enr,
        z_alpha=za,
        z_power=zb,
        method=(
            "Two independent proportions; normal approximation to the difference in proportions "
            "(pooled variance under H0, unpooled under H1); no continuity correction; single unadjusted comparison."
        ),
    )


def continuous_sample_size(inp: ContinuousInputs) -> SampleSizeResult:
    inp.validate()
    r = inp.ratio
    za, zb = z_alpha(inp.alpha, inp.sidedness), z_power(inp.power)
    n0 = _ceil_pos((za + zb) ** 2 * inp.sd**2 * (1 + 1 / r) / inp.difference**2)
    n1 = _ceil_pos(n0 * r)
    a_enr, c_enr = _inflate(n0, r, inp.evaluable_fraction)
    return SampleSizeResult(
        ratio=r,
        active_evaluable=n1,
        control_evaluable=n0,
        active_enrolled=a_enr,
        control_enrolled=c_enr,
        z_alpha=za,
        z_power=zb,
        method=(
            "Two independent means with a common known SD; normal approximation; "
            "single unadjusted comparison. Baseline-adjusted (ANCOVA) designs need the baseline correlation."
        ),
    )


def binary_power(inp: BinaryInputs, n_control_evaluable: int) -> float:
    """Achieved power for a given evaluable control-arm size (active = ratio * control)."""
    inp.validate()
    r, p1, p0 = inp.ratio, inp.p_active, inp.p_control
    n0 = n_control_evaluable
    n1 = n0 * r
    za = z_alpha(inp.alpha, inp.sidedness)
    pbar = (r * p1 + p0) / (r + 1)
    se0 = math.sqrt(pbar * (1 - pbar) * (1 / n1 + 1 / n0))
    se1 = math.sqrt(p1 * (1 - p1) / n1 + p0 * (1 - p0) / n0)
    return _N.cdf((abs(p1 - p0) - za * se0) / se1)


def allocation_sensitivity(
    inp: BinaryInputs | ContinuousInputs, ratios: tuple[float, ...] = (1.0, 2.0, 3.0)
) -> list[SampleSizeResult]:
    """Same assumptions, several active:control ratios. Unequal allocation costs total enrollment."""
    out: list[SampleSizeResult] = []
    for r in ratios:
        if isinstance(inp, BinaryInputs):
            out.append(
                binary_sample_size(
                    BinaryInputs(
                        inp.p_active, inp.p_control, inp.alpha, inp.sidedness, inp.power, r, inp.evaluable_fraction
                    )
                )
            )
        else:
            out.append(
                continuous_sample_size(
                    ContinuousInputs(
                        inp.difference, inp.sd, inp.alpha, inp.sidedness, inp.power, r, inp.evaluable_fraction
                    )
                )
            )
    return out
