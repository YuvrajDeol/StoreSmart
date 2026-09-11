#!/usr/bin/env python3
"""Phase 1: footfall & queue.

Usage:
  python -m storesmart.phase1_footfall.run --simulate
  python -m storesmart.phase1_footfall.run --cam entrance --counter-cam counter

Keys (windowed mode): q quit | v change view | + / - open counters | f flip IN direction
"""
from __future__ import annotations

import argparse
import time

import cv2
import numpy as np

from storesmart.common.bus import EventBus
from storesmart.common.config import load_cameras, load_settings
from storesmart.common.privacy import VIEWS, render_blurred, render_raw, render_zero_frame
from storesmart.common.video import open_source
from storesmart.phase1_footfall.counter import EntryExitCounter
from storesmart.phase1_footfall.queue import QueueAnalyzer
from storesmart.sim.people_sim import PeopleSimulator

WIN = "StoreSmart — Footfall & Queue"


def _scale(pts_norm, w, h):
    return [[x * w, y * h] for x, y in pts_norm]


def draw_panel(h: int, counter: EntryExitCounter, qa: QueueAnalyzer, fps: float, bus: EventBus) -> np.ndarray:
    panel = np.full((h, 380, 3), (30, 24, 20), np.uint8)
    y = 34

    def line(s, scale=0.6, color=(235, 235, 235), gap=28, thick=1):
        nonlocal y
        cv2.putText(panel, s, (17, y + 1), cv2.FONT_HERSHEY_SIMPLEX, scale, (0, 0, 0), thick + 1, cv2.LINE_AA)
        cv2.putText(panel, s, (16, y), cv2.FONT_HERSHEY_SIMPLEX, scale, color, thick, cv2.LINE_AA)
        y += gap

    line("STORESMART  live demo", 0.75, (180, 230, 210), 36, 2)
    line("FOOTFALL", 0.55, (150, 170, 190), 26)
    line(f"IN {counter.entries}    OUT {counter.exits}    Inside {counter.inside}", 0.62)
    line(f"Browsing (not yet queuing): {qa.browsing}", 0.52, gap=34)
    line("QUEUE", 0.55, (150, 170, 190), 26)
    line(f"In queue: {qa.length}   At counter: {qa.serving_now}", 0.6)
    line(f"Open counters: {qa.counters}   Served: {qa.served}", 0.6)
    line(f"Avg service time: {qa.mean_service():.1f} s", 0.55)
    line(f"Est. wait now: {qa.wait_now:.0f} s", 0.62)
    line(f"Forecast wait: {qa.forecast_wait_s:.0f} s", 0.62, gap=34)
    if qa.alert:
        cv2.rectangle(panel, (10, y - 22), (370, y + 30), (0, 0, 200), -1)
        line("OPEN ANOTHER COUNTER", 0.65, (255, 255, 255), 34, 2)
    else:
        line("Status: queue under control", 0.55, (120, 220, 120), 40)
    line("PRIVACY", 0.55, (150, 170, 190), 26)
    line("Images written to disk: 0", 0.55, (180, 230, 210), 24)
    counts = bus.counts()
    line(f"Events: {counts['accepted']} accepted, {counts['rejected']} rejected", 0.5, (180, 230, 210), 24)
    line(f"{fps:4.1f} FPS", 0.5, (150, 150, 150), 20)
    return panel


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--simulate", action="store_true")
    ap.add_argument("--headless", action="store_true", help="no window (for automated runs/tests)")
    ap.add_argument("--duration", type=float, default=0, help="stop after N seconds (0 = run until q)")
    ap.add_argument("--counters", type=int, default=1)
    args = ap.parse_args()

    settings = load_settings().get("footfall", {})
    bus = EventBus()
    cameras = load_cameras()
    simulate = args.simulate or cameras.get("entrance", {}).get("url", "simulate") == "simulate"

    if not args.headless:
        cv2.namedWindow(WIN, cv2.WINDOW_NORMAL)

    if simulate:
        sim = PeopleSimulator()
        geom = sim.geometry()
        w, h = sim.w, sim.h
    else:
        entrance_src = open_source(cameras.get("entrance", {}))
        frame = None
        t_wait = time.time()
        while frame is None and time.time() - t_wait < 15:
            frame = entrance_src.read()
            time.sleep(0.05)
        if frame is None:
            raise RuntimeError(f"cannot reach camera at {cameras['entrance']['url']} — check the hotspot")
        h, w = frame.shape[:2]
        geom = {"line": [[0.25, 0.10], [0.25, 0.92]],
                "queue": [[0.42, 0.38], [0.74, 0.38], [0.74, 0.62], [0.42, 0.62]],
                "service": [[0.77, 0.28], [0.93, 0.28], [0.93, 0.72], [0.77, 0.72]],
                "in_from": 1}
        from storesmart.common.detector import PersonTracker
        tracker = PersonTracker(settings.get("model", "yolov8n.pt"))

    counter = EntryExitCounter(
        line=_scale(geom["line"], w, h), in_from=geom["in_from"],
        margin=settings.get("margin_px", 12), lost_after=settings.get("lost_after_s", 1.5),
    )
    qa = QueueAnalyzer(
        queue_poly=_scale(geom["queue"], w, h) if geom.get("queue") else None,
        service_poly=_scale(geom["service"], w, h) if geom.get("service") else None,
        counters=args.counters, threshold_s=settings.get("threshold_wait_s", 12),
        horizon_s=settings.get("horizon_s", 10), join_prob=settings.get("join_prob", 1.0),
        hold_s=settings.get("hold_s", 3), window_s=settings.get("window_s", 30),
        default_service_s=settings.get("default_service_s", 6), min_service_s=settings.get("min_service_s", 1.0),
    )

    views = list(VIEWS)
    view_idx = 0
    t0 = time.time()
    dt_sim = 1 / 15
    fps, last = 0.0, time.time()
    last_summary = -1e9

    while True:
        if simulate:
            sim.servers = qa.counters
            frame, tracks = sim.step(dt_sim)
            now = sim.t
        else:
            frame = entrance_src.read()
            if frame is None:
                if not args.headless and (cv2.waitKey(10) & 0xFF) == ord("q"):
                    break
                continue
            now = time.time() - t0
            tracks = tracker.update(frame)

        counter.update(tracks, now, bus)
        qa.update(tracks, now, counter.inside, bus)

        if now - last_summary >= 5:
            last_summary = now
            bus.emit({"type": "summary", "in": counter.entries, "out": counter.exits, "inside": counter.inside})

        tnow = time.time()
        fps = 0.9 * fps + 0.1 / max(tnow - last, 1e-3)
        last = tnow

        if not args.headless:
            view = views[view_idx]
            boxes = [b for _, b in tracks]
            if view == "blurred":
                img = render_blurred(frame, boxes)
            elif view == "zero-frame":
                img = render_zero_frame(frame, [((x1 + x2) // 2, y2) for _, (x1, y1, x2, y2) in tracks])
            else:
                img = render_raw(frame)
                cv2.putText(img, "RAW VIEW - setup only, nothing is saved", (10, 24),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2, cv2.LINE_AA)
            panel = draw_panel(img.shape[0], counter, qa, fps, bus)
            cv2.imshow(WIN, np.hstack([img, panel]))
            wait_ms = max(1, int((dt_sim - (time.time() - tnow)) * 1000)) if simulate else 1
            k = cv2.waitKey(wait_ms) & 0xFF
            if k == ord("q"):
                break
            elif k == ord("v"):
                view_idx = (view_idx + 1) % len(views)
            elif k in (ord("+"), ord("=")):
                qa.set_counters(qa.counters + 1)
            elif k in (ord("-"), ord("_")):
                qa.set_counters(qa.counters - 1)
            elif k == ord("f"):
                counter.flip_direction()

        if args.duration and now >= args.duration:
            break

    print(f"IN {counter.entries} OUT {counter.exits} served {qa.served} | images written: 0")
    if not simulate:
        entrance_src.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
