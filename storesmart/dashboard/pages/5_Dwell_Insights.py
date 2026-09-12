"""Dwell & Insights page: dwell time per zone, an occupancy heatmap (with
small-count suppression), and rule-based layout suggestions."""
import matplotlib.patches as patches
import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st

from storesmart.common.bus import EventBus
from storesmart.common.config import load_settings
from storesmart.dashboard.refresh import autorefresh, fragment
from storesmart.phase2_map.map_model import load_map
from storesmart.dashboard.theme import PLOT_FG, apply_theme, page_header, style_axes
from storesmart.phase4_dwell.heatmap import build_heatmap
from storesmart.phase4_dwell.insights import compute_insights
from storesmart.stock.db import get_connection

st.set_page_config(page_title="StoreSmart — Dwell & Insights", page_icon="🔥", layout="wide")
apply_theme()
page_header("🔥 Dwell & Insights",
            "Time spent per zone, an occupancy heatmap, and rule-based layout suggestions")

bus = EventBus()
conn = get_connection()
store_map = load_map()
settings = load_settings()
k = settings.get("privacy", {}).get("small_count_suppression_k", 5)


@fragment(run_every=3.0)
def render():
    dwell_events = bus.recent(limit=500, event_type="dwell")
    positions = bus.recent(limit=1000, event_type="position")

    st.subheader("Occupancy heatmap")
    st.caption(f"Cells with fewer than k={k} distinct visitors are hidden (small-count suppression).")
    if positions:
        cells = build_heatmap(positions, grid_ft=settings.get("dwell", {}).get("grid_ft", 1), k=k)
        fig, ax = plt.subplots(figsize=(6, 6 * store_map.breadth_ft / max(store_map.length_ft, 1)))
        ax.set_xlim(0, store_map.length_ft)
        ax.set_ylim(0, store_map.breadth_ft)
        ax.invert_yaxis()
        ax.set_aspect("equal")
        style_axes(fig, ax)
        for shelf in store_map.shelves():
            ax.add_patch(patches.Rectangle((shelf.x, shelf.y), shelf.w, shelf.h,
                                             facecolor="none", edgecolor="#4A5468"))
            ax.text(shelf.x + shelf.w / 2, shelf.y + shelf.h / 2, shelf.label, ha="center", fontsize=7, color=PLOT_FG)
        if cells:
            xs = [c[0] for c in cells]
            ys = [c[1] for c in cells]
            counts = [cells[c] for c in cells]
            ax.scatter(xs, ys, c=counts, cmap="Reds", s=200, marker="s", alpha=0.7)
        else:
            st.info(f"Not enough distinct visitors yet to show any cell (need >= {k}).")
        st.pyplot(fig)
    else:
        st.info("No position events yet — start Phase 2's live map (`python -m storesmart.phase2_map.live_map --simulate`).")

    st.subheader("Dwell per zone")
    if dwell_events:
        df = pd.DataFrame(dwell_events)
        summary = df.groupby("zone")["dwell_s"].agg(["mean", "count"]).reset_index()
        summary.columns = ["Zone", "Avg dwell (s)", "Visits recorded"]
        st.dataframe(summary, use_container_width=True)
    else:
        st.info("No dwell events yet — Phase 4 needs shelves drawn on the Store Map page and the dwell tracker running.")

    st.subheader("Layout suggestions")
    insights = compute_insights(conn, dwell_events)
    if not insights:
        st.info("Not enough data yet for layout suggestions.")
    for insight in insights:
        st.write(f"**{insight.zone}** — avg dwell {insight.avg_dwell_s}s, "
                 f"{insight.sales_count} sales: {insight.suggestion}")
    st.caption("Suggestions only — layout changes are made by the shopkeeper, never automatically.")


render()
autorefresh(3.0)
