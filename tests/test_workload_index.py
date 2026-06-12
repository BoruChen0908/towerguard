"""Tests for modules/workload_index.py."""

import config
from modules.workload_index import _score_to_tier, compute, compute_unavailable


# ---------------------------------------------------------------------------
# Score → Tier boundary values (§2a) — same thresholds as traffic_density
# ---------------------------------------------------------------------------


class TestScoreToTier:
    def test_0_39_is_low(self):
        assert _score_to_tier(0.39) == "LOW"

    def test_0_40_is_medium(self):
        assert _score_to_tier(0.40) == "MEDIUM"

    def test_0_64_is_medium(self):
        assert _score_to_tier(0.64) == "MEDIUM"

    def test_0_65_is_high(self):
        assert _score_to_tier(0.65) == "HIGH"

    def test_0_84_is_high(self):
        assert _score_to_tier(0.84) == "HIGH"

    def test_0_85_is_critical(self):
        assert _score_to_tier(0.85) == "CRITICAL"

    def test_1_0_is_critical(self):
        assert _score_to_tier(1.0) == "CRITICAL"


# ---------------------------------------------------------------------------
# compute() — config-based inputs
# ---------------------------------------------------------------------------


class TestCompute:
    def test_kjfk_event_type(self):
        event = compute("KJFK")
        assert event["event_type"] == "workload_index"

    def test_kjfk_data_available(self):
        event = compute("KJFK")
        assert event["data_unavailable"] is False

    def test_kjfk_alert_id_prefix(self):
        event = compute("KJFK")
        assert event["alert_id"].startswith("WI-")

    def test_kjfk_score_in_range(self):
        event = compute("KJFK")
        assert 0.0 <= event["score"] <= 1.0

    def test_kjfk_tier_valid(self):
        event = compute("KJFK")
        assert event["tier"] in {"LOW", "MEDIUM", "HIGH", "CRITICAL"}

    def test_kjfk_staffed_matches_config(self):
        event = compute("KJFK")
        assert (
            event["staffed_controllers"] == config.AIRPORTS["KJFK"].staffed_controllers
        )

    def test_kjfk_recommended_matches_config(self):
        event = compute("KJFK")
        assert (
            event["recommended_controllers"]
            == config.AIRPORTS["KJFK"].recommended_controllers
        )

    def test_all_airports_compute_without_error(self):
        for icao in config.AIRPORTS:
            event = compute(icao)
            assert event["data_unavailable"] is False
            assert event["tier"] in {"LOW", "MEDIUM", "HIGH", "CRITICAL"}

    def test_unknown_airport_returns_unavailable(self):
        event = compute("ZZZZ")
        assert event["data_unavailable"] is True
        assert event["tier"] == "UNKNOWN"

    def test_understaffed_airport_higher_score(self):
        """ATL is understaffed (52 recommended / 37 staffed) — score should be at least MEDIUM.

        KATL: staffing_ratio=0.71, staffing_score=0.29 * 0.50 = 0.145
        active_freq=5/8=0.625 * 0.25 = 0.156; handoff=16/30=0.53 * 0.25 = 0.133
        total ≈ 0.434 → MEDIUM (≥ 0.40).
        """
        event = compute("KATL")
        assert (
            event["score"] >= config.SCORE_TIER_LOW_MAX
        )  # at least MEDIUM (> LOW boundary)

    def test_score_is_float(self):
        event = compute("KJFK")
        assert isinstance(event["score"], float)


# ---------------------------------------------------------------------------
# compute_unavailable()
# ---------------------------------------------------------------------------


class TestComputeUnavailable:
    def test_tier_unknown(self):
        event = compute_unavailable("KJFK")
        assert event["tier"] == "UNKNOWN"

    def test_data_unavailable_true(self):
        event = compute_unavailable("KJFK")
        assert event["data_unavailable"] is True

    def test_score_none(self):
        event = compute_unavailable("KJFK")
        assert event["score"] is None

    def test_event_type(self):
        event = compute_unavailable("KJFK")
        assert event["event_type"] == "workload_index"
