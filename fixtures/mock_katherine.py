"""Mock Katherine — stand-in for the Orchestrator + Narrator LLM agents.

Standalone demo script. It listens to the three module topics so its output
references real recent events, then publishes:

  - every 45 s: an ESCALATE advisory (contact.md §3 schema) to
    ``towerguard:advisory``
  - every 90 s: a five-section handover briefing (contact.md §4 markdown) to
    ``towerguard:briefing``

It also stands in for the Orchestrator's shift-event log (contact.md §1,
``towerguard:shift_events`` Redis Stream). As tiers move on any module topic it
XADDs a ``tier_change`` event; each advisory and briefing it publishes also
gets an ``advisory`` / ``briefing`` shift event. The dashboard renders these as
a live shift log (and replays the most recent 20 on connect).

Briefing transport note: ``towerguard:briefing`` is a DEMO-INTERNAL topic
convention, not part of Katherine's frozen contract — the real briefing
transport is to be confirmed with Katherine (contact.md §4 only specifies the
markdown format, not the topic). The briefing payload here is shaped as
``{"advisory_id", "markdown"}`` to match the dashboard SSE contract.

Run alongside the runner and server:
    DEMO_MODE=1 python -m modules.runner          # produces conflicts
    python -m fixtures.mock_katherine             # produces advisories/briefings
    python -m dashboard.server                    # serves the dashboard
"""

import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any, Optional

import redis

import config
from dashboard.shift_stream import (
    KIND_ADVISORY,
    KIND_BRIEFING,
    KIND_TIER_CHANGE,
    xadd_shift_event,
)

logger = logging.getLogger(__name__)

TOPIC_TRAFFIC_DENSITY = "towerguard:traffic_density"
TOPIC_CONFLICT_GEOMETRY = "towerguard:conflict_geometry"
TOPIC_WORKLOAD_INDEX = "towerguard:workload_index"
TOPIC_ADVISORY = "towerguard:advisory"
TOPIC_BRIEFING = "towerguard:briefing"

# Module topics whose tier transitions feed the shift-event log.
_MODULE_TOPICS = (
    TOPIC_TRAFFIC_DENSITY,
    TOPIC_CONFLICT_GEOMETRY,
    TOPIC_WORKLOAD_INDEX,
)

# Human-readable module names for tier_change summaries.
_MODULE_LABELS = {
    TOPIC_TRAFFIC_DENSITY: "TRAFFIC DENSITY",
    TOPIC_CONFLICT_GEOMETRY: "CONFLICT GEOMETRY",
    TOPIC_WORKLOAD_INDEX: "WORKLOAD INDEX",
}

ADVISORY_INTERVAL_SECONDS = 45
BRIEFING_INTERVAL_SECONDS = 90

_AIRPORT = os.getenv("AIRPORT", config.DEFAULT_AIRPORT)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _build_redis_client() -> redis.Redis:
    url = os.getenv("REDIS_URL", config.REDIS_URL_DEFAULT)
    return redis.from_url(url, decode_responses=True)


