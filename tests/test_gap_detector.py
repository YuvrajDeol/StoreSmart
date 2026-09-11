import numpy as np

from storesmart.phase3_shelf.gap_detector import GapDetector

SLOTS = [{"slot": "A1", "item_id": 1, "x": 0, "y": 0, "w": 50, "h": 50}]
WHITE_HSV_LOWER = [0, 0, 180]
WHITE_HSV_UPPER = [180, 40, 255]


def full_shelf_frame():
    frame = np.full((50, 50, 3), (60, 140, 200), np.uint8)  # product color, no backdrop visible
    return frame


def empty_shelf_frame():
    return np.full((50, 50, 3), (235, 235, 235), np.uint8)  # all backdrop


def test_full_shelf_reports_ok():
    detector = GapDetector(SLOTS, WHITE_HSV_LOWER, WHITE_HSV_UPPER, confirm_frames=1)
    changes = detector.update(full_shelf_frame(), [])
    assert changes == []  # starts at 'ok', stays 'ok' -> no change event
    assert detector.states["A1"].state == "ok"


def test_empty_shelf_confirmed_after_two_frames():
    detector = GapDetector(SLOTS, WHITE_HSV_LOWER, WHITE_HSV_UPPER, confirm_frames=2)
    changes1 = detector.update(empty_shelf_frame(), [])
    assert changes1 == []  # first frame only starts the pending count
    changes2 = detector.update(empty_shelf_frame(), [])
    assert changes2 == [("A1", "empty")]
    assert detector.states["A1"].state == "empty"


def test_person_overlap_skips_slot():
    detector = GapDetector(SLOTS, WHITE_HSV_LOWER, WHITE_HSV_UPPER, confirm_frames=1)
    person_boxes = [(0, 0, 50, 50)]  # covers the whole slot
    changes = detector.update(empty_shelf_frame(), person_boxes)
    assert changes == []
    assert detector.states["A1"].state == "ok"  # unchanged, snapshot was skipped


def test_one_off_glitch_does_not_change_confirmed_state():
    detector = GapDetector(SLOTS, WHITE_HSV_LOWER, WHITE_HSV_UPPER, confirm_frames=2)
    detector.update(full_shelf_frame(), [])
    changes = detector.update(empty_shelf_frame(), [])  # single glitch frame
    assert changes == []
    assert detector.states["A1"].state == "ok"
