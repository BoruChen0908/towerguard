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
    # --- Extended airport set (live OpenSky demo) -------------------------
    # lat/lon are exact (public). For SFO/SEA/ORD the staffing ratio matches
    # the N16 community-exposure figures (National Academies Table 2-6). For
    # the others, controller counts are size-scaled ESTIMATES (not a cited CWP
    # page) — traffic/conflict come live from OpenSky regardless.
    "KLAX": AirportConfig(
        icao="KLAX", name="Los Angeles International",
        lat=33.9425, lon=-118.4081,
        recommended_controllers=48, staffed_controllers=36,
        active_frequencies=5, handoff_rate_per_hour=16,
    ),
    "KSFO": AirportConfig(
        icao="KSFO", name="San Francisco International",
        lat=37.6188, lon=-122.3750,
        # NCT ~80% staffed (N16)
        recommended_controllers=40, staffed_controllers=32,
        active_frequencies=4, handoff_rate_per_hour=14,
    ),
    "KORD": AirportConfig(
        icao="KORD", name="Chicago O'Hare International",
        lat=41.9742, lon=-87.9073,
        # C90 ~107% staffed (N16) — the well-staffed high-traffic contrast
        recommended_controllers=55, staffed_controllers=59,
        active_frequencies=6, handoff_rate_per_hour=18,
    ),
    "KDFW": AirportConfig(
        icao="KDFW", name="Dallas/Fort Worth International",
        lat=32.8998, lon=-97.0403,
        recommended_controllers=50, staffed_controllers=39,
        active_frequencies=5, handoff_rate_per_hour=16,
    ),
    "KDEN": AirportConfig(
        icao="KDEN", name="Denver International",
        lat=39.8561, lon=-104.6737,
        recommended_controllers=48, staffed_controllers=37,
        active_frequencies=5, handoff_rate_per_hour=15,
    ),
    "KSEA": AirportConfig(
        icao="KSEA", name="Seattle-Tacoma International",
        lat=47.4502, lon=-122.3088,
        # S46 ~67% staffed (N16)
        recommended_controllers=36, staffed_controllers=24,
        active_frequencies=4, handoff_rate_per_hour=13,
    ),
    "KLAS": AirportConfig(
        icao="KLAS", name="Harry Reid International (Las Vegas)",
        lat=36.0840, lon=-115.1537,
        recommended_controllers=38, staffed_controllers=29,
        active_frequencies=4, handoff_rate_per_hour=13,
    ),
    "KMIA": AirportConfig(
        icao="KMIA", name="Miami International",
        lat=25.7932, lon=-80.2906,
        recommended_controllers=42, staffed_controllers=32,
        active_frequencies=4, handoff_rate_per_hour=14,
    ),
    "KDCA": AirportConfig(
        icao="KDCA", name="Ronald Reagan Washington National",
        lat=38.8512, lon=-77.0402,
        recommended_controllers=30, staffed_controllers=22,
        active_frequencies=3, handoff_rate_per_hour=12,
    ),
    "KCLT": AirportConfig(
        icao="KCLT", name="Charlotte Douglas International",
        lat=35.2140, lon=-80.9431,
        recommended_controllers=42, staffed_controllers=33,
        active_frequencies=4, handoff_rate_per_hour=14,
    ),
}

DEFAULT_AIRPORT = "KJFK"

# ---------------------------------------------------------------------------
# Redis
# ---------------------------------------------------------------------------
REDIS_URL_DEFAULT = "redis://localhost:6379/0"

# ---------------------------------------------------------------------------
# LLM augmentation (optional — Live Validation advisory / briefing phrasing)
# ---------------------------------------------------------------------------
# The deterministic AdvisoryEngine always decides WHETHER and WHEN to issue an
# advisory and enforces every guardrail (dedup, cooldown, supersede/resolve,
# human-override fields). The LLM, when enabled, only rewrites the human-facing
# text — the advisory summary / recommended_attention and the relief briefing
# prose — from the same structured signals. Any failure (no key, network, parse)
# falls back to the deterministic template, so the demo always runs offline.
LLM_MODEL_DEFAULT = "claude-opus-4-8"


def llm_model() -> str:
    """The Claude model id used for advisory/briefing phrasing."""
    return os.getenv("TOWERGUARD_LLM_MODEL", LLM_MODEL_DEFAULT)


def llm_enabled() -> bool:
    """True only when augmentation is explicitly enabled AND a key is present.

    Defaults OFF so the test suite and the offline demo never touch the network;
    callers degrade to the deterministic template whenever this is False.
    """
    if os.getenv("TOWERGUARD_USE_LLM", "0").lower() not in ("1", "true", "yes"):
        return False
    return bool(os.getenv("ANTHROPIC_API_KEY"))

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

# Aircraft slower than this groundspeed (knots) are treated as on-surface /
# taxiing and excluded from airborne traffic + conflict scope (shared by
# traffic_density, conflict_geometry, and the map snapshot via
# data.opensky.is_airborne). This filters live-data ground clutter — parked /
# taxiing aircraft that OpenSky reports with on_ground=False but ~zero speed,
# which otherwise inflate the count and produce 0.0 NM "conflicts". DEMO traffic
# is all >=180 kt, so DEMO behaviour is unchanged.
MIN_AIRBORNE_SPEED_KTS = 50.0

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
