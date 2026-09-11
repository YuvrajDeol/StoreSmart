"""Synthetic store simulator for Phase 1: shoppers enter, browse, queue, get
served, and leave. Arrivals surge mid-cycle so the queue/forecast alert can be
demonstrated with no camera or phone at all.

Ported from sanket_demo.py, renamed and adapted to emit foot-point tracks the
same way a real tracker would (track_id, bbox).
"""
from __future__ import annotations

import math
import random

import cv2
import numpy as np


class PeopleSimulator:
    def __init__(self, w: int = 960, h: int = 540, seed: int = 7):
        self.w, self.h = w, h
        self.people: list[dict] = []
        self.queue: list[dict] = []
        self.next_id = 1
        self.servers = 1
        self.t = 0.0
        self.next_arrival = 1.0
        random.seed(seed)

    def geometry(self) -> dict:
        """Normalized (0-1) line/zone geometry, matching the config schema
        used by real cameras."""
        return {
            "line": [[0.25, 0.10], [0.25, 0.92]],
            "queue": [[0.42, 0.38], [0.74, 0.38], [0.74, 0.62], [0.42, 0.62]],
            "service": [[0.77, 0.28], [0.93, 0.28], [0.93, 0.72], [0.77, 0.72]],
            "in_from": 1,
        }

    def _rate(self) -> float:
        cycle = self.t % 150
        if cycle < 35:
            return 1 / 7.0
        if cycle < 95:
            return 1 / 3.2
        return 1 / 9.0

    def _queue_slot(self, i: int) -> tuple[float, float]:
        return (self.w * (0.71 - 0.05 * i), self.h * 0.50)

    def _server_pos(self, k: int) -> tuple[float, float]:
        return (self.w * 0.85, self.h * (0.40 + 0.20 * k))

    def step(self, dt: float):
        w, h = self.w, self.h
        self.t += dt
        if self.t >= self.next_arrival:
            self.people.append({
                "id": self.next_id, "x": -0.02 * w, "y": h * random.uniform(0.45, 0.8),
                "state": "enter", "tx": w * random.uniform(0.3, 0.62),
                "ty": h * random.uniform(0.14, 0.30), "v": random.uniform(90, 140), "timer": 0,
            })
            self.next_id += 1
            self.next_arrival = self.t + random.expovariate(self._rate())

        serving = [p for p in self.people if p["state"] == "serving"]
        busy = {p["server"] for p in serving}
        for p in list(self.people):
            if p["state"] == "browse":
                p["timer"] -= dt
                if p["timer"] <= 0:
                    p["state"] = "queue"
                    self.queue.append(p)
            if p["state"] == "queue":
                i = self.queue.index(p)
                p["tx"], p["ty"] = self._queue_slot(i)
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
                    p["state"], p["tx"], p["ty"] = "exit1", w * 0.86, h * 0.86
            elif p["state"] == "exit1" and arrived:
                p["state"], p["tx"], p["ty"] = "exit2", -0.08 * w, h * 0.86
            elif p["state"] == "exit2" and arrived:
                self.people.remove(p)

        frame = np.full((h, w, 3), (38, 38, 42), np.uint8)
        tracks = []
        for p in self.people:
            x, y = int(p["x"]), int(p["y"])
            cv2.rectangle(frame, (x - 14, y - 62), (x + 14, y), (150, 150, 160), -1)
            cv2.circle(frame, (x, y - 74), 12, (170, 170, 180), -1)
            tracks.append((p["id"], (x - 18, y - 88, x + 18, y)))
        return frame, tracks

    @staticmethod
    def _move(p: dict, dt: float) -> bool:
        dx, dy = p["tx"] - p["x"], p["ty"] - p["y"]
        dist = math.hypot(dx, dy)
        step = p["v"] * dt
        if dist <= step:
            p["x"], p["y"] = p["tx"], p["ty"]
            return True
        p["x"] += dx / dist * step
        p["y"] += dy / dist * step
        return False
