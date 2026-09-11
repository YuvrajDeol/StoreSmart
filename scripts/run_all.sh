#!/usr/bin/env bash
# Starts StoreSmart modules as background processes with readable logs, and
# stops them cleanly on Ctrl+C. Pass --simulate to run with no cameras/phones.
set -euo pipefail
cd "$(dirname "$0")/.."

MODE="${1:-}"
SIM_FLAG=""
if [[ "$MODE" == "--simulate" ]]; then
  SIM_FLAG="--simulate"
fi

PY=".venv/bin/python"
if [[ ! -x "$PY" ]]; then
  echo "No .venv found — run 'make setup' first." >&2
  exit 1
fi

mkdir -p data logs
PIDS=()

start() {
  local name="$1"; shift
  echo "starting $name: $*"
  "$@" > "logs/${name}.log" 2>&1 &
  PIDS+=("$!")
}

cleanup() {
  echo ""
  echo "stopping StoreSmart modules..."
  for pid in "${PIDS[@]:-}"; do
    kill "$pid" 2>/dev/null || true
  done
  wait 2>/dev/null || true
  echo "stopped."
}
trap cleanup EXIT INT TERM

start footfall "$PY" -m storesmart.phase1_footfall.run $SIM_FLAG --headless
[[ -f storesmart/phase3_shelf/run.py ]] && start shelf "$PY" -m storesmart.phase3_shelf.run $SIM_FLAG --headless
[[ -f storesmart/phase4_dwell/run.py ]] && start dwell "$PY" -m storesmart.phase4_dwell.run $SIM_FLAG --headless

echo ""
echo "Modules running in background. Logs in ./logs/*.log"
echo "Start the dashboard in another terminal with: make dashboard"
echo "Press Ctrl+C here to stop everything."

wait
