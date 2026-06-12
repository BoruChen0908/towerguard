"""Tests for dashboard/shift_stream.py — the shift-events Redis Stream contract.

Covers XADD field shape, the null-ref sentinel roundtrip, decode coercion, and
read_recent ordering / replay count.
"""

import fakeredis
import pytest

from dashboard.shift_stream import (
    KIND_ADVISORY,
    KIND_TIER_CHANGE,
    SHIFT_EVENTS_KEY,
    SHIFT_EVENTS_REPLAY_COUNT,
    decode_entry,
    read_recent,
    xadd_shift_event,
)


@pytest.fixture()
def fake_redis():
    return fakeredis.FakeRedis(decode_responses=True)


class TestXadd:
    def test_xadd_writes_contract_fields(self, fake_redis):
        xadd_shift_event(
            fake_redis,
            kind=KIND_TIER_CHANGE,
            summary="CONFLICT GEOMETRY HIGH → CRITICAL (DMO901/DMO902)",
            ref="CG-0009",
            timestamp="2026-06-12T18:42:00Z",
            tier="CRITICAL",
        )
        (_entry_id, fields) = fake_redis.xrange(SHIFT_EVENTS_KEY)[0]
        # v1.2 added the optional fifth `tier` field.
        assert set(fields.keys()) == {"timestamp", "kind", "summary", "ref", "tier"}
        assert fields["kind"] == KIND_TIER_CHANGE
        assert fields["ref"] == "CG-0009"
        assert fields["timestamp"] == "2026-06-12T18:42:00Z"
        assert fields["tier"] == "CRITICAL"

    def test_xadd_omitted_tier_stores_null_sentinel(self, fake_redis):
        xadd_shift_event(fake_redis, kind=KIND_ADVISORY, summary="x", ref="ADV-1")
        (_id, fields) = fake_redis.xrange(SHIFT_EVENTS_KEY)[0]
        # No tier passed → "null" sentinel on the wire, decoded back to None.
        assert fields["tier"] == "null"
        assert read_recent(fake_redis)[0]["tier"] is None

    def test_xadd_defaults_timestamp(self, fake_redis):
        xadd_shift_event(fake_redis, kind=KIND_ADVISORY, summary="x", ref="ADV-1")
        (_id, fields) = fake_redis.xrange(SHIFT_EVENTS_KEY)[0]
        # ISO 8601 Z, generated for us
        assert fields["timestamp"].endswith("Z")
        assert "T" in fields["timestamp"]


class TestNullRef:
    def test_none_ref_roundtrips_to_none(self, fake_redis):
        xadd_shift_event(
            fake_redis, kind="airport_switch", summary="Monitoring switched to KEWR"
        )
        events = read_recent(fake_redis)
        assert len(events) == 1
        assert events[0]["ref"] is None
        assert events[0]["summary"] == "Monitoring switched to KEWR"

    def test_decode_entry_maps_null_sentinel(self):
        decoded = decode_entry(
            {"timestamp": "t", "kind": "advisory", "summary": "s", "ref": "null"}
        )
        # A pre-v1.2 entry has no tier field → decodes to None.
        assert decoded == {
            "timestamp": "t",
            "kind": "advisory",
            "summary": "s",
            "ref": None,
            "tier": None,
        }

    def test_decode_entry_coerces_bytes_with_tier(self):
        decoded = decode_entry(
            {
                b"timestamp": b"t",
                b"kind": b"tier_change",
                b"summary": b"s",
                b"ref": b"R1",
                b"tier": b"HIGH",
            }
        )
        assert decoded == {
            "timestamp": "t",
            "kind": "tier_change",
            "summary": "s",
            "ref": "R1",
            "tier": "HIGH",
        }


class TestReadRecent:
    def test_returns_time_ordered_oldest_first(self, fake_redis):
        for i in range(3):
            xadd_shift_event(
                fake_redis, kind=KIND_ADVISORY, summary=f"s{i}", ref=f"ADV-{i}"
            )
        events = read_recent(fake_redis)
        assert [e["summary"] for e in events] == ["s0", "s1", "s2"]

    def test_caps_at_replay_count(self, fake_redis):
        total = SHIFT_EVENTS_REPLAY_COUNT + 5
        for i in range(total):
            xadd_shift_event(fake_redis, kind=KIND_ADVISORY, summary=f"s{i}")
        events = read_recent(fake_redis)
        assert len(events) == SHIFT_EVENTS_REPLAY_COUNT
        # The most recent SHIFT_EVENTS_REPLAY_COUNT, oldest→newest.
        assert events[0]["summary"] == f"s{total - SHIFT_EVENTS_REPLAY_COUNT}"
        assert events[-1]["summary"] == f"s{total - 1}"

    def test_empty_stream_returns_empty_list(self, fake_redis):
        assert read_recent(fake_redis) == []
