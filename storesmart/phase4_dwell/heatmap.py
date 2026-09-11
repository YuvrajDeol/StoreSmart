"""Occupancy heatmap on a 1 ft grid over the map, with small-count
suppression: any cell that fewer than k distinct people ever visited is
hidden from the aggregate output."""
from __future__ import annotations

from collections import defaultdict


def build_heatmap(positions: list[dict], grid_ft: float = 1.0, k: int = 5) -> dict[tuple[int, int], int]:
    """positions: [{"x_ft":..,"y_ft":..,"track":..}, ...]. Returns
    {(gx, gy): occupancy_count} for cells with >= k distinct tracks seen."""
    cell_tracks: dict[tuple[int, int], set[int]] = defaultdict(set)
    for p in positions:
        gx = int(p["x_ft"] // grid_ft)
        gy = int(p["y_ft"] // grid_ft)
        cell_tracks[(gx, gy)].add(p["track"])

    return {cell: len(tracks) for cell, tracks in cell_tracks.items() if len(tracks) >= k}
