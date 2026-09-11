#!/usr/bin/env python3
"""Probe a camera source and report whether a frame can be read.

Prints a single line of JSON and exits. The frame is held in memory only for
long enough to check it decoded — it is never displayed, written or
transmitted, and only its dimensions (metadata, not pixels) are reported.

This exists as a standalone CLI so the *dashboard* never opens a camera
itself: it shells out, reads the text result, and stays on the safe side of
the Zero-Frame boundary described in CLAUDE.md.

Usage:
  python -m storesmart.common.camera_check simulate
  python -m storesmart.common.camera_check 0
  python -m storesmart.common.camera_check http://192.168.1.7:8080/video
"""
from __future__ import annotations

import argparse
import json
import time


def probe(source: str, timeout_s: float = 8.0) -> dict:
    if source.strip() == "simulate":
        return {"ok": True, "detail": "simulate — no camera needed"}

    import cv2

    # Snapshot endpoints (IP Webcam's /shot.jpg) are a single JPEG, not a
    # stream, so fetch and decode them directly.
    if source.lower().endswith((".jpg", ".jpeg", ".png")):
        try:
            import numpy as np
            import requests

            resp = requests.get(source, timeout=timeout_s)
            resp.raise_for_status()
            frame = cv2.imdecode(np.frombuffer(resp.content, dtype=np.uint8), cv2.IMREAD_COLOR)
            if frame is None:
                return {"ok": False, "detail": "reached the URL but could not decode an image"}
            h, w = frame.shape[:2]
            return {"ok": True, "detail": "snapshot OK", "width": int(w), "height": int(h)}
        except Exception as exc:
            return {"ok": False, "detail": f"cannot reach {source} — {exc}"}

    capture = cv2.VideoCapture(int(source) if source.isdigit() else source)
    try:
        if not capture.isOpened():
            return {"ok": False, "detail": f"could not open source {source!r} — "
                                           "check the URL/index, Wi-Fi or hotspot"}
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            ok, frame = capture.read()
            if ok and frame is not None:
                h, w = frame.shape[:2]
                return {"ok": True, "detail": "stream OK", "width": int(w), "height": int(h)}
            time.sleep(0.1)
        return {"ok": False, "detail": f"opened {source!r} but no frame arrived within {timeout_s:.0f}s"}
    finally:
        capture.release()


def list_cameras(max_index: int = 4) -> dict:
    """What capture devices exist right now.

    On macOS, `system_profiler` gives the device *names*, which is the only
    way to tell a Continuity Camera iPhone apart from the built-in webcam —
    OpenCV exposes indices with no names at all. An iPhone that is asleep or
    has no active Continuity session simply won't be listed, which is the
    usual reason live mode "can't find" it.
    """
    import platform
    import subprocess

    names: list[str] = []
    if platform.system() == "Darwin":
        try:
            out = subprocess.run(["system_profiler", "SPCameraDataType", "-json"],
                                 capture_output=True, text=True, timeout=25)
            for entry in json.loads(out.stdout or "{}").get("SPCameraDataType", []):
                name = entry.get("_name")
                if name:
                    names.append(name)
        except Exception:
            pass

    import cv2

    working: list[int] = []
    for index in range(max_index):
        capture = cv2.VideoCapture(index)
        try:
            if capture.isOpened():
                ok, frame = capture.read()
                if ok and frame is not None:
                    working.append(index)
        except Exception:
            pass
        finally:
            capture.release()

    return {"names": names, "open_indices": working}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", nargs="?", default=None,
                        help="'simulate', a webcam index, a stream/snapshot URL, or a file")
    parser.add_argument("--list", action="store_true", help="list available cameras instead of probing")
    parser.add_argument("--timeout", type=float, default=8.0)
    args = parser.parse_args()
    if args.list:
        print(json.dumps(list_cameras()))
    elif args.source:
        print(json.dumps(probe(args.source, args.timeout)))
    else:
        parser.error("give a source to probe, or --list")


if __name__ == "__main__":
    main()
