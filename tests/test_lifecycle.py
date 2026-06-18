"""Tests for the lifecycle/governance layer (N-lifecycle).

Guards the freshness-from-drift mapping (the light is computed, never hardcoded)
and the structured governance contract the frontend + Devpost fields consume.
"""

from models import calibration as cal
from models.lifecycle import (
    BYPASS_CONDITIONS,
    build_lifecycle,
    compute_freshness,
)
from models.validation import BacktestResult, run_backtest


def _fake_backtest(drift_pct: float) -> BacktestResult:
    return BacktestResult(
        window="test",
        points=[],
        mean_abs_cpc_error_pct=drift_pct,
        final_total_error_pct=drift_pct,
        drift_threshold_pct=cal.DRIFT_THRESHOLD_PCT,
        within_threshold=drift_pct <= cal.DRIFT_THRESHOLD_PCT,
        note="",
    )


def test_freshness_tiers() -> None:
    assert compute_freshness(_fake_backtest(3.0)).status == "green"
    assert compute_freshness(_fake_backtest(5.0)).status == "green"  # boundary
    assert compute_freshness(_fake_backtest(7.0)).status == "yellow"
    assert compute_freshness(_fake_backtest(10.0)).status == "yellow"  # boundary
    assert compute_freshness(_fake_backtest(12.0)).status == "red"


def test_freshness_is_not_hardcoded() -> None:
    # The real model currently sits in the yellow band (COVID-window drift ~8%);
    # if this ever reads a bare "green" without the drift backing it, the light
    # has been faked.
    report = build_lifecycle()
    f = report.freshness
    assert f.drift_pct == run_backtest().mean_abs_cpc_error_pct
    assert f.status in {"green", "yellow", "red"}
    assert f.status == "yellow"  # honest: the FY2020-2025 backtest diverges ~8%


def test_drift_detection_consistent() -> None:
    report = build_lifecycle()
    d = report.drift_detection
    assert d.triggered == (d.current_drift_pct > d.threshold_pct)


def test_five_bypass_conditions() -> None:
    assert len(BYPASS_CONDITIONS) == 5
    report = build_lifecycle()
    assert len(report.human_in_loop.bypass_conditions) == 5
    for b in report.human_in_loop.bypass_conditions:
        assert b.condition and b.why


def test_human_in_loop_complete() -> None:
    hil = build_lifecycle().human_in_loop
    assert hil.ai_informs and hil.human_decides and hil.two_review_cycle


def test_versioning_present() -> None:
    report = build_lifecycle()
    assert report.versioning
    assert report.versioning[0].version == "1.0"
    assert report.governance
