"""Privacy page: the audit view — live event feed, storage footprint,
rejected-event count, and a button proving an image-bearing event is
rejected by the gate."""
import html
import time

import pandas as pd
import streamlit as st

from storesmart.common.bus import EventBus
from storesmart.common.config import load_settings
from storesmart.dashboard import data
from storesmart.dashboard.refresh import autorefresh, fragment
from storesmart.dashboard.theme import apply_theme, card, kpi_grid, page_header, pill

st.set_page_config(page_title="StoreSmart — Privacy", page_icon="🔒", layout="wide")
apply_theme()

bus = EventBus()
settings = load_settings()
k = settings.get("privacy", {}).get("small_count_suppression_k", 5)

page_header("🔒 Privacy",
            "Everything the system keeps, and everything it refuses to keep",
            pill("Zero-Frame Architecture", "good"))

st.markdown(
    "Video frames exist **only in memory**, inside the perception modules. The only thing "
    "that ever leaves a module is a small, schema-validated JSON event — no image, no video, "
    "no face, no appearance embedding, no demographic guess. Tracking is motion-only "
    "(YOLOv8 person class + ByteTrack). See `CLAUDE.md` for the full invariant list."
)

INVARIANTS = [
    ("No image or video written to disk, ever",
     "Enforced by tests/test_privacy_scan.py, which fails the build if cv2.imwrite / "
     "VideoWriter / imencode appears outside tests/ and scripts/dev_only/."),
    ("Only whitelisted JSON events can persist",
     "Pydantic models with extra=\"forbid\", 9 allowed event types, max 1 KB serialized. "
     "Anything else is rejected and counted, never silently dropped."),
    ("No identity, only motion",
     "No face detection/recognition, no appearance embeddings, no re-identification, "
     "no age/gender inference. Track IDs are ephemeral and per-camera."),
    (f"Small groups are suppressed (k = {k})",
     "Any dwell zone or heatmap cell visited by fewer than k people is hidden from "
     "aggregates, so no individual's path can be picked out."),
    ("Works fully offline",
     "No CDN, map tiles, webfonts or remote APIs at runtime — only local model weights."),
]


@fragment(run_every=2.0)
def render():
    counts = bus.counts()
    kpi_grid([
        {"label": "Images written to disk", "value": "0", "tone": "good",
         "sub": "verified by source scan"},
        {"label": "Events stored", "value": counts["accepted"], "tone": "info",
         "sub": "schema-validated only"},
        {"label": "Total storage", "value": f"{counts['bytes'] / 1024:.1f} KB",
         "tone": "neutral", "sub": "text events, not video"},
        {"label": "Rejected by gate", "value": counts["rejected"],
         "tone": "warn" if counts["rejected"] else "neutral", "sub": "blocked at the boundary"},
    ], cols=4)

    st.write("")
    st.markdown("##### Try to break it")
    st.caption(
        "Simulates a bug — or an attacker — trying to smuggle a camera frame out as an "
        "event. The gate should reject it and count it, storing none of the image data."
    )
    inject_col, result_col = st.columns([1, 3])
    if inject_col.button("💉 Inject fake image event", use_container_width=True):
        accepted = bus.emit({
            "cam": "entrance", "type": "entry",
            "image_base64": "/9j/4AAQSkZJRgABAQAAAQABAAD" + "A" * 200,
        })
        # Held in session state, not rendered inline: this fragment re-runs
        # every couple of seconds, which would wipe the result off the screen
        # moments after someone pressed the button.
        st.session_state["inject_result"] = accepted

    outcome = st.session_state.get("inject_result")
    if outcome is True:
        result_col.error("BUG: the event was accepted! This should never happen.")
    elif outcome is False:
        result_col.success(
            "Rejected by the event gate, as expected — no image data was stored.")

    st.write("")
    left, right = st.columns([3, 2], gap="medium")

    with left:
        events = data.feed_events(bus, limit=18)
        if events:
            now = time.time()
            rows = "".join(
                f'<div class="ev"><span class="t">{data.rel_time(ts, now)}</span>'
                f'<span class="x">{data.EVENT_ICONS.get(ev.get("type"), "•")} '
                f'{html.escape(data.describe_event(ev))}</span></div>'
                for ts, ev in events
            )
            card("Everything the system knows right now", f'<div class="ss-feed">{rows}</div>')
        else:
            card("Everything the system knows right now",
                 '<div class="ss-empty">No events yet — run <code>make sim</code>.</div>')

    with right:
        rows = "".join(
            f'<div class="ss-row"><div><div class="name">✅ {html.escape(title)}</div>'
            f'<div class="meta">{html.escape(detail)}</div></div></div>'
            for title, detail in INVARIANTS
        )
        card("Enforced invariants", rows)


render()


with st.expander("Raw event log (last 50)"):
    st.dataframe(pd.DataFrame(bus.recent(limit=50)), use_container_width=True, height=340)

autorefresh(2.0)
