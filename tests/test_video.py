import numpy as np

from storesmart.common.video import rotate_frame


def _landscape_frame():
    # 40 tall x 80 wide, with a marker pixel at the top-left
    frame = np.zeros((40, 80, 3), dtype=np.uint8)
    frame[0, 0] = (255, 255, 255)
    return frame


def test_no_rotation_returns_same_shape():
    frame = _landscape_frame()
    assert rotate_frame(frame, 0).shape == frame.shape


def test_90_degrees_swaps_width_and_height():
    rotated = rotate_frame(_landscape_frame(), 90)
    assert rotated.shape[:2] == (80, 40)


def test_270_degrees_swaps_width_and_height():
    rotated = rotate_frame(_landscape_frame(), 270)
    assert rotated.shape[:2] == (80, 40)


def test_180_degrees_keeps_shape_and_moves_the_marker():
    frame = _landscape_frame()
    rotated = rotate_frame(frame, 180)
    assert rotated.shape == frame.shape
    # the top-left marker ends up bottom-right
    assert tuple(rotated[-1, -1]) == (255, 255, 255)


def test_90_then_270_restores_the_original():
    frame = _landscape_frame()
    assert np.array_equal(rotate_frame(rotate_frame(frame, 90), 270), frame)


def test_unsupported_angle_is_ignored_rather_than_crashing():
    frame = _landscape_frame()
    assert np.array_equal(rotate_frame(frame, 45), frame)


def test_360_is_treated_as_no_rotation():
    frame = _landscape_frame()
    assert np.array_equal(rotate_frame(frame, 360), frame)
