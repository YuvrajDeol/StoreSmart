"""Store Map page: upload an optional floor-plan image, enter shop size, place
shelves/doors/counters/cameras one at a time by arming an "+ Add a ___" button
and drawing a single shape, preview the layout, calibrate the floor camera
homography, and show live anonymous dots from Phase 2's position events.

The canvas is inert until an add button arms it, so a stray drag never creates
anything. Every confirmed shape is painted back into the canvas background each
rerun, so the sketch always shows the map as it stands.
"""
import math
import time
from pathlib import Path

import matplotlib.patches as patches
import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st
import streamlit.elements.image as _st_image_internals  # version guard, see below
from PIL import Image, ImageDraw, ImageFont
from streamlit_drawable_canvas import st_canvas

from storesmart.common.bus import EventBus
from storesmart.dashboard.theme import (
    PLOT_BG, PLOT_FG, apply_theme, page_header, style_axes,
)
from storesmart.dashboard.refresh import autorefresh, fragment
from storesmart.phase2_map.calibrate import calibrate
from storesmart.phase2_map.map_model import (
    DEFAULT_PATH, RECT_TYPES, Rectangle, StoreMap, load_map, save_map,
)

st.set_page_config(page_title="StoreSmart — Store Map", page_icon="🗺️", layout="wide")
apply_theme()
page_header("🗺️ Store Map",
            "Sketch the floor plan, then watch anonymous dots move on it live.")

# Version guard. streamlit-drawable-canvas 0.9.3 reaches into the PRIVATE helper
# streamlit.elements.image.image_to_url whenever a canvas background image is
# set — which this page always does. Streamlit moved that helper to
# streamlit.elements.lib.image_utils and changed its signature
# (width: int -> layout_config: LayoutConfig) after 1.39, so on a newer
# Streamlit the canvas raises a bare
#   AttributeError: module 'streamlit.elements.image' has no attribute 'image_to_url'
# with nothing pointing at the real cause. requirements.txt pins the two
# together; read the note there before bumping either. This check turns the
# cryptic crash into an actionable message — it is not a workaround, and
# aliasing the moved function would not be one either (the signature differs).
if not hasattr(_st_image_internals, "image_to_url"):
    st.error(
        f"The sketch canvas needs the pinned Streamlit version. This interpreter "
        f"has streamlit {st.__version__}, which moved the private helper that "
        f"streamlit-drawable-canvas 0.9.3 depends on. Run the dashboard from the "
        f"project venv instead — `.venv/Scripts/python -m streamlit run "
        f"storesmart/dashboard/app.py` on Windows, `.venv/bin/python -m streamlit "
        f"run storesmart/dashboard/app.py` elsewhere — or reinstall this "
        f"environment with `pip install -r requirements.txt`. See the COUPLED PIN "
        f"note in requirements.txt."
    )
    st.stop()

BACKGROUND_PATH = Path("config/store_map_background.png")
# Canvas scale: how many screen pixels represent one foot of shop floor. Fixed
# so that canvas pixels convert back to feet by simple division.
PX_PER_FT = 20
MAX_CANVAS_PX = 1100  # keeps very large shops on screen
COLORS = {"shelf": "#4C78A8", "door": "#54A24B", "counter": "#E45756", "camera": "#F2B701"}
# Types placed by arming a button and drawing one rectangle. Cameras have their
# own two-step flow (place the marker, then aim it), so they are not here.
SHAPE_TYPES = ("shelf", "door", "counter")
# How long a track may go without a position event before it stops being drawn.
# Phase 2 emits every 0.5s per person (--rate-hz 2), so this tolerates two
# missed emissions without blinking a live shopper off the map. Keep it tight:
# every extra second here keeps shoppers who have already walked out on screen
# for that much longer, which is what made the dot count read far higher than
# the Live page's "Inside" number.
POSITION_STALE_S = 1.5
CAMERA_SIZE_FT = 1.0      # fixed camera footprint — deliberately small vs a shelf
CAMERA_ARROW_FT = 3.0     # how far the facing arrow reaches on the canvas
DEFAULT_FOV_DEG = 60.0
# drawing_mode that creates nothing. "transform" only manipulates existing
# objects, and the canvas is kept empty, so this is the canvas's resting state.
INERT_MODE = "transform"

# Built once per session rather than inside the preview fragment below, which
# reruns every 1.5s — a fresh EventBus per run would open a new SQLite
# connection each time.
bus = EventBus()

if "store_map" not in st.session_state:
    st.session_state.store_map = load_map()
    # Whether the loaded map is load_map()'s example fallback rather than a real
    # save. Determined from whether the save file exists, not by comparing
    # contents. Cleared once the user saves or explicitly starts blank.
    st.session_state.using_example = not Path(DEFAULT_PATH).exists()
