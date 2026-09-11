from storesmart.common.bus import EventBus
from storesmart.phase1_footfall.counter import EntryExitCounter
from storesmart.phase1_footfall.queue import QueueAnalyzer


def make_bus(tmp_path):
    return EventBus(db_path=tmp_path / "test.db")


def test_entry_exit_counter_counts_full_crossing(tmp_path):
    bus = make_bus(tmp_path)
    counter = EntryExitCounter(line=[[100, 0], [100, 200]], in_from=-1, buffer_px=10)
    # track starts confirmed on the "in_from" side, then crosses fully through
    # the buffer to the other side
    counter.update([(1, (150, 90, 170, 110))], now=0.0, bus=bus)  # x=160, clearly right of line
    counter.update([(1, (30, 90, 50, 110))], now=1.0, bus=bus)    # x=40, clearly left of line
    assert counter.entries == 1
    assert counter.exits == 0
    assert counter.inside == 1


def test_entry_exit_counter_ignores_buffer_jitter(tmp_path):
    bus = make_bus(tmp_path)
    counter = EntryExitCounter(line=[[100, 0], [100, 200]], in_from=1, buffer_px=20)
    counter.update([(1, (150, 90, 170, 110))], now=0.0, bus=bus)  # x=160, confirmed right
    counter.update([(1, (95, 90, 105, 110))], now=1.0, bus=bus)   # x=100, inside the buffer band
    assert counter.entries == 0
    assert counter.exits == 0


def test_entry_exit_counter_ignores_repeated_jitter_near_line(tmp_path):
    """A person lingering right at the line shouldn't get counted repeatedly
    just because detection noise nudges them a few pixels each frame — this
    is the bug the buffer zone exists to prevent."""
    bus = make_bus(tmp_path)
    counter = EntryExitCounter(line=[[100, 0], [100, 200]], in_from=1, buffer_px=20)
    counter.update([(1, (150, 90, 170, 110))], now=0.0, bus=bus)  # x=160, confirmed right
    for i, x in enumerate([95, 105, 98, 102, 96, 104]):  # noisy wobble, all inside the buffer
        counter.update([(1, (x, 90, x + 20, 110))], now=1.0 + i, bus=bus)
    assert counter.entries == 0
    assert counter.exits == 0


def test_entry_exit_counter_initial_inside_baseline(tmp_path):
    """Someone already in the store when the system starts, then leaving,
    should decrement from the seeded baseline rather than making the OUT
    count outrun IN with the inside total stuck at 0."""
    bus = make_bus(tmp_path)
    counter = EntryExitCounter(line=[[100, 0], [100, 200]], in_from=1, buffer_px=10,
                                initial_inside=3)
    assert counter.inside == 3
    counter.update([(1, (150, 90, 170, 110))], now=0.0, bus=bus)  # confirmed right (in_from side)
    counter.update([(1, (30, 90, 50, 110))], now=1.0, bus=bus)    # crosses left -> exit
    assert counter.exits == 1
    assert counter.entries == 0
    assert counter.inside == 2  # 3 - 1, not clamped to 0


def test_entry_exit_counter_wide_box_counts_as_two_people(tmp_path):
    bus = make_bus(tmp_path)
    counter = EntryExitCounter(line=[[100, 0], [100, 200]], in_from=-1, buffer_px=5)
    # calibrate the single-person baseline first
    counter.update([(1, (150, 90, 170, 110))], now=0.0, bus=bus)   # width 20, confirmed right
    counter.update([(1, (30, 90, 50, 110))], now=1.0, bus=bus)     # width 20, crosses -> 1 entry
    assert counter.entries == 1
    # now a much wider box (two people merged) crosses the same way
    counter.update([(2, (150, 90, 190, 110))], now=2.0, bus=bus)   # width 40, confirmed right
    counter.update([(2, (10, 90, 50, 110))], now=3.0, bus=bus)     # width 40, crosses -> should count as 2
    assert counter.entries == 3  # 1 (single) + 2 (merged pair)


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
