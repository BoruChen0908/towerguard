"""
Economic Impact Module (N4) — prices a workforce trajectory into annual and
cumulative economic cost (masterplan §8).

The bridge from workforce to dollars is the CPC staffing gap (and the B1 flow
control it triggers): understaffing -> overtime + flow-control delays ->
airline/passenger cost. Pure functions over WorkforceState trajectories; no
dependency on the scenario engine (the __main__ demo wires them together).

================================================================================
PROVENANCE & DECISIONS — N4
================================================================================
Two cost channels, both anchored to documented §8 figures (see calibration D17):
  - Delay/cancellation = $33B/yr NAS delay cost (FAA/Nextor 2019) x a controller-
    attributable cost MULTIPLE. The multiple scales with the CPC staffing gap vs
    the FAA target: 5% at the current gap (~0.124) -> 61% at a shutdown-level gap
    (~0.25, the 2025 ~10% shed), extrapolated above, capped at the 3x COLLAPSE
    CEILING (~$99B/yr; the gap-driven natural peak, still below the A4A-implied
    range). Can exceed 1.0: collapse stacks cancellations + lost demand on top.
  - Overtime cost scales with the flow-control-relieved gap, anchored at $200M
    (FY2024) for the current gap.

Decisions:
  - Only CONTROLLER-ATTRIBUTABLE cost is charged (conservative): the baseline
    non-staffing delay is not blamed on the staffing decision.
  - Cost accrues over the PROJECTED years (the initial FY2025 state is the
    starting point and is not charged).
  - The do_nothing-minus-plan cumulative gap is the "cost of doing nothing".
  - The 3x ceiling replaces the old 1x cap, which suppressed collapse cost and
    made "delaying further" look free in the timing comparator (see #7 / D17).
    The cost-of-delay CURVE (~$70B/yr, roughly linear) is insensitive to the
    ceiling above ~2x. Numbers/sources: D17.

OBSERVED BEHAVIOR (cumulative FY2026-2036, loops on, 3x ceiling — model output)
  accelerated   $ 23B   full staffing -> gap ~0 -> only the 5% baseline cost.
  current_plan  $157B   FAA's plan.
  baseline      $215B   status quo costs ~$58B MORE than the plan.
  disruption    $231B   one FY2027 shutdown adds ~$74B vs the un-shocked plan.
  do_nothing    $523B   most expensive — and the ONLY scenario that collapses
                        past the old 1x threshold, so only its cost moved when
                        the cap rose from 1x to 3x.
  Cost of doing nothing: ~$366B (vs current_plan) ... ~$500B (vs accelerated).
  Net cost of DELAY (current_plan): ~$70B per year, roughly linear
  (70/139/206/271 for start 2027/28/29/30 vs 2026), robust to the ceiling above ~2x.
  CAVEATS: do_nothing's total inherits the illustrative R1 collapse depth (not
  calibrated). Lead with the per-year ~$70B (defensible) over the $523B total;
  present with Monte Carlo bands (N3) and the safety leg (N5), not as a lone $.
================================================================================
"""

from dataclasses import dataclass

from models import calibration as cal
from models.workforce_sd import LoopParams, WorkforceState, feedback_factors


@dataclass(frozen=True)
class EconomicCost:
    """Annual economic cost attributable to controller staffing, by channel."""

    year: int
    overtime_cost: float
    delay_cost: float

    @property
    def total(self) -> float:
        return self.overtime_cost + self.delay_cost


def controller_cost_multiple(gap: float) -> float:
    """Controller-attributable cost as a MULTIPLE of the $33B NAS delay bill, as
    a function of the CPC staffing gap (vs the FAA target). Linear through the
    two documented anchors (5% at the current gap, 61% at the shutdown gap),
    extrapolated above, floored at the normal share, capped at the collapse
    ceiling (3x, D17). Can exceed 1.0: deep collapse stacks cancellations and
    lost demand on top of normal-ops delays."""
    slope = (cal.CONTROLLER_DELAY_SHARE_SHUTDOWN - cal.CONTROLLER_DELAY_SHARE_NORMAL) / (
        cal.SHUTDOWN_STAFFING_GAP - cal.CURRENT_STAFFING_GAP
    )
    multiple = cal.CONTROLLER_DELAY_SHARE_NORMAL + slope * (gap - cal.CURRENT_STAFFING_GAP)
    return max(cal.CONTROLLER_DELAY_SHARE_NORMAL, min(multiple, cal.COLLAPSE_COST_CEILING))


