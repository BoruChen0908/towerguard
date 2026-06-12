"""
Conflict Geometry module — W1-3.

Projects aircraft positions forward by CG_PROJECTION_WINDOW_SECONDS using
constant-velocity straight-line extrapolation from ADS-B state vectors.
Compares projected separation against ICAO terminal minima.

Two distinct quantities are reported per conflicting pair:
  - projected_separation_nm: the minimum horizontal separation over the
    window, found analytically via closest point of approach (CPA).
  - time_to_violation_seconds: the first instant both the horizontal (< 3 NM)
    and vertical (< 1000 ft) minima are breached, found by a 1-second scan.
These are not the same time point — CPA is the closest approach; the first
violation is the onset of the conflict, which drives the tier.

Tier rules per contract §2c (evaluated top-to-bottom, first match wins):
  1. data_unavailable=true  → UNKNOWN
  2. no conflicts           → LOW
  3. any conflict ≤ 60 s   → CRITICAL
  4. any conflict ≤ 90 s   → HIGH
  5. all conflicts  > 90 s → MEDIUM

Scientific basis: constant-velocity pairwise projection method per
NASA Paielli (TSAFE) — NTRS-20170011259.
"""

import logging
import math
from typing import Any, Optional

import config
from modules.envelope import (
    build_unavailable_base,
    next_alert_id,
    utc_now_iso,
)

logger = logging.getLogger(__name__)

EVENT_TYPE = "conflict_geometry"
ALERT_PREFIX = "CG"

# Nautical miles per degree latitude (approximation)
_NM_PER_DEG_LAT = 60.0
# Knots to NM/s conversion
_KTS_TO_NM_PER_S = 1.0 / 3600.0
# Step (seconds) for the first-violation scan; 1 s gives ~30 m positional
# granularity at typical terminal speeds, well below the 3 NM threshold.
_VIOLATION_SCAN_STEP_SECONDS = 1


# ---------------------------------------------------------------------------
# Geometry helpers
#
# Both aircraft are placed in a shared local flat-earth frame measured in
# nautical miles (x = east, y = north) with aircraft-1's current position as
# origin. Relative position/velocity in this frame let us solve closest point
# of approach (CPA) analytically instead of sampling — see _check_pair.
# ---------------------------------------------------------------------------


def _local_xy_nm(
    lat: float,
    lon: float,
    lat0: float,
    lon0: float,
) -> tuple[float, float]:
    """Project (lat, lon) to local (east_nm, north_nm) relative to (lat0, lon0).

    Flat-earth approximation: 1 deg latitude = 60 NM; longitude scaled by
    cos(lat0). Valid for the short ranges (<=50 NM) in terminal airspace.
    """
    north_nm = (lat - lat0) * _NM_PER_DEG_LAT
    cos_lat = math.cos(math.radians(lat0))
    east_nm = (lon - lon0) * _NM_PER_DEG_LAT * cos_lat
    return east_nm, north_nm


def _velocity_xy_nm_per_s(heading_deg: float, speed_kts: float) -> tuple[float, float]:
    """Return (east, north) velocity components in NM/s.

    Heading is degrees clockwise from north, so north = cos(h), east = sin(h).
    """
    speed_nm_per_s = speed_kts * _KTS_TO_NM_PER_S
    heading_rad = math.radians(heading_deg)
    east = speed_nm_per_s * math.sin(heading_rad)
    north = speed_nm_per_s * math.cos(heading_rad)
    return east, north


def _vertical_separation_ft(
    s1: dict[str, Any],
    s2: dict[str, Any],
    dt: float,
) -> float:
    """Return absolute vertical separation in feet after dt seconds.

    geo_altitude is already in feet (converted at parse time in
    data.opensky._parse_states); vertical_rate is converted to ft/s there too.
    """
    alt1 = (s1.get("geo_altitude") or 0.0) + (s1.get("vertical_rate") or 0.0) * dt
    alt2 = (s2.get("geo_altitude") or 0.0) + (s2.get("vertical_rate") or 0.0) * dt
    return abs(alt1 - alt2)


# ---------------------------------------------------------------------------
# Conflict detection
# ---------------------------------------------------------------------------


def _is_valid_state(s: dict[str, Any]) -> bool:
    """Return True if the state vector has the minimum fields for projection."""
    return (
        s.get("latitude") is not None
        and s.get("longitude") is not None
        and not s.get("on_ground", True)
    )


def _min_horizontal_separation_nm(
    s1: dict[str, Any],
    s2: dict[str, Any],
) -> float:
    """Minimum horizontal separation (NM) over the projection window via CPA.

    Solves the closest-point-of-approach time analytically:
        t_cpa = -(Δp · Δv) / |Δv|²
    clamped to [0, window]. With straight-line constant-velocity motion the
    relative-distance function is a parabola in t, so its minimum over the
    window is reached either at t_cpa (if inside the window) or at a window
    endpoint. Sampling (the old approach) could step over t_cpa and miss the
    true closest approach.

    |Δv|² == 0 (relative rest) → separation is constant; report it at t=0.
    """
    lat0, lon0 = s1["latitude"], s1["longitude"]
    p1 = _local_xy_nm(lat0, lon0, lat0, lon0)  # origin → (0, 0)
    p2 = _local_xy_nm(s2["latitude"], s2["longitude"], lat0, lon0)
    v1 = _velocity_xy_nm_per_s(s1.get("true_track") or 0.0, s1.get("velocity") or 0.0)
    v2 = _velocity_xy_nm_per_s(s2.get("true_track") or 0.0, s2.get("velocity") or 0.0)

    dpx, dpy = p2[0] - p1[0], p2[1] - p1[1]
    dvx, dvy = v2[0] - v1[0], v2[1] - v1[1]

    window = float(config.CG_PROJECTION_WINDOW_SECONDS)
    dv_sq = dvx * dvx + dvy * dvy
    if dv_sq == 0.0:
        t_cpa = 0.0
    else:
        t_cpa = -(dpx * dvx + dpy * dvy) / dv_sq
        t_cpa = max(0.0, min(t_cpa, window))

    sep_x = dpx + dvx * t_cpa
    sep_y = dpy + dvy * t_cpa
    return math.hypot(sep_x, sep_y)


