"""ps_stats — deterministic planning arithmetic for the Trial Lab.

Everything here is pure and reproducible: no randomness, no network, no model
calls. The routines implement the *documented* closed-form approximations the
design package uses (docs/05-planning-example.md in the design handoff), so
the UI numbers can be checked by hand:

* two independent proportions, normal approximation, no continuity correction;
* two independent means, known common SD;
* non-evaluability inflation applied to the control arm and propagated through
  the allocation ratio so the ratio is preserved exactly.

Exact/simulation methods can differ; the API surfaces the method text with
every result so a reader always knows which formula produced a number.
"""

from ps_stats.explorer import EndpointScenario, ExplorerRow, explore_endpoints
from ps_stats.sample_size import (
    BinaryInputs,
    ContinuousInputs,
    SampleSizeResult,
    allocation_sensitivity,
    binary_power,
    binary_sample_size,
    continuous_sample_size,
    z_alpha,
    z_power,
)

__all__ = [
    "BinaryInputs",
    "ContinuousInputs",
    "EndpointScenario",
    "ExplorerRow",
    "SampleSizeResult",
    "allocation_sensitivity",
    "binary_power",
    "binary_sample_size",
    "continuous_sample_size",
    "explore_endpoints",
    "z_alpha",
    "z_power",
]
