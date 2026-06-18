"""Tests for the model-validation layer (N-eval).

These guard the validation CONTRACT and the structural invariants — NOT a target
accuracy for the out-of-sample backtest. The backtest legitimately exceeds the
drift threshold (the COVID window is a structural break); asserting it "passes"
would defeat the purpose. We assert: the extreme-condition invariants hold, the
in-sample back-cast reproduces tightly, and the report shape is stable.
"""

from models import calibration as cal
from models.validation import (
    build_validation,
    extreme_condition_tests,
    reproduction_checks,
    run_backtest,
)


def test_backtest_covers_full_window() -> None:
    result = run_backtest()
    years = [p.year for p in result.points]
    assert years == sorted(cal.HISTORICAL_ACTUALS)
    assert result.window == "FY2020-FY2025"


def test_backtest_seed_year_has_zero_error() -> None:
    result = run_backtest()
    seed = result.points[0]
    assert seed.year == 2020
    # FY2020 is the seed: predicted == actual, excluded from the mean.
    assert seed.predicted_cpc == seed.actual_cpc


def test_backtest_error_is_computed_and_sane() -> None:
    result = run_backtest()
    assert result.mean_abs_cpc_error_pct >= 0.0
    # Sanity bound only — not a target. The honest value is ~8% (COVID window).
    assert result.mean_abs_cpc_error_pct < 25.0
    # within_threshold must agree with the comparison it claims to make.
    assert result.within_threshold == (
        result.mean_abs_cpc_error_pct <= result.drift_threshold_pct
    )


def test_extreme_conditions_all_pass() -> None:
    # These are structural invariants of the pipeline, not data fits.
    tests = extreme_condition_tests()
    assert len(tests) == 3
    for t in tests:
        assert t.passed, f"extreme-condition invariant failed: {t.name} — {t.observed}"


def test_backcast_reproduces_history_tightly() -> None:
    checks = {c.name: c for c in reproduction_checks()}
    # The in-sample total and the semi-independent composition both reproduce.
    assert checks["backcast_fy2015_to_2025_total"].abs_error_pct < 1.0
    assert checks["backcast_fy2025_cpc_composition"].abs_error_pct < 2.0


def test_build_validation_is_complete() -> None:
    report = build_validation()
    assert report.backtest.points
    assert len(report.extreme_conditions) == 3
    assert len(report.reproduction) == 3
    assert report.face_validity
    assert report.method_note