def annual_cost(state: WorkforceState, loop: LoopParams | None = None) -> EconomicCost:
    """Economic cost for one year, derived from the workforce state (D17)."""
    factors = feedback_factors(state, loop if loop is not None else LoopParams())
    gap = max(0.0, 1.0 - factors.staffing_ratio)
    relieved_gap = max(0.0, gap - factors.flow_control_fraction)

    overtime = cal.OVERTIME_COST_FY2024 * (relieved_gap / cal.CURRENT_STAFFING_GAP)
    delay = cal.ANNUAL_DELAY_COST * controller_cost_multiple(gap)
    return EconomicCost(year=state.year, overtime_cost=overtime, delay_cost=delay)


def scenario_costs(
    trajectory: list[WorkforceState], loop: LoopParams | None = None
) -> list[EconomicCost]:
    """Per-year cost over the projected years (skips the initial FY2025 state)."""
    return [annual_cost(state, loop) for state in trajectory[1:]]


def cumulative_cost(
    trajectory: list[WorkforceState], loop: LoopParams | None = None
) -> float:
    """Total controller-attributable economic cost over the horizon."""
    return sum(cost.total for cost in scenario_costs(trajectory, loop))


def cost_of_doing_nothing(
    do_nothing: list[WorkforceState],
    reference: list[WorkforceState],
    loop: LoopParams | None = None,
) -> float:
    """Cumulative cost of the do-nothing path minus a reference (intervention)
    path — the headline 'cost of doing nothing' in dollars."""
    return cumulative_cost(do_nothing, loop) - cumulative_cost(reference, loop)


def net_cost_of_delay(
    late: list[WorkforceState],
    early: list[WorkforceState],
    loop: LoopParams | None = None,
) -> float:
    """Extra cumulative cost of intervening late vs early (§10.2) — the price of
    waiting. Positive and (because of the R1 spiral) growing with the delay."""
    return cumulative_cost(late, loop) - cumulative_cost(early, loop)


if __name__ == "__main__":  # pragma: no cover — acceptance demo
    from models.scenario_engine import (
        SCENARIOS,
        SCENARIOS_BY_ID,
        run_all,
        timing_comparison,
    )

    results = run_all()
    print("Cumulative controller-attributable economic cost (FY2026-2036):")
    cumulative = {}
    for scenario in SCENARIOS:
        total = cumulative_cost(results[scenario.id], scenario.loop)
        cumulative[scenario.id] = total
        print(f"  {scenario.id:<13} ${total / 1e9:>7.1f}B")

    gap_vs_plan = cumulative["do_nothing"] - cumulative["current_plan"]
    gap_vs_accel = cumulative["do_nothing"] - cumulative["accelerated"]
    print(
        f"\nCost of doing nothing (do_nothing - current_plan): ${gap_vs_plan / 1e9:.1f}B"
        f"\nCost of doing nothing (do_nothing - accelerated):  ${gap_vs_accel / 1e9:.1f}B"
    )

    print("\nNet cost of DELAYING the Current Plan (vs starting in 2026):")
    timing = timing_comparison(SCENARIOS_BY_ID["current_plan"])
    early = timing[min(timing)]
    for start_year in sorted(timing):
        traj = timing[start_year]
        delay_cost = net_cost_of_delay(traj, early, LoopParams())
        print(
            f"  start {start_year}: FY{traj[-1].year} total={traj[-1].total_controllers:>7.0f}"
            f"   net cost of delay = ${delay_cost / 1e9:>6.1f}B"
        )
