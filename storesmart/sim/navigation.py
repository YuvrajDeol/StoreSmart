"""Walkable-floor navigation for the synthetic shoppers.

The simulators used to pick a random destination anywhere in the shop and walk
a straight line to it, so dots cut through — and stood inside — shelves. This
module gives them a walkability grid of the store map plus a path finder, so a
simulated route bends around fixed furniture the way a person would.

Only `shelf` and `counter` rectangles block the floor. `door` must stay
walkable (it is the entry/exit point) and `camera` has no floor footprint at
all — it is mounted on a wall or ceiling.

Obstacles use each rectangle's exact x/y/w/h. The zone-expansion margin that
`geometry.expand_rect()` applies for Phase 4's dwell zones is deliberately NOT
used here: those two things measure different things. A dwell zone is padded so
that standing *near* a shelf counts as browsing it; an obstacle is the shelf's
physical footprint, and people are supposed to be able to walk right up to its
edge — that is what browsing looks like.

Safety property this module relies on: cells are blocked if they *overlap* an
obstacle at all, and paths move only between 4-connected neighbours. The
straight segment between two 4-adjacent cell centres stays inside those two
cells, and neither overlaps an obstacle, so no point along a generated route
can land inside one. Diagonal steps would break that guarantee by clipping
corners, which is why they are not allowed.
"""
from __future__ import annotations

import math
from collections import deque
from typing import Iterable, Sequence

# Rectangle types that occupy floor space. Deliberately excludes "door" and
# "camera" — see the module docstring.
BLOCKING_TYPES = ("shelf", "counter")
DEFAULT_CELL_FT = 0.5


class WalkGrid:
    """A coarse walkability grid over the shop floor, in feet."""

    def __init__(self, length_ft: float, breadth_ft: float,
                 rectangles: Iterable, cell_ft: float = DEFAULT_CELL_FT):
        self.length_ft = max(float(length_ft), cell_ft)
        self.breadth_ft = max(float(breadth_ft), cell_ft)
        self.cell_ft = cell_ft
        self.cols = max(1, math.ceil(self.length_ft / cell_ft))
        self.rows = max(1, math.ceil(self.breadth_ft / cell_ft))
        self.blocked = [[False] * self.cols for _ in range(self.rows)]
        self.obstacles = [
            (float(r.x), float(r.y), float(r.w), float(r.h))
            for r in (rectangles or [])
            if getattr(r, "type", None) in BLOCKING_TYPES
        ]
        for x, y, w, h in self.obstacles:
            self._block_rect(x, y, w, h)

    def _block_rect(self, x: float, y: float, w: float, h: float) -> None:
        """Mark every cell whose square overlaps this rectangle.

        A cell that merely touches the rectangle's edge is left walkable, so
        someone can stand flush against a shelf.
        """
        if w <= 0 or h <= 0:
            return
        c0 = max(math.floor(x / self.cell_ft), 0)
        c1 = min(math.ceil((x + w) / self.cell_ft) - 1, self.cols - 1)
        r0 = max(math.floor(y / self.cell_ft), 0)
        r1 = min(math.ceil((y + h) / self.cell_ft) - 1, self.rows - 1)
        for row in range(r0, r1 + 1):
            for col in range(c0, c1 + 1):
                self.blocked[row][col] = True

    # -- cell <-> feet ------------------------------------------------------

    def cell_of(self, point: Sequence[float]) -> tuple[int, int]:
        col = min(max(int(point[0] / self.cell_ft), 0), self.cols - 1)
        row = min(max(int(point[1] / self.cell_ft), 0), self.rows - 1)
        return col, row

    def center_of(self, cell: tuple[int, int]) -> tuple[float, float]:
        col, row = cell
        return ((col + 0.5) * self.cell_ft, (row + 0.5) * self.cell_ft)

    def is_blocked_cell(self, cell: tuple[int, int]) -> bool:
        col, row = cell
        if not (0 <= col < self.cols and 0 <= row < self.rows):
            return True
        return self.blocked[row][col]

    def is_walkable(self, point: Sequence[float]) -> bool:
        return not self.is_blocked_cell(self.cell_of(point))

    def point_in_obstacle(self, point: Sequence[float]) -> bool:
        """True if the point is strictly inside a blocking rectangle. Used by
        the tests/verification rather than by pathing."""
        x, y = point[0], point[1]
        return any(ox < x < ox + w and oy < y < oy + h for ox, oy, w, h in self.obstacles)

    # -- queries ------------------------------------------------------------

    def nearest_walkable_cell(self, cell: tuple[int, int]) -> tuple[int, int] | None:
        """The given cell, or the closest free one by breadth-first spread."""
        if not self.is_blocked_cell(cell):
            return cell
        seen = {cell}
        queue = deque([cell])
        while queue:
            col, row = queue.popleft()
            for nxt in ((col + 1, row), (col - 1, row), (col, row + 1), (col, row - 1)):
                if nxt in seen:
                    continue
                ncol, nrow = nxt
                if not (0 <= ncol < self.cols and 0 <= nrow < self.rows):
                    continue
                seen.add(nxt)
                if not self.blocked[nrow][ncol]:
                    return nxt
                queue.append(nxt)
        return None

    def nearest_walkable_point(self, point: Sequence[float]) -> tuple[float, float]:
        """Snap a point onto walkable floor, leaving it alone if it already is."""
        cell = self.cell_of(point)
        if not self.is_blocked_cell(cell):
            return (float(point[0]), float(point[1]))
        free = self.nearest_walkable_cell(cell)
        return self.center_of(free) if free else (float(point[0]), float(point[1]))

    def random_point(self, rng, max_tries: int = 200) -> tuple[float, float]:
        """A random destination on walkable floor.

        Rejection-samples cells, then jitters inside the chosen cell so people
        do not all line up on exact cell centres. The jitter is safe because a
        free cell overlaps no obstacle anywhere in its square.
        """
        for _ in range(max_tries):
            col = rng.randrange(self.cols)
            row = rng.randrange(self.rows)
            if self.blocked[row][col]:
                continue
            return (
                min((col + rng.random()) * self.cell_ft, self.length_ft),
                min((row + rng.random()) * self.cell_ft, self.breadth_ft),
            )
        # Shop is almost entirely furniture: fall back to any free cell.
        for row in range(self.rows):
            for col in range(self.cols):
                if not self.blocked[row][col]:
                    return self.center_of((col, row))
        return (self.length_ft / 2, self.breadth_ft / 2)

    def path(self, start: Sequence[float], goal: Sequence[float]) -> list[tuple[float, float]]:
        """Waypoints from `start` to `goal` that stay on walkable floor.

        Breadth-first over 4-connected cells — the shop is a few thousand cells,
        so there is no need for anything cleverer than that. Returns a list of
        points in feet ending at `goal`; an empty list means `start` is already
        there. Collinear waypoints are dropped so straight runs stay straight,
        but corners are never cut (that would break the no-clipping guarantee).
        """
        start_cell = self.nearest_walkable_cell(self.cell_of(start))
        goal_cell = self.nearest_walkable_cell(self.cell_of(goal))
        if start_cell is None or goal_cell is None:
            return [(float(goal[0]), float(goal[1]))]

        goal_point = (float(goal[0]), float(goal[1]))
        if self.is_blocked_cell(self.cell_of(goal_point)):
            goal_point = self.center_of(goal_cell)

        if start_cell == goal_cell:
            return [goal_point]

        came_from: dict[tuple[int, int], tuple[int, int] | None] = {start_cell: None}
        queue = deque([start_cell])
        while queue:
            current = queue.popleft()
            if current == goal_cell:
                break
            col, row = current
            for nxt in ((col + 1, row), (col - 1, row), (col, row + 1), (col, row - 1)):
                if nxt in came_from:
                    continue
                ncol, nrow = nxt
                if not (0 <= ncol < self.cols and 0 <= nrow < self.rows):
                    continue
                if self.blocked[nrow][ncol]:
                    continue
                came_from[nxt] = current
                queue.append(nxt)

        if goal_cell not in came_from:
            # Walled off (shouldn't happen in a normal shop) — go straight
            # there rather than freezing the shopper in place.
            return [goal_point]

        cells: list[tuple[int, int]] = []
        node: tuple[int, int] | None = goal_cell
        while node is not None:
            cells.append(node)
            node = came_from[node]
        cells.reverse()

        points = [self.center_of(c) for c in cells]
        points.append(goal_point)
        return _drop_collinear(points)


