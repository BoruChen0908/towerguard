"""Tests for modules/traffic_density.py — score computation and tier mapping."""

import config
from modules.traffic_density import (
    _score_to_tier,
    _std_dev,
    compute,
    compute_unavailable,
)


# ---------------------------------------------------------------------------
# Score → Tier boundary values (§2a)
# ---------------------------------------------------------------------------


class TestScoreToTier:
    def test_below_low_boundary(self):
        assert _score_to_tier(0.39) == "LOW"

    def test_at_low_boundary(self):
        assert _score_to_tier(0.40) == "MEDIUM"

    def test_below_medium_boundary(self):
        assert _score_to_tier(0.64) == "MEDIUM"

    def test_at_medium_boundary(self):
        assert _score_to_tier(0.65) == "HIGH"

    def test_below_high_boundary(self):
        assert _score_to_tier(0.84) == "HIGH"

    def test_at_high_boundary(self):
        assert _score_to_tier(0.85) == "CRITICAL"

    def test_above_high_boundary(self):
        assert _score_to_tier(1.0) == "CRITICAL"

    def test_zero_is_low(self):
        assert _score_to_tier(0.0) == "LOW"


# ---------------------------------------------------------------------------
# _std_dev
# ---------------------------------------------------------------------------


class TestStdDev:
    def test_empty_list(self):
        assert _std_dev([]) == 0.0

    def test_single_element(self):
        assert _std_dev([42.0]) == 0.0

    def test_known_values(self):
        # std_dev([2, 4, 4, 4, 5, 5, 7, 9]) = 2.0
        result = _std_dev([2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0])
        assert abs(result - 2.0) < 1e-9

    def test_identical_values(self):
        assert _std_dev([5.0, 5.0, 5.0]) == 0.0


# ---------------------------------------------------------------------------
# compute()
# ---------------------------------------------------------------------------


def _make_state(
    velocity: float = 250.0,
    geo_altitude: float = 5000.0,
    on_ground: bool = False,
) -> dict:
    return {
        "icao24": "abc123",
        "callsign": "TST001",
        "latitude": 40.64,
        "longitude": -73.78,
        "baro_altitude": geo_altitude,
        "on_ground": on_ground,
        "velocity": velocity,
        "true_track": 90.0,
        "vertical_rate": 0.0,
        "geo_altitude": geo_altitude,
    }


class TestCompute:
    def test_empty_states_returns_low_tier(self):
        event = compute("KJFK", [])
        assert event["tier"] == "LOW"
        assert event["aircraft_count"] == 0
        assert event["data_unavailable"] is False

    def test_event_type_correct(self):
        event = compute("KJFK", [])
        assert event["event_type"] == "traffic_density"

    def test_ground_and_slow_aircraft_excluded_from_count(self):
        # Only genuinely airborne traffic counts; on_ground and ~zero-speed
        # surface aircraft are excluded (config.MIN_AIRBORNE_SPEED_KTS).
        states = [
            _make_state(velocity=250.0),                   # airborne
            _make_state(velocity=300.0),                   # airborne
            _make_state(velocity=250.0, on_ground=True),   # on the ground
            _make_state(velocity=5.0),                     # taxiing / parked
        ]
        event = compute("KJFK", states)
        assert event["aircraft_count"] == 2

    def test_airport_in_output(self):
        event = compute("KATL", [])
        assert event["airport"] == "KATL"

    def test_aircraft_count_matches_states(self):
        states = [_make_state() for _ in range(10)]
        event = compute("KJFK", states)
        assert event["aircraft_count"] == 10

    def test_score_between_zero_and_one(self):
        states = [_make_state(velocity=float(v)) for v in range(200, 320, 10)]
        event = compute("KJFK", states)
        assert 0.0 <= event["score"] <= 1.0

    def test_none_velocity_excluded_from_variance(self):
        states = [
            {**_make_state(), "velocity": None},
            {**_make_state(), "velocity": 250.0},
        ]
        event = compute("KJFK", states)
        # Should not crash; speed_variance reflects only non-None values
        assert event["speed_variance"] == 0.0  # single valid speed → std_dev=0

    def test_window_seconds_fixed(self):
        event = compute("KJFK", [])
        assert event["window_seconds"] == 60

    def test_high_count_pushes_score_up(self):
        # 200 aircraft at TD_MAX_AIRCRAFT → count_score = 1.0
        states = [_make_state() for _ in range(200)]
        event = compute("KJFK", states)
        assert event["score"] >= config.TD_WEIGHT_COUNT

    def test_alert_id_prefixed_td(self):
        event = compute("KJFK", [])
        assert event["alert_id"].startswith("TD-")


# ---------------------------------------------------------------------------
# compute_unavailable()
# ---------------------------------------------------------------------------


class TestComputeUnavailable:
    def test_data_unavailable_true(self):
        event = compute_unavailable("KJFK")
        assert event["data_unavailable"] is True

    def test_tier_unknown(self):
        event = compute_unavailable("KJFK")
        assert event["tier"] == "UNKNOWN"

    def test_score_is_none(self):
        event = compute_unavailable("KJFK")
        assert event["score"] is None

    def test_event_type(self):
        event = compute_unavailable("KJFK")
        assert event["event_type"] == "traffic_density"
