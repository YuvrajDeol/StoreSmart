#!/usr/bin/env bash
# Quick standalone privacy check: runs just the source-tree scan test.
set -euo pipefail
cd "$(dirname "$0")/.."
.venv/bin/python -m pytest tests/test_privacy_scan.py tests/test_event_gate.py -v
