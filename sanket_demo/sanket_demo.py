#!/usr/bin/env python3
"""
Sanket demo - privacy-first people counter + queue intelligence.

Runs on a laptop with a phone as the camera (or a built-in simulator).
  * Counts people crossing an entry line (IN / OUT)
  * Measures queue length, service time and estimated wait
  * Forecasts wait from shoppers already inside the store (entrance = early warning)
  * Recommends opening another counter, with hysteresis
  * Privacy: frames stay in memory only, no image is ever written,
    tracking is motion-only (ByteTrack, no appearance features),
    the display shows blurred people or a "zero-frame" dots-only view.

Usage:
  python sanket_demo.py --source simulate                    # no camera needed
  python sanket_demo.py --source 0                           # laptop/USB/virtual webcam
  python sanket_demo.py --source http://PHONE_IP:8080/video  # phone stream (IP Webcam / DroidCam)

Keys: q quit | v change view | + / - open counters | f flip IN direction
      s redo setup | r reset counts
"""
import argparse
import json
import math
import os
import random
import socket
import threading
import time
from collections import deque

import cv2
import numpy as np

WIN = "Sanket demo"
PANEL_W = 380

# ----------------------------------------------------------------------------- video input

class FrameSource:
    """Live streams: background thread keeps only the newest frame (no lag build-up).
    Video files: read frame by frame."""

    def __init__(self, src, proc_width):
        self.proc_width = proc_width
        self.is_file = isinstance(src, str) and os.path.isfile(src)
        self.cap = cv2.VideoCapture(int(src) if str(src).isdigit() else src)
        if not self.cap.isOpened():
            raise RuntimeError(f"Could not open video source: {src}")
        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        self.frame, self.running = None, True
        self.lock = threading.Lock()
        if not self.is_file:
            threading.Thread(target=self._loop, daemon=True).start()

    def _resize(self, f):
        h, w = f.shape[:2]
        if w > self.proc_width:
            f = cv2.resize(f, (self.proc_width, int(h * self.proc_width / w)))
        return f

    def _loop(self):
        fails = 0
        while self.running:
            ok, f = self.cap.read()
            if not ok:
                fails += 1
                time.sleep(0.05)
                continue
            fails = 0
            with self.lock:
                self.frame = self._resize(f)

    def read(self):
        if self.is_file:
            ok, f = self.cap.read()
            return self._resize(f) if ok else None
        with self.lock:
            return None if self.frame is None else self.frame.copy()

    def release(self):
        self.running = False
        self.cap.release()


class YoloTracker:
    """Person detection + ByteTrack (motion-only association, no re-identification features)."""

    def __init__(self, model, conf, imgsz, device):
        from ultralytics import YOLO  # imported here so --source simulate works without it
        self.model = YOLO(model)
        self.kw = dict(persist=True, classes=[0], tracker="bytetrack.yaml",
                       conf=conf, imgsz=imgsz, verbose=False)
        if device:
            self.kw["device"] = device

    def update(self, frame):
        r = self.model.track(frame, **self.kw)[0]
        out = []
        if r.boxes is not None and r.boxes.id is not None:
            for box, tid in zip(r.boxes.xyxy.cpu().numpy(), r.boxes.id.int().cpu().tolist()):
                x1, y1, x2, y2 = (int(v) for v in box)
                out.append((tid, (x1, y1, x2, y2)))
        return out

# ----------------------------------------------------------------------------- simulator

