"""Unit tests for the condition-driven advisory rule engine (design §3/§6).

Covers the rule table and the lifecycle protocol end-to-end through fakeredis:
  C1  dedup — same pair, same HIGH tier, not re-issued
  C2  escalation pierces dedup/cooldown, carries supersedes + retires the old card
  W   composite escalation when workload ≥ MEDIUM co-occurs with a conflict
  S   SURFACE_CONFLICT when density LOW disagrees with conflict ≥ HIGH
  R   lifecycle resolved + resolve XADD when an issued pair drops to LOW
  re-assess: (a) still-active → new advisory w/ supersedes + in_response_to
             (b) cleared      → lifecycle resolved w/ in_response_to
  cooldown: a human-handled card is held 300 s, then re-issues
"""

import json

import fakeredis
import pytest

from dashboard.shift_stream import (
    KIND_ADVISORY,
    KIND_REASSESS,
    KIND_RESOLVE,
    KIND_SUPERSEDE,
    read_recent,
)
from dashboard.topics import (
    TOPIC_ADVISORY,
    TOPIC_ADVISORY_LIFECYCLE,
)
from fixtures.advisory_engine import (
    ADVISORY_STATE_KEY_PREFIX,
    CONFIRMED_KEY_PREFIX,
    AdvisoryEngine,
)


@pytest.fixture()
def fake_redis():
    return fakeredis.FakeRedis(decode_responses=True)


class _Clock:
    """Manually advanced monotonic clock for deterministic cooldown tests."""

    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


def _capture(fake_redis) -> dict[str, list[str]]:
    captured: dict[str, list[str]] = {}
    original = fake_redis.publish

    def capture_publish(channel, message):
        captured.setdefault(channel, []).append(message)
        return original(channel, message)

    fake_redis.publish = capture_publish
    return captured


def _cg(tier: str, *, pair=("AAL891", "UAL412"), sep=2.8, ttv=50, alert="CG-0001"):
    if tier == "LOW":
        closest = None
    else:
        closest = {
            "callsigns": list(pair),
            "projected_separation_nm": sep,
            "icao_minimum_nm": 3.0,
            "time_to_violation_seconds": ttv,
        }
    return {
        "event_type": "conflict_geometry",
        "alert_id": alert,
        "airport": "KJFK",
        "tier": tier,
        "closest_pair": closest,
        "all_conflicts": [] if closest is None else [closest],
    }


def _td(tier: str, count: int = 80):
    return {
        "event_type": "traffic_density",
        "alert_id": "TD-0001",
        "tier": tier,
        "aircraft_count": count,
        "score": 0.7 if tier != "LOW" else 0.1,
    }


def _wi(tier: str, staffed: int = 31, recommended: int = 52):
    return {
        "event_type": "workload_index",
        "alert_id": "WI-0001",
        "tier": tier,
        "staffed_controllers": staffed,
        "recommended_controllers": recommended,
        "score": 0.45 if tier != "LOW" else 0.2,
    }


def _advisories(captured) -> list[dict]:
    return [json.loads(m) for m in captured.get(TOPIC_ADVISORY, [])]


def _lifecycles(captured) -> list[dict]:
    return [json.loads(m) for m in captured.get(TOPIC_ADVISORY_LIFECYCLE, [])]


class TestC1Dedup:
    def test_same_pair_same_high_tier_not_reissued(self, fake_redis):
        captured = _capture(fake_redis)
        engine = AdvisoryEngine(fake_redis, "KJFK")
        # Plain conflict (no workload pressure, td not LOW) → C1.
        engine.update_module("towerguard:traffic_density", _td("MEDIUM"))
        first = engine.on_conflict_event(_cg("HIGH"))
        second = engine.on_conflict_event(_cg("HIGH", alert="CG-0002"))
        assert first is not None
        assert first["action"] == "ESCALATE"
        assert first["severity"] == "HIGH"
        assert second is None  # deduped
        assert len(_advisories(captured)) == 1

    def test_advisory_carries_evidence_and_condition_key(self, fake_redis):
        engine = AdvisoryEngine(fake_redis, "KJFK")
        engine.update_module("towerguard:traffic_density", _td("MEDIUM"))
        adv = engine.on_conflict_event(_cg("HIGH"))
        assert adv["condition_key"] == "KJFK:conflict_geometry:AAL891/UAL412"
        assert len(adv["evidence"]["signals"]) == 3
        # advisory shift event carries the tier
        adv_events = [e for e in read_recent(fake_redis) if e["kind"] == KIND_ADVISORY]
        assert adv_events[0]["tier"] == "HIGH"


class TestC2Escalation:
    def test_critical_pierces_cooldown_with_supersedes(self, fake_redis):
        captured = _capture(fake_redis)
        engine = AdvisoryEngine(fake_redis, "KJFK")
        engine.update_module("towerguard:traffic_density", _td("MEDIUM"))
        first = engine.on_conflict_event(_cg("HIGH"))
        # Same pair escalates to CRITICAL → must pierce dedup and supersede.
        second = engine.on_conflict_event(_cg("CRITICAL", ttv=40, alert="CG-0003"))
        assert second is not None
        assert second["severity"] == "CRITICAL"
        assert second["supersedes"] == [first["advisory_id"]]
        # Old card retired: state key set, lifecycle superseded event, XADD supersede
        assert (
            fake_redis.get(f"{ADVISORY_STATE_KEY_PREFIX}{first['advisory_id']}")
            == "superseded"
        )
        lifecycles = _lifecycles(captured)
        assert any(
            lc["new_state"] == "superseded"
            and lc["advisory_id"] == first["advisory_id"]
            for lc in lifecycles
        )
        assert any(e["kind"] == KIND_SUPERSEDE for e in read_recent(fake_redis))


