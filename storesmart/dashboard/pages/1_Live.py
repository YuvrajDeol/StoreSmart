"""Live page: footfall, queue, wait/forecast, and the alert feed with
acknowledgement. Reads only from the event bus — no camera access here."""
import html
import time

import pandas as pd
import streamlit as st

from storesmart.common.bus import EventBus
from storesmart.dashboard import data
from storesmart.dashboard.refresh import autorefresh, fragment
from storesmart.dashboard.theme import (
    alert_html, apply_theme, card, kpi_grid, page_header, pill,
)

st.set_page_config(page_title="StoreSmart — Live", page_icon="🛒", layout="wide")
apply_theme()

bus = EventBus()

if "acked_alerts" not in st.session_state:
    st.session_state.acked_alerts = {}


@fragment(run_every=1.5)
def render():
    kpis = data.kpi_snapshot(bus)
    modules = data.module_statuses(bus)
    footfall = next((m for m in modules if m["phase"] == "Phase 1"), None)
    status = pill(footfall["label"], footfall["tone"]) if footfall else ""

    page_header("Live — footfall & queue",
                "Entry/exit counting, queue length and wait forecast", status)

    wait = kpis["wait_s"]
    wait_tone = "bad" if wait > 30 else ("warn" if wait > 12 else "good")
    kpi_grid([
        {"label": "People inside · अंदर", "value": kpis["inside"], "tone": "info"},
        {"label": "Entered · आए", "value": kpis["entered"], "tone": "good"},
        {"label": "Exited · गए", "value": kpis["exited"], "tone": "neutral"},
        {"label": "In queue · कतार", "value": kpis["queue_length"], "tone": wait_tone,
         "sub": f"{kpis['serving']} at counter"},
        {"label": "Est. wait now", "value": f"{wait:.0f}s", "tone": wait_tone},
        {"label": "Forecast wait", "value": f"{kpis['forecast_wait_s']:.0f}s", "tone": wait_tone,
         "sub": "from shoppers inside"},
    ], cols=6)

    st.write("")
    left, right = st.columns([3, 2], gap="medium")

    with left:
        st.markdown("##### Alerts")
        alerts = bus.recent_with_ts(limit=15, event_type="alert")
        if not alerts:
            st.success("No active alerts — queue under control.")
        for ts, alert in alerts:
            key = f"{alert.get('t')}-{alert.get('kind')}-{alert.get('item')}"
            cols = st.columns([6, 1])
            cols[0].markdown(
                alert_html(alert.get("kind", "alert"), alert.get("msg", ""),
                           alert.get("severity", "warn")),
                unsafe_allow_html=True,
            )
            if key in st.session_state.acked_alerts:
                took = st.session_state.acked_alerts[key]
                cols[1].caption(f"✅ {took:.0f}s")
            elif cols[1].button("Ack", key=f"ack_{key}", use_container_width=True):
                # time-to-acknowledge: how long the alert sat before a human saw it
                st.session_state.acked_alerts[key] = max(0.0, time.time() - ts)

    with right:
        served = bus.recent(limit=20, event_type="served")
        if served:
            times = [s.get("service_s", 0) for s in served]
            avg = sum(times) / len(times)
            card("Checkout", (
                f'<div class="ss-row"><div class="name">Customers served</div>'
                f'<div class="meta">{len(served)} recent</div></div>'
                f'<div class="ss-row"><div class="name">Avg service time</div>'
                f'<div class="meta">{avg:.1f}s</div></div>'
                f'<div class="ss-row"><div class="name">Counters open</div>'
                f'<div class="meta">{kpis["counters"]}</div></div>'
            ))
        else:
            card("Checkout", '<div class="ss-empty">No completed services yet.</div>')

        events = data.feed_events(bus, limit=12)
        if events:
            now = time.time()
            rows = "".join(
                f'<div class="ev"><span class="t">{data.rel_time(ts, now)}</span>'
                f'<span class="x">{data.EVENT_ICONS.get(ev.get("type"), "•")} '
                f'{html.escape(data.describe_event(ev))}</span></div>'
                for ts, ev in events
            )
            card("Recent events", f'<div class="ss-feed">{rows}</div>')

    with st.expander("Raw event stream (last 40)"):
        st.dataframe(pd.DataFrame(bus.recent(limit=40)), use_container_width=True, height=300)


render()
autorefresh(1.5)
