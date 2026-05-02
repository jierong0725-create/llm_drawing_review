# Canvas Coordinate Fix Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix two rendering bugs: (1) drawing doesn't auto-fit on load, (2) dimension markers appear at wrong positions because anchor coordinates are stored in PDF points instead of image pixels.

**Architecture:** Three changes — expose a DPI constant from image_gen.py, apply the PDF→pixel scale when storing dimensions in parts.py, run a one-time SQL migration for existing data, and fix two frontend bugs in review_workbench.html (missing offsetY return + missing onLoad handler).

**Tech Stack:** Python/FastAPI backend, SQLite via SQLAlchemy, React (Babel in-browser), pdfplumber at 300 DPI

---

### Task 1: Export RASTER_DPI constant from image_gen.py

**Files:**
- Modify: `app/services/image_gen.py`

The image is rasterized at `resolution=300` (hardcoded). Export this as a named constant so other modules can import it and compute the correct PDF-point → pixel scale.

**Step 1: Add constant and update usage**

In `app/services/image_gen.py`, add at top of file and update the call site:

```python
RASTER_DPI = 300

def generate_drawing_images(drawing_id: int, pdf_path: str, output_dir: str) -> list[str]:
    ...
    with pdfplumber.open(pdf_path) as pdf:
        for page_num, page in enumerate(pdf.pages, start=1):
            img = page.to_image(resolution=RASTER_DPI)   # was: resolution=300
```

**Step 2: Verify app still starts**

```bash
cd /Users/rongjie/llm_projects/llm_drawing_review
uvicorn app.main:app --reload &
curl -s http://localhost:8000/api/parts/3/versions | python3 -m json.tool | head -5
```

Expected: JSON response with version list (no 500 error).

**Step 3: Commit**

```bash
git add app/services/image_gen.py
git commit -m "refactor: export RASTER_DPI constant from image_gen"
```

---

### Task 2: Scale anchor coordinates to pixel space in parts.py

**Files:**
- Modify: `app/routers/parts.py`

pdfplumber's `extract_words()` returns coordinates in PDF user units (points, 1 pt = 1/72 inch). The image is rasterized at 300 DPI, so 1 pt = 300/72 ≈ 4.167 pixels. Currently `anchor_x` / `anchor_y` are stored as PDF points; they must be stored as image pixels.

**Step 1: Import RASTER_DPI in parts.py**

```python
from ..services.image_gen import generate_drawing_images, RASTER_DPI
```

(Replace the existing import line that only imports `generate_drawing_images`.)

**Step 2: Apply scale in _process_version**

Find the `Dimension(...)` constructor call inside `_process_version` and scale the anchor values:

```python
PDF_SCALE = RASTER_DPI / 72.0  # PDF points → image pixels

for seq, dim in enumerate(final_dims, start=1):
    record = Dimension(
        drawing_id=drawing_id,
        sequence=seq,
        value=dim.value,
        nominal=dim.nominal,
        tolerance=dim.tolerance,
        dim_type=DimensionType(dim.dim_type),
        view_name=dim.view_name,
        source=DimensionSource(dim.source),
        anchor_x=dim.anchor_x * PDF_SCALE if dim.anchor_x is not None else None,
        anchor_y=dim.anchor_y * PDF_SCALE if dim.anchor_y is not None else None,
    )
    db.add(record)
```

**Step 3: Commit**

```bash
git add app/routers/parts.py
git commit -m "fix: scale anchor coordinates from PDF points to image pixels on ingest"
```

---

### Task 3: Migrate existing anchor coordinates in dev.db

**Files:**
- Create: `scripts/migrate_anchor_coords.py`

Existing rows in `dimensions` have coordinates in PDF points. Multiply all by 300/72. Guard against double-migration by checking if max(anchor_x) is already > 3000 (pixel space).

**Step 1: Write migration script**

