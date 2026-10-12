from edge_lab.shelf_watch import Det, ShelfWatcher

BOTTLE = Det("bottle", (100, 100, 140, 200), 0.9)
CUP = Det("cup", (300, 100, 340, 160), 0.8)


def mk():
    w = ShelfWatcher(frame_width=640, debounce=5)
    w.set_baseline([BOTTLE, CUP])
    return w


def test_taken_after_n_frames():
    w = mk()
    for _ in range(4):
        _, missing, _ = w.update([CUP])
        assert missing == []
    _, missing, _ = w.update([CUP])
    assert [m.cls for m in missing] == ["bottle"]
    assert any("bottle TAKEN" in e for e in w.log)


def test_single_dropout_ignored():
    w = mk()
    w.update([BOTTLE, CUP])
    _, missing, _ = w.update([CUP])  # one dropped frame
    assert missing == []
    for _ in range(10):
        _, missing, _ = w.update([BOTTLE, CUP])
    assert missing == [] and not any("TAKEN" in e for e in w.log)


def test_returned_item_restored():
    w = mk()
    for _ in range(5):
        w.update([CUP])
    for i in range(5):
        present, missing, _ = w.update([BOTTLE, CUP])
        assert (len(missing) == 1) == (i < 4)
    assert missing == [] and len(present) == 2
    assert any("bottle returned" in e for e in w.log)


def test_wrong_class_or_far_does_not_match():
    w = mk()
    far = Det("bottle", (500, 100, 540, 200))
    for _ in range(5):
        _, missing, added = w.update([CUP, far])
    assert [m.cls for m in missing] == ["bottle"] and len(added) == 1
