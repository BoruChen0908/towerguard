"""
Workforce calibration data — initial stocks and flow rates for the TowerGuard
air-traffic-controller stock-flow model (N1).

Scope: this module holds ONLY the workforce-pipeline calibration consumed by
models/workforce_sd.py. Economic (N4) and safety (N5) constants live in their
own modules and are added when those are built. Style mirrors config.py:
module-level constants with an inline source citation on every value.

================================================================================
PROVENANCE & DECISIONS — Stage 1a (deterministic skeleton)
================================================================================
Data sources used
  - GAO-26-107320 (Dec 2025): total controller headcount, historical trend,
    recruitment funnel.
  - FAA Controller Workforce Plan (CWP) 2026-2028: CPC count, hiring targets,
    attrition, FY2025 actuals.
  - FAA / Reuters (Apr 2026): developmental headcount snapshot.
  - masterplan.md §7.1, §7.2, §13, Appendix A (this repo) — consolidated.

Reconciliation decisions (the published numbers do not trivially add up, and
several "calibration values" are flows or cumulative totals, not point-in-time
stock levels):

  D1  "Total controllers" = Developmental + CPC, and is DERIVED, not stored.
      GAO reports 13,164 total at FY2025 end; FAA CWP reports ~11,000 CPC, so
      initial Developmental = 13,164 - 11,000 = 2,164. "Total controllers"
      excludes Academy students (pre-facility) — matches FAA's controller-
      workforce definition.
      We do NOT use the ~4,000 developmental figure (FAA/Reuters, Apr 2026) as
      the initial stock: it is a later, post-hiring-surge snapshot that would
      contradict the FY2025-end total of 13,164. Kept as a future validation
      checkpoint instead (the skeleton's developmental stock converges toward
      ~4,000 on its own — see workforce_sd.py).

  D2  Applicants: GAO's 106,533 is CUMULATIVE applications over FY2017-2022
      (6 yr, Track 1) — a flow accumulation, NOT a stock. Converted to an
      annual application rate (106,533 / 6 ≈ 17,756 / yr); initial Applicant
      stock seeded with one year of applications.

  D3  Academy is a ~6-month process but the model runs at ANNUAL resolution, so
      most of a year's intake graduates within the same year. Academy stock is
      therefore approximate; seeded with FY2025 annual intake (~2,028) and the
      prior cohort is treated as flushed each year.

  D4  Retirement age-structure deferred. masterplan flows F4 (CPC->Eligible) and
      F5 (Eligible->out) imply an age-structured sub-stock; 1a collapses
      retirement + resignation into a single constant CPC attrition rate. The
      age-structured "retirement cliff" (§10.3) is a later refinement.

  D5  NO feedback loops in 1a. All rates constant. R1 burnout spiral, R2
      knowledge drain, B1 load shedding (§7.3) are layered in stage 1b, where
      attrition / certification rates become functions of workload.

  D6  Attrition split (corrected in 1c). Total FY2025 attrition of 1,460 splits
      THREE ways, not two: CPC departures + developmental attrition (201) +
      academy washout (~30% of ~2,028 intake ≈ 608). The 1c back-cast proved the
      2-way split (1,460 - 201 = 1,259, rate 0.114) over-attrited CPCs and broke
      the CPC/dev composition. Corrected: CPC = 1,460 - 201 - 608 = 651, rate
      651 / 11,000 ≈ 0.059 — also a realistic ATC turnover figure. Reconciliation:
      1,460 = 651 (CPC) + 201 (dev) + 608 (academy washout).

--------------------------------------------------------------------------------
PROVENANCE & DECISIONS — Stage 1b (feedback loops, masterplan §7.3)
--------------------------------------------------------------------------------
  Loops are opt-in: they enter workforce_sd.step() via an optional LoopParams.
  loop=None reduces the model exactly to the 1a deterministic skeleton.
  All functional forms below are ILLUSTRATIVE, anchored to the cited literature;
  precise calibration is stage 1c and the coefficients are the primary Monte
  Carlo / sensitivity targets (N3 / N11).

  D7  R1 burnout spiral (reinforcing). Staffing gap -> overtime -> fatigue ->
      attrition. Encoded as an attrition MULTIPLIER driven by a SAFTE-FAST-style
      effectiveness score with a hard threshold at 0.77 (= 18.5 h awake = BAC
      0.05%; Hursh et al. 2004, FAA-recognized). Above 0.77 the attrition
      response is mild and linear; below it, a quadratic "spiral" kick.
      Amplification magnitude is order-of-magnitude anchored to the Brazil
      aviation fatigue study (arXiv 2201.05438: +23.3% relative fatigue risk as
      monthly night shifts go 1->13). The operational staffing reference is the
      FAA target (12,563) — the lower, conservative choice (smaller gap, harder
      to accuse of exaggeration); the dashboard still shows both targets.

  D8  R2 knowledge drain (reinforcing). Certification throughput scales with
      instructor availability, which scales with the CPC pool (DOT OIG:
      shortage of qualified ATC instructors). Encoded as a certification-rate
      factor = clamp(cpc / 11,000, 0.5, 1.0): fewer CPCs -> fewer trainers ->
      slower certification -> fewer CPCs.

  D9  B1 load shedding (balancing, costly). Below the 85% staffing floor (§10.3)
      traffic is shed (flow control), which RELIEVES controller workload and
      partly offsets R1 — at the price of economic loss (priced later by N4).
      2025 shutdown shed up to ~10% of flights at 40 airports (A4A); shed
      fraction capped at 0.15 here. This is why severe understaffing does not
      simply explode attrition: the system trades flights (economic pain) to
      keep controllers below the fatigue cliff.

  D10 Effective CPC attrition rate is capped at 0.95/yr — a structural invariant
      (a stock cannot lose more than itself in one step), not a calibrated value.

--------------------------------------------------------------------------------
PROVENANCE & DECISIONS — Stage 1c (historical calibration, §12.3)
--------------------------------------------------------------------------------
  D11 Historical back-cast. FY2015 composition is assumed at the FY2025 CPC/total
      ratio (0.836) — no FY2015 split is published, so this is the best proxy.
      Average historical hiring is solved so the 10-yr run (loops on) reproduces
      GAO's FY2025 total of 13,164: ~1,192/yr. That sits within the documented
      non-COVID hiring range (1,700 FY2024 -> 2,028 FY2025; the COVID low of 500
      was a one-off). The back-cast reproduces both the total (13,166) and the
      composition (CPC 11,258 vs real ~11,000) — validating the pipeline
      structure and the corrected attrition (D6).

  D12 Calibration surfaced that the forward baseline over-grew with the 0.059
      rate. The INITIAL hypothesis was a missing retirement wave (1981 PATCO
      cohort). RESEARCH OVERTURNED THIS (FAA CWP / GAO, queried June 2026): the
      retirement wave peaked in 2007 (828 retirements); forward retirements are
      LOW and declining (~205-236/yr, only 463 eligible at end-FY2024) and the
      workforce is young (26-43). So the real cause is NOT retirement but
      under-counted non-retirement attrition + missing OJT washout. Resolved in
      Stage 1d (D13-D15), not an age structure. NOTE: §10.3's "retirement cliff
      coming" framing is outdated for a 2026-2036 horizon — flag for the deck.

--------------------------------------------------------------------------------
PROVENANCE & DECISIONS — Stage 1d (forward attrition + OJT washout, option 1)
--------------------------------------------------------------------------------
  D13 OJT / certification washout. The funnel (GAO FY2017-2022) shows academy
      completers 2,610 -> certified/OJT 2,258, i.e. ~13.5% wash out DURING
      certification (separate from the 30% academy washout). The model now routes
      developmentals through certification at an OJT pass rate of 2,258/2,610
      ≈ 0.865; the rest leave without becoming CPCs. Structural — always on,
      including the back-cast.

  D14 Two attrition regimes (both data-anchored):
        - Historical (back-cast, FY2015-2025): CPC attrition 0.059 (D6).
        - Forward (projection, FY2025+):        CPC attrition 0.10.
      FAA's own CWP projects forward attrition ABOVE the FY2025 actual (6,872
      over FY2025-28 ≈ 1,718/yr vs 1,460), and the hiring surge fills the
      OJT-washout-prone developmental stage. The forward 0.10 is set by
      calibrating the baseline to FAA's plan intent (modest growth toward the
      staffing-target band, not overshooting) — calibration-to-reference,
      slightly above the bottom-up projection. It lands near the OLD pre-1c
      0.114, but now for the RIGHT reason (forward non-retirement attrition +
      OJT), not a fake retirement proxy.

  D15 With D13+D14 both periods reproduce credibly:
        - Back-cast (OJT on, attrition 0.059, hiring ~1,326/yr): total 13,166 and
          CPC 10,982 — total AND composition now match (OJT washout fixed the
          composition the 1c-only fit lacked).
        - Forward baseline (2,200-2,400/yr, attrition 0.10): total grows 13,164
          -> ~14,692 toward the staffing-target band while CPC holds ~10,000 and
          developmentals rise to ~4,600 (matching the FAA/Reuters Apr-2026 surge
          figure ~4,000). Story: hiring grows headcount, but CERTIFIED
          controllers barely move (certification lag + OJT washout).

--------------------------------------------------------------------------------
PROVENANCE & DECISIONS — N2 (scenario engine, §10.1)
--------------------------------------------------------------------------------
  D16 Five scenarios. The masterplan's "Baseline" and "Current Plan" were nearly
      identical (both = FAA CWP trajectory); split here so the curves are
      distinct:
        baseline      hiring flat at FY2025 actual (2,028) — status quo, no new effort.
        do_nothing    hiring 500/yr (FY2021 COVID low, GAO).
        current_plan  FAA CWP ramp 2,200 -> 2,300 -> 2,400 (HIRING_TARGET_FY2026-28).
        accelerated   hiring 2,600 (assumption, ~max Academy capacity) + TSS cert
                      (-27% time, Appendix A) + retention x0.85 (assumption, cf.
                      $12.3M bonus) + academy grad 0.78 (assumption, CTI 41% vs 22%).
        disruption    current_plan + a 2025-style shutdown shock: ~450 trainee
                      loss (Appendix A) + a hiring dip, in FY2027 (assumption).
      All scenarios run loops on. "(assumption)" marks a design choice, not a
      published figure. Cost is NOT priced here — that is N4.

--------------------------------------------------------------------------------
PROVENANCE & DECISIONS — N4 (economic impact, §8)
--------------------------------------------------------------------------------
  D17 Cost is driven by the workforce state, anchored to documented figures:
        - Delay/cancellation: a controller-attributable COST MULTIPLE of the
          $33B/yr NAS delay cost (FAA/Nextor 2019). The multiple scales with the
          CPC staffing gap (vs the FAA target), linear from 5% at the current gap
          (~0.124) to 61% at a shutdown-level gap (~0.25 ~ ratio 0.75 ~ the 2025
          10% shed), then extrapolated above that. Cost = $33B x multiple.
        - Overtime: scales with the flow-control-relieved gap, anchored at $200M
          for the current gap (FY2024).
      COLLAPSE CEILING (updated, see #7 discussion): the multiple is capped at
      3.0 (COLLAPSE_CEILING), NOT the old 1.0. Rationale: the gap-driven multiple
      naturally peaks at ~3x when do_nothing bottoms out (CPC ~19% of target), so
      3x is the natural peak, not an imposed number; ~$99B/yr at near-total
      collapse is still BELOW the A4A-implied range ($100-210B/yr for sustained
      10% shed), so it stays conservative. The old 1.0 cap artificially
      suppressed collapse cost and created a "delaying further is free" artifact
      in the timing comparator; 3.0 fixes it. The timing cost-of-delay CURVE
      (~$70B per year of delay, roughly linear) is INSENSITIVE to the ceiling
      above ~2x — so the headline does not hinge on this assumption.
      Only CONTROLLER-ATTRIBUTABLE cost is counted (conservative — the baseline
      non-staffing delay is not charged to the staffing decision).

--------------------------------------------------------------------------------
PROVENANCE & DECISIONS — N2 timing (intervention timing comparator, §10.2)
--------------------------------------------------------------------------------
  D18 The comparator runs a chosen intervention starting at each candidate year
      (2026-2030); before the start year it follows "do_nothing". Net cost of
      delay = cumulative cost(start late) - cost(start early), priced by N4.
      OBSERVED: net cost of delay is positive and monotonic (1-yr delay ~$70B,
      4-yr ~$146B) but CONCAVE / front-loaded — NOT the convex "exponential"
      acceleration §10.2 implies. Cause: N4 caps annual delay cost at the $33B
      NAS total (D17), so the nonlinear WORKFORCE collapse has a capped DOLLAR
      expression. Restoring convexity (to match §10.2) would mean letting cost
      escalate in deep collapse via the lost-demand / GDP cascade (§8.1) — a
      deliberate OPEN choice, conservative for now, flagged for the deck like the
      §10.3 retirement item (cal D12).

--------------------------------------------------------------------------------
PROVENANCE & DECISIONS — N3 (Monte Carlo, §3 / §11)
--------------------------------------------------------------------------------
  D19 Why: ISPOR good practice and Brief 6 both require reporting distributions,
      not point estimates ("single-point predictions" is a listed common
      mistake). N3 samples the uncertain parameters and reports P10/P50/P90 bands
      per year (the JSON `bands` field; fan charts in N6).
      What is sampled: multiplicative factors on EACH scenario's base flow / loop
      params, so scenario differences are preserved. The widest ranges sit on the
      most illustrative, least-calibrated coefficients — the R1 loop
      (effectiveness sensitivity, below-threshold amplification) — which is
      honest: our least certain assumptions drive the most output uncertainty.
      Certification range tracks the documented 2-6 yr (median 3) certification
      time. Sampler is seeded (MC_SEED) for reproducibility.

--------------------------------------------------------------------------------
PROVENANCE & DECISIONS — N5 (safety risk, §9)
--------------------------------------------------------------------------------
  D20 Safety risk index = a RELATIVE risk MULTIPLIER (1.0 = rested / fully-staffed
      baseline), NOT an accident probability. §9.2: serious near-misses are rare
      events (~0.00004% of ops) with high noise, so the model must NOT predict
      accidents — shown with wide bands + disclaimer. GROUNDED in fatigue science
      (not an arbitrary blend): risk is driven by SAFTE-FAST effectiveness (which
      itself integrates staffing via the loops), anchored so effectiveness 0.77 =
      the BAC-0.05% point ~ 2.0x relative risk (Williamson & Feyer; driving /
      fatigue literature), rising quadratically below it toward a 5.0x ceiling
      (severe impairment ~ BAC 0.10% / 24h awake ~ 4-7x, conservatively 5x). The
      0.77 -> 2x mapping is an analogy to ATC error risk — no ATC accident-rate-
      vs-fatigue dataset exists (that IS the rare-event problem). months_below_85pct
      counts projected years with CPC < 85% of the FAA target, x12. The near-miss
      trend (FY2023: 19 serious, 7-yr high) is corroborating CONTEXT, not a fit.
================================================================================
"""

