# Tile-Based Dimension Extraction Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace Phase 1 view-detection + Phase 2b per-view LLM extraction + Phase 4 verify_coverage with a simpler tile-grid approach that runs at full resolution and requires no drawing-structure understanding.

**Architecture:** A lightweight Phase 1 call detects only excluded regions (title block, tolerance notes) on a downscaled image. The drawing is then split into overlapping tiles (size dynamic based on image dimensions, capped at 30 tiles for A0). Each tile is sent to the LLM for dimension text extraction in parallel. Results are merged with overlap-aware deduplication and filtered against excluded regions.

**Tech Stack:** Python, PIL/Pillow, pdfplumber, openai (sync client), concurrent.futures.ThreadPoolExecutor

---

### Task 1: Add `compute_tile_grid()` and `_dedup()` helpers + tests

**Files:**
- Create: `tests/test_tile_helpers.py`
- Modify: `app/services/analyzer.py` (add after existing imports, before `_make_client`)

**Step 1: Create test file**

```python
# tests/test_tile_helpers.py
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
```

**Step 2: Run tests to verify they fail**

```bash
cd /Users/rongjie/llm_projects/llm_drawing_review
python -m pytest tests/test_tile_helpers.py -v 2>&1 | head -30
```
Expected: ImportError or AttributeError — `compute_tile_grid` and `_dedup` don't exist yet.

**Step 3: Add helpers to `analyzer.py`**

Add after line 29 (after `from .extractor import ...`), before `try: from openai`:

```python
from math import ceil
from concurrent.futures import ThreadPoolExecutor, as_completed
```

Add after `_JPEG_QUALITY = 85` (after line 31), before `_MODEL`:

```python
_TARGET_MAX_TILES = 30
_BASE_TILE_SIZE = 1400
_BASE_OVERLAP = 200


def compute_tile_grid(w: int, h: int) -> tuple[list[tuple[int, int, int, int]], int]:
    """Return (tiles, overlap). tiles are (x0, y0, x1, y1) in full-image pixels.

    Tile size grows until the grid fits within _TARGET_MAX_TILES (handles A0).
    """
    tile_size = _BASE_TILE_SIZE
    overlap = _BASE_OVERLAP
    for t in range(_BASE_TILE_SIZE, 3100, 100):
        stride = t - _BASE_OVERLAP
        if ceil(w / stride) * ceil(h / stride) <= _TARGET_MAX_TILES:
            tile_size = t
            break
    else:
        tile_size = 3000
        overlap = 300

    stride = tile_size - overlap
    tiles: list[tuple[int, int, int, int]] = []
    for row in range(ceil(h / stride)):
        for col in range(ceil(w / stride)):
            x0 = col * stride
            y0 = row * stride
            x1 = min(x0 + tile_size, w)
            y1 = min(y0 + tile_size, h)
            tiles.append((x0, y0, x1, y1))
    return tiles, overlap


def _dedup(dims: list, radius: float) -> list:
    """Remove duplicate dimensions within overlap zones.

    Two dims are duplicates if their text matches and their centers are
    within `radius` pixels of each other in full-image space.
    """
    kept: list = []
    for d in dims:
        if d.anchor_x is None or d.anchor_y is None:
            kept.append(d)
            continue
        is_dup = any(
            d.value == k.value
            and k.anchor_x is not None
            and k.anchor_y is not None
            and abs(d.anchor_x - k.anchor_x) < radius
            and abs(d.anchor_y - k.anchor_y) < radius
            for k in kept
        )
        if not is_dup:
            kept.append(d)
    return kept
```

**Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_tile_helpers.py -v
```
Expected: All 6 tests PASS.

> Note: `test_tile_grid_no_gaps` iterates pixel-by-pixel over a 3000×2000 grid and is slow (~10s). That's acceptable for a one-time correctness check.

**Step 5: Commit**

```bash
git add tests/test_tile_helpers.py app/services/analyzer.py
git commit -m "feat: add compute_tile_grid and _dedup helpers"
```

---

### Task 2: Replace `analyze_structure()` with `detect_excluded_regions()`

**Files:**
- Modify: `app/services/analyzer.py`

**Step 1: Replace `_STRUCTURE_PROMPT` and `analyze_structure()`**

In `analyzer.py`, replace the entire `_STRUCTURE_PROMPT` constant and `analyze_structure()` function (lines 63–181) with:

```python
_EXCLUDED_PROMPT = """You are an expert at reading engineering drawings.

Scan the edges and corners of this drawing frame. Find every region that contains
administrative/reference information rather than part-specific dimensions:

- title_block: bottom-right corner, table-like layout with part number, material,
  date, revision, company logo/name. ALWAYS mark this as excluded.
- general_tolerance_notes: a box (typically right side) listing DIN/ISO standard
  references, default Ra surface roughness values, edge tolerances, burr height
  limits. ALWAYS mark this as excluded.
- technical_notes: text blocks with NOTES:, MATERIAL SPECIFICATION, SURFACE
  TREATMENT, CLEANLINESS, etc.
- revision_block: a table listing engineering change history (Ind./Change/Date).
- parts_list: a BOM table listing component items, usually above the title block.

Return ONLY valid JSON (no markdown, no code fences):
{{
  "excluded_regions": [
    {{"region_type": "title_block",             "bbox": [x1, y1, x2, y2]}},
    {{"region_type": "general_tolerance_notes", "bbox": [x1, y1, x2, y2]}}
  ]
}}

Coordinates are image pixels. bbox = [x1, y1, x2, y2] where (x1,y1) is top-left.
The image is {width}x{height} pixels."""

_STRUCTURE_MAX_DIM = 1600


def detect_excluded_regions(pdf_path: str) -> list[ExcludedRegion]:
    """Phase 1 (simplified): detect excluded regions only, no view detection."""
    if not _LLM_AVAILABLE or not _API_KEY:
        return []

    client = _make_client()

    with pdfplumber.open(pdf_path) as pdf:
        page = pdf.pages[0]
        page_img = page.to_image(resolution=_RESOLUTION)
        pil_img: Image.Image = page_img.original
        full_w, full_h = pil_img.size

        longest = max(full_w, full_h)
        if longest > _STRUCTURE_MAX_DIM:
            ratio = _STRUCTURE_MAX_DIM / longest
            send_img = pil_img.resize(
                (int(full_w * ratio), int(full_h * ratio)), Image.LANCZOS
            )
        else:
            ratio = 1.0
            send_img = pil_img

        send_w, send_h = send_img.size
        b64 = _image_to_base64(send_img)

    prompt = _EXCLUDED_PROMPT.format(width=send_w, height=send_h)

    try:
        response = client.chat.completions.create(
            model=_MODEL,
            max_tokens=512,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                        {"type": "text", "text": prompt},
                    ],
                }
            ],
        )
        raw = response.choices[0].message.content.strip()
        data = json.loads(raw)
        upscale = 1.0 / ratio if ratio != 1.0 else 1.0
        excluded: list[ExcludedRegion] = []
        for e in data.get("excluded_regions", []):
            bbox = e.get("bbox", [])
            if len(bbox) != 4:
                continue
            l, t, r, b = bbox
            if not (0 <= l < r <= send_w and 0 <= t < b <= send_h):
                continue
            excluded.append(ExcludedRegion(
                region_type=str(e.get("region_type", "")),
                bbox=(
                    int(l * upscale), int(t * upscale),
                    int(r * upscale), int(b * upscale),
                ),
            ))
        return excluded
    except (json.JSONDecodeError, KeyError, ValueError):
        return []
