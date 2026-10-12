"""Gamified, step-by-step explainer of the object-detection pipeline (YOLOv8) for the Edge AI lab.

Run it in front of a webcam: n/p walk the six stages, digits 1-9 answer the quiz, + / - move the
confidence threshold in stage 4. Frames live only in memory; nothing is ever written to disk.

HONESTY NOTES (also shown on screen):
* Stage 3 shows MINIMALLY FILTERED output: a real forward pass with conf=0.01 and NMS iou=0.95, so
  almost nothing is dropped or merged. It is NOT the literal pre-NMS tensor of the detection head
  (Ultralytics does not expose that through predict()).
* Stage 2 draws the classic square letterbox (what fixed-shape / NPU exports receive). The PyTorch
  predict() path on a single image trims the padding to a multiple of 32 (e.g. 640x384), same scale.
* Inference time is recorded only for real stage-6 forward passes; if none ran the HUD says n/a.
"""
from __future__ import annotations

import argparse
import time
from dataclasses import dataclass, field

import cv2
import numpy as np

from edge_lab.app import FONT, blur_boxes, hud, hud_rows
from edge_lab.metrics import PerfMeter
from edge_lab.shelf_watch import Det, ObjectDetector

WIN = "Edge AI - How Detection Works"
N_STAGES = 6
MAX_SCORE = 300
QUESTION_STAGES = (2, 3, 4)          # 0-based indices of stages that pose a question
CAND_CONF, CAND_IOU = 0.01, 0.95     # stage 3: "minimally filtered" settings
NMS_IOU = 0.45                       # standard YOLO NMS iou
Q_THRESHOLD = 0.50                   # stage 4 question is asked at this threshold
PAD_GREY = 114                       # YOLO's letterbox fill colour
MAX_DET = 300

# BGR colours
C_OK, C_CLOSE, C_BAD = (90, 220, 90), (0, 190, 255), (70, 70, 240)
C_TXT, C_DIM, C_ACC = (235, 235, 235), (175, 175, 175), (255, 200, 0)
C_BAR = (38, 38, 38)

STAGES = [
    ("INPUT", "The camera hands us a full-resolution frame. The model never sees this resolution directly - it gets resized first."),
    ("PREPROCESS", "The frame is scaled to fit a square and padded with grey bars so shapes are not stretched. This square is what the network receives."),
    ("CANDIDATES", "One forward pass at a very low threshold: the model proposes many overlapping guesses for every object."),
    ("CONFIDENCE", "Every guess carries a confidence score. The threshold is the precision/recall dial: higher = fewer false alarms, lower = fewer misses."),
    ("NMS", "Non-maximum suppression collapses overlapping boxes that describe the same object into the single best one."),
    ("RESULT", "Clean final detections. This is exactly what the people counter and the shelf watcher consume."),
]
QUESTIONS = {
    2: "How many candidate boxes will the model propose? 1-9 = that many x5",
    3: "At threshold 0.5, how many survive? press 1-9",
    4: "After NMS, how many distinct objects? press 1-9",
}


# ----------------------------------------------------------------------------- pure logic (tested)
def score_answer(guess: int, truth: int) -> tuple[int, str]:
    """-> (points, verdict). Exact = 100, within 1 = 50, else 0."""
    d = abs(int(guess) - int(truth))
    if d == 0:
        return 100, "correct"
    if d == 1:
        return 50, "close"
    return 0, "wrong"


def candidate_bucket(n: int) -> int:
    """Stage-3 answers are 'k x 5' boxes, k in 1-9: nearest multiple of 5, clamped to 0-9."""
    return max(0, min(9, int(n / 5 + 0.5)))


def clamp_digit(n: int) -> int:
    return max(0, min(9, int(n)))


def letterbox_params(w: int, h: int, size: int) -> dict:
    """Scale + padding to fit a w x h frame into a size x size square, keeping aspect ratio."""
    scale = min(size / w, size / h)
    nw, nh = int(round(w * scale)), int(round(h * scale))
    px, py = (size - nw) // 2, (size - nh) // 2
    return dict(scale=scale, new_w=nw, new_h=nh, pad_x=px, pad_y=py,
                pad_r=size - nw - px, pad_b=size - nh - py, size=size)


