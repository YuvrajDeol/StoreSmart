"""Shared dashboard styling and small UI helpers.

All CSS is inlined here and the font stack is the OS's own — nothing is
fetched from a CDN or webfont service at runtime, per the offline-only
invariant in CLAUDE.md.
"""
from __future__ import annotations

import html

import streamlit as st

TONES = ("neutral", "good", "warn", "bad", "info")

_CSS = """
<style>
:root {
  --ss-card:   #161A23;
  --ss-card-2: #1B2130;
  --ss-border: #262C3A;
  --ss-text:   #E6EAF1;
  --ss-muted:  #8A93A6;
  --ss-good:   #3DDC97;
  --ss-warn:   #F5B94A;
  --ss-bad:    #FF5C7A;
  --ss-info:   #5AA9FF;
}

/* tighten Streamlit's default chrome so the hub fits one screen */
.block-container { padding-top: 2.2rem; padding-bottom: 3rem; max-width: 1400px; }
#MainMenu, footer { visibility: hidden; }

/* ---------- page header ---------- */
.ss-head { display:flex; align-items:flex-end; justify-content:space-between;
           gap:16px; flex-wrap:wrap; margin-bottom:.4rem; }
.ss-head h1 { font-size:30px; font-weight:700; margin:0; letter-spacing:-0.4px;
              color:var(--ss-text); }
.ss-head .sub { color:var(--ss-muted); font-size:13.5px; margin-top:4px; }
.ss-rule { height:1px; background:linear-gradient(90deg,var(--ss-border),transparent);
           margin:.6rem 0 1.2rem; }

/* ---------- KPI grid ----------
   Column count comes from a class, not an inline style: Streamlit strips
   style attributes from injected HTML, so a `--cols` custom property set
   inline never reaches the element. */
.ss-grid { display:grid; gap:12px; margin-bottom:6px;
           grid-template-columns:repeat(4,minmax(0,1fr)); }
.ss-grid.c2 { grid-template-columns:repeat(2,minmax(0,1fr)); }
.ss-grid.c3 { grid-template-columns:repeat(3,minmax(0,1fr)); }
.ss-grid.c4 { grid-template-columns:repeat(4,minmax(0,1fr)); }
.ss-grid.c5 { grid-template-columns:repeat(5,minmax(0,1fr)); }
.ss-grid.c6 { grid-template-columns:repeat(6,minmax(0,1fr)); }
@media (max-width: 1250px) {
  .ss-grid.c5, .ss-grid.c6 { grid-template-columns:repeat(3,minmax(0,1fr)); }
}
@media (max-width: 900px) {
  .ss-grid, .ss-grid.c3, .ss-grid.c4, .ss-grid.c5, .ss-grid.c6 {
    grid-template-columns:repeat(2,minmax(0,1fr)); }
}

.ss-kpi { background:linear-gradient(180deg,var(--ss-card) 0%,var(--ss-card-2) 100%);
          border:1px solid var(--ss-border); border-left:3px solid var(--ss-border);
          border-radius:14px; padding:13px 15px; }
.ss-kpi.good { border-left-color:var(--ss-good); }
.ss-kpi.warn { border-left-color:var(--ss-warn); }
.ss-kpi.bad  { border-left-color:var(--ss-bad); }
.ss-kpi.info { border-left-color:var(--ss-info); }
.ss-kpi .lab { font-size:10.5px; letter-spacing:.09em; text-transform:uppercase;
               color:var(--ss-muted); font-weight:600; }
.ss-kpi .val { font-size:30px; font-weight:700; line-height:1.2; margin-top:3px;
               color:var(--ss-text); font-variant-numeric:tabular-nums; }
.ss-kpi .sub { font-size:11.5px; color:var(--ss-muted); margin-top:2px; }

/* ---------- cards ---------- */
.ss-card { background:var(--ss-card); border:1px solid var(--ss-border);
           border-radius:14px; padding:14px 16px; margin-bottom:12px; }
.ss-card h3 { font-size:12px; letter-spacing:.09em; text-transform:uppercase;
              color:var(--ss-muted); font-weight:600; margin:0 0 10px; }

/* ---------- status pills ---------- */
.ss-pill { display:inline-flex; align-items:center; gap:6px; font-size:11.5px;
           padding:3px 9px; border-radius:999px; border:1px solid transparent;
           font-weight:500; white-space:nowrap; }
.ss-pill .dot { width:6px; height:6px; border-radius:50%; background:currentColor; }
.ss-pill.good { color:var(--ss-good); border-color:rgba(61,220,151,.32); background:rgba(61,220,151,.10); }
.ss-pill.warn { color:var(--ss-warn); border-color:rgba(245,185,74,.32); background:rgba(245,185,74,.10); }
.ss-pill.bad  { color:var(--ss-bad);  border-color:rgba(255,92,122,.32); background:rgba(255,92,122,.10); }
.ss-pill.info { color:var(--ss-info); border-color:rgba(90,169,255,.32); background:rgba(90,169,255,.10); }
.ss-pill.neutral { color:var(--ss-muted); border-color:var(--ss-border); background:rgba(255,255,255,.03); }

/* ---------- module status rows ---------- */
.ss-row { display:flex; align-items:center; justify-content:space-between; gap:10px;
          padding:9px 0; border-bottom:1px solid rgba(38,44,58,.6); }
.ss-row:last-child { border-bottom:none; }
.ss-row .name { font-size:13.5px; color:var(--ss-text); font-weight:500; }
.ss-row .meta { font-size:11.5px; color:var(--ss-muted); margin-top:1px; }

/* ---------- alerts ---------- */
.ss-alert { display:flex; gap:11px; align-items:flex-start; background:var(--ss-card);
            border:1px solid var(--ss-border); border-left:3px solid var(--ss-warn);
            border-radius:11px; padding:10px 13px; margin-bottom:8px; }
.ss-alert.urgent { border-left-color:var(--ss-bad); }
.ss-alert.info   { border-left-color:var(--ss-info); }
.ss-alert .ico { font-size:16px; line-height:1.35; }
.ss-alert .kind { font-size:10px; letter-spacing:.09em; text-transform:uppercase;
                  color:var(--ss-muted); font-weight:700; }
.ss-alert .msg { font-size:13.5px; color:var(--ss-text); margin-top:1px; line-height:1.45; }

/* ---------- slot chips ---------- */
.ss-chips { display:flex; flex-wrap:wrap; gap:7px; }
.ss-chip { border:1px solid var(--ss-border); border-radius:9px; padding:6px 10px;
           font-size:12px; background:rgba(255,255,255,.02); min-width:64px; }
.ss-chip .s { font-weight:700; color:var(--ss-text); }
.ss-chip .p { font-size:10.5px; color:var(--ss-muted); }
.ss-chip.ok    { border-color:rgba(61,220,151,.35); }
.ss-chip.low   { border-color:rgba(245,185,74,.45); background:rgba(245,185,74,.07); }
.ss-chip.empty { border-color:rgba(255,92,122,.45); background:rgba(255,92,122,.08); }

/* ---------- event feed ---------- */
.ss-feed { max-height:330px; overflow-y:auto; }
.ss-feed .ev { display:flex; gap:10px; align-items:baseline; padding:5px 0;
               border-bottom:1px solid rgba(38,44,58,.45); font-size:12.5px; }
.ss-feed .ev:last-child { border-bottom:none; }
.ss-feed .t { color:var(--ss-muted); font-size:11px; min-width:58px;
              font-variant-numeric:tabular-nums; }
.ss-feed .x { color:var(--ss-text); }
.ss-empty { color:var(--ss-muted); font-size:13px; padding:6px 0; }
</style>
"""


