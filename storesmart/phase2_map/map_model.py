"""Store map data model: shop dimensions (feet), rectangles (shelf/door/
counter/camera), an optional background floor-plan image, and an optional
homography for the floor camera. Persisted as plain coordinates in
config/store_map.json — never pixels of shoppers.

Note on `background_image`: this holds a path to an owner-supplied floor-plan
sketch or blueprint, NOT a camera frame. It is unrelated to the Zero-Frame
Architecture rule in CLAUDE.md, which governs frames of shoppers captured by
perception modules.

Note on `facing_deg` / `fov_deg`: these describe where a camera rectangle
points, for human layout planning and installer reference ONLY. They are not
consumed by calibrate.py or live_map.py — the homography is computed
independently from 4 clicked point-pairs and does not read these fields.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

from storesmart.common.config import load_json, save_json

DEFAULT_PATH = "config/store_map.json"
EXAMPLE_PATH = "config/store_map.example.json"

RECT_TYPES = ("shelf", "door", "counter", "camera")


@dataclass
class Rectangle:
    type: str
    label: str
    x: float
    y: float
    w: float
    h: float
    # Camera-only, and purely descriptive (see module docstring). Angles are in
    # degrees in map coordinates: 0 deg points along +x (toward increasing
    # length), and angles increase toward +y (toward increasing breadth, which
    # renders as "down" on the preview because the preview's y-axis is
    # inverted). None for every non-camera rectangle.
    facing_deg: float | None = None
    fov_deg: float | None = None


@dataclass
class StoreMap:
    length_ft: float
    breadth_ft: float
    rectangles: list[Rectangle] = field(default_factory=list)
    homography: list[list[float]] | None = None
    # Path to an owner-uploaded floor-plan image, or None. Not a camera frame.
    background_image: str | None = None

    def to_dict(self) -> dict:
        return {
            "shop_ft": {"length": self.length_ft, "breadth": self.breadth_ft},
            "rectangles": [asdict(r) for r in self.rectangles],
            "homography": self.homography,
            "background_image": self.background_image,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "StoreMap":
        shop = data.get("shop_ft", {})
        # Rectangle(**r) tolerates older store_map.json files written before
        # facing_deg/fov_deg existed: the dataclass defaults fill them in.
        rects = [Rectangle(**r) for r in data.get("rectangles", [])]
        return cls(length_ft=shop.get("length", 30), breadth_ft=shop.get("breadth", 20),
                    rectangles=rects, homography=data.get("homography"),
                    background_image=data.get("background_image"))

    def shelves(self) -> list[Rectangle]:
        return [r for r in self.rectangles if r.type == "shelf"]

    def cameras(self) -> list[Rectangle]:
        return [r for r in self.rectangles if r.type == "camera"]


def load_map(path: str = DEFAULT_PATH) -> StoreMap:
    try:
        return StoreMap.from_dict(load_json(path))
    except FileNotFoundError:
        return StoreMap.from_dict(load_json(EXAMPLE_PATH))


def save_map(store_map: StoreMap, path: str = DEFAULT_PATH) -> None:
    save_json(path, store_map.to_dict())
