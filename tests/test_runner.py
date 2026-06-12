"""
Tests for modules/runner.py — one full cycle publishes three valid JSON events.

Uses fakeredis (no live Redis) and mocks OpenSky HTTP.
"""

import json
from unittest.mock import patch

import fakeredis
import pytest

from modules.runner import (
    TOPIC_CONFLICT_GEOMETRY,
    TOPIC_TRAFFIC_DENSITY,
    TOPIC_WORKLOAD_INDEX,
    run_cycle,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def fake_redis():
    """Return a fakeredis client wired up with a pubsub subscription."""
    r = fakeredis.FakeRedis(decode_responses=True)
    return r


def _sample_states() -> list[dict]:
    """Minimal valid state vectors for testing."""
    return [
        {
            "icao24": "a12345",
            "callsign": "TST001",
            "latitude": 40.64,
            "longitude": -73.78,
            "geo_altitude": 3000.0,
            "baro_altitude": 3000.0,
            "on_ground": False,
            "velocity": 250.0,
            "true_track": 90.0,
            "vertical_rate": 0.0,
        },
        {
            "icao24": "b23456",
            "callsign": "TST002",
            "latitude": 40.70,
            "longitude": -73.85,
            "geo_altitude": 5000.0,
            "baro_altitude": 5000.0,
            "on_ground": False,
            "velocity": 280.0,
            "true_track": 180.0,
            "vertical_rate": -2.0,
        },
    ]


# ---------------------------------------------------------------------------
# One cycle → three topics published
# ---------------------------------------------------------------------------


class TestRunCycle:
    def test_three_topics_receive_one_message_each(self, fake_redis):
        """After one cycle, each topic should have received exactly one message."""
        published: dict[str, list[str]] = {
            TOPIC_TRAFFIC_DENSITY: [],
            TOPIC_CONFLICT_GEOMETRY: [],
            TOPIC_WORKLOAD_INDEX: [],
        }

        # Intercept redis.publish calls
        original_publish = fake_redis.publish

        def capture_publish(channel, message):
            if channel in published:
                published[channel].append(message)
            return original_publish(channel, message)

        fake_redis.publish = capture_publish

        with patch("modules.runner.fetch_states", return_value=_sample_states()):
            run_cycle("KJFK", fake_redis)

        assert len(published[TOPIC_TRAFFIC_DENSITY]) == 1
        assert len(published[TOPIC_CONFLICT_GEOMETRY]) == 1
        assert len(published[TOPIC_WORKLOAD_INDEX]) == 1

    def test_published_messages_are_valid_json(self, fake_redis):
        """Each published message must parse as JSON."""
        captured = []

        original_publish = fake_redis.publish

        def capture_publish(channel, message):
            captured.append(message)
            return original_publish(channel, message)

        fake_redis.publish = capture_publish

        with patch("modules.runner.fetch_states", return_value=_sample_states()):
            run_cycle("KJFK", fake_redis)

        assert len(captured) == 3
        for msg in captured:
            parsed = json.loads(msg)
            assert "event_type" in parsed
            assert "tier" in parsed
            assert "data_unavailable" in parsed

    def test_cycle_with_opensky_unavailable_publishes_unknown_events(self, fake_redis):
        """When OpenSky fails, all traffic/conflict events must be tier=UNKNOWN."""
        from data.opensky import OpenSkyUnavailable

        captured: dict[str, str] = {}

        original_publish = fake_redis.publish

        def capture_publish(channel, message):
            captured[channel] = message
            return original_publish(channel, message)

        fake_redis.publish = capture_publish

        with patch(
            "modules.runner.fetch_states",
            side_effect=OpenSkyUnavailable("mock failure"),
        ):
            run_cycle("KJFK", fake_redis)

        # Traffic Density and Conflict Geometry should be UNKNOWN
        td = json.loads(captured[TOPIC_TRAFFIC_DENSITY])
        cg = json.loads(captured[TOPIC_CONFLICT_GEOMETRY])
        wi = json.loads(captured[TOPIC_WORKLOAD_INDEX])

        assert td["tier"] == "UNKNOWN"
        assert td["data_unavailable"] is True
        assert cg["tier"] == "UNKNOWN"
        assert cg["data_unavailable"] is True

        # Workload Index never depends on live data — should still be available
        assert wi["data_unavailable"] is False

    def test_traffic_density_event_has_required_fields(self, fake_redis):
        captured: dict[str, str] = {}
        original_publish = fake_redis.publish

        def capture_publish(channel, message):
            captured[channel] = message
            return original_publish(channel, message)

        fake_redis.publish = capture_publish

        with patch("modules.runner.fetch_states", return_value=_sample_states()):
            run_cycle("KJFK", fake_redis)

        td = json.loads(captured[TOPIC_TRAFFIC_DENSITY])
        assert td["event_type"] == "traffic_density"
        assert td["airport"] == "KJFK"
        assert "aircraft_count" in td
        assert "score" in td

    def test_conflict_geometry_event_has_required_fields(self, fake_redis):
        captured: dict[str, str] = {}
        original_publish = fake_redis.publish

        def capture_publish(channel, message):
            captured[channel] = message
            return original_publish(channel, message)

        fake_redis.publish = capture_publish

        with patch("modules.runner.fetch_states", return_value=_sample_states()):
            run_cycle("KJFK", fake_redis)

        cg = json.loads(captured[TOPIC_CONFLICT_GEOMETRY])
        assert cg["event_type"] == "conflict_geometry"
        assert "pairs_checked" in cg
        assert "conflicts_detected" in cg
        assert "all_conflicts" in cg

    def test_workload_index_event_has_required_fields(self, fake_redis):
        captured: dict[str, str] = {}
        original_publish = fake_redis.publish

        def capture_publish(channel, message):
            captured[channel] = message
            return original_publish(channel, message)

        fake_redis.publish = capture_publish

        with patch("modules.runner.fetch_states", return_value=_sample_states()):
            run_cycle("KJFK", fake_redis)

        wi = json.loads(captured[TOPIC_WORKLOAD_INDEX])
        assert wi["event_type"] == "workload_index"
        assert "staffed_controllers" in wi
        assert "recommended_controllers" in wi
        assert "score" in wi
