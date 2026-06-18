"""
Workforce Stock-Flow model (N1) — skeleton (1a) + feedback loops (1b).

Projects the FAA air-traffic-controller pipeline year by year:

    Applicants -> Academy -> Developmental -> CPC -> (attrition out)

Stage 1a is DETERMINISTIC: every flow rate is a constant from
models/calibration.py. Stage 1b adds the R1/R2/B1 feedback loops
(masterplan §7.3) as an OPTIONAL LoopParams argument to step()/simulate();
with loop=None the model is the deterministic, no-feedback skeleton (OJT
washout, added in 1d, is structural and always on).

Style follows the existing TowerGuard modules (pure functions, frozen
dataclasses, no mutation) — see modules/workload_index.py.

================================================================================
PROVENANCE & DECISIONS — Stage 1a
================================================================================
What this code does
  - Represents the pipeline stocks (§7.1) as an immutable WorkforceState.
  - Applies the flows (§7.2), collapsed where noted, as constant annual rates.
  - simulate() returns a trajectory of immutable yearly states.

Decisions (data/literature basis lives in models/calibration.py D1-D6):
  - "total_controllers" is DERIVED (developmental + cpc), not stored (cal D1).
  - Retirement collapsed into one CPC attrition rate (cal D4 + D6).
  - Annual time step (masterplan projects FY2026-2036 yearly).
  - Immutable: step() returns a NEW state; inputs never mutated (global rule).
  - Feedback loops are opt-in via LoopParams (cal D7-D10); loop=None = 1a.

Sanity check baked into the structure: with baseline params the developmental
stock converges toward ~4,000, independently matching the FAA/Reuters Apr-2026
snapshot we deliberately did NOT feed in as an initial value (cal D1).

PROVENANCE & DECISIONS — Stage 1b (feedback loops)
  - R1 burnout spiral: attrition multiplier from a SAFTE-FAST-style
    effectiveness score; linear above the 0.77 threshold, quadratic kick below
    (cal D7). Computed by feedback_factors().
  - R2 knowledge drain: certification rate scaled by instructor availability
    ~ CPC pool (cal D8).
  - B1 load shedding: below the 85% staffing floor, traffic is shed, relieving
    workload and partly offsetting R1 at economic cost priced later by N4
    (cal D9). This keeps severe understaffing from exploding attrition.
  - Effective CPC attrition capped at 0.95/yr — structural invariant (cal D10).
  - loop=None keeps the exact 1a behavior (regression-tested).

OBSERVED BEHAVIOR (model outputs after 1d calibration — not inputs)
  Stage 1d added OJT certification washout (cal D13) and a forward attrition
  regime (0.10, cal D14). The earlier "missing retirement wave" hypothesis was
  overturned by research (cal D12): the wave peaked in 2007, forward retirements
  are low/declining, the workforce is young. The real gaps were OJT washout +
  under-counted non-retirement attrition.

  Historical back-cast (OJT on, attrition 0.059, hiring ~1,326/yr):
    - Reproduces both the GAO total (13,166 ~ 13,164) AND composition (CPC 10,982
      ~ 11,000). OJT washout is what fixed the composition the 1c-only fit missed.
  Forward baseline (2,200-2,400/yr, attrition 0.10, loops on):
    - Total grows modestly 13,164 -> ~14,692 (reaching the ~14,600 staffing-target
      band by FY2035) — a credible "the plan slowly helps" trajectory, no longer
      the ~19,000 explosion.
    - CPC dips to a ~9,600 trough (~FY2030) then recovers to ~10,030 — the
      certification lag again (§10.2). Developmental rises to ~4,663, matching the
      FAA/Reuters Apr-2026 surge figure (~4,000). Story: hiring grows headcount,
      but CERTIFIED controllers barely move.
  Do-nothing (500/yr, attrition 0.10):
    - FY2035 total collapses to ~4,609 (loops on) vs ~6,361 (loops off): the
      calibrated attrition makes the burnout spiral genuinely catastrophic. The
      baseline-vs-do-nothing gap (~14,700 vs ~4,600) is the cost of doing nothing.

Deferred on purpose (not bugs):
  - Age-structured retirement cliff .. §10.3, later
  - Monte Carlo uncertainty .......... N3 (loop coefficients are the targets)
  - Precise re-calibration to the FY2015->FY2025 -6% curve .. stage 1c
================================================================================
"""

