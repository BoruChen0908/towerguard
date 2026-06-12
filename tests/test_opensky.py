"""
Tests for data/opensky.py.

All HTTP calls are mocked — no live network or API keys required.
"""

import time
from unittest.mock import MagicMock, patch

import pytest
import requests

from data import opensky as osky
from data.opensky import (
    OpenSkyAuthError,
    OpenSkyUnavailable,
    _bounding_box,
    _parse_states,
    fetch_states,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_response(status_code: int, json_body: dict = None, headers: dict = None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_body or {}
    resp.headers = headers or {}
    return resp


def _token_response():
    return _make_response(200, {"access_token": "test-token", "expires_in": 300})


# ---------------------------------------------------------------------------
# _bounding_box
# ---------------------------------------------------------------------------


class TestBoundingBox:
    def test_returns_four_values(self):
        result = _bounding_box(40.64, -73.78, 50.0)
        assert len(result) == 4

    def test_lat_min_less_than_lat_max(self):
        lat_min, lon_min, lat_max, lon_max = _bounding_box(40.0, -73.0, 50.0)
        assert lat_min < lat_max
        assert lon_min < lon_max

    def test_zero_radius(self):
        lat_min, lon_min, lat_max, lon_max = _bounding_box(40.0, -73.0, 0.0)
        assert lat_min == lat_max
        assert lon_min == lon_max


# ---------------------------------------------------------------------------
# _parse_states
# ---------------------------------------------------------------------------


class TestParseStates:
    def test_parses_full_row(self):
        raw = {
            "states": [
                [
                    "a12345",
                    "UAL412  ",
                    "United States",
                    100,
                    100,
                    -73.78,
                    40.64,
                    3000.0,
                    False,
                    250.0,
                    90.0,
                    -2.0,
                    None,
                    3100.0,
                    "1234",
                    False,
                    0,
                ]
            ]
        }
        result = _parse_states(raw)
        assert len(result) == 1
        assert result[0]["icao24"] == "a12345"
        assert result[0]["velocity"] == 250.0

    def test_empty_states_returns_empty_list(self):
        assert _parse_states({"states": []}) == []

    def test_missing_states_key(self):
        assert _parse_states({}) == []

    def test_null_states(self):
        assert _parse_states({"states": None}) == []

    def test_short_row_excluded(self):
        raw = {"states": [["a12345"]]}  # too short
        result = _parse_states(raw)
        assert result == []


# ---------------------------------------------------------------------------
# Token fetch and 401 refresh
# ---------------------------------------------------------------------------


class TestTokenRefresh:
    def test_401_triggers_token_refresh_and_retry(self):
        """On 401, client should refresh token and retry once."""
        # Reset module token so it attempts a fetch
        osky._token = None
        osky._token_expires_at = 0.0

        call_count = {"n": 0}

        def fake_post(url, data=None, timeout=None):
            return _token_response()

        def fake_get(url, params=None, headers=None, timeout=None):
            call_count["n"] += 1
            if call_count["n"] == 1:
                # First call returns 401
                return _make_response(401)
            # Second call (after token refresh) succeeds
            return _make_response(200, {"time": 0, "states": []})

        with patch("data.opensky.requests.post", fake_post):
            with patch("data.opensky.requests.get", fake_get):
                with patch("os.getenv", return_value="test-value"):
                    result = fetch_states("KJFK")
        assert result == []
        assert call_count["n"] == 2

    def test_double_401_raises_auth_error(self):
        """If 401 persists after token refresh, raise OpenSkyAuthError."""
        osky._token = "stale-token"
        osky._token_expires_at = time.time() + 9999  # pretend still valid

        def fake_post(url, data=None, timeout=None):
            return _token_response()

        def fake_get(url, params=None, headers=None, timeout=None):
            return _make_response(401)

        with patch("data.opensky.requests.post", fake_post):
            with patch("data.opensky.requests.get", fake_get):
                with patch("os.getenv", return_value="test-value"):
                    with pytest.raises(OpenSkyAuthError):
                        fetch_states("KJFK")


# ---------------------------------------------------------------------------
# 429 rate limiting
# ---------------------------------------------------------------------------


class TestRateLimit:
    def test_429_with_retry_after_raises_unavailable(self):
        """429 should parse Retry-After, sleep (mocked), and raise."""
        osky._token = "valid-token"
        osky._token_expires_at = time.time() + 9999

        resp_429 = _make_response(429, headers={"Retry-After": "5"})

        with patch("data.opensky.requests.get", return_value=resp_429):
            with patch("data.opensky.time.sleep") as mock_sleep:
                with pytest.raises(OpenSkyUnavailable, match="rate-limited"):
                    fetch_states("KJFK")
                mock_sleep.assert_called_once_with(5.0)

    def test_429_retry_after_capped(self):
        """Retry-After larger than cap should be clamped."""
        osky._token = "valid-token"
        osky._token_expires_at = time.time() + 9999

        huge_wait = str(9999)
        resp_429 = _make_response(429, headers={"Retry-After": huge_wait})

        with patch("data.opensky.requests.get", return_value=resp_429):
            with patch("data.opensky.time.sleep") as mock_sleep:
                with pytest.raises(OpenSkyUnavailable):
                    fetch_states("KJFK")
                called_with = mock_sleep.call_args[0][0]
                import config

                assert called_with <= config.OPENSKY_MAX_RETRY_AFTER_SECONDS

    def test_429_missing_retry_after_uses_cap(self):
        """Missing Retry-After header should use the configured cap."""
        osky._token = "valid-token"
        osky._token_expires_at = time.time() + 9999

        resp_429 = _make_response(429, headers={})

        with patch("data.opensky.requests.get", return_value=resp_429):
            with patch("data.opensky.time.sleep") as mock_sleep:
                with pytest.raises(OpenSkyUnavailable):
                    fetch_states("KJFK")
                import config

                mock_sleep.assert_called_once_with(
                    float(config.OPENSKY_MAX_RETRY_AFTER_SECONDS)
                )


# ---------------------------------------------------------------------------
# Timeout and connection errors
# ---------------------------------------------------------------------------


class TestConnectionErrors:
    def test_timeout_raises_unavailable(self):
        osky._token = "valid-token"
        osky._token_expires_at = time.time() + 9999

        with patch(
            "data.opensky.requests.get",
            side_effect=requests.exceptions.Timeout("timed out"),
        ):
            with pytest.raises(OpenSkyUnavailable, match="timed out"):
                fetch_states("KJFK")

    def test_connection_error_raises_unavailable(self):
        osky._token = "valid-token"
        osky._token_expires_at = time.time() + 9999

        with patch(
            "data.opensky.requests.get",
            side_effect=requests.exceptions.ConnectionError("refused"),
        ):
            with pytest.raises(OpenSkyUnavailable):
                fetch_states("KJFK")

    def test_5xx_raises_unavailable(self):
        osky._token = "valid-token"
        osky._token_expires_at = time.time() + 9999

        with patch("data.opensky.requests.get", return_value=_make_response(503)):
            with pytest.raises(OpenSkyUnavailable, match="server error"):
                fetch_states("KJFK")


# ---------------------------------------------------------------------------
# Unknown airport
# ---------------------------------------------------------------------------


class TestUnknownAirport:
    def test_unknown_airport_raises_unavailable(self):
        with pytest.raises(OpenSkyUnavailable, match="Unknown airport"):
            fetch_states("ZZZZ")
