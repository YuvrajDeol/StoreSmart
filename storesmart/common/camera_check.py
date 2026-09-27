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


def _http_precheck(source: str, timeout_s: float) -> dict | None:
    """For http(s) sources, check the status code before handing the URL to
    OpenCV — otherwise a password-protected camera just looks like a dead
    one, which sends people hunting for network problems that don't exist."""
    if not source.lower().startswith(("http://", "https://")):
        return None
    try:
        import requests

        resp = requests.get(source, timeout=min(timeout_s, 6), stream=True)
        status = resp.status_code
        realm = resp.headers.get("WWW-Authenticate", "")
        resp.close()
        if status == 401:
            return {"ok": False, "needs_auth": True, "detail": (
                "the camera requires a username and password"
                + (f' ({realm})' if realm else "")
                + ". Put them in the URL: http://USER:PASS@host:port/path — "
                  "or turn the password off in the phone app."
            )}
        if status == 404:
            return {"ok": False, "detail": f"reached the server, but path not found (404). "
                                           f"Check the path the app shows (often /video or /live)."}
        if status >= 500:
            return {"ok": False, "detail": f"the camera server returned HTTP {status}"}
    except Exception:
        return None  # not conclusive — let OpenCV have its own try
    return None


def probe(source: str, timeout_s: float = 8.0) -> dict:
    if source.strip() == "simulate":
        return {"ok": True, "detail": "simulate — no camera needed"}

    precheck = _http_precheck(source, timeout_s)
    if precheck is not None:
        return precheck

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

    # http(s) video streams are read the same way the modules read them
    # (requests, not FFmpeg), so a passing test means the real thing works.
    if source.lower().startswith(("http://", "https://")):
        from storesmart.common.video import MjpegStreamReader

        reader = MjpegStreamReader(source, proc_width=10_000, timeout_s=timeout_s)
        try:
            deadline = time.time() + timeout_s
            while time.time() < deadline:
                frame = reader.read()
                if frame is not None:
                    h, w = frame.shape[:2]
                    return {"ok": True, "detail": "stream OK",
                            "width": int(w), "height": int(h)}
                time.sleep(0.2)
            return {"ok": False, "detail": reader.last_error
                    or f"connected to {source} but no frame decoded within {timeout_s:.0f}s"}
        finally:
            reader.release()

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


#: Ports the common phone IP-camera apps serve on (IP Webcam, IP Camera Lite,
#: DroidCam, and the RTSP/RTMP variants some of them expose).
CAMERA_PORTS = (8080, 8081, 4747, 8082, 8090, 8000, 80, 554, 8554, 1935)


def scan_network(timeout_s: float = 0.4, max_hosts: int = 64) -> dict:
    """Look for phone camera servers on this machine's local subnet.

    A phone hotspot subnet is tiny (a /28), so this is near-instant there;
    on a big /24 it is capped to the first `max_hosts` addresses. Only
    connectivity is tested — no frame is fetched here.
    """
    import ipaddress
    import socket
    from concurrent.futures import ThreadPoolExecutor

    # local IPv4 + netmask
    local_ip, netmask = None, None
    try:
        import subprocess

        out = subprocess.run(["ifconfig"], capture_output=True, text=True, timeout=10).stdout
        for line in out.splitlines():
            line = line.strip()
            if line.startswith("inet ") and "127.0.0.1" not in line:
                parts = line.split()
                local_ip = parts[1]
                if "netmask" in parts:
                    netmask = parts[parts.index("netmask") + 1]
                break
    except Exception:
        pass
    if not local_ip:
        return {"error": "could not determine this machine's IP"}

    try:
        bits = bin(int(netmask, 16)).count("1") if netmask and netmask.startswith("0x") else 24
        network = ipaddress.ip_network(f"{local_ip}/{bits}", strict=False)
    except Exception:
        network = ipaddress.ip_network(f"{local_ip}/24", strict=False)

    hosts = [str(h) for h in network.hosts()][:max_hosts]

    def check(target: tuple[str, int]):
        host, port = target
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout_s)
        try:
            if sock.connect_ex((host, port)) == 0:
                return host, port
        except Exception:
            pass
        finally:
            sock.close()
        return None

    targets = [(h, p) for h in hosts for p in CAMERA_PORTS if h != local_ip]
    found: list[dict] = []
    with ThreadPoolExecutor(max_workers=64) as pool:
        for result in pool.map(check, targets):
            if result:
                host, port = result
                scheme = "rtsp" if port in (554, 8554) else ("rtmp" if port == 1935 else "http")
                found.append({"host": host, "port": port, "scheme": scheme})

    return {"scanned": f"{network} ({len(hosts)} hosts)", "local_ip": local_ip, "found": found}


def find_camera_url(configured_url: str, timeout_s: float = 6.0) -> str | None:
    """Find the camera again after its address changed.

    A phone's IP changes every time it moves between Wi-Fi and its own
    hotspot, which otherwise means editing config mid-demo. Scans the local
    subnet for a camera server and rebuilds the configured URL against
    whatever it finds — keeping the scheme, credentials and path, since only
    the host and port actually change.
    """
    from urllib.parse import urlsplit, urlunsplit

    parts = urlsplit(configured_url)
    credentials = ""
    if parts.username:
        credentials = parts.username + (f":{parts.password}" if parts.password else "") + "@"
    path = parts.path or "/"

    for entry in scan_network().get("found", []):
        if entry["scheme"] != "http":
            continue
        candidate = urlunsplit(("http", f"{credentials}{entry['host']}:{entry['port']}",
                                path, "", ""))
        if probe(candidate, timeout_s).get("ok"):
            return candidate
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", nargs="?", default=None,
                        help="'simulate', a webcam index, a stream/snapshot URL, or a file")
    parser.add_argument("--list", action="store_true", help="list available cameras instead of probing")
    parser.add_argument("--scan", action="store_true",
                        help="scan the local network for phone camera servers")
    parser.add_argument("--timeout", type=float, default=8.0)
    args = parser.parse_args()
    if args.list:
        print(json.dumps(list_cameras()))
    elif args.scan:
        print(json.dumps(scan_network()))
    elif args.source:
        print(json.dumps(probe(args.source, args.timeout)))
    else:
        parser.error("give a source to probe, or --list")


if __name__ == "__main__":
    main()
