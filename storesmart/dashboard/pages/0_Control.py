"""Control page: choose what each phase runs on — synthetic data or a real
camera — and start/stop it, without touching a terminal.

The dashboard never opens a camera itself: modules run as separate
processes, and the "Test source" button shells out to
storesmart.common.camera_check. See CLAUDE.md.
"""
import os
from pathlib import Path

import streamlit as st

from storesmart.common.bus import EventBus
from storesmart.common.config import load_cameras, save_cameras_local
from storesmart.dashboard import data, processes
from storesmart.dashboard.theme import apply_theme, page_header, pill

st.set_page_config(page_title="StoreSmart — Control", page_icon="🎛️", layout="wide")
apply_theme()

REPO_ROOT = Path(__file__).resolve().parents[3]
bus = EventBus()

#: What each phase supports. Phases 2 and 4 exit with a clear message if run
#: without --simulate, so the UI doesn't pretend otherwise.
MODULES = [
    {
        "key": "footfall", "title": "Footfall & queue", "phase": "Phase 1",
        "module": "storesmart.phase1_footfall.run", "role": "entrance",
        "live": True,
        "needs": [("config/line.json", "entry line (line mode)"),
                  ("config/doorway.json", "doorway rectangle (doorway mode)")],
    },
    {
        "key": "shelf", "title": "Shelf gaps", "phase": "Phase 3",
        "module": "storesmart.phase3_shelf.run", "role": "shelf",
        "live": True,
        "needs": [("config/shelf_slots.json", "shelf slot rectangles")],
    },
    {
        "key": "floor", "title": "Live floor map", "phase": "Phase 2",
        "module": "storesmart.phase2_map.live_map", "role": "floor",
        "live": False,
        "live_note": "Real floor-camera mode isn't implemented yet — the module exits "
                     "with an explanation. Simulate only for now.",
    },
    {
        "key": "dwell", "title": "Dwell zones", "phase": "Phase 4",
        "module": "storesmart.phase4_dwell.run", "role": None,
        "live": False,
        "live_note": "Real-camera dwell needs the Phase 2 floor camera first. Simulate only for now.",
    },
]

running_now = sum(1 for m in MODULES if processes.status(m["key"])["running"])
page_header("🎛️ Control",
            "Pick what runs on synthetic data and what runs on a real camera",
            pill(f"{running_now}/{len(MODULES)} running", "good" if running_now else "neutral"))

# --------------------------------------------------------------- quick actions
col1, col2, col3 = st.columns([1, 1, 3])
if col1.button("▶️ Start all (simulate)", use_container_width=True, type="primary"):
    messages = []
    for module in MODULES:
        ok, msg = processes.start(module["key"], module["module"],
                                  ["--simulate", "--headless"], mode="simulate")
        messages.append(f"{module['title']}: {msg}")
    st.toast("  |  ".join(messages))
    st.rerun()
if col2.button("⏹ Stop all", use_container_width=True):
    processes.stop_all()
    st.toast("All modules stopped")
    st.rerun()
col3.caption("Simulate needs no camera and is the safe stage fallback. "
             "Live uses whatever source you set below for that camera role.")

st.divider()

cameras = load_cameras()

