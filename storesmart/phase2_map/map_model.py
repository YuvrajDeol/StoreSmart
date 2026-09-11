"""Store map data model: shop dimensions (feet), rectangles (shelf/door/
counter/camera), and an optional homography for the floor camera. Persisted
as plain coordinates in config/store_map.json — never pixels."""
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


@dataclass
class StoreMap:
    length_ft: float
    breadth_ft: float
    rectangles: list[Rectangle] = field(default_factory=list)
    homography: list[list[float]] | None = None

    def to_dict(self) -> dict:
        return {
            "shop_ft": {"length": self.length_ft, "breadth": self.breadth_ft},
            "rectangles": [asdict(r) for r in self.rectangles],
            "homography": self.homography,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "StoreMap":
        shop = data.get("shop_ft", {})
        rects = [Rectangle(**r) for r in data.get("rectangles", [])]
        return cls(length_ft=shop.get("length", 30), breadth_ft=shop.get("breadth", 20),
                    rectangles=rects, homography=data.get("homography"))

    def shelves(self) -> list[Rectangle]:
        return [r for r in self.rectangles if r.type == "shelf"]


def load_map(path: str = DEFAULT_PATH) -> StoreMap:
    try:
        return StoreMap.from_dict(load_json(path))
    except FileNotFoundError:
        return StoreMap.from_dict(load_json(EXAMPLE_PATH))


def save_map(store_map: StoreMap, path: str = DEFAULT_PATH) -> None:
    save_json(path, store_map.to_dict())