# ---------------------------------------------------------------------------
# Initial stocks — FY2025 end snapshot
# ---------------------------------------------------------------------------
TOTAL_CONTROLLERS_FY2025 = 13164    # GAO-26-107320 (hard number, FY2025 end)
TOTAL_CONTROLLERS_FY2015 = 14007    # GAO-26-107320 — historical anchor (-6% / decade); validation target for stage 1c
CPC_FY2025 = 11000                  # FAA CWP 2026-2028 (approx) — 21st-century low

# Derived (D1): Developmental + CPC = Total controllers
INITIAL_DEVELOPMENTAL = TOTAL_CONTROLLERS_FY2025 - CPC_FY2025  # = 2164

# Academy (D3): seeded with FY2025 annual intake
ACADEMY_ANNUAL_INTAKE_FY2025 = 2028  # FAA CWP 2026-2028 (FY2025 actual)
ACADEMY_DURATION_MONTHS = 6          # Appendix A (approx) — basis for D3
INITIAL_ACADEMY = ACADEMY_ANNUAL_INTAKE_FY2025

# Applicants (D2): cumulative -> annual rate
APPLICATIONS_CUMULATIVE_FY2017_2022 = 106533  # GAO-26-107320 (Track 1, 6 yr)
APPLICATION_YEARS = 6
ANNUAL_APPLICATION_RATE = APPLICATIONS_CUMULATIVE_FY2017_2022 / APPLICATION_YEARS  # ≈ 17756 / yr
INITIAL_APPLICANTS = round(ANNUAL_APPLICATION_RATE)