class Simulator:
    """Synthetic store: shoppers enter, browse, queue, get served, leave.
    Arrivals surge mid-cycle so the queue alert can be demonstrated without people."""

    def __init__(self, w=960, h=540, seed=7):
        self.w, self.h = w, h
        self.people, self.queue, self.next_id = [], [], 1
        self.servers = 1
        self.t, self.next_arrival = 0.0, 1.0
        random.seed(seed)

    def cfg(self):
        return {"line": [[0.25, 0.10], [0.25, 0.92]],
                "queue": [[0.42, 0.38], [0.74, 0.38], [0.74, 0.62], [0.42, 0.62]],
                "service": [[0.77, 0.28], [0.93, 0.28], [0.93, 0.72], [0.77, 0.72]],
                "in_from": 1}

    def _rate(self):
        c = self.t % 150
        return 1 / 7.0 if c < 35 else (1 / 3.2 if c < 95 else 1 / 9.0)

    def _slot(self, i):
        return (self.w * (0.71 - 0.05 * i), self.h * 0.50)

    def _server_pos(self, k):
        return (self.w * 0.85, self.h * (0.40 + 0.20 * k))

    def step(self, dt):
        W, H = self.w, self.h
        self.t += dt
        if self.t >= self.next_arrival:
            self.people.append({"id": self.next_id, "x": -0.02 * W, "y": H * random.uniform(0.45, 0.8),
                                "state": "enter", "tx": W * random.uniform(0.3, 0.62),
                                "ty": H * random.uniform(0.14, 0.30), "v": random.uniform(90, 140), "timer": 0})
            self.next_id += 1
            self.next_arrival = self.t + random.expovariate(self._rate())
        serving = [p for p in self.people if p["state"] == "serving"]
        busy = {p["server"] for p in serving}
        for p in list(self.people):
            s = p["state"]
            if s == "browse":
                p["timer"] -= dt
                if p["timer"] <= 0:
                    p["state"] = "queue"
                    self.queue.append(p)
            if p["state"] == "queue":
                i = self.queue.index(p)
                p["tx"], p["ty"] = self._slot(i)
                free = [k for k in range(self.servers) if k not in busy]
                if i == 0 and free:
                    self.queue.pop(0)
                    p["state"], p["server"] = "serving", free[0]
                    busy.add(free[0])
                    p["tx"], p["ty"] = self._server_pos(free[0])
                    p["timer"] = random.uniform(4, 8)
            arrived = self._move(p, dt)
            if p["state"] == "enter" and arrived:
                p["state"], p["timer"] = "browse", random.uniform(3, 8)
            elif p["state"] == "serving" and arrived:
                p["timer"] -= dt
                if p["timer"] <= 0:
                    p["state"], p["tx"], p["ty"] = "exit1", W * 0.86, H * 0.86
            elif p["state"] == "exit1" and arrived:
                p["state"], p["tx"], p["ty"] = "exit2", -0.08 * W, H * 0.86
            elif p["state"] == "exit2" and arrived:
                self.people.remove(p)
        frame = np.full((H, W, 3), (38, 38, 42), np.uint8)
        tracks = []
        for p in self.people:
            x, y = int(p["x"]), int(p["y"])
            cv2.rectangle(frame, (x - 14, y - 62), (x + 14, y), (150, 150, 160), -1)
            cv2.circle(frame, (x, y - 74), 12, (170, 170, 180), -1)
            tracks.append((p["id"], (x - 18, y - 88, x + 18, y)))
        return frame, tracks

    @staticmethod
    def _move(p, dt):
        dx, dy = p["tx"] - p["x"], p["ty"] - p["y"]
        d = math.hypot(dx, dy)
        stepd = p["v"] * dt
        if d <= stepd:
            p["x"], p["y"] = p["tx"], p["ty"]
            return True
        p["x"] += dx / d * stepd
        p["y"] += dy / d * stepd
        return False

# ----------------------------------------------------------------------------- events (the only thing that persists)

class EventLog:
    def __init__(self, path, udp):
        self.f = open(path, "a", encoding="utf-8")
        self.count, self.bytes = 0, 0
        self.sock, self.addr = None, None
        if udp:
            host, port = udp.split(":")
            self.sock, self.addr = socket.socket(socket.AF_INET, socket.SOCK_DGRAM), (host, int(port))

    def emit(self, ev):
        line = json.dumps(ev, separators=(",", ":"))
        self.f.write(line + "\n")
        self.f.flush()
        self.count += 1
        self.bytes += len(line) + 1
        if self.sock:
            self.sock.sendto(line.encode(), self.addr)

# ----------------------------------------------------------------------------- analytics

