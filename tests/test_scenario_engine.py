"""Tests for the scenario engine (N2)."""

import pytest

from models import calibration as cal
from models.scenario_engine import (
    SCENARIOS_BY_ID,
    run_all,
    run_delayed_intervention,
    run_scenario,
    staffing_pct,
    timing_comparison,
)


def test_run_all_has_five_scenarios() -> None:
    results = run_all()
    assert set(results) == {
        "baseline",
        "do_nothing",
        "current_plan",
        "accelerated",
        "disruption",
    }


def test_all_trajectories_share_initial_state() -> None:
    for traj in run_all().values():
        assert traj[0].total_controllers == pytest.approx(
            cal.TOTAL_CONTROLLERS_FY2025
        )


def test_trajectory_length_and_horizon() -> None:
    traj = run_scenario(SCENARIOS_BY_ID["baseline"])
    assert len(traj) == cal.SCENARIO_HORIZON_YEARS + 1
    assert traj[-1].year == 2025 + cal.SCENARIO_HORIZON_YEARS


def test_do_nothing_is_worst_accelerated_is_best() -> None:
    end = {k: v[-1].total_controllers for k, v in run_all().items()}
    assert end["do_nothing"] == min(end.values())
    assert end["accelerated"] == max(end.values())


def test_disruption_is_below_current_plan() -> None:
    """The shutdown shock leaves disruption short of the un-shocked plan."""
    results = run_all()
    assert (
        results["disruption"][-1].total_controllers
        < results["current_plan"][-1].total_controllers
    )


def test_staffing_pct() -> None:
    state = run_scenario(SCENARIOS_BY_ID["baseline"])[0]
    assert staffing_pct(state, cal.TARGET_FAA) == pytest.approx(
        cal.TOTAL_CONTROLLERS_FY2025 / cal.TARGET_FAA
    )


def test_delayed_intervention_at_first_year_equals_full_run() -> None:
    """Intervening in 2026 (the first projected year) == running it outright."""
    plan = SCENARIOS_BY_ID["current_plan"]
    delayed = run_delayed_intervention(plan, start_year=2026)
    full = run_scenario(plan)
    assert [s.cpc for s in delayed] == [s.cpc for s in full]


def test_later_intervention_leaves_fewer_controllers() -> None:
    """Delaying the same intervention ends with a smaller workforce."""
    plan = SCENARIOS_BY_ID["current_plan"]
    early = run_delayed_intervention(plan, start_year=2026)
    late = run_delayed_intervention(plan, start_year=2030)
    assert late[-1].total_controllers < early[-1].total_controllers


def test_timing_comparison_covers_all_start_years() -> None:
    timing = timing_comparison(SCENARIOS_BY_ID["current_plan"])
    assert set(timing) == set(cal.INTERVENTION_START_YEARS)
