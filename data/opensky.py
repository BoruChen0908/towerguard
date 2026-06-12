"""
OpenSky Network API client with OAuth2 token caching and error boundary.

Error handling per contract §6 and api-design kit L82-101:
  - 429 + Retry-After  → wait once (capped), raise OpenSkyUnavailable
  - 401                → force-refresh token once, retry once, then raise
  - connection / timeout → raise OpenSkyUnavailable immediately
  - any unrecoverable → raise OpenSkyUnavailable (never return fake data)
"""

import logging
import math
import time
from typing import Any, Optional

import os

import requests

import config

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------


class OpenSkyUnavailable(Exception):
    """Raised when OpenSky data cannot be obtained.

    Callers should produce a data_unavailable=true event per contract §6.
    """


class OpenSkyAuthError(OpenSkyUnavailable):
    """Raised when token refresh fails or auth is permanently broken."""


# ---------------------------------------------------------------------------
# Token cache (module-level, reset on process restart)
# ---------------------------------------------------------------------------

_token: Optional[str] = None
_token_expires_at: float = 0.0  # Unix timestamp


def _token_needs_refresh() -> bool:
    headroom = config.TOKEN_REFRESH_HEADROOM_SECONDS
    return _token is None or time.time() >= (_token_expires_at - headroom)


def _fetch_token() -> None:
    """Request a new OAuth2 client_credentials token from OpenSky.

    Updates module-level _token and _token_expires_at.
    Raises OpenSkyAuthError on failure.
    """
    global _token, _token_expires_at

    client_id = os.getenv("OPENSKY_CLIENT_ID")
    client_secret = os.getenv("OPENSKY_CLIENT_SECRET")

    try:
        resp = requests.post(
            config.OPENSKY_TOKEN_URL,
            data={
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret,
            },
            timeout=config.OPENSKY_TIMEOUT_SECONDS,
        )
    except requests.exceptions.RequestException as exc:
        raise OpenSkyAuthError(f"Token fetch network error: {exc}") from exc

    if resp.status_code != 200:
        raise OpenSkyAuthError(f"Token fetch failed: HTTP {resp.status_code}")

    try:
        payload = resp.json()
    except ValueError as exc:
        raise OpenSkyAuthError(f"Token response was not valid JSON: {exc}") from exc
    _token = payload["access_token"]
    expires_in: int = payload.get("expires_in", 300)
    _token_expires_at = time.time() + expires_in
    logger.debug("OpenSky token refreshed; expires_in=%ss", expires_in)


def _get_token() -> str:
    """Return a valid bearer token, refreshing if necessary."""
    if _token_needs_refresh():
        _fetch_token()
    assert _token is not None  # _fetch_token raises on failure
    return _token


# ---------------------------------------------------------------------------
# Bounding box helper
# ---------------------------------------------------------------------------