class Analytics:
    def __init__(self, cfg, size, args, log):
        self.args, self.log = args, log
        self.set_geometry(cfg, size)
        self.counters = args.counters
        self.reset()

    def set_geometry(self, cfg, size):
        w, h = size
        self.cfg = cfg
        px = lambda pts: None if not pts else np.array([[x * w, y * h] for x, y in pts], np.float32)
        self.line = px(cfg["line"])
        self.queue_poly, self.service_poly = px(cfg.get("queue")), px(cfg.get("service"))
        self.in_from = cfg.get("in_from", 1)

    def reset(self):
        self.side, self.last_seen, self.in_service = {}, {}, {}
        self.entries = self.exits = self.served = 0
        self.entry_times, self.durations = deque(), deque(maxlen=10)
        self.q = self.serving_now = self.browsing = 0
        self.wait_now = self.pred_wait = self.pred_wait_plus = 0.0
        self.alert, self.cond_since, self.clear_since = False, None, None
        self.alert_reason, self.last_summary = "", -1e9

    def _signed(self, p):
        (ax, ay), (bx, by) = self.line
        return ((bx - ax) * (p[1] - ay) - (by - ay) * (p[0] - ax)) / (math.hypot(bx - ax, by - ay) + 1e-6)

    @staticmethod
    def _inside(poly, p):
        return poly is not None and cv2.pointPolygonTest(poly, (float(p[0]), float(p[1])), False) >= 0

    def mean_service(self):
        return sum(self.durations) / len(self.durations) if self.durations else self.args.default_service

    def update(self, tracks, now):
        a = self.args
        q = serving = 0
        for tid, (x1, y1, x2, y2) in tracks:
            foot = ((x1 + x2) / 2, y2)
            self.last_seen[tid] = now
            d = self._signed(foot)
            s = 1 if d > a.margin else (-1 if d < -a.margin else 0)
            if s:
                prev = self.side.get(tid)
                if prev is not None and prev != s:
                    if prev == self.in_from:
                        self.entries += 1
                        self.entry_times.append(now)
                        self.log.emit({"t": round(now, 2), "type": "entry"})
                    else:
                        self.exits += 1
                        self.log.emit({"t": round(now, 2), "type": "exit"})
                self.side[tid] = s
            if self._inside(self.queue_poly, foot):
                q += 1
            if self._inside(self.service_poly, foot):
                serving += 1
                self.in_service.setdefault(tid, now)
            elif tid in self.in_service:
                self._finish_service(tid, now)
        for tid in [t for t, ts in self.last_seen.items() if now - ts > a.lost_after]:
            if tid in self.in_service:
                self._finish_service(tid, now)
            self.last_seen.pop(tid, None)
            self.side.pop(tid, None)
        while self.entry_times and now - self.entry_times[0] > a.window:
            self.entry_times.popleft()

        self.q, self.serving_now = q, serving
        inside = max(0, self.entries - self.exits)
        self.browsing = max(0, inside - q - serving)
        mu = 1.0 / max(self.mean_service(), 0.5)
        self.wait_now = q / (self.counters * mu)
        self.pred_wait = self._forecast(self.counters, mu)
        self.pred_wait_plus = self._forecast(self.counters + 1, mu)
        self._alerting(now)
        if now - self.last_summary >= 5:
            self.last_summary = now
            self.log.emit({"t": round(now, 2), "type": "summary", "in": self.entries, "out": self.exits,
                           "queue": q, "counters": self.counters, "wait_s": round(self.wait_now, 1),
                           "forecast_wait_s": round(self.pred_wait, 1)})

    def _forecast(self, c, mu):
        # Early warning: shoppers already inside (counted at the entrance) will reach checkout soon.
        # Demo heuristic; the production design uses a trained forecaster (LightGBM) + Erlang-C.
        a = self.args
        q_future = max(0.0, self.q + a.join_prob * self.browsing - c * mu * a.horizon)
        return q_future / (c * mu)

    def _finish_service(self, tid, now):
        dur = now - self.in_service.pop(tid)
        if dur >= self.args.min_service:
            self.served += 1
            self.durations.append(dur)
            self.log.emit({"t": round(now, 2), "type": "served", "service_s": round(dur, 1)})

    def _alerting(self, now):
        a = self.args
        hot = self.wait_now > a.threshold or self.pred_wait > a.threshold
        cool = self.wait_now < 0.6 * a.threshold and self.pred_wait < 0.6 * a.threshold
        if not self.alert:
            self.cond_since = (self.cond_since or now) if hot else None
            if self.cond_since is not None and now - self.cond_since >= a.hold:
                self.alert, self.clear_since = True, None
                self.alert_reason = "forecast" if self.pred_wait > self.wait_now else "queue now"
                self.log.emit({"t": round(now, 2), "type": "alert_open_counter", "reason": self.alert_reason,
                               "wait_s": round(self.wait_now, 1), "forecast_wait_s": round(self.pred_wait, 1)})
        else:
            self.clear_since = (self.clear_since or now) if cool else None
            if self.clear_since is not None and now - self.clear_since >= a.hold:
                self.alert, self.cond_since = False, None
                self.log.emit({"t": round(now, 2), "type": "alert_cleared"})

    def set_counters(self, n, now):
        self.counters = max(1, n)
        self.log.emit({"t": round(now, 2), "type": "counters_changed", "counters": self.counters})

