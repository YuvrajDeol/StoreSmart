#!/usr/bin/env python3
"""Dev-only helper: show why the counter is or isn't counting.

Runs the real pipeline pieces against the configured entrance camera and
prints, per sample: how many people the detector found, where each one's
foot point is, how far that is from the entry line, and which side the
counter considers them on. That separates the three usual causes —
no frames, no detections, or geometry that a person never actually crosses.

Frames stay in memory; only numbers are printed.

Usage:  python scripts/dev_only/debug_counting.py [--seconds 25]
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from storesmart.common.config import load_cameras, load_settings  # noqa: E402
from storesmart.common.geometry import signed_distance  # noqa: E402
from storesmart.common.video import open_source  # noqa: E402
from storesmart.phase1_footfall.counter import load_line_config  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=float, default=25)
    args = parser.parse_args()

    settings = load_settings().get("footfall", {})
    buffer_px = settings.get("buffer_px", 40)
    cam_cfg = load_cameras().get("entrance", {})
    print(f"camera : {cam_cfg.get('url')}  rotate={cam_cfg.get('rotate', 0)}")

    source = open_source(cam_cfg)
    if source is None:
        sys.exit("entrance is set to 'simulate' — point it at the phone first")

    frame = None
    deadline = time.time() + 20
    while frame is None and time.time() < deadline:
        frame = source.read()
        time.sleep(0.1)
    if frame is None:
        sys.exit(f"no frames arrived: {getattr(source, 'last_error', 'unknown error')}")

    h, w = frame.shape[:2]
    line_cfg = load_line_config()
    line_px = [[x * w, y * h] for x, y in line_cfg["line"]]
    print(f"frame  : {w}x{h}")
    print(f"line   : ({line_px[0][0]:.0f},{line_px[0][1]:.0f}) -> "
          f"({line_px[1][0]:.0f},{line_px[1][1]:.0f})   buffer={buffer_px}px  "
          f"in_from={line_cfg.get('in_from')}")
    print("\nwatching — walk across the line now\n")

    from storesmart.common.detector import PersonTracker

    tracker = PersonTracker()
    seen_sides: dict[int, int] = {}
    end = time.time() + args.seconds
    samples = 0
    frames_with_people = 0

    while time.time() < end:
        frame = source.read()
        if frame is None:
            continue
        tracks = tracker.update(frame)
        samples += 1
        if not tracks:
            if samples % 15 == 0:
                print(f"  [{samples:3}] no people detected")
            continue
        frames_with_people += 1
        parts = []
        for tid, (x1, y1, x2, y2) in tracks:
            foot = ((x1 + x2) / 2, y2)
            dist = signed_distance(line_px, foot)
            if abs(dist) < buffer_px:
                side = "BUFFER"
            else:
                side = "side +1" if dist > 0 else "side -1"
                s = 1 if dist > 0 else -1
                if tid in seen_sides and seen_sides[tid] != s:
                    side += "  <<< CROSSED"
                seen_sides[tid] = s
            parts.append(f"id{tid} foot=({foot[0]:.0f},{foot[1]:.0f}) "
                         f"dist={dist:+.0f}px w={x2 - x1} {side}")
        print(f"  [{samples:3}] " + " | ".join(parts))

    source.release()
    print(f"\nsummary: {samples} samples, {frames_with_people} had people "
          f"({100 * frames_with_people / max(samples, 1):.0f}%)")
    if frames_with_people == 0:
        print("➜ Nobody was detected. Check rotation, the front-camera inset, "
              "lighting, and that a whole person (not just a face) is in view.")


if __name__ == "__main__":
    main()
