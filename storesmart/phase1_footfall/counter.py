"""Line-crossing entry/exit counter with a dead-band margin against jitter.

Ported from sanket_demo.py's Analytics class, split into a counter and a
queue analyzer so each has one job.
"""
from __future__ import annotations

from storesmart.common.bus import EventBus
from storesmart.common.geometry import side_of_line


class EntryExitCounter:
    def __init__(self, line: list[list[float]], in_from: int = 1, margin: float = 12,
                 lost_after: float = 1.5, cam: str = "entrance"):
        self.line = line
        self.in_from = in_from
        self.margin = margin
        self.lost_after = lost_after
        self.cam = cam
        self.side: dict[int, int] = {}
        self.last_seen: dict[int, float] = {}
        self.entries = 0
        self.exits = 0

    def flip_direction(self) -> None:
        self.in_from = -self.in_from
        self.side.clear()

    def update(self, tracks: list[tuple[int, tuple[int, int, int, int]]], now: float, bus: EventBus) -> None:
        for tid, (x1, y1, x2, y2) in tracks:
            foot = ((x1 + x2) / 2, y2)
            self.last_seen[tid] = now
            s = side_of_line(self.line, foot, self.margin)
            if s == 0:
                continue
            prev = self.side.get(tid)
            if prev is not None and prev != s:
                if prev == self.in_from:
                    self.entries += 1
                    bus.emit({"cam": self.cam, "type": "entry"})
                else:
                    self.exits += 1
                    bus.emit({"cam": self.cam, "type": "exit"})
            self.side[tid] = s
        stale = [t for t, ts in self.last_seen.items() if now - ts > self.lost_after]
        for tid in stale:
            self.last_seen.pop(tid, None)
            self.side.pop(tid, None)

    @property
    def inside(self) -> int:
        return max(0, self.entries - self.exits)
