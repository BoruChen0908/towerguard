"""
Shared envelope builder and schema validator for all TowerGuard module events.

Contract reference: contact.md §2 — envelope fields are frozen; field names
must not deviate.
"""

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Alert ID counters — per-prefix, resets on restart (demo-acceptable per spec)
# ---------------------------------------------------------------------------
_counters: dict[str, int] = {"TD": 0, "CG": 0, "WI": 0}

VALID_PREFIXES = frozenset({"TD", "CG", "WI"})
VALID_TIERS = frozenset({"LOW", "MEDIUM", "HIGH", "CRITICAL", "UNKNOWN"})
VALID_EVENT_TYPES = frozenset(
    {"traffic_density", "conflict_geometry", "workload_index"}
)


def next_alert_id(prefix: str) -> str:
    """Return next alert ID for the given prefix (e.g. 'TD-0001').

    Thread-safety: not required — runner is single-threaded.
    """
    if prefix not in VALID_PREFIXES:
        raise ValueError(f"Unknown alert prefix: {prefix!r}")
    _counters[prefix] += 1
    return f"{prefix}-{_counters[prefix]:04d}"


def utc_now_iso() -> str:
    """Return current UTC time as ISO 8601 string."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Frozen envelope dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Envelope:
    """Immutable top-level envelope shared by all three module events.

    Fields mirror contact.md §2 exactly — do not rename.
    """

    event_type: str
    alert_id: str
    airport: str
    timestamp: str
    tier: str
    data_unavailable: bool


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class EnvelopeValidationError(ValueError):
    """Raised when an event dict fails schema validation."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise EnvelopeValidationError(message)


def validate_envelope(event: dict[str, Any]) -> None:
    """Validate the envelope fields of a module event dict.

    Raises EnvelopeValidationError on any schema violation.
    Called before publishing to Redis.
    """
    _require("event_type" in event, "Missing field: event_type")
    _require("alert_id" in event, "Missing field: alert_id")
    _require("airport" in event, "Missing field: airport")
    _require("timestamp" in event, "Missing field: timestamp")
    _require("tier" in event, "Missing field: tier")
    _require("data_unavailable" in event, "Missing field: data_unavailable")

    _require(
        event["event_type"] in VALID_EVENT_TYPES,
        f"Invalid event_type: {event['event_type']!r}",
    )
    _require(
        event["tier"] in VALID_TIERS,
        f"Invalid tier: {event['tier']!r}",
    )
    _require(
        isinstance(event["data_unavailable"], bool),
        "data_unavailable must be a bool",
    )

    # Invariant §6: data_unavailable=true forces tier=UNKNOWN
    if event["data_unavailable"]:
        _require(
            event["tier"] == "UNKNOWN",
            "data_unavailable=true requires tier='UNKNOWN' (§6)",
        )

    # Invariant: UNKNOWN tier requires data_unavailable=true
    if event["tier"] == "UNKNOWN":
        _require(
            event["data_unavailable"] is True,
            "tier='UNKNOWN' requires data_unavailable=true (§2a)",
        )


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------


def to_json(event: dict[str, Any]) -> str:
    """Validate and serialise an event dict to a JSON string."""
    validate_envelope(event)
    return json.dumps(event, separators=(",", ":"))


def build_unavailable_base(
    *,
    event_type: str,
    prefix: str,
    airport: str,
) -> dict[str, Any]:
    """Build the minimal data-unavailable envelope (tier=UNKNOWN, score=null).

    Callers must merge module-specific fields on top.
    """
    return {
        "event_type": event_type,
        "alert_id": next_alert_id(prefix),
        "airport": airport,
        "timestamp": utc_now_iso(),
        "tier": "UNKNOWN",
        "data_unavailable": True,
    }
