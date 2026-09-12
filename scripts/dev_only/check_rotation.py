#!/usr/bin/env python3
"""Dev-only helper: work out which rotation a camera needs.

Grabs a few frames, tries 0/90/180/270 degrees, runs the person detector on
each, and reports how many people were found and how confident it was. The
rotation with the best detections is the one to put in cameras.yaml.

Frames are held in memory only and never written anywhere — this reports
counts and confidences, nothing else.

Usage:
  python scripts/dev_only/check_rotation.py "http://user:pass@ip:8081/"
"""
import argparse
import sys
import time
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # run as a plain script
from storesmart.common.video import rotate_frame  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source")
    parser.add_argument("--frames", type=int, default=3, help="frames to sample per rotation")
    parser.add_argument("--conf", type=float, default=0.25)
    args = parser.parse_args()

    from ultralytics import YOLO

    model = YOLO("yolov8n.pt")

    capture = cv2.VideoCapture(int(args.source) if args.source.isdigit() else args.source)
    if not capture.isOpened():
        sys.exit(f"Could not open {args.source}")

    # warm up — the first frames off a network stream are often partial
    frames = []
    deadline = time.time() + 30
    while len(frames) < args.frames and time.time() < deadline:
        ok, frame = capture.read()
        if ok and frame is not None:
            frames.append(frame)
    capture.release()

    if not frames:
        sys.exit("No frames arrived from the camera")

    print(f"Sampled {len(frames)} frame(s) at {frames[0].shape[1]}x{frames[0].shape[0]}\n")
    results = []
    for degrees in (0, 90, 180, 270):
        total_people, best_conf = 0, 0.0
        for frame in frames:
            rotated = rotate_frame(frame, degrees)
            detections = model(rotated, classes=[0], conf=args.conf, verbose=False)[0]
            if detections.boxes is not None and len(detections.boxes):
                total_people += len(detections.boxes)
                best_conf = max(best_conf, float(detections.boxes.conf.max()))
        avg = total_people / len(frames)
        results.append((degrees, avg, best_conf))
        print(f"  rotate {degrees:>3}° : {avg:.1f} people/frame, best confidence {best_conf:.2f}")

    best = max(results, key=lambda r: (r[1], r[2]))
    print()
    if best[1] == 0:
        print("No people detected at any rotation — make sure someone is actually in view,")
        print("then re-run. (Also check the front-camera inset is switched off.)")
    else:
        print(f"➜ Use rotate: {best[0]}   ({best[1]:.1f} people/frame, confidence {best[2]:.2f})")


if __name__ == "__main__":
    main()