```

Also remove `_parse_structure_result()` (lines 184–229) and the `StructureResult` + `ViewRegion` dataclasses — they will no longer be exported. Keep `ExcludedRegion`.

**Step 2: Verify syntax**

```bash
python -c "from app.services.analyzer import detect_excluded_regions, ExcludedRegion; print('OK')"
```
Expected: `OK`

**Step 3: Commit**

```bash
git add app/services/analyzer.py
git commit -m "feat: replace analyze_structure with detect_excluded_regions (Phase 1 simplified)"
```

---

### Task 3: Add `extract_dimensions_tiled()`

**Files:**
- Modify: `app/services/analyzer.py`

**Step 1: Add function after `extract_view_dimensions()`**

Insert after the `extract_view_dimensions()` function (after line ~320 in the original, now shifted):

```python
def extract_dimensions_tiled(
    pdf_path: str,
    excluded: list[ExcludedRegion],
) -> list[ExtractedDimension]:
    """Tile-based full-drawing LLM dimension extraction (replaces Phase 2b + Phase 4).

    Splits the full-resolution drawing into overlapping tiles, extracts dimensions
    from each tile in parallel, deduplicates overlap zones, then filters excluded
    regions.
    """
    if not _LLM_AVAILABLE or not _API_KEY:
        return []

    with pdfplumber.open(pdf_path) as pdf:
        page = pdf.pages[0]
        page_img = page.to_image(resolution=_RESOLUTION)
        pil_img: Image.Image = page_img.original
        w, h = pil_img.size

    tiles, overlap = compute_tile_grid(w, h)
    radius = overlap * 0.8
    client = _make_client()

    def _extract_tile(tile_bbox: tuple[int, int, int, int]) -> list[ExtractedDimension]:
        dummy_view = ViewRegion(name="tile", bbox=tile_bbox, page=1)
        return extract_view_dimensions(pil_img, dummy_view, 1, client)

    all_dims: list[ExtractedDimension] = []
    with ThreadPoolExecutor(max_workers=min(len(tiles), 8)) as executor:
        futures = {executor.submit(_extract_tile, t): t for t in tiles}
        for future in as_completed(futures):
            try:
                all_dims.extend(future.result())
            except Exception:
                pass

    all_dims = _dedup(all_dims, radius)

    if excluded:
        all_dims = [
            d for d in all_dims
            if not any(
                e.bbox[0] <= (d.anchor_x or -1) <= e.bbox[2]
                and e.bbox[1] <= (d.anchor_y or -1) <= e.bbox[3]
                for e in excluded
            )
        ]

    return all_dims
```

Note: `extract_view_dimensions` already maps tile-local coords to full-image coords via `view.bbox[0/1]`, so no extra offset math needed here.

**Step 2: Verify syntax**

```bash
python -c "from app.services.analyzer import extract_dimensions_tiled; print('OK')"
```
Expected: `OK`

**Step 3: Commit**

```bash
git add app/services/analyzer.py
git commit -m "feat: add extract_dimensions_tiled (tile-grid LLM extraction)"
```

---

### Task 4: Add `filter_excluded()` to `extractor.py`

**Files:**
- Modify: `app/services/extractor.py`

**Step 1: Add function at end of file**

Append after `filter_by_views()`:

```python
def filter_excluded(
    dims: list[ExtractedDimension],
    excluded: list,
    *,
    is_pixels: bool = False,
) -> list[ExtractedDimension]:
    """Filter dims whose anchor falls in any excluded region.

    anchor coords are in PDF points when is_pixels=False,
    or 300-DPI image pixels when is_pixels=True.
    excluded bboxes are always in 300-DPI image pixels.
    """
    if not excluded:
        return dims
    scale = 1.0 if is_pixels else PDF_SCALE
    result = []
    for d in dims:
        if d.anchor_x is None or d.anchor_y is None:
            result.append(d)
            continue
        px = d.anchor_x * scale
        py = d.anchor_y * scale
        in_exc = any(
            e.bbox[0] <= px <= e.bbox[2] and e.bbox[1] <= py <= e.bbox[3]
            for e in excluded
        )
        if not in_exc:
            result.append(d)
    return result
```

**Step 2: Verify syntax**

```bash
python -c "from app.services.extractor import filter_excluded; print('OK')"
```
Expected: `OK`

**Step 3: Commit**

```bash
git add app/services/extractor.py
git commit -m "feat: add filter_excluded to extractor"
```

---

### Task 5: Update `parts.py` router

**Files:**
- Modify: `app/routers/parts.py`

**Step 1: Update imports (line 19–22)**

Replace:
```python
from ..services.extractor import extract_from_pdf, filter_by_views
from ..services.analyzer import analyze_structure, extract_view_dimensions, verify_coverage, StructureResult, _make_client
```

With:
```python
from ..services.extractor import extract_from_pdf, filter_by_views, filter_excluded
from ..services.analyzer import detect_excluded_regions, extract_dimensions_tiled
```

**Step 2: Replace `_process_version` body (lines ~197–316)**

Replace the entire block inside `_process_version` from `for drawing_id, pdf_path in drawing_paths:` through the Phase 4 block. New logic:

```python
    try:
        for drawing_id, pdf_path in drawing_paths:
            try:
                # Phase 1: Detect excluded regions (title block, tolerance notes, etc.)
                excluded = []
                if _ANTHROPIC_OK:
                    excluded = detect_excluded_regions(pdf_path)

                # Phase 2a: pdfplumber text extraction + filter excluded
                program_dims = extract_from_pdf(pdf_path)
                program_dims = filter_excluded(program_dims, excluded, is_pixels=False)

                # Phase 2b: Tile-based LLM extraction (full-res, parallel)
                llm_dims: list = []
                if _ANTHROPIC_OK:
                    llm_dims = extract_dimensions_tiled(pdf_path, excluded)

                # Phase 3: Reconcile
                final_dims = reconcile(program_dims, llm_dims, views=None)

                # Sequence numbering (global, no view grouping)
                for seq, dim in enumerate(final_dims, start=1):
                    record = Dimension(
                        drawing_id=drawing_id,
                        sequence=seq,
                        value=dim.value,
                        nominal=dim.nominal,
                        tolerance=dim.tolerance,
                        dim_type=DimensionType(dim.dim_type),
                        view_name=None,
                        source=DimensionSource(dim.source),
                        anchor_x=dim.anchor_x * PDF_SCALE if dim.anchor_x is not None else None,
                        anchor_y=dim.anchor_y * PDF_SCALE if dim.anchor_y is not None else None,
                    )
                    db.add(record)
                db.commit()

                # Generate JPG images for web review
                output_dir = os.path.join(STATIC_DIR, str(drawing_id))
                try:
                    generate_drawing_images(drawing_id, pdf_path, output_dir)
                except Exception as img_err:
                    version = db.query(Version).filter(Version.id == version_id).first()
                    if version:
                        version.notes = (version.notes or "") + f"\n[图片生成失败] drawing {drawing_id}: {img_err}"
                        db.commit()
            except Exception:
                db.rollback()
                raise
