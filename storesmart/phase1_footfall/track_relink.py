"""Bridges a track ID that gets dropped and reassigned during a brief
occlusion, using only position and time — never appearance — so a person
who's fleetingly lost right at the doorway (very common: people cluster,
briefly block each other, or the camera hiccups) doesn't generate a bogus
crossing when their new track ID's "first sighting" is treated as an
unrelated, brand-new person starting from scratch.

This is not re-identification in the sense the privacy rules forbid: it
carries forward only the counter's own crossing-state (which side of the
line, or whether inside a rectangle), never any visual/appearance data, and
only within a short time/distance window that a person plausibly could not
have re-crossed the line within.
"""
from __future__ import annotations


class TrackRelinker:
    def __init__(self, window_s: float = 3.0, max_px: float = 80):
        self.window_s = window_s
        self.max_px = max_px
        self._lost: list[dict] = []  # {"state": Any, "pos": (x, y), "time": float}

    def remember(self, state, pos: tuple[float, float], now: float) -> None:
        self._lost.append({"state": state, "pos": pos, "time": now})

    def try_relink(self, pos: tuple[float, float], now: float):
        """Returns the state of a recently-lost track near this position
        (and forgets it), or None if nothing matches."""
        for i, entry in enumerate(self._lost):
            if now - entry["time"] > self.window_s:
                continue
            dx = pos[0] - entry["pos"][0]
            dy = pos[1] - entry["pos"][1]
            if (dx * dx + dy * dy) ** 0.5 <= self.max_px:
                self._lost.pop(i)
                return entry["state"]
        return None

    def prune(self, now: float) -> None:
        self._lost = [e for e in self._lost if now - e["time"] <= self.window_s]
