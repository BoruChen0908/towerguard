"""Mock Katherine — stand-in for the Orchestrator + Narrator LLM agents.

Standalone demo script. It listens to the live conflict_geometry topic so its
output references real recent events, then publishes:

  - every 45 s: an ESCALATE advisory (contact.md §3 schema) to
    ``towerguard:advisory``
  - every 90 s: a five-section handover briefing (contact.md §4 markdown) to
    ``towerguard:briefing``

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

logger = logging.getLogger(__name__)

TOPIC_CONFLICT_GEOMETRY = "towerguard:conflict_geometry"
TOPIC_ADVISORY = "towerguard:advisory"
TOPIC_BRIEFING = "towerguard:briefing"

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


def _listen_conflicts(redis_client: redis.Redis, tracker: _ConflictTracker) -> None:
    """Background thread: keep the tracker's latest conflict event fresh."""
    pubsub = redis_client.pubsub(ignore_subscribe_messages=True)
    pubsub.subscribe(TOPIC_CONFLICT_GEOMETRY)
    for raw in pubsub.listen():
        if raw.get("type") != "message":
            continue
        try:
            tracker.update(json.loads(raw["data"]))
        except (ValueError, KeyError) as exc:
            logger.debug("skipping malformed conflict event: %s", exc)


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


def run_forever() -> None:
    redis_client = _build_redis_client()
    tracker = _ConflictTracker()
    threading.Thread(
        target=_listen_conflicts,
        args=(redis_client, tracker),
        name="mock-katherine-conflicts",
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
            redis_client.publish(
                TOPIC_ADVISORY, json.dumps(advisory, separators=(",", ":"))
            )
            logger.info("Published advisory %s", last_advisory_id)
            next_advisory = now + ADVISORY_INTERVAL_SECONDS

        if now >= next_briefing:
            payload = build_briefing_payload(last_advisory_id, tracker.latest())
            redis_client.publish(
                TOPIC_BRIEFING, json.dumps(payload, separators=(",", ":"))
            )
            logger.info("Published briefing for %s", last_advisory_id)
            next_briefing = now + BRIEFING_INTERVAL_SECONDS

        time.sleep(1.0)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    run_forever()
