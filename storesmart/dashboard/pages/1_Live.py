"""Live page: footfall, queue, wait/forecast, alerts. Reads only from the
event bus — no camera access here."""
import streamlit as st

from storesmart.common.bus import EventBus
from storesmart.dashboard.refresh import autorefresh, fragment

st.set_page_config(page_title="StoreSmart — Live", page_icon="🛒", layout="wide")
st.title("Live — footfall & queue")

bus = EventBus()

if "acked_alerts" not in st.session_state:
    st.session_state.acked_alerts = set()
if "alert_seen_at" not in st.session_state:
    st.session_state.alert_seen_at = {}


def _latest(event_type: str):
    rows = bus.recent(limit=1, event_type=event_type)
    return rows[0] if rows else None


@fragment(run_every=1.5)
def render():
    summary = _latest("summary")
    queue = _latest("queue")

    col1, col2, col3 = st.columns(3)
    col1.metric("IN", summary.get("in", 0) if summary else 0)
    col2.metric("OUT", summary.get("out", 0) if summary else 0)
    col3.metric("Inside", summary.get("inside", 0) if summary else 0)

    st.subheader("Queue")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Queue length", queue.get("length", 0) if queue else 0)
    c2.metric("Open counters", queue.get("counters", 1) if queue else 1)
    c3.metric("Wait now (s)", queue.get("wait_s", 0) if queue else 0)
    c4.metric("Forecast wait (s)", queue.get("forecast_wait_s", 0) if queue else 0)

    st.subheader("Alerts")
    alerts = bus.recent(limit=20, event_type="alert")
    if not alerts:
        st.success("No active alerts.")
    for i, alert in enumerate(alerts):
        key = f"{alert['t']}-{alert.get('kind')}-{i}"
        cols = st.columns([6, 1])
        cols[0].warning(f"**{alert.get('kind')}**: {alert.get('msg')}")
        if key not in st.session_state.acked_alerts:
            if cols[1].button("Acknowledge", key=f"ack_{key}"):
                st.session_state.acked_alerts.add(key)
                st.session_state.alert_seen_at[key] = alert["t"]
        else:
            cols[1].write("✅ acked")

    st.subheader("Recent events")
    st.dataframe(bus.recent(limit=25), use_container_width=True, height=300)


render()
autorefresh(1.5)
