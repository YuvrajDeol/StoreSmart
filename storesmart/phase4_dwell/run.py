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
import datetime
import time

from storesmart.common.bus import EventBus
from storesmart.common.config import load_settings
from storesmart.phase2_map.map_model import load_map
from storesmart.phase4_dwell.dwell import DwellTracker, build_zones

DEFAULT_POLL_INTERVAL_S = 0.5
# How long to wait with no new position event for a track before treating it
# as gone and closing out its current zone's dwell timer.
STALE_TRACK_S = 3.0


def _event_time(ev: dict, fallback: float) -> float:
    """Epoch seconds for an event, taken from the producer's own timestamp.

    Dwell durations must be measured in the timebase the positions were
    observed in, not in whenever this process happened to poll — otherwise
    every event in a batch collapses to one instant and our scheduling jitter
    is charged to the shopper.
    """
    try:
        return datetime.datetime.fromisoformat(ev["t"]).timestamp()
    except (KeyError, TypeError, ValueError):
        return fallback


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
    # Row ids are monotonic and become visible with the commit, so this cursor
    # cannot skip or re-deliver an event the way a `ts` cursor does. Seeding it
    # at the current tip means whatever is already logged stays backlog instead
    # of being replayed as one long fake dwell.
    last_id = bus.latest_id()
    # track -> (wall clock of the poll that saw it, producer's event time).
    # The wall clock is only for deciding a track has gone quiet; every dwell
    # duration is computed from the event time.
    last_seen: dict[int, tuple[float, float]] = {}

    try:
        while True:
            poll_time = time.time()
            for row_id, ev in bus.since_id(last_id, event_type="position"):
                last_id = row_id
                track_id = ev["track"]
                ev_time = _event_time(ev, poll_time)
                last_seen[track_id] = (poll_time, ev_time)
                tracker.update(track_id, (ev["x_ft"], ev["y_ft"]), ev_time, bus)

            stale = [tid for tid, (wall, _) in last_seen.items()
                     if poll_time - wall > STALE_TRACK_S]
            for tid in stale:
                _, ev_time = last_seen.pop(tid)
                tracker.remove_track(tid, ev_time, bus)

            if args.duration and poll_time - t0 >= args.duration:
                break
            time.sleep(args.poll_interval)
    except KeyboardInterrupt:
        print()
    finally:
        # Close out everyone still standing in a zone, at the time we last
        # actually saw them, so a run never silently discards dwell in progress.
        for tid, (_, ev_time) in last_seen.items():
            tracker.remove_track(tid, ev_time, bus)
        print("Phase 4 dwell tracker stopped.")


if __name__ == "__main__":
    main()
