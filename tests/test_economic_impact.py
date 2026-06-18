"""Tests for the economic impact module (N4)."""

from dataclasses import replace

import pytest

from models import calibration as cal
from models.economic_impact import (
    annual_cost,
    controller_cost_multiple,
    cost_of_doing_nothing,
    cumulative_cost,
    net_cost_of_delay,
)
from models.scenario_engine import (
    SCENARIOS_BY_ID,
    run_scenario,
    timing_comparison,
)
from models.workforce_sd import LoopParams, initial_state


def test_cost_multiple_anchors() -> None:
    """Multiple hits the documented anchors: 5% at the current gap, 61% at shutdown."""
    assert controller_cost_multiple(cal.CURRENT_STAFFING_GAP) == pytest.approx(
        cal.CONTROLLER_DELAY_SHARE_NORMAL
    )
    assert controller_cost_multiple(cal.SHUTDOWN_STAFFING_GAP) == pytest.approx(
        cal.CONTROLLER_DELAY_SHARE_SHUTDOWN
    )


def test_cost_multiple_floored_and_capped() -> None:
    assert controller_cost_multiple(0.0) == cal.CONTROLLER_DELAY_SHARE_NORMAL  # floor
    assert controller_cost_multiple(5.0) == cal.COLLAPSE_COST_CEILING  # 3x ceiling


def test_fully_staffed_costs_only_baseline_delay() -> None:
    """At/above the FAA target there is no gap: no overtime, floor delay share."""
    state = replace(initial_state(), cpc=13000)  # above FAA target 12,563
    cost = annual_cost(state, LoopParams())
    assert cost.overtime_cost == pytest.approx(0.0)
    assert cost.delay_cost == pytest.approx(
        cal.ANNUAL_DELAY_COST * cal.CONTROLLER_DELAY_SHARE_NORMAL
    )


def test_understaffing_costs_more() -> None:
    healthy = annual_cost(replace(initial_state(), cpc=12000), LoopParams())
    starved = annual_cost(replace(initial_state(), cpc=6000), LoopParams())
    assert starved.total > healthy.total


def test_cost_ordering_matches_scenarios() -> None:
    """Cumulative cost: accelerated cheapest, do_nothing most expensive."""
    costs = {
        sid: cumulative_cost(run_scenario(s), s.loop)
        for sid, s in SCENARIOS_BY_ID.items()
    }
    assert costs["accelerated"] == min(costs.values())
    assert costs["do_nothing"] == max(costs.values())


def test_cost_of_doing_nothing_is_positive() -> None:
    do_nothing = run_scenario(SCENARIOS_BY_ID["do_nothing"])
    plan = run_scenario(SCENARIOS_BY_ID["current_plan"])
    assert cost_of_doing_nothing(do_nothing, plan, LoopParams()) > 0


def test_net_cost_of_delay_grows_with_delay() -> None:
    """Delaying the same intervention costs more, and disproportionately so."""
    timing = timing_comparison(SCENARIOS_BY_ID["current_plan"])
    early = timing[2026]
    ncod = {sy: net_cost_of_delay(timing[sy], early, LoopParams()) for sy in timing}
    assert ncod[2026] == pytest.approx(0.0)
    assert ncod[2030] > ncod[2028] > ncod[2026]
