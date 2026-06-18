"""Contract-shape tests for the scenario-results JSON (the frontend interface).

Guards the contract KT builds against: required keys, index-aligned arrays,
JSON-serialisability. build_results runs Monte Carlo for all scenarios, so it is
built once per module.
"""

import json

import pytest

from models import calibration as cal
from models.scenario_results import build_results


@pytest.fixture(scope="module")
def results() -> dict:
    return build_results()


def test_top_level_keys(results: dict) -> None:
    assert set(results) == {
        "meta",
        "targets",
        "safety_context",
        "scenarios",
        "timing_comparator",
        "sensitivity",
        "assumptions",
        "policy_brief",
    }


def test_both_targets_present(results: dict) -> None:
    assert results["targets"] == {"faa": cal.TARGET_FAA, "natca": cal.TARGET_NATCA}


def test_five_scenarios(results: dict) -> None:
    ids = [s["id"] for s in results["scenarios"]]
    assert ids == ["baseline", "do_nothing", "current_plan", "accelerated", "disruption"]


def test_per_scenario_arrays_are_index_aligned(results: dict) -> None:
    for scenario in results["scenarios"]:
        n = len(scenario["years"])
        assert n == cal.SCENARIO_HORIZON_YEARS + 1
        for series in scenario["series"].values():
            assert len(series) == n
        assert len(scenario["bands"]["cpc_p10"]) == n
        assert len(scenario["bands"]["cpc_p90"]) == n
        assert len(scenario["costs"]["annual_cost_by_year"]) == n
        assert len(scenario["safety"]["risk_index"]) == n


def test_bands_bracket_each_other(results: dict) -> None:
    for scenario in results["scenarios"]:
        for p10, p90 in zip(scenario["bands"]["cpc_p10"], scenario["bands"]["cpc_p90"]):
            assert p10 <= p90


def test_timing_and_sensitivity_present(results: dict) -> None:
    assert results["timing_comparator"]["start_years"] == list(
        cal.INTERVENTION_START_YEARS
    )
    assert len(results["sensitivity"]) >= 3
    for entry in results["sensitivity"]:
        assert {"parameter", "baseline", "low_impact", "high_impact"} <= set(entry)


def test_assumptions_have_source_and_confidence(results: dict) -> None:
    assert results["assumptions"]
    for entry in results["assumptions"]:
        assert {"parameter", "value", "source", "confidence"} <= set(entry)


def test_is_json_serialisable(results: dict) -> None:
    json.dumps(results)  # must not raise
