"""Tests for the runner's aircraft_snapshot publish and DEMO_MODE cycle.

Covers:
  - one cycle publishes a well-formed snapshot on TOPIC_AIRCRAFT_SNAPSHOT
  - the snapshot is NOT published when upstream data is unavailable
  - DEMO_MODE runs a full cycle offline and yields a HIGH conflict from the
    guaranteed converging pair
"""

import json
import random
from unittest.mock import patch

import fakeredis
import pytest

from modules import demo_source
from modules.runner import (
    TOPIC_AIRCRAFT_SNAPSHOT,
    TOPIC_CONFLICT_GEOMETRY,
    run_cycle,
)


@pytest.fixture()
def fake_redis():
    return fakeredis.FakeRedis(decode_responses=True)


@pytest.fixture(autouse=True)
def _reset_converge_state():
    """The converging pair advances via module-level state; reset before each
    test so cross-cycle continuity does not leak between tests."""
    demo_source.reset_converge_state()
    yield
    demo_source.reset_converge_state()


def _sample_states() -> list[dict]:
    return [
        {
            "icao24": "a12345",
            "callsign": "TST001  ",
            "latitude": 40.64,
            "longitude": -73.78,
            "geo_altitude": 3000.0,
            "baro_altitude": 3000.0,
            "on_ground": False,
            "velocity": 250.0,
            "true_track": 90.0,
            "vertical_rate": 0.0,
        },
    ]


def _capture(fake_redis) -> dict[str, str]:
    captured: dict[str, str] = {}
    original = fake_redis.publish

    def capture_publish(channel, message):
        captured[channel] = message
        return original(channel, message)

    fake_redis.publish = capture_publish
    return captured


class TestSnapshotPublish:
    def test_cycle_publishes_aircraft_snapshot(self, fake_redis):
        captured = _capture(fake_redis)
        with patch("modules.runner.fetch_states", return_value=_sample_states()):
            run_cycle("KJFK", fake_redis)

        assert TOPIC_AIRCRAFT_SNAPSHOT in captured
        snap = json.loads(captured[TOPIC_AIRCRAFT_SNAPSHOT])
        assert snap["airport"] == "KJFK"
        assert "timestamp" in snap
        assert len(snap["aircraft"]) == 1
        ac = snap["aircraft"][0]
        assert set(ac.keys()) == {
            "icao24",
            "callsign",
            "lat",
            "lon",
            "alt_ft",
            "velocity_kt",
            "heading",
        }
        assert ac["callsign"] == "TST001"  # stripped
        assert ac["velocity_kt"] == 250.0

    def test_snapshot_not_published_when_unavailable(self, fake_redis):
        from data.opensky import OpenSkyUnavailable

        captured = _capture(fake_redis)
        with patch(
            "modules.runner.fetch_states",
            side_effect=OpenSkyUnavailable("mock"),
        ):
            run_cycle("KJFK", fake_redis)

        # Contract topics still published; snapshot omitted (no positions to draw)
        assert TOPIC_AIRCRAFT_SNAPSHOT not in captured


class TestDemoMode:
    def test_demo_cycle_runs_offline_and_yields_converging_conflict(self, fake_redis):
        captured = _capture(fake_redis)
        # DEMO_MODE=1 must bypass OpenSky entirely; fetch_states is patched to
        # raise so any accidental call would fail the test loudly.
        with (
            patch.dict("os.environ", {"DEMO_MODE": "1"}),
            patch(
                "modules.runner.fetch_states",
                side_effect=AssertionError("OpenSky must not be called in DEMO_MODE"),
            ),
        ):
            run_cycle("KJFK", fake_redis)

        cg = json.loads(captured[TOPIC_CONFLICT_GEOMETRY])
        assert cg["conflicts_detected"] >= 1
        # The synthesized converging pair must appear as a conflict whose first
        # violation lands in the 61-90 s HIGH band (the runner-level guarantee).
        # The overall tier may be CRITICAL because the fixture already contains a
        # near-pair (UAL412/AAL891 ~2.3 NM apart) — that is pre-existing fixture
        # data, not the converging-pair requirement.
        # On the spawn cycle (state reset by the autouse fixture) the pair is at
        # its 10 NM start geometry, so the first violation lands in the HIGH band.
        converging = [
            c
            for c in cg["all_conflicts"]
            if set(c["callsigns"]) == {"DMO901", "DMO902"}
        ]
        assert len(converging) == 1
        assert 60 < converging[0]["time_to_violation_seconds"] <= 90
        # Snapshot includes background + the converging pair
        snap = json.loads(captured[TOPIC_AIRCRAFT_SNAPSHOT])
        callsigns = {ac["callsign"] for ac in snap["aircraft"]}
        assert {"DMO901", "DMO902"}.issubset(callsigns)


class TestDemoSource:
    def test_converging_pair_first_violation_in_high_band(self):
        """At spawn (elapsed=0) the pair first violates in the 61-90 s HIGH band."""
        from modules.conflict_geometry import _check_pair

        pair = demo_source._converging_pair(40.64, -73.78)
        result = _check_pair(pair[0], pair[1])
        assert result is not None
        ttv = result["time_to_violation_seconds"]
        assert 60 < ttv <= 90

    def test_converging_pair_advances_continuously_then_respawns(self):
        """The pair closes across cycles (ttv shrinks) then respawns to the start.

        Spawn cycle lands in the HIGH band; the next cycle's snapshot has the
        pair 6 NM closer so the time-to-violation drops into the CRITICAL band;
        the following cycle respawns to the start geometry and the loop repeats.
        """
        from modules.conflict_geometry import _check_pair

        def cycle_ttv() -> int:
            states = demo_source.demo_states(40.64, -73.78)
            pair = [s for s in states if s.get("callsign") in ("DMO901", "DMO902")]
            result = _check_pair(pair[0], pair[1])
            assert result is not None
            return result["time_to_violation_seconds"]

        demo_source.reset_converge_state()
        first = cycle_ttv()
        second = cycle_ttv()
        third = cycle_ttv()

        # Cycle 0: HIGH band. Cycle 1: closer, so a smaller (CRITICAL) ttv.
        assert 60 < first <= 90
        assert second < first
        assert second <= 60
        # Cycle 2: respawned back to the start geometry → HIGH band again.
        assert third == first

    def test_converging_pair_state_is_continuous(self):
        """Two successive cycles move the pair closer (smaller half-separation)."""
        demo_source.reset_converge_state()
        s0 = demo_source.demo_states(40.64, -73.78)
        s1 = demo_source.demo_states(40.64, -73.78)

        def half_sep(states: list[dict]) -> float:
            north = next(s for s in states if s["callsign"] == "DMO901")
            south = next(s for s in states if s["callsign"] == "DMO902")
            return (north["latitude"] - south["latitude"]) / 2.0

        assert half_sep(s1) < half_sep(s0)

    def test_jitter_is_immutable(self):
        rng = random.Random(42)
        original = {
            "latitude": 40.0,
            "longitude": -73.0,
            "velocity": 200.0,
        }
        jittered = demo_source._jitter(original, rng)
        # original untouched
        assert original == {"latitude": 40.0, "longitude": -73.0, "velocity": 200.0}
        # values moved
        assert jittered["latitude"] != 40.0 or jittered["longitude"] != -73.0
