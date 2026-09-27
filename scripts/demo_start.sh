#!/usr/bin/env bash
# One command to get into a demo-ready state.
#
# Resets the data, seeds the stock database, starts every phase on synthetic
# data, starts the dashboard, then waits until there is actually something on
# screen worth showing — so the first thing a judge sees is a store with
# numbers moving, not an empty dashboard warming up.
#
#   bash scripts/demo_start.sh          # everything simulated (safe default)
#   bash scripts/demo_start.sh --live   # entrance camera live, rest simulated
#
# Stop everything afterwards with: bash scripts/demo_stop.sh
set -uo pipefail
cd "$(dirname "$0")/.."

PY=".venv/bin/python"
PORT="${PORT:-8520}"
LIVE_ENTRANCE=false
[[ "${1:-}" == "--live" ]] && LIVE_ENTRANCE=true

if [[ ! -x "$PY" ]]; then
  echo "No .venv — run 'make setup' first." >&2
  exit 1
fi

echo "› clearing previous run"
pkill -f "storesmart.phase" 2>/dev/null
pkill -f "streamlit run storesmart" 2>/dev/null
sleep 1
rm -f data/storesmart.db data/storesmart.db-wal data/storesmart.db-shm data/processes.json
mkdir -p logs data

echo "› seeding stock database"
$PY -m storesmart.stock.seed >/dev/null 2>&1 || { echo "seed failed — see above" >&2; exit 1; }

start() {  # start <name> <module> [args...]
  local name="$1"; shift
  nohup $PY -m "$@" > "logs/${name}.log" 2>&1 &
  echo "  started ${name}"
}

echo "› starting modules"
if $LIVE_ENTRANCE; then
  start footfall storesmart.phase1_footfall.run --initial-inside 0
  echo "    (entrance is LIVE — its window will open; draw the line if asked)"
else
  start footfall storesmart.phase1_footfall.run --simulate --headless
fi
start floor  storesmart.phase2_map.live_map --simulate --headless
start shelf  storesmart.phase3_shelf.run --simulate --headless --interval 2
start dwell  storesmart.phase4_dwell.run --simulate --headless

echo "› starting dashboard on :${PORT}"
nohup $PY -m streamlit run storesmart/dashboard/app.py \
  --server.headless true --server.port "$PORT" > logs/dashboard.log 2>&1 &

# Wait for the dashboard to answer rather than guessing at a sleep duration.
for _ in $(seq 1 40); do
  curl -s -o /dev/null -m 2 "http://localhost:${PORT}" && break
  sleep 0.5
done

# The shelf and dwell modules only emit when something actually changes — a
# slot draining to "low", a shopper leaving a zone. That takes a minute of
# simulated time, so wait for it here rather than opening the hub on a screen
# full of "no data yet".
echo "› warming up — waiting for every phase to report (up to 100s)"
for i in $(seq 1 50); do
  ready=$($PY - <<'EOF' 2>/dev/null
from storesmart.common.bus import EventBus
bus = EventBus()
have = {t: len(bus.recent(limit=1, event_type=t)) for t in ("summary", "position", "shelf_status", "dwell")}
print(sum(1 for v in have.values() if v) , "".join(k[0] for k, v in have.items() if v))
EOF
)
  set -- $ready
  printf "\r  phases reporting: %s/4 %s   " "${1:-0}" "${2:-}"
  [[ "${1:-0}" -ge 4 ]] && break
  sleep 2
done
echo

echo
echo "────────────────────────────────────────────────"
echo " READY   →  http://localhost:${PORT}"
echo "────────────────────────────────────────────────"
$PY - <<'EOF'
from storesmart.common.bus import EventBus
from storesmart.dashboard import data
bus = EventBus()
k = data.kpi_snapshot(bus)
print(f"  inside={k['inside']}  in={k['entered']}  out={k['exited']}  queue={k['queue_length']}")
for m in data.module_statuses(bus):
    print(f"  {m['phase']:<8} {m['name']:<18} {m['label']}")
print(f"  events stored: {bus.counts()['accepted']}")
EOF
echo
echo "Open the hub, then follow docs/demo-2min.md"