from dataclasses import dataclass, replace

from models import calibration as cal


@dataclass(frozen=True)
class WorkforceState:
    """Immutable snapshot of the pipeline at the end of one fiscal year."""

    year: int
    applicants: float
    academy: float
    developmental: float
    cpc: float

    @property
    def total_controllers(self) -> float:
        """FAA controller-workforce headcount = developmental + CPC.

        Excludes Academy students (pre-facility). See calibration D1.
        """
        return self.developmental + self.cpc


@dataclass(frozen=True)
class FlowParams:
    """Constant annual flow rates for the deterministic skeleton (1a)."""

    annual_applications: float = cal.ANNUAL_APPLICATION_RATE  # inflow to applicants
    hiring: float = cal.HIRING_TARGET_FY2026                  # F1, policy lever
    academy_grad_rate: float = cal.ACADEMY_GRAD_RATE          # F2
    academy_washout_rate: float = cal.ACADEMY_WASHOUT_RATE    # F7 (academy)
    certification_rate: float = cal.CERTIFICATION_RATE        # F3
    cpc_attrition_rate: float = cal.CPC_ATTRITION_RATE        # F5 + F6 (D4/D6/D14)
    dev_attrition: float = cal.DEV_ATTRITION_ANNUAL           # F7 (developmental)
    ojt_pass_rate: float = cal.OJT_PASS_RATE                  # D13 certification washout


@dataclass(frozen=True)
class LoopParams:
    """Feedback-loop coefficients (stage 1b). Sources: calibration D7-D10."""

    target: float = cal.TARGET_FAA                          # operational reference (D7)
    fatigue_threshold: float = cal.FATIGUE_THRESHOLD        # R1
    effectiveness_gap_sensitivity: float = cal.EFFECTIVENESS_GAP_SENSITIVITY  # R1
    attrition_slope: float = cal.ATTRITION_FATIGUE_SLOPE    # R1 above threshold
    attrition_amplify: float = cal.ATTRITION_FATIGUE_AMPLIFY  # R1 below threshold
    cert_instructor_reference: float = cal.CERT_INSTRUCTOR_REFERENCE  # R2
    cert_instructor_floor: float = cal.CERT_INSTRUCTOR_FLOOR  # R2
    flow_control_floor: float = cal.FLOW_CONTROL_FLOOR      # B1
    flow_control_shed_sensitivity: float = cal.FLOW_CONTROL_SHED_SENSITIVITY  # B1
    flow_control_max_shed: float = cal.FLOW_CONTROL_MAX_SHED  # B1


@dataclass(frozen=True)
class FeedbackFactors:
    """Per-year feedback state — transparent intermediate outputs (1b)."""

    staffing_ratio: float        # cpc / target
    flow_control_fraction: float  # B1: fraction of traffic shed
    effectiveness: float         # R1: SAFTE-FAST-style score (1.0 = rested)
    attrition_multiplier: float  # R1: applied to CPC attrition rate
    cert_factor: float           # R2: applied to certification rate


# Loop-off identity: every multiplier neutral -> step() == 1a skeleton.
NEUTRAL_FACTORS = FeedbackFactors(
    staffing_ratio=1.0,
    flow_control_fraction=0.0,
    effectiveness=1.0,
    attrition_multiplier=1.0,
    cert_factor=1.0,
)


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


