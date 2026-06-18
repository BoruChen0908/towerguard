"""Tests for the deterministic workforce stock-flow skeleton (N1, stage 1a).

These validate structure, immutability, and calibration anchoring — not the
final dynamics (feedback loops arrive in 1b, precise calibration in 1c).
"""

from dataclasses import replace

import pytest

from models import calibration as cal
from models.workforce_sd import (
    FlowParams,
    LoopParams,
    WorkforceState,
    feedback_factors,
    initial_state,
    simulate,
    step,
)


def test_initial_total_matches_gao_fy2025() -> None:
    """Initial total controllers must equal the GAO FY2025 figure (13,164)."""
    state = initial_state()
    assert state.total_controllers == pytest.approx(cal.TOTAL_CONTROLLERS_FY2025)


def test_total_is_derived_dev_plus_cpc() -> None:
    """total_controllers = developmental + cpc (calibration D1)."""
    state = WorkforceState(
        year=2025, applicants=0, academy=0, developmental=2164, cpc=11000
    )
    assert state.total_controllers == 13164


def test_step_does_not_mutate_input() -> None:
    """step() returns a new state and never mutates its input (global rule)."""
    state = initial_state()
    before = (state.applicants, state.academy, state.developmental, state.cpc)
    step(state, FlowParams())
    after = (state.applicants, state.academy, state.developmental, state.cpc)
    assert before == after


def test_stocks_stay_non_negative() -> None:
    trajectory = simulate(initial_state(), FlowParams(), years=10)
    for state in trajectory:
        assert state.applicants >= 0
        assert state.academy >= 0
        assert state.developmental >= 0
        assert state.cpc >= 0


def test_simulate_length_and_years() -> None:
    trajectory = simulate(initial_state(), FlowParams(), years=10)
    assert len(trajectory) == 11
    assert trajectory[0].year == 2025
    assert trajectory[-1].year == 2035


def test_historical_backcast_reproduces_gao() -> None:
    """1c calibration (§12.3): running FY2015->FY2025 with the implied historical
    hiring reproduces the GAO total (13,164) AND the CPC/dev composition.

    Doubles as a regression guard: if a flow rate changes and breaks this,
    the model needs re-calibration.
    """
    cpc15 = cal.TOTAL_CONTROLLERS_FY2015 * cal.HISTORICAL_CPC_TOTAL_RATIO
    dev15 = cal.TOTAL_CONTROLLERS_FY2015 - cpc15
    start = WorkforceState(
        year=2015,
        applicants=cal.INITIAL_APPLICANTS,
        academy=cal.IMPLIED_HISTORICAL_HIRING,
        developmental=dev15,
        cpc=cpc15,
    )
    params = FlowParams(
        hiring=cal.IMPLIED_HISTORICAL_HIRING,
        cpc_attrition_rate=cal.CPC_ATTRITION_RATE_HISTORICAL,  # historical regime (D14)
    )
    end = simulate(start, params, years=10, loop=LoopParams())[-1]
    assert end.total_controllers == pytest.approx(
        cal.TOTAL_CONTROLLERS_FY2025, rel=0.02
    )
    assert end.cpc == pytest.approx(cal.CPC_FY2025, rel=0.05)


def test_ojt_washout_reduces_certification() -> None:
    """OJT washout (pass rate < 1.0) sends fewer developmentals to CPC (D13)."""
    state = initial_state()
    no_washout = step(state, FlowParams(ojt_pass_rate=1.0))
    with_washout = step(state, FlowParams(ojt_pass_rate=cal.OJT_PASS_RATE))
    assert with_washout.cpc < no_washout.cpc


def test_baseline_stays_in_target_band() -> None:
    """After 1d calibration the baseline no longer explodes (~19k); it lands near
    the staffing-target band (cal D14/D15)."""
    end = simulate(initial_state(), FlowParams(), years=10, loop=LoopParams())[-1]
    assert cal.TARGET_FAA * 0.9 <= end.total_controllers <= cal.TARGET_NATCA * 1.1


def test_developmental_converges_toward_apr2026_snapshot() -> None:
    """Sanity: developmental should drift toward ~4,000 (FAA/Reuters Apr 2026),
    a figure deliberately NOT used as an initial value (calibration D1)."""
    trajectory = simulate(initial_state(), FlowParams(), years=10)
    end_dev = trajectory[-1].developmental
    assert 3000 <= end_dev <= 5000


# --- Stage 1b: feedback loops ---------------------------------------------


def test_loop_off_matches_1a_skeleton() -> None:
    """Regression: simulate(loop=None) must equal the deterministic skeleton."""
    skeleton = simulate(initial_state(), FlowParams(), years=10)
    explicit_none = simulate(initial_state(), FlowParams(), years=10, loop=None)
    assert [s.cpc for s in skeleton] == [s.cpc for s in explicit_none]


def test_feedback_neutral_when_fully_staffed() -> None:
    """At/above target the gap is zero -> no fatigue, no shedding (loop-off identity)."""
    state = replace(initial_state(), cpc=13000)  # above FAA target 12,563
    factors = feedback_factors(state, LoopParams())
    assert factors.effectiveness == pytest.approx(1.0)
    assert factors.attrition_multiplier == pytest.approx(1.0)
    assert factors.flow_control_fraction == 0.0


def test_understaffing_raises_attrition_multiplier() -> None:
    factors = feedback_factors(replace(initial_state(), cpc=9000), LoopParams())
    assert factors.attrition_multiplier > 1.0


def test_attrition_nonlinear_below_fatigue_threshold() -> None:
    """Below 0.77 the attrition response exceeds the above-threshold linear form."""
    loop = LoopParams()
    severe = feedback_factors(replace(initial_state(), cpc=6000), loop)
    assert severe.effectiveness < loop.fatigue_threshold
    linear_equiv = 1.0 + loop.attrition_slope * (1.0 - severe.effectiveness)
    assert severe.attrition_multiplier > linear_equiv


def test_flow_control_engages_below_floor() -> None:
    factors = feedback_factors(replace(initial_state(), cpc=8000), LoopParams())
    assert factors.flow_control_fraction > 0.0


def test_loops_worsen_understaffed_trajectory() -> None:
    """With low hiring, enabling the loops yields fewer CPCs than the skeleton."""
    params = FlowParams(hiring=500)  # do-nothing-style hiring
    skeleton = simulate(initial_state(), params, years=10)
    looped = simulate(initial_state(), params, years=10, loop=LoopParams())
    assert looped[-1].cpc < skeleton[-1].cpc


def test_effective_attrition_capped() -> None:
    """Even in deep collapse, one year cannot remove more than the cap (D10)."""
    params = FlowParams(hiring=0)
    looped = simulate(initial_state(), params, years=15, loop=LoopParams())
    for state in looped:
        assert state.cpc >= 0
