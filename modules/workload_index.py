"""
Workload Index module — W1-4.

Computes a weighted controller workload score from mock/config values.
OpenSky provides no staffing data; all inputs come from config.py constants
which are sourced from the FAA Controller Workforce Plan 2025-2028 (p.28-33).

Score formula:
  staffing_score  = 1 - clamp(staffed / recommended, 0, 1)
                    (higher understaffing → higher score)
  frequency_score = clamp(active_freq / WI_MAX_FREQUENCIES, 0, 1)
  handoff_score   = clamp(handoff_rate / WI_MAX_HANDOFF_RATE, 0, 1)
  score = 0.50*staffing_score + 0.25*frequency_score + 0.25*handoff_score

Tier mapping per §2a (same thresholds as Traffic Density).
"""

import logging
from typing import Any

import config
from modules.envelope import (
    build_unavailable_base,
    next_alert_id,
    utc_now_iso,
)

logger = logging.getLogger(__name__)

EVENT_TYPE = "workload_index"
ALERT_PREFIX = "WI"


def _score_to_tier(score: float) -> str:
    """Map normalised score (0.0–1.0) to tier string per §2a."""
    if score < config.SCORE_TIER_LOW_MAX:
        return "LOW"
    if score < config.SCORE_TIER_MEDIUM_MAX:
        return "MEDIUM"
    if score < config.SCORE_TIER_HIGH_MAX:
        return "HIGH"
    return "CRITICAL"


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


def compute(
    airport_icao: str,
    staffed_override: int | None = None,
) -> dict[str, Any]:
    """Build a workload_index event for the given airport.

    All inputs come from config; no live data dependency beyond airport lookup.
    Returns a validated event dict ready for JSON serialisation.

    ``staffed_override`` lets the runner force the on-board headcount for a
    director switch (workload_surge drops staffing to drive the score up). When
    None the config value is used, preserving the default behaviour.
    """
    airport = config.AIRPORTS.get(airport_icao)
    if airport is None:
        logger.error("Unknown airport %r for workload_index", airport_icao)
        return compute_unavailable(airport_icao)

    staffed = (
        staffed_override
        if staffed_override is not None
        else airport.staffed_controllers
    )
    recommended = airport.recommended_controllers
    active_freq = airport.active_frequencies
    handoff_rate = airport.handoff_rate_per_hour

    # Staffing score: understaffed → higher pressure
    if recommended > 0:
        staffing_ratio = _clamp(staffed / recommended)
    else:
        staffing_ratio = 1.0
    staffing_score = 1.0 - staffing_ratio

    frequency_score = _clamp(active_freq / config.WI_MAX_FREQUENCIES)
    handoff_score = _clamp(handoff_rate / config.WI_MAX_HANDOFF_RATE)

    score = (
        config.WI_WEIGHT_STAFFING_RATIO * staffing_score
        + config.WI_WEIGHT_FREQUENCIES * frequency_score
        + config.WI_WEIGHT_HANDOFF_RATE * handoff_score
    )
    score = round(_clamp(score), 4)
    tier = _score_to_tier(score)

    return {
        "event_type": EVENT_TYPE,
        "alert_id": next_alert_id(ALERT_PREFIX),
        "airport": airport_icao,
        "timestamp": utc_now_iso(),
        "tier": tier,
        "data_unavailable": False,
        "score": score,
        "staffed_controllers": staffed,
        "recommended_controllers": recommended,
        "active_frequencies": active_freq,
        "handoff_rate_per_hour": handoff_rate,
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
        "staffed_controllers": 0,
        "recommended_controllers": 0,
        "active_frequencies": 0,
        "handoff_rate_per_hour": 0,
    }