def feedback_factors(state: WorkforceState, loop: LoopParams) -> FeedbackFactors:
    """Compute the R1/R2/B1 feedback factors for one year (pure function).

    Order matters: B1 (load shedding) relieves workload BEFORE R1 (fatigue) is
    evaluated, so flow control caps how far effectiveness can fall.
    """
    ratio = state.cpc / loop.target if loop.target > 0 else 1.0
    gap = max(0.0, 1.0 - ratio)

    # B1 — shed traffic below the staffing floor; relief reduces the workload gap
    if ratio < loop.flow_control_floor:
        shed = _clamp(
            loop.flow_control_shed_sensitivity * (loop.flow_control_floor - ratio),
            0.0,
            loop.flow_control_max_shed,
        )
    else:
        shed = 0.0
    effective_gap = max(0.0, gap - shed)

    # R1 — effectiveness falls with the relieved gap; quadratic kick below 0.77
    effectiveness = _clamp(
        1.0 - loop.effectiveness_gap_sensitivity * effective_gap
    )
    if effectiveness >= loop.fatigue_threshold:
        attrition_multiplier = 1.0 + loop.attrition_slope * (1.0 - effectiveness)
    else:
        above = loop.attrition_slope * (1.0 - loop.fatigue_threshold)
        deficit = loop.fatigue_threshold - effectiveness
        attrition_multiplier = 1.0 + above + loop.attrition_amplify * deficit**2

    # R2 — certification throughput scales with the instructor (CPC) pool
    cert_factor = _clamp(
        state.cpc / loop.cert_instructor_reference,
        loop.cert_instructor_floor,
        1.0,
    )

    return FeedbackFactors(
        staffing_ratio=ratio,
        flow_control_fraction=shed,
        effectiveness=effectiveness,
        attrition_multiplier=attrition_multiplier,
        cert_factor=cert_factor,
    )


def initial_state(year: int = 2025) -> WorkforceState:
    """FY2025-end initial stocks. See calibration D1-D3 for the derivations."""
    return WorkforceState(
        year=year,
        applicants=float(cal.INITIAL_APPLICANTS),
        academy=float(cal.INITIAL_ACADEMY),
        developmental=float(cal.INITIAL_DEVELOPMENTAL),
        cpc=float(cal.CPC_FY2025),
    )


def step(
    state: WorkforceState,
    params: FlowParams,
    loop: LoopParams | None = None,
) -> WorkforceState:
    """Advance the pipeline one fiscal year. Returns a NEW state.

    With ``loop=None`` this is the 1a deterministic skeleton. With a LoopParams
    the R1/R2/B1 feedback factors (1b) adjust the certification and CPC
    attrition rates for this year.

    Flow order within the year (annual resolution, see calibration D2/D3):
      1. Academy graduates -> developmental (grad_rate); the remainder washes
         out (washout_rate). Academy then refills with this year's hiring
         intake — the ~6-month cohort is treated as flushed yearly (D3).
      2. Developmentals attempt certification at the (R2-adjusted) rate; the OJT
         pass rate reach CPC, the rest wash out (D13). A fixed developmental
         attrition headcount also leaves (FAA reports a count, D6).
      3. CPC loses the (R1-amplified) attrition rate of its stock, capped at
         MAX_CPC_ATTRITION_RATE (retire + resign, D4/D6/D10).
      4. Applicant pool refreshes to one year of applications; hiring is drawn
         from it but is non-binding in baseline (applications >> hiring).
    """
    factors = feedback_factors(state, loop) if loop is not None else NEUTRAL_FACTORS
    eff_cert_rate = params.certification_rate * factors.cert_factor
    eff_cpc_attrition = min(
        params.cpc_attrition_rate * factors.attrition_multiplier,
        cal.MAX_CPC_ATTRITION_RATE,  # D10 structural invariant
    )

    grads_to_dev = state.academy * params.academy_grad_rate
    cert_attempts = state.developmental * eff_cert_rate
    certified = cert_attempts * params.ojt_pass_rate  # D13: the rest wash out in OJT

    new_academy = params.hiring  # D3: prior cohort flushed, refill with intake
    new_dev = (
        state.developmental - cert_attempts - params.dev_attrition + grads_to_dev
    )
    new_cpc = state.cpc - state.cpc * eff_cpc_attrition + certified
    new_applicants = params.annual_applications  # D2: fresh annual pool

    return replace(
        state,
        year=state.year + 1,
        applicants=max(0.0, new_applicants),
        academy=max(0.0, new_academy),
        developmental=max(0.0, new_dev),
        cpc=max(0.0, new_cpc),
    )


def simulate(
    initial: WorkforceState,
    params: FlowParams,
    years: int,
    loop: LoopParams | None = None,
) -> list[WorkforceState]:
    """Run the model for ``years`` annual steps.

    Returns the initial state followed by one state per simulated year, so the
    result has length ``years + 1``. Pass ``loop`` to enable the 1b feedback
    loops; omit it for the 1a deterministic skeleton.
    """
    trajectory = [initial]
    state = initial
    for _ in range(years):
        state = step(state, params, loop)
        trajectory.append(state)
    return trajectory