# ---------------------------------------------------------------------------
# Flow rates
# ---------------------------------------------------------------------------
# F1 Hiring (-> Academy) — policy lever; year-varying schedule comes with the
# scenario engine (N2). 1a uses a constant default.
HIRING_TARGET_FY2026 = 2200          # FAA CWP 2026-2028
HIRING_TARGET_FY2027 = 2300          # FAA CWP 2026-2028
HIRING_TARGET_FY2028 = 2400          # FAA CWP 2026-2028

# F2 / F7 Academy graduation vs washout
ACADEMY_WASHOUT_RATE = 0.30          # GAO: >30% washout FY2024
ACADEMY_GRAD_RATE = 1.0 - ACADEMY_WASHOUT_RATE  # 0.70

# F3 Certification (Developmental -> CPC): median 3 yr (range 2-6, FAA/National Academies)
DEV_CERTIFICATION_MEDIAN_YEARS = 3
CERTIFICATION_RATE = 1.0 / DEV_CERTIFICATION_MEDIAN_YEARS  # ≈ 0.333 / yr
# OJT washout (D13): funnel academy-complete 2,610 -> certified/OJT 2,258
OJT_PASS_RATE = 2258 / 2610          # ≈ 0.865 (13.5% wash out during certification)

# F7 Developmental attrition — FAA gives this as an annual count, not a rate
DEV_ATTRITION_ANNUAL = 201           # FAA CWP projected (was 102/yr 5-yr avg)

