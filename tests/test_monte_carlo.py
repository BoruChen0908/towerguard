"""Tests for the Monte Carlo wrapper (N3)."""

import pytest

from models import calibration as cal
from models.monte_carlo import _percentile, run_monte_carlo
from models.scenario_engine import SCENARIOS_BY_ID, run_scenario


def test_percentile_interpolates() -> None:
    values = [0.0, 10.0, 20.0, 30.0, 40.0]
    assert _percentile(values, 0.0) == 0.0
    assert _percentile(values, 1.0) == 40.0
    assert _percentile(values, 0.5) == 20.0


def test_bands_are_ordered() -> None:
    bands = run_monte_carlo(SCENARIOS_BY_ID["do_nothing"], samples=100)
    for series in bands.values():
        for band in series:
            assert band.p10 <= band.p50 <= band.p90


def test_bands_cover_horizon() -> None:
    bands = run_monte_carlo(SCENARIOS_BY_ID["baseline"], samples=50)
    assert len(bands["total"]) == cal.SCENARIO_HORIZON_YEARS + 1
    assert bands["total"][0].year == 2025
    assert bands["total"][-1].year == 2036


def test_seed_is_reproducible() -> None:
    a = run_monte_carlo(SCENARIOS_BY_ID["current_plan"], samples=50, seed=7)
    b = run_monte_carlo(SCENARIOS_BY_ID["current_plan"], samples=50, seed=7)
    assert [band.p50 for band in a["cpc"]] == [band.p50 for band in b["cpc"]]


def test_median_brackets_deterministic_run() -> None:
    """The P50 band should sit near the deterministic (un-perturbed) trajectory."""
    scenario = SCENARIOS_BY_ID["current_plan"]
    bands = run_monte_carlo(scenario, samples=300)
    deterministic = run_scenario(scenario)
    final_det = deterministic[-1].total_controllers
    final_p10 = bands["total"][-1].p10
    final_p90 = bands["total"][-1].p90
    assert final_p10 <= final_det <= final_p90


def test_initial_year_has_no_spread() -> None:
    """FY2025 is the fixed initial state — identical across all samples."""
    bands = run_monte_carlo(SCENARIOS_BY_ID["do_nothing"], samples=50)
    first = bands["total"][0]
    assert first.p10 == pytest.approx(first.p90)
    assert first.p50 == pytest.approx(cal.TOTAL_CONTROLLERS_FY2025)
