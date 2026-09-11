"""StoreSmart hub — one screen showing the whole store at a glance.

Reads only from the shared SQLite event bus and stock DB; it never touches a
camera or a frame. See CLAUDE.md for the Zero-Frame boundary.
"""
import html
import time

import streamlit as st

from storesmart.common.bus import EventBus
from storesmart.common.config import load_settings
from storesmart.dashboard import data
from storesmart.dashboard.refresh import autorefresh, fragment
from storesmart.dashboard.theme import (
    alert_html, apply_theme, card, kpi_grid, page_header, pill,
)
from storesmart.stock.db import get_connection

st.set_page_config(page_title="StoreSmart", page_icon="🛒", layout="wide")
apply_theme()

bus = EventBus()
settings = load_settings()


@fragment(run_every=2.0)
def render():
    kpis = data.kpi_snapshot(bus)
    modules = data.module_statuses(bus)
    counts = bus.counts()
    live_count = sum(1 for m in modules if m["tone"] == "good")

    system_pill = (
        pill(f"{live_count}/2 live modules", "good" if live_count else "neutral")
        + " " + pill("0 images stored", "good")
    )
    page_header(
        "🛒 StoreSmart",
        "Privacy-first store intelligence · all AI runs on this device · अंदर ही प्रोसेसिंग",
        system_pill,
    )

    # ---------------------------------------------------------------- KPIs
    wait = kpis["wait_s"]
    wait_tone = "bad" if wait > 30 else ("warn" if wait > 12 else "good")
    kpi_grid([
        {"label": "People inside · अंदर", "value": kpis["inside"], "tone": "info",
         "sub": "live occupancy"},
        {"label": "Entered · आए", "value": kpis["entered"], "tone": "good",
         "sub": "since start"},
        {"label": "Exited · गए", "value": kpis["exited"], "tone": "neutral",
         "sub": "since start"},
        {"label": "Queue · कतार", "value": kpis["queue_length"], "tone": wait_tone,
         "sub": f"{kpis['serving']} at counter"},
        {"label": "Est. wait", "value": f"{wait:.0f}s", "tone": wait_tone,
         "sub": f"forecast {kpis['forecast_wait_s']:.0f}s"},
        {"label": "Counters open", "value": kpis["counters"], "tone": "neutral",
         "sub": "checkout lanes"},
    ], cols=6)

    st.write("")
    left, right = st.columns([3, 2], gap="medium")

    # ------------------------------------------------------------- alerts
    with left:
        alerts = data.active_alerts(bus, limit=5)
        if alerts:
            body = "".join(
                alert_html(a.get("kind", "alert"), a.get("msg", ""), a.get("severity", "warn"))
                for a in alerts
            )
            st.markdown(f'<div class="ss-card"><h3>Needs attention</h3>{body}</div>',
                        unsafe_allow_html=True)
        else:
            card("Needs attention",
                 '<div class="ss-empty">✅ Nothing needs attention right now.</div>')

        # ------------------------------------------------------ shelf slots
        slots = data.shelf_slots(bus)
        if slots:
            chips = []
            for slot, ev in sorted(slots.items()):
                state = ev.get("state", "ok")
                chips.append(
                    f'<div class="ss-chip {html.escape(state)}"><div class="s">{html.escape(slot)}</div>'
                    f'<div class="p">{state} · {ev.get("fill_pct", 0):.0f}%</div></div>'
                )
            counts_by_state = {}
            for ev in slots.values():
                counts_by_state[ev.get("state")] = counts_by_state.get(ev.get("state"), 0) + 1
            summary = " · ".join(f"{v} {k}" for k, v in sorted(counts_by_state.items()))
            card("Shelf slots",
                 f'<div class="ss-chips">{"".join(chips)}</div>'
                 f'<div class="ss-empty" style="margin-top:9px">{html.escape(summary)}</div>')
        else:
            card("Shelf slots",
                 '<div class="ss-empty">No shelf snapshots yet — start Phase 3 '
                 '(<code>make sim</code> or <code>python -m storesmart.phase3_shelf.run --simulate</code>).</div>')

        # ---------------------------------------------------- activity feed
        events = data.feed_events(bus, limit=14)
        if events:
            now = time.time()
            rows = "".join(
                f'<div class="ev"><span class="t">{data.rel_time(ts, now)}</span>'
                f'<span class="x">{data.EVENT_ICONS.get(ev.get("type"), "•")} '
                f'{html.escape(data.describe_event(ev))}</span></div>'
                for ts, ev in events
            )
            card("Live activity", f'<div class="ss-feed">{rows}</div>')
        else:
            card("Live activity",
                 '<div class="ss-empty">No events yet. Run <code>make sim</code> in another terminal.</div>')

    # ------------------------------------------------- modules + stock + privacy
    with right:
        rows = "".join(
            f'<div class="ss-row"><div><div class="name">{html.escape(m["name"])}</div>'
            f'<div class="meta">{html.escape(m["phase"])} · last {html.escape(m["last"])}</div></div>'
            f'<div>{pill(m["label"], m["tone"])}</div></div>'
            for m in modules
        )
        card("Modules", rows)

        try:
            conn = get_connection()
            attention = data.stock_attention(conn)
        except Exception:
            attention = []
        if attention:
            stock_rows = []
            for r in attention[:6]:
                days_pill = pill(f"{r['days_left']:.0f}d left", "bad" if r["urgent"] else "warn")
                meta = f"{r['total']} in stock · order by {r['order_by'].strftime('%a %d %b')} · {r['supplier']}"
                stock_rows.append(
                    f'<div class="ss-row"><div><div class="name">{html.escape(r["name"])}</div>'
                    f'<div class="meta">{html.escape(meta)}</div></div>'
                    f'<div>{days_pill}</div></div>'
                )
            card("Stock to order", "".join(stock_rows))
        else:
            card("Stock to order",
                 '<div class="ss-empty">Nothing to reorder. Run <code>make seed</code> '
                 'if the stock database is empty.</div>')

        k = settings.get("privacy", {}).get("small_count_suppression_k", 5)
        card("Privacy", (
            f'<div class="ss-row"><div class="name">Images written to disk</div>'
            f'<div>{pill("0", "good")}</div></div>'
            f'<div class="ss-row"><div class="name">Events stored</div>'
            f'<div class="meta">{counts["accepted"]} · {counts["bytes"] / 1024:.1f} KB</div></div>'
            f'<div class="ss-row"><div class="name">Rejected by gate</div>'
            f'<div>{pill(str(counts["rejected"]), "warn" if counts["rejected"] else "neutral")}</div></div>'
            f'<div class="ss-row"><div class="name">Small-count suppression</div>'
            f'<div class="meta">k = {k}</div></div>'
        ))


render()

with st.sidebar:
    st.markdown("### Pages")
    st.markdown(
        "- **Control** — start/stop phases, simulate vs live\n"
        "- **Live** — footfall, queue, alerts\n"
        "- **Store Map** — layout & calibration\n"
        "- **Shelves & Stock** — slots, forecasts\n"
        "- **Billing** — simulated point of sale\n"
        "- **Dwell & Insights** — heatmap, layout tips\n"
        "- **Privacy** — event gate & audit"
    )
    st.caption("Use **Control** to start each phase on synthetic data or a real camera — "
               "no terminal needed.")

autorefresh(2.0)