def letterbox_text(w: int, h: int, size: int) -> str:
    p = letterbox_params(w, h, size)
    return f"{w}x{h} -> {size}x{size}, scale {p['scale']:.2f}, pad {p['pad_x']},{p['pad_y']}"


def letterbox_image(frame, size: int):
    """The real resized + grey-padded square (memory only)."""
    h, w = frame.shape[:2]
    p = letterbox_params(w, h, size)
    interp = cv2.INTER_AREA if p["scale"] < 1 else cv2.INTER_LINEAR
    r = cv2.resize(frame, (p["new_w"], p["new_h"]), interpolation=interp)
    g = (PAD_GREY,) * 3
    return cv2.copyMakeBorder(r, p["pad_y"], p["pad_b"], p["pad_x"], p["pad_r"], cv2.BORDER_CONSTANT, value=g)


def grade(total: int, pts: dict[int, int]) -> str:
    """One-line verdict; below the top band it names the weakest question stage."""
    if total >= 250:
        return "You understand the pipeline"
    topics = {2: "candidates", 3: "the confidence dial", 4: "NMS"}
    worst = min(QUESTION_STAGES, key=lambda s: pts.get(s, 0))
    return f"Good start - revisit {topics[worst]}" if total >= 100 else f"Revisit {topics[worst]} (and replay with r)"


def count_at(dets, thr: float) -> int:
    return sum(1 for d in dets if d.conf >= thr)


# ----------------------------------------------------------------------------- drawing helpers
def text(img, s, org, scale=0.55, color=C_TXT, th=1):
    cv2.putText(img, s, org, FONT, scale, (0, 0, 0), th + 2, cv2.LINE_AA)
    cv2.putText(img, s, org, FONT, scale, color, th, cv2.LINE_AA)


def tsize(s, scale, th=1):
    (w, h), base = cv2.getTextSize(s, FONT, scale, th)
    return w, h, base


def wrap(s, max_w, scale, th=1):
    lines, cur = [], ""
    for word in s.split():
        t = f"{cur} {word}".strip()
        if cur and tsize(t, scale, th)[0] > max_w:
            lines.append(cur)
            cur = word
        else:
            cur = t
    return lines + [cur] if cur else lines or [""]


def shade(img, x0, y0, x1, y1, border=None, alpha=0.25):
    H, W = img.shape[:2]
    x0, y0, x1, y1 = max(0, x0), max(0, y0), min(W, x1), min(H, y1)
    if x1 <= x0 or y1 <= y0:
        return
    roi = img[y0:y1, x0:x1]
    roi[:] = (roi * alpha).astype(np.uint8)
    if border:
        cv2.rectangle(img, (x0, y0), (x1 - 1, y1 - 1), border, 1)


def chip(img, lines, x, y, sc, anchor="tl", border=C_ACC, max_w=None):
    """Dark translucent panel with (text, colour, size-factor) lines; wraps to max_w, stays inside img."""
    H, W = img.shape[:2]
    pad = int(8 * sc)
    max_w = max_w or W - 2 * pad - 16
    rows = []
    for s, col, f in lines:
        for ln in wrap(s, max_w, 0.5 * sc * f):
            rows.append((ln, col, 0.5 * sc * f))
    tw = max(tsize(r[0], r[2])[0] for r in rows)
    lh = [tsize(r[0], r[2])[1] + int(8 * sc) for r in rows]
    w, h = tw + 2 * pad, sum(lh) + 2 * pad - int(4 * sc)
    x0 = x if anchor == "tl" else x - w
    x0, y0 = max(2, min(x0, W - w - 2)), max(2, min(y, H - h - 2))
    shade(img, x0, y0, x0 + w, y0 + h, border)
    yy = y0 + pad
    for (ln, col, s), step in zip(rows, lh):
        yy += step
        text(img, ln, (x0 + pad, yy - int(5 * sc)), s, col)
    return x0, y0, w, h