```

Also remove the now-unused `PDF_SCALE` local import at line 38 (it's already imported from extractor via `filter_excluded`). Keep the `from ..services.extractor import PDF_SCALE` import at the top if `PDF_SCALE` is used directly for `anchor_x/y` scaling in the record creation — it is, so keep it.

**Step 3: Verify the app starts**

```bash
cd /Users/rongjie/llm_projects/llm_drawing_review
python -c "from app.routers.parts import router; print('OK')"
```
Expected: `OK`

**Step 4: Commit**

```bash
git add app/routers/parts.py
git commit -m "refactor: switch router to tile-based extraction pipeline"
```

---

### Task 6: Remove dead code from `analyzer.py`

**Files:**
- Modify: `app/services/analyzer.py`

**Step 1: Remove unused exports**

The following are no longer used by any caller. Remove them:
- `verify_coverage()` function and `_VERIFY_PROMPT` constant
- `StructureResult` dataclass
- `ViewRegion` dataclass (still used internally by `extract_dimensions_tiled` as a shim → **keep it** as a private detail; do NOT export it)

Double-check no other file imports `StructureResult` or `ViewRegion`:

```bash
grep -rn "StructureResult\|ViewRegion\|verify_coverage\|analyze_structure\|extract_view_dimensions" \
  /Users/rongjie/llm_projects/llm_drawing_review/app/ --include="*.py"
```

Expected: only internal uses within `analyzer.py` itself.

**Step 2: Remove `_VERIFY_PROMPT` and `verify_coverage()`**

Delete lines for `_VERIFY_PROMPT` constant and `verify_coverage()` function (Phase 4 section).

**Step 3: Verify**

```bash
python -c "from app.services.analyzer import detect_excluded_regions, extract_dimensions_tiled, ExcludedRegion, _dedup, compute_tile_grid; print('OK')"
python -m pytest tests/test_tile_helpers.py -v
```
Expected: `OK` + all tests PASS.

**Step 4: Commit**

```bash
git add app/services/analyzer.py
git commit -m "chore: remove verify_coverage and StructureResult dead code"
```

---

### Task 7: Smoke test end-to-end

**Step 1: Start the dev server**

```bash
cd /Users/rongjie/llm_projects/llm_drawing_review
uvicorn app.main:app --reload --port 8000
```

**Step 2: Upload a test PDF**

Navigate to `http://localhost:8000` in the browser. Upload any engineering drawing PDF and verify:
- Processing completes without error
- Dimensions appear in the review workbench
- No title block numbers appear in the dimension list

**Step 3: Check logs for tile count**

Add a temporary print in `extract_dimensions_tiled()` after `compute_tile_grid`:
```python
print(f"[tile] {len(tiles)} tiles for {w}×{h} image")
```
Confirm reasonable tile count is logged.

**Step 4: Remove temp print and final commit**

```bash
git add app/services/analyzer.py
git commit -m "chore: remove debug print from extract_dimensions_tiled"
```
