"""Shelves & Stock page: slot grid colored by state, items table with
days-left and order-by date, refill/reorder alerts."""
import datetime

import pandas as pd
import streamlit as st

import html

from storesmart.common.bus import EventBus
from storesmart.dashboard import data
from storesmart.dashboard.refresh import autorefresh, fragment
from storesmart.dashboard.theme import alert_html, apply_theme, card, kpi_grid, page_header
from storesmart.stock.db import get_connection, get_items
from storesmart.stock.forecast import forecast_run_out

st.set_page_config(page_title="StoreSmart — Shelves & Stock", page_icon="📦", layout="wide")
apply_theme()
page_header("📦 Shelves & Stock",
            "Shelf gaps from the camera, combined with the stock and billing database")

bus = EventBus()
conn = get_connection()


@fragment(run_every=2.0)
def render():
    slots = data.shelf_slots(bus)
    if slots:
        by_state = {}
        for ev in slots.values():
            by_state[ev.get("state")] = by_state.get(ev.get("state"), 0) + 1
        kpi_grid([
            {"label": "Slots watched", "value": len(slots), "tone": "info"},
            {"label": "Stocked · भरा", "value": by_state.get("ok", 0), "tone": "good"},
            {"label": "Running low", "value": by_state.get("low", 0), "tone": "warn"},
            {"label": "Empty · खाली", "value": by_state.get("empty", 0), "tone": "bad"},
        ], cols=4)
        chips = "".join(
            f'<div class="ss-chip {html.escape(ev.get("state", "ok"))}">'
            f'<div class="s">{html.escape(slot)}</div>'
            f'<div class="p">{ev.get("state")} · {ev.get("fill_pct", 0):.0f}%</div></div>'
            for slot, ev in sorted(slots.items())
        )
        card("Slot grid", f'<div class="ss-chips">{chips}</div>')
    else:
        st.info("No shelf snapshots yet — start Phase 3 (`make sim` or "
                "`python -m storesmart.phase3_shelf.run --simulate`).")

    st.subheader("Items")
    rows = []
    today = datetime.date.today()
    for item in get_items(conn):
        forecast = forecast_run_out(conn, dict(item), today=today)
        rows.append({
            "Item": item["name"], "Category": item["category"], "Slot": item["slot"],
            "Shelf qty": item["shelf_qty"], "Store qty": item["store_qty"],
            "Avg daily demand": forecast.avg_daily_demand, "Days left": forecast.days_left,
            "Supplier": item["supplier"], "Next visit": forecast.next_supplier_visit.isoformat(),
            "Order by": forecast.order_by.isoformat(),
            "Run-out risk": "⚠️ before next visit" if forecast.will_run_out_before_visit else "ok",
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True, height=380)
    st.caption("Sales history used for the forecast is simulated (seeded demo data), not real POS data.")

    st.subheader("Refill / Reorder / Mismatch alerts")
    stock_alerts = [a for a in data.active_alerts(bus, limit=9, per_kind=3)
                    if a.get("kind") in ("refill", "reorder", "mismatch")]
    if stock_alerts:
        st.markdown(
            "".join(alert_html(a.get("kind", ""), a.get("msg", ""), a.get("severity", "warn"))
                    for a in stock_alerts),
            unsafe_allow_html=True,
        )
    else:
        st.success("No refill, reorder or mismatch alerts right now.")


render()
autorefresh(2.0)
