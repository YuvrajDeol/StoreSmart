"""Privacy page: live event feed, storage size, rejected-event count, and a
button that proves an image-bearing event gets rejected by the gate."""
import streamlit as st

from storesmart.common.bus import EventBus
from storesmart.common.config import load_settings
from storesmart.dashboard.refresh import autorefresh, fragment

st.set_page_config(page_title="StoreSmart — Privacy", page_icon="🔒", layout="wide")
st.title("Privacy")

bus = EventBus()
settings = load_settings()

st.markdown(
    """
**Zero-Frame Architecture**: video frames are only ever held in memory inside
perception modules. Only small, schema-validated JSON events leave a module —
see [CLAUDE.md](../CLAUDE.md) for the full invariant list.
"""
)

st.subheader("Try it: inject a fake image-bearing event")
st.write("This simulates a bug that tries to smuggle a frame out as an event. It should be rejected.")
if st.button("Inject fake image event"):
    ok = bus.emit({
        "cam": "entrance", "type": "entry",
        "image_base64": "/9j/4AAQSkZJRgABAQAAAQABAAD" + "A" * 200,
    })
    if ok:
        st.error("BUG: the event was accepted! This should never happen.")
    else:
        st.success("Rejected by the event gate, as expected. No image data was stored.")


@fragment(run_every=2.0)
def render():
    counts = bus.counts()
    c1, c2, c3 = st.columns(3)
    c1.metric("Events accepted", counts["accepted"])
    c2.metric("Events rejected", counts["rejected"])
    c3.metric("Storage used", f"{counts['bytes'] / 1024:.1f} KB")

    st.metric("Images written to disk", 0)
    st.caption(
        "Enforced by tests/test_privacy_scan.py, which scans the source tree "
        "for cv2.imwrite/VideoWriter/imencode calls outside tests/ and "
        "scripts/dev_only/."
    )

    st.subheader(f"Small-count suppression threshold (k)")
    st.write(settings.get("privacy", {}).get("small_count_suppression_k", 5))

    st.subheader("Last 50 events")
    st.dataframe(bus.recent(limit=50), use_container_width=True, height=400)


render()
autorefresh(2.0)
