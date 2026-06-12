"""
TowerGuard runner — W1-5.

Loop (per cycle):
  1. Fetch OpenSky state vectors once (fan-out to all three modules)
  2. Compute Traffic Density, Conflict Geometry, Workload Index
  3. Publish each as JSON to its Redis pub/sub topic

Cadence (functional A): the runner does not block for a full 60 s between
cycles. It wakes every RUNNER_POLL_SECONDS to read towerguard:selected_airport
(set by the dashboard). If the airport changed it runs an immediate cycle for
the new airport — re-anchoring the DEMO fleet, resetting the converging-pair
state, and writing an airport_switch shift event — instead of waiting out the
remaining 60 s. With no change it keeps the 60 s publish cadence.
"""

import json
import logging
import os
import time
from typing import Any, Optional

import redis

import config
from dashboard.shift_stream import KIND_AIRPORT_SWITCH, xadd_shift_event
from dashboard.topics import SELECTED_AIRPORT_KEY
from data.opensky import OpenSkyUnavailable, fetch_states
from modules import conflict_geometry, traffic_density, workload_index
from modules.envelope import to_json, utc_now_iso

logger = logging.getLogger(__name__)

# Redis topic names per §1
TOPIC_TRAFFIC_DENSITY = "towerguard:traffic_density"
TOPIC_CONFLICT_GEOMETRY = "towerguard:conflict_geometry"
TOPIC_WORKLOAD_INDEX = "towerguard:workload_index"
# Demo-internal topic — NOT in Katherine's contract (contact.md §1). The
# dashboard subscribes to this to render a live aircraft map; the snapshot
# payload schema is a demo convention, not part of the frozen module envelopes.
TOPIC_AIRCRAFT_SNAPSHOT = "towerguard:aircraft_snapshot"


def _build_redis_client() -> redis.Redis:
    url = os.getenv("REDIS_URL", config.REDIS_URL_DEFAULT)
    return redis.from_url(url, decode_responses=True)


def _demo_mode_enabled() -> bool:
    """True when DEMO_MODE=1 — read fixtures instead of calling OpenSky."""
    return os.getenv("DEMO_MODE") == "1"


def _fetch_states_for_cycle(airport_icao: str) -> Optional[list]:
    """Return state vectors for this cycle, or None if upstream is unavailable.

    In DEMO_MODE the OpenSky call is bypassed entirely and synthetic state
    vectors (jittered fixture + a guaranteed converging pair) are returned.
    """
    if _demo_mode_enabled():
        from config import AIRPORTS
        from modules.demo_source import demo_states

        airport = AIRPORTS.get(airport_icao)
        if airport is None:
            logger.warning("DEMO_MODE: unknown airport %s", airport_icao)
            return None
        states = demo_states(airport.lat, airport.lon)
        logger.info("DEMO_MODE: synthesized %d state vectors", len(states))
        return states

    try:
        states = fetch_states(airport_icao)
        logger.info("Fetched %d state vectors for %s", len(states), airport_icao)
        return states
    except OpenSkyUnavailable as exc:
        logger.warning("OpenSky unavailable: %s — publishing UNKNOWN events", exc)
        return None


def _build_snapshot(airport_icao: str, states: list[dict[str, Any]]) -> dict[str, Any]:
    """Build an aircraft_snapshot payload from parsed state vectors.

    Demo-internal schema (TOPIC_AIRCRAFT_SNAPSHOT). lat/lon are the raw parsed
    degrees; alt_ft is geo_altitude and velocity_kt is velocity, both already in
    feet / knots after the metric conversions done at the parse boundary.
    """
    aircraft = [
        {
            "icao24": s.get("icao24"),
            "callsign": (s.get("callsign") or "").strip(),
            "lat": s.get("latitude"),
            "lon": s.get("longitude"),
            "alt_ft": s.get("geo_altitude"),
            "velocity_kt": s.get("velocity"),
            "heading": s.get("true_track"),
        }
        for s in states
    ]
    return {
        "airport": airport_icao,
        "timestamp": utc_now_iso(),
        "aircraft": aircraft,
    }


