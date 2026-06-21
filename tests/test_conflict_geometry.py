"""
Tests for modules/conflict_geometry.py.

Covers:
  - All five tier branches per §2c (UNKNOWN/LOW/CRITICAL/HIGH/MEDIUM)
  - First-match ordering (CRITICAL beats HIGH when both would fire)
  - compute_unavailable()
  - _check_pair() direct testing
  - _derive_tier() boundary conditions
"""

from modules.conflict_geometry import (
    _check_pair,
    _derive_tier,
    _is_valid_state,
    compute,
    compute_unavailable,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_aircraft(
    icao24: str = "aaaaaa",
    callsign: str = "TST001",
    lat: float = 40.64,
    lon: float = -73.78,
    altitude_ft: float = 1000.0,
    velocity_kts: float = 0.0,
    heading_deg: float = 0.0,
    vertical_rate_ftps: float = 0.0,
    on_ground: bool = False,
) -> dict:
    """Build a state-vector dict in downstream units (feet, ft/s).

    The module consumes geo_altitude in feet and vertical_rate in ft/s (the
    OpenSky parse boundary converts from metric upstream). These fixtures feed
    the module directly, so values are supplied already in feet.
    """
    return {
        "icao24": icao24,
        "callsign": callsign,
        "latitude": lat,
        "longitude": lon,
        "geo_altitude": altitude_ft,
        "velocity": velocity_kts,
        "true_track": heading_deg,
        "vertical_rate": vertical_rate_ftps,
        "on_ground": on_ground,
    }


def _headon_pair(start_sep_nm: float, alt_gap_ft: float = 0.0) -> tuple[dict, dict]:
    """Two aircraft head-on along a N-S line, both at 180 kts.

    180 kts = 0.05 NM/s each; combined closing speed = 0.1 NM/s. A pair that
    starts ``start_sep_nm`` apart first breaches the 3 NM minimum at
    ``ceil((start_sep_nm - 3.0) / 0.1)`` seconds. ``alt_gap_ft`` sets a constant
    vertical gap (0 → vertical condition always satisfied).

    geo_altitude is supplied in feet (the downstream unit), not metres — the
    OpenSky parse boundary already converts to feet, and these test fixtures
    feed the module directly, bypassing that boundary.
    """
    half_sep_deg = start_sep_nm / 2.0 / 60.0
    a1 = _make_aircraft(
        icao24="aaaa01",
        callsign="TST001",
        lat=40.64 + half_sep_deg,
        lon=-73.78,
        altitude_ft=1000.0,
        velocity_kts=180.0,
        heading_deg=180.0,  # heading south
        vertical_rate_ftps=0.0,
    )
    a2 = _make_aircraft(
        icao24="aaaa02",
        callsign="TST002",
        lat=40.64 - half_sep_deg,
        lon=-73.78,
        altitude_ft=1000.0 + alt_gap_ft,
        velocity_kts=180.0,
        heading_deg=0.0,  # heading north
        vertical_rate_ftps=0.0,
    )
    return a1, a2


# ---------------------------------------------------------------------------
# _is_valid_state
# ---------------------------------------------------------------------------


class TestIsValidState:
    def test_airborne_valid(self):
        s = _make_aircraft(lat=40.0, lon=-73.0, velocity_kts=200.0)
        assert _is_valid_state(s) is True

    def test_airborne_but_stationary_invalid(self):
        # on_ground=False but ~zero groundspeed = surface/ramp clutter → excluded
        s = _make_aircraft(lat=40.0, lon=-73.0, velocity_kts=0.0)
        assert _is_valid_state(s) is False

    def test_on_ground_invalid(self):
        s = _make_aircraft(on_ground=True)
        assert _is_valid_state(s) is False

    def test_missing_lat_invalid(self):
        s = _make_aircraft()
        s["latitude"] = None
        assert _is_valid_state(s) is False


# ---------------------------------------------------------------------------
# _derive_tier — all five §2c branches
# ---------------------------------------------------------------------------


class TestDeriveTier:
    def test_no_conflicts_low(self):
        assert _derive_tier([]) == "LOW"

    def test_critical_threshold_exact(self):
        conflicts = [{"time_to_violation_seconds": 60}]
        assert _derive_tier(conflicts) == "CRITICAL"

    def test_below_critical_threshold(self):
        conflicts = [{"time_to_violation_seconds": 59}]
        assert _derive_tier(conflicts) == "CRITICAL"

    def test_high_threshold_exact(self):
        conflicts = [{"time_to_violation_seconds": 90}]
        assert _derive_tier(conflicts) == "HIGH"

    def test_below_high_threshold(self):
        conflicts = [{"time_to_violation_seconds": 61}]
        assert _derive_tier(conflicts) == "HIGH"

    def test_above_high_is_medium(self):
        conflicts = [{"time_to_violation_seconds": 91}]
        assert _derive_tier(conflicts) == "MEDIUM"

    def test_critical_dominates_high(self):
        """First-match ordering: CRITICAL should win over HIGH."""
        conflicts = [
            {"time_to_violation_seconds": 91},  # MEDIUM alone
            {"time_to_violation_seconds": 45},  # CRITICAL
            {"time_to_violation_seconds": 80},  # HIGH
        ]
        assert _derive_tier(conflicts) == "CRITICAL"

    def test_high_dominates_medium(self):
        conflicts = [
            {"time_to_violation_seconds": 120},  # MEDIUM
            {"time_to_violation_seconds": 75},  # HIGH
        ]
        assert _derive_tier(conflicts) == "HIGH"


# ---------------------------------------------------------------------------
# compute() — integration with state vectors
# ---------------------------------------------------------------------------


class TestCompute:
    def test_empty_states_returns_low(self):
        event = compute("KJFK", [])
        assert event["tier"] == "LOW"
        assert event["conflicts_detected"] == 0
        assert event["closest_pair"] is None
        assert event["all_conflicts"] == []

    def test_event_type_correct(self):
        event = compute("KJFK", [])
        assert event["event_type"] == "conflict_geometry"

    def test_data_unavailable_false(self):
        event = compute("KJFK", [])
        assert event["data_unavailable"] is False

    def test_on_ground_aircraft_excluded(self):
        states = [_make_aircraft(on_ground=True) for _ in range(5)]
        event = compute("KJFK", states)
        assert event["pairs_checked"] == 0
        assert event["tier"] == "LOW"

    def test_alert_id_prefixed_cg(self):
        event = compute("KJFK", [])
        assert event["alert_id"].startswith("CG-")

    def test_single_aircraft_no_pairs(self):
        states = [_make_aircraft()]
        event = compute("KJFK", states)
        assert event["pairs_checked"] == 0

    def test_stationary_surface_aircraft_excluded(self):
        """Co-located but stationary (velocity ~0) aircraft are surface/ramp
        clutter — on_ground=False yet ~zero groundspeed — and are excluded from
        conflict scope, so they produce no spurious 0.0 NM conflict
        (config.MIN_AIRBORNE_SPEED_KTS). This is the live ground-clutter fix."""
        a1 = _make_aircraft(
            icao24="aa0001",
            callsign="TST001",
            lat=40.64,
            lon=-73.78,
            altitude_ft=1000.0,
            velocity_kts=0.0,
        )
        a2 = _make_aircraft(
            icao24="aa0002",
            callsign="TST002",
            lat=40.64,
            lon=-73.78,
            altitude_ft=1000.0,
            velocity_kts=0.0,
        )
        event = compute("KJFK", [a1, a2])
        assert event["pairs_checked"] == 0
        assert event["conflicts_detected"] == 0
        assert event["closest_pair"] is None
        assert event["tier"] == "LOW"

    def test_airborne_same_position_conflict(self):
        """Two co-located, co-altitude AIRBORNE aircraft still conflict."""
        a1 = _make_aircraft(
            icao24="aa0011", lat=40.64, lon=-73.78, altitude_ft=5000.0, velocity_kts=200.0
        )
        a2 = _make_aircraft(
            icao24="aa0012", lat=40.64, lon=-73.78, altitude_ft=5000.0, velocity_kts=200.0
        )
        event = compute("KJFK", [a1, a2])
        assert event["conflicts_detected"] >= 1
        assert event["closest_pair"] is not None

    def test_well_separated_aircraft_no_conflict(self):
        """Two aircraft 100 NM apart — no conflict in 120s at 300 kts."""
        a1 = _make_aircraft(icao24="bb0001", lat=40.0, lon=-73.0, velocity_kts=300.0)
        a2 = _make_aircraft(
            icao24="bb0002", lat=42.0, lon=-73.0, velocity_kts=300.0
        )  # ~120 NM apart
        event = compute("KJFK", [a1, a2])
        assert event["conflicts_detected"] == 0
        assert event["tier"] == "LOW"

    def test_closest_pair_has_required_fields(self):
        a1 = _make_aircraft(
            icao24="cc0001", lat=40.64, lon=-73.78, altitude_ft=1000.0, velocity_kts=200.0
        )
        a2 = _make_aircraft(
            icao24="cc0002", lat=40.64, lon=-73.78, altitude_ft=1000.0, velocity_kts=200.0
        )
        event = compute("KJFK", [a1, a2])
        # Co-located, co-altitude pair must conflict — assert the pair exists
        # before checking its shape (previously this guard let the body skip).
        assert event["closest_pair"] is not None
        cp = event["closest_pair"]
        assert "callsigns" in cp
        assert "projected_separation_nm" in cp
        assert "icao_minimum_nm" in cp
        assert "time_to_violation_seconds" in cp


# ---------------------------------------------------------------------------
# Real converging-track geometry (proves #1 first-violation semantics and
# #2 analytic CPA). Closing speed for the head-on fixtures is 0.1 NM/s, so a
# pair starting S NM apart first breaches 3 NM at (S - 3.0) / 0.1 seconds.
# ---------------------------------------------------------------------------


class TestConvergingTracks:
    def test_critical_band_first_violation_30s(self):
        """Start 6 NM apart → first violation ~30 s → CRITICAL."""
        a1, a2 = _headon_pair(start_sep_nm=6.0)
        conflict = _check_pair(a1, a2)
        assert conflict is not None
        assert abs(conflict["time_to_violation_seconds"] - 30) <= 2
        event = compute("KJFK", [a1, a2])
        assert event["tier"] == "CRITICAL"

    def test_high_band_first_violation_75s(self):
        """Start 10.5 NM apart → first violation ~75 s → HIGH."""
        a1, a2 = _headon_pair(start_sep_nm=10.5)
        conflict = _check_pair(a1, a2)
        assert conflict is not None
        assert abs(conflict["time_to_violation_seconds"] - 75) <= 2
        event = compute("KJFK", [a1, a2])
        assert event["tier"] == "HIGH"

    def test_medium_band_first_violation_105s(self):
        """Start 13.5 NM apart → first violation ~105 s → MEDIUM."""
        a1, a2 = _headon_pair(start_sep_nm=13.5)
        conflict = _check_pair(a1, a2)
        assert conflict is not None
        assert abs(conflict["time_to_violation_seconds"] - 105) <= 2
        event = compute("KJFK", [a1, a2])
        assert event["tier"] == "MEDIUM"

    def test_vertical_separation_blocks_conflict(self):
        """Horizontally converging but 1500 ft apart → no conflict (#4 dual
        condition: both horizontal AND vertical minima must be breached)."""
        a1, a2 = _headon_pair(start_sep_nm=6.0, alt_gap_ft=1500.0)
        assert _check_pair(a1, a2) is None
        event = compute("KJFK", [a1, a2])
        assert event["conflicts_detected"] == 0
        assert event["tier"] == "LOW"

    def test_projected_separation_distinct_from_violation_time(self):
        """projected_separation_nm (CPA) and time_to_violation are different
        quantities. For a shallow-converging pair the closest approach happens
        well after the first breach, so the two must not be conflated."""
        # Both eastbound, tracks angled 2° toward each other, starting 3.2 NM
        # apart in latitude at 200 kts. First breach ~52 s (CRITICAL); the
        # minimum horizontal separation (CPA) is ~2.73 NM, reached much later.
        half = 3.2 / 2.0 / 60.0
        a1 = _make_aircraft(
            icao24="rr01",
            callsign="REG001",
            lat=40.64 + half,
            lon=-73.90,
            altitude_ft=1000.0,
            velocity_kts=200.0,
            heading_deg=92.0,
        )
        a2 = _make_aircraft(
            icao24="rr02",
            callsign="REG002",
            lat=40.64 - half,
            lon=-73.90,
            altitude_ft=1000.0,
            velocity_kts=200.0,
            heading_deg=88.0,
        )
        conflict = _check_pair(a1, a2)
        assert conflict is not None
        # First-violation onset is CRITICAL...
        assert abs(conflict["time_to_violation_seconds"] - 52) <= 2
        # ...while the minimum-separation metric is a separate, larger value.
        assert abs(conflict["projected_separation_nm"] - 2.73) <= 0.1
        assert conflict["projected_separation_nm"] < conflict["icao_minimum_nm"]

    def test_regression_old_min_sep_sampler_mistiered_medium(self):
        """Regression guard for #1/#2.

        The previous implementation keyed the tier off the *minimum-separation*
        sample time using a coarse 15 s sweep. For this shallow-converging pair
        the deepest in-window sample lands at t=120 s, which the old code
        reported as MEDIUM — even though the pair actually breaches the 3 NM
        minimum at ~52 s, which is CRITICAL urgency. With the corrected
        first-violation semantics this must now resolve to CRITICAL.
        """
        half = 3.2 / 2.0 / 60.0
        a1 = _make_aircraft(
            icao24="rr01",
            callsign="REG001",
            lat=40.64 + half,
            lon=-73.90,
            altitude_ft=1000.0,
            velocity_kts=200.0,
            heading_deg=92.0,
        )
        a2 = _make_aircraft(
            icao24="rr02",
            callsign="REG002",
            lat=40.64 - half,
            lon=-73.90,
            altitude_ft=1000.0,
            velocity_kts=200.0,
            heading_deg=88.0,
        )
        event = compute("KJFK", [a1, a2])
        assert event["tier"] == "CRITICAL"  # old code: MEDIUM


# ---------------------------------------------------------------------------
# compute_unavailable()
# ---------------------------------------------------------------------------


class TestComputeUnavailable:
    def test_tier_unknown(self):
        event = compute_unavailable("KJFK")
        assert event["tier"] == "UNKNOWN"

    def test_data_unavailable_true(self):
        event = compute_unavailable("KJFK")
        assert event["data_unavailable"] is True

    def test_closest_pair_none(self):
        event = compute_unavailable("KJFK")
        assert event["closest_pair"] is None

    def test_all_conflicts_empty(self):
        event = compute_unavailable("KJFK")
        assert event["all_conflicts"] == []

    def test_event_type(self):
        event = compute_unavailable("KJFK")
        assert event["event_type"] == "conflict_geometry"