store_map: StoreMap = st.session_state.store_map

# Canvas/sketch state:
#   canvas_reset   — bumped to clear the shapes drawn on the canvas (see below)
#   arm_mode       — None when inert, else "shelf"/"door"/"counter" for a single
#                    rectangle, "camera_place" or "camera_aim" for the two-step
#                    camera gesture
#   pending_shape  — one drawn rectangle awaiting its label
#   camera_origin  — a placed but unaimed camera marker, in feet
#   pending_camera — a placed and aimed camera awaiting its label/fov
#
# The canvas keeps a STABLE key. Changing a canvas's key re-registers its
# background image under a new media-file coordinate, which orphans the old one
# and leaves the frontend fetching a URL Streamlit has already evicted (the
# canvas then renders with no background at all). Clearing drawn shapes is done
# by handing the canvas a changed `initial_drawing` instead, which resets it
# without disturbing the background.
st.session_state.setdefault("canvas_reset", 0)
st.session_state.setdefault("arm_mode", None)
st.session_state.setdefault("pending_shape", None)
st.session_state.setdefault("camera_origin", None)
st.session_state.setdefault("pending_camera", None)
st.session_state.setdefault("pending_seq", 0)


def _disarm() -> None:
    """Return the canvas to its inert state and clear whatever it holds."""
    st.session_state.arm_mode = None
    st.session_state.canvas_reset += 1


# ---------------------------------------------------------------------------
# 0. Floor plan image (optional)
# ---------------------------------------------------------------------------
st.subheader("0. Floor plan (optional)")
st.caption(
    "Upload a sketch, blueprint, or photo of a hand-drawn plan to trace over. "
    "Optional — the layout can be drawn from scratch without one."
)
# PRIVACY NOTE: writing this file to disk is NOT a Zero-Frame violation. The
# rule in CLAUDE.md covers camera frames of shoppers, produced by the
# perception modules (detector.py, video.py, the *_sim.py simulators). This is
# an owner-supplied floor-plan drawing — a different category of image
# entirely, containing no people and coming from a file picker, not a camera.
# It is written with Path.write_bytes() rather than an imwrite/PIL-save call,
# so it also stays clear of the patterns tests/test_privacy_scan.py greps for.
uploaded = st.file_uploader("Floor plan image", type=["png", "jpg", "jpeg"])
# Process each upload EXACTLY ONCE. st.file_uploader keeps returning the same
# file on every subsequent rerun, and re-writing the image + reassigning
# background_image each time kept re-mounting the canvas component, which reset
# its value before a drawn shape could ever be read back (a drawn rectangle
# simply never registered while a floor plan was loaded).
upload_id = None if uploaded is None else (uploaded.name, uploaded.size)
if uploaded is not None and st.session_state.get("last_upload_id") != upload_id:
    BACKGROUND_PATH.parent.mkdir(parents=True, exist_ok=True)
    BACKGROUND_PATH.write_bytes(uploaded.getvalue())
    store_map.background_image = BACKGROUND_PATH.as_posix()
    st.session_state.last_upload_id = upload_id
    st.toast(f"Floor plan stored at {BACKGROUND_PATH.as_posix()} — remember to save the map.")

if store_map.background_image:
    col_bg1, col_bg2 = st.columns([3, 1])
    col_bg1.info(f"Background in use: `{store_map.background_image}`")
    if col_bg2.button("Remove background image"):
        old = Path(store_map.background_image)
        if old.exists():
            old.unlink()
        store_map.background_image = None
        save_map(store_map)
        st.rerun()


def _background_pil():
    """Load the floor-plan image if one is configured and still on disk."""
    if not store_map.background_image:
        return None
    path = Path(store_map.background_image)
    if not path.exists():
        return None
    return Image.open(path).convert("RGB")


# ---------------------------------------------------------------------------
# 1. Shop size
# ---------------------------------------------------------------------------
st.subheader("1. Shop size")
c1, c2 = st.columns(2)
store_map.length_ft = c1.number_input("Length (ft)", min_value=5.0, value=float(store_map.length_ft), step=1.0)
store_map.breadth_ft = c2.number_input("Breadth (ft)", min_value=5.0, value=float(store_map.breadth_ft), step=1.0)

# ---------------------------------------------------------------------------
# Canvas helpers
# ---------------------------------------------------------------------------


