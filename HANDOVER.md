# HANDOVER — for Katherine (and her agent)

*Updated 2026-06-18 by Bo-Ru · single entry point: read this first, then the files it links.*

This is the one doc to orient on before touching anything. It tells you **what the project is now**, **your two jobs**, **which files to read in what order**, and **the exact interfaces** so the two halves stay decoupled.

---

## 1. What TowerGuard is now (the pivot)

TowerGuard is a **"Cost of Doing Nothing" simulator** for the US air-traffic-controller (ATC) staffing crisis — a decision-support tool for policymakers (Challenge Brief 6, Direction A). It projects the controller workforce across policy scenarios over 2026–2036 and quantifies the cost + safety risk of delaying intervention.

The project has **two halves**, and **you own a piece of each**:

| Half | What it is | Data path | Status |
|---|---|---|---|
| **Simulator (NEW)** | The cost-of-doing-nothing model + dashboard | `models/` → `contracts/scenario_results.example.json` → **your new frontend** | model layer done; frontend = **your Job A** |
| **Live Validation (OLD real-time)** | The original real-time ATC advisory system, now embedded as a "this model reflects reality" panel | OpenSky → `modules/` → Redis → **your two LLM agents** → `dashboard/` | modules + dashboard done; agents = **your Job B** |

---

## 2. Your two jobs

### Job A — the simulator frontend (NEW)
Build the dashboard components that consume **one JSON file**: `contracts/scenario_results.example.json`. You never touch the Python model or the backend.
- **Spec:** [WORK_KT.md](WORK_KT.md) — your components (N6–N16), the JSON-field map, and the design rules that drive the score.
- **Interface:** the JSON contract (see §4 below for the block-by-block dictionary).

### Job B — the two LLM agents → Live Validation panel (OLD)
Finish [`agents/orchestrator.py`](agents/orchestrator.py) and [`agents/narrator.py`](agents/narrator.py). These **replace** the stand-in `fixtures/mock_katherine.py` and power the real-time advisory + handover briefing that becomes the embedded **Live Validation panel** in the new dashboard.
- **Spec / interface:** [contact.md](contact.md) — the frozen Redis contract (topics, the module-event envelope, the advisory output schema, the briefing format, and the v1.2 lifecycle additions). Build to that schema and the two halves stay independent.
- **Current state:** you've pushed first versions of both agents; until they're wired in, `mock_katherine` stands in.

---

## 3. Reading order (for your agent)

**For Job A (frontend):**
1. **[WORK_KT.md](WORK_KT.md)** — your scope, components N6–N16, which JSON field each reads, design rules.
2. **[contracts/scenario_results.example.json](contracts/scenario_results.example.json)** — the real data you build against (11 blocks; §4 below explains each).
3. **[masterplan.md](masterplan.md)** — the "why" / evidence base. Read selectively: §6 (dashboard), §10 (scenarios + timing comparator), §11 + §13 (Responsible AI), §14 (demo script). It's long and in Chinese — reference, not cover-to-cover.

