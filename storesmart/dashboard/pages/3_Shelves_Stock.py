"""Shelves & Stock page: slot grid colored by state, items table with
days-left and order-by date, refill/reorder alerts."""
import datetime

import pandas as pd
import streamlit as st

from storesmart.common.bus import EventBus
from storesmart.dashboard.refresh import autorefresh, fragment
from storesmart.stock.db import get_connection, get_items
from storesmart.stock.forecast import forecast_run_out

st.set_page_config(page_title="StoreSmart — Shelves & Stock", page_icon="📦", layout="wide")
st.title("Shelves & Stock")

bus = EventBus()
conn = get_connection()

STATE_COLOR = {"ok": "🟢", "low": "🟡", "empty": "🔴"}


@fragment(run_every=2.0)
def render():
    st.subheader("Shelf slots")
    shelf_events = bus.recent(limit=100, event_type="shelf_status")
    latest_by_slot: dict[str, dict] = {}
    for ev in reversed(shelf_events):
        latest_by_slot[ev["slot"]] = ev
    if latest_by_slot:
        cols = st.columns(len(latest_by_slot))
        for col, (slot, ev) in zip(cols, sorted(latest_by_slot.items())):
            col.metric(f"{STATE_COLOR.get(ev['state'], '⚪')} {slot}", f"{ev['fill_pct']:.0f}% backdrop", ev["state"])
    else:
        st.info("No shelf snapshots yet — start Phase 3 (`make sim` or `python -m storesmart.phase3_shelf.run --simulate`).")

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
    for kind, label in (("refill", "🔵 Refill"), ("reorder", "🟠 Reorder"), ("mismatch", "🔴 Mismatch")):
        alerts = [a for a in bus.recent(limit=50, event_type="alert") if a.get("kind") == kind]
        for a in alerts[:5]:
            st.write(f"{label}: {a['msg']}")


render()
autorefresh(2.0)
