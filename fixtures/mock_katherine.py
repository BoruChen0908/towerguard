"""Mock Katherine — stand-in for the Orchestrator + Narrator LLM agents (v1.2).

Condition-driven (design §3/§6): the old 45-second advisory timer is gone. This
process subscribes to the three module topics and the re-assess request channel,
keeps the latest module state, and lets ``AdvisoryEngine`` decide when to issue
an advisory — re-surfacing only on a change in the world, never on the passage
of time. It also stands in for the Narrator, assembling the five-section relief
briefing dynamically from the real shift-events log on a slow cadence (or right
after a re-assess / supersede / resolve), so every render reflects the shift.

Transport responsibilities (unchanged contract surfaces):
  - tier_change shift events as module tiers move (now carrying the new tier)
  - advisory / lifecycle publish + shift events come from the engine
  - briefing publish to ``towerguard:briefing`` ({"advisory_id","markdown",
    "briefing_id"}; briefing transport is still a demo-internal convention)

Run alongside the runner and server:
    DEMO_MODE=1 python -m modules.runner          # produces module events
    python -m fixtures.mock_katherine             # condition-driven advisories
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
    KIND_TIER_CHANGE,
    read_recent,
    xadd_shift_event,
)
from dashboard.topics import (
    TOPIC_BRIEFING,
    TOPIC_CONFLICT_GEOMETRY,
    TOPIC_REASSESS_REQUEST,
    TOPIC_TRAFFIC_DENSITY,
    TOPIC_WORKLOAD_INDEX,
)
from fixtures import advisory_briefing
from fixtures.advisory_engine import (
    CONFIRMED_KEY_PREFIX,
    DISMISSED_KEY_PREFIX,
    AdvisoryEngine,
)

logger = logging.getLogger(__name__)

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

# Briefing cadence: slow steady refresh; a re-assess / supersede / resolve also
# triggers an out-of-band briefing so the narrative tracks the world (design §6).
BRIEFING_INTERVAL_SECONDS = 120

_AIRPORT = os.getenv("AIRPORT", config.DEFAULT_AIRPORT)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _build_redis_client() -> redis.Redis:
    url = os.getenv("REDIS_URL", config.REDIS_URL_DEFAULT)
    return redis.from_url(url, decode_responses=True)


def _channel_name(channel: object) -> str:
    """Coerce a redis-py channel field (bytes or str) to str."""
    if isinstance(channel, bytes):
        return channel.decode("utf-8", errors="replace")
    return "" if channel is None else str(channel)


# ---------------------------------------------------------------------------
# tier_change shift events (now carrying the new tier — v1.2 §5)
# ---------------------------------------------------------------------------


def _pair_suffix(event: dict[str, Any]) -> str:
    """Trailing ``(DMO901/DMO902)`` for a conflict event, or '' otherwise."""
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

    The first event seen for a topic establishes a baseline without logging.
    ``ref`` is the module's alert_id; ``tier`` (v1.2) is the new tier so the
    event strip can colour the row.
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
            tier=new_tier,
        )
        logger.info("shift_event tier_change: %s", summary)
    except Exception as exc:
        logger.error("Failed to XADD tier_change: %s", exc)


# ---------------------------------------------------------------------------
# Briefing (dynamic — design §6)
# ---------------------------------------------------------------------------


def _decision_of(redis_client: redis.Redis):
    """Return a callback advisory_id → confirmed|dismissed|pending.

    Reads the dashboard-owned decision keys so the briefing can flag each active
    advisory ✓ / ✕ / pending.
    """

    def lookup(advisory_id: str) -> str:
        try:
            if redis_client.get(f"{CONFIRMED_KEY_PREFIX}{advisory_id}") is not None:
                return advisory_briefing.DECISION_CONFIRMED
            if redis_client.get(f"{DISMISSED_KEY_PREFIX}{advisory_id}") is not None:
                return advisory_briefing.DECISION_DISMISSED
        except Exception as exc:  # pragma: no cover - redis blip
            logger.warning("decision lookup failed for %s: %s", advisory_id, exc)
        return advisory_briefing.DECISION_PENDING

    return lookup


def _next_briefing_id(counter: int) -> str:
    return f"BRF-{counter:04d}"


def publish_briefing(
    redis_client: redis.Redis,
    briefing_id: str,
    airport: str,
) -> None:
    """Assemble a dynamic briefing from the shift log and publish it.

    The five sections are generated from read_recent shift events plus the live
    decision keys, so the markdown reflects the actual shift each render.
    """
    events = read_recent(redis_client, count=50)
    payload = advisory_briefing.build_briefing_payload(
        briefing_id=briefing_id,
        airport=airport,
        events=events,
        decision_of=_decision_of(redis_client),
    )
    try:
        from dashboard.shift_stream import KIND_BRIEFING

        redis_client.publish(TOPIC_BRIEFING, json.dumps(payload, separators=(",", ":")))
        xadd_shift_event(
            redis_client,
            kind=KIND_BRIEFING,
            summary=f"Relief briefing {briefing_id} assembled from shift log",
            ref=briefing_id,
        )
        logger.info("Published briefing %s", briefing_id)
    except Exception as exc:
        logger.error("Failed to publish briefing: %s", exc)


# ---------------------------------------------------------------------------
# Subscription threads
# ---------------------------------------------------------------------------


def _poll_messages(pubsub: redis.client.PubSub):
    """Yield pub/sub messages via get_message polling.

    redis-py >= 8 applies a default socket timeout, so a blocking listen()
    raises TimeoutError on a quiet subscription (same fix as dashboard.bridge).
    """
    while True:
        try:
            raw = pubsub.get_message(timeout=1.0)
        except TimeoutError:
            continue
        except Exception as exc:
            logger.error("pubsub poll error: %s", exc, exc_info=True)
            time.sleep(1.0)
            continue
        if raw is None:
            continue
        yield raw


def _listen_modules(
    redis_client: redis.Redis,
    engine: AdvisoryEngine,
) -> None:
    """Background thread: feed module events to the engine + log tier changes.

    Every conflict_geometry event drives a rule evaluation (design §6); traffic
    and workload events only update the engine's latest-state snapshot. All three
    feed tier_change shift events.
    """
    pubsub = redis_client.pubsub(ignore_subscribe_messages=True)
    pubsub.subscribe(*_MODULE_TOPICS)
    last_tiers: dict[str, str] = {}
    for raw in _poll_messages(pubsub):
        if raw.get("type") != "message":
            continue
        channel = _channel_name(raw.get("channel"))
        try:
            event = json.loads(raw["data"])
        except (ValueError, KeyError) as exc:
            logger.debug("skipping malformed module event: %s", exc)
            continue
        engine.update_module(channel, event)
        if channel == TOPIC_CONFLICT_GEOMETRY:
            engine.on_conflict_event(event)
        _maybe_log_tier_change(redis_client, channel, event, last_tiers)


def _listen_reassess(
    redis_client: redis.Redis,
    engine: AdvisoryEngine,
    on_handled: Optional[Any] = None,
) -> None:
    """Background thread: handle re-assess requests — engine always replies."""
    pubsub = redis_client.pubsub(ignore_subscribe_messages=True)
    pubsub.subscribe(TOPIC_REASSESS_REQUEST)
    for raw in _poll_messages(pubsub):
        if raw.get("type") != "message":
            continue
        try:
            request = json.loads(raw["data"])
        except (ValueError, KeyError) as exc:
            logger.debug("skipping malformed reassess request: %s", exc)
            continue
        try:
            engine.on_reassess_request(request)
            if on_handled is not None:
                on_handled()
        except Exception as exc:
            logger.error("reassess handling failed: %s", exc)


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------


def run_forever() -> None:
    redis_client = _build_redis_client()
    engine = AdvisoryEngine(redis_client, _AIRPORT)

    # A re-assess sets this so the main loop emits an out-of-band briefing.
    briefing_due = threading.Event()

    threading.Thread(
        target=_listen_modules,
        args=(redis_client, engine),
        name="mock-katherine-modules",
        daemon=True,
    ).start()
    threading.Thread(
        target=_listen_reassess,
        args=(redis_client, engine, briefing_due.set),
        name="mock-katherine-reassess",
        daemon=True,
    ).start()

    logger.info(
        "mock_katherine (v1.2 condition-driven) running — briefing every %ss "
        "or on re-assess",
        BRIEFING_INTERVAL_SECONDS,
    )

    counter = 0
    next_briefing = time.monotonic()
    while True:
        now = time.monotonic()
        if now >= next_briefing or briefing_due.is_set():
            briefing_due.clear()
            counter += 1
            publish_briefing(redis_client, _next_briefing_id(counter), _AIRPORT)
            next_briefing = time.monotonic() + BRIEFING_INTERVAL_SECONDS
        time.sleep(1.0)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    run_forever()
