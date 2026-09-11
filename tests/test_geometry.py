import numpy as np
import pytest

from storesmart.common.geometry import (
    apply_homography,
    compute_homography,
    expand_rect,
    point_in_polygon,
    point_in_rect,
    side_of_line,
    signed_distance,
)


def test_signed_distance_sign_flips_across_line():
    line = [[0, 0], [0, 10]]
    one_side = signed_distance(line, (5, 5))
    other_side = signed_distance(line, (-5, 5))
    assert (one_side > 0) != (other_side > 0)
    assert one_side == pytest.approx(-other_side)


def test_side_of_line_margin_dead_band():
    line = [[0, 0], [0, 10]]
    right_side = side_of_line(line, (5, 5), margin=1)
    left_side = side_of_line(line, (-5, 5), margin=1)
    assert right_side == -left_side
    assert {right_side, left_side} == {1, -1}
    assert side_of_line(line, (0.5, 5), margin=1) == 0


def test_point_in_polygon():
    poly = np.array([[0, 0], [10, 0], [10, 10], [0, 10]], dtype=np.float32)
    assert point_in_polygon(poly, (5, 5)) is True
    assert point_in_polygon(poly, (50, 50)) is False


def test_point_in_polygon_none_is_false():
    assert point_in_polygon(None, (5, 5)) is False


def test_homography_round_trip():
    image_pts = [[0, 0], [100, 0], [100, 100], [0, 100]]
    map_pts_ft = [[0, 0], [20, 0], [20, 20], [0, 20]]
    h = compute_homography(image_pts, map_pts_ft)
    x, y = apply_homography(h, (50, 50))
    assert x == pytest.approx(10, abs=0.5)
    assert y == pytest.approx(10, abs=0.5)


def test_expand_rect():
    rect = {"x": 5, "y": 5, "w": 4, "h": 2}
    expanded = expand_rect(rect, 1.5)
    assert expanded == {"x": 3.5, "y": 3.5, "w": 7, "h": 5}


def test_point_in_rect():
    rect = {"x": 0, "y": 0, "w": 10, "h": 10}
    assert point_in_rect(rect, (5, 5)) is True
    assert point_in_rect(rect, (15, 5)) is False
