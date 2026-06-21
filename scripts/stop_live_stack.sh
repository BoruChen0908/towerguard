#!/usr/bin/env bash
# Stop the TowerGuard live-validation stack (3 services). Leaves Redis running
# (it's cheap and shared); pass --redis to stop that too.
#
#   bash scripts/stop_live_stack.sh
#   bash scripts/stop_live_stack.sh --redis
set -uo pipefail

echo "→ stopping TowerGuard live stack"
for name in "dashboard.server" "fixtures.mock_katherine" "modules.runner"; do
  if pkill -f "$name" 2>/dev/null; then
    echo "  ✓ stopped $name"
  else
    echo "  · $name not running"
  fi
done

if [[ "${1:-}" == "--redis" ]]; then
  redis-cli -p 6379 shutdown nosave 2>/dev/null && echo "  ✓ stopped redis" || echo "  · redis not running"
fi
echo "done."
