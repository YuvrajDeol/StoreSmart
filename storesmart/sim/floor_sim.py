"""Synthetic foot-traffic generator for the floor camera: people wander
between random destinations inside the shop bounds (feet), used by both the
Phase 2 live map and Phase 4 dwell/heatmap when no real floor camera or
calibration is available.

Routes are planned on a walkability grid (see `navigation.py`) so simulated
shoppers walk around shelves and counters instead of straight through them.
"""
from __future__ import annotations

import random
from pathlib import Path

from storesmart.sim.navigation import WalkGrid, advance_along_path, find_door_point

# The simulators run for hours while someone edits the layout in the dashboard.
# Saving there rewrites config/store_map.json, and a long-running simulator has
# to pick that up without being restarted — otherwise the grid silently keeps
# whatever furniture existed when the process launched and dots walk straight
# through everything added since. Checking the file's mtime once a second is
# plenty: it is far faster than anyone can redraw a shelf, and costs one stat().
MAP_RELOAD_INTERVAL_S = 1.0


def _saved_map_mtime():
    """Modification time of the saved store map, or None if there isn't one."""
    try:
        from storesmart.phase2_map.map_model import DEFAULT_PATH

        return Path(DEFAULT_PATH).stat().st_mtime
    except OSError:
        return None
    except Exception:
        return None


def _resolve_rectangles(rectangles):
    """Obstacle rectangles for the grid.

    Callers that already hold a store map should pass its `rectangles`. When
    they don't, the saved map is loaded here so that existing call sites become
    obstacle-aware without every one of them having to change. Falls back to an
    empty (obstacle-free) floor if no map can be read.
    """
    if rectangles is not None:
        return rectangles
    try:
        from storesmart.phase2_map.map_model import load_map

        return load_map().rectangles
    except Exception:
        return []


class _MapSourcedGrid:
    """Keeps a WalkGrid in step with the store map file it came from.

    Only applies when the caller let the simulator load the map itself. If
    rectangles were passed in explicitly the caller owns them, and nothing is
    reloaded behind its back.
    """

    def _init_grid(self, length_ft, breadth_ft, rectangles) -> None:
        self.length_ft = length_ft
        self.breadth_ft = breadth_ft
        self._grid_from_file = rectangles is None
        self._map_mtime = _saved_map_mtime()
        self._next_map_check = MAP_RELOAD_INTERVAL_S
        self.grid = WalkGrid(length_ft, breadth_ft, _resolve_rectangles(rectangles))

    def _reloaded_map(self, clock: float):
        """Reload the map and rebuild the grid if the file changed on disk.

        Returns the freshly loaded StoreMap, or None when nothing changed.
        """
        if not self._grid_from_file or clock < self._next_map_check:
            return None
        self._next_map_check = clock + MAP_RELOAD_INTERVAL_S
        mtime = _saved_map_mtime()
        if mtime == self._map_mtime:
            return None
        self._map_mtime = mtime
        try:
            from storesmart.phase2_map.map_model import load_map

            store_map = load_map()
        except Exception:
            return None
        # Shop size comes from the same file, so it goes stale the same way.
        self.length_ft = store_map.length_ft
        self.breadth_ft = store_map.breadth_ft
        self.grid = WalkGrid(store_map.length_ft, store_map.breadth_ft, store_map.rectangles)
        return store_map

    def _replan(self, people, goal_of) -> None:
        """Re-route everyone on the rebuilt grid.

        Nobody is moved and nobody's destination changes — people keep walking
        from exactly where they are, towards exactly where they were already
        headed; only the route between the two is recomputed so it goes around
        furniture that has just appeared. Someone standing inside a brand-new
        shelf is left alone and simply walks out of it on the way to the same
        place, which is what "carry on as normal" should look like.
        """
        for p in people:
            goal = goal_of(p)
            if goal is None:
                continue
            p["path"] = self.grid.path((p["x"], p["y"]), goal)


class FloorSimulator(_MapSourcedGrid):
    def __init__(self, length_ft: float, breadth_ft: float, n_people: int = 4,
                 seed: int = 11, rectangles=None):
        self._init_grid(length_ft, breadth_ft, rectangles)
        self._clock = 0.0
        random.seed(seed)
        self.people = [self._spawn(i) for i in range(n_people)]
        self.next_id = n_people

    def _spawn(self, track_id: int) -> dict:
        start = self.grid.random_point(random)
        return {
            "id": track_id,
            "x": start[0],
            "y": start[1],
            # Waypoints still to walk. Empty means "pick a new destination".
            "path": self.grid.path(start, self.grid.random_point(random)),
            "v": random.uniform(1.5, 3.0),  # ft/s, roughly walking pace
        }

    def step(self, dt: float) -> list[tuple[int, float, float]]:
        """Advance all tracks by dt seconds. Returns [(track_id, x_ft, y_ft)]."""
        self._clock += dt
        if self._reloaded_map(self._clock) is not None:
            self._replan(self.people, lambda p: p["path"][-1] if p["path"] else None)
        out = []
        for p in self.people:
            if not p["path"]:
                # Arrived last tick — browse for a beat, then head somewhere new.
                p["path"] = self.grid.path((p["x"], p["y"]), self.grid.random_point(random))
            (p["x"], p["y"]), p["path"] = advance_along_path(
                (p["x"], p["y"]), p["path"], p["v"] * dt
            )
            out.append((p["id"], round(p["x"], 2), round(p["y"], 2)))
        return out


