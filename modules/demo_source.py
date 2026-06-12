"""DEMO_MODE state-vector source (offline OpenSky substitute).

When the runner runs with ``DEMO_MODE=1`` it does not call OpenSky. Instead it
loads ``fixtures/sample_states.json``, applies a small per-cycle random jitter to
each aircraft's position and speed (so the dashboard map visibly moves), and
appends one deterministically converging pair that is guaranteed to trigger a
HIGH conflict within ~60-90 s. This is the mock basis for the 6/19 integration
test.

The converging pair advances continuously across cycles (not respawned at the
start geometry every cycle): module-level state pushes the pair forward by one
cycle's worth of travel each call, so the dashboard shows a real closing
approach and the time-to-violation ticks down cycle by cycle. Once the pair has
closed past the 3 NM minimum it respawns to the start geometry and the loop
repeats. The eight fixture aircraft are the moving "background" traffic.

Units note: parsed OpenSky ``velocity`` is consumed as knots throughout the
pipeline (conflict_geometry converts it with a kts→NM/s factor). OpenSky's raw
velocity is m/s and is converted to knots at the parse boundary, so the fixture
stores raw m/s values that ``_parse_fixture_row`` converts to the same knots the
real path produces. The synthesized converging pair below is built post-parse,
so its ``velocity`` is already in knots and is not run through the conversion.
"""

import json
import random
from pathlib import Path
from typing import Any

from data.opensky import _STATE_COLUMNS, _to_feet, _to_knots

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

# Seconds the converging pair advances per cycle (matches the runner's 60 s
# publish cadence). Each cycle the pair closes 2 * 180 kt = 0.1 NM/s, so the
# 10 NM start gap shrinks 6 NM per cycle: 10 → 4 → respawn. The first violation
# (3 NM breach) lands at 70 s on the spawn cycle (HIGH band) and at 10 s one
# cycle later (CRITICAL), giving the demo its HIGH→CRITICAL narrative.
_CONVERGE_CYCLE_SECONDS = 60.0

# Module-level state: seconds the converging pair has been advancing since its
# last spawn. Lives across cycles so the approach is continuous, not reset.
_converge_elapsed_s = 0.0


def _parse_fixture_row(row: list[Any]) -> dict[str, Any]:
    """Apply column names + the metric conversions done at the OpenSky parse
    boundary (metres→feet, m/s→knots), so DEMO states match real parsed states
    field-for-field."""
    state = dict(zip(_STATE_COLUMNS, row))
    state["baro_altitude"] = _to_feet(state["baro_altitude"])
    state["geo_altitude"] = _to_feet(state["geo_altitude"])
    state["vertical_rate"] = _to_feet(state["vertical_rate"])
    state["velocity"] = _to_knots(state["velocity"])
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


def _converging_pair(
    lat0: float,
    lon0: float,
    elapsed_s: float = 0.0,
) -> list[dict[str, Any]]:
    """Two head-on aircraft straddling (lat0, lon0), closing at 180 kt each.

    At ``elapsed_s == 0`` they are 10 NM apart and first breach the 3 NM minimum
    at ~70 s with zero vertical gap → HIGH conflict on the spawn cycle. As
    ``elapsed_s`` grows the pair has already closed in by that many seconds, so
    the remaining gap (and the time-to-violation) shrinks accordingly.
    """
    # Each plane has closed (speed * elapsed) toward the centre line.
    closed_nm = _CONVERGE_SPEED_KTS / 3600.0 * elapsed_s
    half_sep_deg = max(0.0, _CONVERGE_START_SEP_NM / 2.0 - closed_nm) / _NM_PER_DEG_LAT
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


def reset_converge_state() -> None:
    """Reset the converging pair to its spawn geometry (test helper)."""
    global _converge_elapsed_s
    _converge_elapsed_s = 0.0


def demo_states(
    lat0: float,
    lon0: float,
    rng: random.Random | None = None,
    background_limit: int | None = None,
) -> list[dict[str, Any]]:
    """Build one cycle's DEMO state vectors: jittered background + converge pair.

    The converging pair advances by one cycle (``_CONVERGE_CYCLE_SECONDS``) of
    closing per call via module-level state, so the approach is continuous and
    the time-to-violation ticks down across cycles. Once the pair has closed in
    past the 3 NM minimum it respawns to the start geometry.

    Args:
        lat0, lon0: airport centre, used to anchor the converging pair.
        rng: optional Random for deterministic tests; defaults to module random.
        background_limit: cap the background fleet to the first N aircraft (the
            ``sparse`` director switch sets this to 2 so traffic density falls to
            LOW while the converging pair still drives the conflict). None keeps
            the full fixture fleet, preserving the default behaviour.
    """
    global _converge_elapsed_s
    r = rng or random
    background = [_jitter(s, r) for s in _load_background()]
    if background_limit is not None:
        background = background[:background_limit]

    # Remaining gap before this cycle's snapshot; once it has shrunk to the
    # terminal minimum the pair has passed through the conflict → respawn.
    remaining_sep_nm = (
        _CONVERGE_START_SEP_NM
        - _CONVERGE_SPEED_KTS / 3600.0 * _converge_elapsed_s * 2.0
    )
    if remaining_sep_nm <= 3.0:
        _converge_elapsed_s = 0.0

    pair = _converging_pair(lat0, lon0, _converge_elapsed_s)
    _converge_elapsed_s += _CONVERGE_CYCLE_SECONDS
    return background + pair
