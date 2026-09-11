"""Auto-refresh helper: uses st.fragment(run_every=...) when the installed
Streamlit supports it, otherwise falls back to a meta-refresh style rerun."""
from __future__ import annotations

import time

import streamlit as st


def has_fragment() -> bool:
    return hasattr(st, "fragment")


def fragment(run_every: float = 1.5):
    """Decorator factory: st.fragment(run_every=...) if available, else a
    no-op decorator (call autorefresh() separately in that case)."""
    if has_fragment():
        return st.fragment(run_every=run_every)
    return lambda fn: fn


def autorefresh(interval_s: float = 1.5) -> None:
    """Fallback for older Streamlit without st.fragment: sleeps briefly then
    triggers a full rerun. Only call this when has_fragment() is False."""
    if has_fragment():
        return
    time.sleep(interval_s)
    st.rerun()