def fit(img, rw, rh):
    """Resize img to fit rw x rh, centred. -> (resized, ox, oy, scale)."""
    h, w = img.shape[:2]
    s = min(rw / w, rh / h)
    nw, nh = max(1, int(w * s)), max(1, int(h * s))
    return cv2.resize(img, (nw, nh), interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_LINEAR), (rw - nw) // 2, (rh - nh) // 2, s


def conf_colour(c):
    """Low confidence = cool/dim blue, high = warm green-yellow (BGR)."""
    c = float(np.clip(c, 0, 1))
    return (int(255 * (1 - c)), int(120 + 135 * c), int(40 + 120 * c))


def draw_boxes(img, dets, tf, labels=True, sc=1.0, solid=True):
    ox, oy, s = tf
    for d in dets:
        x1, y1, x2, y2 = (int(ox + d.box[0] * s), int(oy + d.box[1] * s), int(ox + d.box[2] * s), int(oy + d.box[3] * s))
        col = conf_colour(d.conf)
        cv2.rectangle(img, (x1, y1), (x2, y2), col, 2 if solid else 1)
        if labels:
            t = f"{d.cls} {d.conf:.2f}"
            fs = 0.5 * sc
            w, h, _ = tsize(t, fs)
            ty = y1 - 5 if y1 - h - 8 > 0 else y1 + h + 6
            tx = max(0, min(x1, img.shape[1] - w - 2))
            text(img, t, (tx, ty), fs, col)


# ----------------------------------------------------------------------------- game state
@dataclass
class Game:
    stage: int = 0
    thr: float = 0.50
    blur: bool = True
    answers: dict = field(default_factory=dict)   # stage -> dict(guess, truth, points, verdict, why)
    snaps: dict = field(default_factory=dict)     # stage -> frozen data dict (memory only)
    visited: set = field(default_factory=lambda: {0})

    @property
    def score(self):
        return sum(a["points"] for a in self.answers.values())

    def go(self, d):
        self.stage = max(0, min(N_STAGES - 1, self.stage + d))
        self.visited.add(self.stage)

    def restart(self):
        self.stage, self.thr = 0, 0.50
        self.answers.clear()
        self.snaps.clear()
        self.visited = {0}

    def adjust(self, d):
        if self.stage == 3:
            self.thr = round(min(0.95, max(0.05, self.thr + d)), 2)

    def answer(self, digit, D, a_conf):
        """Lock in a quiz answer using the data the player was looking at. Returns the record or None."""
        s = self.stage
        if s not in QUESTION_STAGES or s in self.answers or D is None:
            return None
        if s == 2:
            n = len(D["cand"])
            truth = candidate_bucket(n)
            why = (f"{n} candidates ({truth} x 5). conf 0.01 lets almost every guess through and iou 0.95 stops NMS "
                   f"merging, so one object yields many near-duplicates." + (" (capped at 300)" if n >= MAX_DET else ""))
        elif s == 3:
            n = len(D["cand"])
            k = count_at(D["cand"], Q_THRESHOLD)
            truth = clamp_digit(k)
            why = f"{k} of {n} candidates have confidence >= {Q_THRESHOLD:.2f}; the rest are weak guesses."
        else:
            hi, lo = len(D["hi"]), len(D["lo"])
            truth = clamp_digit(lo)
            why = (f"NMS (iou {NMS_IOU}) cut {hi} boxes to {lo} at conf {a_conf:.2f}: a box that overlaps a "
                   f"higher-scoring one by more than {int(NMS_IOU * 100)}% is dropped.")
        pts, verdict = score_answer(digit, truth)
        rec = dict(guess=digit, truth=truth, points=pts, verdict=verdict, why=why)
        self.answers[s] = rec
        self.snaps[s] = D
        return rec


