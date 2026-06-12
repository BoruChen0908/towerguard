"""
TowerGuard runner — W1-5.

60-second synchronous loop:
  1. Fetch OpenSky state vectors once (fan-out to all three modules)
  2. Compute Traffic Density, Conflict Geometry, Workload Index
  3. Publish each as JSON to its Redis pub/sub topic
  4. Sleep until next cycle
"""

import logging
import os
import time
from typing import Optional

import redis

import config
from data.opensky import OpenSkyUnavailable, fetch_states
from modules import conflict_geometry, traffic_density, workload_index
from modules.envelope import to_json

logger = logging.getLogger(__name__)

# Redis topic names per §1
TOPIC_TRAFFIC_DENSITY = "towerguard:traffic_density"
TOPIC_CONFLICT_GEOMETRY = "towerguard:conflict_geometry"
TOPIC_WORKLOAD_INDEX = "towerguard:workload_index"


def _build_redis_client() -> redis.Redis:
    url = os.getenv("REDIS_URL", config.REDIS_URL_DEFAULT)
    return redis.from_url(url, decode_responses=True)


def run_cycle(
    airport_icao: str,
    redis_client: redis.Redis,
) -> None:
    """Execute one full data-fetch → compute → publish cycle.

    On OpenSky failure, all three modules emit data_unavailable events.
    """
    # --- Fetch (single call, fan-out) ---
    states: Optional[list] = None
    try:
        states = fetch_states(airport_icao)
        logger.info("Fetched %d state vectors for %s", len(states), airport_icao)
    except OpenSkyUnavailable as exc:
        logger.warning("OpenSky unavailable: %s — publishing UNKNOWN events", exc)

    # --- Compute ---
    if states is not None:
        td_event = traffic_density.compute(airport_icao, states)
        cg_event = conflict_geometry.compute(airport_icao, states)
    else:
        td_event = traffic_density.compute_unavailable(airport_icao)
        cg_event = conflict_geometry.compute_unavailable(airport_icao)

    # Workload Index never depends on live data
    wi_event = workload_index.compute(airport_icao)

    # --- Publish ---
    _publish(redis_client, TOPIC_TRAFFIC_DENSITY, td_event)
    _publish(redis_client, TOPIC_CONFLICT_GEOMETRY, cg_event)
    _publish(redis_client, TOPIC_WORKLOAD_INDEX, wi_event)


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


def run_forever(airport_icao: str = config.DEFAULT_AIRPORT) -> None:
    """Main loop — runs until interrupted."""
    config.validate_env()
    r = _build_redis_client()
    logger.info(
        "TowerGuard runner starting — airport=%s, cycle=%ss",
        airport_icao,
        config.RUNNER_CYCLE_SECONDS,
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
