#!/usr/bin/env python3
"""Phase 4: dwell zones & layout insights.

Reads 'position' events (emitted by Phase 2's live_map, whether it's running
with --simulate or a real, calibrated floor camera) from the shared event
bus, maps them to shelf zones from the store map, and emits dwell events.
Falls back to no zones (nothing emitted) if store_map.json has no shelves —
the dashboard's Dwell & Insights page then tells you to draw shelves on the
Store Map page first.

This process never touches a camera, a tracker, or a simulator directly —
only the bus. That means it works unchanged in both simulate and real-camera
mode, and stays in sync with whatever Phase 2 is actually emitting (no more
running a second, disconnected simulation of its own).

Usage:
  python -m storesmart.phase4_dwell.run             # run alongside Phase 2's live_map
  python -m storesmart.phase4_dwell.run --simulate   # same; only changes the startup message
"""
from __future__ import annotations

import argparse
import time

from storesmart.common.bus import EventBus
from storesmart.common.config import load_settings
from storesmart.phase2_map.map_model import load_map
from storesmart.phase4_dwell.dwell import DwellTracker, build_zones

DEFAULT_POLL_INTERVAL_S = 0.5
# How long to wait with no new position event for a track before treating it
# as gone and closing out its current zone's dwell timer.
STALE_TRACK_S = 3.0


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--simulate", action="store_true",
                     help="accepted for symmetry with the other phases / run_all.sh — Phase 4 "
                          "always reads the bus, so this only affects the startup message")
    ap.add_argument("--headless", action="store_true")
    ap.add_argument("--duration", type=float, default=0)
    ap.add_argument("--poll-interval", type=float, default=DEFAULT_POLL_INTERVAL_S,
                     help="seconds between bus polls for new position events")
    args = ap.parse_args()

    settings = load_settings().get("dwell", {})
    bus = EventBus()
    store_map = load_map()
    zones = build_zones(store_map, expand_ft=settings.get("zone_expand_ft", 1.5))
    tracker = DwellTracker(zones, enter_delay_s=settings.get("enter_delay_s", 2),
                            exit_delay_s=settings.get("exit_delay_s", 2))

    if not zones:
        print("No shelf zones in the store map — draw shelves on the Store Map page first.")
        return

    print(f"Phase 4 dwell tracker running{' (simulate)' if args.simulate else ''} with zones: {list(zones)}")
    print("Reading 'position' events from the shared bus — make sure Phase 2's live_map is "
          f"running too ({'python -m storesmart.phase2_map.live_map --simulate' if args.simulate else 'real-camera mode, after calibration'}).")

    t0 = time.time()
    last_ts = t0
    last_seen: dict[int, float] = {}

    while True:
        poll_time = time.time()
        for ev in bus.since(last_ts, event_type="position"):
            track_id = ev["track"]
            last_seen[track_id] = poll_time
            tracker.update(track_id, (ev["x_ft"], ev["y_ft"]), poll_time, bus)
        last_ts = poll_time

        stale = [tid for tid, seen in last_seen.items() if poll_time - seen > STALE_TRACK_S]
        for tid in stale:
            tracker.remove_track(tid, last_seen.pop(tid), bus)

        if args.duration and poll_time - t0 >= args.duration:
            break
        time.sleep(args.poll_interval)

    print("Phase 4 dwell tracker stopped.")


if __name__ == "__main__":
    main()
