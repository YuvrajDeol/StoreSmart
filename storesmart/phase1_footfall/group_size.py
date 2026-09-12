"""Estimates how many people a single detection box represents.

The common failure mode this handles: two people walking close together
(or briefly occluding each other) can merge into a single YOLO detection
box instead of two. Rather than trying to re-detect/re-identify people
(which the privacy rules here forbid), we use a simple, explainable size
heuristic: track a running baseline of how wide a *single* person's box
usually is at this camera's distance/angle, and if a crossing box is
roughly double (or triple, etc.) that width, count it as that many people.

There is no hardcoded pixel default for "one person" — that number depends
entirely on camera resolution and distance (a phone stream can be several
times wider than a laptop webcam), and guessing wrong made the very first
crossing miscount and get stuck that way forever. Instead, the first few
crossings (`min_samples_before_estimating`) are always assumed to be one
person each, purely to calibrate the baseline from this camera's own real
data; only after that does the ratio check kick in.
"""
from __future__ import annotations

import statistics
from collections import deque


class GroupSizeEstimator:
    def __init__(self, max_group_size: int = 4, history_size: int = 30,
                 min_samples_before_estimating: int = 5):
        self.max_group_size = max_group_size
        self.min_samples_before_estimating = min_samples_before_estimating
        self._widths: deque[float] = deque(maxlen=history_size)

    def estimate(self, width: float) -> int:
        if len(self._widths) < self.min_samples_before_estimating:
            self._widths.append(width)
            return 1  # still calibrating — assume one person per crossing

        baseline = statistics.median(self._widths)
        if baseline <= 0:
            return 1
        group = max(1, min(round(width / baseline), self.max_group_size))
        if group == 1:
            self._widths.append(width)
        return group
