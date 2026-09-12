"""Shared read-side helpers for the dashboard.

Everything here reads from the event bus / stock DB only — the dashboard
never touches a camera or a frame, per the Zero-Frame boundary.
"""
from __future__ import annotations

import datetime
import time
from typing import Optional

from storesmart.common.bus import EventBus

# A module counts as "live" if it emitted something within this many seconds.
LIVE_WINDOW_S = 15


def rel_time(ts: Optional[float], now: Optional[float] = None) -> str:
    if ts is None:
        return "never"
    now = now or time.time()
    delta = max(0, now - ts)
    if delta < 60:
        return f"{int(delta)}s ago"
    if delta < 3600:
        return f"{int(delta // 60)}m ago"
    if delta < 86400:
        return f"{int(delta // 3600)}h ago"
    return f"{int(delta // 86400)}d ago"


def latest(bus: EventBus, event_type: str) -> Optional[dict]:
    rows = bus.recent(limit=1, event_type=event_type)
    return rows[0] if rows else None


def kpi_snapshot(bus: EventBus) -> dict:
    """The headline numbers shown across the top of the hub."""
    summary = latest(bus, "summary") or {}
    queue = latest(bus, "queue") or {}
    return {
        "inside": summary.get("inside", 0),
        "entered": summary.get("in", 0),
        "exited": summary.get("out", 0),
        "queue_length": queue.get("length", 0),
        "wait_s": queue.get("wait_s", 0),
        "forecast_wait_s": queue.get("forecast_wait_s", 0),
        "counters": queue.get("counters", 1),
        "serving": queue.get("serving", 0),
    }


def module_statuses(bus: EventBus) -> list[dict]:
    """Per-phase health. Phases 1 and 2 emit continuously, so absence of
    recent events genuinely means "not running". Phases 3 and 4 only emit on
    a state change, so they get a neutral "last update" reading instead of a
    liveness claim — saying "stale" there would be misleading."""
    now = time.time()
    rows = []

    for name, phase, event_type, continuous in (
        ("Footfall & queue", "Phase 1", "summary", True),
        ("Live floor map", "Phase 2", "position", True),
        ("Shelf gaps", "Phase 3", "shelf_status", False),
        ("Dwell zones", "Phase 4", "dwell", False),
    ):
        ts = bus.last_ts(event_type=event_type)
        age = None if ts is None else now - ts
        if continuous:
            if age is None:
                tone, label = "neutral", "not started"
            elif age <= LIVE_WINDOW_S:
                tone, label = "good", "live"
            else:
                tone, label = "bad", "stopped"
        else:
            tone, label = ("neutral", "no data yet") if ts is None else ("info", "waiting for changes")
        rows.append({
            "name": name, "phase": phase, "tone": tone, "label": label,
            "last": rel_time(ts, now),
        })
    return rows


def shelf_slots(bus: EventBus) -> dict[str, dict]:
    """Latest known state per shelf slot, newest wins."""
    states: dict[str, dict] = {}
    for event in reversed(bus.recent(limit=200, event_type="shelf_status")):
        states[event["slot"]] = event
    return states


SEVERITY_RANK = {"urgent": 0, "warn": 1, "info": 2}


def active_alerts(bus: EventBus, limit: int = 6, per_kind: int = 2) -> list[dict]:
    """Most recent alerts, deduplicated per (kind, item) and capped at
    `per_kind` of any one kind — otherwise a run of, say, stock mismatches
    crowds every other alert type off the panel. Most severe first."""
    seen: set = set()
    by_kind: dict[str, int] = {}
    out = []
    for event in bus.recent(limit=80, event_type="alert"):
        kind = event.get("kind")
        key = (kind, event.get("item"))
        if key in seen or by_kind.get(kind, 0) >= per_kind:
            continue
        seen.add(key)
        by_kind[kind] = by_kind.get(kind, 0) + 1
        out.append(event)
    out.sort(key=lambda e: SEVERITY_RANK.get(e.get("severity", "info"), 3))
    return out[:limit]


#: Position events fire several times a second and say nothing useful in a
#: text feed — they're for the live map, so the activity feed skips them.
FEED_EXCLUDED_TYPES = ("position",)


def feed_events(bus: EventBus, limit: int = 14,
                exclude: tuple[str, ...] = FEED_EXCLUDED_TYPES) -> list[tuple[float, dict]]:
    rows = bus.recent_with_ts(limit=limit * 12)
    kept = [(ts, ev) for ts, ev in rows if ev.get("type") not in exclude]
    return kept[:limit]


def describe_event(event: dict) -> str:
    """One human-readable line for the activity feed."""
    etype = event.get("type")
    cam = event.get("cam")
    if etype == "entry":
        return "Person entered the store"
    if etype == "exit":
        return "Person left the store"
    if etype == "queue":
        return (f"Queue: {event.get('length', 0)} waiting, {event.get('serving', 0)} at counter "
                f"(~{event.get('wait_s', 0):.0f}s wait)")
    if etype == "served":
        return f"Customer served in {event.get('service_s', 0):.1f}s"
    if etype == "shelf_status":
        return f"Slot {event.get('slot')} is {event.get('state')} ({event.get('fill_pct', 0):.0f}% backdrop visible)"
    if etype == "position":
        return f"Floor position ({event.get('x_ft', 0):.1f}, {event.get('y_ft', 0):.1f}) ft"
    if etype == "dwell":
        return f"{event.get('dwell_s', 0):.0f}s spent in {event.get('zone')}"
    if etype == "alert":
        return f"[{event.get('kind')}] {event.get('msg', '')}"
    if etype == "summary":
        return f"Summary: {event.get('in', 0)} in, {event.get('out', 0)} out, {event.get('inside', 0)} inside"
    return f"{etype} ({cam})" if cam else str(etype)


EVENT_ICONS = {
    "entry": "🟢", "exit": "🔴", "queue": "🧑‍🤝‍🧑", "served": "✅",
    "shelf_status": "📦", "position": "📍", "dwell": "⏱️",
    "alert": "⚠️", "summary": "📊",
}


def stock_attention(conn, today: Optional[datetime.date] = None) -> list[dict]:
    """Items that need ordering — either projected to run out before the
    supplier's next visit, or already at/below the reorder level."""
    from storesmart.stock.db import get_items
    from storesmart.stock.forecast import forecast_run_out

    today = today or datetime.date.today()
    rows = []
    for item in get_items(conn):
        item = dict(item)
        forecast = forecast_run_out(conn, item, today=today)
        total = item["shelf_qty"] + item["store_qty"]
        below_reorder = total <= item["reorder_level"]
        if not (forecast.will_run_out_before_visit or below_reorder):
            continue
        rows.append({
            "name": item["name"],
            "days_left": forecast.days_left,
            "order_by": forecast.order_by,
            "supplier": item["supplier"],
            "total": total,
            "urgent": below_reorder,
        })
    rows.sort(key=lambda r: r["days_left"])
    return rows
