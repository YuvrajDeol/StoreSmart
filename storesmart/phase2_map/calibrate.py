"""Floor-camera calibration: 4 image points <-> 4 map points (feet) ->
homography, stored in the map JSON. The calibration screen should show the
in-memory people-free background (storesmart.common.privacy.BackgroundEstimator),
never a saved photo."""
from __future__ import annotations

from storesmart.common.geometry import apply_homography, compute_homography
from storesmart.phase2_map.map_model import StoreMap


def calibrate(store_map: StoreMap, image_points: list[list[float]], map_points_ft: list[list[float]]) -> StoreMap:
    if len(image_points) != 4 or len(map_points_ft) != 4:
        raise ValueError("Calibration needs exactly 4 point pairs")
    h = compute_homography(image_points, map_points_ft)
    store_map.homography = h.tolist()
    return store_map


def image_point_to_feet(store_map: StoreMap, point: tuple[float, float]) -> tuple[float, float] | None:
    if store_map.homography is None:
        return None
    import numpy as np

    h = np.array(store_map.homography)
    return apply_homography(h, point)