for module in MODULES:
    key = module["key"]
    state = processes.status(key)
    role = module["role"]

    with st.container(border=True):
        head_left, head_right = st.columns([3, 1])
        head_left.markdown(f"#### {module['title']}")
        head_left.caption(module["phase"] + (f" · camera role: `{role}`" if role else ""))
        if state["running"]:
            mins = state.get("uptime_s", 0) / 60
            head_right.markdown(
                pill(f"running · {state.get('mode')}", "good") +
                f"<div class='ss-empty'>pid {state['pid']} · up {mins:.1f}m</div>",
                unsafe_allow_html=True,
            )
        else:
            head_right.markdown(pill("stopped", "neutral"), unsafe_allow_html=True)

        mode_options = ["Simulate", "Live camera"] if module["live"] else ["Simulate"]
        mode = st.radio("Mode", mode_options, horizontal=True, key=f"mode_{key}",
                        label_visibility="collapsed")
        if not module["live"]:
            st.caption(f"ℹ️ {module['live_note']}")

        args: list[str] = []
        blocked_reason = ""

        if mode == "Simulate":
            args = ["--simulate", "--headless"]
        else:
            # ---- source for this role
            current = cameras.get(role, {}).get("url", "simulate")
            source = st.text_input(
                "Camera source", value=current, key=f"src_{key}",
                help="A webcam index (0, 1), a stream URL (http://IP:8080/video), "
                     "a snapshot URL (http://IP:8080/shot.jpg) or a video file path.",
            )
            scol1, scol2 = st.columns([1, 3])
            if scol1.button("🔌 Test source", key=f"test_{key}", use_container_width=True):
                with st.spinner(f"Probing {source}…"):
                    result = processes.probe_camera(source)
                if result.get("ok"):
                    size = (f" · {result.get('width')}×{result.get('height')}"
                            if result.get("width") else "")
                    scol2.success(f"✅ {result.get('detail')}{size}")
                else:
                    scol2.error(f"❌ {result.get('detail')}")

            if source != current:
                if scol2.button("💾 Save this source", key=f"save_{key}"):
                    updated = dict(cameras)
                    entry = dict(updated.get(role, {}))
                    entry["url"] = source
                    entry.setdefault("role", role)
                    updated[role] = entry
                    path = save_cameras_local(updated)
                    st.success(f"Saved to {path.relative_to(REPO_ROOT)}")
                    st.rerun()

            # ---- per-module live options
            if key == "footfall":
                ocol1, ocol2, ocol3 = st.columns(3)
                counting_mode = ocol1.selectbox("Counting", ["line", "doorway"], key=f"cm_{key}")
                initial_inside = ocol2.number_input("Already inside", min_value=0, value=0,
                                                    step=1, key=f"ii_{key}")
                show_window = ocol3.checkbox("Show camera window", value=True, key=f"win_{key}",
                                             help="Shows the blurred live view. Turn off to run "
                                                  "headless in the background.")
                args = ["--counting-mode", counting_mode, "--initial-inside", str(int(initial_inside))]
                if not show_window:
                    args.append("--headless")

                needed = ("config/line.json" if counting_mode == "line" else "config/doorway.json")
                if not (REPO_ROOT / needed).exists():
                    blocked_reason = (
                        f"`{needed}` doesn't exist yet — the {counting_mode} has to be drawn once "
                        "on the camera view. Run this in a terminal first:\n\n"
                        f"```bash\n.venv/bin/python -m storesmart.phase1_footfall.run "
                        f"--counting-mode {counting_mode}\n```"
                    )
            elif key == "shelf":
                args = ["--headless"]
                if not (REPO_ROOT / "config/shelf_slots.json").exists():
                    blocked_reason = (
                        "`config/shelf_slots.json` doesn't exist yet, so the slot rectangles for "
                        "your shelf camera are unknown. Copy `config/shelf_slots.example.json` to "
                        "`config/shelf_slots.json` and set each slot's pixel x/y/w/h for your "
                        "camera view."
                    )

        # ---- start / stop
        bcol1, bcol2, bcol3 = st.columns([1, 1, 3])
        start_disabled = state["running"] or bool(blocked_reason)
        if bcol1.button("▶️ Start", key=f"start_{key}", disabled=start_disabled,
                        use_container_width=True):
            ok, msg = processes.start(key, module["module"], args,
                                      mode="simulate" if mode == "Simulate" else "live")
            (st.toast if ok else st.error)(f"{module['title']}: {msg}")
            st.rerun()
        if bcol2.button("⏹ Stop", key=f"stop_{key}", disabled=not state["running"],
                        use_container_width=True):
            processes.stop(key)
            st.rerun()
        if blocked_reason:
            bcol3.warning(blocked_reason)
        elif not state["running"]:
            bcol3.caption(f"Will run: `python -m {module['module']} {' '.join(args)}`")

        with st.expander("Log output"):
            st.code(processes.tail_log(key, lines=25) or "(empty)", language="text")

st.divider()
st.caption(
    "Modules started here keep running even if you close the dashboard — use **Stop all** "
    "to clean up. Anything started from a terminal (`make sim`) won't show a PID here, but its "
    "events still appear on the hub."
)