class _ConflictTracker:
    """Holds the most recent conflict_geometry event seen on the wire."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._latest: Optional[dict[str, Any]] = None

    def update(self, event: dict[str, Any]) -> None:
        with self._lock:
            self._latest = event

    def latest(self) -> Optional[dict[str, Any]]:
        with self._lock:
            return dict(self._latest) if self._latest is not None else None


def _pair_suffix(event: dict[str, Any]) -> str:
    """Trailing ``(DMO901/DMO902)`` for a conflict event, or '' otherwise.

    Only conflict_geometry events carry a closest_pair; the suffix is dropped
    when there is no pair to name.
    """
    pair = event.get("closest_pair")
    if isinstance(pair, dict) and pair.get("callsigns"):
        return f" ({'/'.join(pair['callsigns'])})"
    return ""


def _build_tier_change_summary(
    topic: str, old_tier: str, new_tier: str, event: dict[str, Any]
) -> str:
    """e.g. ``CONFLICT GEOMETRY HIGH → CRITICAL (DMO901/DMO902)``."""
    label = _MODULE_LABELS.get(topic, topic)
    return f"{label} {old_tier} → {new_tier}{_pair_suffix(event)}"


def _maybe_log_tier_change(
    redis_client: redis.Redis,
    topic: str,
    event: dict[str, Any],
    last_tiers: dict[str, str],
) -> None:
    """XADD a tier_change shift event when ``topic``'s tier differs from before.

    The first event seen for a topic establishes a baseline without logging
    (there is no "previous" tier to transition from). ``ref`` is the module's
    alert_id so the dashboard can trace the change back to its source event.
    """
    new_tier = event.get("tier")
    if not isinstance(new_tier, str):
        return
    old_tier = last_tiers.get(topic)
    last_tiers[topic] = new_tier
    if old_tier is None or old_tier == new_tier:
        return
    summary = _build_tier_change_summary(topic, old_tier, new_tier, event)
    try:
        xadd_shift_event(
            redis_client,
            kind=KIND_TIER_CHANGE,
            summary=summary,
            ref=event.get("alert_id"),
        )
        logger.info("shift_event tier_change: %s", summary)
    except Exception as exc:
        logger.error("Failed to XADD tier_change: %s", exc)


def _listen_modules(redis_client: redis.Redis, tracker: _ConflictTracker) -> None:
    """Background thread: track module tiers and log tier_change shift events.

    Subscribes to all three module topics. Conflict events also refresh the
    tracker so advisories/briefings reference the latest conflict pair.
    """
    pubsub = redis_client.pubsub(ignore_subscribe_messages=True)
    pubsub.subscribe(*_MODULE_TOPICS)
    last_tiers: dict[str, str] = {}
    for raw in pubsub.listen():
        if raw.get("type") != "message":
            continue
        channel = _channel_name(raw.get("channel"))
        try:
            event = json.loads(raw["data"])
        except (ValueError, KeyError) as exc:
            logger.debug("skipping malformed module event: %s", exc)
            continue
        if channel == TOPIC_CONFLICT_GEOMETRY:
            tracker.update(event)
        _maybe_log_tier_change(redis_client, channel, event, last_tiers)


def _channel_name(channel: object) -> str:
    """Coerce a redis-py channel field (bytes or str) to str."""
    if isinstance(channel, bytes):
        return channel.decode("utf-8", errors="replace")
    return "" if channel is None else str(channel)


# ---------------------------------------------------------------------------
# Advisory (contact.md §3)
# ---------------------------------------------------------------------------


def build_advisory(
    advisory_id: str, conflict: Optional[dict[str, Any]]
) -> dict[str, Any]:
    """Build an ESCALATE advisory referencing the most recent conflict.

    Falls back to generic wording if no conflict has been seen yet.
    """
    now = _utc_now_iso()
    if conflict and conflict.get("closest_pair"):
        pair = conflict["closest_pair"]
        callsigns = "/".join(pair.get("callsigns", []))
        sep = pair.get("projected_separation_nm")
        ttv = pair.get("time_to_violation_seconds")
        attention = (
            f"{callsigns} pair approaching {sep}nm in {ttv}s, understaffed sector."
        )
        summary = "Projected separation violation detected with elevated workload."
    else:
        attention = "Elevated traffic and workload; monitor sector closely."
        summary = "Elevated workload with no confirmed separation conflict."

    return {
        "advisory_id": advisory_id,
        "timestamp": now,
        "airport": _AIRPORT,
        "action": "ESCALATE",
        "severity": "HIGH",
        "confidence": 0.9,
        "summary": summary,
        "contributing_signals": [
            "traffic_density",
            "conflict_geometry",
            "workload_index",
        ],
        "recommended_attention": attention,
        "human_override_required": True,
        "confirmed_by_controller": False,
        "generated_at": now,
    }


# ---------------------------------------------------------------------------
# Briefing (contact.md §4 — five-section markdown)
# ---------------------------------------------------------------------------


def build_briefing_markdown(
    advisory_id: str, conflict: Optional[dict[str, Any]]
) -> str:
    """Assemble the §4 five-section relief briefing markdown."""
    zulu = datetime.now(timezone.utc).strftime("%H%M")
    if conflict and conflict.get("closest_pair"):
        pair = conflict["closest_pair"]
        callsigns = "/".join(pair.get("callsigns", []))
        sep = pair.get("projected_separation_nm")
        ttv = pair.get("time_to_violation_seconds")
        conflict_line = (
            f"- {callsigns}: projected {sep} NM separation, first violation in {ttv} s."
        )
    else:
        conflict_line = "- No confirmed separation conflicts this period."

    return (
        f"---\n"
        f"## Position Relief Briefing — {_AIRPORT} {zulu}Z\n"
        f"*AI-generated draft. Outgoing controller must review and confirm.*\n\n"
        f"### 1. Current traffic picture\n"
        f"Sustained terminal traffic within 50 NM; mixed arrivals and departures.\n\n"
        f"### 2. Active advisories\n"
        f"- {advisory_id}: ESCALATE — review recommended attention items.\n\n"
        f"### 3. Notable events this shift\n"
        f"{conflict_line}\n\n"
        f"### 4. Weather and NOTAMs\n"
        f"VFR conditions, no active NOTAMs affecting the field (demo).\n\n"
        f"### 5. Pending actions\n"
        f"- Confirm outstanding advisories before relief.\n\n"
        f"---\n"
        f"*Reviewed and confirmed by: ________________  [TIME]__________*\n"
        f"---\n"
    )


def build_briefing_payload(
    advisory_id: str, conflict: Optional[dict[str, Any]]
) -> dict[str, str]:
    """Dashboard-contract briefing payload: {"advisory_id", "markdown"}."""
    return {
        "advisory_id": advisory_id,
        "markdown": build_briefing_markdown(advisory_id, conflict),
    }


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------


def _publish_advisory(redis_client: redis.Redis, advisory: dict[str, Any]) -> None:
    """Publish an advisory to its pub/sub topic and log it to the shift stream."""
    redis_client.publish(TOPIC_ADVISORY, json.dumps(advisory, separators=(",", ":")))
    try:
        xadd_shift_event(
            redis_client,
            kind=KIND_ADVISORY,
            summary=advisory.get("summary", "Advisory issued."),
            ref=advisory.get("advisory_id"),
        )
    except Exception as exc:
        logger.error("Failed to XADD advisory shift event: %s", exc)


def _publish_briefing(
    redis_client: redis.Redis, payload: dict[str, str], advisory_id: str
) -> None:
    """Publish a briefing to its pub/sub topic and log it to the shift stream."""
    redis_client.publish(TOPIC_BRIEFING, json.dumps(payload, separators=(",", ":")))
    try:
        xadd_shift_event(
            redis_client,
            kind=KIND_BRIEFING,
            summary=f"Position relief briefing generated for {advisory_id}",
            ref=advisory_id,
        )
    except Exception as exc:
        logger.error("Failed to XADD briefing shift event: %s", exc)


def run_forever() -> None:
    redis_client = _build_redis_client()
    tracker = _ConflictTracker()
    threading.Thread(
        target=_listen_modules,
        args=(redis_client, tracker),
        name="mock-katherine-modules",
        daemon=True,
    ).start()

    logger.info(
        "mock_katherine running — advisory every %ss, briefing every %ss",
        ADVISORY_INTERVAL_SECONDS,
        BRIEFING_INTERVAL_SECONDS,
    )

    counter = 0
    last_advisory_id = "ADV-0000"
    next_advisory = time.monotonic()
    next_briefing = time.monotonic() + BRIEFING_INTERVAL_SECONDS

    while True:
        now = time.monotonic()

        if now >= next_advisory:
            counter += 1
            last_advisory_id = f"ADV-{counter:04d}"
            advisory = build_advisory(last_advisory_id, tracker.latest())
            _publish_advisory(redis_client, advisory)
            logger.info("Published advisory %s", last_advisory_id)
            next_advisory = now + ADVISORY_INTERVAL_SECONDS

        if now >= next_briefing:
            payload = build_briefing_payload(last_advisory_id, tracker.latest())
            _publish_briefing(redis_client, payload, last_advisory_id)
            logger.info("Published briefing for %s", last_advisory_id)
            next_briefing = now + BRIEFING_INTERVAL_SECONDS

        time.sleep(1.0)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    run_forever()
