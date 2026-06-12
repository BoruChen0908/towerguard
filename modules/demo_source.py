"""DEMO_MODE state-vector source (offline OpenSky substitute).

When the runner runs with ``DEMO_MODE=1`` it does not call OpenSky. Instead it
loads ``fixtures/sample_states.json``, applies a small per-cycle random jitter to
each aircraft's position and speed (so the dashboard map visibly moves), and
appends one deterministically converging pair that is guaranteed to trigger a
HIGH conflict within ~60-90 s. This is the mock basis for the 6/19 integration
test.

The converging pair is synthesized fresh every cycle (not jittered) so the
conflict timing stays deterministic regardless of jitter; the eight fixture
aircraft are the moving "background" traffic.

Units note: parsed OpenSky ``velocity`` is consumed as knots throughout the
pipeline (conflict_geometry converts it with a kts→NM/s factor, and the fixture
speeds 240-320 are realistic terminal knots, not m/s). DEMO state vectors follow
the same convention.
"""

import json
import random
from pathlib import Path
from typing import Any

from data.opensky import _STATE_COLUMNS, _to_feet

_FIXTURE_PATH = Path(__file__).parent.parent / "fixtures" / "sample_states.json"

# Jitter magnitudes per cycle (visual movement only — small enough not to
# perturb the background traffic into spurious conflicts).
_JITTER_DEG = 0.01  # ~0.6 NM latitude
_JITTER_KTS = 5.0

# Converging pair geometry. Head-on along a N-S line at the airport centre,
# both at 180 kt → combined closing speed 0.1 NM/s. Starting 10 NM apart, the
# 3 NM horizontal minimum is first breached at ceil((10 - 3) / 0.1) = 70 s,
# which lands in the §2c HIGH band (61-90 s) with zero vertical gap.
_CONVERGE_SPEED_KTS = 180.0
_CONVERGE_START_SEP_NM = 10.0
_CONVERGE_ALT_FT = 4000.0
_NM_PER_DEG_LAT = 60.0


def _parse_fixture_row(row: list[Any]) -> dict[str, Any]:
    """Apply column names + the metric→feet conversion done at the OpenSky
    parse boundary, so DEMO states match real parsed states field-for-field."""
    state = dict(zip(_STATE_COLUMNS, row))
    state["baro_altitude"] = _to_feet(state["baro_altitude"])
    state["geo_altitude"] = _to_feet(state["geo_altitude"])
    state["vertical_rate"] = _to_feet(state["vertical_rate"])
    return state


def _load_background() -> list[dict[str, Any]]:
    """Load and parse the fixture's background aircraft (no jitter yet)."""
    raw = json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))
    return [
        _parse_fixture_row(row)
        for row in raw.get("states", [])
        if len(row) >= len(_STATE_COLUMNS)
    ]


def _jitter(state: dict[str, Any], rng: random.Random) -> dict[str, Any]:
    """Return a new state with small random offsets on lat/lon/velocity.

    Immutable: builds a new dict rather than mutating the input.
    """
    jittered = dict(state)
    if jittered.get("latitude") is not None:
        jittered["latitude"] = jittered["latitude"] + rng.uniform(
            -_JITTER_DEG, _JITTER_DEG
        )
    if jittered.get("longitude") is not None:
        jittered["longitude"] = jittered["longitude"] + rng.uniform(
            -_JITTER_DEG, _JITTER_DEG
        )
    if jittered.get("velocity") is not None:
        jittered["velocity"] = max(
            0.0, jittered["velocity"] + rng.uniform(-_JITTER_KTS, _JITTER_KTS)
        )
    return jittered


def _converging_pair(lat0: float, lon0: float) -> list[dict[str, Any]]:
    """Two head-on aircraft straddling (lat0, lon0), 10 NM apart, 180 kt each.

    First breaches the 3 NM minimum at ~70 s with zero vertical gap → guaranteed
    HIGH conflict every cycle.
    """
    half_sep_deg = _CONVERGE_START_SEP_NM / 2.0 / _NM_PER_DEG_LAT
    north = {
        "icao24": "demo01",
        "callsign": "DMO901",
        "latitude": lat0 + half_sep_deg,
        "longitude": lon0,
        "geo_altitude": _CONVERGE_ALT_FT,
        "baro_altitude": _CONVERGE_ALT_FT,
        "on_ground": False,
        "velocity": _CONVERGE_SPEED_KTS,
        "true_track": 180.0,  # heading south
        "vertical_rate": 0.0,
    }
    south = {
        "icao24": "demo02",
        "callsign": "DMO902",
        "latitude": lat0 - half_sep_deg,
        "longitude": lon0,
        "geo_altitude": _CONVERGE_ALT_FT,
        "baro_altitude": _CONVERGE_ALT_FT,
        "on_ground": False,
        "velocity": _CONVERGE_SPEED_KTS,
        "true_track": 0.0,  # heading north
        "vertical_rate": 0.0,
    }
    return [north, south]


def demo_states(
    lat0: float,
    lon0: float,
    rng: random.Random | None = None,
) -> list[dict[str, Any]]:
    """Build one cycle's DEMO state vectors: jittered background + converge pair.

    Args:
        lat0, lon0: airport centre, used to anchor the converging pair.
        rng: optional Random for deterministic tests; defaults to module random.
    """
    r = rng or random
    background = [_jitter(s, r) for s in _load_background()]
    return background + _converging_pair(lat0, lon0)