**For Job B (agents):**
4. **[contact.md](contact.md)** — the Redis interface contract (your agents' input/output schema). This is the contract; honor it.
5. **[PROGRESS.md](PROGRESS.md)** — status of the Live-Validation half specifically (the real-time modules/dashboard you integrate with). Note: it predates the pivot, so its framing describes the real-time system as if it were the whole project — read it as **Job B context only**, not the project overview (this doc is the overview).

---

## 4. The JSON contract — block-by-block (Job A)

`contracts/scenario_results.example.json` (~35 KB) has **11 top-level blocks**. It is committed and is real model output (regenerate any time with `python -m models.scenario_results`). Build against it offline; it has no external dependencies.

| Block | What it is | Your component |
|---|---|---|
| `meta` | model version, calibration date, horizon, data sources, **`freshness` (🟢🟡🔴, computed — currently 🟡)**, notes | N12 / dashboard header |
| `targets` | `faa` (12,563) + `natca` (14,633) staffing targets — **show both, favor neither** | N6 (target lines) |
| `safety_context` | the FY2023 near-miss note + the "risk_index is a relative multiplier, not an accident probability" disclaimer string | N6 safety caption |
| `scenarios[]` | the 5 scenarios; each has `years[]`, `series.*` (total/cpc/developmentals/staffing_pct/overtime), `bands` (p10/p90 fan), `costs`, `safety` (`risk_index[]`, `months_below_85pct`) | **N6 (centerpiece)** |
| `timing_comparator` | intervene at 2026–2030: `trajectories`, `net_cost_of_delay_usd`, `cumulative_cost_gap_usd` | **N7 (slider)** |
| `sensitivity[]` | tornado data: parameter, baseline, low/high impact | N11 |
| `assumptions[]` | parameter, value, source, confidence | N12 |
| `community_exposure` | `methodology`, `caveats`, `facilities[]` — the "who gets hurt first" ranking + per-metro NAS delay cost | **N16** |
| `validation` | `backtest` (predicted vs actual CPC), `extreme_conditions[]`, `reproduction[]`, `method_note` | **N14** |
| `lifecycle` | `freshness`, `drift_detection`, `human_in_loop` (informs/decides/two-review/bypass), `governance`, `versioning` | **N15** |
| `policy_brief` | executive_summary, key_findings, cost_of_delay, recommendations, limitations | brief render |

**Three things in this JSON are the score-winners — surface them, don't bury them:**
- `validation` (N14) = the evaluation strategy (35% AI Reasoning). The backtest honestly shows the model under-predicts CPC ~8% on the COVID window; **that's the point** — don't hide it, caption it as the drift monitor catching a structural break.
- `lifecycle` (N15) = the grad "infrastructure thinking" differentiator. `freshness` is **computed** (🟡), not decorative.
- `community_exposure` (N16) = answers the contest title "communities." Hook = **New York (most exposed) vs Chicago (top-traffic but ~zero exposure, because it's 107% staffed)**. The dollar is real BTS data but is an **upper bound, not a "staffing cost"** — always show `caveats`.

---

## 5. Current backend status (what's done, what's stub)

**Simulator (Job A's data source) — DONE:**
- Full model layer in `models/`: N1 workforce stock-flow, N2 scenario engine + timing, N3 Monte Carlo bands, N4 economic cost, N5 safety risk, N8 policy brief (template), plus validation, lifecycle, community.
- `policy_brief` is **template-first** (every figure pulled live from the model); the optional LLM-rephrase layer is **deferred** (no API key) — render the template text as-is.
- The JSON is **deterministic, offline** — there is no separate "live vs stub" version; the committed example IS the real output.

**Live Validation (Job B's integration target) — modules done, agents are yours:**
- `modules/` (traffic density, conflict geometry, workload index), `dashboard/` (FastAPI/SSE/Leaflet), Redis pub/sub — all built and running.
- `fixtures/mock_katherine.py` currently stands in for your two agents; replace it with `agents/orchestrator.py` + `agents/narrator.py`.
- **Caveat (from PROGRESS.md):** the real-time path has only ever run in `DEMO_MODE` — live OpenSky has not been run end-to-end.

**Tests:** 290 passing across both halves; `ruff check` clean. (The repo lints with `ruff check`; it is hand-formatted, not `ruff format`-enforced — match the surrounding style.)

---

## 6. What NOT to touch
- The Python model (`models/`), the JSON generator, the FastAPI backend, `modules/`, the Redis/SSE pipeline. You consume their outputs; you don't edit them.
- The Leaflet live-validation map **internals** — you position the embeddable panel, not its guts.
- The two contracts are the boundary: **`contracts/scenario_results.example.json`** (Job A) and **`contact.md`** (Job B). Build to them; if either needs to change, raise it with Bo-Ru — don't fork the schema.

---

## 7. Run it locally
```bash
docker compose up -d redis                 # Redis (Live Validation half)
DEMO_MODE=1 python -m modules.runner       # 3 deterministic signals + demo fleet
python -m fixtures.mock_katherine          # advisory/briefing engine (until your agents replace it)
python -m dashboard.server                 # -> http://127.0.0.1:8800

python -m models.scenario_results          # (re)generate the simulator JSON contract
```

---

*Questions on the simulator JSON → Bo-Ru. Questions on the Redis contract → contact.md §1–§6 (+ §7 v1.2). Keep the two halves decoupled and we never block each other.*