class DoorFloorSimulator(_MapSourcedGrid):
    """Floor population whose size is driven from outside — by Phase 1's
    entry/exit events on the shared bus — rather than a fixed headcount.

    People appear at a door, wander between random destinations with the same
    walk as `FloorSimulator`, and on exit walk back to the door they came in
    through before being removed, so a departure reads as someone leaving
    rather than a dot blinking out. Every route is planned around shelves and
    counters.

    Uses its own random.Random rather than seeding the global module, so it
    cannot perturb any other seeded simulator running in the same process.
    """

    # A departing shopper is drawn walking back to the door, but Phase 1 has
    # already counted them out — so while they walk they are a dot that the
    # "Inside" number no longer includes. These two knobs bound that overshoot:
    # departures move faster than browsers, and only a few may be walking out at
    # once (beyond that the extras are treated as already gone). At realistic
    # footfall the cap never binds and every exit is animated in full; under the
    # demo simulator's very fast churn it keeps the dot count close to "Inside"
    # instead of letting leavers pile up indefinitely.
    LEAVE_SPEED_MULT = 2.0
    MAX_LEAVING = 3
    LEAVE_TIMEOUT_S = 4.0

    def __init__(self, length_ft: float, breadth_ft: float,
                 door_point: tuple[float, float], seed: int = 11, rectangles=None):
        self._rng = random.Random(seed)
        self._init_grid(length_ft, breadth_ft, rectangles)
        # A door rectangle never blocks the floor, so this is normally the point
        # as given; it only moves if furniture has been drawn over the doorway.
        self.door_point = self.grid.nearest_walkable_point(door_point)
        # Ordered oldest-first, which is what makes FIFO exit matching cheap.
        self.tracks: list[dict] = []
        self.next_id = 1
        self._clock = 0.0

    def spawn(self) -> int:
        """Add one shopper just inside the door. Returns the new track id."""
        dx, dy = self.door_point
        start = self.grid.nearest_walkable_point(
            (dx + self._rng.uniform(-1, 1), dy + self._rng.uniform(-1, 1))
        )
        track_id = self.next_id
        self.next_id += 1
        self.tracks.append({
            "id": track_id,
            "x": start[0],
            "y": start[1],
            "path": self.grid.path(start, self.grid.random_point(self._rng)),
            "v": self._rng.uniform(1.5, 3.0),  # ft/s, roughly walking pace
            "leaving": False,
        })
        return track_id

    def begin_exit(self) -> int | None:
        """Send the oldest still-shopping track back to the door.

        FIFO ASSUMPTION: `entry`/`exit` events carry no track id (see
        docs/event-contract.md), so there is no way to know *which* shopper a
        given exit belongs to. We treat the longest-present shopper as the one
        leaving, which roughly matches how people actually cycle through a
        shop. It is an approximation for the demo, not a claim about identity —
        and deliberately so: matching a specific exit to a specific person
        would mean re-identification, which CLAUDE.md forbids.
        """
        for track in self.tracks:
            if not track["leaving"]:
                track["leaving"] = True
                track["path"] = self.grid.path((track["x"], track["y"]), self.door_point)
                track["deadline"] = self._clock + self.LEAVE_TIMEOUT_S
                return track["id"]
        return None

    def shopping_count(self) -> int:
        """Tracks still inside and not yet heading out — the number that should
        line up with Phase 1's `inside` count."""
        return sum(1 for t in self.tracks if not t["leaving"])

    def step(self, dt: float) -> tuple[list[tuple[int, float, float]], list[int]]:
        """Advance every track by dt seconds.

        Returns ([(track_id, x_ft, y_ft)], [removed_track_ids]) — removed
        tracks are those that reached the door on their way out.
        """
        self._clock += dt
        store_map = self._reloaded_map(self._clock)
        if store_map is not None:
            # The door may have been moved (or drawn over). spawn() and
            # begin_exit() both read self.door_point when they run, so updating
            # it here is enough for every future decision; people already on
            # their way out are redirected to where the door is now rather than
            # walking to where it used to be.
            moved_door, _found = find_door_point(store_map.rectangles, store_map.breadth_ft)
            self.door_point = self.grid.nearest_walkable_point(moved_door)
            self._replan(
                self.tracks,
                lambda p: self.door_point if p["leaving"]
                else (p["path"][-1] if p["path"] else None),
            )

        out: list[tuple[int, float, float]] = []
        removed: list[int] = []
        still_here: list[dict] = []

        # Only MAX_LEAVING departures are animated at a time. Anyone queued
        # behind that (oldest first) is treated as already out of the door.
        leaving = [t for t in self.tracks if t["leaving"]]
        overflow = {t["id"] for t in leaving[:max(len(leaving) - self.MAX_LEAVING, 0)]}

        for p in self.tracks:
            if p["id"] in overflow or (p["leaving"] and self._clock >= p.get("deadline", 0)):
                removed.append(p["id"])
                continue

            if not p["path"]:
                if p["leaving"]:
                    # Reached the door on the way out — stop reporting them.
                    removed.append(p["id"])
                    continue
                p["path"] = self.grid.path((p["x"], p["y"]), self.grid.random_point(self._rng))

            speed = p["v"] * (self.LEAVE_SPEED_MULT if p["leaving"] else 1.0)
            (p["x"], p["y"]), p["path"] = advance_along_path(
                (p["x"], p["y"]), p["path"], speed * dt
            )
            still_here.append(p)
            out.append((p["id"], round(p["x"], 2), round(p["y"], 2)))

        self.tracks = still_here
        return out, removed
