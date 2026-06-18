"""
Community impact (N-community) — who gets hurt first (Brief 6 title: "Build AI
That Helps Communities Decide Better"; Impact 15%). The national model says
"doing nothing is costly nationally"; this breaks that down to specific
communities using REAL, differentiated per-facility data — not a sliced-up
national number.

Two outputs, both grounded:
  1. Exposure ranking = staffing gap x traffic share. Two real facts combined
     into a RELATIVE rank. The headline insight: exposure is NOT uniform — it is
     about the GAP, not size. New York (N90, 72% staffed) tops it; Chicago (C90,
     107% staffed) sits at zero exposure despite being a top-traffic hub. That
     contrast is the honest counter to "big airports just get hurt."
  2. NAS-category system-delay cost = the airport's actual FY/CY2024 NAS
     delay-minutes (BTS) x A4A's $100.76/min block-time cost. A REAL number — but
     see the heavy caveat below: it is an UPPER BOUND on the staffing-relevant
     cost, NOT a "staffing cost."

================================================================================
PROVENANCE & DECISIONS — N-community
================================================================================
Data (all retrieved, sourced; no fabrication):
  - NAS delay-minutes, per airport, CY2024: BTS TranStats "Airline On-Time
    Performance / Delay Cause" (reporting carriers, arriving flights).
  - Facility annual operations, FY2024: FAA "Air Traffic by the Numbers" (FY2024,
    OPSNET; TRACON facility table).
  - Staffing % of standard, FY2024: National Academies/TRB "ATC Workforce
    Imperative" (Jun 2025), Table 2-6 (single internally-consistent source —
    NOT averaged with the divergent OIG/CPC figures, which differ by definition).
  - A4A block-time cost $100.76/min (2024), verified verbatim.

Decisions:
  D-C1 Unit = the GOVERNING ATC facility / metro (the decision-relevant unit),
       not the airport, because staffing is reported per facility. N90 serves
       JFK+LGA+EWR, so its delay cost SUMS those three airports; staffing/ops are
       the facility's. C90 is included as the well-staffed high-traffic CONTRAST.
  D-C2 exposure_score = max(0, 1 - staffing_pct) x ops_share. The max(0,...)
       floors well-staffed facilities (C90 at 107% -> 0), which is the point:
       exposure tracks the gap, not traffic. exposure_index normalises to the
       most-exposed facility (= 1.0).
  D-C3 The dollar is the NAS-category delay cost, labelled as an UPPER BOUND.
       BTS "NAS" bundles non-extreme weather + volume + equipment; the
       staffing-controllable slice is the volume portion (FAA Core-30 FY2024:
       volume ~25%, equipment ~0.7%). We do NOT multiply by a contested share —
       we report the real NAS cost and state plainly it is not a staffing cost.

Honest caveats (carried in the JSON `caveats` field):
  - NAS != controller staffing (bundles weather/volume/equipment).
  - BTS covers reporting carriers, arriving flights only (~70-80%) -> undercount.
    MEM is passenger-only here (FedEx does not report) -> its cargo hub is
    massively understated.
  - NCT delay = SFO only (OAK/SJC not pulled) -> NCT understated.
  - Facility ops are FY2024 (all traffic); delay-minutes are CY2024 (arrivals,
    reporting carriers) — different denominators, not divided against each other.

OBSERVED BEHAVIOR (model output, not input)
  Ranking: New York (N90) most exposed; Chicago (C90) zero exposure despite ~2nd
  traffic — the gap, not size, drives exposure. NAS system-delay cost across the
  featured facilities totals ~$0.56B/yr (an upper bound, airline-direct only).
================================================================================
"""

from dataclasses import dataclass

# A4A 2024 average block-time (taxi + airborne) cost, US passenger carriers.
# Airline-direct cost only (no passenger-time / lost-demand) — conservative.
A4A_BLOCK_MINUTE_COST_USD = 100.76

# FAA Core-30 FY2024 delay categories: the staffing-controllable slice is volume.
# Reported for transparency; NOT applied as a multiplier (see D-C3).
FAA_CORE30_VOLUME_SHARE = 0.252


@dataclass(frozen=True)
class Facility:
    """A governing ATC facility + the real data for its metro (see provenance)."""

    code: str
    metro: str
    airports: tuple[str, ...]
    staffing_pct_of_standard: float  # NAS Table 2-6, FY2024
    annual_ops: int                  # FAA OPSNET FY2024 (facility total)
    nas_delay_minutes: int           # BTS CY2024, summed over its airports
    note: str = ""


