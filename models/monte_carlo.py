"""
Monte Carlo wrapper (N3) — runs a scenario many times with the uncertain
parameters sampled, and reports P10/P50/P90 bands per year.

Why this exists (masterplan §3, §11): ISPOR good practice and Brief 6 both
require reporting distributions, not point estimates. The bands become the fan
charts in N6 and the `bands` field of the scenario-results JSON.

================================================================================
PROVENANCE & DECISIONS — N3 (see calibration D19)
================================================================================
  - Sampled: multiplicative factors on EACH scenario's base flow / loop params
    (preserves scenario differences). Widest ranges on the least-calibrated R1
    loop coefficients — our least certain assumptions drive the most output
    uncertainty, which is the honest result.
  - Pure Python (no numpy): seeded random sampling + a small percentile helper.
  - Reuses scenario_engine.run_scenario unchanged; only perturbs the params.

OBSERVED BEHAVIOR (model output, not input)
  Bands widen over time as the illustrative coefficients propagate. do_nothing
  FY2035 CPC spans P10 ~229 to P90 ~5,727 (median ~3,631) — a huge spread that
  honestly says "we are confident it collapses, not how far". This wide fan is
  the point: the least-calibrated assumptions (R1) drive the most uncertainty.
================================================================================
"""

import random
from dataclasses import dataclass, replace

from models import calibration as cal
from models.scenario_engine import Scenario, run_scenario


@dataclass(frozen=True)
class Band:
    """Per-year percentile band of a quantity across Monte Carlo samples."""

    year: int
    p10: float
    p50: float
    p90: float


def _percentile(sorted_values: list[float], p: float) -> float:
    """Linear-interpolated percentile (p in [0, 1]) of an ascending list."""
    if not sorted_values:
        return 0.0
    rank = (len(sorted_values) - 1) * p
    low = int(rank)
    high = min(low + 1, len(sorted_values) - 1)
    if low == high:
        return sorted_values[low]
    return sorted_values[low] + (sorted_values[high] - sorted_values[low]) * (rank - low)


def _sample_scenario(scenario: Scenario, rng: random.Random) -> Scenario:
    """Perturb a scenario's flow / loop params within the documented ranges."""
    flow = replace(
        scenario.flow,
        cpc_attrition_rate=scenario.flow.cpc_attrition_rate
        * rng.uniform(*cal.MC_ATTRITION_FACTOR),
        certification_rate=scenario.flow.certification_rate
        * rng.uniform(*cal.MC_CERT_FACTOR),
        ojt_pass_rate=min(
            1.0, scenario.flow.ojt_pass_rate * rng.uniform(*cal.MC_OJT_FACTOR)
        ),
    )
    loop = scenario.loop
    if loop is not None:
        loop = replace(
            loop,
            effectiveness_gap_sensitivity=loop.effectiveness_gap_sensitivity
            * rng.uniform(*cal.MC_R1_SENSITIVITY_FACTOR),
            attrition_amplify=loop.attrition_amplify
            * rng.uniform(*cal.MC_R1_AMPLIFY_FACTOR),
        )
    return replace(scenario, flow=flow, loop=loop)


def _bands_from_samples(
    years: list[int], columns: list[list[float]]
) -> list[Band]:
    """columns[i] = the sampled values for year i; return one Band per year."""
    bands = []
    for year, values in zip(years, columns):
        ordered = sorted(values)
        bands.append(
            Band(
                year=year,
                p10=_percentile(ordered, 0.10),
                p50=_percentile(ordered, 0.50),
                p90=_percentile(ordered, 0.90),
            )
        )
    return bands


def run_monte_carlo(
    scenario: Scenario,
    samples: int = cal.MC_SAMPLES,
    seed: int = cal.MC_SEED,
    years: int = cal.SCENARIO_HORIZON_YEARS,
) -> dict[str, list[Band]]:
    """Run ``samples`` perturbed runs of ``scenario``; return P10/P50/P90 bands
    per year for total controllers and CPCs. {"total": [...], "cpc": [...]}."""
    rng = random.Random(seed)
    deterministic = run_scenario(scenario, years)
    year_labels = [state.year for state in deterministic]

    total_cols: list[list[float]] = [[] for _ in year_labels]
    cpc_cols: list[list[float]] = [[] for _ in year_labels]
    for _ in range(samples):
        trajectory = run_scenario(_sample_scenario(scenario, rng), years)
        for i, state in enumerate(trajectory):
            total_cols[i].append(state.total_controllers)
            cpc_cols[i].append(state.cpc)

    return {
        "total": _bands_from_samples(year_labels, total_cols),
        "cpc": _bands_from_samples(year_labels, cpc_cols),
    }