# ----------------------------------------------------------------------------- drawing

def txt(img, s, org, scale=0.55, color=(235, 235, 235), thick=1):
    cv2.putText(img, s, (org[0] + 1, org[1] + 1), cv2.FONT_HERSHEY_SIMPLEX, scale, (0, 0, 0), thick + 1, cv2.LINE_AA)
    cv2.putText(img, s, org, cv2.FONT_HERSHEY_SIMPLEX, scale, color, thick, cv2.LINE_AA)


def draw_geometry(img, an):
    (ax, ay), (bx, by) = an.line.astype(int)
    cv2.line(img, (ax, ay), (bx, by), (0, 220, 255), 3)
    mx, my = (ax + bx) // 2, (ay + by) // 2
    nx, ny = (by - ay), -(bx - ax)
    n = math.hypot(nx, ny) + 1e-6
    sgn = -an.in_from  # arrow points from the "outside" side to the inside
    ex, ey = int(mx + sgn * -nx / n * 45), int(my + sgn * -ny / n * 45)
    cv2.arrowedLine(img, (mx, my), (ex, ey), (0, 220, 255), 3, tipLength=0.35)
    txt(img, "IN", (ex + 6, ey), 0.7, (0, 220, 255), 2)
    for poly, col, name in ((an.queue_poly, (0, 150, 255), "QUEUE"), (an.service_poly, (80, 220, 80), "COUNTER")):
        if poly is not None:
            cv2.polylines(img, [poly.astype(np.int32)], True, col, 2)
            x, y = poly.min(axis=0).astype(int)
            txt(img, name, (x + 6, y + 20), 0.55, col, 2)


