"""Tests for functional B — mock_katherine's shift-event publishing.

Covers:
  - _maybe_log_tier_change: baseline (no log), unchanged (no log), transition
    (XADD tier_change with the contract summary + alert_id ref)
  - tier_change summary formatting incl. the conflict pair suffix
  - _publish_advisory / _publish_briefing also XADD advisory / briefing events
"""

import json

import fakeredis
import pytest

from dashboard.shift_stream import (
    KIND_ADVISORY,
    KIND_BRIEFING,
    KIND_TIER_CHANGE,
    read_recent,
)
from fixtures import mock_katherine
from fixtures.mock_katherine import (
    TOPIC_ADVISORY,
    TOPIC_CONFLICT_GEOMETRY,
    _maybe_log_tier_change,
    _publish_advisory,
    _publish_briefing,
    build_advisory,
    build_briefing_payload,
)


@pytest.fixture()
def fake_redis():
    return fakeredis.FakeRedis(decode_responses=True)


def _cg_event(tier: str, alert_id: str = "CG-0001") -> dict:
    return {
        "event_type": "conflict_geometry",
        "alert_id": alert_id,
        "tier": tier,
        "closest_pair": {
            "callsigns": ["DMO901", "DMO902"],
            "projected_separation_nm": 2.8,
            "icao_minimum_nm": 3.0,
            "time_to_violation_seconds": 50,
        },
    }


class TestTierChange:
    def test_first_event_establishes_baseline_without_logging(self, fake_redis):
        last: dict[str, str] = {}
        _maybe_log_tier_change(
            fake_redis, TOPIC_CONFLICT_GEOMETRY, _cg_event("HIGH"), last
        )
        assert read_recent(fake_redis) == []
        assert last[TOPIC_CONFLICT_GEOMETRY] == "HIGH"

    def test_unchanged_tier_does_not_log(self, fake_redis):
        last = {TOPIC_CONFLICT_GEOMETRY: "HIGH"}
        _maybe_log_tier_change(
            fake_redis, TOPIC_CONFLICT_GEOMETRY, _cg_event("HIGH"), last
        )
        assert read_recent(fake_redis) == []

    def test_transition_logs_tier_change_with_contract_summary(self, fake_redis):
        last = {TOPIC_CONFLICT_GEOMETRY: "HIGH"}
        _maybe_log_tier_change(
            fake_redis,
            TOPIC_CONFLICT_GEOMETRY,
            _cg_event("CRITICAL", alert_id="CG-0009"),
            last,
        )
        events = read_recent(fake_redis)
        assert len(events) == 1
        assert events[0]["kind"] == KIND_TIER_CHANGE
        assert (
            events[0]["summary"] == "CONFLICT GEOMETRY HIGH → CRITICAL (DMO901/DMO902)"
        )
        assert events[0]["ref"] == "CG-0009"
        assert last[TOPIC_CONFLICT_GEOMETRY] == "CRITICAL"

    def test_summary_without_pair_omits_suffix(self, fake_redis):
        # traffic_density events carry no closest_pair → no suffix.
        last = {mock_katherine.TOPIC_TRAFFIC_DENSITY: "LOW"}
        td_event = {
            "event_type": "traffic_density",
            "alert_id": "TD-0003",
            "tier": "MEDIUM",
        }
        _maybe_log_tier_change(
            fake_redis, mock_katherine.TOPIC_TRAFFIC_DENSITY, td_event, last
        )
        events = read_recent(fake_redis)
        assert events[0]["summary"] == "TRAFFIC DENSITY LOW → MEDIUM"
        assert events[0]["ref"] == "TD-0003"


class TestPublishHelpers:
    def test_publish_advisory_publishes_and_logs(self, fake_redis):
        published = _capture_publish(fake_redis)

        advisory = build_advisory("ADV-0001", _cg_event("CRITICAL"))
        _publish_advisory(fake_redis, advisory)

        # advisory shift event logged with the advisory_id ref
        events = [e for e in read_recent(fake_redis) if e["kind"] == KIND_ADVISORY]
        assert len(events) == 1
        assert events[0]["ref"] == "ADV-0001"
        assert events[0]["summary"] == advisory["summary"]

        # and the advisory was published verbatim to its pub/sub topic
        assert TOPIC_ADVISORY in published
        assert json.loads(published[TOPIC_ADVISORY])["advisory_id"] == "ADV-0001"

    def test_publish_briefing_publishes_and_logs(self, fake_redis):
        published = _capture_publish(fake_redis)

        payload = build_briefing_payload("ADV-0002", _cg_event("HIGH"))
        _publish_briefing(fake_redis, payload, "ADV-0002")

        events = [e for e in read_recent(fake_redis) if e["kind"] == KIND_BRIEFING]
        assert len(events) == 1
        assert events[0]["ref"] == "ADV-0002"
        assert "ADV-0002" in events[0]["summary"]

        assert mock_katherine.TOPIC_BRIEFING in published


def _capture_publish(fake_redis) -> dict[str, str]:
    """Intercept redis.publish, recording the last payload per channel."""
    captured: dict[str, str] = {}
    original = fake_redis.publish

    def capture(channel, message):
        captured[channel] = message
        return original(channel, message)

    fake_redis.publish = capture
    return captured
