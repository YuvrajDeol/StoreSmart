"""StoreSmart Streamlit dashboard entry point.

Reads only from the shared SQLite event bus (storesmart/common/bus.py) — it
never touches a camera or a frame directly.
"""
import streamlit as st

st.set_page_config(page_title="StoreSmart", page_icon="🛒", layout="wide")

st.title("🛒 StoreSmart — privacy-first store intelligence")
st.markdown(
    """
Use the pages in the sidebar:

- **Live** — footfall, queue, wait/forecast, alerts
- **Store Map** — draw the shop layout and calibrate the floor camera
- **Shelves & Stock** — shelf slot grid, stock table, refill/reorder alerts
- **Billing** — sell items (simulated point of sale)
- **Dwell & Insights** — dwell heatmap and layout suggestions
- **Privacy** — live event feed, rejected events, "images written to disk: 0"

Run `make sim` (or the individual `python -m storesmart.phase*.run --simulate`
commands) in another terminal first so this dashboard has events to show.
"""
)
