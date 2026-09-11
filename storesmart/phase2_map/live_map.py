#!/usr/bin/env python3
"""Phase 2: floor camera -> live anonymous dots on the store map.

In real-camera mode, foot points are detected the same way as Phase 1
(YOLO+ByteTrack) and mapped to feet via the stored homography. In
--simulate mode, a synthetic floor simulator plays the role of the camera +
homography so the live map can be demoed with no phone.

Usage:
  python -m storesmart.phase2_map.live_map --simulate
"""
from __future__ import annotations

import argparse
import time

from storesmart.common.bus import EventBus
from storesmart.common.config import load_cameras
from storesmart.phase2_map.map_model import load_map
from storesmart.sim.floor_sim import FloorSimulator


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--simulate", action="store_true")
    ap.add_argument("--headless", action="store_true")
    ap.add_argument("--duration", type=float, default=0)
    ap.add_argument("--rate-hz", type=float, default=2.0, help="position events per second per person")
    args = ap.parse_args()

    bus = EventBus()
    store_map = load_map()
    cameras = load_cameras()
    simulate = args.simulate or cameras.get("floor", {}).get("url", "simulate") == "simulate"

    if not simulate:
        raise SystemExit(
            "Real floor-camera mode needs a calibrated homography and a running "
            "YOLO tracker — run Phase 2's calibration in the dashboard first, "
            "then extend this script the way phase1_footfall/run.py does."
        )

    sim = FloorSimulator(store_map.length_ft, store_map.breadth_ft)
    dt = 1.0 / args.rate_hz
    t0 = time.time()
    print(f"Phase 2 live map running (simulate), shop {store_map.length_ft}x{store_map.breadth_ft} ft")
    while True:
        now = time.time() - t0
        for track_id, x_ft, y_ft in sim.step(dt):
            bus.emit({"cam": "floor", "type": "position", "x_ft": x_ft, "y_ft": y_ft, "track": track_id})
        if args.duration and now >= args.duration:
            break
        time.sleep(dt)
    print("Phase 2 live map stopped.")


if __name__ == "__main__":
    main()
