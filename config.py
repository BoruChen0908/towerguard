"""TowerGuard configuration — loaded once at startup, never mutated."""

import logging
import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# OpenSky OAuth2
# ---------------------------------------------------------------------------
OPENSKY_TOKEN_URL = (
    "https://auth.opensky-network.org/auth/realms/opensky-network"
    "/protocol/openid-connect/token"
)
OPENSKY_API_BASE = "https://opensky-network.org/api"

# Token refresh headroom — refresh this many seconds before actual expiry
TOKEN_REFRESH_HEADROOM_SECONDS = 30

# HTTP timeout for OpenSky requests (seconds)
OPENSKY_TIMEOUT_SECONDS = 10

# Maximum single wait on 429 Retry-After (seconds); do not retry after waiting
OPENSKY_MAX_RETRY_AFTER_SECONDS = 60


# ---------------------------------------------------------------------------
# Airports
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class AirportConfig:
    icao: str
    name: str
    lat: float
    lon: float
    # FAA CRWG TARGET (recommended_controllers) — source: FAA Controller
    # Workforce Plan 2025-2028, p.28-33, Terminal facilities table, as of 09/21/24
    recommended_controllers: int
    # FAA CPC (Certified Professional Controllers) on board — same source
    staffed_controllers: int
    # Active frequency count — mock value, config-adjustable
    active_frequencies: int
    # Handoff rate per hour — mock value, config-adjustable
    handoff_rate_per_hour: int


# Radius for aircraft bounding-box query (nautical miles → degrees).
# 1 NM ≈ 1/60 degree latitude; longitude scaling applied in opensky.py
AIRPORT_RADIUS_NM = 50

AIRPORTS: dict[str, AirportConfig] = {
    "KJFK": AirportConfig(
        icao="KJFK",
        name="John F. Kennedy International",
        lat=40.6413,
        lon=-73.7781,
        # JFK (Kennedy Tower) — CRWG TARGET 33, CPC 30 — FAA CWP 2025-2028 p.32
        recommended_controllers=33,
        staffed_controllers=30,
        active_frequencies=4,
        handoff_rate_per_hour=14,
    ),
    "KEWR": AirportConfig(
        icao="KEWR",
        name="Newark Liberty International",
        lat=40.6895,
        lon=-74.1745,
        # EWR (Newark Tower) — CRWG TARGET 37, CPC 26 — FAA CWP 2025-2028 p.30
        recommended_controllers=37,
        staffed_controllers=26,
        active_frequencies=4,
        handoff_rate_per_hour=12,
    ),
    "KBOS": AirportConfig(
        icao="KBOS",
        name="Boston Logan International",
        lat=42.3656,
        lon=-71.0096,
        # BOS (Boston Tower) — CRWG TARGET 33, CPC 24 — FAA CWP 2025-2028 p.29
        recommended_controllers=33,
        staffed_controllers=24,
        active_frequencies=3,
        handoff_rate_per_hour=10,
    ),
    "KATL": AirportConfig(
        icao="KATL",
        name="Hartsfield-Jackson Atlanta International",
        lat=33.6407,
        lon=-84.4277,
        # ATL (Atlanta Tower) — CRWG TARGET 52, CPC 37 — FAA CWP 2025-2028 p.28
        recommended_controllers=52,
        staffed_controllers=37,
        active_frequencies=5,
        handoff_rate_per_hour=16,
    ),
    "KMDW": AirportConfig(
        icao="KMDW",
        name="Chicago Midway International",
        lat=41.7868,
        lon=-87.7522,
        # MDW (Midway Tower) — CRWG TARGET 22, CPC 19 — FAA CWP 2025-2028 p.32
        # (Terminal facilities table, "Actual on board as of 09/21/24")
        recommended_controllers=22,
        staffed_controllers=19,
        # mock / config-adjustable, scaled to a single-complex hub tower
        active_frequencies=3,
        handoff_rate_per_hour=11,
    ),
}

DEFAULT_AIRPORT = "KJFK"

# ---------------------------------------------------------------------------
# Redis
# ---------------------------------------------------------------------------
REDIS_URL_DEFAULT = "redis://localhost:6379/0"

# ---------------------------------------------------------------------------
# Traffic Density scoring weights (must sum to 1.0)
# ---------------------------------------------------------------------------
TD_WEIGHT_COUNT = 0.5
TD_WEIGHT_SPEED_VAR = 0.25
TD_WEIGHT_ALT_VAR = 0.25

# Normalization denominators for traffic density sub-scores
TD_MAX_AIRCRAFT = 200  # aircraft count at which count-score saturates at 1.0
TD_MAX_SPEED_VARIANCE = 100.0  # knots std-dev at score = 1.0
# feet std-dev at score = 1.0. geo_altitude is converted m→ft at the OpenSky
# parse boundary (data.opensky._parse_states), so this variance is in feet.
TD_MAX_ALT_VARIANCE = 8000.0

# ---------------------------------------------------------------------------
# Score → Tier thresholds (§2a)
# ---------------------------------------------------------------------------
SCORE_TIER_LOW_MAX = 0.40
SCORE_TIER_MEDIUM_MAX = 0.65
SCORE_TIER_HIGH_MAX = 0.85
# score >= 0.85 → CRITICAL

# ---------------------------------------------------------------------------
# Conflict Geometry
# ---------------------------------------------------------------------------
CG_PROJECTION_WINDOW_SECONDS = 120  # look-ahead for external projection
CG_TERMINAL_SEPARATION_NM = 3.0  # ICAO terminal minimum — FAA JO 7110.65 ¶5-5-4
CG_VERTICAL_SEPARATION_FT = 1000.0  # ICAO vertical minimum — FAA JO 7110.65 ¶4-5-1

# Tier time-to-violation thresholds (§2c)
CG_CRITICAL_THRESHOLD_SECONDS = 60
CG_HIGH_THRESHOLD_SECONDS = 90

# ---------------------------------------------------------------------------
# Workload Index scoring weights (must sum to 1.0)
# ---------------------------------------------------------------------------
WI_WEIGHT_STAFFING_RATIO = 0.50  # staffed / recommended ratio (inverted)
WI_WEIGHT_FREQUENCIES = 0.25  # active frequencies relative to capacity
WI_WEIGHT_HANDOFF_RATE = 0.25  # handoff rate relative to reference

WI_MAX_FREQUENCIES = 8  # frequency count at which freq-score saturates
WI_MAX_HANDOFF_RATE = 30  # handoffs/hr at which handoff-score saturates

# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
RUNNER_CYCLE_SECONDS = 60
# How often the runner wakes to check the dashboard-selected airport. A change
# triggers an immediate cycle for the new airport rather than waiting out the
# remaining cycle window (functional A).
RUNNER_POLL_SECONDS = 5

# ---------------------------------------------------------------------------
# Startup validation
# ---------------------------------------------------------------------------


def validate_env() -> None:
    """Fast-fail at startup if required environment variables are missing."""
    required = ["OPENSKY_CLIENT_ID", "OPENSKY_CLIENT_SECRET", "REDIS_URL"]
    missing = [k for k in required if not os.getenv(k)]
    if missing:
        raise EnvironmentError(
            f"Missing required environment variables: {', '.join(missing)}. "
            "Check your .env file."
        )
    logger.info("Environment validation passed.")
