#!/usr/bin/env bash
# Launch the TowerGuard live-validation stack locally (Redis + 3 services).
# Idempotent: skips anything already running. Reads .env automatically
# (config.py calls load_dotenv), so TOWERGUARD_USE_LLM / ANTHROPIC_API_KEY
# are picked up — Claude phrasing is live when the key is set.
#
#   bash scripts/run_live_stack.sh          # DEMO_MODE: synthetic traffic (no creds)
#   bash scripts/run_live_stack.sh --live   # REAL OpenSky (needs creds in .env)
#   bash scripts/run_live_stack.sh --logs   # also tail the logs after starting
#
# Stop with: bash scripts/stop_live_stack.sh
set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$(pwd)"
LOG_DIR="$ROOT/logs"
mkdir -p "$LOG_DIR"
PY="$(command -v python3)"
PORT=8800

LIVE_MODE=0
TAIL_LOGS=0
for arg in "$@"; do
  case "$arg" in
    --live) LIVE_MODE=1 ;;
    --logs) TAIL_LOGS=1 ;;
  esac
done

echo "→ TowerGuard live stack"

# 1. Redis
if redis-cli -p 6379 ping >/dev/null 2>&1; then
  echo "  ✓ redis already up"
else
  redis-server --port 6379 --save '' --appendonly no --daemonize yes
  sleep 1
  echo "  ✓ redis started"
fi

# 2. modules.runner — DEMO_MODE (synthetic) by default, or real OpenSky with --live
if pgrep -f "modules.runner" >/dev/null 2>&1; then
  echo "  ✓ runner already up"
elif [[ "$LIVE_MODE" == "1" ]]; then
  nohup "$PY" -m modules.runner > "$LOG_DIR/runner.log" 2>&1 &
  echo "  ✓ runner started (LIVE OpenSky — needs creds in .env) → logs/runner.log"
else
  DEMO_MODE=1 nohup "$PY" -m modules.runner > "$LOG_DIR/runner.log" 2>&1 &
  echo "  ✓ runner started (DEMO_MODE synthetic) → logs/runner.log"
fi

# 3. mock_katherine (advisory + briefing engine; Claude augmentation if key set)
if pgrep -f "fixtures.mock_katherine" >/dev/null 2>&1; then
  echo "  ✓ katherine already up"
else
  nohup "$PY" -m fixtures.mock_katherine > "$LOG_DIR/katherine.log" 2>&1 &
  echo "  ✓ katherine started → logs/katherine.log"
fi

# 4. dashboard
if pgrep -f "dashboard.server" >/dev/null 2>&1; then
  echo "  ✓ dashboard already up"
else
  nohup "$PY" -m dashboard.server > "$LOG_DIR/dashboard.log" 2>&1 &
  echo "  ✓ dashboard started → logs/dashboard.log"
fi

# Wait for the dashboard to answer
for _ in $(seq 1 15); do
  if curl -s -o /dev/null --max-time 2 "http://127.0.0.1:$PORT/"; then break; fi
  sleep 1
done

echo
if grep -q "LLM augmentation ON" "$LOG_DIR/katherine.log" 2>/dev/null; then
  echo "  🤖 Claude augmentation: ON (real claude-opus-4-8 calls)"
else
  echo "  ⚠ Claude augmentation: OFF (deterministic template) — check .env"
fi
if grep -q "demo=False" "$LOG_DIR/runner.log" 2>/dev/null; then
  echo "  📡 Data source: REAL OpenSky live traffic"
elif grep -q "demo=True" "$LOG_DIR/runner.log" 2>/dev/null; then
  echo "  🧪 Data source: DEMO_MODE synthetic traffic"
fi
echo
echo "  ▶ Open the dashboard:  http://127.0.0.1:$PORT"
echo "  ▶ Watch Claude calls:  tail -f logs/katherine.log | grep anthropic"
echo "  ▶ Stop everything:     bash scripts/stop_live_stack.sh"

if [[ "$TAIL_LOGS" == "1" ]]; then
  echo; echo "── tailing logs (Ctrl-C to stop tailing; services keep running) ──"
  tail -f "$LOG_DIR"/runner.log "$LOG_DIR"/katherine.log "$LOG_DIR"/dashboard.log
fi