def shop_box_ft(length_ft: float, breadth_ft: float) -> tuple[float, float, float, float]:
    """The rectangle, in feet, that the floor plan must fill: the whole shop.

    The length x breadth entered in section 1 is the ground truth for the real
    store's proportions, so an uploaded plan is always stretched to exactly
    this box regardless of its own pixel dimensions or aspect ratio. Both
    places that draw the plan — the sketch canvas background and the preview's
    imshow — derive their geometry from this one function, so they cannot be
    fitted by two different rules and drift out of alignment.
    """
    return (0.0, 0.0, float(length_ft), float(breadth_ft))


def shop_box_extent(length_ft: float, breadth_ft: float) -> list[float]:
    """The shop box as a matplotlib `extent`. Top and bottom are swapped
    because the preview's y-axis is inverted (y grows down the map)."""
    x, y, w, h = shop_box_ft(length_ft, breadth_ft)
    return [x, x + w, y + h, y]


def shop_box_px(length_ft: float, breadth_ft: float, px_per_ft: float) -> tuple[int, int]:
    """The shop box in canvas pixels at `px_per_ft`."""
    _x, _y, w, h = shop_box_ft(length_ft, breadth_ft)
    return max(1, round(w * px_per_ft)), max(1, round(h * px_per_ft))


def fit_floor_plan(image, length_ft: float, breadth_ft: float, px_per_ft: float):
    """Stretch a floor plan to exactly fill the shop box at `px_per_ft`.

    The pixel-space twin of `shop_box_extent`: same box, same rule, so the
    canvas background and the preview land on identical geometry.
    """
    return image.resize(shop_box_px(length_ft, breadth_ft, px_per_ft))


def _next_pending_seq() -> int:
    """A fresh id for each pending shape/camera.

    Streamlit keeps widget state by key, so reusing a fixed key would carry the
    previous shape's typed label and numbers into the next one. Keying on this
    counter gives every capture its own clean set of inputs.
    """
    st.session_state.pending_seq = st.session_state.get("pending_seq", 0) + 1
    return st.session_state.pending_seq


def _label_font():
    """A readable TrueType font if one can be found, else PIL's bitmap default.
    matplotlib is already a dependency and ships DejaVuSans, so this normally
    succeeds without adding a font dependency of our own."""
    try:
        from matplotlib import font_manager

        return ImageFont.truetype(font_manager.findfont("DejaVu Sans"), 11)
    except Exception:
        return ImageFont.load_default()


def _rgba(hex_color: str, alpha: int) -> tuple[int, int, int, int]:
    hex_color = hex_color.lstrip("#")
    return (int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16), alpha)


def _draw_arrow(draw: ImageDraw.ImageDraw, start, end, color, width=3) -> None:
    """Line with the arrow head at `end`, so a camera's arrow reads as pointing
    away from its marker and into the store."""
    draw.line([start, end], fill=color, width=width)
    angle = math.atan2(end[1] - start[1], end[0] - start[0])
    head = 9
    for offset in (math.radians(150), math.radians(-150)):
        draw.line(
            [end, (end[0] + head * math.cos(angle + offset), end[1] + head * math.sin(angle + offset))],
            fill=color, width=width,
        )