def render(frame, tracks, an, view, fps, log):
    h, w = frame.shape[:2]
    if view == "zero-frame":
        img = np.zeros_like(frame)
    else:
        img = frame.copy()
        if view == "blurred":
            for _, (x1, y1, x2, y2) in tracks:
                x1, y1, x2, y2 = max(0, x1), max(0, y1), min(w, x2), min(h, y2)
                if x2 - x1 > 4 and y2 - y1 > 4:
                    img[y1:y2, x1:x2] = cv2.GaussianBlur(img[y1:y2, x1:x2], (0, 0), 18)
    draw_geometry(img, an)
    for tid, (x1, y1, x2, y2) in tracks:
        foot = ((x1 + x2) // 2, y2)
        if view != "zero-frame":
            cv2.rectangle(img, (x1, y1), (x2, y2), (255, 200, 0), 1)
        cv2.circle(img, foot, 7, (255, 200, 0), -1)
        txt(img, f"#{tid}", (foot[0] + 8, foot[1] - 6), 0.45, (255, 200, 0))
    label = {"blurred": "VIEW: people blurred", "zero-frame": "VIEW: zero-frame (positions only)",
             "raw": "RAW VIEW - setup only, nothing is saved"}[view]
    txt(img, label, (10, 24), 0.6, (0, 0, 255) if view == "raw" else (200, 255, 200), 2)
    txt(img, f"{fps:4.1f} FPS", (10, h - 12), 0.5)

    panel = np.full((h, PANEL_W, 3), (30, 24, 20), np.uint8)
    y = 34
    def line(s, scale=0.6, color=(235, 235, 235), gap=28, thick=1):
        nonlocal y
        txt(panel, s, (16, y), scale, color, thick)
        y += gap
    line("SANKET  live demo", 0.75, (180, 230, 210), 36, 2)
    line("FOOTFALL", 0.55, (150, 170, 190), 26)
    line(f"IN {an.entries}    OUT {an.exits}    Inside {max(0, an.entries - an.exits)}", 0.62)
    line(f"Browsing (not yet queuing): {an.browsing}", 0.52, gap=34)
    line("QUEUE", 0.55, (150, 170, 190), 26)
    line(f"In queue: {an.q}     At counter: {an.serving_now}", 0.6)
    line(f"Open counters: {an.counters}     Served: {an.served}", 0.6)
    line(f"Avg service time: {an.mean_service():.1f} s", 0.55)
    line(f"Est. wait now: {an.wait_now:.0f} s", 0.62)
    line(f"Forecast wait: {an.pred_wait:.0f} s", 0.62, gap=34)
    if an.alert:
        cv2.rectangle(panel, (10, y - 22), (PANEL_W - 10, y + 52), (0, 0, 200), -1)
        txt(panel, "OPEN ANOTHER COUNTER", (20, y + 4), 0.68, (255, 255, 255), 2)
        txt(panel, f"({an.alert_reason}) wait {an.pred_wait if an.alert_reason == 'forecast' else an.wait_now:.0f}s"
                   f" -> {an.pred_wait_plus:.0f}s with {an.counters + 1}", (20, y + 36), 0.5, (255, 255, 255))
        y += 76
    else:
        line("Status: queue under control", 0.55, (120, 220, 120), 40)
    line("PRIVACY", 0.55, (150, 170, 190), 26)
    line("Images written to disk: 0", 0.55, (180, 230, 210), 24)
    line(f"Events logged: {log.count} ({log.bytes / 1024:.1f} KB)", 0.55, (180, 230, 210), 24)
    line("Identity features: none", 0.55, (180, 230, 210), 30)
    txt(panel, "q quit  v view  +/- counters  f flip  r reset", (16, h - 14), 0.45, (150, 150, 150))
    return np.hstack([img, panel])

# ----------------------------------------------------------------------------- setup (click to place line and zones)

def run_setup(get_frame):
    stages = [("Click 2 points for the ENTRY LINE", "line"),
              ("Click corners of the QUEUE zone, ENTER to finish  (N = counter only, skip queue)", "queue"),
              ("Click corners of the COUNTER / service zone, ENTER to finish", "service")]
    pts, done, idx = [], {}, 0
    cv2.setMouseCallback(WIN, lambda e, x, y, *_: pts.append((x, y)) if e == cv2.EVENT_LBUTTONDOWN else None)
    size = None
    while idx < len(stages):
        f = get_frame()
        if f is None:
            if cv2.waitKey(30) & 0xFF == 27:
                return None
            continue
        size = (f.shape[1], f.shape[0])
        img = f.copy()
        for key, col in (("line", (0, 220, 255)), ("queue", (0, 150, 255)), ("service", (80, 220, 80))):
            if done.get(key):
                cv2.polylines(img, [np.array(done[key], np.int32)], key != "line", col, 2)
        for p in pts:
            cv2.circle(img, p, 5, (0, 0, 255), -1)
        if len(pts) > 1:
            cv2.polylines(img, [np.array(pts, np.int32)], False, (0, 0, 255), 1)
        txt(img, "SETUP - " + stages[idx][0], (10, 28), 0.6, (0, 255, 255), 2)
        txt(img, "U = undo point   ESC = cancel   (raw view, nothing is saved)", (10, 54), 0.5)
        cv2.imshow(WIN, img)
        k = cv2.waitKey(30) & 0xFF
        name = stages[idx][1]
        if k == 27:
            return None
        if k in (ord("u"), ord("U")) and pts:
            pts.pop()
        if name == "line" and len(pts) >= 2:
            done["line"], pts, idx = pts[:2], [], idx + 1
        elif name == "queue" and k in (ord("n"), ord("N")):
            break
        elif name != "line" and k in (13, 10) and len(pts) >= 3:
            done[name], pts, idx = list(pts), [], idx + 1
    cv2.setMouseCallback(WIN, lambda *a: None)
    w, h = size
    norm = lambda P: [[round(x / w, 4), round(y / h, 4)] for x, y in P]
    return {"line": norm(done["line"]), "queue": norm(done["queue"]) if "queue" in done else None,
            "service": norm(done["service"]) if "service" in done else None, "in_from": 1}

# ----------------------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description="Sanket privacy-first counter + queue demo")
    ap.add_argument("--source", default="0", help="'simulate', webcam index (0,1..), stream URL or video file")
    ap.add_argument("--config", default="sanket_config.json")
    ap.add_argument("--events", default="events.jsonl")
    ap.add_argument("--udp", default=None, help="also send events as UDP JSON to host:port (for a network-capture demo)")
    ap.add_argument("--model", default="yolov8n.pt")
    ap.add_argument("--conf", type=float, default=0.35)
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument("--device", default=None, help="e.g. cpu, 0 (CUDA), mps")
    ap.add_argument("--proc-width", type=int, default=960)
    ap.add_argument("--counters", type=int, default=1)
    ap.add_argument("--threshold", type=float, default=12, help="alert when wait (s) exceeds this")
    ap.add_argument("--horizon", type=float, default=10, help="forecast horizon (s); minutes in a real store")
    ap.add_argument("--join-prob", type=float, default=1.0, help="share of browsing shoppers expected at checkout")
    ap.add_argument("--hold", type=float, default=3, help="condition must hold this long before alert on/off (s)")
    ap.add_argument("--window", type=float, default=30)
    ap.add_argument("--default-service", type=float, default=6)
    ap.add_argument("--min-service", type=float, default=1.0)
    ap.add_argument("--margin", type=float, default=12, help="px dead-band around the line against jitter")
    ap.add_argument("--lost-after", type=float, default=1.5)
    ap.add_argument("--headless", action="store_true", help="no window (testing)")
    ap.add_argument("--duration", type=float, default=0, help="stop after N seconds (0 = run until q)")
    args = ap.parse_args()

    simulate = args.source == "simulate"
    log = EventLog(args.events, args.udp)
    if not args.headless:
        cv2.namedWindow(WIN, cv2.WINDOW_NORMAL)

    if simulate:
        sim = Simulator()
        cfg, size = sim.cfg(), (sim.w, sim.h)
        get_frame, tracker = None, None
    else:
        src = FrameSource(args.source, args.proc_width)
        get_frame = src.read
        t_wait = time.time()
        f = None
        while f is None and time.time() - t_wait < 15:
            f = get_frame()
            time.sleep(0.05)
        if f is None:
            raise RuntimeError("No frames from the camera. Check the URL / app / Wi-Fi.")
        size = (f.shape[1], f.shape[0])
        cfg = None
        if os.path.exists(args.config):
            with open(args.config, encoding="utf-8") as fh:
                cfg = json.load(fh)
        if cfg is None:
            if args.headless:
                raise RuntimeError("No config file; run once with a window to click the line and zones.")
            cfg = run_setup(get_frame)
            if cfg is None:
                return
            with open(args.config, "w", encoding="utf-8") as fh:
                json.dump(cfg, fh, indent=2)
        print("Loading detector...")
        tracker = YoloTracker(args.model, args.conf, args.imgsz, args.device)

    an = Analytics(cfg, size, args, log)
    views = ["blurred", "zero-frame", "raw"]
    view = 0
    t0, dt_sim = time.time(), 1 / 15
    fps, last = 0.0, time.time()
    while True:
        if simulate:
            sim.servers = an.counters
            frame, tracks = sim.step(dt_sim)
            now = sim.t
        else:
            frame = get_frame()
            if frame is None:
                if not args.headless and (cv2.waitKey(10) & 0xFF) == ord("q"):
                    break
                continue
            now = time.time() - t0
            tracks = tracker.update(frame)
        an.update(tracks, now)
        # frame is only ever held in memory; it is never written anywhere
        tnow = time.time()
        fps = 0.9 * fps + 0.1 / max(tnow - last, 1e-3)
        last = tnow
        if not args.headless:
            cv2.imshow(WIN, render(frame, tracks, an, views[view], fps, log))
            wait = max(1, int((dt_sim - (time.time() - tnow)) * 1000)) if simulate else 1
            k = cv2.waitKey(wait) & 0xFF
            if k == ord("q"):
                break
            elif k == ord("v"):
                view = (view + 1) % len(views)
            elif k in (ord("+"), ord("=")):
                an.set_counters(an.counters + 1, now)
            elif k in (ord("-"), ord("_")):
                an.set_counters(an.counters - 1, now)
            elif k == ord("r"):
                an.reset()
            elif k == ord("f"):
                cfg["in_from"] = -cfg.get("in_from", 1)
                an.set_geometry(cfg, size)
                an.side.clear()
                if not simulate:
                    with open(args.config, "w", encoding="utf-8") as fh:
                        json.dump(cfg, fh, indent=2)
            elif k == ord("s") and not simulate:
                new = run_setup(get_frame)
                if new:
                    cfg = new
                    an.set_geometry(cfg, size)
                    with open(args.config, "w", encoding="utf-8") as fh:
                        json.dump(cfg, fh, indent=2)
        if args.duration and now >= args.duration:
            break
    print(f"IN {an.entries} OUT {an.exits} served {an.served} | events {log.count} "
          f"({log.bytes / 1024:.1f} KB) | images written: 0")
    if not simulate:
        src.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
