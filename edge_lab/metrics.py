"""Rolling on-device metrics. Inference time is recorded ONLY when a model actually ran."""
from __future__ import annotations

import time
from collections import deque


class PerfMeter:
    def __init__(self, window: int = 120):
        self.times_ms: deque[float] = deque(maxlen=window)
        self._stamps: deque[float] = deque(maxlen=window)
        self.frames = 0          # frames processed by the pipeline
        self.inferences = 0      # frames on which a real model ran
        self.last_ran = False

    def tick(self) -> None:
        """Call once per processed frame (drives FPS)."""
        self._stamps.append(time.perf_counter())
        self.frames += 1

    def add(self, ms: float) -> None:
        """Record one real model inference."""
        self.times_ms.append(ms)
        self.inferences += 1

    @property
    def has_data(self) -> bool:
        return bool(self.times_ms)

    @property
    def inference_ms(self) -> float:
        return sum(self.times_ms) / len(self.times_ms) if self.times_ms else float("nan")

    @property
    def p95_ms(self) -> float:
        if not self.times_ms:
            return float("nan")
        s = sorted(self.times_ms)
        return s[min(len(s) - 1, int(0.95 * len(s)))]

    @property
    def fps(self) -> float:
        if len(self._stamps) < 2:
            return 0.0
        span = self._stamps[-1] - self._stamps[0]
        return (len(self._stamps) - 1) / span if span > 0 else 0.0