# F5 + F6 CPC attrition (retirement + resignation), collapsed per D4 + D6.
# D6 corrected in 1c: total attrition splits THREE ways (CPC + dev + academy
# washout), not two — see the 1c provenance block (D11/D12).
TOTAL_ATTRITION_FY2025 = 1460        # FAA actual (all stocks)
ACADEMY_WASHOUT_COUNT_FY2025 = round(ACADEMY_WASHOUT_RATE * ACADEMY_ANNUAL_INTAKE_FY2025)  # ≈ 608
CPC_ATTRITION_FY2025 = (
    TOTAL_ATTRITION_FY2025 - DEV_ATTRITION_ANNUAL - ACADEMY_WASHOUT_COUNT_FY2025
)  # = 651 (D6 corrected)
# Two regimes (D14): historical (back-cast) vs forward (projection).
CPC_ATTRITION_RATE_HISTORICAL = CPC_ATTRITION_FY2025 / CPC_FY2025  # ≈ 0.059 / yr (FY2015-2025)
CPC_ATTRITION_RATE = 0.10            # forward default — calibrated to FAA plan intent (D14)

# ---------------------------------------------------------------------------
# Staffing targets — present BOTH, do not pick sides (§13 Risk 2/4).
# Used by staffing-gap / scenario stages (not by the 1a skeleton math).
# ---------------------------------------------------------------------------
TARGET_FAA = 12563                   # FAA CWP 2026-2028 (lowered from 14,633)
TARGET_NATCA = 14633                 # NATCA / CRWG preferred

