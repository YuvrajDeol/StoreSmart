"""Start and stop the perception modules from the dashboard.

Streamlit re-runs its script constantly and loses local state, so the running
processes are tracked in a small JSON file instead of session state — that
also means the control page still sees modules that were started before the
dashboard was reloaded, or from a terminal-launched `make sim`.

Children are started in their own process group, so stopping one never
signals the dashboard itself.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
STATE_PATH = REPO_ROOT / "data" / "processes.json"
LOG_DIR = REPO_ROOT / "logs"


def _load() -> dict:
    try:
        return json.loads(STATE_PATH.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2))


def _alive(pid: int, marker: str = "") -> bool:
    """Is this PID still running? `marker` (the module path) guards against
    PID reuse pointing at some unrelated process."""
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, PermissionError, TypeError, OverflowError):
        return False
    if not marker:
        return True
    try:
        out = subprocess.run(["ps", "-p", str(pid), "-o", "command="],
                             capture_output=True, text=True, timeout=3).stdout
        return marker in out
    except Exception:
        return True  # can't verify — assume the PID check was right


def status(name: str) -> dict:
    info = _load().get(name)
    if not info:
        return {"running": False}
    if not _alive(info.get("pid", -1), info.get("marker", "")):
        return {"running": False, "mode": info.get("mode"), "log": info.get("log"),
                "exited": True}
    return {
        "running": True,
        "pid": info["pid"],
        "mode": info.get("mode"),
        "log": info.get("log"),
        "uptime_s": max(0.0, time.time() - info.get("started", time.time())),
        "cmd": info.get("cmd", ""),
    }


def start(name: str, module: str, args: list[str], mode: str = "simulate") -> tuple[bool, str]:
    """Launch `python -m <module> <args>` detached, logging to logs/<name>.log."""
    if status(name)["running"]:
        return False, f"{name} is already running"

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / f"{name}.log"
    cmd = [sys.executable, "-m", module, *args]
    try:
        with open(log_path, "ab") as log:
            log.write(f"\n--- started {time.strftime('%H:%M:%S')}: {' '.join(cmd)}\n".encode())
            log.flush()
            proc = subprocess.Popen(
                cmd, cwd=REPO_ROOT, stdout=log, stderr=subprocess.STDOUT,
                # DEVNULL rather than inheriting: a module that tries to prompt
                # gets EOF and falls back to its default instead of hanging
                # forever on a stdin nobody can type into.
                stdin=subprocess.DEVNULL,
                start_new_session=True,
            )
    except Exception as exc:
        return False, f"could not start {name}: {exc}"

    try:
        log_display = str(log_path.relative_to(REPO_ROOT))
    except ValueError:  # log dir moved outside the repo (e.g. in tests)
        log_display = str(log_path)
    state = _load()
    state[name] = {
        "pid": proc.pid, "marker": module, "mode": mode, "started": time.time(),
        "log": log_display, "cmd": " ".join(cmd),
    }
    _save(state)
    return True, f"started (pid {proc.pid})"


def stop(name: str) -> tuple[bool, str]:
    state = _load()
    info = state.get(name)
    if not info:
        return False, f"{name} is not tracked as running"
    pid = info.get("pid", -1)
    if _alive(pid, info.get("marker", "")):
        try:
            os.killpg(os.getpgid(pid), signal.SIGTERM)
        except Exception:
            try:
                os.kill(pid, signal.SIGTERM)
            except Exception as exc:
                return False, f"could not stop {name}: {exc}"
    state.pop(name, None)
    _save(state)
    return True, f"{name} stopped"


def stop_all() -> list[str]:
    return [stop(name)[1] for name in list(_load().keys())]


def tail_log(name: str, lines: int = 20) -> str:
    path = LOG_DIR / f"{name}.log"
    try:
        return "\n".join(path.read_text(errors="replace").splitlines()[-lines:])
    except FileNotFoundError:
        return "(no log yet)"


def probe_camera(source: str, timeout_s: float = 8.0) -> dict:
    """Shell out to the camera probe so the dashboard process never opens a
    camera itself."""
    try:
        out = subprocess.run(
            [sys.executable, "-m", "storesmart.common.camera_check", source,
             "--timeout", str(timeout_s)],
            cwd=REPO_ROOT, capture_output=True, text=True, timeout=timeout_s + 10,
        )
        line = (out.stdout or "").strip().splitlines()
        return json.loads(line[-1]) if line else {"ok": False, "detail": out.stderr.strip()[:300] or "no output"}
    except Exception as exc:
        return {"ok": False, "detail": f"probe failed: {exc}"}
