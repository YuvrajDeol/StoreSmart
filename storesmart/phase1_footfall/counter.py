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

A track that ByteTrack drops and reassigns during a brief occlusion (common
right at a doorway, where people cluster) would otherwise look like a
brand-new person on first sighting — TrackRelinker bridges that gap using
only position and time, so it doesn't fabricate a phantom crossing.
"""
from __future__ import annotations

import math
from collections import deque
from typing import Optional

from storesmart.common.bus import EventBus
from storesmart.common.config import load_json, save_json
from storesmart.common.geometry import signed_distance
from storesmart.phase1_footfall.group_size import GroupSizeEstimator
from storesmart.phase1_footfall.track_relink import TrackRelinker

DEFAULT_PATH = "config/line.json"
EXAMPLE_PATH = "config/line.example.json"


class EntryExitCounter:
    def __init__(self, line: list[list[float]], in_from: int = 1, buffer_px: float = 40,
                 lost_after: float = 1.5, cam: str = "entrance",
                 in_label: str = "Inside", out_label: str = "Outside",
                 initial_inside: int = 0, max_group_size: int = 4,
                 relink_window_s: float = 3.0, relink_max_px: float = 80):
        self.line = line
        self.in_from = in_from
        self.buffer_px = buffer_px
        self.lost_after = lost_after
        self.cam = cam
        self.in_label = in_label
        self.out_label = out_label
        self.initial_inside = initial_inside
        self.relink_window_s = relink_window_s
        self.relink_max_px = relink_max_px
        self.confirmed_side: dict[int, int] = {}
        self.last_seen: dict[int, float] = {}
        self.last_position: dict[int, tuple[float, float]] = {}
        self.entries = 0
        self.exits = 0
        #: Human-readable trail of the last few side changes, for the on-screen
        #: panel — makes "is the geometry registering crossings at all?"
        #: answerable without attaching a debugger mid-demo.
        self.activity: deque[str] = deque(maxlen=6)
        self._group_estimator = GroupSizeEstimator(max_group_size=max_group_size)
        self._relinker = TrackRelinker(window_s=relink_window_s, max_px=relink_max_px)

    def flip_direction(self) -> None:
        self.in_from = -self.in_from
        self.confirmed_side.clear()

    def _inherit_side(self, new_tid: int, foot: tuple[float, float], now: float,
                      current_ids: set[int]) -> Optional[int]:
        """Carry a crossing state over when the tracker swaps a person's ID.

        The replacement ID usually appears in the very next frame, while the
        old one is not stale yet (that takes `lost_after`), so the stale-track
        relinker has nothing to match against at that moment — the crossing
        would be lost. So first look for a track that is still known but has
        just vanished from this frame, near this position.
        """
        best: Optional[tuple[float, int, int]] = None
        for other_tid, side in self.confirmed_side.items():
            if other_tid == new_tid or other_tid in current_ids:
                continue  # still being tracked in its own right
            position = self.last_position.get(other_tid)
            if position is None or now - self.last_seen.get(other_tid, -1e9) > self.relink_window_s:
                continue
            distance = math.hypot(foot[0] - position[0], foot[1] - position[1])
            if distance <= self.relink_max_px and (best is None or distance < best[0]):
                best = (distance, other_tid, side)

        if best is not None:
            _, other_tid, side = best
            self.confirmed_side.pop(other_tid, None)
            self.last_seen.pop(other_tid, None)
            self.last_position.pop(other_tid, None)
            self.activity.append(f"#{other_tid}->#{new_tid} same person")
            return side
        return self._relinker.try_relink(foot, now)

    def update(self, tracks: list[tuple[int, tuple[int, int, int, int]]], now: float, bus: EventBus) -> None:
        current_ids = {tid for tid, _ in tracks}
        for tid, (x1, y1, x2, y2) in tracks:
            foot = ((x1 + x2) / 2, y2)
            self.last_seen[tid] = now
            self.last_position[tid] = foot
            d = signed_distance(self.line, foot)
            if abs(d) < self.buffer_px:
                continue  # inside the buffer band — not clearly on either side yet
            s = 1 if d > 0 else -1
            prev = self.confirmed_side.get(tid)
            if prev is None:
                prev = self._inherit_side(tid, foot, now, current_ids)
                if prev is None:
                    self.activity.append(
                        f"#{tid} first seen {self.in_label if s != self.in_from else self.out_label}")
            if prev is not None and prev != s:
                self.activity.append(
                    f"#{tid} {self.out_label if prev == self.in_from else self.in_label}"
                    f" -> {self.in_label if s != self.in_from else self.out_label}")
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
            side = self.confirmed_side.get(tid)
            pos = self.last_position.get(tid)
            if side is not None and pos is not None:
                self._relinker.remember(side, pos, now)
            self.last_seen.pop(tid, None)
            self.confirmed_side.pop(tid, None)
            self.last_position.pop(tid, None)
        self._relinker.prune(now)

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
