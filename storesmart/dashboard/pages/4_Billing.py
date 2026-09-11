"""Billing page: big buttons to 'sell' items. Each sale decrements shelf
stock and writes a sales row."""
import streamlit as st

from storesmart.stock.db import get_connection, get_items, record_sale

st.set_page_config(page_title="StoreSmart — Billing", page_icon="🧾", layout="wide")
st.title("Billing")
st.caption("Simulated point-of-sale for the demo — sales history in the DB is seeded synthetic data.")

conn = get_connection()
items = get_items(conn)

if "cart_total" not in st.session_state:
    st.session_state.cart_total = 0.0

cols = st.columns(3)
for i, item in enumerate(items):
    with cols[i % 3]:
        disabled = item["shelf_qty"] <= 0
        label = f"{item['name']}\n₹{item['price']:.0f}  ({item['shelf_qty']} on shelf)"
        if st.button(label, key=f"sell_{item['id']}", disabled=disabled, use_container_width=True):
            record_sale(conn, item["id"], 1)
            st.session_state.cart_total += item["price"]
            st.rerun()

st.divider()
st.metric("Session total", f"₹{st.session_state.cart_total:.0f}")
if st.button("Reset session total"):
    st.session_state.cart_total = 0.0
    st.rerun()