def find_door_point(rectangles, breadth_ft: float):
    """Centre of the first door rectangle, in feet. Returns (point, found).

    With several doors the first one wins — shoppers all arrive through the
    same entrance, which is the common shop layout and keeps the demo
    readable. With none, falls back to the middle of the left wall so the
    simulation still runs.

    Lives here rather than in the Phase 2 runner because the simulator has to
    re-derive it whenever the map is reloaded: a door that moves in the
    dashboard has to move for spawns and exits too.
    """
    for rect in rectangles or []:
        if getattr(rect, "type", None) == "door":
            return (rect.x + rect.w / 2, rect.y + rect.h / 2), True
    return (0.5, breadth_ft / 2), False


def _drop_collinear(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Remove waypoints that sit on a straight line between their neighbours."""
    if len(points) <= 2:
        return points
    kept = [points[0]]
    for prev, current, nxt in zip(points, points[1:], points[2:]):
        ax, ay = current[0] - prev[0], current[1] - prev[1]
        bx, by = nxt[0] - current[0], nxt[1] - current[1]
        if abs(ax * by - ay * bx) > 1e-9:  # direction changed: it is a corner
            kept.append(current)
    kept.append(points[-1])
    return kept


def advance_along_path(position: Sequence[float], path: Sequence[tuple[float, float]],
                       distance: float):
    """Walk `distance` feet along `path`.

    Returns (new_position, remaining_path). The path is consumed as waypoints
    are reached, so an empty remaining path means the destination was reached
    within this step.
    """
    x, y = float(position[0]), float(position[1])
    remaining = list(path)
    budget = float(distance)
    while remaining and budget > 0:
        tx, ty = remaining[0]
        dx, dy = tx - x, ty - y
        leg = math.hypot(dx, dy)
        if leg <= 1e-9:
            remaining.pop(0)
            continue
        if leg <= budget:
            x, y = tx, ty
            budget -= leg
            remaining.pop(0)
        else:
            x += dx / leg * budget
            y += dy / leg * budget
            budget = 0.0
    return (x, y), remaining
