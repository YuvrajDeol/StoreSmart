"""Edge AI lab demo: on-device people counting + shelf gap detection.

Frames live only in memory; nothing is ever written to disk.
Inference metrics are always real: they time an actual YOLOv8 forward pass
(plus ByteTrack). If no model ran, the HUD says so instead of showing 0 ms.
"""
from __future__ import annotations

import argparse
import time

import cv2
import numpy as np

from edge_lab.metrics import PerfMeter
from storesmart.common.video import FrameSource
from storesmart.phase1_footfall.counter import EntryExitCounter
from storesmart.phase3_shelf.gap_detector import GapDetector
from storesmart.phase3_shelf.slots import load_slots

COLORS = {"ok": (0, 200, 0), "low": (0, 170, 255), "empty": (0, 0, 230)}
FONT = cv2.FONT_HERSHEY_SIMPLEX
MAX_VIEW_W = 1280


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


def draw_shelf(out, slots, detector):
    for s in slots:
        st = detector.states[s["slot"]]
        c = COLORS.get(st.state, (200, 200, 200))
        x, y, w, h = s["x"], s["y"], s["w"], s["h"]
        cv2.rectangle(out, (x, y), (x + w, y + h), c, 2)
        t = f"{s['slot']} {st.fill_pct:.0f}%"
        cv2.putText(out, t, (x + 4, y + 18), FONT, 0.5, (0, 0, 0), 3, cv2.LINE_AA)
        cv2.putText(out, t, (x + 4, y + 18), FONT, 0.5, c, 1, cv2.LINE_AA)
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


def fit_height(img, h):
    if img.shape[0] == h:
        return img
    s = h / img.shape[0]
    return cv2.resize(img, (int(img.shape[1] * s), h))


def main(argv=None):
    ap = argparse.ArgumentParser(description="Edge AI lab: people counting + shelf gap detection")
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

    cfg = load_slots()
    slots = cfg["slots"]
    detector = GapDetector(slots, cfg["backdrop_hsv_lower"], cfg["backdrop_hsv_upper"])

    tracker = None
    if not (sim and a.no_yolo_on_sim):
        from storesmart.common.detector import PersonTracker
        tracker = PersonTracker(a.model, conf=a.conf, imgsz=a.imgsz, device=a.device)
        # warm-up (model load / MPS kernel compile) so it doesn't pollute p95; blank frame, memory only
        tracker.update(np.zeros((480, 640, 3), np.uint8))
        try:
            tracker.model.predictor.trackers[0].reset()  # forget warm-up track state
        except Exception:
            pass
    device = tracker.device if tracker else "none"
    model_name = a.model if tracker else "NONE"

    people_sim = shelf_sim = src = None
    geo = None
    if sim:
        from storesmart.sim.people_sim import PeopleSimulator
        from storesmart.sim.shelf_sim import ShelfSimulator
        people_sim = PeopleSimulator()
        shelf_sim = ShelfSimulator(slots)
        geo = people_sim.geometry()
    else:
        s = int(a.source) if a.source.isdigit() else a.source
        src = FrameSource(s, rotate=a.rotate)
        if not src.connected:
            print(f"ERROR: {src.last_error}")
            src.release()
            return 2
    counter = None
    line_px = band = None
    meter = PerfMeter()
    gap_ms = 0.0
    bus = _NullBus()
    blur = True
    t0 = last = time.perf_counter()
    ndet = 0
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
                infer_frame = pframe if pframe is not None else sframe
            else:
                f = src.read()
                if f is None:
                    time.sleep(0.01)
                    continue
                pframe = sframe = infer_frame = f
            if want_people and counter is None:
                h, w = pframe.shape[:2]
                ln = geo["line"] if geo else [[0.5, 0.05], [0.5, 0.95]]  # webcam: vertical centre line
                line_px = [(int(x * w), int(y * h)) for x, y in ln]
                counter = EntryExitCounter(line_px, in_from=(geo or {}).get("in_from", 1))
                band = make_band(line_px, counter.buffer_px)

            # --- real inference (timed) ---
            real = []
            ran = False
            if tracker is not None:
                t = time.perf_counter()
                real = tracker.update(infer_frame)
                meter.add((time.perf_counter() - t) * 1000)
                ran = True
            meter.last_ran = ran
            tracks = sim_tracks if (sim and want_people) else real
            ndet = len(real)

            if want_people:
                counter.update(tracks, now, bus)
            if want_shelf:
                boxes = [b for _, b in real] if not sim else []
                t = time.perf_counter()
                detector.update(sframe, boxes)
                gap_ms = (time.perf_counter() - t) * 1000
            meter.tick()

            panels = []
            if want_people:
                pf = pframe.copy() if (want_shelf and pframe is sframe) else pframe  # shelf analysis already done
                panels.append(banner(draw_people(pf, tracks, counter, line_px, band, blur), "PEOPLE COUNTING"))
            if want_shelf:
                panels.append(banner(draw_shelf(sframe, slots, detector), "SHELF GAP DETECTION"))
            h = max(p.shape[0] for p in panels)
            view = panels[0] if len(panels) == 1 else np.hstack([fit_height(p, h) for p in panels])
            if view.shape[1] > MAX_VIEW_W:  # single downscale; HUD drawn after so text stays crisp
                s = MAX_VIEW_W / view.shape[1]
                view = cv2.resize(view, (MAX_VIEW_W, int(view.shape[0] * s)), interpolation=cv2.INTER_AREA)

            if ran and meter.has_data:
                rows = [
                    ("Model", f"{model_name} (YOLOv8 + ByteTrack)", None),
                    ("Device", device, None),
                    ("Input size", f"{a.imgsz}px", None),
                    ("Inference", f"{meter.inference_ms:.1f} ms mean", None),
                    ("Inference p95", f"{meter.p95_ms:.1f} ms", None),
                    ("FPS", f"{meter.fps:.1f}", None),
                    ("People (YOLO)", ndet, None),
                ]
                if want_shelf:
                    rows.append(("Gap detector", f"{gap_ms:.1f} ms (classical CV)", None))
                if sim:
                    rows.append(("Source", "SIMULATED scene, real YOLO", (0, 200, 255)))
                else:
                    rows.append(("Source", f"camera {a.source}", None))
                ok = True
            else:
                red = (80, 80, 255)
                rows = [("Model", "NO MODEL RAN - no inference", red),
                        ("Inference", "n/a", red),
                        ("FPS", f"{meter.fps:.1f}", None),
                        ("Source", "SIMULATED, detections are fake", red)]
                ok = False
            hud(view, rows, ok)

            if not a.headless:
                cv2.imshow("StoreSmart Edge Lab", view)
                k = cv2.waitKey(1) & 0xFF
                if k == ord("q"):
                    break
                if k == ord("v"):
                    blur = not blur
    finally:
        if src is not None:
            src.release()
        if not a.headless:
            cv2.destroyAllWindows()
    inf = (f"mean={meter.inference_ms:.1f}ms p95={meter.p95_ms:.1f}ms inferences={meter.inferences}"
           if meter.has_data else "inference=NONE (no model ran)")
    print(f"frames={meter.frames} {inf} fps={meter.fps:.1f} device={device} "
          f"in={getattr(counter, 'entries', 0)} out={getattr(counter, 'exits', 0)}")


if __name__ == "__main__":
    raise SystemExit(main() or 0)
