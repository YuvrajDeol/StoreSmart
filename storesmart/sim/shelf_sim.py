"""Synthetic shelf snapshot generator: a white-backdrop shelf with colored
product blocks whose fill level slowly drains over time (and can be reset by
a simulated refill), so gap detection can be demoed with no phone."""
from __future__ import annotations

import random

import cv2
import numpy as np


class ShelfSimulator:
    def __init__(self, slots: list[dict], w: int = 320, h: int = 240, seed: int = 3):
        self.slots = slots
        self.w, self.h = w, h
        random.seed(seed)
        self.fill = {s["slot"]: random.uniform(0.7, 1.0) for s in slots}
        self.drain_rate = {s["slot"]: random.uniform(0.01, 0.03) for s in slots}

    def refill(self, slot: str) -> None:
        self.fill[slot] = 1.0

    def step(self, dt: float):
        frame = np.full((self.h, self.w, 3), (235, 235, 235), np.uint8)  # white backdrop
        for slot in self.slots:
            name = slot["slot"]
            self.fill[name] = max(0.0, self.fill[name] - self.drain_rate[name] * dt)
            x, y, w, h = slot["x"], slot["y"], slot["w"], slot["h"]
            filled_h = int(h * self.fill[name])
            top = y + (h - filled_h)
            color = (60, 140, 200)
            if filled_h > 0:
                cv2.rectangle(frame, (x + 4, top), (x + w - 4, y + h - 4), color, -1)
            cv2.rectangle(frame, (x, y), (x + w, y + h), (120, 120, 120), 1)
        return frame, []  # no people in this synthetic shelf view
