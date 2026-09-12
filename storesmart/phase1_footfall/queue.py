"""Queue length, service time, wait estimate, forecast, and open-counter
alert with hysteresis. Ported from sanket_demo.py's Analytics class.
"""
from __future__ import annotations

from collections import deque

import numpy as np

from storesmart.common.bus import EventBus
from storesmart.common.geometry import point_in_polygon


class QueueAnalyzer:
    def __init__(self, queue_poly: list[list[float]] | None, service_poly: list[list[float]] | None,
                 counters: int = 1, threshold_s: float = 12, horizon_s: float = 10,
                 join_prob: float = 1.0, hold_s: float = 3, window_s: float = 30,
                 default_service_s: float = 6, min_service_s: float = 1.0, cam: str = "counter",
                 emit_interval_s: float = 1.0):
        self.queue_poly = _as_poly(queue_poly)
        self.service_poly = _as_poly(service_poly)
        self.counters = counters
        self.threshold_s = threshold_s
        self.horizon_s = horizon_s
        self.join_prob = join_prob
        self.hold_s = hold_s
        self.window_s = window_s
        self.default_service_s = default_service_s
        self.min_service_s = min_service_s
        self.cam = cam
        self.emit_interval_s = emit_interval_s
        self._last_queue_emit = -1e9

        self.in_service: dict[int, float] = {}
        self.durations: deque[float] = deque(maxlen=10)
        self.entry_times: deque[float] = deque()
        self.served = 0
        self.length = 0
        self.serving_now = 0
        self.browsing = 0
        self.wait_now = 0.0
        self.forecast_wait_s = 0.0
        self.forecast_wait_plus = 0.0
        self.alert = False
        self.alert_reason = ""
        self._cond_since: float | None = None
        self._clear_since: float | None = None
        self._last_summary = -1e9

    def mean_service(self) -> float:
        return sum(self.durations) / len(self.durations) if self.durations else self.default_service_s

    def update(self, tracks: list[tuple[int, tuple[int, int, int, int]]], now: float,
               inside: int, bus: EventBus) -> None:
        q = serving = 0
        seen_this_frame = set()
        for tid, (x1, y1, x2, y2) in tracks:
            foot = ((x1 + x2) / 2, y2)
            seen_this_frame.add(tid)
            if point_in_polygon(self.queue_poly, foot):
                q += 1
            if point_in_polygon(self.service_poly, foot):
                serving += 1
                self.in_service.setdefault(tid, now)
            elif tid in self.in_service:
                self._finish_service(tid, now, bus)
        for tid in [t for t in self.in_service if t not in seen_this_frame]:
            self._finish_service(tid, now, bus)

        self.length, self.serving_now = q, serving
        self.browsing = max(0, inside - q - serving)
        mu = 1.0 / max(self.mean_service(), 0.5)
        self.wait_now = q / (self.counters * mu)
        self.forecast_wait_s = self._forecast(self.counters, mu)
        self.forecast_wait_plus = self._forecast(self.counters + 1, mu)
        self._alerting(now, bus)

        # Internal state (and therefore alerting) updates every frame, but the
        # queue event is only emitted about once a second — a near-identical
        # event per frame would bloat the log for no extra information, and the
        # dashboard only polls every 1.5s anyway.
        if now - self._last_queue_emit >= self.emit_interval_s:
            self._last_queue_emit = now
            bus.emit({
                "cam": self.cam, "type": "queue", "length": q, "serving": serving,
                "counters": self.counters, "wait_s": round(self.wait_now, 1),
                "forecast_wait_s": round(self.forecast_wait_s, 1),
            })

    def _forecast(self, counters: int, mu: float) -> float:
        # Demo heuristic: shoppers already inside (counted at the entrance)
        # will reach checkout soon. Production would use a trained
        # forecaster + Erlang-C, not this linear approximation.
        q_future = max(0.0, self.length + self.join_prob * self.browsing - counters * mu * self.horizon_s)
        return q_future / (counters * mu)

    def _finish_service(self, tid: int, now: float, bus: EventBus) -> None:
        started = self.in_service.pop(tid)
        duration = now - started
        if duration >= self.min_service_s:
            self.served += 1
            self.durations.append(duration)
            bus.emit({"cam": self.cam, "type": "served", "service_s": round(duration, 1)})

    def _alerting(self, now: float, bus: EventBus) -> None:
        hot = self.wait_now > self.threshold_s or self.forecast_wait_s > self.threshold_s
        cool = self.wait_now < 0.6 * self.threshold_s and self.forecast_wait_s < 0.6 * self.threshold_s
        if not self.alert:
            self._cond_since = (self._cond_since or now) if hot else None
            if self._cond_since is not None and now - self._cond_since >= self.hold_s:
                self.alert, self._clear_since = True, None
                self.alert_reason = "forecast" if self.forecast_wait_s > self.wait_now else "queue now"
                shown_wait = self.forecast_wait_s if self.alert_reason == "forecast" else self.wait_now
                bus.emit({
                    "type": "alert", "kind": "open_counter", "severity": "warn",
                    "msg": f"Open another counter ({self.alert_reason}): wait {shown_wait:.0f}s "
                           f"-> {self.forecast_wait_plus:.0f}s with {self.counters + 1}",
                })
        else:
            self._clear_since = (self._clear_since or now) if cool else None
            if self._clear_since is not None and now - self._clear_since >= self.hold_s:
                self.alert, self._cond_since = False, None

    def set_counters(self, n: int) -> None:
        self.counters = max(1, n)


def _as_poly(pts: list[list[float]] | None):
    return None if not pts else np.array(pts, dtype=np.float32)
