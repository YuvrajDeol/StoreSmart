"""Rule-based layout suggestions combining dwell time per zone (Phase 4)
with sales per category (Phase 3's stock DB). Zone labels are matched to
item categories by name. Suggestions only — nothing here changes the map or
stock automatically.
"""
from __future__ import annotations

import statistics
import time
from dataclasses import dataclass


@dataclass
class ZoneInsight:
    zone: str
    avg_dwell_s: float
    sales_count: int
    suggestion: str


def _percentile_rank(value: float, values: list[float]) -> float:
    if not values:
        return 0.5
    below = sum(1 for v in values if v < value)
    return below / len(values)


def compute_insights(conn, dwell_events: list[dict], lookback_days: float = 14,
                      high_pct: float = 0.66, low_pct: float = 0.33) -> list[ZoneInsight]:
    """dwell_events: [{"zone":..,"dwell_s":..}, ...] from the event bus."""
    dwell_by_zone: dict[str, list[float]] = {}
    for ev in dwell_events:
        dwell_by_zone.setdefault(ev["zone"], []).append(ev["dwell_s"])
    avg_dwell = {zone: statistics.mean(vals) for zone, vals in dwell_by_zone.items() if vals}

    since = time.time() - lookback_days * 86400
    sales_by_category: dict[str, int] = {}
    rows = conn.execute(
        "SELECT items.category AS category, SUM(sales.qty) AS qty FROM sales "
        "JOIN items ON items.id = sales.item_id WHERE sales.ts >= ? GROUP BY items.category",
        (since,),
    ).fetchall()
    for row in rows:
        sales_by_category[row["category"]] = row["qty"] or 0

    dwell_values = list(avg_dwell.values())
    sales_values = list(sales_by_category.values())

    insights = []
    for zone, dwell_s in avg_dwell.items():
        sales_count = sales_by_category.get(zone, 0)
        dwell_rank = _percentile_rank(dwell_s, dwell_values)
        sales_rank = _percentile_rank(sales_count, sales_values)
        high_dwell, low_dwell = dwell_rank >= high_pct, dwell_rank <= low_pct
        high_sales, low_sales = sales_rank >= high_pct, sales_rank <= low_pct

        if high_dwell and low_sales:
            suggestion = "High dwell, low sales — check price or display for this category."
        elif high_sales and low_dwell:
            suggestion = "High sales, low dwell — a destination item; consider placing it further back."
        elif high_dwell and high_sales:
            suggestion = "High dwell and high sales — a strong candidate zone for promotions."
        else:
            suggestion = "No strong signal yet."
        insights.append(ZoneInsight(zone=zone, avg_dwell_s=round(dwell_s, 1),
                                     sales_count=sales_count, suggestion=suggestion))
    return insights