def _first_violation_time(
    s1: dict[str, Any],
    s2: dict[str, Any],
) -> Optional[int]:
    """First time (s) both horizontal and vertical minima are violated.

    Scans the window at 1-second steps; returns the earliest t where
    horizontal < terminal minimum AND vertical < vertical minimum, or None if
    no such instant exists. This is a distinct quantity from the minimum
    horizontal separation — onset of violation, not the closest approach.
    """
    lat0, lon0 = s1["latitude"], s1["longitude"]
    p2 = _local_xy_nm(s2["latitude"], s2["longitude"], lat0, lon0)
    v1 = _velocity_xy_nm_per_s(s1.get("true_track") or 0.0, s1.get("velocity") or 0.0)
    v2 = _velocity_xy_nm_per_s(s2.get("true_track") or 0.0, s2.get("velocity") or 0.0)
    dpx, dpy = p2[0], p2[1]
    dvx, dvy = v2[0] - v1[0], v2[1] - v1[1]

    window = config.CG_PROJECTION_WINDOW_SECONDS
    for t in range(0, window + 1, _VIOLATION_SCAN_STEP_SECONDS):
        horiz_nm = math.hypot(dpx + dvx * t, dpy + dvy * t)
        if horiz_nm >= config.CG_TERMINAL_SEPARATION_NM:
            continue
        vert_ft = _vertical_separation_ft(s1, s2, float(t))
        if vert_ft < config.CG_VERTICAL_SEPARATION_FT:
            return t
    return None


def _check_pair(
    s1: dict[str, Any],
    s2: dict[str, Any],
) -> Optional[dict[str, Any]]:
    """Check one aircraft pair for conflict within the projection window.

    A conflict exists when there is an instant in [0, window] where the
    projected horizontal separation is below the ICAO terminal minimum AND the
    vertical separation is below the vertical minimum (§2c dual condition).

    Returns a conflict dict, or None if no violation occurs. The two reported
    quantities are deliberately distinct:
      - projected_separation_nm: minimum horizontal separation over the window
        (analytic CPA).
      - time_to_violation_seconds: first instant the dual condition holds.
    """
    violation_time = _first_violation_time(s1, s2)
    if violation_time is None:
        return None

    min_horiz = _min_horizontal_separation_nm(s1, s2)

    cs1 = (s1.get("callsign") or s1.get("icao24") or "UNKNOWN").strip()
    cs2 = (s2.get("callsign") or s2.get("icao24") or "UNKNOWN").strip()
    return {
        "callsigns": [cs1, cs2],
        "projected_separation_nm": round(min_horiz, 2),
        "icao_minimum_nm": config.CG_TERMINAL_SEPARATION_NM,
        "time_to_violation_seconds": violation_time,
    }


# ---------------------------------------------------------------------------
# Tier rule (§2c)
# ---------------------------------------------------------------------------


def _derive_tier(conflicts: list[dict[str, Any]]) -> str:
    """Apply §2c tier rules top-to-bottom, first match wins."""
    if not conflicts:
        return "LOW"
    times = [c["time_to_violation_seconds"] for c in conflicts]
    if any(t <= config.CG_CRITICAL_THRESHOLD_SECONDS for t in times):
        return "CRITICAL"
    if any(t <= config.CG_HIGH_THRESHOLD_SECONDS for t in times):
        return "HIGH"
    return "MEDIUM"


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------


def compute(
    airport_icao: str,
    states: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build a conflict_geometry event from a list of OpenSky state dicts.

    Args:
        airport_icao: ICAO code of the queried airport.
        states: State vector dicts from data.opensky.fetch_states().

    Returns:
        A validated event dict ready for JSON serialisation.
    """
    airborne = [s for s in states if _is_valid_state(s)]
    n = len(airborne)
    pairs_checked = n * (n - 1) // 2

    conflicts: list[dict[str, Any]] = []
    for i in range(n):
        for j in range(i + 1, n):
            result = _check_pair(airborne[i], airborne[j])
            if result is not None:
                conflicts.append(result)

    tier = _derive_tier(conflicts)

    # Closest pair = conflict with smallest projected separation
    closest_pair: Optional[dict[str, Any]] = None
    if conflicts:
        closest_pair = min(conflicts, key=lambda c: c["projected_separation_nm"])

    return {
        "event_type": EVENT_TYPE,
        "alert_id": next_alert_id(ALERT_PREFIX),
        "airport": airport_icao,
        "timestamp": utc_now_iso(),
        "tier": tier,
        "data_unavailable": False,
        "pairs_checked": pairs_checked,
        "conflicts_detected": len(conflicts),
        "closest_pair": closest_pair,
        "all_conflicts": conflicts,
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
        "pairs_checked": 0,
        "conflicts_detected": 0,
        "closest_pair": None,
        "all_conflicts": [],
    }
