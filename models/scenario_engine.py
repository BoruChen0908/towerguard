"""
Scenario Engine (N2) — runs the workforce model under the five policy scenarios
(masterplan §10.1) and returns their trajectories.

Scenarios differ by their hiring schedule plus per-scenario flow overrides
(certification speed, retention, academy washout) and, for disruption, a
one-time shock. They reuse models/workforce_sd.step() unchanged — this module
only orchestrates per-year parameters; the pipeline mechanics live in N1.

================================================================================
PROVENANCE & DECISIONS — N2
================================================================================
Five scenarios (§10.1). The masterplan's "Baseline" and "Current Plan" were
nearly identical (both = FAA CWP trajectory); resolved here by splitting them:
  - baseline      status quo: hiring stays at the FY2025 actual (~2,028/yr),
                  no efficiency gains. "No new effort."
  - do_nothing    hiring collapses to the FY2021 COVID low (~500/yr).
  - current_plan  FAA CWP 2026-2028 as announced: hiring ramp 2,200 -> 2,400.
  - accelerated   max push: higher hiring + TSS-faster certification (-27% cert
                  time) + better retention + lower academy washout (CTI).
  - disruption    current_plan hit by a 2025-style shutdown shock (one-time
                  ~450 trainee loss + a hiring dip) in FY2027.

Decisions:
  - All scenarios run loops on (the real mode).
  - hiring is a callable year -> intake so flat / ramped / shocked schedules
    share one interface; non-hiring overrides ride on a per-scenario FlowParams.
  - Cost is NOT produced here — economic pricing is N4. This module returns the
    workforce curves only.
  - Numbers / sources: calibration D16.

OBSERVED BEHAVIOR (FY2036 endpoints, loops on — model output, not input)
  do_nothing    total 3,273  (%NATCA 22)  — collapses; the R1 burnout spiral
                turns a hiring freeze into a runaway. THE "cost of doing nothing"
                headline. CAVEAT: collapse DEPTH depends on the illustrative R1
                coefficients (not yet calibrated) — quote the shape, not 3,273.
  baseline      total 13,490 (%NATCA 92)  — treads water near today's level.
  disruption    total 14,682 (%NATCA 100) — the FY2027 shock digs a trough
                (~12,000 in FY2028) then recovers, landing ~500 short of the
                un-shocked plan: a shock costs ~1 year of progress.
  current_plan  total 15,223 (%NATCA 104) — FAA's plan slowly closes the gap.
  accelerated   total 18,627 (%NATCA 127) — overshoots; constant max hiring with
                no taper, so read it as an upper-bound bookend, not a forecast.
  Ordering holds (do_nothing lowest, accelerated highest), and all five share the
  FY2025 start (13,164).
================================================================================
"""

from collections.abc import Callable
from dataclasses import dataclass, replace

from models import calibration as cal
from models.workforce_sd import (
    FlowParams,
    LoopParams,
    WorkforceState,
    initial_state,
    step,
)


@dataclass(frozen=True)
class Scenario:
    """A policy scenario: a hiring schedule + flow overrides (+ optional shock)."""

    id: str
    label: str
    description: str
    hiring: Callable[[int], float]              # fiscal year -> academy intake
    flow: FlowParams                            # non-hiring flow params
    loop: LoopParams | None
    shock: Callable[[int, WorkforceState], WorkforceState] | None = None


# --- hiring schedules ------------------------------------------------------


def _current_plan_hiring(year: int) -> float:
    """FAA CWP ramp: 2,200 (<=FY2026) -> 2,300 (FY2027) -> 2,400 (FY2028+)."""
    if year <= 2026:
        return cal.HIRING_TARGET_FY2026
    if year == 2027:
        return cal.HIRING_TARGET_FY2027
    return cal.HIRING_TARGET_FY2028


def _disruption_hiring(year: int) -> float:
    """current_plan ramp, but hiring dips in the shutdown year."""
    if year == cal.DISRUPTION_SHOCK_YEAR:
        return cal.SHUTDOWN_HIRING_DIP
    return _current_plan_hiring(year)


def _disruption_shock(year: int, state: WorkforceState) -> WorkforceState:
    """One-time developmental loss in the shutdown year (2025 replay)."""
    if year == cal.DISRUPTION_SHOCK_YEAR:
        return replace(
            state,
            developmental=max(0.0, state.developmental - cal.SHUTDOWN_TRAINEE_LOSS),
        )
    return state


# --- the five scenarios ----------------------------------------------------

