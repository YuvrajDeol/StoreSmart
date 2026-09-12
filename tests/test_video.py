import numpy as np

from storesmart.common.video import MjpegStreamReader, is_snapshot_url, rotate_frame


def _part(payload: bytes) -> bytes:
    return b"--BoundaryString\r\nContent-type: image/jpeg\r\nContent-Length: " \
           + str(len(payload)).encode() + b"\r\n\r\n" + payload


def test_mjpeg_parser_extracts_a_complete_part():
    payload = b"\xff\xd8" + b"body-bytes" + b"\xff\xd9"
    buffer = bytearray(_part(payload))
    assert MjpegStreamReader._take_latest_jpeg(buffer) == payload


def test_mjpeg_parser_survives_nested_jpeg_markers():
    """Phone cameras embed an EXIF thumbnail, so a frame contains nested
    SOI/EOI markers. Scanning for markers slices out a corrupt image that
    never decodes — the part's Content-Length must be used instead."""
    thumbnail = b"\xff\xd8" + b"thumb" + b"\xff\xd9"
    payload = b"\xff\xd8" + b"header" + thumbnail + b"real-image-data" + b"\xff\xd9"
    buffer = bytearray(_part(payload))
    assert MjpegStreamReader._take_latest_jpeg(buffer) == payload


def test_mjpeg_parser_returns_the_newest_of_several_parts():
    first = b"\xff\xd8first\xff\xd9"
    second = b"\xff\xd8second\xff\xd9"
    buffer = bytearray(_part(first) + _part(second))
    assert MjpegStreamReader._take_latest_jpeg(buffer) == second
    assert len(buffer) < 40  # both parts consumed


def test_mjpeg_parser_waits_for_an_incomplete_part():
    payload = b"\xff\xd8" + b"x" * 50 + b"\xff\xd9"
    truncated = _part(payload)[:-20]
    buffer = bytearray(truncated)
    before = len(buffer)
    assert MjpegStreamReader._take_latest_jpeg(buffer) is None
    assert len(buffer) == before  # nothing consumed; wait for the rest


def test_snapshot_urls_are_recognised():
    assert is_snapshot_url("http://host:8080/shot.jpg") is True
    assert is_snapshot_url("http://host:8080/shot.jpg?x=1") is True
    assert is_snapshot_url("http://host:8081/video") is False


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
