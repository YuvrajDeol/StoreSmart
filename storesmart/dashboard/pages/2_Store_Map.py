"""Store Map page: enter shop size, add/remove rectangles (shelf/door/
counter/camera), preview the layout, calibrate the floor camera homography,
and show live anonymous dots from Phase 2's position events."""
import matplotlib.patches as patches
import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st

from storesmart.common.bus import EventBus
from storesmart.dashboard.refresh import autorefresh, fragment
from storesmart.phase2_map.calibrate import calibrate
from storesmart.phase2_map.map_model import RECT_TYPES, Rectangle, StoreMap, load_map, save_map

st.set_page_config(page_title="StoreSmart — Store Map", page_icon="🗺️", layout="wide")
st.title("Store Map")

if "store_map" not in st.session_state:
    st.session_state.store_map = load_map()
store_map: StoreMap = st.session_state.store_map

st.subheader("1. Shop size")
c1, c2 = st.columns(2)
store_map.length_ft = c1.number_input("Length (ft)", min_value=5.0, value=float(store_map.length_ft), step=1.0)
store_map.breadth_ft = c2.number_input("Breadth (ft)", min_value=5.0, value=float(store_map.breadth_ft), step=1.0)

st.subheader("2. Rectangles (shelves, doors, counters, cameras)")
rect_rows = [{"type": r.type, "label": r.label, "x": r.x, "y": r.y, "w": r.w, "h": r.h} for r in store_map.rectangles]
edited = st.data_editor(
    pd.DataFrame(rect_rows, columns=["type", "label", "x", "y", "w", "h"]),
    num_rows="dynamic", use_container_width=True,
    column_config={"type": st.column_config.SelectboxColumn(options=list(RECT_TYPES))},
)
store_map.rectangles = [
    Rectangle(type=row["type"], label=row["label"], x=row["x"], y=row["y"], w=row["w"], h=row["h"])
    for _, row in edited.dropna().iterrows()
    if row["type"] in RECT_TYPES
]

if st.button("Save store map", type="primary"):
    save_map(store_map)
    st.success("Saved to config/store_map.json")

st.subheader("3. Preview")
COLORS = {"shelf": "#4C78A8", "door": "#54A24B", "counter": "#E45756", "camera": "#F2B701"}
bus = EventBus()


@fragment(run_every=1.5)
def render_preview():
    fig, ax = plt.subplots(figsize=(6, 6 * store_map.breadth_ft / max(store_map.length_ft, 1)))
    ax.set_xlim(0, store_map.length_ft)
    ax.set_ylim(0, store_map.breadth_ft)
    ax.set_aspect("equal")
    ax.invert_yaxis()
    for r in store_map.rectangles:
        ax.add_patch(patches.Rectangle((r.x, r.y), r.w, r.h, facecolor=COLORS.get(r.type, "gray"), alpha=0.6, edgecolor="black"))
        ax.text(r.x + r.w / 2, r.y + r.h / 2, r.label, ha="center", va="center", fontsize=8)

    positions = bus.recent(limit=200, event_type="position")
    if positions:
        xs = [p["x_ft"] for p in positions]
        ys = [p["y_ft"] for p in positions]
        ax.scatter(xs, ys, c="black", s=15, zorder=5, label="anonymous dots")
        ax.legend(loc="upper right")
    st.pyplot(fig)
    # Re-rendering every 1.5s means a new figure every 1.5s; pyplot keeps them
    # all alive until the tab closes, so drop this one now.
    plt.close(fig)
    st.caption("Dots are anonymous foot positions from Phase 2's position events — no image is shown here.")


render_preview()

st.subheader("4. Calibrate the floor camera (4-point homography)")
st.caption(
    "In real-camera mode this screen shows the in-memory people-free background "
    "(median of recent frames) — never a saved photo. For the demo, enter matching "
    "image-pixel points and map-feet points directly."
)
colA, colB = st.columns(2)
with colA:
    st.write("Image points (pixels)")
    img_pts_df = st.data_editor(
        pd.DataFrame([{"x_px": 0, "y_px": 0}] * 4), num_rows="fixed", key="img_pts"
    )
with colB:
    st.write("Map points (feet)")
    map_pts_df = st.data_editor(
        pd.DataFrame([{"x_ft": 0.0, "y_ft": 0.0}] * 4), num_rows="fixed", key="map_pts"
    )
if st.button("Compute homography"):
    try:
        image_points = img_pts_df[["x_px", "y_px"]].values.tolist()
        map_points = map_pts_df[["x_ft", "y_ft"]].values.tolist()
        calibrate(store_map, image_points, map_points)
        save_map(store_map)
        st.success("Homography computed and saved.")
    except Exception as exc:
        st.error(f"Calibration failed: {exc}")

autorefresh(1.5)
