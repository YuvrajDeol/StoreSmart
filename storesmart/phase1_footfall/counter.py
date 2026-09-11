"""Line-crossing entry/exit counter with a buffer zone against jitter.

`in_from` is the side of the line a person is on *before* they enter — i.e.
the "outside"/away-from-camera side for a typical entrance setup. Which side
that is gets decided once during setup (see run_line_setup in run.py) by
clicking a point on whichever side should count as "outside", or toggled
live with the 'f' key.

Simple hard rule: a track that is confirmed clearly on the outside, then
later confirmed clearly on the inside, is one entry. Confirmed inside, then
confirmed outside, is one exit. "Confirmed" means the foot point is more
than `buffer_px` away from the line on that side — anything within the
buffer band around the line is a no-man's-land that doesn't change the
track's confirmed side, so detector jitter right at the line can't flip the
count back and forth. A crossing only registers once the track has fully
walked through the buffer and out the other side.

Two people crossing shoulder-to-shoulder can merge into a single detection
box — GroupSizeEstimator compares the crossing box's width to the usual
single-person width and counts a wide box as more than one person.

`initial_inside` seeds the inside/outside baseline with however many people
were already in the store when the system started, so someone leaving who
was never seen entering doesn't quietly send the inside count negative
(clamped) or leave it stuck at 0 while OUT keeps climbing.
"""
from __future__ import annotations

from storesmart.common.bus import EventBus
from storesmart.common.config import load_json, save_json
from storesmart.common.geometry import signed_distance
from storesmart.phase1_footfall.group_size import GroupSizeEstimator

DEFAULT_PATH = "config/line.json"
EXAMPLE_PATH = "config/line.example.json"


class EntryExitCounter:
    def __init__(self, line: list[list[float]], in_from: int = 1, buffer_px: float = 40,
                 lost_after: float = 1.5, cam: str = "entrance",
                 in_label: str = "Inside", out_label: str = "Outside",
                 initial_inside: int = 0, max_group_size: int = 4):
        self.line = line
        self.in_from = in_from
        self.buffer_px = buffer_px
        self.lost_after = lost_after
        self.cam = cam
        self.in_label = in_label
        self.out_label = out_label
        self.initial_inside = initial_inside
        self.confirmed_side: dict[int, int] = {}
        self.last_seen: dict[int, float] = {}
        self.entries = 0
        self.exits = 0
        self._group_estimator = GroupSizeEstimator(max_group_size=max_group_size)

    def flip_direction(self) -> None:
        self.in_from = -self.in_from
        self.confirmed_side.clear()

    def update(self, tracks: list[tuple[int, tuple[int, int, int, int]]], now: float, bus: EventBus) -> None:
        for tid, (x1, y1, x2, y2) in tracks:
            foot = ((x1 + x2) / 2, y2)
            self.last_seen[tid] = now
            d = signed_distance(self.line, foot)
            if abs(d) < self.buffer_px:
                continue  # inside the buffer band — not clearly on either side yet
            s = 1 if d > 0 else -1
            prev = self.confirmed_side.get(tid)
            if prev is not None and prev != s:
                group_size = self._group_estimator.estimate(x2 - x1)
                if prev == self.in_from:
                    self.entries += group_size
                    for _ in range(group_size):
                        bus.emit({"cam": self.cam, "type": "entry"})
                else:
                    self.exits += group_size
                    for _ in range(group_size):
                        bus.emit({"cam": self.cam, "type": "exit"})
            self.confirmed_side[tid] = s
        stale = [t for t, ts in self.last_seen.items() if now - ts > self.lost_after]
        for tid in stale:
            self.last_seen.pop(tid, None)
            self.confirmed_side.pop(tid, None)

    @property
    def inside(self) -> int:
        return max(0, self.initial_inside + self.entries - self.exits)


def load_line_config(path: str = DEFAULT_PATH) -> dict:
    try:
        return load_json(path)
    except FileNotFoundError:
        return load_json(EXAMPLE_PATH)


def save_line_config(data: dict, path: str = DEFAULT_PATH) -> None:
    save_json(path, data)
