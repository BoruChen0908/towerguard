"""Tests for the safety risk module (N5)."""

from dataclasses import replace

import pytest

from models import calibration as cal
from models.safety_risk import annual_risk_index, safety_metrics
from models.scenario_engine import SCENARIOS_BY_ID, run_scenario
from models.workforce_sd import LoopParams, initial_state


def test_risk_is_bounded_multiplier() -> None:
    """Relative multiplier stays within [baseline, ceiling] (D20)."""
    for cpc in (14000, 11000, 8000, 4000, 1000):
        risk = annual_risk_index(replace(initial_state(), cpc=cpc), LoopParams())
        assert cal.RISK_BASELINE_MULTIPLIER <= risk <= cal.RISK_CEILING


def test_well_staffed_is_baseline() -> None:
    """At/above the FAA target: rested -> 1.0x baseline risk."""
    risk = annual_risk_index(replace(initial_state(), cpc=13000), LoopParams())
    assert risk == pytest.approx(cal.RISK_BASELINE_MULTIPLIER)


def test_understaffing_raises_risk() -> None:
    healthy = annual_risk_index(replace(initial_state(), cpc=12000), LoopParams())
    starved = annual_risk_index(replace(initial_state(), cpc=5000), LoopParams())
    assert starved > healthy


def test_deep_collapse_approaches_ceiling() -> None:
    """Severe understaffing drives risk toward the 5x ceiling (but not past it)."""
    risk = annual_risk_index(replace(initial_state(), cpc=1000), LoopParams())
    assert risk > 3.0
    assert risk <= cal.RISK_CEILING


def test_months_below_floor_ordering() -> None:
    """do_nothing spends far more time below the 85% floor than accelerated."""
    do_nothing = safety_metrics(run_scenario(SCENARIOS_BY_ID["do_nothing"]))
    accelerated = safety_metrics(run_scenario(SCENARIOS_BY_ID["accelerated"]))
    assert do_nothing.months_below_85pct > accelerated.months_below_85pct


def test_metrics_cover_projected_years() -> None:
    metrics = safety_metrics(run_scenario(SCENARIOS_BY_ID["baseline"]))
    assert len(metrics.risk_index_by_year) == cal.SCENARIO_HORIZON_YEARS
    assert metrics.months_below_85pct % 12 == 0
