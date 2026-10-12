"""Entry-line setup for edge_lab.

History worth keeping: a non-blocking rewrite drove the clicks from the main
render loop, which meant every click had to be mapped back through the title
banner stacked on the frame and through the window's own scaling. It never
worked reliably. edge_lab now reuses the blocking loop that
storesmart/phase1_footfall/run.py has always used, where the window shows the
bare frame at its own size so a click is already in frame coordinates.

These tests drive that loop headlessly by faking cv2's window callbacks.
"""
import numpy as np
import pytest

import edge_lab.app as app


class FakeCv2:
    """Minimal stand-in: records the mouse callback, then feeds it clicks."""

    EVENT_LBUTTONDOWN = 1
    LINE_AA = 16
    FONT_HERSHEY_SIMPLEX = 0

    def __init__(self, clicks, keys=None):
        self._clicks = list(clicks)
        self._keys = list(keys or [])
        self._cb = None
        self.shown = 0

    def setMouseCallback(self, win, cb):
        self._cb = cb

    def imshow(self, win, img):
        self.shown += 1

    def waitKey(self, _ms):
        # deliver one queued click per displayed frame
        if self._clicks and self._cb:
            x, y = self._clicks.pop(0)
            self._cb(self.EVENT_LBUTTONDOWN, x, y)
        return self._keys.pop(0) if self._keys else 255

    def circle(self, *a, **k):
        pass

    def line(self, *a, **k):
        pass

    def putText(self, *a, **k):
        pass


@pytest.fixture
def frame():
    return np.zeros((480, 640, 3), np.uint8)


def run(monkeypatch, clicks, frame, keys=None):
    fake = FakeCv2(clicks, keys)
    monkeypatch.setattr(app, "cv2", fake)
    return app.draw_line_blocking("win", lambda: frame)


def test_three_clicks_produce_a_line_and_direction(monkeypatch, frame):
    out = run(monkeypatch, [(320, 10), (320, 400), (100, 200)], frame)
    assert out is not None
    line_px, in_from = out
    assert line_px == [(320, 10), (320, 400)]
    assert in_from in (1, -1)


def test_clicks_are_used_as_frame_coordinates_unchanged(monkeypatch, frame):
    """The whole point of the blocking loop: no banner, no window scaling, so
    a click needs no correction to become a frame coordinate."""
    line_px, _ = run(monkeypatch, [(11, 22), (33, 44), (55, 66)], frame)
    assert line_px == [(11, 22), (33, 44)]


def test_outside_point_flips_the_direction(monkeypatch, frame):
    _, left = run(monkeypatch, [(320, 10), (320, 400), (100, 200)], frame)
    _, right = run(monkeypatch, [(320, 10), (320, 400), (540, 200)], frame)
    assert left == -right


def test_escape_cancels(monkeypatch, frame):
    # no clicks; first waitKey returns ESC
    assert run(monkeypatch, [], frame, keys=[27]) is None


def test_no_frames_available_does_not_hang(monkeypatch):
    fake = FakeCv2([], keys=[27])
    monkeypatch.setattr(app, "cv2", fake)
    assert app.draw_line_blocking("win", lambda: None) is None