```python
#!/usr/bin/env python3
"""One-time migration: convert anchor_x / anchor_y from PDF points to image pixels."""
import sqlite3, sys, os

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "dev.db")
SCALE = 300 / 72.0  # PDF points → image pixels at 300 DPI

conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

cur.execute("SELECT MAX(anchor_x) FROM dimensions")
max_x = cur.fetchone()[0] or 0
if max_x > 3000:
    print(f"anchor_x max={max_x:.0f} — looks like pixels already, skipping.")
    conn.close()
    sys.exit(0)

cur.execute("""
    UPDATE dimensions
    SET anchor_x = anchor_x * ?,
        anchor_y = anchor_y * ?
    WHERE anchor_x IS NOT NULL
""", (SCALE, SCALE))
print(f"Updated {cur.rowcount} rows (scale={SCALE:.4f})")
conn.commit()
conn.close()
print("Done.")
```

**Step 2: Run migration**

```bash
python3 scripts/migrate_anchor_coords.py
```

Expected output:
```
Updated 256 rows (scale=4.1667)
Done.
```

**Step 3: Verify via API**

```bash
curl -s "http://localhost:8000/api/versions/3/drawings/3/dimensions" | \
  python3 -c "import json,sys; d=json.load(sys.stdin); print('anchor_x range:', min(x['anchor_x'] for x in d), max(x['anchor_x'] for x in d))"
```

Expected: values in the range ~276 – ~6735 (image pixel space, not ~66–1616 PDF points).

**Step 4: Commit**

```bash
git add scripts/migrate_anchor_coords.py
git commit -m "fix: migrate existing anchor coords from PDF points to image pixels"
```

---

### Task 4: Fix usePanZoom — return offsetY

**Files:**
- Modify: `app/templates/review_workbench.html` (line 74)

`usePanZoom` computes `offsetY` but does not include it in the return object, so `DrawingCanvas` always receives `offsetY = undefined`. This breaks vertical centering and the Y component of all marker positions.

**Step 1: Fix the return statement**

Find line 74 in `review_workbench.html`:

```javascript
// BEFORE
return { zoom, offsetX, setOffsetX, setOffsetY, fitScreen, handleWheel, handleMouseDown, handleMouseMove, handleMouseUp, handleDblClick };

// AFTER
return { zoom, offsetX, offsetY, setOffsetX, setOffsetY, fitScreen, handleWheel, handleMouseDown, handleMouseMove, handleMouseUp, handleDblClick };
```

(Just add `offsetY,` after `offsetX,`.)

**Step 2: Commit**

```bash
git add app/templates/review_workbench.html
git commit -m "fix: return offsetY from usePanZoom hook"
```

---

### Task 5: Fix DrawingCanvas — call fitScreen after image loads

**Files:**
- Modify: `app/templates/review_workbench.html` (line ~165)

`fitScreen()` is called in a `useEffect` when `drawing?.id` changes, but the image hasn't loaded yet at that point, so it falls back to `zoom=1, offset=0` — showing only the top-left corner of the 7016×4961px drawing.

**Step 1: Add onLoad handler to the img element**

Find the `React.createElement("img", { ... })` call (around line 164). Add `onLoad: fitScreen`:

```javascript
// BEFORE
: imgSrc && React.createElement("img", {
    src: imgSrc,
    onError: () => setImageError(true),
    style: { ... },
    draggable: false,
  }),

// AFTER
: imgSrc && React.createElement("img", {
    src: imgSrc,
    onError: () => setImageError(true),
    onLoad: fitScreen,
    style: { ... },
    draggable: false,
  }),
```

**Step 2: Verify in browser**

Open `http://localhost:8000/parts/3/versions/3/review`. The drawing should auto-fit to fill the canvas on load, and all dimension markers should appear at their correct positions overlaid on the drawing.

Take a screenshot:

```bash
python3 -c "
from playwright.sync_api import sync_playwright; import time
with sync_playwright() as p:
    b = p.chromium.launch(channel='chrome')
    pg = b.new_page(viewport={'width':1400,'height':900})
    pg.goto('http://localhost:8000/parts/3/versions/3/review', wait_until='networkidle')
    time.sleep(3)
    pg.screenshot(path='/tmp/after_fix.png', full_page=False)
    b.close()
"
```

Expected: drawing fills the canvas, numbered marker labels appear overlaid on the drawing's dimension annotations.

**Step 3: Commit**

```bash
git add app/templates/review_workbench.html
git commit -m "fix: call fitScreen after image loads so drawing auto-fits on open"
```
