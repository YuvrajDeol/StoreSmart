"""Shelf watch: YOLO object detection over retail-plausible COCO classes, plus
baseline-vs-now matching that notices when an item is taken away.

Frames never leave this module's caller; only (class, box, conf) tuples are used.
Inanimate objects only - people are not detected here.
"""
from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field

# COCO class id -> name. Edit this dict to tune what counts as a "shelf item".
SHELF_CLASSES: dict[int, str] = {
    39: "bottle", 40: "wine glass", 41: "cup", 42: "fork", 43: "knife", 44: "spoon",
    45: "bowl", 46: "banana", 47: "apple", 48: "sandwich", 49: "orange", 50: "broccoli",
    51: "carrot", 53: "pizza", 54: "donut", 55: "cake", 73: "book", 74: "clock",
    75: "vase", 76: "scissors", 77: "teddy bear", 67: "cell phone", 64: "mouse",
    65: "remote", 66: "keyboard",
}


@dataclass
class Det:
    cls: str
    box: tuple[int, int, int, int]
    conf: float = 1.0

    @property
    def centroid(self) -> tuple[float, float]:
        return ((self.box[0] + self.box[2]) / 2, (self.box[1] + self.box[3]) / 2)


@dataclass
class _Item:
    det: Det                 # last known detection (for drawing)
    base_centroid: tuple[float, float]
    state: str = "present"   # present | missing
    streak: int = 0          # consecutive frames contradicting `state`


class ObjectDetector:
    """Plain YOLO detection (no tracking) restricted to SHELF_CLASSES."""

    def __init__(self, model_path="yolov8n.pt", conf=0.35, imgsz=640, device=None):
        from ultralytics import YOLO
        self.model = YOLO(model_path)
        if device is None:
            try:
                import torch
                device = "mps" if torch.backends.mps.is_available() else "cpu"
            except Exception:
                device = "cpu"
        self.device = device
        self.kw = dict(classes=list(SHELF_CLASSES), conf=conf, imgsz=imgsz, verbose=False, device=device)

    def detect(self, frame) -> list[Det]:
        r = self.model.predict(frame, **self.kw)[0]
        out = []
        if r.boxes is not None:
            for b, c, k in zip(r.boxes.xyxy.cpu().numpy(), r.boxes.cls.int().cpu().tolist(),
                               r.boxes.conf.cpu().tolist()):
                out.append(Det(SHELF_CLASSES.get(c, str(c)), tuple(int(v) for v in b), float(k)))
        return out


class ShelfWatcher:
    def __init__(self, frame_width: int = 640, dist_frac: float = 0.12, debounce: int = 5, log_len: int = 6):
        self.max_dist = dist_frac * frame_width
        self.debounce = debounce
        self.items: list[_Item] = []
        self.log: deque[str] = deque(maxlen=log_len)
        self.has_baseline = False

    def set_baseline(self, detections: list[Det]) -> None:
        self.items = [_Item(d, d.centroid) for d in detections]
        self.has_baseline = True
        self.log.append(f"{time.strftime('%H:%M:%S')} baseline set: {len(self.items)} items")

    def _match(self, dets: list[Det]):
        """Greedy nearest match, same class AND centroid within max_dist of the baseline spot."""
        pairs = []
        for i, it in enumerate(self.items):
            for j, d in enumerate(dets):
                if d.cls != it.det.cls:
                    continue
                dist = ((d.centroid[0] - it.base_centroid[0]) ** 2 + (d.centroid[1] - it.base_centroid[1]) ** 2) ** 0.5
                if dist <= self.max_dist:
                    pairs.append((dist, i, j))
        pairs.sort()
        mi, mj = {}, set()
        for _, i, j in pairs:
            if i not in mi and j not in mj:
                mi[i] = j
                mj.add(j)
        return mi, mj

    def update(self, dets: list[Det]):
        """Returns (present, missing, added): present = [Det], missing = [Det last-known],
        added = [Det] not in the baseline.

        DEBOUNCE: YOLO routinely drops a detection for a frame or two (blur, occlusion, conf
        flicker). Reporting TAKEN on a single missed frame would spam false alerts, so an item
        must be unmatched for `debounce` consecutive frames before it is TAKEN, and matched
        for `debounce` consecutive frames before it is RESTORED. Any contradicting frame
        resets the streak.
        """
        mi, mj = self._match(dets)
        stamp = time.strftime("%H:%M:%S")
        present, missing = [], []
        for i, it in enumerate(self.items):
            matched = i in mi
            if matched:
                it.det = dets[mi[i]]
            if it.state == "present":
                it.streak = 0 if matched else it.streak + 1
                if it.streak >= self.debounce:
                    it.state, it.streak = "missing", 0
                    self.log.append(f"{stamp} {it.det.cls} TAKEN")
            else:
                it.streak = it.streak + 1 if matched else 0
                if it.streak >= self.debounce:
                    it.state, it.streak = "present", 0
                    self.log.append(f"{stamp} {it.det.cls} returned")
            (missing if it.state == "missing" else present).append(it.det)
        added = [d for j, d in enumerate(dets) if j not in mj]
        return present, missing, added

    @property
    def baseline_count(self) -> int:
        return len(self.items)