# ---------------------------------------------------------------------------
# Historical back-cast validation — stage 1c (§12.3). See D11.
# ---------------------------------------------------------------------------
HISTORICAL_CPC_TOTAL_RATIO = CPC_FY2025 / TOTAL_CONTROLLERS_FY2025  # 0.836 — FY2015 proxy
IMPLIED_HISTORICAL_HIRING = 1326     # solved with OJT washout on + historical attrition (D15)

# ---------------------------------------------------------------------------
# Feedback-loop parameters — stage 1b (R1/R2/B1, §7.3). See D7-D10 above.
# ILLUSTRATIVE forms anchored to the cited literature; coefficients are the
# primary Monte Carlo / sensitivity targets (N3/N11), calibrated for real in 1c.
# ---------------------------------------------------------------------------
# R1 — fatigue threshold (SAFTE-FAST 0.77 = 18.5 h awake = BAC 0.05%; Hursh 2004)
FATIGUE_THRESHOLD = 0.77             # FAA fatigue risk line
FATIGUE_THRESHOLD_FRA = 0.70         # Federal Railroad Administration alt (sensitivity)
# Maps staffing gap -> effectiveness drop. Anchored so current conditions
# (gap ~0.12: 167 OT hrs/yr, 41% on 6-day weeks) sit just ABOVE 0.77 — stressed
# but operational.
EFFECTIVENESS_GAP_SENSITIVITY = 1.2
ATTRITION_FATIGUE_SLOPE = 0.5        # above-threshold linear response
ATTRITION_FATIGUE_AMPLIFY = 15.0     # below-threshold quadratic kick (Brazil ~23%)

