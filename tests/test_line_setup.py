"""Click -> frame coordinate mapping for the entry-line setup.

Regression: clicks arrive in window coordinates, but were stored as if they
were frame coordinates. Two things break that — the title banner stacked on
top of the frame, and the resizable window scaling the image — so the drawn
line landed nowhere near where it was clicked.
"""
import cv2

from edge_lab.app import LineSetup

BANNER_H = 26
FRAME = (640, 480)  # w, h


def click(setup, x, y):
    setup.on_mouse(cv2.EVENT_LBUTTONDOWN, x, y)


def test_banner_offset_is_subtracted():
    setup = LineSetup()
    setup.start()
    setup.set_transform(1.0, BANNER_H, FRAME)
    click(setup, 100, 126)
    assert setup.pts == [(100, 100)]  # 126 on screen is 100 in the frame


def test_window_scaling_is_undone():
    """Window showing the view at half size: a click at (50, 63) on screen is
    (100, 100) in the frame once the banner is also accounted for."""
    setup = LineSetup()
    setup.start()
    setup.set_transform(0.5, BANNER_H, FRAME)
    click(setup, 50, 63)
    assert setup.pts == [(100, 100)]


def test_clicks_are_clamped_into_the_frame():
    setup = LineSetup()
    setup.start()
    setup.set_transform(1.0, BANNER_H, FRAME)
    click(setup, 5, 5)          # on the banner itself -> would be negative
    click(setup, 9999, 9999)    # past the far corner
    assert setup.pts[0] == (5, 0)
    assert setup.pts[1] == (639, 479)


def test_only_three_points_are_taken_and_only_while_active():
    setup = LineSetup()
    setup.set_transform(1.0, BANNER_H, FRAME)
    click(setup, 10, 40)                      # inactive — ignored
    assert setup.pts == []
    setup.start()
    for i in range(5):
        click(setup, 10 + i, 40)
    assert len(setup.pts) == 3


def test_result_returns_line_and_direction_then_deactivates():
    setup = LineSetup()
    setup.start()
    setup.set_transform(1.0, BANNER_H, FRAME)
    click(setup, 320, 26 + 10)    # line top
    click(setup, 320, 26 + 400)   # line bottom
    click(setup, 100, 26 + 200)   # outside point, left of the line
    out = setup.result(*FRAME)
    assert out is not None
    line_px, in_from = out
    assert line_px == [(320, 10), (320, 400)]
    assert in_from in (1, -1)
    assert setup.active is False


def test_result_is_none_before_three_clicks():
    setup = LineSetup()
    setup.start()
    setup.set_transform(1.0, BANNER_H, FRAME)
    click(setup, 320, 36)
    assert setup.result(*FRAME) is None
