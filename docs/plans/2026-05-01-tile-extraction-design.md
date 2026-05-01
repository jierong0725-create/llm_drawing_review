# Tile-Based Dimension Extraction Design

**Date:** 2026-05-01  
**Replaces:** Phase 1 (view detection) + Phase 2b (per-view LLM extraction) + Phase 4 (verify_coverage)

---

## Problem

Current Phase 1 asks the LLM to understand drawing structure (view types, bounding boxes). This is:
- Fragile — LLM must interpret semantic content
- Low-resolution — A0 drawings downscaled to 1600px lose fine text
- Expensive — two LLM passes per view (extract + verify)

## Approach

Split the full-resolution drawing image into overlapping tiles. Run a simple extraction prompt on each tile in parallel. Merge results with deduplication. A lightweight Phase 1 call still detects excluded regions (title block, tolerance notes, etc.) on a downscaled image — this remains reliable at low resolution.

---

## Architecture

```
PDF → full-res PIL image
        │
        ├─► detect_excluded_regions()   (1× LLM, downscaled image, excluded bboxes only)
        │
        └─► extract_dimensions_tiled()
                │
                ├── compute_tile_grid(w, h)   → list of (x0,y0,x1,y1) tiles
                ├── parallel LLM per tile      → raw dims with tile-local coords
                ├── map coords to full-image space
                ├── deduplicate overlap regions
                └── filter by excluded_regions
                        │
                        ▼
                list[ExtractedDimension]  (view_name=None)
```

---

## Tile Grid Strategy

| Paper size | Full-res pixels (300 DPI) | Approx tiles | tile_size |
|-----------|--------------------------|-------------|-----------|
| A4 / A3   | ~2500–3500 px            | 4–9         | 1400 px   |
| A2 / A1   | ~5000–7000 px            | 12–20       | 1600 px   |
| A0        | ~9900 × 7000 px          | ≤ 30        | 2200 px   |

**Dynamic computation:**
```python
TARGET_MAX_TILES = 30
BASE_TILE_SIZE   = 1400
OVERLAP          = 200

def compute_tile_size(w: int, h: int) -> tuple[int, int]:
    for tile in range(BASE_TILE_SIZE, 3100, 100):
        stride = tile - OVERLAP
        if ceil(w / stride) * ceil(h / stride) <= TARGET_MAX_TILES:
            return tile, OVERLAP
    return 3000, 300
```

---

## Simplified Phase 1 — Excluded Regions Only

Prompt reduced to ~20 lines (STEP 1 only from old prompt). Returns:

```json
{
  "excluded_regions": [
    {"region_type": "title_block",             "bbox": [x1,y1,x2,y2]},
    {"region_type": "general_tolerance_notes", "bbox": [x1,y1,x2,y2]},
    {"region_type": "technical_notes",         "bbox": [x1,y1,x2,y2]},
    {"region_type": "revision_block",          "bbox": [x1,y1,x2,y2]}
  ]
}
```

Image downscaled to max 1600px (same as before). One LLM call per drawing.

---

## Per-Tile Extraction

Uses the existing `_EXTRACT_PROMPT` (unchanged). Each tile call:
1. Crop `pil_img` to tile bbox
2. Encode as base64 JPEG
3. Call LLM → parse dimensions with local (x, y)
4. Add tile offset: `full_x = local_x + tile_x0`, `full_y = local_y + tile_y0`

Parallelism: `ThreadPoolExecutor(max_workers=min(n_tiles, 8))`

---

## Deduplication

After merging all tile results, deduplicate:

```python
def _dedup(dims: list[ExtractedDimension], radius: float) -> list[ExtractedDimension]:
    kept = []
    for d in dims:
        duplicate = any(
            d.value == k.value
            and abs(d.anchor_x - k.anchor_x) < radius
            and abs(d.anchor_y - k.anchor_y) < radius
            for k in kept
        )
        if not duplicate:
            kept.append(d)
    return kept
```

`radius = overlap * 0.8` (default ~160 px for standard tiles).

---

## Router Changes

**Removed:**
- `analyze_structure()` call (replaced by `detect_excluded_regions()`)
- Per-view loop for `extract_view_dimensions()`
- Phase 4 `verify_coverage()` loop (tiling covers full drawing)

**Added:**
- `detect_excluded_regions(pdf_path)` → `list[ExcludedRegion]`
- `extract_dimensions_tiled(pdf_path, excluded)` → `list[ExtractedDimension]`

**Modified:**
- `filter_by_views()` replaced by `filter_excluded()` — keeps excluded-region filtering, drops view_name assignment
- `view_seq` grouping: all dims go to `"_nogroup"` (global sequential numbering)
- `reconcile()` called with `views=None`

---

## Files Changed

| File | Change |
|------|--------|
| `app/services/analyzer.py` | Replace `_STRUCTURE_PROMPT` + `analyze_structure()` with `detect_excluded_regions()`; replace Phase 2b/4 functions with `extract_dimensions_tiled()`; add `compute_tile_grid()`, `_dedup()` |
| `app/services/extractor.py` | Add `filter_excluded()` alongside existing `filter_by_views()` |
| `app/routers/parts.py` | Update import + call sites; remove Phase 4 block; simplify view_seq logic |