def _bounding_box(
    lat: float, lon: float, radius_nm: float
) -> tuple[float, float, float, float]:
    """Return (lat_min, lon_min, lat_max, lon_max) for a circular query.

    Approximation: 1 NM = 1/60 degree latitude; longitude scaled by cos(lat).
    """
    delta_lat = radius_nm / 60.0
    # Guard against cos(90°) = 0 edge case (not a real airport)
    cos_lat = math.cos(math.radians(lat))
    delta_lon = radius_nm / 60.0 / max(cos_lat, 1e-6)
    return (
        lat - delta_lat,
        lon - delta_lon,
        lat + delta_lat,
        lon + delta_lon,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def fetch_states(airport_icao: str) -> list[dict[str, Any]]:
    """Fetch current state vectors for aircraft within 50 NM of the airport.

    Returns a list of state-vector dicts (OpenSky /states/all format, parsed
    from the 'states' array with column names applied).

    Raises OpenSkyUnavailable on any unrecoverable condition.
    """
    from config import AIRPORTS, AIRPORT_RADIUS_NM  # local import avoids circular

    airport = AIRPORTS.get(airport_icao)
    if airport is None:
        raise OpenSkyUnavailable(f"Unknown airport: {airport_icao!r}")

    lat_min, lon_min, lat_max, lon_max = _bounding_box(
        airport.lat, airport.lon, AIRPORT_RADIUS_NM
    )

    return _request_states(lat_min, lon_min, lat_max, lon_max)


def _request_states(
    lat_min: float,
    lon_min: float,
    lat_max: float,
    lon_max: float,
) -> list[dict[str, Any]]:
    """Internal: make the /states/all request with error boundary."""
    token = _get_token()
    url = f"{config.OPENSKY_API_BASE}/states/all"
    params = {
        "lamin": lat_min,
        "lomin": lon_min,
        "lamax": lat_max,
        "lomax": lon_max,
    }

    try:
        resp = _make_request(url, params, token)
    except _NeedTokenRefresh:
        # 401 — force one token refresh then retry
        logger.warning("401 received; forcing token refresh.")
        _fetch_token()
        token = _get_token()  # narrows Optional[str] → str; raises if refresh failed
        resp = _make_request(url, params, token, allow_401_retry=False)

    try:
        raw = resp.json()
    except ValueError as exc:
        raise OpenSkyUnavailable(f"OpenSky response was not valid JSON: {exc}") from exc
    return _parse_states(raw)


class _NeedTokenRefresh(Exception):
    """Internal signal: received 401, should refresh token."""


def _make_request(
    url: str,
    params: dict[str, Any],
    token: str,
    allow_401_retry: bool = True,
) -> requests.Response:
    """Make a single HTTP GET with error handling.

    Raises:
        _NeedTokenRefresh — on 401 (if allow_401_retry is True)
        OpenSkyUnavailable — on 429 (after optional wait), 5xx, network error
    """
    try:
        resp = requests.get(
            url,
            params=params,
            headers={"Authorization": f"Bearer {token}"},
            timeout=config.OPENSKY_TIMEOUT_SECONDS,
        )
    except requests.exceptions.Timeout as exc:
        raise OpenSkyUnavailable("OpenSky request timed out") from exc
    except requests.exceptions.RequestException as exc:
        raise OpenSkyUnavailable(f"OpenSky connection error: {exc}") from exc

    if resp.status_code == 401:
        if allow_401_retry:
            raise _NeedTokenRefresh()
        raise OpenSkyAuthError("401 after token refresh — auth broken")

    if resp.status_code == 429:
        _handle_rate_limit(resp)  # may sleep once; always raises afterward

    if resp.status_code >= 500:
        raise OpenSkyUnavailable(f"OpenSky server error: HTTP {resp.status_code}")

    if resp.status_code != 200:
        raise OpenSkyUnavailable(f"Unexpected OpenSky status: HTTP {resp.status_code}")

    return resp


def _handle_rate_limit(resp: requests.Response) -> None:
    """Parse Retry-After header, sleep once (capped), then raise.

    Per spec: wait once, do NOT retry — prevents retry storm.
    """
    retry_after_raw = resp.headers.get("Retry-After", "")
    try:
        wait = min(float(retry_after_raw), config.OPENSKY_MAX_RETRY_AFTER_SECONDS)
    except (ValueError, TypeError):
        wait = config.OPENSKY_MAX_RETRY_AFTER_SECONDS

    wait = max(wait, 0.0)
    logger.warning(
        "OpenSky 429 — waiting %.1fs (Retry-After: %s)", wait, retry_after_raw
    )
    if wait > 0:
        time.sleep(wait)

    raise OpenSkyUnavailable(f"OpenSky rate-limited (waited {wait:.1f}s, not retrying)")


# ---------------------------------------------------------------------------
# State vector column mapping (OpenSky /states/all format)
# ---------------------------------------------------------------------------

_STATE_COLUMNS = [
    "icao24",
    "callsign",
    "origin_country",
    "time_position",
    "last_contact",
    "longitude",
    "latitude",
    "baro_altitude",
    "on_ground",
    "velocity",
    "true_track",
    "vertical_rate",
    "sensors",
    "geo_altitude",
    "squawk",
    "spi",
    "position_source",
]

# OpenSky reports altitude in metres and vertical_rate in m/s. The whole
# downstream pipeline works in feet (separation minima are 1000 ft, altitude
# variance is in feet), so we convert once here at the parse boundary.
_METRES_TO_FEET = 3.28084

# OpenSky reports velocity (ground speed) in m/s, but the pipeline treats
# velocity as knots everywhere (conflict_geometry's kts→NM/s factor,
# traffic_density's speed_variance, the runner's velocity_kt). Convert once
# here at the parse boundary, same as altitude / vertical_rate above.
_KNOTS_PER_MS = 1.943844


def _to_feet(value: Any) -> Any:
    """Convert a metres value to feet, passing through None unchanged."""
    return value * _METRES_TO_FEET if value is not None else None


def _to_knots(value: Any) -> Any:
    """Convert a metres-per-second value to knots, passing None through."""
    return value * _KNOTS_PER_MS if value is not None else None


def _parse_states(raw: dict[str, Any]) -> list[dict[str, Any]]:
    """Convert OpenSky raw response to list of named-field dicts.

    Altitudes (baro_altitude, geo_altitude) and vertical_rate are converted
    from OpenSky's metric units to feet / ft-per-second, and velocity from m/s
    to knots, so that every consumer downstream operates in the same units
    (feet, knots) consistently.
    """
    states_raw = raw.get("states") or []
    result = []
    for row in states_raw:
        if len(row) < len(_STATE_COLUMNS):
            continue
        state = dict(zip(_STATE_COLUMNS, row))
        state["baro_altitude"] = _to_feet(state["baro_altitude"])
        state["geo_altitude"] = _to_feet(state["geo_altitude"])
        state["vertical_rate"] = _to_feet(state["vertical_rate"])
        state["velocity"] = _to_knots(state["velocity"])
        result.append(state)
    return result
