from storesmart.common.bus import EventBus
from storesmart.phase1_footfall.doorway import DoorwayCounter

RECT = {"x": 100, "y": 0, "w": 100, "h": 200}  # pixel-space doorway rectangle


def make_bus(tmp_path):
    return EventBus(db_path=tmp_path / "test.db")


def test_track_entering_rectangle_counts_as_entry(tmp_path):
    bus = make_bus(tmp_path)
    counter = DoorwayCounter(rect=RECT)
    counter.update([(1, (0, 50, 20, 70))], now=0.0, bus=bus)     # outside the rect
    counter.update([(1, (130, 50, 150, 70))], now=1.0, bus=bus)  # now inside
    assert counter.entries == 1
    assert counter.exits == 0
    assert counter.inside == 1


def test_track_leaving_rectangle_counts_as_exit(tmp_path):
    bus = make_bus(tmp_path)
    counter = DoorwayCounter(rect=RECT)
    counter.update([(1, (130, 50, 150, 70))], now=0.0, bus=bus)  # starts inside
    counter.update([(1, (0, 50, 20, 70))], now=1.0, bus=bus)     # leaves
    assert counter.entries == 0
    assert counter.exits == 1


def test_track_already_inside_at_first_sighting_not_counted(tmp_path):
    """A person standing in the doorway when tracking starts shouldn't be
    miscounted as a fresh entry — only an actual crossing counts."""
    bus = make_bus(tmp_path)
    counter = DoorwayCounter(rect=RECT)
    counter.update([(1, (130, 50, 150, 70))], now=0.0, bus=bus)  # first sighting, already inside
    assert counter.entries == 0
    assert counter.exits == 0


def test_track_staying_inside_does_not_double_count(tmp_path):
    bus = make_bus(tmp_path)
    counter = DoorwayCounter(rect=RECT)
    counter.update([(1, (0, 50, 20, 70))], now=0.0, bus=bus)
    counter.update([(1, (130, 50, 150, 70))], now=1.0, bus=bus)
    counter.update([(1, (135, 55, 155, 75))], now=2.0, bus=bus)  # still inside
    assert counter.entries == 1


def test_doorway_counter_initial_inside_baseline(tmp_path):
    bus = make_bus(tmp_path)
    counter = DoorwayCounter(rect=RECT, initial_inside=2)
    assert counter.inside == 2
    counter.update([(1, (0, 50, 20, 70))], now=0.0, bus=bus)     # outside
    counter.update([(1, (130, 50, 150, 70))], now=1.0, bus=bus)  # enters -> +1
    counter.update([(1, (0, 50, 20, 70))], now=2.0, bus=bus)     # leaves -> -1
    assert counter.inside == 2  # back to baseline, never dipped negative/stuck


def test_stale_track_is_forgotten(tmp_path):
    bus = make_bus(tmp_path)
    counter = DoorwayCounter(rect=RECT, lost_after=1.0)
    counter.update([(1, (130, 50, 150, 70))], now=0.0, bus=bus)
    counter.update([], now=5.0, bus=bus)  # track lost, well past lost_after
    # if track 1 reappears "inside" later it's treated as a fresh sighting, not an exit
    counter.update([(1, (130, 50, 150, 70))], now=6.0, bus=bus)
    assert counter.exits == 0
