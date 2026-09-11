"""Synthetic foot-traffic generator for the floor camera: people wander
between random waypoints inside the shop bounds (feet), used by both the
Phase 2 live map and Phase 4 dwell/heatmap when no real floor camera or
calibration is available."""
from __future__ import annotations

import random


class FloorSimulator:
    def __init__(self, length_ft: float, breadth_ft: float, n_people: int = 4, seed: int = 11):
        self.length_ft = length_ft
        self.breadth_ft = breadth_ft
        random.seed(seed)
        self.people = [self._spawn(i) for i in range(n_people)]
        self.next_id = n_people

    def _spawn(self, track_id: int) -> dict:
        return {
            "id": track_id,
            "x": random.uniform(1, self.length_ft - 1),
            "y": random.uniform(1, self.breadth_ft - 1),
            "tx": random.uniform(1, self.length_ft - 1),
            "ty": random.uniform(1, self.breadth_ft - 1),
            "v": random.uniform(1.5, 3.0),  # ft/s, roughly walking pace
        }

    def step(self, dt: float) -> list[tuple[int, float, float]]:
        """Advance all tracks by dt seconds. Returns [(track_id, x_ft, y_ft)]."""
        out = []
        for p in self.people:
            dx, dy = p["tx"] - p["x"], p["ty"] - p["y"]
            dist = (dx ** 2 + dy ** 2) ** 0.5
            step = p["v"] * dt
            if dist <= step:
                p["x"], p["y"] = p["tx"], p["ty"]
                p["tx"] = random.uniform(1, self.length_ft - 1)
                p["ty"] = random.uniform(1, self.breadth_ft - 1)
            else:
                p["x"] += dx / dist * step
                p["y"] += dy / dist * step
            out.append((p["id"], round(p["x"], 2), round(p["y"], 2)))
        return out
