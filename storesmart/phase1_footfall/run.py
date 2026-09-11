#!/usr/bin/env python3
"""Phase 1: footfall & queue.

Usage:
  python -m storesmart.phase1_footfall.run --simulate
  python -m storesmart.phase1_footfall.run                        # line-crossing counter (default)
  python -m storesmart.phase1_footfall.run --counting-mode doorway  # rectangle-based doorway counter

Keys (windowed mode): q quit | v change view | + / - open counters | f flip IN direction (line mode only)
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
from storesmart.common.geometry import side_of_line
from storesmart.phase1_footfall.counter import EntryExitCounter, load_line_config, save_line_config
from storesmart.phase1_footfall.doorway import DoorwayCounter, load_doorway, save_doorway, scale_rect
from storesmart.phase1_footfall.queue import QueueAnalyzer
from storesmart.sim.people_sim import PeopleSimulator

WIN = "StoreSmart — Footfall & Queue"


def _scale(pts_norm, w, h):
    return [[x * w, y * h] for x, y in pts_norm]


def _txt(img, s, org, scale=0.55, color=(235, 235, 235), thick=1):
    cv2.putText(img, s, (org[0] + 1, org[1] + 1), cv2.FONT_HERSHEY_SIMPLEX, scale, (0, 0, 0), thick + 1, cv2.LINE_AA)
    cv2.putText(img, s, org, cv2.FONT_HERSHEY_SIMPLEX, scale, color, thick, cv2.LINE_AA)


def run_doorway_setup(get_frame) -> dict | None:
    """Click the top-left then bottom-right corner of the doorway rectangle
    on the (raw, setup-only) camera view. Labels are typed in the terminal
    afterwards. Returns a normalized {rect, in_label, out_label} dict, or
    None if cancelled with ESC."""
    pts: list[tuple[int, int]] = []
    cv2.setMouseCallback(WIN, lambda e, x, y, *_: pts.append((x, y)) if e == cv2.EVENT_LBUTTONDOWN else None)
    size = None
    while len(pts) < 2:
        frame = get_frame()
        if frame is None:
            if cv2.waitKey(30) & 0xFF == 27:
                return None
            continue
        size = (frame.shape[1], frame.shape[0])
        img = frame.copy()
        for p in pts:
            cv2.circle(img, p, 6, (0, 0, 255), -1)
        if len(pts) == 1:
            cv2.circle(img, pts[0], 6, (0, 0, 255), -1)
        _txt(img, "SETUP - click the doorway rectangle's top-left corner, then bottom-right",
             (10, 28), 0.55, (0, 255, 255), 2)
        _txt(img, "ESC = cancel   (raw view, setup only, nothing is saved)", (10, 54), 0.5)
        cv2.imshow(WIN, img)
        k = cv2.waitKey(30) & 0xFF
        if k == 27:
            return None
    cv2.setMouseCallback(WIN, lambda *a: None)

    (x1, y1), (x2, y2) = pts
    x1, x2 = sorted((x1, x2))
    y1, y2 = sorted((y1, y2))
    w, h = size
    rect_norm = {"x": x1 / w, "y": y1 / h, "w": (x2 - x1) / w, "h": (y2 - y1) / h}

    in_label = input("Label for INSIDE the rectangle [Inside]: ").strip() or "Inside"
    out_label = input("Label for OUTSIDE the rectangle [Outside]: ").strip() or "Outside"
    return {"rect": rect_norm, "in_label": in_label, "out_label": out_label}


def draw_doorway_overlay(img, counter: DoorwayCounter) -> None:
    r = counter.rect
    x1, y1 = int(r["x"]), int(r["y"])
    x2, y2 = int(r["x"] + r["w"]), int(r["y"] + r["h"])
    cv2.rectangle(img, (x1, y1), (x2, y2), (0, 220, 255), 2)
    _txt(img, counter.in_label, (x1 + 6, y1 + 22), 0.55, (0, 220, 255), 2)
    _txt(img, counter.out_label, (x1 + 6, y2 - 10), 0.5, (150, 200, 255))


def run_line_setup(get_frame) -> dict | None:
    """Click 2 points to draw the entry line, then click one more point on
    whichever side should count as OUTSIDE (e.g. away from the camera,
    towards the street). Labels are typed in the terminal afterwards.
    Returns a normalized {line, in_from, in_label, out_label} dict, or None
    if cancelled with ESC."""
    pts: list[tuple[int, int]] = []
    cv2.setMouseCallback(WIN, lambda e, x, y, *_: pts.append((x, y)) if e == cv2.EVENT_LBUTTONDOWN else None)
    size = None
    while len(pts) < 3:
        frame = get_frame()
        if frame is None:
            if cv2.waitKey(30) & 0xFF == 27:
                return None
            continue
        size = (frame.shape[1], frame.shape[0])
        img = frame.copy()
        for p in pts[:2]:
            cv2.circle(img, p, 6, (0, 0, 255), -1)
        if len(pts) == 2:
            cv2.line(img, pts[0], pts[1], (0, 220, 255), 2)
        if len(pts) >= 3:
            break
        stage = "click the line's 2 endpoints" if len(pts) < 2 else \
            "now click a point on the OUTSIDE (e.g. away from camera / towards the street)"
        _txt(img, f"SETUP - {stage}", (10, 28), 0.55, (0, 255, 255), 2)
        _txt(img, "ESC = cancel   (raw view, setup only, nothing is saved)", (10, 54), 0.5)
        cv2.imshow(WIN, img)
        k = cv2.waitKey(30) & 0xFF
        if k == 27:
            return None
    cv2.setMouseCallback(WIN, lambda *a: None)

    line_px = pts[:2]
    outside_point = pts[2]
    in_from = side_of_line(line_px, outside_point, margin=0) or 1
    w, h = size
    line_norm = [[x / w, y / h] for x, y in line_px]

    in_label = input("Label for INSIDE the store [Inside]: ").strip() or "Inside"
    out_label = input("Label for OUTSIDE the store [Outside]: ").strip() or "Outside"
    return {"line": line_norm, "in_from": in_from, "in_label": in_label, "out_label": out_label}


def draw_line_overlay(img, counter: EntryExitCounter) -> None:
    ax, ay = (int(v) for v in counter.line[0])
    bx, by = (int(v) for v in counter.line[1])
    cv2.line(img, (ax, ay), (bx, by), (0, 220, 255), 3)
    mx, my = (ax + bx) // 2, (ay + by) // 2
    nx, ny = (by - ay), -(bx - ax)
    norm = (nx ** 2 + ny ** 2) ** 0.5 + 1e-6
    offset = 40
    p1 = (int(mx + nx / norm * offset), int(my + ny / norm * offset))
    p2 = (int(mx - nx / norm * offset), int(my - ny / norm * offset))
    side1 = side_of_line(counter.line, p1, margin=0)
    label1, label2 = (counter.out_label, counter.in_label) if side1 == counter.in_from \
        else (counter.in_label, counter.out_label)
    _txt(img, label1, p1, 0.55, (150, 200, 255), 2)
    _txt(img, label2, p2, 0.55, (0, 220, 255), 2)


def draw_panel(h: int, counter: EntryExitCounter | DoorwayCounter, qa: QueueAnalyzer, fps: float, bus: EventBus) -> np.ndarray:
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
    ap.add_argument("--counting-mode", choices=["line", "doorway"], default="line",
                     help="line: click-crossing counter (default). doorway: click a rectangle; "
                          "entering it counts as IN, leaving it counts as OUT.")
    ap.add_argument("--doorway-config", default=None, help="override path to the doorway rectangle config")
    ap.add_argument("--line-config", default=None, help="override path to the entry line config")
    ap.add_argument("--initial-inside", type=int, default=None,
                     help="how many people are already inside the store at startup "
                          "(skips the interactive prompt; useful for --headless/--simulate runs)")
    args = ap.parse_args()

    settings = load_settings().get("footfall", {})
    bus = EventBus()
    cameras = load_cameras()
    simulate = args.simulate or cameras.get("entrance", {}).get("url", "simulate") == "simulate"
    doorway_path = args.doorway_config or "config/doorway.json"
    line_path = args.line_config or "config/line.json"

    initial_inside = args.initial_inside
    if initial_inside is None:
        if args.headless or simulate:
            initial_inside = 0
        else:
            raw = input("How many people are already inside the store right now? [0]: ").strip()
            try:
                initial_inside = int(raw) if raw else 0
            except ValueError:
                print("Not a number, assuming 0.")
                initial_inside = 0

    if not args.headless:
        cv2.namedWindow(WIN, cv2.WINDOW_NORMAL)

    if simulate:
        sim = PeopleSimulator()
        geom = sim.geometry()
        w, h = sim.w, sim.h
        doorway_cfg = load_doorway() if args.counting_mode == "doorway" else None
        line_cfg = None  # simulator's own geometry() already gives a line/in_from
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
        geom = {"queue": [[0.42, 0.38], [0.74, 0.38], [0.74, 0.62], [0.42, 0.62]],
                "service": [[0.77, 0.28], [0.93, 0.28], [0.93, 0.72], [0.77, 0.72]]}
        from storesmart.common.detector import PersonTracker
        tracker = PersonTracker(settings.get("model", "yolov8n.pt"))

        import os

        doorway_cfg = None
        if args.counting_mode == "doorway":
            if os.path.exists(doorway_path):
                doorway_cfg = load_doorway(doorway_path)
            elif args.headless:
                raise RuntimeError(f"no doorway config at {doorway_path} — run once with a window to draw it")
            else:
                doorway_cfg = run_doorway_setup(entrance_src.read)
                if doorway_cfg is None:
                    return
                save_doorway(doorway_cfg, doorway_path)

        line_cfg = None
        if args.counting_mode == "line":
            if os.path.exists(line_path):
                line_cfg = load_line_config(line_path)
            elif args.headless:
                raise RuntimeError(f"no line config at {line_path} — run once with a window to draw it")
            else:
                line_cfg = run_line_setup(entrance_src.read)
                if line_cfg is None:
                    return
                save_line_config(line_cfg, line_path)

    max_group_size = settings.get("max_group_size", 4)
    if args.counting_mode == "doorway":
        counter = DoorwayCounter(
            rect=scale_rect(doorway_cfg["rect"], w, h),
            in_label=doorway_cfg.get("in_label", "Inside"), out_label=doorway_cfg.get("out_label", "Outside"),
            lost_after=settings.get("lost_after_s", 1.5),
            initial_inside=initial_inside, max_group_size=max_group_size,
        )
    elif line_cfg is not None:
        counter = EntryExitCounter(
            line=_scale(line_cfg["line"], w, h), in_from=line_cfg["in_from"],
            buffer_px=settings.get("buffer_px", 40), lost_after=settings.get("lost_after_s", 1.5),
            in_label=line_cfg.get("in_label", "Inside"), out_label=line_cfg.get("out_label", "Outside"),
            initial_inside=initial_inside, max_group_size=max_group_size,
        )
    else:
        counter = EntryExitCounter(
            line=_scale(geom["line"], w, h), in_from=geom["in_from"],
            buffer_px=settings.get("buffer_px", 40), lost_after=settings.get("lost_after_s", 1.5),
            initial_inside=initial_inside, max_group_size=max_group_size,
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
            if isinstance(counter, DoorwayCounter):
                draw_doorway_overlay(img, counter)
            elif isinstance(counter, EntryExitCounter):
                draw_line_overlay(img, counter)
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
            elif k == ord("f") and isinstance(counter, EntryExitCounter):
                counter.flip_direction()
        elif simulate:
            # Windowed mode is paced by cv2.waitKey; headless simulate has no
            # such pause, so without this the loop spins the CPU flat out and
            # runs simulated time ~100x too fast.
            time.sleep(max(0.0, dt_sim - (time.time() - tnow)))

        if args.duration and now >= args.duration:
            break

    print(f"IN {counter.entries} OUT {counter.exits} served {qa.served} | images written: 0")
    if not simulate:
        entrance_src.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
