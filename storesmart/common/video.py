"""Video input: threaded "latest frame" readers for live streams, a snapshot
poller for shelf cameras, and a simulate mode. Frames live in memory only and
are never written to disk from this module.
"""
from __future__ import annotations

import os
import threading
import time
from typing import Optional

import cv2
import numpy as np
import requests


class FrameSource:
    """Live streams: a background thread always holds only the newest frame,
    so processing never falls behind (no buffer build-up). Video files are
    read frame by frame instead. Reconnects automatically on failure."""

    def __init__(self, src, proc_width: int = 960, reconnect_delay: float = 2.0):
        self.src = src
        self.proc_width = proc_width
        self.reconnect_delay = reconnect_delay
        self.is_file = isinstance(src, str) and os.path.isfile(src)
        self.frame: Optional[np.ndarray] = None
        self.running = True
        self.connected = False
        self.last_error: Optional[str] = None
        self._lock = threading.Lock()
        self.cap = self._open()
        if not self.is_file:
            threading.Thread(target=self._loop, daemon=True).start()

    def _open(self):
        cap = cv2.VideoCapture(int(self.src) if str(self.src).isdigit() else self.src)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        self.connected = cap.isOpened()
        if not self.connected:
            self.last_error = f"cannot reach camera at {self.src} — check the hotspot / URL"
        return cap

    def _resize(self, frame: np.ndarray) -> np.ndarray:
        h, w = frame.shape[:2]
        if w > self.proc_width:
            frame = cv2.resize(frame, (self.proc_width, int(h * self.proc_width / w)))
        return frame

    def _loop(self) -> None:
        while self.running:
            if not self.cap.isOpened():
                time.sleep(self.reconnect_delay)
                self.cap.release()
                self.cap = self._open()
                continue
            ok, frame = self.cap.read()
            if not ok:
                self.connected = False
                self.last_error = f"lost connection to {self.src}, reconnecting..."
                time.sleep(self.reconnect_delay)
                self.cap.release()
                self.cap = self._open()
                continue
            self.connected = True
            with self._lock:
                self.frame = self._resize(frame)

    def read(self) -> Optional[np.ndarray]:
        if self.is_file:
            ok, frame = self.cap.read()
            return self._resize(frame) if ok else None
        with self._lock:
            return None if self.frame is None else self.frame.copy()

    def release(self) -> None:
        self.running = False
        self.cap.release()


class SnapshotPoller:
    """Polls a still-image URL (e.g. IP Webcam's /shot.jpg) every `interval_s`
    seconds on a background thread. Used for the shelf camera, where a full
    video stream isn't needed."""

    def __init__(self, url: str, interval_s: float = 3.0, timeout_s: float = 5.0):
        self.url = url
        self.interval_s = interval_s
        self.timeout_s = timeout_s
        self.frame: Optional[np.ndarray] = None
        self.last_error: Optional[str] = None
        self.running = True
        self._lock = threading.Lock()
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self) -> None:
        while self.running:
            try:
                resp = requests.get(self.url, timeout=self.timeout_s)
                resp.raise_for_status()
                arr = np.frombuffer(resp.content, dtype=np.uint8)
                frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                if frame is not None:
                    with self._lock:
                        self.frame = frame
                    self.last_error = None
            except Exception as exc:  # network hiccup, phone asleep, wrong URL
                self.last_error = f"cannot reach shelf camera at {self.url} — {exc}"
            time.sleep(self.interval_s)

    def read(self) -> Optional[np.ndarray]:
        with self._lock:
            return None if self.frame is None else self.frame.copy()

    def stop(self) -> None:
        self.running = False


def open_source(cam_cfg: dict, proc_width: int = 960):
    """Build the right reader for a camera config entry from cameras.yaml."""
    url = cam_cfg.get("url", "simulate")
    if url == "simulate":
        return None
    return FrameSource(url, proc_width=proc_width)
