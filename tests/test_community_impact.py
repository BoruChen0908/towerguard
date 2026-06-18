"""Tests for the community-impact layer (N-community).

Guards the exposure ranking, the honest "gap not size" property (the well-staffed
contrast floors at zero exposure), and the real delay-cost arithmetic.
"""

from models.community_impact import (
    A4A_BLOCK_MINUTE_COST_USD,
    FACILITIES,
    build_community,
    community_exposure,
)


def test_all_facilities_ranked() -> None:
    exposures = community_exposure()
    assert len(exposures) == len(FACILITIES)
    ranks = [e.exposure_rank for e in exposures]
    assert ranks == list(range(1, len(FACILITIES) + 1))  # 1..N, ordered, unique


def test_new_york_is_most_exposed() -> None:
    top = community_exposure()[0]
    assert top.code == "N90"
    assert top.exposure_rank == 1
    assert top.exposure_index == 1.0


def test_well_staffed_facility_floors_at_zero_exposure() -> None:
    # The honest "gap not size" property: Chicago (C90, 107%) has a big delay
    # bill but ZERO exposure, and ranks last despite high traffic.
    by_code = {e.code: e for e in community_exposure()}
    c90 = by_code["C90"]
    assert c90.staffing_pct_of_standard > 1.0
    assert c90.exposure_score == 0.0
    assert c90.exposure_rank == len(FACILITIES)
    assert c90.nas_delay_cost_usd > 0  # still has real delay cost — that's the point


def test_delay_cost_is_minutes_times_rate() -> None:
    for e in community_exposure():
        expected = round(e.nas_delay_minutes * A4A_BLOCK_MINUTE_COST_USD)
        assert e.nas_delay_cost_usd == expected


def test_ops_share_sums_to_one() -> None:
    assert abs(sum(e.ops_share for e in community_exposure()) - 1.0) < 0.01


def test_build_community_shape() -> None:
    block = build_community()
    assert {"methodology", "caveats", "facilities"} <= set(block)
    assert len(block["facilities"]) == len(FACILITIES)
    # The upper-bound caveat must be carried — never sell this as a staffing cost.
    assert "UPPER BOUND" in block["caveats"]
    for f in block["facilities"]:
        assert {"code", "metro", "exposure_index", "exposure_rank",
                "nas_delay_cost_usd"} <= set(f)
