import time

import pytest

from storesmart.common.camera_check import probe
from storesmart.dashboard import processes


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    """Keep the tests off the real data/processes.json and logs/."""
    monkeypatch.setattr(processes, "STATE_PATH", tmp_path / "processes.json")
    monkeypatch.setattr(processes, "LOG_DIR", tmp_path / "logs")


def test_status_of_unknown_module_is_not_running():
    assert processes.status("nope")["running"] is False


def test_start_status_and_stop_roundtrip():
    # a trivial, harmless python module that stays alive briefly
    ok, msg = processes.start("t", "http.server", ["--bind", "127.0.0.1", "0"], mode="simulate")
    assert ok, msg

    state = processes.status("t")
    assert state["running"] is True
    assert state["mode"] == "simulate"
    assert state["pid"] > 0

    ok, _ = processes.stop("t")
    assert ok
    # give the signal a moment to land
    for _ in range(20):
        if not processes.status("t")["running"]:
            break
        time.sleep(0.1)
    assert processes.status("t")["running"] is False


def test_starting_twice_is_refused():
    processes.start("t", "http.server", ["--bind", "127.0.0.1", "0"])
    ok, msg = processes.start("t", "http.server", ["--bind", "127.0.0.1", "0"])
    assert ok is False
    assert "already running" in msg
    processes.stop("t")


def test_dead_pid_reports_not_running():
    processes.start("t", "http.server", ["--bind", "127.0.0.1", "0"])
    processes.stop("t")
    assert processes.status("t")["running"] is False


def test_probe_simulate_needs_no_camera():
    result = probe("simulate")
    assert result["ok"] is True


def test_probe_bad_source_reports_failure_not_crash():
    result = probe("http://127.0.0.1:1/definitely-not-a-camera.jpg", timeout_s=2)
    assert result["ok"] is False
    assert result["detail"]


def test_probe_never_returns_image_data():
    """The probe reports only metadata — a frame must never leak out of it."""
    result = probe("simulate")
    for value in result.values():
        assert not isinstance(value, (bytes, bytearray))
    assert set(result) <= {"ok", "detail", "width", "height"}
