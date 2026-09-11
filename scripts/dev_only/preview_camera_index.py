#!/usr/bin/env python3
"""Dev-only helper: shows a live preview window for one camera index, so you
can visually confirm which OpenCV index maps to which physical camera
(e.g. MacBook built-in vs iPhone via Continuity Camera). Not used by any
StoreSmart module — purely for local setup/debugging.

Usage: python scripts/dev_only/preview_camera_index.py <index>
Press q to quit.
"""
import sys

import cv2

index = int(sys.argv[1]) if len(sys.argv) > 1 else 0
cap = cv2.VideoCapture(index)
if not cap.isOpened():
    print(f"Could not open camera index {index}")
    sys.exit(1)

print(f"Showing camera index {index} — press q in the window to quit")
while True:
    ok, frame = cap.read()
    if not ok:
        print("Failed to read frame")
        break
    cv2.imshow(f"Camera index {index}", frame)
    if cv2.waitKey(1) & 0xFF == ord("q"):
        break

cap.release()
cv2.destroyAllWindows()
