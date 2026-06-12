"""Tests for functional A — airport-switch control channel in modules/runner.py.

Covers:
  - _read_selected_airport: stored value, fallback on unset / unknown / error
  - _on_airport_switch: resets the converging-pair state and XADDs airport_switch
  - run_forever: a change to towerguard:selected_airport triggers an immediate
    cycle for the new airport (not waiting out the 60 s window) and resets the
    DEMO converge state
"""

from unittest.mock import patch

import fakeredis
import pytest

from dashboard.shift_stream import KIND_AIRPORT_SWITCH, read_recent
from dashboard.topics import SELECTED_AIRPORT_KEY
from modules import demo_source, runner


@pytest.fixture()
def fake_redis():
    return fakeredis.FakeRedis(decode_responses=True)


@pytest.fixture(autouse=True)
def _reset_converge_state():
    demo_source.reset_converge_state()
    yield
    demo_source.reset_converge_state()


class TestReadSelectedAirport:
    def test_returns_stored_value(self, fake_redis):
        fake_redis.set(SELECTED_AIRPORT_KEY, "KEWR")
        assert runner._read_selected_airport(fake_redis, "KJFK") == "KEWR"

    def test_fallback_when_unset(self, fake_redis):
        assert runner._read_selected_airport(fake_redis, "KJFK") == "KJFK"

    def test_fallback_when_unknown_icao(self, fake_redis):
        fake_redis.set(SELECTED_AIRPORT_KEY, "ZZZZ")
        assert runner._read_selected_airport(fake_redis, "KJFK") == "KJFK"

    def test_fallback_on_redis_error(self, fake_redis):
        with patch.object(fake_redis, "get", side_effect=Exception("down")):
            assert runner._read_selected_airport(fake_redis, "KBOS") == "KBOS"


class TestOnAirportSwitch:
    def test_resets_converge_state(self, fake_redis):
        # Advance the converging pair so a reset is observable.
        demo_source.demo_states(40.64, -73.78)
        assert demo_source._converge_elapsed_s != 0.0
        runner._on_airport_switch(fake_redis, "KEWR")
        assert demo_source._converge_elapsed_s == 0.0

    def test_xadds_airport_switch_shift_event(self, fake_redis):
        runner._on_airport_switch(fake_redis, "KEWR")
        events = read_recent(fake_redis)
        assert len(events) == 1
        assert events[0]["kind"] == KIND_AIRPORT_SWITCH
        assert events[0]["summary"] == "Monitoring switched to KEWR"
        assert events[0]["ref"] is None


class TestRunForeverSwitch:
    def test_switch_triggers_immediate_cycle_for_new_airport(self, fake_redis):
        """With the cycle window not yet due, changing the selected airport must
        still fire a cycle immediately for the new airport."""
        fake_redis.set(SELECTED_AIRPORT_KEY, "KJFK")
        cycles: list[str] = []

        # Stop the loop deterministically after a fixed number of sleeps.
        class _Stop(Exception):
            pass

        sleep_calls = {"n": 0}

        def fake_sleep(_seconds):
            sleep_calls["n"] += 1
            # iteration 1 ran the seed cycle (KJFK). Flip selection to KEWR so
            # iteration 2 detects the switch and cycles immediately; then stop.
            if sleep_calls["n"] == 1:
                fake_redis.set(SELECTED_AIRPORT_KEY, "KEWR")
            elif sleep_calls["n"] >= 2:
                raise _Stop()

        def fake_run_cycle(airport_icao, _redis_client):
            cycles.append(airport_icao)

        with (
            patch("modules.runner._build_redis_client", return_value=fake_redis),
            patch("modules.runner.time.sleep", side_effect=fake_sleep),
            patch("modules.runner.run_cycle", side_effect=fake_run_cycle),
            # monotonic frozen → cycle window never naturally elapses, so the
            # second cycle is proven to be switch-driven, not time-driven.
            patch("modules.runner.time.monotonic", return_value=1000.0),
        ):
            with pytest.raises(_Stop):
                runner.run_forever("KJFK")

        # First cycle on the seeded airport, second cycle forced by the switch.
        assert cycles == ["KJFK", "KEWR"]
        # The switch also logged an airport_switch shift event.
        switch_events = [
            e for e in read_recent(fake_redis) if e["kind"] == KIND_AIRPORT_SWITCH
        ]
        assert switch_events and switch_events[-1]["summary"].endswith("KEWR")

    def test_no_change_holds_cycle_cadence(self, fake_redis):
        """Without a switch and with the window not due, no extra cycle runs."""
        fake_redis.set(SELECTED_AIRPORT_KEY, "KJFK")
        cycles: list[str] = []

        class _Stop(Exception):
            pass

        sleep_calls = {"n": 0}

        def fake_sleep(_seconds):
            sleep_calls["n"] += 1
            if sleep_calls["n"] >= 3:
                raise _Stop()

        with (
            patch("modules.runner._build_redis_client", return_value=fake_redis),
            patch("modules.runner.time.sleep", side_effect=fake_sleep),
            patch(
                "modules.runner.run_cycle",
                side_effect=lambda a, _r: cycles.append(a),
            ),
            patch("modules.runner.time.monotonic", return_value=1000.0),
        ):
            with pytest.raises(_Stop):
                runner.run_forever("KJFK")

        # Only the initial seed cycle; the frozen clock means the 60 s window
        # never elapses and no switch occurred.
        assert cycles == ["KJFK"]