SCENARIOS: tuple[Scenario, ...] = (
    Scenario(
        id="baseline",
        label="Baseline (status quo)",
        description="Hiring stays at the FY2025 actual (~2,028/yr), no new effort.",
        hiring=lambda _year: cal.BASELINE_HIRING,
        flow=FlowParams(),
        loop=LoopParams(),
    ),
    Scenario(
        id="do_nothing",
        label="Do Nothing",
        description="Hiring collapses to the FY2021 COVID low (~500/yr).",
        hiring=lambda _year: cal.DO_NOTHING_HIRING,
        flow=FlowParams(),
        loop=LoopParams(),
    ),
    Scenario(
        id="current_plan",
        label="Current Plan (FAA CWP)",
        description="FAA CWP 2026-2028 hiring ramp 2,200 -> 2,300 -> 2,400.",
        hiring=_current_plan_hiring,
        flow=FlowParams(),
        loop=LoopParams(),
    ),
    Scenario(
        id="accelerated",
        label="Accelerated",
        description="Max hiring + TSS-faster certification + retention + CTI.",
        hiring=lambda _year: cal.ACCELERATED_HIRING,
        flow=FlowParams(
            certification_rate=cal.CERTIFICATION_RATE_TSS,
            cpc_attrition_rate=cal.CPC_ATTRITION_RATE * cal.ACCELERATED_RETENTION_FACTOR,
            academy_grad_rate=cal.ACADEMY_GRAD_RATE_CTI,
        ),
        loop=LoopParams(),
    ),
    Scenario(
        id="disruption",
        label="Disruption (shutdown shock)",
        description="Current Plan hit by a 2025-style shutdown in FY2027.",
        hiring=_disruption_hiring,
        flow=FlowParams(),
        loop=LoopParams(),
        shock=_disruption_shock,
    ),
)

SCENARIOS_BY_ID: dict[str, Scenario] = {s.id: s for s in SCENARIOS}


def run_scenario(
    scenario: Scenario,
    years: int = cal.SCENARIO_HORIZON_YEARS,
    start: WorkforceState | None = None,
) -> list[WorkforceState]:
    """Run one scenario for ``years`` annual steps from the FY2025 initial state.

    Returns the initial state followed by one state per year (length years + 1).
    """
    state = start if start is not None else initial_state()
    trajectory = [state]
    for _ in range(years):
        target_year = state.year + 1
        params = replace(scenario.flow, hiring=scenario.hiring(target_year))
        state = step(state, params, scenario.loop)
        if scenario.shock is not None:
            state = scenario.shock(target_year, state)
        trajectory.append(state)
    return trajectory


def run_all(
    years: int = cal.SCENARIO_HORIZON_YEARS,
) -> dict[str, list[WorkforceState]]:
    """Run all five scenarios. Returns {scenario_id: trajectory}."""
    return {s.id: run_scenario(s, years) for s in SCENARIOS}


# --- intervention timing comparator (N2 timing, §10.2) ---------------------


def run_delayed_intervention(
    intervention: Scenario,
    start_year: int,
    before: Scenario | None = None,
    years: int = cal.SCENARIO_HORIZON_YEARS,
    start: WorkforceState | None = None,
) -> list[WorkforceState]:
    """Follow ``before`` (default: do_nothing) until ``start_year``, then switch
    to ``intervention`` from that year on — i.e. "we delayed acting until Y".

    Each year's hiring AND flow params come from whichever scenario is active,
    so an intervention with faster certification / better retention only kicks in
    once it starts.
    """
    before = before if before is not None else SCENARIOS_BY_ID["do_nothing"]
    state = start if start is not None else initial_state()
    trajectory = [state]
    for _ in range(years):
        target_year = state.year + 1
        active = intervention if target_year >= start_year else before
        params = replace(active.flow, hiring=active.hiring(target_year))
        state = step(state, params, active.loop)
        if active.shock is not None:
            state = active.shock(target_year, state)
        trajectory.append(state)
    return trajectory


def timing_comparison(
    intervention: Scenario,
    start_years: tuple[int, ...] = cal.INTERVENTION_START_YEARS,
    before: Scenario | None = None,
    years: int = cal.SCENARIO_HORIZON_YEARS,
) -> dict[int, list[WorkforceState]]:
    """Trajectory for intervening at each candidate start year. {start_year: traj}."""
    return {
        start_year: run_delayed_intervention(intervention, start_year, before, years)
        for start_year in start_years
    }


def staffing_pct(state: WorkforceState, target: float) -> float:
    """Total controllers as a fraction of a staffing target (§10.3 uses 0.85)."""
    return state.total_controllers / target if target > 0 else 0.0


if __name__ == "__main__":  # pragma: no cover — acceptance demo (§6 Day 1)
    results = run_all()
    print("Total controllers by scenario (loops on):")
    print(f"{'FY':>6}" + "".join(f"{s.id:>13}" for s in SCENARIOS))
    for i in range(len(results["baseline"])):
        row = f"{results['baseline'][i].year:>6}"
        for s in SCENARIOS:
            row += f"{results[s.id][i].total_controllers:>13.0f}"
        print(row)
    print(
        f"\nFY{results['baseline'][-1].year} staffing vs FAA target "
        f"({cal.TARGET_FAA}) / NATCA target ({cal.TARGET_NATCA}):"
    )
    for s in SCENARIOS:
        end = results[s.id][-1]
        print(
            f"  {s.id:<13} total={end.total_controllers:>7.0f}  "
            f"cpc={end.cpc:>7.0f}  "
            f"%FAA={100 * staffing_pct(end, cal.TARGET_FAA):>5.0f}  "
            f"%NATCA={100 * staffing_pct(end, cal.TARGET_NATCA):>5.0f}"
        )
