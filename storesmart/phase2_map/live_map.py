#!/usr/bin/env python3
"""Phase 2: floor camera -> live anonymous dots on the store map.

In real-camera mode, foot points are detected the same way as Phase 1
(YOLO+ByteTrack) and mapped to feet via the stored homography. In
--simulate mode the floor population is driven by Phase 1's own entry/exit
events on the shared bus, so the dots on the Store Map and the "Inside" count
on the Live page describe the same shoppers instead of two unrelated fake
populations. Phase 1 and Phase 2 are separate OS processes, so the bus
(data/storesmart.db) is the only thing linking them.

Usage:
  python -m storesmart.phase2_map.live_map --simulate
"""
from __future__ import annotations

import argparse
import datetime
import time

from storesmart.common.bus import EventBus
from storesmart.common.config import load_cameras
from storesmart.phase2_map.map_model import StoreMap, load_map
from storesmart.sim.floor_sim import DoorFloorSimulator
from storesmart.sim.navigation import find_door_point

# Only reconcile against a `summary` event this fresh. Phase 1 emits one every
# 5s, so anything older than this means Phase 1 is not currently running and
# its last known headcount should not be used to conjure shoppers.
SUMMARY_MAX_AGE_S = 15.0
# How long to wait before pointing out that nothing is arriving.
QUIET_HINT_AFTER_S = 20.0


class _EventTail:
    """Incremental reader for one event type, using the ISO-8601 `t` field as a
    high-water mark so no entry/exit is missed or counted twice.

    INTERIM: the Phase 4 branch adds EventBus.since_id()/latest_id() for exactly
    this job, and those are id-based, so they cannot be confused by two events
    sharing a timestamp. Swap this class for them once that branch merges —
    nothing outside this file depends on it.

    `t` comes from EventBus._now_iso(): fixed UTC offset, millisecond
    precision, one writer per event type. That makes lexicographic comparison
    chronological. The one case it cannot separate is two events emitted by the
    same module within the same millisecond.
    """

    def __init__(self, bus: EventBus, event_type: str, limit: int = 200):
        self._bus = bus
        self._type = event_type
        self._limit = limit
        # Start from whatever is already on the bus: events from earlier runs
        # predate this process and must not replay as a burst of arrivals.
        seen = bus.recent(limit=1, event_type=event_type)
        self._high_water = seen[0]["t"] if seen else ""

    def new_events(self) -> list[dict]:
        rows = self._bus.recent(limit=self._limit, event_type=self._type)  # newest first
        fresh = [r for r in rows if r.get("t", "") > self._high_water]
        if fresh:
            self._high_water = max(r["t"] for r in fresh)
        return list(reversed(fresh))  # hand back oldest-first


def _event_age_s(payload: dict) -> float:
    """Seconds since an event's ISO-8601 `t`, or +inf if it cannot be read."""
    try:
        stamped = datetime.datetime.fromisoformat(payload["t"])
    except (KeyError, TypeError, ValueError):
        return float("inf")
    if stamped.tzinfo is None:
        stamped = stamped.replace(tzinfo=datetime.timezone.utc)
    return (datetime.datetime.now(datetime.timezone.utc) - stamped).total_seconds()


def door_point(store_map: StoreMap) -> tuple[tuple[float, float], bool]:
    """Centre of the first door rectangle on the map, in feet — see
    `navigation.find_door_point`.

    Used here only for the start-up message. The simulator re-derives the door
    itself whenever the saved map changes, so a door moved mid-run takes effect
    without this being called again.
    """
    return find_door_point(store_map.rectangles, store_map.breadth_ft)


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

    spawn_at, found_door = door_point(store_map)
    if not found_door:
        print(
            "WARNING: no door rectangle in the store map — shoppers will appear at "
            f"{spawn_at[0]:.1f}, {spawn_at[1]:.1f} ft. Draw a door on the Store Map "
            "page to place the entrance properly."
        )

    sim = DoorFloorSimulator(store_map.length_ft, store_map.breadth_ft, spawn_at)
    entry_tail = _EventTail(bus, "entry")
    exit_tail = _EventTail(bus, "exit")

    dt = 1.0 / args.rate_hz
    t0 = time.time()
    saw_any_activity = False
    warned_quiet = False
    print(
        f"Phase 2 live map running (simulate), shop {store_map.length_ft}x{store_map.breadth_ft} ft, "
        f"entrance at {spawn_at[0]:.1f}, {spawn_at[1]:.1f} ft. "
        "Population follows Phase 1's entry/exit events."
    )
    while True:
        now = time.time() - t0

        # Edges: every entry puts someone through the door, every exit starts
        # someone walking back to it.
        for _ in entry_tail.new_events():
            sim.spawn()
            saw_any_activity = True
        for _ in exit_tail.new_events():
            sim.begin_exit()
            saw_any_activity = True

        # Level: Phase 1's `summary.inside` is the authority on how many people
        # are in the shop. Edges alone would drift permanently after a single
        # missed event, so reconcile against the count whenever a fresh summary
        # is available. Tracks already walking out are excluded, since Phase 1
        # has already counted them as gone.
        latest_summary = bus.recent(limit=1, event_type="summary")
        if latest_summary and _event_age_s(latest_summary[0]) <= SUMMARY_MAX_AGE_S:
            saw_any_activity = True
            drift = int(latest_summary[0].get("inside", 0)) - sim.shopping_count()
            for _ in range(max(drift, 0)):
                sim.spawn()
            for _ in range(max(-drift, 0)):
                sim.begin_exit()

        positions, _removed = sim.step(dt)
        for track_id, x_ft, y_ft in positions:
            bus.emit({"cam": "floor", "type": "position", "x_ft": x_ft, "y_ft": y_ft, "track": track_id})

        if not saw_any_activity and not warned_quiet and now >= QUIET_HINT_AFTER_S:
            warned_quiet = True
            print(
                "No entry/exit or summary events seen yet — Phase 2's population now "
                "follows Phase 1. Start it with: "
                "python -m storesmart.phase1_footfall.run --simulate --headless"
            )

        if args.duration and now >= args.duration:
            break
        time.sleep(dt)
    print("Phase 2 live map stopped.")


if __name__ == "__main__":
    main()
