"""Tests for modules/envelope.py — alert ID generation, validation, serialisation."""

import json

import pytest

from modules.envelope import (
    EnvelopeValidationError,
    build_unavailable_base,
    next_alert_id,
    to_json,
    validate_envelope,
)


# ---------------------------------------------------------------------------
# Alert ID generation
# ---------------------------------------------------------------------------


class TestNextAlertId:
    def test_td_increments(self):
        # Read current counter state by calling twice
        id1 = next_alert_id("TD")
        id2 = next_alert_id("TD")
        n1 = int(id1.split("-")[1])
        n2 = int(id2.split("-")[1])
        assert n2 == n1 + 1

    def test_prefix_format(self):
        alert_id = next_alert_id("CG")
        assert alert_id.startswith("CG-")
        assert len(alert_id) == 7  # "CG-" + 4 digits

    def test_wi_prefix(self):
        alert_id = next_alert_id("WI")
        assert alert_id.startswith("WI-")

    def test_unknown_prefix_raises(self):
        with pytest.raises(ValueError, match="Unknown alert prefix"):
            next_alert_id("XX")

    def test_four_digit_padding(self):
        # Call enough times to see padding (counters start at 0)
        # Just check format is always 4 digits for a fresh-ish counter
        alert_id = next_alert_id("TD")
        num_part = alert_id.split("-")[1]
        assert len(num_part) == 4


# ---------------------------------------------------------------------------
# validate_envelope
# ---------------------------------------------------------------------------


def _valid_event() -> dict:
    return {
        "event_type": "traffic_density",
        "alert_id": "TD-0001",
        "airport": "KJFK",
        "timestamp": "2026-06-12T00:00:00Z",
        "tier": "LOW",
        "data_unavailable": False,
    }


class TestValidateEnvelope:
    def test_valid_passes(self):
        validate_envelope(_valid_event())  # no exception

    def test_missing_tier_raises(self):
        event = _valid_event()
        del event["tier"]
        with pytest.raises(EnvelopeValidationError, match="Missing field: tier"):
            validate_envelope(event)

    def test_missing_data_unavailable_raises(self):
        event = _valid_event()
        del event["data_unavailable"]
        with pytest.raises(
            EnvelopeValidationError, match="Missing field: data_unavailable"
        ):
            validate_envelope(event)

    def test_missing_event_type_raises(self):
        event = _valid_event()
        del event["event_type"]
        with pytest.raises(EnvelopeValidationError):
            validate_envelope(event)

    def test_invalid_tier_raises(self):
        event = _valid_event()
        event["tier"] = "EXTREME"
        with pytest.raises(EnvelopeValidationError, match="Invalid tier"):
            validate_envelope(event)

    def test_data_unavailable_true_requires_unknown_tier(self):
        event = _valid_event()
        event["data_unavailable"] = True
        event["tier"] = "LOW"  # violation: should be UNKNOWN
        with pytest.raises(
            EnvelopeValidationError, match="data_unavailable=true requires tier"
        ):
            validate_envelope(event)

    def test_unknown_tier_requires_data_unavailable_true(self):
        event = _valid_event()
        event["tier"] = "UNKNOWN"
        event["data_unavailable"] = False
        with pytest.raises(EnvelopeValidationError, match="tier='UNKNOWN' requires"):
            validate_envelope(event)

    def test_data_unavailable_true_with_unknown_tier_passes(self):
        event = _valid_event()
        event["data_unavailable"] = True
        event["tier"] = "UNKNOWN"
        validate_envelope(event)  # no exception

    def test_all_valid_tiers_pass(self):
        for tier in ("LOW", "MEDIUM", "HIGH", "CRITICAL"):
            event = _valid_event()
            event["tier"] = tier
            validate_envelope(event)  # no exception


# ---------------------------------------------------------------------------
# build_unavailable_base
# ---------------------------------------------------------------------------


class TestBuildUnavailableBase:
    def test_returns_unknown_tier(self):
        base = build_unavailable_base(
            event_type="traffic_density",
            prefix="TD",
            airport="KJFK",
        )
        assert base["tier"] == "UNKNOWN"
        assert base["data_unavailable"] is True

    def test_event_type_set(self):
        base = build_unavailable_base(
            event_type="conflict_geometry",
            prefix="CG",
            airport="KATL",
        )
        assert base["event_type"] == "conflict_geometry"
        assert base["airport"] == "KATL"

    def test_alert_id_generated(self):
        base = build_unavailable_base(
            event_type="workload_index",
            prefix="WI",
            airport="KBOS",
        )
        assert base["alert_id"].startswith("WI-")


# ---------------------------------------------------------------------------
# to_json / serialisation
# ---------------------------------------------------------------------------


class TestToJson:
    def test_valid_serialises_to_json(self):
        event = _valid_event()
        result = to_json(event)
        parsed = json.loads(result)
        assert parsed["tier"] == "LOW"
        assert parsed["airport"] == "KJFK"

    def test_invalid_raises_before_serialising(self):
        event = _valid_event()
        del event["tier"]
        with pytest.raises(EnvelopeValidationError):
            to_json(event)
