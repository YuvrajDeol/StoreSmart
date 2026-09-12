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
    # calibrate the single-person baseline first (needs a handful of samples
    # before the group-size ratio check kicks in — see GroupSizeEstimator)
    for tid in range(5):
        x = 150 + tid  # vary track id/position slightly, same ~20px width each time
        counter.update([(tid, (x, 90, x + 20, 110))], now=tid * 2.0, bus=bus)       # confirmed right
        counter.update([(tid, (x - 120, 90, x - 100, 110))], now=tid * 2.0 + 1, bus=bus)  # crosses -> 1 entry
    assert counter.entries == 5
    # now a much wider box (two people merged) crosses the same way
    counter.update([(99, (150, 90, 190, 110))], now=20.0, bus=bus)   # width 40, confirmed right
    counter.update([(99, (10, 90, 50, 110))], now=21.0, bus=bus)     # width 40, crosses -> should count as 2
    assert counter.entries == 7  # 5 (singles) + 2 (merged pair)


def test_entry_exit_counter_bridges_id_swap_without_phantom_crossing(tmp_path):
    """Regression test for the reported bug: ByteTrack drops a track ID
    during a brief occlusion right at the doorway and reassigns a new ID to
    the same physical person. Without relinking, the new ID's first sighting
    (already confirmed on one side) would look like a fresh person and the
    very next frame's tiny position update could look like a "crossing" —
    inflating the count with a phantom person who never actually walked
    through the line."""
    bus = make_bus(tmp_path)
    counter = EntryExitCounter(line=[[100, 0], [100, 200]], in_from=-1, buffer_px=10, lost_after=0.5)
    # track 1: confirmed on the right (outside) side, then lost (occluded)
    counter.update([(1, (150, 90, 170, 110))], now=0.0, bus=bus)
    # track 1 goes stale (not seen for > lost_after) — simulate by advancing
    # time with no detections at all
    counter.update([], now=1.0, bus=bus)
    # a new track ID appears a moment later, at essentially the same spot —
    # this must be recognized as the same person, not a fresh sighting
    counter.update([(2, (152, 90, 172, 110))], now=1.2, bus=bus)
    assert counter.entries == 0
    assert counter.exits == 0
    # now that (relinked) person actually crosses to the inside
    counter.update([(2, (30, 90, 50, 110))], now=2.0, bus=bus)
    assert counter.entries == 1
    assert counter.exits == 0


def test_counts_crossing_when_track_id_swaps_mid_walk(tmp_path):
    """The reported failure: a solo person walks across and nothing counts.

    ByteTrack reassigns an ID mid-walk and the replacement appears in the very
    next frame — while the old track is not stale yet (that takes lost_after).
    The stale-track relinker therefore had nothing to match against at that
    moment, so the new id looked like a brand-new person and the crossing was
    silently dropped."""
    bus = make_bus(tmp_path)
    counter = EntryExitCounter(line=[[100, 0], [100, 200]], in_from=-1, buffer_px=10,
                                lost_after=1.5)
    # confirmed on the in_from (outside) side as track 1
    counter.update([(1, (150, 90, 170, 110))], now=0.0, bus=bus)
    assert counter.confirmed_side[1] == -1

    # track 1 vanishes and track 2 appears the very next frame, a short walk
    # further on — same person, no stale gap at all
    counter.update([(2, (120, 90, 140, 110))], now=0.1, bus=bus)   # still same side, nearer line
    counter.update([(2, (30, 90, 50, 110))], now=0.6, bus=bus)     # now clearly across

    assert counter.entries == 1, f"crossing lost across the id swap: {list(counter.activity)}"
    assert counter.exits == 0


def test_id_swap_does_not_steal_a_still_tracked_person(tmp_path):
    """Inheriting state must only consider tracks absent from this frame —
    otherwise a second person standing nearby would have their side stolen."""
    bus = make_bus(tmp_path)
    counter = EntryExitCounter(line=[[100, 0], [100, 200]], in_from=-1, buffer_px=10)
    # two people side by side, both confirmed on the same side
    counter.update([(1, (150, 90, 170, 110)), (2, (155, 90, 175, 110))], now=0.0, bus=bus)
    # a third id appears next to them while both are still tracked
    counter.update([(1, (150, 90, 170, 110)), (2, (155, 90, 175, 110)),
                    (3, (152, 90, 172, 110))], now=0.1, bus=bus)
    # nobody's state was stolen: all three are independently tracked
    assert counter.confirmed_side.keys() == {1, 2, 3}
    assert counter.entries == 0 and counter.exits == 0


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
