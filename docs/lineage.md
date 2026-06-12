# TowerGuard — Decision Lineage: Every Threshold Has a Source

**TowerGuard does not invent procedures — every decision point stands on existing ATC standards, optimized with modern tooling.**

This document traces each decision point that drives a TowerGuard display or recommendation back to the established professional standard, fielded-system precedent, or academic lineage it rests on. The intent is twofold: to demonstrate to reviewers that nothing here is invented from scratch, and to make explicit to operators exactly what authority stands behind every number on the screen. Where a value is a demonstration-calibrated figure rather than a hard regulatory threshold, the table below labels it honestly and does not present it as an FAA requirement.

---

## Decision point → TowerGuard implementation → Professional basis

| Decision point | TowerGuard implementation | Professional basis |
|---|---|---|
| **Terminal-area horizontal separation, 3.0 NM** | First of the two conflict conditions | FAA Order JO 7110.65BB ¶5-5-4, Separation Minima (verified against the local PDF); international cross-reference: ICAO Doc 4444 PANS-ATM |
| **Vertical separation, 1000 ft** | Second of the two conflict conditions | FAA Order JO 7110.65BB ¶4-5-1, Vertical Separation |
| **Pairwise extrapolated conflict detection (120 s horizon, closest point of approach)** | conflict_geometry module | Fielded-system precedent: STARS/ERAM Conflict Alert (safety-net role, per SKYbrary STCA); algorithmic lineage: NASA Paielli pairwise terminal CD&R (NTRS 20170011259) |
| **Tier time thresholds, 60 / 90 s** | CRITICAL / HIGH classification | Conceptually aligned with the STCA tactical-alert window. *Honest note: the specific values are calibrated for this demo; the tiering structure follows STARS/ERAM Conflict Alert and STCA practice.* |
| **Score → tier breakpoints, 0.40 / 0.65 / 0.85** | traffic / workload classification | *Honest note: these are demo-calibrated values; the tiering convention follows FAA traffic-management practice.* |
| **staffed / recommended staffing** | workload_index, grounded in real baselines | FAA Controller Workforce Plan 2025–2028, facility table, pp. 28–33 (CRWG target vs. CPC on-board; e.g., JFK 33/30); model scientific review: TRB Special Report 357 (2025) |
| **Human decides; AI performs information acquisition and analysis only** | HUMAN DECISION REQUIRED prompt; Confirm action | FAA Order JO 7110.65BB ¶2-1-2, Duty Priority; Parasuraman, Sheridan & Wickens (2000), IEEE TSMC-A 30(3) — four-stage automation model, stages 1–2 only |
| **Five-part shift-handover briefing with sign-off** | Narrator briefing + Controller Confirmed | FAA Order JO 7110.65BB ¶2-1-24, Transfer of Position Responsibility; FAA Order JO 7210.3EE ¶2-2-4; narrative-content lineage: NASA ASRS controller report sets |
| **Loss of feed displays DEGRADED — never masquerades as LOW** | UNKNOWN tier + banner | Safety-critical fail-safe principle: a fault must never be presented as a safe state |
| **System positioning** | Whole system | Nearest predecessor: NASA ATD-2/IADS (NTRS 20205006383) — data integration has precedent; what is new is the single controller-facing interface plus LLM-generated handover narration |

---

The complete source set is in `docs/references/` (13 official documents, including the original-text PDFs).
