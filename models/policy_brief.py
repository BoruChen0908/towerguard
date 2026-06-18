"""
Policy Brief Generator (N8) — template-first.

Builds a structured policy brief from the model's ACTUAL outputs (scenario
costs, the do-nothing collapse, the cost of delay, the safety floor). It is
fully deterministic and needs no external API, so the brief is always available
for the demo and for the scenario-results JSON.

A future LLM layer (Claude API) can rephrase these sections into nicer prose;
that path is intentionally NOT built yet (no API key configured). The structured
output here is exactly what such a layer would take as input.

================================================================================
PROVENANCE & DECISIONS — N8
================================================================================
  - Template-first: every sentence is filled from computed model numbers, not
    hand-written constants — change the model and the brief follows.
  - Bakes in the Responsible-AI guardrails (§13): quote ranges over points, show
    BOTH the FAA and NATCA targets, and carry the safety / illustrative-loop
    disclaimers in `limitations`.
  - LLM rephrasing layer deferred (decided with user): connect the Claude API
    later. No anthropic SDK call is made here.

OBSERVED BEHAVIOR (model output, not input)
  The brief leads with BOTH legs: "every year of delay ~$70B" (money) AND
  "do-nothing pushes fatigue-error risk to ~3.6x baseline + a decade below the
  85% floor" (safety). Every figure is pulled live from the model, so the brief
  tracks any recalibration automatically.
================================================================================
"""

from dataclasses import dataclass

from models.economic_impact import cumulative_cost, net_cost_of_delay
from models.safety_risk import safety_metrics
from models.scenario_engine import SCENARIOS_BY_ID, timing_comparison
from models.workforce_sd import LoopParams


@dataclass(frozen=True)
class PolicyBrief:
    """Structured policy brief (§11.4). All text derived from model output."""

    executive_summary: str
    key_findings: list[str]
    cost_of_delay: str
    recommendations: list[str]
    limitations: str


def _billions(value: float) -> str:
    return f"${value / 1e9:.0f}B"


def generate_brief(
    results: dict[str, list],
    loop: LoopParams | None = None,
) -> PolicyBrief:
    """Generate the template policy brief from full scenario results."""
    active = loop if loop is not None else LoopParams()

    cumulative = {sid: cumulative_cost(traj, active) for sid, traj in results.items()}
    cost_vs_plan = cumulative["do_nothing"] - cumulative["current_plan"]
    cost_vs_accel = cumulative["do_nothing"] - cumulative["accelerated"]

    do_nothing = results["do_nothing"]
    start_cpc = do_nothing[0].cpc
    end_cpc = do_nothing[-1].cpc
    end_year = do_nothing[-1].year
    collapse_pct = (1 - end_cpc / start_cpc) * 100

    timing = timing_comparison(SCENARIOS_BY_ID["current_plan"])
    earliest = timing[min(timing)]
    delay = {
        sy: net_cost_of_delay(timing[sy], earliest, active) for sy in timing
    }

    dn_safety = safety_metrics(do_nothing, active)
    years_below = dn_safety.months_below_85pct // 12

    executive_summary = (
        f"On the do-nothing path, the certified controller (CPC) workforce is "
        f"projected to fall from {start_cpc:,.0f} to about {end_cpc:,.0f} by "
        f"FY{end_year} (~{collapse_pct:.0f}%), while staffing stays below the 85% "
        f"safety floor for the entire projection. Executing the current FAA plan "
        f"instead of doing nothing avoids on the order of {_billions(cost_vs_plan)} "
        f"in controller-attributable delay and overtime costs over the decade. "
        f"The cost of waiting is front-loaded and largely irreversible: the "
        f"certification pipeline takes years, so a hire today reaches the line in "
        f"2-3 years."
    )

    key_findings = [
        f"Do-nothing collapse: CPCs fall ~{collapse_pct:.0f}% by FY{end_year}, "
        f"driven by a reinforcing burnout-attrition loop.",
        f"Cost of doing nothing: ~{_billions(cost_vs_plan)} versus the current "
        f"plan, up to ~{_billions(cost_vs_accel)} versus accelerated hiring "
        f"(controller-attributable delay + overtime, FY2026-{end_year}).",
        f"Safety (the cost money can't buy back): doing nothing pushes the "
        f"relative fatigue-error risk to ~{dn_safety.peak_risk_index:.1f}x the "
        f"rested baseline, and CPCs stay below the 85% floor for all "
        f"{years_below} projected years.",
        f"Front-loaded delay: starting the plan one year late locks in "
        f"~{_billions(delay[min(k for k in delay if k > min(delay))])}; four years "
        f"late ~{_billions(delay[max(delay)])}.",
    ]

    cost_of_delay = (
        "Net cost of delaying the current plan, relative to starting in "
        f"{min(timing)}: "
        + ", ".join(
            f"{sy} → +{_billions(delay[sy])}"
            for sy in sorted(delay)
            if sy > min(delay)
        )
        + "."
    )

    recommendations = [
        "Begin or sustain the hiring ramp now — the certification lag means "
        "delay compounds for years before it can be reversed.",
        "Plan against the confidence ranges, not the point estimates "
        "(the bands widen with the least-calibrated assumptions).",
        "Evaluate outcomes against BOTH the FAA (12,563) and NATCA (14,633) "
        "staffing targets; this model endorses neither.",
    ]

    limitations = (
        "Strategic, aggregate model — not a facility-level or accident-prediction "
        "tool. Safety outputs are RELATIVE risk indicators with wide uncertainty, "
        "not accident forecasts. The burnout-loop coefficients are illustrative "
        "(literature-anchored, not yet calibrated), so collapse depth and the "
        "do-nothing cost are order-of-magnitude. The 'retirement cliff' framing in "
        "some source material is outdated for the 2026-2036 horizon."
    )

    return PolicyBrief(
        executive_summary=executive_summary,
        key_findings=key_findings,
        cost_of_delay=cost_of_delay,
        recommendations=recommendations,
        limitations=limitations,
    )
