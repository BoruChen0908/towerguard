"""
Safety Risk Module (N5) — maps a workforce trajectory to a probabilistic
relative risk indicator and a "months below the 85% staffing floor" count (§9).

CRITICAL FRAMING (§9.2): the risk index is a RELATIVE risk MULTIPLIER (1.0 =
rested / fully-staffed baseline), NOT a probability of an accident. Serious
near-misses are rare events with high statistical noise; this output must always
be shown with wide uncertainty and a disclaimer, and must never be read as
predicting specific accidents.

================================================================================
PROVENANCE & DECISIONS — N5 (see calibration D20)
================================================================================
Grounded in fatigue science (not an arbitrary blend). Risk is driven by SAFTE-
FAST effectiveness, which itself integrates staffing via the loops (low CPC ->
high gap -> low effectiveness). Anchors:
  - effectiveness 1.0 (rested)  -> 1.0x baseline
  - effectiveness 0.77 (= BAC 0.05% point, §9.3) -> 2.0x relative risk
    (Williamson & Feyer; driving/fatigue literature, applied to ATC by analogy)
  - below 0.77: quadratic rise toward a 5.0x ceiling (severe impairment ~ BAC
    0.10% / 24h awake ~ 4-7x, conservatively capped at 5x)
The 0.77->2x mapping is an analogy — no ATC accident-rate-vs-fatigue dataset
exists (the rare-event problem, §9.2). months_below_85pct counts projected years
with CPC < 85% of the FAA target, x12. The FY2023 near-miss spike (19 serious,
7-yr high) is corroborating CONTEXT (surfaced by the JSON assembler), not a fit.

OBSERVED BEHAVIOR (model output, not input)
  Relative risk multiplier: do_nothing peaks ~3.6x the rested baseline; the
  intervention scenarios (current_plan / baseline / disruption) sit ~1.8x for the
  whole decade; only accelerated returns to ~1.0x. months_below_85pct still
  saturates at 132 (all 11 years) for everything except accelerated — under every
  scenario except aggressive intervention, CPCs sit below the 85% floor the WHOLE
  decade. Floor uses the FAA target (D7-consistent); CRWG/NATCA would be worse.
================================================================================
"""

from dataclasses import dataclass

from models import calibration as cal
from models.workforce_sd import LoopParams, WorkforceState, feedback_factors


@dataclass(frozen=True)
class SafetyMetrics:
    """Safety summary for a scenario trajectory (relative indicator, not a forecast)."""

    months_below_85pct: int
    peak_risk_index: float
    risk_index_by_year: list[tuple[int, float]]


def annual_risk_index(state: WorkforceState, loop: LoopParams | None = None) -> float:
    """Relative risk MULTIPLIER for one year (1.0 = rested baseline), driven by
    SAFTE-FAST effectiveness and anchored to the BAC-0.05% point (D20).

    Linear from 1.0x (effectiveness 1.0) to 2.0x at the 0.77 fatigue line, then a
    quadratic rise below it toward a 5.0x ceiling. NOT an accident probability (§9.2).
    """
    active = loop if loop is not None else LoopParams()
    effectiveness = feedback_factors(state, active).effectiveness
    threshold = active.fatigue_threshold

    if effectiveness >= threshold:
        slope = (cal.RISK_AT_FATIGUE_THRESHOLD - cal.RISK_BASELINE_MULTIPLIER) / (
            1.0 - threshold
        )
        return cal.RISK_BASELINE_MULTIPLIER + slope * (1.0 - effectiveness)

    deficit_fraction = (threshold - effectiveness) / threshold
    span = cal.RISK_CEILING - cal.RISK_AT_FATIGUE_THRESHOLD
    risk = cal.RISK_AT_FATIGUE_THRESHOLD + span * deficit_fraction**2
    return min(risk, cal.RISK_CEILING)


def safety_metrics(
    trajectory: list[WorkforceState], loop: LoopParams | None = None
) -> SafetyMetrics:
    """Summarise safety over the projected years (skips the initial FY2025 state)."""
    active = loop if loop is not None else LoopParams()
    projected = trajectory[1:]

    by_year = [(state.year, annual_risk_index(state, active)) for state in projected]
    years_below = sum(
        1
        for state in projected
        if state.cpc / active.target < cal.FLOW_CONTROL_FLOOR
    )
    peak = max((risk for _, risk in by_year), default=0.0)
    return SafetyMetrics(
        months_below_85pct=years_below * 12,
        peak_risk_index=peak,
        risk_index_by_year=by_year,
    )
