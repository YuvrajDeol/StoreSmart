#!/usr/bin/env python3
"""Phase 4: dwell zones & layout insights.

Reads position events (emitted by Phase 2's live_map) from the shared event
bus, maps them to shelf zones from the store map, and emits dwell events.
Falls back to no zones (nothing emitted) if store_map.json has no shelves —
the dashboard's Dwell & Insights page then reads directly from the camera
view instead, per the design fallback.

Usage:
  python -m storesmart.phase4_dwell.run --simulate
"""
from __future__ import annotations

import argparse
import time

from storesmart.common.bus import EventBus
from storesmart.common.config import load_settings
from storesmart.phase2_map.map_model import load_map
from storesmart.phase4_dwell.dwell import DwellTracker, build_zones
from storesmart.sim.floor_sim import FloorSimulator


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--simulate", action="store_true")
    ap.add_argument("--headless", action="store_true")
    ap.add_argument("--duration", type=float, default=0)
    ap.add_argument("--rate-hz", type=float, default=2.0)
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

    if not args.simulate:
        raise SystemExit(
            "Real floor-camera dwell tracking reads 'position' events from the bus "
            "(emitted by phase2_map/live_map.py in real-camera mode). Run that first, "
            "then extend this script to poll bus.since() instead of the simulator."
        )

    sim = FloorSimulator(store_map.length_ft, store_map.breadth_ft)
    dt = 1.0 / args.rate_hz
    t0 = time.time()
    print(f"Phase 4 dwell tracker running (simulate) with zones: {list(zones)}")
    while True:
        now = time.time() - t0
        for track_id, x_ft, y_ft in sim.step(dt):
            tracker.update(track_id, (x_ft, y_ft), now, bus)
        if args.duration and now >= args.duration:
            break
        time.sleep(dt)
    print("Phase 4 dwell tracker stopped.")


if __name__ == "__main__":
    main()