# R2 — certification throughput ~ instructor pool ~ CPC pool (DOT OIG)
CERT_INSTRUCTOR_REFERENCE = CPC_FY2025   # 11,000 = current instructor capacity
CERT_INSTRUCTOR_FLOOR = 0.5              # training never fully stops

# B1 — flow control (load shedding) below the 85% staffing floor (§10.3)
FLOW_CONTROL_FLOOR = 0.85            # cpc/target below which traffic is shed
FLOW_CONTROL_SHED_SENSITIVITY = 1.0  # shed fraction per unit below floor
FLOW_CONTROL_MAX_SHED = 0.15         # cap (2025 shutdown reached ~10%)

# Structural invariant (D10) — not a calibrated value
MAX_CPC_ATTRITION_RATE = 0.95

# ---------------------------------------------------------------------------
# Scenario parameters — N2 (§10.1). See D16. Sources inline; "(assumption)"
# marks a design choice, not a published figure.
# ---------------------------------------------------------------------------
SCENARIO_HORIZON_YEARS = 11          # FY2025 base -> FY2036 (masterplan 2026-2036)
INTERVENTION_START_YEARS = (2026, 2027, 2028, 2029, 2030)  # timing comparator slider (§10.2)

BASELINE_HIRING = ACADEMY_ANNUAL_INTAKE_FY2025   # 2,028 — status quo (FY2025 actual)
DO_NOTHING_HIRING = 500              # FY2021 COVID low (GAO)
# current_plan uses HIRING_TARGET_FY2026/27/28 (2,200/2,300/2,400) defined above.
ACCELERATED_HIRING = 2600            # (assumption) above the 2,400 plan ~ max Academy capacity

