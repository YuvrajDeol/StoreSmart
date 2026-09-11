"""Estimates how many people a single detection box represents.

The common failure mode this handles: two people walking close together
(or briefly occluding each other) can merge into a single YOLO detection
box instead of two. Rather than trying to re-detect/re-identify people
(which the privacy rules here forbid), we use a simple, explainable size
heuristic: track a running baseline of how wide a *single* person's box
usually is at this camera's distance/angle, and if a crossing box is
roughly double (or triple, etc.) that width, count it as that many people.

The baseline is seeded with a generic default and only updated from boxes
that were themselves judged to be a single person, so a run of merged
detections can't drag the baseline upward and hide itself.
"""
from __future__ import annotations

import statistics
from collections import deque

DEFAULT_SINGLE_WIDTH_PX = 70


class GroupSizeEstimator:
    def __init__(self, max_group_size: int = 4, history_size: int = 30,
                 default_width_px: float = DEFAULT_SINGLE_WIDTH_PX):
        self.max_group_size = max_group_size
        self.default_width_px = default_width_px
        self._widths: deque[float] = deque(maxlen=history_size)

    def estimate(self, width: float) -> int:
        baseline = statistics.median(self._widths) if self._widths else self.default_width_px
        if baseline <= 0:
            return 1
        group = max(1, min(round(width / baseline), self.max_group_size))
        if group == 1:
            self._widths.append(width)
        return group