def run_cycle(
    airport_icao: str,
    redis_client: redis.Redis,
) -> None:
    """Execute one full data-fetch → compute → publish cycle.

    On OpenSky failure, all three modules emit data_unavailable events.
    """
    # --- Fetch (single call, fan-out) ---
    states: Optional[list] = _fetch_states_for_cycle(airport_icao)

    # --- Compute ---
    if states is not None:
        td_event = traffic_density.compute(airport_icao, states)
        cg_event = conflict_geometry.compute(airport_icao, states)
    else:
        td_event = traffic_density.compute_unavailable(airport_icao)
        cg_event = conflict_geometry.compute_unavailable(airport_icao)

    # Workload Index never depends on live data
    wi_event = workload_index.compute(airport_icao)

    # --- Publish contract topics (unchanged behaviour) ---
    _publish(redis_client, TOPIC_TRAFFIC_DENSITY, td_event)
    _publish(redis_client, TOPIC_CONFLICT_GEOMETRY, cg_event)
    _publish(redis_client, TOPIC_WORKLOAD_INDEX, wi_event)

    # --- Publish demo-internal aircraft snapshot for the dashboard map ---
    # Only when live data exists; an UNKNOWN cycle has no positions to draw.
    if states is not None:
        snapshot = _build_snapshot(airport_icao, states)
        _publish_raw(redis_client, TOPIC_AIRCRAFT_SNAPSHOT, snapshot)


def _publish(
    redis_client: redis.Redis,
    topic: str,
    event: dict,
) -> None:
    """Validate and publish an event dict to a Redis pub/sub channel."""
    try:
        payload = to_json(event)  # validate_envelope called inside to_json
        redis_client.publish(topic, payload)
        logger.debug("Published to %s: tier=%s", topic, event.get("tier"))
    except Exception as exc:
        logger.error("Failed to publish to %s: %s", topic, exc)


def _publish_raw(
    redis_client: redis.Redis,
    topic: str,
    payload_obj: dict,
) -> None:
    """Publish a non-envelope dict (e.g. aircraft snapshot) as compact JSON.

    Skips envelope validation — the snapshot is a demo-internal payload, not a
    contract module event.
    """
    try:
        redis_client.publish(topic, json.dumps(payload_obj, separators=(",", ":")))
        logger.debug(
            "Published to %s: %d aircraft", topic, len(payload_obj.get("aircraft", []))
        )
    except Exception as exc:
        logger.error("Failed to publish to %s: %s", topic, exc)


def _read_selected_airport(
    redis_client: redis.Redis,
    fallback: str,
) -> str:
    """Return the dashboard-selected airport, or ``fallback`` if unset/unknown.

    A missing key, a Redis error, or an ICAO not in config all resolve to the
    fallback so the runner never targets an airport it cannot serve.
    """
    try:
        selected = redis_client.get(SELECTED_AIRPORT_KEY)
    except Exception as exc:
        logger.warning("Could not read selected airport: %s", exc)
        return fallback
    if selected in config.AIRPORTS:
        return selected
    return fallback


def _on_airport_switch(redis_client: redis.Redis, new_airport: str) -> None:
    """Re-anchor the DEMO fleet and log the switch as a shift event.

    Resetting the converging-pair state makes the synthetic fleet re-spawn at
    the new airport's coordinates on the next cycle (the cycle re-anchors via
    the airport's lat/lon); the airport_switch shift event records the change.
    """
    from modules.demo_source import reset_converge_state

    reset_converge_state()
    try:
        xadd_shift_event(
            redis_client,
            kind=KIND_AIRPORT_SWITCH,
            summary=f"Monitoring switched to {new_airport}",
            ref=None,
        )
    except Exception as exc:
        logger.error("Failed to write airport_switch shift event: %s", exc)


def run_forever(airport_icao: str = config.DEFAULT_AIRPORT) -> None:
    """Main loop — runs until interrupted.

    Wakes every RUNNER_POLL_SECONDS to check the dashboard-selected airport. A
    change runs an immediate cycle for the new airport; otherwise a full cycle
    fires once RUNNER_CYCLE_SECONDS has elapsed since the last one.
    """
    # DEMO_MODE never calls OpenSky, so it does not require OpenSky credentials.
    if not _demo_mode_enabled():
        config.validate_env()
    r = _build_redis_client()
    # Seed the selection from Redis so a value set before start is honoured;
    # the CLI/default airport is the fallback.
    current_airport = _read_selected_airport(r, airport_icao)
    logger.info(
        "TowerGuard runner starting — airport=%s, cycle=%ss, poll=%ss, demo=%s",
        current_airport,
        config.RUNNER_CYCLE_SECONDS,
        config.RUNNER_POLL_SECONDS,
        _demo_mode_enabled(),
    )

    last_cycle_at = -float("inf")  # force a cycle on the first iteration
    while True:
        selected = _read_selected_airport(r, current_airport)
        switched = selected != current_airport
        if switched:
            logger.info("Airport switch detected: %s → %s", current_airport, selected)
            current_airport = selected
            _on_airport_switch(r, current_airport)

        due = (time.monotonic() - last_cycle_at) >= config.RUNNER_CYCLE_SECONDS
        if switched or due:
            try:
                run_cycle(current_airport, r)
            except Exception as exc:
                logger.error("Unexpected error in cycle: %s", exc, exc_info=True)
            last_cycle_at = time.monotonic()

        time.sleep(config.RUNNER_POLL_SECONDS)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    run_forever()
