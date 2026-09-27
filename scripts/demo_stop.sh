#!/usr/bin/env bash
# Stop everything started by demo_start.sh.
set -uo pipefail
cd "$(dirname "$0")/.."
pkill -f "storesmart.phase" 2>/dev/null
pkill -f "streamlit run storesmart" 2>/dev/null
rm -f data/processes.json
sleep 1
echo "stopped. (data/storesmart.db kept — demo_start.sh clears it next run)"
