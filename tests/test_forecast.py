import datetime
import time

import pytest

from storesmart.stock.db import get_connection
from storesmart.stock.forecast import average_daily_demand, forecast_run_out, next_weekday


@pytest.fixture
def conn(tmp_path):
    c = get_connection(tmp_path / "test.db")
    cur = c.execute(
        "INSERT INTO items(name, category, slot, shelf_qty, store_qty, reorder_level, "
        "supplier, supplier_visit_weekday, lead_days, price) VALUES "
        "('Rice','Grocery','A1',10,10,5,'ACME',2,1,100)"
    )
    c.commit()
    item_id = cur.lastrowid
    now = time.time()
    for day in range(10):
        c.execute("INSERT INTO sales(item_id, qty, ts) VALUES (?, 2, ?)", (item_id, now - day * 86400))
    c.commit()
    return c, item_id


def test_average_daily_demand(conn):
    conn, item_id = conn
    demand = average_daily_demand(conn, item_id, lookback_days=10)
    assert demand == pytest.approx(2.0, abs=0.01)


def test_next_weekday_wraps_forward():
    monday = datetime.date(2026, 1, 5)  # a Monday
    assert next_weekday(monday, 2).weekday() == 2  # next Wednesday
    assert next_weekday(monday, 0) == monday  # today counts


def test_forecast_run_out_flags_risk_when_demand_high(conn):
    conn, item_id = conn
    item = dict(conn.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone())
    forecast = forecast_run_out(conn, item, lookback_days=10, today=datetime.date(2026, 1, 5))
    assert forecast.avg_daily_demand == pytest.approx(2.0, abs=0.01)
    assert forecast.days_left == pytest.approx(10, rel=0.3)
    assert forecast.next_supplier_visit.weekday() == 2
    assert forecast.order_by == forecast.next_supplier_visit - datetime.timedelta(days=item["lead_days"])
