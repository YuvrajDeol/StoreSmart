"""Round-trip tests for the store map model, including the optional fields
(background_image, camera facing_deg/fov_deg) added for the sketch-based
map builder. Old store_map.json files predate those keys, so loading without
them must keep working.
"""
import pytest

from storesmart.phase2_map.map_model import Rectangle, StoreMap

OLD_FORMAT = {
    "shop_ft": {"length": 30, "breadth": 20},
    "rectangles": [
        {"type": "shelf", "label": "Snacks", "x": 4, "y": 2, "w": 6, "h": 3},
        {"type": "camera", "label": "Floor Cam", "x": 15, "y": 0.5, "w": 1, "h": 1},
    ],
    "homography": None,
}

NEW_FORMAT = {
    "shop_ft": {"length": 24, "breadth": 16},
    "rectangles": [
        {"type": "shelf", "label": "Dairy", "x": 2, "y": 3, "w": 5, "h": 2},
        {"type": "camera", "label": "Floor Cam", "x": 12, "y": 0.5, "w": 1, "h": 1,
         "facing_deg": 90.0, "fov_deg": 80.0},
    ],
    "homography": None,
    "background_image": "config/store_map_background.png",
}


def test_old_format_without_new_keys_still_loads():
    store_map = StoreMap.from_dict(OLD_FORMAT)
    assert store_map.background_image is None
    assert [r.label for r in store_map.rectangles] == ["Snacks", "Floor Cam"]
    for rect in store_map.rectangles:
        assert rect.facing_deg is None
        assert rect.fov_deg is None


def test_new_optional_fields_survive_a_round_trip():
    store_map = StoreMap.from_dict(NEW_FORMAT)
    assert store_map.background_image == "config/store_map_background.png"

    camera = store_map.cameras()[0]
    assert camera.facing_deg == pytest.approx(90.0)
    assert camera.fov_deg == pytest.approx(80.0)

    again = StoreMap.from_dict(store_map.to_dict())
    assert again.to_dict() == store_map.to_dict()
    assert again.background_image == store_map.background_image
    assert again.cameras()[0].facing_deg == pytest.approx(90.0)


def test_old_format_round_trips_through_to_dict():
    """to_dict() adds the new keys as None; feeding that back must not fail."""
    store_map = StoreMap.from_dict(OLD_FORMAT)
    as_dict = store_map.to_dict()
    assert as_dict["background_image"] is None
    assert as_dict["rectangles"][0]["facing_deg"] is None

    again = StoreMap.from_dict(as_dict)
    assert again.to_dict() == as_dict


def test_non_camera_rectangles_default_to_no_direction():
    shelf = Rectangle(type="shelf", label="Snacks", x=1, y=1, w=2, h=2)
    assert shelf.facing_deg is None
    assert shelf.fov_deg is None


def test_cameras_helper_selects_only_camera_rectangles():
    store_map = StoreMap.from_dict(NEW_FORMAT)
    assert [r.label for r in store_map.cameras()] == ["Floor Cam"]
    assert [r.label for r in store_map.shelves()] == ["Dairy"]
