"""Tests for mock_katherine's tier_change shift-event publishing (v1.2).

Covers _maybe_log_tier_change: baseline (no log), unchanged (no log), transition
(XADD tier_change with the contract summary + alert_id ref + the new tier field),
and the conflict-pair summary suffix.
"""

import fakeredis
import pytest

from dashboard.shift_stream import KIND_TIER_CHANGE, read_recent
from fixtures import mock_katherine
from fixtures.mock_katherine import (
    TOPIC_CONFLICT_GEOMETRY,
    _maybe_log_tier_change,
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

    def test_transition_logs_tier_change_with_contract_summary_and_tier(
        self, fake_redis
    ):
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
        # v1.2: the new tier is carried so the event strip can colour the row.
        assert events[0]["tier"] == "CRITICAL"
        assert last[TOPIC_CONFLICT_GEOMETRY] == "CRITICAL"

    def test_summary_without_pair_omits_suffix(self, fake_redis):
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
        assert events[0]["tier"] == "MEDIUM"
