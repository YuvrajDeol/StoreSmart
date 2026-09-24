from storesmart.common.bus import EventBus
from storesmart.dashboard import data


def make_bus(tmp_path):
    return EventBus(db_path=tmp_path / "t.db")


def alert(kind, item, severity="warn"):
    return {"type": "alert", "kind": kind, "item": item, "severity": severity,
            "msg": f"{kind} {item}"}


def test_alerts_show_one_of_each_kind_before_a_second_of_any(tmp_path):
    """A run of mismatches must not hide the refill and the reorder — those
    are different jobs for different people, and the panel is how anyone
    finds out they exist."""
    bus = make_bus(tmp_path)
    for i in range(5):
        bus.emit(alert("mismatch", f"item{i}"))
    bus.emit(alert("refill", "Rice"))
    bus.emit(alert("reorder", "Sugar"))

    kinds = [a["kind"] for a in data.active_alerts(bus, limit=6, per_kind=2)]
    assert set(kinds[:3]) == {"mismatch", "refill", "reorder"}


def test_alerts_are_capped_per_kind(tmp_path):
    bus = make_bus(tmp_path)
    for i in range(6):
        bus.emit(alert("mismatch", f"item{i}"))
    kinds = [a["kind"] for a in data.active_alerts(bus, limit=9, per_kind=2)]
    assert kinds.count("mismatch") == 2


def test_alerts_deduplicate_the_same_kind_and_item(tmp_path):
    bus = make_bus(tmp_path)
    for _ in range(4):
        bus.emit(alert("refill", "Rice"))
    assert len(data.active_alerts(bus, limit=6, per_kind=3)) == 1


def test_urgent_kinds_come_before_warnings(tmp_path):
    bus = make_bus(tmp_path)
    bus.emit(alert("refill", "Rice", severity="warn"))
    bus.emit(alert("reorder", "Sugar", severity="urgent"))
    assert data.active_alerts(bus, limit=6)[0]["kind"] == "reorder"


def test_no_alerts_returns_empty(tmp_path):
    assert data.active_alerts(make_bus(tmp_path)) == []
