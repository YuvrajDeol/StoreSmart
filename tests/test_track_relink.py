from storesmart.phase1_footfall.track_relink import TrackRelinker


def test_relink_within_window_and_distance():
    relinker = TrackRelinker(window_s=3.0, max_px=50)
    relinker.remember(state="left", pos=(100, 100), now=10.0)
    result = relinker.try_relink(pos=(120, 110), now=11.0)  # ~22px away, 1s later
    assert result == "left"


def test_relink_forgets_after_use():
    relinker = TrackRelinker(window_s=3.0, max_px=50)
    relinker.remember(state="left", pos=(100, 100), now=10.0)
    relinker.try_relink(pos=(120, 110), now=11.0)
    # a second lookup at the same spot should find nothing — already consumed
    assert relinker.try_relink(pos=(120, 110), now=11.5) is None


def test_relink_rejects_too_far(tmp_path=None):
    relinker = TrackRelinker(window_s=3.0, max_px=50)
    relinker.remember(state="left", pos=(100, 100), now=10.0)
    assert relinker.try_relink(pos=(500, 500), now=11.0) is None


def test_relink_rejects_too_late():
    relinker = TrackRelinker(window_s=2.0, max_px=50)
    relinker.remember(state="left", pos=(100, 100), now=10.0)
    assert relinker.try_relink(pos=(105, 100), now=13.0) is None  # 3s later, past the window


def test_prune_drops_expired_entries():
    relinker = TrackRelinker(window_s=1.0, max_px=50)
    relinker.remember(state="left", pos=(100, 100), now=10.0)
    relinker.prune(now=12.0)
    assert relinker.try_relink(pos=(100, 100), now=12.0) is None
