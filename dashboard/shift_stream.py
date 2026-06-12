"""Shift-events Redis Stream contract (contact.md §1, `towerguard:shift_events`).

This is the one place the four-field XADD schema lives, shared by every writer
(mock_katherine, runner) and the reader (bridge). The contract froze the entry
shape with the frontend agent:

    {"timestamp": "<ISO8601Z>", "kind": "<str>", "summary": "<str>",
     "ref": "<str|null>"}

`kind` ∈ {tier_change, advisory, briefing, airport_switch}. A null `ref` is
written as the literal string ``"null"`` on the wire (Redis Stream fields are
strings) and decoded back to ``None`` on read, so the SSE payload matches the
JSON contract exactly.
"""

from datetime import datetime, timezone
from typing import Any, Optional

import redis

# Redis Stream key (contract §1). Stream, not pub/sub: it accumulates the whole
# shift so a late subscriber (or a freshly opened dashboard) can replay it.
SHIFT_EVENTS_KEY = "towerguard:shift_events"

# Approximate cap on retained entries; XADD trims with MAXLEN ~ so Redis can
# drop in efficient whole-node chunks rather than exact-trimming every add.
SHIFT_EVENTS_MAXLEN = 200

# Replay count for a newly connected SSE client (contract: most recent 20).
SHIFT_EVENTS_REPLAY_COUNT = 20

# `kind` values (contract-frozen).
KIND_TIER_CHANGE = "tier_change"
KIND_ADVISORY = "advisory"
KIND_BRIEFING = "briefing"
KIND_AIRPORT_SWITCH = "airport_switch"

# Sentinel written for a null ref (stream fields cannot be None).
_NULL_REF = "null"


def _utc_now_iso() -> str:
    """Current UTC time as ISO 8601 (matches the module envelope format)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def xadd_shift_event(
    redis_client: redis.Redis,
    *,
    kind: str,
    summary: str,
    ref: Optional[str] = None,
    timestamp: Optional[str] = None,
) -> str:
    """Append one shift event to the stream, returning the entry id.

    ``timestamp`` defaults to now (UTC ISO 8601). ``ref=None`` is stored as the
    ``"null"`` sentinel and decoded back to None by ``decode_entry``.
    """
    fields = {
        "timestamp": timestamp or _utc_now_iso(),
        "kind": kind,
        "summary": summary,
        "ref": _NULL_REF if ref is None else ref,
    }
    return redis_client.xadd(
        SHIFT_EVENTS_KEY, fields, maxlen=SHIFT_EVENTS_MAXLEN, approximate=True
    )


def decode_entry(fields: dict[Any, Any]) -> dict[str, Any]:
    """Decode a raw stream entry's fields into the SSE contract shape.

    Coerces bytes→str (so it works whether or not the client uses
    decode_responses) and maps the ``"null"`` ref sentinel back to None.
    """
    decoded = {_as_str(k): _as_str(v) for k, v in fields.items()}
    ref = decoded.get("ref", _NULL_REF)
    return {
        "timestamp": decoded.get("timestamp", ""),
        "kind": decoded.get("kind", ""),
        "summary": decoded.get("summary", ""),
        "ref": None if ref == _NULL_REF else ref,
    }


def read_recent(
    redis_client: redis.Redis,
    count: int = SHIFT_EVENTS_REPLAY_COUNT,
) -> list[dict[str, Any]]:
    """Return the most recent ``count`` shift events in time order (oldest→newest).

    Uses XREVRANGE to grab the tail efficiently, then reverses so replay reaches
    a new client chronologically.
    """
    raw = redis_client.xrevrange(SHIFT_EVENTS_KEY, count=count)
    return [decode_entry(fields) for _entry_id, fields in reversed(raw)]


def _as_str(value: object) -> str:
    """Coerce a redis-py field (bytes or str depending on decode_responses)."""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return "" if value is None else str(value)