TSS_CERT_TIME_REDUCTION = 0.27       # Appendix A (2021 study): TSS shortens cert time 27%
CERTIFICATION_RATE_TSS = CERTIFICATION_RATE / (1 - TSS_CERT_TIME_REDUCTION)  # ≈ 0.456 / yr
ACADEMY_GRAD_RATE_CTI = 0.78         # (assumption) more CTI: §7.2 CTI 41% vs non-CTI 22% success
ACCELERATED_RETENTION_FACTOR = 0.85  # (assumption) better retention (cf. $12.3M bonus, 400 retained)

SHUTDOWN_TRAINEE_LOSS = 450          # 2025 shutdown (~400-500), Appendix A
DISRUPTION_SHOCK_YEAR = 2027         # (assumption) shock in the 2nd projected year
SHUTDOWN_HIRING_DIP = 1000           # (assumption) hiring ~halved in the shock year (cf. FY2021)

# ---------------------------------------------------------------------------
# Economic impact — N4 (§8). See D17. Sources inline.
# ---------------------------------------------------------------------------
OVERTIME_COST_FY2024 = 200_000_000          # $200M overtime, FY2024 (National Academies/Reuters)
OVERTIME_HOURS_PER_CONTROLLER_FY2024 = 167  # avg overtime hrs/controller FY2024 (Appendix A)
ANNUAL_DELAY_COST = 33_000_000_000          # $33B/yr total NAS delay cost (FAA/Nextor 2019)
CONTROLLER_DELAY_SHARE_NORMAL = 0.05        # controller-staffing share of NAS delays, normal (§8)
CONTROLLER_DELAY_SHARE_SHUTDOWN = 0.61      # controller-staffing share at 2025 shutdown peak (§8)
CURRENT_STAFFING_GAP = round(1 - CPC_FY2025 / TARGET_FAA, 3)   # ≈ 0.124 — anchors the 5% share / overtime
SHUTDOWN_STAFFING_GAP = 0.25                # gap (~ratio 0.75) at the shutdown's ~10% shed — anchors 61%
COLLAPSE_COST_CEILING = 3.0                 # max cost multiple of the $33B bill (D17): ~natural gap-driven peak, < A4A-implied range

# ---------------------------------------------------------------------------
# Monte Carlo — N3 (§3 "why Monte Carlo", ISPOR / Brief 6: report distributions
# not point estimates). See D19. Multiplicative factors on each scenario's base
# params (preserves scenario differences); the widest ranges are on the most
# illustrative coefficients (the R1 loop).
# ---------------------------------------------------------------------------
MC_SAMPLES = 500                     # masterplan ("Monte Carlo 500 次")
MC_SEED = 42                         # reproducibility
MC_ATTRITION_FACTOR = (0.80, 1.20)   # CPC attrition +/-20%
MC_CERT_FACTOR = (0.67, 1.50)        # certification rate (cert time ~2-6 yr around the 3-yr median)
MC_OJT_FACTOR = (0.90, 1.05)         # OJT pass rate (funnel-anchored, tight)
MC_R1_SENSITIVITY_FACTOR = (0.70, 1.30)  # R1 effectiveness sensitivity (illustrative -> wide)
MC_R1_AMPLIFY_FACTOR = (0.50, 1.50)      # R1 below-threshold amplification (most illustrative -> widest)

# ---------------------------------------------------------------------------
# Safety risk — N5 (§9). See D20. Reuses FATIGUE_THRESHOLD (0.77) and
# FLOW_CONTROL_FLOOR (0.85). Risk index is a RELATIVE indicator, not a forecast.
# ---------------------------------------------------------------------------
RISK_BASELINE_MULTIPLIER = 1.0       # rested / fully-staffed baseline
RISK_AT_FATIGUE_THRESHOLD = 2.0      # eff 0.77 = BAC 0.05% ~ 2x relative risk (Williamson & Feyer)
RISK_CEILING = 5.0                   # severe impairment ~ BAC 0.10% / 24h awake ~ 4-7x (conservative 5x)
NEAR_MISS_SERIOUS_FY2023 = 19        # serious near-misses, 7-yr high (FAA) — corroborating context
