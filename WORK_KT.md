# WORK — Katherine: Frontend (all new presentation)

*Work split · pairs with [masterplan.md](masterplan.md) · Deadline 6/21 23:59 ET*
*Bo-Ru produces data, you consume it. The only interface between you two is a single JSON file.*

---

## Your scope

You own the **entire new frontend**. You consume one JSON file; you never touch the Python model, the backend, or the existing real-time code.

The contract is **`contracts/scenario_results.example.json`**. Bo-Ru ships a hardcoded stub on **Day 1 morning** so you are never blocked — build the whole UI against the stub, then swap to live data on Day 2 with zero code changes.

## Components you own

| # | Component | Priority | Notes |
|---|---|---|---|
| N6 | Scenario Dashboard (5 curves) | P0 | the demo centerpiece |
| N7 | Intervention Timing Comparator | P0 | slider + cumulative cost-gap area chart |
| N11 | Sensitivity / Tornado Chart | P1 | |
| N12 | Assumption Ledger UI | P1 | parameters + sources + confidence |
| N13 | Causal Loop Diagram (CLD) | P1 | mostly a static diagram, see below |
| — | Demo shell / layout | P0 | stitch everything into one page |
| — | Embed Bo-Ru's Live Validation panel | P0 | as a component/route — you just place it |

**Stack:** Chart.js + Leaflet (per masterplan). HTML/CSS/JS frontend served by the existing FastAPI app.

## What you DON'T touch

- Python models / FastAPI backend
- OpenSky / Redis / SSE live pipeline
- The Leaflet live-validation map **internals** — Bo-Ru gives you an embeddable panel; you only position it.

---

## Which JSON fields each component reads

| Component | Reads from `scenario_results.example.json` |
|---|---|
| **N6 Scenario Dashboard** | `scenarios[].years`, `scenarios[].series.*` (total_controllers / cpc / staffing_pct_of_target), `scenarios[].bands` (fan chart), `targets` (FAA + NATCA lines) |
| **N7 Timing Comparator** | `timing_comparator.*` (trajectories, cumulative_cost_gap_usd, net_cost_of_delay_usd) |
| **N11 Tornado** | `sensitivity[]` |
| **N12 Assumption Ledger** | `assumptions[]`, `meta` (model_version, calibration_date, freshness 🟢🟡🔴) |
| **N13 CLD** | **No JSON** — static diagram of the R1 / R2 / B1 loops from [masterplan.md](masterplan.md) §7.3 |
| **Policy brief render** | `policy_brief.*` (executive_summary, key_findings, cost_of_delay, recommendations, limitations) |
| **Live Validation panel** | not your data — embedded from Bo-Ru |

> **Note — `scenarios[].safety.risk_index` is a RELATIVE risk MULTIPLIER** (1.0 = rested baseline; e.g. do-nothing peaks ~3.6×), NOT a 0–1 score or an accident probability. Always render it with the disclaimer + the top-level `safety_context` string (FY2023 near-miss note), and pair it with the money curves — safety is the cost money can't buy back.

---

## 4-day schedule

| Day | What | Done when |
|---|---|---|
| **Day 1 (6/17)** | Agree on the JSON schema with Bo-Ru → build demo shell + N6 dashboard skeleton **against the stub JSON** | 5 curves render from stub data |
| **Day 2 (6/18)** | N7 timing comparator (slider → cost-gap area), polish N6, embed Live Validation panel, swap stub → live JSON | slider interaction works end-to-end |
| **Day 3 (6/19)** | N11 tornado, N12 assumption ledger, N13 CLD, render policy brief, Responsible-AI UI rules (below) | full demo flow looks finished |
| **Day 4 (6/20)** | Visual polish, screens for the video, submit | — |

---

## Design rules (these drive the 35% AI / Responsible-AI score — masterplan §11, §13)

1. **Always show Monte Carlo confidence bands**, never bare point estimates. Brief 6 explicitly penalizes single-point predictions. Use `scenarios[].bands`.
2. **Show BOTH FAA (12,563) and NATCA (14,633) targets** — don't visually favor either side.
3. **Assumptions panel is mandatory and always reachable.**
4. **No single scenario shown/exported without the comparison context** (prevents cherry-picking).
5. Freshness indicator (🟢🟡🔴) from `meta.freshness` visible on the dashboard.

## Where to find detail

- Dashboard + 4-day flow → [masterplan.md](masterplan.md) §6
- Timing comparator design → §10.2 · 5 scenarios → §10.1 · tipping points → §10.3
- Assumption ledger / drift → §12 · Responsible AI → §13 · demo script → §14
