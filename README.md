# TowerGuard

> **Non-certified decision-support — not for operational use.**

**TowerGuard is a "Cost of Doing Nothing" simulator for the US air-traffic-controller (ATC) staffing crisis** — a decision-support tool for policymakers (USAII Global AI Hackathon 2026, Challenge Brief 6, Direction A). It projects the controller workforce across policy scenarios over FY2025–FY2036 and quantifies the cost + safety risk of delaying intervention.

## Two halves

| Half | What it is | Where |
|---|---|---|
| **Simulator** (the project) | System-dynamics workforce model → one JSON contract → policy dashboard | `models/` → `contracts/scenario_results.example.json` |
| **Live Validation** (real-time) | The original real-time ATC advisory system, now embedded as a "this model reflects reality" panel | `modules/` → Redis → `agents/` → `dashboard/` |

## Start here
- **[HANDOVER.md](HANDOVER.md)** — orientation + reading order (read this first).
- **[masterplan.md](masterplan.md)** — the simulator plan + research evidence base.
- **[contact.md](contact.md)** — the Redis interface contract (real-time half).
- **[WORK_BORU.md](WORK_BORU.md)** / **[WORK_KT.md](WORK_KT.md)** — the work split.

## Layout
```
models/      simulator model layer — workforce stock-flow, scenarios + timing,
             economic cost, Monte Carlo, safety, validation, lifecycle, community
contracts/   scenario_results.example.json — the frontend JSON contract
modules/     real-time deterministic signals (traffic / conflict / workload)
dashboard/   FastAPI + SSE + Leaflet UI
agents/      LLM agents (orchestrator, narrator) for the Live Validation panel
fixtures/    mock_katherine — advisory/briefing stand-in until agents/ replace it
docs/        evidence base + design notes
tests/       290 tests across both halves
```

## Run

Simulator JSON contract:
```bash
python -m models.scenario_results        # (re)generate contracts/scenario_results.example.json
```

Live Validation (real-time half):
```bash
pip install -r requirements.txt
docker compose up -d redis
DEMO_MODE=1 python -m modules.runner      # 3 deterministic signals + demo fleet
python -m fixtures.mock_katherine         # advisory/briefing stand-in
python -m dashboard.server                # -> http://127.0.0.1:8800
```

## Tests
```bash
pytest -q
ruff check .
```

*USAII Global AI Hackathon 2026 · Graduate Track · Bo-Ru & Katherine*