# Featured facilities: those with BOTH documented understaffing AND retrievable
# traffic + delay data, plus C90 as the well-staffed contrast (D-C1).
FACILITIES: tuple[Facility, ...] = (
    Facility(
        code="N90",
        metro="New York",
        airports=("JFK", "LGA", "EWR"),
        staffing_pct_of_standard=0.72,
        annual_ops=1_848_004,
        nas_delay_minutes=496_960 + 719_315 + 957_980,  # JFK + LGA + EWR
    ),
    Facility(
        code="NCT",
        metro="San Francisco Bay",
        airports=("SFO",),
        staffing_pct_of_standard=0.80,
        annual_ops=1_522_376,
        nas_delay_minutes=1_102_917,  # SFO only — OAK/SJC not pulled (understated)
        note="Delay = SFO only; OAK/SJC not included, so NCT is understated.",
    ),
    Facility(
        code="A80",
        metro="Atlanta",
        airports=("ATL",),
        staffing_pct_of_standard=0.78,
        annual_ops=800_196,
        nas_delay_minutes=763_292,
    ),
    Facility(
        code="S46",
        metro="Seattle",
        airports=("SEA",),
        staffing_pct_of_standard=0.67,
        annual_ops=498_297,
        nas_delay_minutes=404_312,
    ),
    Facility(
        code="M03",
        metro="Memphis",
        airports=("MEM",),
        staffing_pct_of_standard=0.71,
        annual_ops=292_564,
        nas_delay_minutes=49_014,  # passenger carriers only; FedEx not in BTS
        note="Passenger carriers only; FedEx does not report to BTS, so the "
        "cargo super-hub is massively understated.",
    ),
    Facility(
        code="C90",
        metro="Chicago",
        airports=("ORD",),
        staffing_pct_of_standard=1.07,  # well-staffed CONTRAST
        annual_ops=1_144_563,
        nas_delay_minutes=1_088_047,
        note="Well-staffed (107%) high-traffic CONTRAST: high traffic, ~zero "
        "exposure — exposure tracks the staffing gap, not size.",
    ),
)


@dataclass(frozen=True)
class CommunityExposure:
    code: str
    metro: str
    airports: list[str]
    staffing_pct_of_standard: float
    staffing_gap: float
    annual_ops: int
    ops_share: float
    exposure_score: float
    exposure_index: float  # normalised to the most-exposed facility (= 1.0)
    exposure_rank: int
    nas_delay_minutes: int
    nas_delay_cost_usd: int  # NAS-category, an UPPER BOUND (D-C3)
    note: str


def _exposure_score(facility: Facility, ops_share: float) -> float:
    """Staffing gap x traffic share; well-staffed facilities floor at 0 (D-C2)."""
    return max(0.0, 1.0 - facility.staffing_pct_of_standard) * ops_share


def community_exposure() -> list[CommunityExposure]:
    """Rank the featured facilities by exposure; attach the real delay cost."""
    total_ops = sum(f.annual_ops for f in FACILITIES)
    scored = [
        (f, _exposure_score(f, f.annual_ops / total_ops)) for f in FACILITIES
    ]
    max_score = max(score for _f, score in scored) or 1.0
    ranked = sorted(scored, key=lambda pair: pair[1], reverse=True)

    out: list[CommunityExposure] = []
    for rank, (f, score) in enumerate(ranked, start=1):
        out.append(
            CommunityExposure(
                code=f.code,
                metro=f.metro,
                airports=list(f.airports),
                staffing_pct_of_standard=f.staffing_pct_of_standard,
                staffing_gap=round(max(0.0, 1.0 - f.staffing_pct_of_standard), 3),
                annual_ops=f.annual_ops,
                ops_share=round(f.annual_ops / total_ops, 4),
                exposure_score=round(score, 4),
                exposure_index=round(score / max_score, 3),
                exposure_rank=rank,
                nas_delay_minutes=f.nas_delay_minutes,
                nas_delay_cost_usd=round(f.nas_delay_minutes * A4A_BLOCK_MINUTE_COST_USD),
                note=f.note,
            )
        )
    return out


METHODOLOGY = (
    "Exposure = max(0, 1 - staffing%) x operations share — two real facts "
    "(National Academies Table 2-6 staffing, FAA OPSNET FY2024 ops) ranked "
    "relatively. The dollar is the airport's CY2024 NAS-category delay-minutes "
    "(BTS) x $100.76/min (A4A block-time). Unit = the governing ATC facility/"
    "metro; N90 sums JFK+LGA+EWR."
)

CAVEATS = (
    "The NAS-category delay cost is an UPPER BOUND on the staffing-relevant cost, "
    "NOT a 'staffing cost': BTS 'NAS' bundles non-extreme weather, volume and "
    "equipment (the staffing-controllable slice is the volume portion — FAA "
    "Core-30 FY2024 ~25%). BTS covers reporting carriers, arriving flights only "
    "(~70-80%), so totals undercount; MEM is passenger-only (FedEx does not "
    "report), understating the cargo hub. NCT delay = SFO only. Facility ops are "
    "FY2024 (all traffic); delay-minutes are CY2024 (arrivals) — not divided "
    "against each other. This is exposure attribution, not an independent "
    "regional economic model."
)


def build_community() -> dict:
    """Assemble the community-exposure block for the JSON contract."""
    exposures = community_exposure()
    return {
        "methodology": METHODOLOGY,
        "caveats": CAVEATS,
        "faa_core30_volume_share": FAA_CORE30_VOLUME_SHARE,
        "facilities": [vars(e) for e in exposures],
    }


if __name__ == "__main__":  # pragma: no cover — inspection
    print(f"{'rank':>4}{'facility':>8}{'metro':>18}{'staff%':>8}{'expo':>7}{'NAS $':>14}")
    for e in community_exposure():
        print(
            f"{e.exposure_rank:>4}{e.code:>8}{e.metro:>18}"
            f"{e.staffing_pct_of_standard:>8.0%}{e.exposure_index:>7.2f}"
            f"{e.nas_delay_cost_usd:>14,}"
        )
    total = sum(e.nas_delay_cost_usd for e in community_exposure())
    print(f"\ntotal NAS-category delay cost (upper bound): ${total:,}")
