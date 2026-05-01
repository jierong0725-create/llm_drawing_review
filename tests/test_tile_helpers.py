import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from math import ceil
from app.services.analyzer import compute_tile_grid, _dedup
from app.services.extractor import ExtractedDimension


def test_tile_grid_a4():
    # A4 at 300 DPI ≈ 2480×3508 → should produce ≤ 30 tiles
    tiles, overlap = compute_tile_grid(2480, 3508)
    assert len(tiles) <= 30
    assert overlap >= 200
    # Every pixel must be covered by at least one tile
    covered_x = set()
    covered_y = set()
    for x0, y0, x1, y1 in tiles:
        covered_x.update(range(x0, x1))
        covered_y.update(range(y0, y1))
    assert 0 in covered_x and 2479 in covered_x
    assert 0 in covered_y and 3507 in covered_y


def test_tile_grid_a0():
    # A0 at 300 DPI ≈ 9921×7016 → must not exceed 30 tiles
    tiles, overlap = compute_tile_grid(9921, 7016)
    assert len(tiles) <= 30


def test_tile_grid_no_gaps(w=3000, h=2000):
    tiles, _ = compute_tile_grid(w, h)
    grid = [[False] * w for _ in range(h)]
    for x0, y0, x1, y1 in tiles:
        for y in range(y0, y1):
            for x in range(x0, x1):
                grid[y][x] = True
    assert all(grid[y][x] for y in range(h) for x in range(w))


def _make_dim(value, x, y):
    return ExtractedDimension(
        value=value, nominal=None, tolerance=None,
        dim_type="linear", view_name=None,
        source="llm", anchor_x=float(x), anchor_y=float(y), page=1,
    )


def test_dedup_removes_same_text_nearby():
    dims = [_make_dim("12.5", 100, 100), _make_dim("12.5", 120, 110)]
    result = _dedup(dims, radius=50)
    assert len(result) == 1


def test_dedup_keeps_same_text_far_apart():
    dims = [_make_dim("12.5", 100, 100), _make_dim("12.5", 500, 500)]
    result = _dedup(dims, radius=50)
    assert len(result) == 2


def test_dedup_keeps_different_text_nearby():
    dims = [_make_dim("12.5", 100, 100), _make_dim("R5", 110, 105)]
    result = _dedup(dims, radius=50)
    assert len(result) == 2
