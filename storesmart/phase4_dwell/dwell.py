"""Dwell tracking: maps floor positions to zones (Phase 2 shelf/category
rectangles, expanded ~1.5 ft into the aisle) and times how long each track
spends inside a zone, with a 2s enter/exit debounce to avoid flicker at zone
boundaries. Falls back to camera-view zones when there's no calibration."""
from __future__ import annotations

from dataclasses import dataclass, field

from storesmart.common.bus import EventBus
from storesmart.common.geometry import expand_rect, point_in_rect
from storesmart.phase2_map.map_model import StoreMap


# "No zone change is pending." Distinct from None, which is itself a real
# candidate meaning "outside every zone" — conflating the two made a committed
# entry reset candidate_zone to None, so the first sample taken outside the
# zone compared equal to the stale candidate and committed the exit with no
# debounce at all.
_NO_CANDIDATE = object()


@dataclass
class _TrackZoneState:
    zone: str | None = None
    candidate_zone: str | None | object = _NO_CANDIDATE
    candidate_since: float = 0.0
    entered_at: float = 0.0


def build_zones(store_map: StoreMap, expand_ft: float = 1.5) -> dict[str, dict]:
    """One zone per shelf rectangle, expanded into the aisle."""
    zones = {}
    for shelf in store_map.shelves():
        rect = {"x": shelf.x, "y": shelf.y, "w": shelf.w, "h": shelf.h}
        zones[shelf.label] = expand_rect(rect, expand_ft)
    return zones


def classify_visit(dwell_s: float, passing_max_s: float = 3, glance_max_s: float = 10) -> str:
    if dwell_s < passing_max_s:
        return "passing"
    if dwell_s < glance_max_s:
        return "glance"
    return "engaged"


class DwellTracker:
    def __init__(self, zones: dict[str, dict], enter_delay_s: float = 2, exit_delay_s: float = 2):
        self.zones = zones
        self.enter_delay_s = enter_delay_s
        self.exit_delay_s = exit_delay_s
        self._states: dict[int, _TrackZoneState] = {}

    def _zone_at(self, point: tuple[float, float]) -> str | None:
        for name, rect in self.zones.items():
            if point_in_rect(rect, point):
                return name
        return None

    def update(self, track_id: int, point: tuple[float, float], now: float, bus: EventBus) -> None:
        state = self._states.setdefault(track_id, _TrackZoneState())
        current_zone = self._zone_at(point)

        if current_zone == state.zone:
            state.candidate_zone = _NO_CANDIDATE
            return

        if current_zone != state.candidate_zone:
            state.candidate_zone, state.candidate_since = current_zone, now
            return

        delay = self.enter_delay_s if current_zone is not None else self.exit_delay_s
        if now - state.candidate_since < delay:
            return

        # debounce satisfied: commit the zone change
        if state.zone is not None:
            dwell_s = now - state.entered_at
            bus.emit({"cam": "floor", "type": "dwell", "zone": state.zone, "dwell_s": round(dwell_s, 1)})
        state.zone = current_zone
        state.entered_at = now
        state.candidate_zone = _NO_CANDIDATE

    def remove_track(self, track_id: int, now: float, bus: EventBus) -> None:
        state = self._states.pop(track_id, None)
        if state and state.zone is not None:
            dwell_s = now - state.entered_at
            bus.emit({"cam": "floor", "type": "dwell", "zone": state.zone, "dwell_s": round(dwell_s, 1)})