class TestSurfaceConflict:
    def test_low_density_high_conflict_surfaces_conflict(self, fake_redis):
        engine = AdvisoryEngine(fake_redis, "KJFK")
        engine.update_module("towerguard:traffic_density", _td("LOW", count=2))
        adv = engine.on_conflict_event(_cg("HIGH"))
        assert adv is not None
        assert adv["action"] == "SURFACE_CONFLICT"
        # conflict block names exactly the two contradictory signals
        between = adv["conflict"]["between"]
        assert len(between) == 2
        assert {b["event_type"] for b in between} == {
            "conflict_geometry",
            "traffic_density",
        }


class TestComposite:
    def test_workload_and_conflict_co_occurrence_escalates(self, fake_redis):
        engine = AdvisoryEngine(fake_redis, "KJFK")
        engine.update_module("towerguard:traffic_density", _td("MEDIUM"))
        engine.update_module("towerguard:workload_index", _wi("MEDIUM"))
        adv = engine.on_conflict_event(_cg("HIGH"))
        assert adv is not None
        assert adv["action"] == "ESCALATE"
        # composite condition key uses the combined signal label
        assert "workload+conflict" in adv["condition_key"]


class TestResolve:
    def test_pair_dropping_to_low_resolves(self, fake_redis):
        captured = _capture(fake_redis)
        engine = AdvisoryEngine(fake_redis, "KJFK")
        engine.update_module("towerguard:traffic_density", _td("MEDIUM"))
        adv = engine.on_conflict_event(_cg("HIGH"))
        assert adv is not None
        # Same pair improves: conflict tier falls back to LOW → resolve.
        engine.on_conflict_event(_cg("LOW"))
        lifecycles = _lifecycles(captured)
        assert any(lc["new_state"] == "resolved" for lc in lifecycles)
        assert (
            fake_redis.get(f"{ADVISORY_STATE_KEY_PREFIX}{adv['advisory_id']}")
            == "resolved"
        )
        assert any(e["kind"] == KIND_RESOLVE for e in read_recent(fake_redis))


class TestReassess:
    def test_still_active_reissues_with_supersedes_and_in_response_to(self, fake_redis):
        engine = AdvisoryEngine(fake_redis, "KJFK")
        engine.update_module("towerguard:traffic_density", _td("MEDIUM"))
        engine.update_module("towerguard:conflict_geometry", _cg("HIGH"))
        result = engine.on_reassess_request(
            {
                "type": "reassess_request",
                "request_id": "RAS-1a2b",
                "advisory_id": "ADV-0001",
                "requested_at": "2026-06-12T18:00:00Z",
                "reason": "controller_manual",
            }
        )
        assert result["action"] == "ESCALATE"
        assert result["supersedes"] == ["ADV-0001"]
        assert result["in_response_to"] == "RAS-1a2b"
        assert any(e["kind"] == KIND_REASSESS for e in read_recent(fake_redis))

    def test_cleared_condition_resolves_with_in_response_to(self, fake_redis):
        captured = _capture(fake_redis)
        engine = AdvisoryEngine(fake_redis, "KJFK")
        # No active conflict in the snapshot → condition gone.
        engine.update_module("towerguard:conflict_geometry", _cg("LOW"))
        result = engine.on_reassess_request(
            {
                "type": "reassess_request",
                "request_id": "RAS-9z9z",
                "advisory_id": "ADV-0007",
                "requested_at": "2026-06-12T18:00:00Z",
                "reason": "controller_manual",
            }
        )
        assert result["type"] == "advisory_lifecycle"
        assert result["new_state"] == "resolved"
        assert result["in_response_to"] == "RAS-9z9z"
        assert not _advisories(captured)  # no new advisory, only a lifecycle event


class TestCooldown:
    def test_handled_card_held_then_reissues_after_cooldown(self, fake_redis):
        clock = _Clock()
        captured = _capture(fake_redis)
        engine = AdvisoryEngine(fake_redis, "KJFK", clock=clock)
        engine.update_module("towerguard:traffic_density", _td("MEDIUM"))
        first = engine.on_conflict_event(_cg("HIGH"))
        # Controller confirms → cooldown gate now applies to same-tier re-fires.
        fake_redis.set(f"{CONFIRMED_KEY_PREFIX}{first['advisory_id']}", "ts")

        # Within cooldown: same HIGH tier is held.
        clock.advance(100)
        assert engine.on_conflict_event(_cg("HIGH", alert="CG-0002")) is None

        # After cooldown lapses: same condition re-issues (world unchanged but the
        # human-handled card has aged out per design §3).
        clock.advance(250)  # total 350 > 300
        again = engine.on_conflict_event(_cg("HIGH", alert="CG-0003"))
        assert again is not None
        assert len(_advisories(captured)) == 2