def _composite_canvas_background(base, length_ft, breadth_ft, px_per_ft, rectangles,
                                 pending_marker=None):
    """Floor plan (if any) with every already-confirmed rectangle painted on
    top, so the sketch canvas shows the map as it stands. `pending_marker` is a
    camera that has been placed but not yet aimed/confirmed — drawn so the user
    can see what the aiming drag refers to.

    The plan is fitted with `fit_floor_plan`, the same rule the preview uses.
    """
    width_px, height_px = shop_box_px(length_ft, breadth_ft, px_per_ft)
    if base is not None:
        canvas_img = fit_floor_plan(base, length_ft, breadth_ft, px_per_ft).convert("RGBA")
    else:
        canvas_img = Image.new("RGBA", (width_px, height_px), (255, 255, 255, 255))

    overlay = Image.new("RGBA", (width_px, height_px), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    font = _label_font()

    for rect in rectangles:
        x0, y0 = rect.x * px_per_ft, rect.y * px_per_ft
        x1, y1 = (rect.x + rect.w) * px_per_ft, (rect.y + rect.h) * px_per_ft
        color = COLORS.get(rect.type, "#888888")
        draw.rectangle([x0, y0, x1, y1], fill=_rgba(color, 130), outline=(40, 40, 40, 220), width=2)

        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        # Camera facing arrow, starting at the marker's centre. Canvas pixel y
        # grows downward and facing_deg increases toward +y, so this matches the
        # matplotlib preview's inverted-y rendering without any sign flip.
        if rect.type == "camera" and rect.facing_deg is not None:
            rad = math.radians(rect.facing_deg)
            reach = CAMERA_ARROW_FT * px_per_ft
            _draw_arrow(draw, (cx, cy), (cx + reach * math.cos(rad), cy + reach * math.sin(rad)),
                        _rgba(color, 255))

        if rect.label:
            ty = y0 - 8 if rect.type == "camera" else cy
            draw.text((cx, ty), rect.label, fill=(20, 20, 20, 255), font=font, anchor="mm",
                      stroke_width=2, stroke_fill=(255, 255, 255, 210))

    if pending_marker is not None:
        mx, my = pending_marker[0] * px_per_ft, pending_marker[1] * px_per_ft
        half = CAMERA_SIZE_FT * px_per_ft / 2
        draw.rectangle([mx - half, my - half, mx + half, my + half],
                       fill=_rgba(COLORS["camera"], 150), outline=(40, 40, 40, 255), width=2)
        draw.text((mx, my - half - 8), "aim me", fill=(20, 20, 20, 255), font=font, anchor="mm",
                  stroke_width=2, stroke_fill=(255, 255, 255, 210))

    return Image.alpha_composite(canvas_img, overlay).convert("RGB")


def _rect_signature(rects) -> tuple:
    """A comparable snapshot of the placed shapes. Used to tell whether the
    numbers typed into the table below differ from what the canvas was drawn
    with this run, so the canvas image can be refreshed immediately."""
    return tuple(
        (r.type, r.label, float(r.x), float(r.y), float(r.w), float(r.h),
         None if r.facing_deg is None else float(r.facing_deg),
         None if r.fov_deg is None else float(r.fov_deg))
        for r in rects
    )


def _first_rect(objects: list) -> dict | None:
    """The first rectangle on the canvas — one arm cycle places one shape, so
    anything drawn after it is ignored."""
    for obj in objects:
        if obj.get("type") == "rect" and float(obj.get("width", 0)) > 0:
            return obj
    return None


def _first_line(objects: list) -> dict | None:
    for obj in objects:
        if obj.get("type") == "line":
            return obj
    return None


def _rect_bounds_px(obj: dict):
    """(left, top, width, height) of a fabric rect in canvas pixels. fabric
    keeps the original width/height and records any later resize as
    scaleX/scaleY, so both must be multiplied."""
    return (
        float(obj.get("left", 0)),
        float(obj.get("top", 0)),
        float(obj.get("width", 0)) * float(obj.get("scaleX", 1)),
        float(obj.get("height", 0)) * float(obj.get("scaleY", 1)),
    )


def _line_endpoints_px(obj: dict):
    """Reconstruct a fabric.js line's (start, end) in canvas pixels.

    The canvas draws lines with originX/originY = "center", so `left`/`top` are
    the line's CENTRE (not its bounding-box corner), and x1/y1/x2/y2 are the
    endpoints expressed as offsets from that centre. Adding the two gives back
    canvas coordinates, in drag order."""
    cx, cy = float(obj.get("left", 0)), float(obj.get("top", 0))
    sx, sy = float(obj.get("scaleX", 1)), float(obj.get("scaleY", 1))
    start = (cx + float(obj.get("x1", 0)) * sx, cy + float(obj.get("y1", 0)) * sy)
    end = (cx + float(obj.get("x2", 0)) * sx, cy + float(obj.get("y2", 0)) * sy)
    return start, end


# ---------------------------------------------------------------------------
# 2. Sketch the layout
# ---------------------------------------------------------------------------
st.subheader("2. Sketch the layout")

if st.session_state.using_example:
    banner, clear_col = st.columns([3, 1])
    banner.warning(
        "This is example layout data for the demo — click Clear to start your own."
    )
    if clear_col.button("Clear example, start blank", type="primary"):
        store_map.rectangles = []
        store_map.background_image = None
        st.session_state.using_example = False
        st.session_state.pending_shape = None
        st.session_state.pending_camera = None
        st.session_state.camera_origin = None
        _disarm()
        st.rerun()

scale = min(
    PX_PER_FT,
    MAX_CANVAS_PX / max(store_map.length_ft, 1),
    MAX_CANVAS_PX / max(store_map.breadth_ft, 1),
)
canvas_w, canvas_h = shop_box_px(store_map.length_ft, store_map.breadth_ft, scale)

arm_mode = st.session_state.arm_mode
awaiting_confirm = st.session_state.pending_shape is not None or st.session_state.pending_camera is not None
buttons_disabled = arm_mode is not None or awaiting_confirm

add_cols = st.columns(4)
for col, shape_type in zip(add_cols, SHAPE_TYPES):
    # The "+" is escaped: Streamlit renders button labels as markdown, and a
    # leading "+ " is otherwise parsed as a list bullet and swallowed.
    if col.button(rf"\+ Add a {shape_type}", disabled=buttons_disabled, use_container_width=True,
                  key=f"arm_{shape_type}"):
        st.session_state.arm_mode = shape_type
        st.session_state.canvas_reset += 1
        st.rerun()
if add_cols[3].button("📷 + Add a camera", disabled=buttons_disabled, use_container_width=True,
                      key="arm_camera"):
    st.session_state.arm_mode = "camera_place"
    st.session_state.camera_origin = None
    st.session_state.canvas_reset += 1
    st.rerun()

# --- prompt describing the armed gesture ------------------------------------
if arm_mode in SHAPE_TYPES:
    prompt, cancel_col = st.columns([3, 1])
    prompt.info(f"**Placing a {arm_mode}** — drag one rectangle on the canvas.")
    if cancel_col.button("Cancel"):
        _disarm()
        st.rerun()
elif arm_mode == "camera_place":
    prompt, cancel_col = st.columns([3, 1])
    prompt.info(
        "**Step 1 of 2 — place the camera.** Click (or drag a small box) where "
        f"the camera is mounted. It is always placed as a fixed {CAMERA_SIZE_FT:g} x "
        f"{CAMERA_SIZE_FT:g} ft marker."
    )
    if cancel_col.button("Cancel"):
        st.session_state.camera_origin = None
        _disarm()
        st.rerun()
elif arm_mode == "camera_aim":
    prompt, cancel_col = st.columns([3, 1])
    prompt.info(
        "**Step 2 of 2 — aim the camera.** Drag outward toward what it looks at. "
        "The arrow always starts at the marker's centre, wherever you begin the drag."
    )
    if cancel_col.button("Cancel"):
        st.session_state.camera_origin = None
        _disarm()
        st.rerun()
elif not awaiting_confirm:
    st.caption(
        "The canvas is inert — nothing is drawn until you click one of the "
        "**+ Add a ___** buttons above. Each click places exactly one item."
    )

# What the canvas image is drawn from this run. Compared after the table
# below so a typed edit redraws the image straight away.
canvas_signature = _rect_signature(store_map.rectangles)
canvas_background = _composite_canvas_background(
    _background_pil(), store_map.length_ft, store_map.breadth_ft, scale,
    store_map.rectangles, pending_marker=st.session_state.camera_origin,
)
if arm_mode in SHAPE_TYPES:
    drawing_mode, stroke = "rect", COLORS[arm_mode]
elif arm_mode == "camera_place":
    drawing_mode, stroke = "rect", COLORS["camera"]
elif arm_mode == "camera_aim":
    drawing_mode, stroke = "line", COLORS["camera"]
else:
    drawing_mode, stroke = INERT_MODE, "#333333"

canvas_result = st_canvas(
    fill_color=("rgba(242, 183, 1, 0.35)" if arm_mode and arm_mode.startswith("camera")
                else "rgba(76, 120, 168, 0.3)"),
    stroke_width=3,
    stroke_color=stroke,
    background_color="",
    background_image=canvas_background,
    drawing_mode=drawing_mode,
    width=canvas_w,
    height=canvas_h,
    initial_drawing={"version": "4.4.0", "objects": [], "_reset": st.session_state.canvas_reset},
    key="map_canvas",
)
st.caption(
    f"Canvas scale: {scale:.1f} px per foot — "
    f"{store_map.length_ft:g} x {store_map.breadth_ft:g} ft shop. "
    f"{len(store_map.rectangles)} shape(s) placed."
)

drawn = (canvas_result.json_data or {}).get("objects", [])

# --- capture one drawn rectangle --------------------------------------------
if arm_mode in SHAPE_TYPES:
    obj = _first_rect(drawn)
    if obj is not None:
        left, top, w_px, h_px = _rect_bounds_px(obj)
        if w_px > 0 and h_px > 0:
            st.session_state.pending_shape = {
                "type": arm_mode,
                "x": round(left / scale, 2), "y": round(top / scale, 2),
                "w": round(w_px / scale, 2), "h": round(h_px / scale, 2),
                "seq": _next_pending_seq(),
            }
            _disarm()
            st.rerun()

# --- step 1: capture the camera marker --------------------------------------
if arm_mode == "camera_place":
    obj = _first_rect(drawn)
    if obj is not None:
        left, top, w_px, h_px = _rect_bounds_px(obj)
        # The drawn box only says WHERE; its size is discarded so a camera is
        # always the same small fixed marker, never a freely resized rectangle.
        st.session_state.camera_origin = (
            round((left + w_px / 2) / scale, 2),
            round((top + h_px / 2) / scale, 2),
        )
        st.session_state.arm_mode = "camera_aim"
        st.session_state.canvas_reset += 1
        st.rerun()

# --- step 2: capture the aim, snapped to the marker's centre ----------------
if arm_mode == "camera_aim" and st.session_state.camera_origin is not None:
    obj = _first_line(drawn)
    if obj is not None:
        _, end = _line_endpoints_px(obj)
        origin_x, origin_y = st.session_state.camera_origin
        # The line's own start point is ignored: the arrow is defined as running
        # from the marker's centre to wherever the drag ended, so it can never
        # be drawn from somewhere else.
        dx = end[0] - origin_x * scale
        dy = end[1] - origin_y * scale
        if math.hypot(dx, dy) >= 5:  # ignore an accidental click
            st.session_state.pending_camera = {
                "x_ft": origin_x, "y_ft": origin_y,
                "facing_deg": round(math.degrees(math.atan2(dy, dx)) % 360, 1),
                "seq": _next_pending_seq(),
            }
            _disarm()
            st.rerun()

# --- inline confirm: name the shape and correct its numbers -----------------
pending_shape = st.session_state.pending_shape
if pending_shape:
    seq = pending_shape["seq"]
    with st.container(border=True):
        st.caption(
            f"New **{pending_shape['type']}** - the drag filled these in. Leave them "
            "for rough placement, or type exact feet."
        )
        f1, f2 = st.columns([3, 1])
        shape_label = f1.text_input("Label", value="", key=f"pending_shape_label_{seq}",
                                    placeholder=f"e.g. Snacks {pending_shape['type']}")
        # Pre-filled from the drag, but THESE are what gets saved: the raw drag
        # values are only a starting point, never used unconditionally.
        n1, n2, n3, n4 = st.columns(4)
        shape_x = n1.number_input("x (ft)", value=float(pending_shape["x"]), step=0.5,
                                  format="%.2f", key=f"pending_shape_x_{seq}")
        shape_y = n2.number_input("y (ft)", value=float(pending_shape["y"]), step=0.5,
                                  format="%.2f", key=f"pending_shape_y_{seq}")
        shape_w = n3.number_input("width (ft)", min_value=0.1, value=float(pending_shape["w"]),
                                  step=0.5, format="%.2f", key=f"pending_shape_w_{seq}")
        shape_h = n4.number_input("height (ft)", min_value=0.1, value=float(pending_shape["h"]),
                                  step=0.5, format="%.2f", key=f"pending_shape_h_{seq}")
        f2.write("")
        if f2.button("Confirm", key=f"pending_shape_confirm_{seq}", type="primary"):
            store_map.rectangles.append(Rectangle(
                type=pending_shape["type"],
                label=shape_label.strip() or f"{pending_shape['type'].title()} {len(store_map.rectangles) + 1}",
                x=round(shape_x, 2), y=round(shape_y, 2),
                w=round(shape_w, 2), h=round(shape_h, 2),
            ))
            st.session_state.pending_shape = None
            _disarm()
            st.rerun()
        if f2.button("Discard", key=f"pending_shape_discard_{seq}"):
            st.session_state.pending_shape = None
            _disarm()
            st.rerun()

# --- inline confirm: a placed and aimed camera ------------------------------
pending_camera = st.session_state.pending_camera
if pending_camera:
    with st.container(border=True):
        cam_seq = pending_camera["seq"]
        st.caption(
            "New **camera** - the place-and-aim drags filled these in. Leave them "
            "or type exact values; position is the marker's centre."
        )
        g1, g2 = st.columns([3, 1])
        cam_label = g1.text_input("Label", value="", key=f"pending_cam_label_{cam_seq}",
                                  placeholder="e.g. Floor Cam")
        m1, m2, m3, m4 = st.columns(4)
        cam_x = m1.number_input("x (ft)", value=float(pending_camera["x_ft"]), step=0.5,
                                format="%.2f", key=f"pending_cam_x_{cam_seq}")
        cam_y = m2.number_input("y (ft)", value=float(pending_camera["y_ft"]), step=0.5,
                                format="%.2f", key=f"pending_cam_y_{cam_seq}")
        cam_facing = m3.number_input("facing (°)", min_value=0.0, max_value=359.9,
                                     value=float(pending_camera["facing_deg"]), step=5.0,
                                     format="%.1f", key=f"pending_cam_facing_{cam_seq}")
        cam_fov = m4.number_input("Field of view (°)", min_value=0.0, max_value=360.0,
                                  value=DEFAULT_FOV_DEG, step=5.0,
                                  key=f"pending_cam_fov_{cam_seq}")
        g2.write("")
        if g2.button("Confirm camera", key=f"pending_cam_confirm_{cam_seq}", type="primary"):
            half = CAMERA_SIZE_FT / 2
            store_map.rectangles.append(Rectangle(
                type="camera",
                label=cam_label.strip() or f"Camera {len(store_map.cameras()) + 1}",
                x=round(cam_x - half, 2),
                y=round(cam_y - half, 2),
                w=CAMERA_SIZE_FT, h=CAMERA_SIZE_FT,
                facing_deg=round(cam_facing, 1),
                fov_deg=cam_fov if cam_fov > 0 else None,
            ))
            st.session_state.pending_camera = None
            st.session_state.camera_origin = None
            _disarm()
            st.rerun()
        if g2.button("Discard", key=f"pending_cam_discard_{cam_seq}"):
            st.session_state.pending_camera = None
            st.session_state.camera_origin = None
            _disarm()
            st.rerun()

# ---------------------------------------------------------------------------
# 3. Exact numbers (precision editor / fallback)
# ---------------------------------------------------------------------------
st.subheader("3. Rectangles (shelves, doors, counters, cameras)")
st.caption("Everything placed on the canvas lands here — edit the numbers for precise placement.")
rect_rows = [{"type": r.type, "label": r.label, "x": r.x, "y": r.y, "w": r.w, "h": r.h} for r in store_map.rectangles]
edited = st.data_editor(
    pd.DataFrame(rect_rows, columns=["type", "label", "x", "y", "w", "h"]),
    num_rows="dynamic", use_container_width=True,
    column_config={"type": st.column_config.SelectboxColumn(options=list(RECT_TYPES))},
    # Keyed by how many shapes exist: adding or deleting one re-creates the
    # editor from fresh data, so a removed row cannot come back from stale
    # editor state. Typing does not change the count, so edits are unaffected.
    key=f"rect_table_{len(store_map.rectangles)}",
)
# Carry facing_deg/fov_deg across the table rebuild, keyed by (type, label), so
# that editing a coordinate does not silently reset a camera's direction.
prior_facing = {(r.type, r.label): (r.facing_deg, r.fov_deg) for r in store_map.rectangles}
store_map.rectangles = []
for _, row in edited.dropna().iterrows():
    if row["type"] not in RECT_TYPES:
        continue
    facing, fov = prior_facing.get((row["type"], row["label"]), (None, None))
    store_map.rectangles.append(Rectangle(
        type=row["type"], label=row["label"], x=row["x"], y=row["y"], w=row["w"], h=row["h"],
        facing_deg=facing, fov_deg=fov,
    ))

# Camera direction inputs. LAYOUT PLANNING AND INSTALLER REFERENCE ONLY: these
# values are never read by calibrate.py or live_map.py, which derive the
# homography independently from 4 clicked image/map point-pairs.
cameras = store_map.cameras()
if cameras:
    st.markdown(
        "**Camera direction** — for layout planning and installer reference only. "
        "These values do not affect calibration or detection."
    )
    st.caption(
        "Angle convention: 0° points right (+x, toward increasing length) and angles "
        "increase toward +y, which renders clockwise on the canvas and preview — so "
        "90° points down the map."
    )
    for cam in cameras:
        cc1, cc2 = st.columns(2)
        cam.facing_deg = cc1.number_input(
            f"{cam.label} — facing (°)", min_value=0.0, max_value=359.0, step=5.0,
            value=float(cam.facing_deg) if cam.facing_deg is not None else 0.0,
            key=f"facing_{cam.type}_{cam.label}",
        )
        fov_val = cc2.number_input(
            f"{cam.label} — field of view (°, 0 hides the wedge)",
            min_value=0.0, max_value=360.0, step=5.0,
            value=float(cam.fov_deg) if cam.fov_deg is not None else 0.0,
            key=f"fov_{cam.type}_{cam.label}",
        )
        cam.fov_deg = fov_val if fov_val > 0 else None

# --- delete a placed shape -------------------------------------------------
if store_map.rectangles:
    st.markdown("**Remove a shape**")
    del_col1, del_col2 = st.columns([3, 1])
    delete_options = [f"{i + 1}. {r.type} — {r.label}" for i, r in enumerate(store_map.rectangles)]
    picked = del_col1.selectbox("Shape to remove", delete_options,
                                key="delete_pick", label_visibility="collapsed")
    if del_col2.button("Delete", key="delete_btn", use_container_width=True):
        store_map.rectangles.pop(delete_options.index(picked))
        st.rerun()
    st.caption("Rows can also be removed straight from the table: tick a row, then press the bin icon.")

# A typed edit (or a delete) changes the shapes after the canvas has already
# been drawn this run, so rerun once to redraw the canvas image with them.
if _rect_signature(store_map.rectangles) != canvas_signature:
    st.rerun()

if st.button("Save store map", type="primary"):
    save_map(store_map)
    # What is on disk is now the user's own map, not the example fallback.
    st.session_state.using_example = False
    st.success("Saved to config/store_map.json")

# ---------------------------------------------------------------------------
# 4. Preview
# ---------------------------------------------------------------------------
st.subheader("4. Preview")


# ONLY the plot lives in this fragment, so the live dots can repaint on their
# own every 1.5s (same pattern as 1_Live.py). Everything above — shop size, the
# sketch canvas, the rectangle table, and the calibration section below — stays
# outside it deliberately: a page-wide auto-rerun would interrupt someone
# mid-drag on the canvas or mid-edit in the table every 1.5 seconds.
@fragment(run_every=1.5)
def render_preview():
    fig, ax = plt.subplots(figsize=(6, 6 * store_map.breadth_ft / max(store_map.length_ft, 1)))
    ax.set_xlim(0, store_map.length_ft)
    ax.set_ylim(0, store_map.breadth_ft)
    ax.set_aspect("equal")
    ax.invert_yaxis()
    style_axes(fig, ax)

    preview_bg = _background_pil()
    if preview_bg is not None:
        # Drawn first and faintly, so the rectangles stay legible on top of it.
        ax.imshow(preview_bg, extent=shop_box_extent(store_map.length_ft, store_map.breadth_ft),
                  alpha=0.5)

    for r in store_map.rectangles:
        ax.add_patch(patches.Rectangle((r.x, r.y), r.w, r.h, facecolor=COLORS.get(r.type, "gray"), alpha=0.6, edgecolor="black"))
        ax.text(r.x + r.w / 2, r.y + r.h / 2, r.label, ha="center", va="center", fontsize=8,
                color=PLOT_FG)
        if r.type == "camera" and r.facing_deg is not None:
            cx, cy = r.x + r.w / 2, r.y + r.h / 2
            reach = max(store_map.length_ft, store_map.breadth_ft) * 0.18
            if r.fov_deg:
                ax.add_patch(patches.Wedge(
                    (cx, cy), reach,
                    r.facing_deg - r.fov_deg / 2, r.facing_deg + r.fov_deg / 2,
                    facecolor=COLORS["camera"], alpha=0.25, edgecolor="none", zorder=3,
                ))
            rad = math.radians(r.facing_deg)
            ax.arrow(
                cx, cy, reach * math.cos(rad), reach * math.sin(rad),
                head_width=reach * 0.18, head_length=reach * 0.22,
                fc=COLORS["camera"], ec="black", linewidth=0.6,
                length_includes_head=True, zorder=4,
            )

    # One dot per person, not a smear of their path. Phase 2 emits a position
    # event per track ~2x/second, so a fixed "last 200 events" window was really
    # ~25 seconds of everyone's history drawn at once. Pull a short time window
    # instead and keep only each track's most recent point: bus.since() returns
    # oldest-first, so the last write per track wins. The window doubles as the
    # staleness rule — a track that stopped reporting drops out on its own.
    recent_positions = bus.since(time.time() - POSITION_STALE_S, event_type="position")
    latest_by_track: dict[int, dict] = {}
    for p in recent_positions:
        latest_by_track[p["track"]] = p

    if latest_by_track:
        xs = [p["x_ft"] for p in latest_by_track.values()]
        ys = [p["y_ft"] for p in latest_by_track.values()]
        ax.scatter(xs, ys, c="#3DDC97", s=40, zorder=5,
                   label=f"{len(latest_by_track)} anonymous dot(s)")
        ax.legend(loc="upper right", facecolor=PLOT_BG, edgecolor="#262C3A",
                  labelcolor=PLOT_FG, fontsize=8)
    st.pyplot(fig)
    # Repainting every 1.5s would otherwise pile up pyplot's global figure
    # registry (and trip its "more than 20 figures" warning) over a long session.
    plt.close(fig)
    st.caption("Dots are anonymous foot positions from Phase 2's position events — no camera image is shown here.")


render_preview()

# ---------------------------------------------------------------------------
# 5. Calibrate the floor camera
# ---------------------------------------------------------------------------
st.subheader("5. Calibrate the floor camera (4-point homography)")
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

# Fallback for Streamlit versions without st.fragment, where render_preview()
# is an ordinary function and cannot repaint by itself: sleep, then rerun the
# page. It is a no-op on any Streamlit that has st.fragment (>= 1.33), which
# includes the pinned version. It has to be the LAST statement on the page —
# it reruns the script, so anything after it would never render.
autorefresh(1.5)
