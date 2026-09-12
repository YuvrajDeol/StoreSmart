"""Rectangle-based doorway entry/exit counter: an alternative to the
line-crossing EntryExitCounter for doorways where a clean crossing line is
awkward (narrow frame, angled camera, etc).

You draw one rectangle over the doorway. A track whose foot point moves from
outside the rectangle to inside it counts as an entry; moving from inside to
outside counts as an exit. A track first seen already inside the rectangle
is not counted until it actually crosses in or out, so someone standing in
frame at startup doesn't get miscounted.
"""
from __future__ import annotations

from storesmart.common.bus import EventBus
from storesmart.common.config import load_json, save_json
from storesmart.common.geometry import point_in_rect
from storesmart.phase1_footfall.group_size import GroupSizeEstimator
from storesmart.phase1_footfall.track_relink import TrackRelinker

DEFAULT_PATH = "config/doorway.json"
EXAMPLE_PATH = "config/doorway.example.json"


class DoorwayCounter:
    def __init__(self, rect: dict, in_label: str = "Inside", out_label: str = "Outside",
                 lost_after: float = 1.5, cam: str = "entrance",
                 initial_inside: int = 0, max_group_size: int = 4,
                 relink_window_s: float = 3.0, relink_max_px: float = 80):
        self.rect = rect  # pixel-space {x, y, w, h}
        self.in_label = in_label
        self.out_label = out_label
        self.lost_after = lost_after
        self.cam = cam
        self.initial_inside = initial_inside
        self._inside_rect: dict[int, bool] = {}
        self.last_seen: dict[int, float] = {}
        self.last_position: dict[int, tuple[float, float]] = {}
        self.entries = 0
        self.exits = 0
        self._group_estimator = GroupSizeEstimator(max_group_size=max_group_size)
        self._relinker = TrackRelinker(window_s=relink_window_s, max_px=relink_max_px)

    def update(self, tracks: list[tuple[int, tuple[int, int, int, int]]], now: float, bus: EventBus) -> None:
        for tid, (x1, y1, x2, y2) in tracks:
            foot = ((x1 + x2) / 2, y2)
            self.last_seen[tid] = now
            self.last_position[tid] = foot
            is_inside = point_in_rect(self.rect, foot)
            was_inside = self._inside_rect.get(tid)
            if was_inside is None:
                was_inside = self._relinker.try_relink(foot, now)
            if was_inside is None:
                self._inside_rect[tid] = is_inside
                continue
            if is_inside and not was_inside:
                group_size = self._group_estimator.estimate(x2 - x1)
                self.entries += group_size
                for _ in range(group_size):
                    bus.emit({"cam": self.cam, "type": "entry"})
            elif was_inside and not is_inside:
                group_size = self._group_estimator.estimate(x2 - x1)
                self.exits += group_size
                for _ in range(group_size):
                    bus.emit({"cam": self.cam, "type": "exit"})
            self._inside_rect[tid] = is_inside

        stale = [t for t, ts in self.last_seen.items() if now - ts > self.lost_after]
        for tid in stale:
            was_inside = self._inside_rect.get(tid)
            pos = self.last_position.get(tid)
            if was_inside is not None and pos is not None:
                self._relinker.remember(was_inside, pos, now)
            self.last_seen.pop(tid, None)
            self._inside_rect.pop(tid, None)
            self.last_position.pop(tid, None)
        self._relinker.prune(now)

    @property
    def inside(self) -> int:
        return max(0, self.initial_inside + self.entries - self.exits)


def load_doorway(path: str = DEFAULT_PATH) -> dict:
    try:
        return load_json(path)
    except FileNotFoundError:
        return load_json(EXAMPLE_PATH)


def save_doorway(data: dict, path: str = DEFAULT_PATH) -> None:
    save_json(path, data)


def scale_rect(rect_norm: dict, w: int, h: int) -> dict:
    """Convert a normalized (0-1) rectangle to pixel coordinates for a frame
    of size (w, h)."""
    return {"x": rect_norm["x"] * w, "y": rect_norm["y"] * h,
            "w": rect_norm["w"] * w, "h": rect_norm["h"] * h}
