"""Pure geometry helpers: line crossing, polygon containment, homography.

No frame data touches this module — only points and matrices.
"""
from __future__ import annotations

import math
from typing import Optional, Sequence

import cv2
import numpy as np


def signed_distance(line: Sequence[Sequence[float]], point: Sequence[float]) -> float:
    """Signed perpendicular distance from `point` to the line through the two
    points in `line`. Sign flips across the line."""
    (ax, ay), (bx, by) = line
    px, py = point
    return ((bx - ax) * (py - ay) - (by - ay) * (px - ax)) / (math.hypot(bx - ax, by - ay) + 1e-6)


def side_of_line(line: Sequence[Sequence[float]], point: Sequence[float], margin: float = 0.0) -> int:
    """Returns -1, 0 (within margin/dead-band), or +1."""
    d = signed_distance(line, point)
    if d > margin:
        return 1
    if d < -margin:
        return -1
    return 0


def point_in_polygon(polygon: Optional[np.ndarray], point: Sequence[float]) -> bool:
    if polygon is None:
        return False
    return cv2.pointPolygonTest(polygon, (float(point[0]), float(point[1])), False) >= 0


def compute_homography(image_points: Sequence[Sequence[float]], map_points_ft: Sequence[Sequence[float]]) -> np.ndarray:
    """4-point homography mapping image pixel coordinates to map feet."""
    src = np.array(image_points, dtype=np.float32)
    dst = np.array(map_points_ft, dtype=np.float32)
    h, _ = cv2.findHomography(src, dst, method=0)
    if h is None:
        raise ValueError("Could not compute homography from the given points")
    return h


def apply_homography(h: np.ndarray, point: Sequence[float]) -> tuple[float, float]:
    px, py = point
    vec = np.array([px, py, 1.0])
    out = h @ vec
    out /= out[2]
    return float(out[0]), float(out[1])


def expand_rect(rect: dict, margin_ft: float) -> dict:
    """Expand a {x,y,w,h} rectangle (feet) outward by margin_ft on all sides."""
    return {
        "x": rect["x"] - margin_ft,
        "y": rect["y"] - margin_ft,
        "w": rect["w"] + 2 * margin_ft,
        "h": rect["h"] + 2 * margin_ft,
    }


def point_in_rect(rect: dict, point: Sequence[float]) -> bool:
    x, y = point
    return rect["x"] <= x <= rect["x"] + rect["w"] and rect["y"] <= y <= rect["y"] + rect["h"]
