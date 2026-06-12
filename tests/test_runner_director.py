"""Tests for the v1.2 director switches in modules/runner.py.

Each switch is deterministic:
  degraded       → run_cycle publishes tier=UNKNOWN (simulated OpenSky outage)
  sparse         → DEMO background fleet capped to 2 aircraft + the converge pair
  workload_surge → workload_index staffing forced to ceil(recommended * 0.60),
                   pushing the score up vs the config baseline
"""

import json
from unittest.mock import patch

import fakeredis
import pytest

from dashboard.topics import DEMO_FLAG_KEY_PREFIX
from modules import demo_source
from modules.runner import (
    TOPIC_CONFLICT_GEOMETRY,
    TOPIC_TRAFFIC_DENSITY,
    TOPIC_WORKLOAD_INDEX,
    _surge_staffed,
    run_cycle,
)


@pytest.fixture()
def fake_redis():
    return fakeredis.FakeRedis(decode_responses=True)


@pytest.fixture(autouse=True)
def _reset_converge_state():
    demo_source.reset_converge_state()
    yield
    demo_source.reset_converge_state()


def _capture(fake_redis) -> dict[str, str]:
    captured: dict[str, str] = {}
    original = fake_redis.publish

    def capture_publish(channel, message):
        captured[channel] = message
        return original(channel, message)

    fake_redis.publish = capture_publish
    return captured


class TestDegradedSwitch:
    def test_degraded_forces_unknown_events(self, fake_redis):
        fake_redis.set(f"{DEMO_FLAG_KEY_PREFIX}degraded", "1")
        captured = _capture(fake_redis)
        # fetch_states must NOT be called when degraded short-circuits to None.
        with patch(
            "modules.runner.fetch_states",
            side_effect=AssertionError("must not fetch when degraded"),
        ):
            run_cycle("KJFK", fake_redis)
        td = json.loads(captured[TOPIC_TRAFFIC_DENSITY])
        cg = json.loads(captured[TOPIC_CONFLICT_GEOMETRY])
        assert td["tier"] == "UNKNOWN"
        assert td["data_unavailable"] is True
        assert cg["tier"] == "UNKNOWN"
        # workload never depends on live data → still available
        wi = json.loads(captured[TOPIC_WORKLOAD_INDEX])
        assert wi["data_unavailable"] is False


class TestSparseSwitch:
    def test_sparse_caps_background_fleet(self, fake_redis):
        fake_redis.set(f"{DEMO_FLAG_KEY_PREFIX}sparse", "1")
        captured = _capture(fake_redis)
        with patch.dict("os.environ", {"DEMO_MODE": "1"}):
            run_cycle("KJFK", fake_redis)
        snap = json.loads(captured["towerguard:aircraft_snapshot"])
        callsigns = {ac["callsign"] for ac in snap["aircraft"]}
        # 2 background aircraft + the converging pair only.
        assert {"DMO901", "DMO902"}.issubset(callsigns)
        assert len(snap["aircraft"]) == 4  # 2 background + 2 converge

    def test_full_fleet_when_sparse_off(self, fake_redis):
        captured = _capture(fake_redis)
        with patch.dict("os.environ", {"DEMO_MODE": "1"}):
            run_cycle("KJFK", fake_redis)
        snap = json.loads(captured["towerguard:aircraft_snapshot"])
        # full fixture background (8) + converge pair (2)
        assert len(snap["aircraft"]) > 4


class TestWorkloadSurgeSwitch:
    def test_surge_staffed_is_ceil_60_percent(self):
        # KJFK recommended=33 → ceil(33*0.60)=20
        assert _surge_staffed("KJFK") == 20
        # KATL recommended=52 → ceil(52*0.60)=32
        assert _surge_staffed("KATL") == 32

    def test_surge_pushes_workload_score_up(self, fake_redis):
        captured = _capture(fake_redis)
        with patch("modules.runner.fetch_states", return_value=[]):
            run_cycle("KJFK", fake_redis)
        baseline = json.loads(captured[TOPIC_WORKLOAD_INDEX])["score"]

        fake_redis.set(f"{DEMO_FLAG_KEY_PREFIX}workload_surge", "1")
        with patch("modules.runner.fetch_states", return_value=[]):
            run_cycle("KJFK", fake_redis)
        surged = json.loads(captured[TOPIC_WORKLOAD_INDEX])["score"]

        assert surged > baseline
        # staffing reflected in the event
        assert json.loads(captured[TOPIC_WORKLOAD_INDEX])["staffed_controllers"] == 20
