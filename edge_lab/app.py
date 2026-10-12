"""Edge AI lab demo: on-device people counting + shelf gap detection.

Frames live only in memory; nothing is ever written to disk.
Inference metrics are always real: they time an actual YOLOv8 forward pass
(plus ByteTrack). If no model ran, the HUD says so instead of showing 0 ms.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import cv2
import numpy as np

from edge_lab.metrics import PerfMeter
from edge_lab.shelf_watch import ObjectDetector, ShelfWatcher
from storesmart.common.geometry import side_of_line
from storesmart.common.video import FrameSource
from storesmart.phase1_footfall.counter import EntryExitCounter

LINE_FILE = Path(__file__).with_name("line.json")
WIN_P = "Edge AI - People Counter"
WIN_S = "Edge AI - Shelf Watch"
FONT = cv2.FONT_HERSHEY_SIMPLEX


class _NullBus:
    """Stand-in for EventBus: keeps a capped in-memory list, no SQLite."""

    def __init__(self, cap: int = 200):
        self.events: list[dict] = []
        self.cap = cap

    def emit(self, ev: dict) -> None:
        self.events.append(ev)
        del self.events[:-self.cap]


def blur_boxes(img, boxes):
    for x1, y1, x2, y2 in boxes:
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(img.shape[1], x2), min(img.shape[0], y2)
        if x2 > x1 and y2 > y1:
            roi = img[y1:y2, x1:x2]
            img[y1:y2, x1:x2] = cv2.GaussianBlur(roi, (0, 0), 12)


def make_band(line_px, buffer_px):
    (x1, y1), (x2, y2) = line_px
    dx, dy = x2 - x1, y2 - y1
    n = max(1.0, (dx * dx + dy * dy) ** 0.5)
    ox, oy = int(-dy / n * buffer_px), int(dx / n * buffer_px)
    return np.array([[x1 - ox, y1 - oy], [x2 - ox, y2 - oy], [x2 + ox, y2 + oy], [x1 + ox, y1 + oy]], np.int32)


def draw_people(out, tracks, counter, line_px, band, blur):
    """Draws in place on `out` (a frame we own)."""
    if blur:
        blur_boxes(out, [b for _, b in tracks])
    H, W = out.shape[:2]
    bx, by, bw, bh = cv2.boundingRect(band)
    bx0, by0 = max(0, bx), max(0, by)
    bx1, by1 = min(W, bx + bw), min(H, by + bh)
    if bx1 > bx0 and by1 > by0:  # blend only the band's bounding rect, not the whole frame
        roi = out[by0:by1, bx0:bx1]
        ov = roi.copy()
        cv2.fillPoly(ov, [band - np.array([bx0, by0], np.int32)], (255, 200, 0))
        cv2.addWeighted(ov, 0.25, roi, 0.75, 0, dst=roi)
    cv2.line(out, line_px[0], line_px[1], (0, 255, 255), 2)
    for tid, (x1, y1, x2, y2) in tracks:
        cv2.rectangle(out, (x1, y1), (x2, y2), (0, 220, 0), 1)
        foot = ((x1 + x2) // 2, y2)
        cv2.circle(out, foot, 6, (0, 255, 0), -1)
        label = f"#{tid}"
        cv2.putText(out, label, (foot[0] + 8, foot[1]), FONT, 0.5, (0, 0, 0), 3, cv2.LINE_AA)
        cv2.putText(out, label, (foot[0] + 8, foot[1]), FONT, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
    return out


def draw_shelf(out, present, missing, baseline_n, log):
    G, R = (0, 200, 0), (0, 0, 230)
    for d in present:
        x1, y1, x2, y2 = d.box
        cv2.rectangle(out, (x1, y1), (x2, y2), G, 2)
        t = f"{d.cls} {d.conf:.2f}"
        cv2.putText(out, t, (x1 + 2, max(12, y1 - 5)), FONT, 0.5, (0, 0, 0), 3, cv2.LINE_AA)
        cv2.putText(out, t, (x1 + 2, max(12, y1 - 5)), FONT, 0.5, G, 1, cv2.LINE_AA)
    for d in missing:
        x1, y1, x2, y2 = d.box
        cv2.rectangle(out, (x1, y1), (x2, y2), R, 2)
        t = f"TAKEN: {d.cls}"
        cv2.putText(out, t, (x1 + 2, max(12, y1 - 5)), FONT, 0.55, (0, 0, 0), 3, cv2.LINE_AA)
        cv2.putText(out, t, (x1 + 2, max(12, y1 - 5)), FONT, 0.55, R, 2, cv2.LINE_AA)
    H = out.shape[0]
    t = f"Items on shelf: {len(present)} / {baseline_n} baseline" if baseline_n else "Calibrating baseline... (b = set now)"
    cv2.putText(out, t, (10, H - 12 - 18 * len(log)), FONT, 0.6, (0, 0, 0), 3, cv2.LINE_AA)
    cv2.putText(out, t, (10, H - 12 - 18 * len(log)), FONT, 0.6, (255, 255, 255), 1, cv2.LINE_AA)
    for i, e in enumerate(log):
        y = H - 8 - 18 * (len(log) - 1 - i)
        cv2.putText(out, e, (10, y), FONT, 0.45, (0, 0, 0), 3, cv2.LINE_AA)
        cv2.putText(out, e, (10, y), FONT, 0.45, (200, 255, 255), 1, cv2.LINE_AA)
    return out


def banner(img, text, bar_h=26):
    """Title strip across the top of a panel (panel is padded on top, so nothing is covered)."""
    pad = np.full((bar_h, img.shape[1], 3), (38, 38, 38), np.uint8)
    cv2.putText(pad, text, (10, 18), FONT, 0.55, (235, 235, 235), 1, cv2.LINE_AA)
    return np.vstack([pad, img])


def hud(img, rows, ok=True):
    """Auto-sized, scale-aware metrics card. rows: (label, value, colour|None)."""
    H, W = img.shape[:2]
    sc = max(0.5, min(1.0, W / 1100))
    th = 1 if sc < 0.8 else 2 if sc > 1.2 else 1
    lh = int(24 * sc)
    pad = int(10 * sc)
    lab_w = max(cv2.getTextSize(k, FONT, 0.5 * sc, 1)[0][0] for k, _, _ in rows)
    val_w = max(cv2.getTextSize(str(v), FONT, 0.55 * sc, th)[0][0] for _, v, _ in rows)
    w = min(W - 16, pad * 3 + lab_w + val_w)
    h = lh * len(rows) + pad * 2
    x0, y0 = 8, 26 + 8
    if y0 + h > H:
        y0 = max(0, H - h - 4)
    roi = img[y0:y0 + h, x0:x0 + w]
    roi[:] = (roi * 0.25).astype(np.uint8)
    cv2.rectangle(img, (x0, y0), (x0 + w, y0 + h), (0, 200, 120) if ok else (0, 0, 230), 1)
    for i, (k, v, col) in enumerate(rows):
        y = y0 + pad + lh * (i + 1) - int(6 * sc)
        cv2.putText(img, k, (x0 + pad, y), FONT, 0.5 * sc, (190, 190, 190), 1, cv2.LINE_AA)
        vx = x0 + pad * 2 + lab_w
        cv2.putText(img, str(v), (vx, y), FONT, 0.55 * sc, col or (80, 255, 150), th, cv2.LINE_AA)


def load_line():
    try:
        d = json.loads(LINE_FILE.read_text())
        return d["line"], int(d["in_from"])
    except Exception:
        return None


def save_line(line_norm, in_from):
    """Only coordinates are stored - never pixels."""
    LINE_FILE.write_text(json.dumps({"line": line_norm, "in_from": in_from}))


def draw_line_blocking(win: str, get_frame):
    """Click 2 endpoints, then 1 point on the OUTSIDE. Blocks until done.

    This is deliberately the same blocking loop as run_line_setup() in
    storesmart/phase1_footfall/run.py, which works in the field. An earlier
    non-blocking rewrite drove this from the main render loop, where the
    clicks had to be mapped back through the title banner and the window's
    own scaling — too many ways to be wrong, and it was.

    Here nothing is stacked on the frame and the window is sized to the
    image, so a click is already in frame coordinates.

    Returns (line_px, in_from) or None if cancelled with ESC.
    """
    pts: list[tuple[int, int]] = []
    cv2.setMouseCallback(
        win, lambda e, x, y, *_: pts.append((x, y)) if e == cv2.EVENT_LBUTTONDOWN else None)
    size = None
    try:
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
            if len(pts) >= 2:
                cv2.line(img, pts[0], pts[1], (0, 220, 255), 2)
            if len(pts) >= 3:
                break
            stage = ("click the line's 2 endpoints" if len(pts) < 2
                     else "now click a point on the OUTSIDE (away from the store)")
            for y, text, colour in ((28, f"SETUP - {stage}", (0, 255, 255)),
                                    (54, "RAW VIEW - setup only, nothing is saved   (ESC = cancel)",
                                     (235, 235, 235))):
                cv2.putText(img, text, (10, y), FONT, 0.55, (0, 0, 0), 3, cv2.LINE_AA)
                cv2.putText(img, text, (10, y), FONT, 0.55, colour, 1, cv2.LINE_AA)
            cv2.imshow(win, img)
            if (cv2.waitKey(30) & 0xFF) == 27:
                return None
    finally:
        cv2.setMouseCallback(win, lambda *a: None)

    if size is None or len(pts) < 3:
        return None
    line_px = pts[:2]
    in_from = side_of_line(line_px, pts[2], margin=0) or 1
    return line_px, in_from


def hud_rows(meter, name, device, imgsz, extra, sim, src_label):
    if meter.last_ran and meter.has_data:
        return [("Model", name, None), ("Device", device, None), ("Input size", f"{imgsz}px", None),
                ("Inference", f"{meter.inference_ms:.1f} ms mean", None),
                ("Inference p95", f"{meter.p95_ms:.1f} ms", None),
                ("FPS", f"{meter.fps:.1f}", None)] + extra + [
                ("Source", "SIMULATED scene, real YOLO" if sim else src_label,
                 (0, 200, 255) if sim else None)], True
    red = (80, 80, 255)
    return [("Model", "NO MODEL RAN - no inference", red), ("Inference", "n/a", red),
            ("FPS", f"{meter.fps:.1f}", None), ("Source", "SIMULATED, detections are fake", red)], False


def main(argv=None):
    ap = argparse.ArgumentParser(description="Edge AI lab: people counting + shelf item watch")
    ap.add_argument("--mode", choices=["people", "shelf", "both"], default="both")
    ap.add_argument("--source", default="0", help="camera index (default 0 = built-in webcam) or MJPEG/RTSP URL or video file")
    ap.add_argument("--simulate", action="store_true", help="use synthetic scenes instead of a camera (YOLO still runs on them)")
    ap.add_argument("--no-yolo-on-sim", action="store_true",
                    help="with --simulate, skip YOLO (HUD then states that no model ran)")
    ap.add_argument("--rotate", type=int, default=0)
    ap.add_argument("--conf", type=float, default=0.35)
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument("--device", default=None)
    ap.add_argument("--model", default="yolov8n.pt")
    ap.add_argument("--duration", type=float, default=0, help="stop after N seconds (0 = until q)")
    ap.add_argument("--headless", action="store_true", help="no GUI window")
    a = ap.parse_args(argv)

    sim = a.simulate
    want_people = a.mode in ("people", "both")
    want_shelf = a.mode in ("shelf", "both")
    use_model = not (sim and a.no_yolo_on_sim)

    tracker = objdet = None
    if use_model and want_people:
        from storesmart.common.detector import PersonTracker
        tracker = PersonTracker(a.model, conf=a.conf, imgsz=a.imgsz, device=a.device)
        tracker.update(np.zeros((480, 640, 3), np.uint8))  # warm-up, memory only
        try:
            tracker.model.predictor.trackers[0].reset()
        except Exception:
            pass
    if use_model and want_shelf:
        objdet = ObjectDetector(a.model, conf=a.conf, imgsz=a.imgsz, device=a.device)
        objdet.detect(np.zeros((480, 640, 3), np.uint8))  # warm-up
    device = (tracker or objdet).device if (tracker or objdet) else "none"

    people_sim = shelf_sim = src = None
    geo = None
    if sim:
        from storesmart.sim.people_sim import PeopleSimulator
        from storesmart.sim.shelf_sim import ShelfSimulator
        people_sim = PeopleSimulator()
        shelf_sim = ShelfSimulator([{"slot": "A1", "x": 20, "y": 20, "w": 100, "h": 100}])
        geo = people_sim.geometry()
    else:
        s = int(a.source) if a.source.isdigit() else a.source
        src = FrameSource(s, rotate=a.rotate)
        if not src.connected:
            print(f"ERROR: {src.last_error}")
            src.release()
            return 2

    # Live frames for the blocking line setup. Only ever used in camera mode;
    # the simulator supplies its own scripted geometry instead.
    def read_frame():
        return src.read() if src is not None else None

    counter = None
    line_px = band = None
    pmeter, smeter = PerfMeter(), PerfMeter()
    watcher = None
    bus = _NullBus()
    blur = True
    ndet_p = ndet_s = 0
    stable_n, stable_since = -1, time.perf_counter()
    gui = not a.headless
    if gui:
        if want_people:
            cv2.namedWindow(WIN_P, cv2.WINDOW_NORMAL)
            cv2.moveWindow(WIN_P, 20, 40)
        if want_shelf:
            cv2.namedWindow(WIN_S, cv2.WINDOW_NORMAL)
            cv2.moveWindow(WIN_S, 700 if want_people else 20, 40)
    t0 = last = time.perf_counter()
    try:
        while True:
            now = time.perf_counter()
            if a.duration and now - t0 >= a.duration:
                break
            dt, last = now - last, now
            sim_tracks, pframe, sframe = [], None, None
            if sim:
                dt = min(max(dt, 0.03), 0.2)
                if want_people:
                    pframe, sim_tracks = people_sim.step(dt)
                if want_shelf:
                    sframe, _ = shelf_sim.step(dt)
            else:
                f = src.read()
                if f is None:
                    time.sleep(0.01)
                    continue
                pframe = sframe = f

            def apply_line(lp, in_from, w, h):
                nonlocal counter, line_px, band
                line_px = lp
                counter = EntryExitCounter(line_px, in_from=in_from)
                band = make_band(line_px, counter.buffer_px)

            if want_people:
                h, w = pframe.shape[:2]
                if counter is None:
                    saved = load_line()
                    centre = [(w // 2, int(0.05 * h)), (w // 2, int(0.95 * h))]
                    if sim:  # simulator has its own scripted geometry
                        apply_line([(int(x * w), int(y * h)) for x, y in geo["line"]], geo["in_from"], w, h)
                    elif saved:
                        apply_line([(int(x * w), int(y * h)) for x, y in saved[0]], saved[1], w, h)
                    elif gui:
                        drawn = draw_line_blocking(WIN_P, read_frame)
                        if drawn is None:
                            apply_line(centre, 1, w, h)   # cancelled: fall back
                        else:
                            apply_line(drawn[0], drawn[1], w, h)
                            save_line([[x / w, y / h] for x, y in drawn[0]], drawn[1])
                    else:
                        apply_line(centre, 1, w, h)

            # --- real inference (timed; only recorded when a model ran) ---
            tracks, dets = [], []
            pmeter.last_ran = smeter.last_ran = False
            if want_people:
                real = []
                if tracker is not None:
                    t = time.perf_counter()
                    real = tracker.update(pframe)
                    pmeter.add((time.perf_counter() - t) * 1000)
                    pmeter.last_ran = True
                tracks = sim_tracks if sim else real
                ndet_p = len(real)
                if counter is not None:
                    counter.update(tracks, now, bus)
                pmeter.tick()
            if want_shelf:
                if objdet is not None:
                    t = time.perf_counter()
                    dets = objdet.detect(sframe)
                    smeter.add((time.perf_counter() - t) * 1000)
                    smeter.last_ran = True
                ndet_s = len(dets)
                if watcher is None:
                    watcher = ShelfWatcher(frame_width=sframe.shape[1])
                if ndet_s != stable_n:
                    stable_n, stable_since = ndet_s, now
                if not watcher.has_baseline and ndet_s > 0 and now - stable_since >= 2.0:
                    watcher.set_baseline(dets)  # auto-baseline after ~2 s of stable detections
                present, missing, _ = watcher.update(dets) if watcher.has_baseline else (dets, [], [])
                smeter.tick()

            if want_people:
                pf = pframe.copy()
                draw_people(pf, tracks, counter, line_px, band, blur)
                view = banner(pf, "PEOPLE COUNTING  [l = redraw line, v = blur, q = quit]")
                rows, ok = hud_rows(pmeter, f"{a.model} (YOLOv8 + ByteTrack)", device, a.imgsz,
                                    [("People (YOLO)", ndet_p, None),
                                     ("IN / OUT", f"{counter.entries} / {counter.exits}" if counter else "-", None)],
                                    sim, f"camera {a.source}")
                hud(view, rows, ok)
                if gui:
                    cv2.imshow(WIN_P, view)
            if want_shelf:
                sf = sframe.copy()
                draw_shelf(sf, present, missing, watcher.baseline_count, list(watcher.log))
                view = banner(sf, "SHELF WATCH  [b = set baseline, q = quit]")
                rows, ok = hud_rows(smeter, f"{a.model} (YOLOv8 detect)", device, a.imgsz,
                                    [("Detections", ndet_s, None)], sim, f"camera {a.source}")
                hud(view, rows, ok)
                if gui:
                    cv2.imshow(WIN_S, view)

            if gui:
                k = cv2.waitKey(1) & 0xFF  # one waitKey drives every window
                if k == ord("q"):
                    break
                if k == ord("v"):
                    blur = not blur
                if k == ord("l") and want_people and not sim:
                    counter = None  # re-acquired (blocking) at the top of the next loop
                if k == ord("b") and watcher is not None and want_shelf:
                    watcher.set_baseline(dets)
    finally:
        if src is not None:
            src.release()
        if gui:
            cv2.destroyAllWindows()
    def summ(m):
        return (f"mean={m.inference_ms:.1f}ms p95={m.p95_ms:.1f}ms inferences={m.inferences} fps={m.fps:.1f}"
                if m.has_data else f"inference=NONE (no model ran) fps={m.fps:.1f}")
    if want_people:
        print(f"[people] frames={pmeter.frames} {summ(pmeter)} device={device} "
              f"in={getattr(counter, 'entries', 0)} out={getattr(counter, 'exits', 0)}")
    if want_shelf:
        print(f"[shelf] frames={smeter.frames} {summ(smeter)} device={device} "
              f"baseline={watcher.baseline_count if watcher else 0} events={list(watcher.log) if watcher else []}")


if __name__ == "__main__":
    raise SystemExit(main() or 0)