#: Matplotlib colours matching the dashboard's dark palette, so the map and
#: heatmap figures don't render as bright white rectangles on a dark page.
PLOT_BG = "#161A23"
PLOT_FG = "#E6EAF1"
PLOT_MUTED = "#8A93A6"


def apply_theme() -> None:
    st.markdown(_CSS, unsafe_allow_html=True)


def style_axes(fig, ax) -> None:
    """Apply the dashboard's dark palette to a matplotlib figure."""
    fig.patch.set_facecolor(PLOT_BG)
    ax.set_facecolor(PLOT_BG)
    ax.tick_params(colors=PLOT_MUTED, labelsize=8)
    for spine in ax.spines.values():
        spine.set_edgecolor("#262C3A")
    ax.xaxis.label.set_color(PLOT_MUTED)
    ax.yaxis.label.set_color(PLOT_MUTED)
    ax.title.set_color(PLOT_FG)


def page_header(title: str, subtitle: str = "", right_html: str = "") -> None:
    st.markdown(
        f"""<div class="ss-head">
              <div><h1>{html.escape(title)}</h1>
                   {f'<div class="sub">{html.escape(subtitle)}</div>' if subtitle else ''}</div>
              <div>{right_html}</div>
            </div><div class="ss-rule"></div>""",
        unsafe_allow_html=True,
    )


def pill(label: str, tone: str = "neutral") -> str:
    tone = tone if tone in TONES else "neutral"
    return f'<span class="ss-pill {tone}"><span class="dot"></span>{html.escape(label)}</span>'


def kpi_grid(items: list[dict], cols: int = 4) -> None:
    """items: [{"label":.., "value":.., "sub":.., "tone":..}, ...]"""
    cards = []
    for it in items:
        tone = it.get("tone", "neutral")
        tone = tone if tone in TONES else "neutral"
        sub = f'<div class="sub">{html.escape(str(it["sub"]))}</div>' if it.get("sub") else ""
        cards.append(
            f'<div class="ss-kpi {tone}"><div class="lab">{html.escape(str(it["label"]))}</div>'
            f'<div class="val">{html.escape(str(it["value"]))}</div>{sub}</div>'
        )
    cols = max(2, min(int(cols), 6))
    st.markdown(
        f'<div class="ss-grid c{cols}">{"".join(cards)}</div>',
        unsafe_allow_html=True,
    )


def card_open(title: str) -> str:
    return f'<div class="ss-card"><h3>{html.escape(title)}</h3>'


def card(title: str, body_html: str) -> None:
    st.markdown(card_open(title) + body_html + "</div>", unsafe_allow_html=True)


def alert_html(kind: str, msg: str, severity: str = "warn") -> str:
    icons = {"open_counter": "🧑‍🤝‍🧑", "refill": "📦", "reorder": "🚚",
             "mismatch": "🔍", "layout": "🗺️"}
    cls = {"urgent": "urgent", "info": "info"}.get(severity, "")
    return (
        f'<div class="ss-alert {cls}"><div class="ico">{icons.get(kind, "⚠️")}</div>'
        f'<div><div class="kind">{html.escape(kind.replace("_", " "))}</div>'
        f'<div class="msg">{html.escape(msg)}</div></div></div>'
    )


def empty_state(message: str) -> None:
    st.markdown(f'<div class="ss-empty">{html.escape(message)}</div>', unsafe_allow_html=True)
