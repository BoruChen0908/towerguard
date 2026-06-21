"""
Traffic Density module — W1-2.

Computes aircraft count, speed variance, altitude variance within 50 NM,
produces a weighted score and maps it to a tier per contract §2a/§2b.
"""

import logging
import math
from typing import Any

import config
from data.opensky import is_airborne
from modules.envelope import (
    build_unavailable_base,
    next_alert_id,
    utc_now_iso,
)

logger = logging.getLogger(__name__)

EVENT_TYPE = "traffic_density"
ALERT_PREFIX = "TD"


def _score_to_tier(score: float) -> str:
    """Map normalised score (0.0–1.0) to tier string per §2a."""
    if score < config.SCORE_TIER_LOW_MAX:
        return "LOW"
    if score < config.SCORE_TIER_MEDIUM_MAX:
        return "MEDIUM"
    if score < config.SCORE_TIER_HIGH_MAX:
        return "HIGH"
    return "CRITICAL"


def _std_dev(values: list[float]) -> float:
    """Population standard deviation of a list of floats."""
    n = len(values)
    if n == 0:
        return 0.0
    mean = sum(values) / n
    variance = sum((v - mean) ** 2 for v in values) / n
    return math.sqrt(variance)


def _normalise(value: float, maximum: float) -> float:
    """Clamp value/maximum to [0.0, 1.0]."""
    return min(value / maximum, 1.0) if maximum > 0 else 0.0


def compute(
    airport_icao: str,
    states: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build a traffic_density event from a list of OpenSky state dicts.

    Args:
        airport_icao: ICAO code of the queried airport.
        states: State vector dicts from data.opensky.fetch_states().

    Returns:
        A validated event dict ready for JSON serialisation.
    """
    # Count only genuinely airborne traffic — surface / taxiing aircraft (live
    # ramp clutter) are out of airspace-density scope (see config.MIN_AIRBORNE_SPEED_KTS).
    states = [s for s in states if is_airborne(s)]
    aircraft_count = len(states)

    # Collect valid speed and altitude values (OpenSky may return None)
    speeds: list[float] = [
        float(s["velocity"]) for s in states if s.get("velocity") is not None
    ]
    # geo_altitude arrives in feet (converted at the OpenSky parse boundary),
    # so altitude_variance below is a feet std-dev, matching TD_MAX_ALT_VARIANCE.
    altitudes: list[float] = [
        float(s["geo_altitude"]) for s in states if s.get("geo_altitude") is not None
    ]

    speed_variance = _std_dev(speeds)
    altitude_variance = _std_dev(altitudes)

    # Weighted score
    count_score = _normalise(aircraft_count, config.TD_MAX_AIRCRAFT)
    speed_score = _normalise(speed_variance, config.TD_MAX_SPEED_VARIANCE)
    alt_score = _normalise(altitude_variance, config.TD_MAX_ALT_VARIANCE)

    score = (
        config.TD_WEIGHT_COUNT * count_score
        + config.TD_WEIGHT_SPEED_VAR * speed_score
        + config.TD_WEIGHT_ALT_VAR * alt_score
    )
    score = round(min(max(score, 0.0), 1.0), 4)
    tier = _score_to_tier(score)

    return {
        "event_type": EVENT_TYPE,
        "alert_id": next_alert_id(ALERT_PREFIX),
        "airport": airport_icao,
        "timestamp": utc_now_iso(),
        "tier": tier,
        "data_unavailable": False,
        "score": score,
        "aircraft_count": aircraft_count,
        "speed_variance": round(speed_variance, 2),
        "altitude_variance": round(altitude_variance, 2),
        "window_seconds": 60,
    }


def compute_unavailable(airport_icao: str) -> dict[str, Any]:
    """Build a data_unavailable=true event for this module per §6."""
    base = build_unavailable_base(
        event_type=EVENT_TYPE,
        prefix=ALERT_PREFIX,
        airport=airport_icao,
    )
    return {
        **base,
        "score": None,
        "aircraft_count": 0,
        "speed_variance": None,
        "altitude_variance": None,
        "window_seconds": 60,
    }
