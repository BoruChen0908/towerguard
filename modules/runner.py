"""
TowerGuard runner — W1-5.

60-second synchronous loop:
  1. Fetch OpenSky state vectors once (fan-out to all three modules)
  2. Compute Traffic Density, Conflict Geometry, Workload Index
  3. Publish each as JSON to its Redis pub/sub topic
  4. Sleep until next cycle
"""

import json
import logging
import os
import time
from typing import Any, Optional

import redis

import config
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


def run_forever(airport_icao: str = config.DEFAULT_AIRPORT) -> None:
    """Main loop — runs until interrupted."""
    # DEMO_MODE never calls OpenSky, so it does not require OpenSky credentials.
    if not _demo_mode_enabled():
        config.validate_env()
    r = _build_redis_client()
    logger.info(
        "TowerGuard runner starting — airport=%s, cycle=%ss, demo=%s",
        airport_icao,
        config.RUNNER_CYCLE_SECONDS,
        _demo_mode_enabled(),
    )

    while True:
        cycle_start = time.monotonic()
        try:
            run_cycle(airport_icao, r)
        except Exception as exc:
            logger.error("Unexpected error in cycle: %s", exc, exc_info=True)

        elapsed = time.monotonic() - cycle_start
        sleep_for = max(0.0, config.RUNNER_CYCLE_SECONDS - elapsed)
        logger.debug("Cycle took %.2fs; sleeping %.2fs", elapsed, sleep_for)
        time.sleep(sleep_for)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    run_forever()
