import base64

import pytest

from storesmart.common.events import EventGate, MAX_EVENT_BYTES, RejectedEvent


@pytest.fixture
def gate():
    return EventGate()


def test_valid_entry_event_accepted(gate):
    event = gate.validate({"t": "2026-01-01T00:00:00Z", "cam": "entrance", "type": "entry"})
    assert event.type == "entry"
    assert gate.accepted == 1
    assert gate.rejected == 0


def test_valid_queue_event_accepted(gate):
    event = gate.validate({
        "t": "2026-01-01T00:00:00Z", "cam": "counter", "type": "queue",
        "length": 4, "serving": 1, "counters": 1, "wait_s": 24.0, "forecast_wait_s": 38.0,
    })
    assert event.length == 4


def test_unknown_event_type_rejected(gate):
    with pytest.raises(RejectedEvent):
        gate.validate({"t": "x", "type": "face_recognized", "name": "bob"})
    assert gate.rejected == 1


def test_extra_field_rejected(gate):
    with pytest.raises(RejectedEvent):
        gate.validate({"t": "x", "type": "entry", "extra_field": "nope"})
    assert gate.rejected == 1


def test_image_blob_rejected(gate):
    """The critical privacy test: an event carrying a base64 image must never
    be accepted, even if it also has otherwise-valid fields."""
    fake_jpeg_b64 = base64.b64encode(b"\xff\xd8\xff\xe0fakejpegbytes").decode()
    with pytest.raises(RejectedEvent):
        gate.validate({
            "t": "2026-01-01T00:00:00Z", "cam": "entrance", "type": "entry",
            "image_base64": fake_jpeg_b64,
        })
    assert gate.rejected == 1


def test_oversized_event_rejected(gate):
    with pytest.raises(RejectedEvent):
        gate.validate({
            "t": "2026-01-01T00:00:00Z", "type": "alert", "kind": "layout",
            "msg": "x" * (MAX_EVENT_BYTES + 10), "severity": "info",
        })
    assert gate.rejected == 1


def test_summary_event_alias(gate):
    event = gate.validate({"t": "x", "type": "summary", "in": 5, "out": 2, "inside": 3})
    assert event.in_ == 5
