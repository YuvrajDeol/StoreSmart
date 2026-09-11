from storesmart.common.bus import EventBus
from storesmart.phase1_footfall.counter import EntryExitCounter
from storesmart.phase1_footfall.queue import QueueAnalyzer


def make_bus(tmp_path):
    return EventBus(db_path=tmp_path / "test.db")


def test_entry_exit_counter_counts_crossing(tmp_path):
    bus = make_bus(tmp_path)
    counter = EntryExitCounter(line=[[100, 0], [100, 200]], in_from=-1, margin=5)
    # track starts on the "in_from" side, then crosses to the other side
    counter.update([(1, (150, 90, 170, 110))], now=0.0, bus=bus)
    counter.update([(1, (30, 90, 50, 110))], now=1.0, bus=bus)
    assert counter.entries == 1
    assert counter.exits == 0
    assert counter.inside == 1


def test_entry_exit_counter_ignores_margin_jitter(tmp_path):
    bus = make_bus(tmp_path)
    counter = EntryExitCounter(line=[[100, 0], [100, 200]], in_from=1, margin=20)
    counter.update([(1, (150, 90, 170, 110))], now=0.0, bus=bus)
    counter.update([(1, (95, 90, 105, 110))], now=1.0, bus=bus)  # within dead-band
    assert counter.entries == 0
    assert counter.exits == 0


def test_queue_alert_uses_hysteresis(tmp_path):
    bus = make_bus(tmp_path)
    queue_poly = [[0, 0], [100, 0], [100, 100], [0, 100]]
    qa = QueueAnalyzer(queue_poly=queue_poly, service_poly=None, counters=1,
                        threshold_s=5, hold_s=1, default_service_s=6)
    tracks = [(i, (10, 10, 20, 20)) for i in range(10)]  # big queue -> high wait
    # condition must hold for `hold_s` before the alert fires
    qa.update(tracks, now=0.0, inside=10, bus=bus)
    assert qa.alert is False
    qa.update(tracks, now=0.5, inside=10, bus=bus)
    assert qa.alert is False
    qa.update(tracks, now=1.5, inside=10, bus=bus)
    assert qa.alert is True


def test_queue_forecast_uses_browsing_shoppers(tmp_path):
    bus = make_bus(tmp_path)
    qa = QueueAnalyzer(queue_poly=None, service_poly=None, counters=1, default_service_s=6)
    qa.update([], now=0.0, inside=20, bus=bus)  # nobody in queue/service yet, but 20 inside
    assert qa.forecast_wait_s > 0
    assert qa.browsing == 20