def verdict_colour(v):
    return {"correct": C_OK, "close": C_CLOSE}.get(v, C_BAD)


# ----------------------------------------------------------------------------- rendering
def draw_topbar(canvas, g, sc, h):
    W = canvas.shape[1]
    canvas[:h] = C_BAR
    title = f"STAGE {g.stage + 1}/{N_STAGES}  {STAGES[g.stage][0]}"
    ts = 0.7 * sc
    text(canvas, title, (int(12 * sc), h // 2 + tsize(title, ts, 2)[1] // 2), ts, C_TXT, 2)
    score = f"SCORE {g.score}/{MAX_SCORE}"
    ss = 0.65 * sc
    sw = tsize(score, ss, 2)[0]
    text(canvas, score, (W - sw - int(12 * sc), h // 2 + tsize(score, ss, 2)[1] // 2), ss, C_OK if g.score else C_TXT, 2)
    # progress boxes: one per stage; question stages get a verdict-coloured tick once answered
    b = int(20 * sc)
    gap = int(8 * sc)
    x = W - sw - int(30 * sc) - N_STAGES * (b + gap)
    y = (h - b) // 2
    for i in range(N_STAGES):
        a = g.answers.get(i)
        x0 = x + i * (b + gap)
        if a:
            col = verdict_colour(a["verdict"])
            cv2.rectangle(canvas, (x0, y), (x0 + b, y + b), col, -1)
            cv2.polylines(canvas, [np.array([[x0 + b * .2, y + b * .55], [x0 + b * .42, y + b * .76], [x0 + b * .8, y + b * .25]], np.int32)],
                          False, (0, 0, 0), 2, cv2.LINE_AA)
        elif i in g.visited and i not in QUESTION_STAGES:
            cv2.rectangle(canvas, (x0, y), (x0 + b, y + b), (120, 120, 120), -1)
        else:
            cv2.rectangle(canvas, (x0, y), (x0 + b, y + b), (110, 110, 110), 1)
        if i == g.stage:
            cv2.rectangle(canvas, (x0 - 3, y - 3), (x0 + b + 3, y + b + 3), C_ACC, 2)


def bottom_lines(g, sc, max_w, extra):
    """-> list of (text, colour, size) for the caption/question panel."""
    cap_s = 0.58 * sc
    rows = [(ln, C_TXT, cap_s) for ln in wrap(STAGES[g.stage][1], max_w, cap_s)]
    if extra:
        rows += [(ln, C_DIM, 0.46 * sc) for ln in wrap(extra, max_w, 0.46 * sc)]
    s = g.stage
    if s in QUESTION_STAGES:
        a = g.answers.get(s)
        if a:
            col = verdict_colour(a["verdict"])
            head = f"{a['verdict'].upper()}  you said {a['guess']}, answer {a['truth']}   +{a['points']} pts"
            rows.append((head, col, 0.62 * sc))
            rows += [(ln, C_DIM, 0.5 * sc) for ln in wrap("Why: " + a["why"], max_w, 0.5 * sc)]
        else:
            rows.append(("QUESTION  " + QUESTIONS[s] + "   (s = skip)", C_ACC, 0.62 * sc))
    return rows


KEYS = "n next   p prev   r restart   + / - threshold (stage 4)   v blur people   q quit"


def render(g, D, a, sim, meter, device, W=1100, H=720, hud_info=None):
    """Compose one full window image from game state + this frame's data D."""
    sc = max(0.6, min(1.4, W / 1100))
    canvas = np.zeros((H, W, 3), np.uint8)
    pad = int(10 * sc)
    top_h = int(46 * sc)
    frame = D["frame"]
    fh, fw = frame.shape[:2]
    s = g.stage
    extra = ""
    if s == 1:
        extra = ("Note: Ultralytics' PyTorch path trims the grey padding to a multiple of 32 (same scale); "
                 "fixed-shape / NPU exports use the full square shown here.")
    rows = bottom_lines(g, sc, W - 2 * pad, extra)
    key_h = tsize(KEYS, 0.45 * sc)[1] + int(10 * sc)
    bot_h = sum(tsize(t, f)[1] + int(8 * sc) for t, _, f in rows) + 2 * pad + key_h
    ch_top, ch_h = top_h, max(60, H - top_h - bot_h)
    cw = W
    content = np.full((ch_h, cw, 3), 18, np.uint8)
    a_rec = g.answers.get(s)
    revealed = a_rec is not None or s not in QUESTION_STAGES
    note = ""

    if s == 0:
        im, ox, oy, k = fit(frame, cw, ch_h)
        content[oy:oy + im.shape[0], ox:ox + im.shape[1]] = im
        chip(content, [(f"Frame {fw}x{fh} pixels", C_ACC, 1.3), ("RAW VIEW - nothing is saved", C_DIM, 1.0)], pad, pad, sc)
        note = f"frame {fw}x{fh}"
    elif s == 1:
        size = a.imgsz
        half = cw // 2
        left, lx, ly, _ = fit(frame, half - 2 * pad, ch_h - 4 * pad)
        content[2 * pad + ly:2 * pad + ly + left.shape[0], pad + lx:pad + lx + left.shape[1]] = left
        lb = letterbox_image(frame, size)
        right, rx, ry, k = fit(lb, half - 2 * pad, ch_h - 4 * pad)
        px0, py0 = half + pad + rx, 2 * pad + ry
        content[py0:py0 + right.shape[0], px0:px0 + right.shape[1]] = right
        cv2.rectangle(content, (px0, py0), (px0 + right.shape[1] - 1, py0 + right.shape[0] - 1), C_ACC, 1)
        p = letterbox_params(fw, fh, size)
        for lab, bar_h in (("grey padding", p["pad_y"] * k), ):
            if p["pad_y"] > 0 and tsize(lab, 0.45 * sc)[1] + 6 < bar_h:
                text(content, lab, (px0 + 6, py0 + int(bar_h / 2) + 5), 0.45 * sc, (30, 30, 30))
                text(content, lab, (px0 + 6, py0 + right.shape[0] - int(bar_h / 2) + 5), 0.45 * sc, (30, 30, 30))
            elif p["pad_x"] > 0 and tsize(lab, 0.45 * sc)[0] + 6 < p["pad_x"] * k:
                text(content, "pad", (px0 + 4, py0 + right.shape[0] // 2), 0.45 * sc, (30, 30, 30))
        text(content, f"camera frame {fw}x{fh}", (pad + lx, pad + int(12 * sc)), 0.5 * sc, C_DIM)
        text(content, f"model input {size}x{size}", (half + pad + rx, pad + int(12 * sc)), 0.5 * sc, C_DIM)
        mid = (half, ch_h // 2)
        cv2.arrowedLine(content, (mid[0] - 22, mid[1]), (mid[0] + 22, mid[1]), C_ACC, 2, cv2.LINE_AA, tipLength=0.4)
        lt = letterbox_text(fw, fh, size)
        chip(content, [(lt, C_OK, 1.3)], cw // 2 - tsize(lt, 0.65 * sc)[0] // 2 - pad, ch_h - int(44 * sc), sc)
        note = lt
    else:
        base = frame.copy()
        persons = [d for d in (D.get("cand") or D.get("lo") or D.get("fin") or []) if d.cls == "person" and d.conf >= max(0.3, a.conf)]
        if g.blur and persons:
            blur_boxes(base, [d.box for d in persons])
        if s in (2, 3, 4) and not revealed:
            im, ox, oy, k = fit(base, cw, ch_h)
            content[oy:oy + im.shape[0], ox:ox + im.shape[1]] = im
            chip(content, [("Make your guess below - the answer is revealed after you press 1-9", C_ACC, 1.1)], pad, pad, sc)
            note = "awaiting answer"
        elif s == 2:
            im, ox, oy, k = fit(base, cw, ch_h)
            content[oy:oy + im.shape[0], ox:ox + im.shape[1]] = im
            ov = content.copy()
            draw_boxes(ov, D["cand"], (ox, oy, k), labels=False, solid=False)
            cv2.addWeighted(ov, 0.6, content, 0.4, 0, dst=content)
            cap = " (capped at 300)" if len(D["cand"]) >= MAX_DET else ""
            chip(content, [(f"{len(D['cand'])} candidate boxes{cap}", C_ACC, 1.4),
                           (f"MINIMALLY FILTERED OUTPUT: conf {CAND_CONF}, NMS iou {CAND_IOU}", C_CLOSE, 0.95),
                           ("Not the raw detection-head tensor", C_DIM, 0.9)], pad, pad, sc)
            note = f"{len(D['cand'])} candidates"
        elif s == 3:
            im, ox, oy, k = fit(base, cw, ch_h)
            content[oy:oy + im.shape[0], ox:ox + im.shape[1]] = im
            keep = [d for d in D["cand"] if d.conf >= g.thr]
            draw_boxes(content, keep, (ox, oy, k), labels=len(keep) <= 12, sc=sc)
            chip(content, [(f"threshold {g.thr:.2f} -> {len(keep)} of {len(D['cand'])} candidates survive", C_ACC, 1.2),
                           ("+ / - moves the dial (step 0.05).  Precision <-> recall", C_DIM, 0.9)], pad, pad, sc)
            note = f"thr {g.thr:.2f}: {len(keep)}/{len(D['cand'])}"
        elif s == 4:
            half = cw // 2
            for i, (key, name, iou_) in enumerate((("hi", "iou 0.95 - duplicates kept", CAND_IOU), ("lo", "iou 0.45 - merged", NMS_IOU))):
                im, ox, oy, k = fit(base, half - 2 * pad, ch_h - 4 * pad)
                x0, y0 = i * half + pad + ox, 3 * pad + oy
                content[y0:y0 + im.shape[0], x0:x0 + im.shape[1]] = im
                sub = content[y0:y0 + im.shape[0], x0:x0 + im.shape[1]].copy()
                draw_boxes(sub, D[key], (0, 0, k), labels=len(D[key]) <= 10, sc=sc * 0.9)
                content[y0:y0 + im.shape[0], x0:x0 + im.shape[1]] = sub
                chip(content, [(f"{name}", C_ACC, 1.0), (f"{len(D[key])} boxes (conf >= {a.conf:.2f})", C_OK if i else C_CLOSE, 1.1)],
                     x0 + 4, y0 + 4, sc)
            note = f"iou0.95: {len(D['hi'])} boxes, iou0.45: {len(D['lo'])} boxes"
        else:
            im, ox, oy, k = fit(base, cw, ch_h)
            content[oy:oy + im.shape[0], ox:ox + im.shape[1]] = im
            draw_boxes(content, D["fin"], (ox, oy, k), labels=True, sc=sc)
            note = f"{len(D['fin'])} detections"
            if hud_info is not None:
                rows_h, ok = hud_rows(meter, hud_info["model"], device, a.imgsz,
                                      [("Detections", len(D["fin"]), None)], sim, f"camera {a.source}")
                tmp = content.copy()
                hud(tmp, rows_h, ok)
                content = tmp
            tot = g.score
            pts = {k_: v["points"] for k_, v in g.answers.items()}
            unans = [str(i + 1) for i in QUESTION_STAGES if i not in g.answers]
            card = [("END CARD", C_ACC, 1.1), (f"Total score {tot} / {MAX_SCORE}", C_OK if tot >= 250 else C_CLOSE, 1.5),
                    (grade(tot, pts), C_TXT, 1.05)]
            if unans:
                card.append((f"Unanswered: stage {', '.join(unans)} (go back with p)", C_DIM, 0.85))
            chip(content, card, cw - pad, pad, sc, anchor="tr", max_w=int(cw * 0.4))
    if sim and s >= 2:
        chip(content, [("SIMULATED scene - model is real, scene is synthetic", C_CLOSE, 0.85)], pad, ch_h - int(34 * sc), sc)
    canvas[ch_top:ch_top + ch_h] = content[:ch_h, :cw]

    draw_topbar(canvas, g, sc, top_h)
    by = ch_top + ch_h
    shade(canvas, 0, by, W, H, None, 0.3)
    cv2.line(canvas, (0, by), (W, by), (90, 90, 90), 1)
    y = by + pad
    for t, col, f in rows:
        y += tsize(t, f)[1] + int(8 * sc)
        text(canvas, t, (pad, y - int(4 * sc)), f, col, 2 if f >= 0.6 * sc else 1)
    text(canvas, KEYS, (pad, H - int(8 * sc)), 0.45 * sc, C_DIM)
    return canvas, note


# ----------------------------------------------------------------------------- main loop
def run_yolo(det, frame, conf, iou, imgsz):
    r = det.model.predict(frame, conf=conf, iou=iou, imgsz=imgsz, device=det.device, verbose=False, max_det=MAX_DET)[0]
    out = []
    if r.boxes is not None:
        names = r.names
        for b, c, k in zip(r.boxes.xyxy.cpu().numpy(), r.boxes.cls.int().cpu().tolist(), r.boxes.conf.cpu().tolist()):
            out.append(Det(names.get(c, str(c)), tuple(int(v) for v in b), float(k)))
    return out


def gather(g, det, frame, a, meter):
    """Run exactly the inference the current stage needs (frozen stages reuse their snapshot)."""
    snap = g.snaps.get(g.stage)
    if snap is not None:
        meter.last_ran = False
        return snap
    D = dict(frame=frame, cand=None, hi=None, lo=None, fin=None)
    meter.last_ran = False
    if det is None:
        return D
    s = g.stage
    if s in (2, 3):
        D["cand"] = run_yolo(det, frame, CAND_CONF, CAND_IOU, a.imgsz)
    elif s == 4:
        D["hi"] = run_yolo(det, frame, a.conf, CAND_IOU, a.imgsz)
        D["lo"] = run_yolo(det, frame, a.conf, NMS_IOU, a.imgsz)
    elif s == 5:
        t = time.perf_counter()
        D["fin"] = run_yolo(det, frame, a.conf, NMS_IOU, a.imgsz)
        meter.add((time.perf_counter() - t) * 1000)  # a real forward pass + NMS ran
        meter.last_ran = True
    return D


def snapshot(D):
    """Freeze this frame's data for a stage (memory only)."""
    d = dict(D)
    d["frame"] = D["frame"].copy()
    return d


def main(argv=None):
    ap = argparse.ArgumentParser(description="Edge AI lab: gamified explainer of the detection pipeline")
    ap.add_argument("--source", default="0", help="camera index (default 0) or MJPEG/RTSP URL or video file")
    ap.add_argument("--simulate", action="store_true", help="synthetic scene instead of a camera (YOLO still runs)")
    ap.add_argument("--rotate", type=int, default=0)
    ap.add_argument("--conf", type=float, default=0.35, help="confidence for the NMS/RESULT stages")
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument("--device", default=None)
    ap.add_argument("--model", default="yolov8n.pt")
    ap.add_argument("--duration", type=float, default=0, help="stop after N seconds (0 = until q)")
    ap.add_argument("--headless", action="store_true", help="no GUI; auto-plays all six stages and prints a summary")
    a = ap.parse_args(argv)

    det = ObjectDetector(a.model, conf=a.conf, imgsz=a.imgsz, device=a.device)
    run_yolo(det, np.zeros((480, 640, 3), np.uint8), a.conf, NMS_IOU, a.imgsz)  # warm-up, not recorded
    device = det.device

    sim, src = a.simulate, None
    if sim:
        from storesmart.sim.people_sim import PeopleSimulator
        psim = PeopleSimulator()
    else:
        from storesmart.common.video import FrameSource
        src = FrameSource(int(a.source) if a.source.isdigit() else a.source, rotate=a.rotate)
        if not src.connected:
            print(f"ERROR: {src.last_error}")
            src.release()
            return 2

    g, meter = Game(), PerfMeter()
    gui = not a.headless
    hud_info = dict(model=f"{a.model} (YOLOv8 detect)")
    notes, shown, t_stage = {}, {i: 0 for i in range(N_STAGES)}, {i: 0.0 for i in range(N_STAGES)}
    if gui:
        cv2.namedWindow(WIN, cv2.WINDOW_NORMAL)
        cv2.resizeWindow(WIN, 1100, 720)
    dwell = (a.duration / N_STAGES) if (not gui and a.duration) else 1.5
    t0 = last = stage_t0 = time.perf_counter()
    last_frame, answered_headless = None, False
    try:
        while True:
            now = time.perf_counter()
            if a.duration and now - t0 >= a.duration:
                break
            dt, last = now - last, now
            if sim:
                frame, _ = psim.step(min(max(dt, 0.03), 0.2))
            else:
                frame = src.read()
                if frame is None:
                    frame = last_frame
                    if frame is None:
                        time.sleep(0.01)
                        if gui and (cv2.waitKey(1) & 0xFF) == ord("q"):
                            break
                        continue
            last_frame = frame
            D = gather(g, det, frame, a, meter)
            if g.stage == 5:
                meter.tick()
            canvas, note = render(g, D, a, sim, meter, device, hud_info=hud_info)
            notes[g.stage] = note
            shown[g.stage] += 1
            t_stage[g.stage] += dt
            key = -1
            if gui:
                cv2.imshow(WIN, canvas)
                key = cv2.waitKey(1) & 0xFF
            else:  # scripted play-through: answer '3' on each question, then advance
                el = now - stage_t0
                if g.stage in QUESTION_STAGES and g.stage not in g.answers and el > dwell * 0.4:
                    key = ord("3")
                elif el > dwell and not (g.stage == N_STAGES - 1):
                    key = ord("n")
                elif el > dwell and not a.duration:
                    break
            if key in (-1, 255):
                continue
            ch = chr(key) if 0 <= key < 128 else ""
            if ch == "q":
                break
            elif ch == "n":
                g.go(1)
            elif ch == "p":
                g.go(-1)
            elif ch == "r":
                g.restart()
            elif ch in "+=":
                g.adjust(0.05)
            elif ch in "-_":
                g.adjust(-0.05)
            elif ch == "v":
                g.blur = not g.blur
            elif ch == "s" and g.stage in QUESTION_STAGES and g.stage not in g.answers:
                g.answers[g.stage] = dict(guess=0, truth=0, points=0, verdict="wrong", why="Skipped.")
                g.snaps[g.stage] = snapshot(D)
            elif ch.isdigit() and ch != "0":
                g.answer(int(ch), snapshot(D), a.conf)
            if ch in "npr":
                stage_t0 = time.perf_counter()
    finally:
        if src is not None:
            src.release()
        if gui:
            cv2.destroyAllWindows()

    print(f"[explain] device={device} imgsz={a.imgsz} conf={a.conf} source={'SIMULATED' if sim else a.source}")
    for i, (title, _) in enumerate(STAGES):
        ans = g.answers.get(i)
        q = f" | guess={ans['guess']} truth={ans['truth']} {ans['verdict']} +{ans['points']}" if ans else ""
        print(f"  stage {i + 1} {title:<10} frames={shown[i]:<4} {notes.get(i, '-')}{q}")
    if meter.has_data:
        print(f"[explain] stage-6 inference mean={meter.inference_ms:.1f}ms p95={meter.p95_ms:.1f}ms "
              f"inferences={meter.inferences} fps={meter.fps:.1f}")
    else:
        print("[explain] inference=NONE recorded (stage 6 never reached) - no timing claimed")
    pts = {k: v["points"] for k, v in g.answers.items()}
    print(f"[explain] score={g.score}/{MAX_SCORE} - {grade(g.score, pts)}")


if __name__ == "__main__":
    raise SystemExit(main() or 0)
