# 视图感知标注提取 实现方案

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 将尺寸提取从全页平面扫描升级为视图感知的混合管道（LLM 做结构理解 + pdfplumber 做精确坐标），显著提升覆盖率和准确度。

**Architecture:** 四阶段管道：(1) LLM 全图结构分析 → 识别视图边界和排除区域；(2a) pdfplumber 精确提取 + 视图归属过滤；(2b) 逐视图裁剪的 LLM 补充提取（替代 3×3 格子）；(3) 视图感知排序和按视图独立编号；(4) 验证回环（漏标检查）。新旧 pipeline 并行，不影响存量数据。

**Tech Stack:** Python 3.11+, Claude Opus 4.7 (Vision), pdfplumber, Pillow, anthropic SDK

---

## 架构概览

```
PDF 页面 (300 DPI 光栅化)
  │
  ├──→ Phase 1: LLM 结构分析 ─────────────────────┐
  │     全图 → {views: [{name, bbox}],             │
  │              excluded: [{type, bbox}]}          │
  │                                                 │
  ├──→ Phase 2a: pdfplumber 提取 + 视图过滤 ──────┼──→ ExtractedDimension (view_name assigned)
  │     extract_from_pdf()                          │    + 排除区域丢弃
  │     filter_by_views(dims, views, excluded)      │
  │                                                 │
  ├──→ Phase 2b: 逐视图裁剪 LLM 提取 ─────────────┼──→ ExtractedDimension (source="llm")
  │     对每个 view bbox 裁剪子图 → Claude Vision   │    替代旧的 3×3 九宫格
  │     返回 list[{text, x, y}]                     │
  │                                                 │
  ├──→ Phase 3: 视图感知调和 + 排序 ──────────────┼──→ 最终尺寸列表 (按 view 分组、独立编号)
  │     reconcile(program, llm, views)              │
  │     每组 view 从 1 开始编号                    │
  │                                                 │
  └──→ Phase 4: 验证回环 ─────────────────────────┼──→ 带标记图纸 → Claude → 漏标列表 → version.notes
```

## 核心数据结构

在 `analyzer.py` 中新增：

```python
@dataclass
class ViewRegion:
    name: str                    # "主视图", "A-A", "俯视图"
    bbox: tuple[int,int,int,int] # (left, top, right, bottom) 300 DPI 像素坐标
    page: int

@dataclass
class ExcludedRegion:
    region_type: str             # "title_block" | "technical_notes" | "parts_list"
    bbox: tuple[int,int,int,int]

@dataclass
class StructureResult:
    views: list[ViewRegion]
    excluded: list[ExcludedRegion]
```

## 坐标系统统一

关键设计：**整个管道统一使用 300 DPI 像素坐标**，消除转换的认知负担。

| 环节 | 坐标系 | 换算 | 最终 DB 值 |
|------|--------|------|-----------|
| pdfplumber 原始 | PDF point (1/72") | `px = pt × 300/72` | 像素 |
| Phase 1 LLM bbox | 300 DPI 像素 | 直接使用 | 像素 |
| Phase 2b LLM 坐标 | 裁剪子图 → 加 crop 偏移 → 全图像素 | `full_x = crop_x + crop_left` | 像素 |
| Phase 2a 过滤比较 | 像素 ↔ 像素 | 把 dim.anchor_x × scale 转为像素再比 bbox | — |
| DB 存储 | 像素 | `anchor_x = dim.anchor_x * PDF_SCALE` (PDF_SCALE = 300/72) | 像素 |

关键约束：`ExtractedDimension.anchor_x/y` 当前是 PDF point（由 extractor 输出），在 `parts.py:195-196` 乘以 `PDF_SCALE` 转为像素存库。新增的 filter_by_views 需要在比较前做这个转换。

---

## 组件详细设计

### 1. `app/services/analyzer.py`（新文件）

#### 1.1 `analyze_structure(pdf_path: str) -> StructureResult`

**输入：** PDF 文件路径

**输出：** 视图和排除区域列表

**流程：**
1. 复用现有 vision.py 的光栅化逻辑：`page.to_image(resolution=300)` → PIL Image
2. 以 85% JPEG 质量编码为 base64
3. 发送给 Claude，使用结构分析 Prompt（见下方）
4. 解析返回的 JSON，容错处理（JSON parse 失败 → 回退 = 空结构 → 旧 pipeline）
5. 对所有 view bbox 和 excluded bbox 做合理性检查（正数、不超出图幅、最小面积 > 图幅 5%）

**Prompt 设计：**

```
You are an expert at analyzing mechanical engineering drawings.

Analyze this engineering drawing and return a JSON object identifying:
1. VIEW regions — areas that contain part geometry projections with dimension annotations (主视图, 俯视图, section views, detail views, auxiliary views)
2. EXCLUDED regions — areas that should NOT have dimension markers (title block / 标题栏, technical notes / 技术要求, parts list / 明细表)

Rules for identifying views:
- Views are large rectangular areas containing part outlines, hatched sections, center lines
- View titles are typically positioned above or below the view (e.g., "A-A", "I", "II", "主视图")
- Dimension lines, extension lines, and leader lines point INTO views
- Each view region should generously encompass its geometry AND its dimensions

Rules for identifying excluded regions:
- Title block is at the bottom-right corner, has table-like layout with text fields
- Technical notes are text blocks positioned along the left or bottom edge
- Parts list / BOM table is typically above the title block

Return ONLY valid JSON (no markdown, no code fences):
{
  "views": [
    {"name": "主视图", "bbox": [left, top, right, bottom]},
    {"name": "A-A",   "bbox": [left, top, right, bottom]}
  ],
  "excluded_regions": [
    {"region_type": "title_block",     "bbox": [left, top, right, bottom]},
    {"region_type": "technical_notes", "bbox": [left, top, right, bottom]}
  ]
}

Coordinates are in image pixels. bbox = [x1, y1, x2, y2] where (x1,y1) is top-left, (x2,y2) is bottom-right.
The image is {width}x{height} pixels.
```

**返回示例：**

```json
{
  "views": [
    {"name": "主视图", "bbox": [80, 60, 980, 760]},
    {"name": "俯视图", "bbox": [80, 800, 980, 1450]},
    {"name": "A-A剖",  "bbox": [1050, 80, 1800, 700]}
  ],
  "excluded_regions": [
    {"region_type": "title_block",     "bbox": [1550, 2100, 1900, 2480]},
    {"region_type": "technical_notes", "bbox": [80, 2100, 1520, 2480]}
  ]
}
```

**错误处理：**
```python
def analyze_structure(pdf_path: str) -> StructureResult:
    # ... setup and API call ...
    try:
        raw = response.content[0].text.strip()
        data = json.loads(raw)
        result = _parse_structure_result(data)
        if not result.views:  # LLM returned empty views
            return StructureResult(views=[], excluded=[])
        return result
    except (json.JSONDecodeError, KeyError, ValueError):
        return StructureResult(views=[], excluded=[])  # graceful fallback
```

#### 1.2 `extract_view_dimensions(image: Image.Image, view: ViewRegion, page_num: int, client) -> list[ExtractedDimension]`

**输入：** 全页 PIL Image、ViewRegion、页码、anthropic client

**输出：** 该视图内的 LLM 提取维度列表

**流程：**
1. `image.crop(view.bbox)` 得到视图子图
2. 编码为 JPEG base64
3. 发送给 Claude，使用尺寸提取 Prompt
4. 对返回的每个结果：`full_x = dim_x + view.bbox[0]`, `full_y = dim_y + view.bbox[1]`
5. 转换为 `ExtractedDimension`（source="llm"），使用 `_parse_nominal_tol` 和 `_infer_type`

**Prompt 设计：**

```
You are an expert at reading mechanical engineering drawings.

This image shows ONE cropped view from an engineering drawing. Identify EVERY dimension annotation visible in this view.

For each dimension, return:
{
  "dimensions": [
    {
      "text": "the exact dimension text as it appears (e.g. ⌀12.5±0.1, R5, 45°, M10×1.5, 2×⌀8, Ra 3.2, 69.5 ±0.4, [⌀20]⊕|⌀0.05|A|B|C)",
      "x": <estimated center X coordinate within this cropped image in pixels>,
      "y": <estimated center Y coordinate within this cropped image in pixels>
    }
  ]
}

Include ALL types:
- Linear dimensions (numbers with tolerance ±)
- Diameters (⌀, Φ, φ)
- Radii (R)
- Angles (°)
- GD&T feature control frames (⊕, ⊘, etc.)
- Surface roughness (Ra, Rz)
- Thread callouts (M, Tr, G)
- Count/dimension patterns (e.g. "2×⌀8", "6×M6")
- Reference dimensions in parentheses
- Chamfer callouts (C, C×45°)

CRITICAL: Return EVERY visible dimension. Missing even one is a failure.
Do NOT include: view title text, notes, or general drawing annotations.
Return ONLY valid JSON, no markdown, no code fences.
The image is {crop_width}x{crop_height} pixels.
```

**Post-processing：**
```python
for item in data.get("dimensions", []):
    text = item["text"].strip()
    if not text or text in seen_texts:
        continue
    seen_texts.add(text)
    full_x = item["x"] + view.bbox[0]  # crop → full image coords
    full_y = item["y"] + view.bbox[1]
    nominal, tol = _parse_nominal_tol(text)
    dim_type = _infer_type(text)
    dims.append(ExtractedDimension(
        value=text, nominal=nominal, tolerance=tol,
        dim_type=dim_type, view_name=view.name,
        source="llm", anchor_x=full_x, anchor_y=full_y, page=page_num,
    ))
```

#### 1.3 `verify_coverage(image: Image.Image, structure: StructureResult, dims: list[ExtractedDimension], page_num: int, client) -> list[str]`

**Phase 4 验证回环：** 将带标记的图纸发送给 LLM，检查是否有漏标。

**注意：** dims 在此阶段还只有 anchor 坐标（没有前端圆圈标记），需要先在锚点位置渲染标记。简单做法：在每处坐标画一个红点 + 序号。

实际上更实用的做法是：不合成带标记的图，而是把 view 子图+已提取的维度列表一起发给 Claude：

```python
def verify_coverage(image, view, dims_in_view, client):
    crop = image.crop(view.bbox)
    texts = [d.value for d in dims_in_view]
    prompt = f"""This view contains {len(texts)} identified dimensions:
{chr(10).join(f'- {t}' for t in texts)}

Review the cropped view image carefully. Are there ANY additional dimensions
visible that are NOT in the list above? If yes, list them. If all dimensions
are accounted for, return an empty list.

Return ONLY a JSON array of strings, or [] if complete."""
    # ... API call ...
    return missing_texts  # list[str]
```

#### 1.4 辅助函数

```python
def _image_to_base64(img: Image.Image, quality=85) -> str:
    """PIL Image → base64 JPEG string."""
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return base64.standard_b64encode(buf.getvalue()).decode()
```

### 2. `app/services/extractor.py` — 新增 `filter_by_views()`

```python
PDF_SCALE = 300.0 / 72.0  # 与 parts.py 保持一致

def filter_by_views(
    dims: list[ExtractedDimension],
    views: list[ViewRegion],
    excluded: list[ExcludedRegion],
) -> list[ExtractedDimension]:
    """Assign view_name to each dimension, discard those in excluded regions.

    Coordinates in ExtractedDimension are PDF points; view/excluded bboxes
    are in 300 DPI pixels. Conversion: px = pt * (300/72).
    """
    scale = PDF_SCALE
    filtered: list[ExtractedDimension] = []

    for dim in dims:
        px = dim.anchor_x * scale if dim.anchor_x is not None else None
        py = dim.anchor_y * scale if dim.anchor_y is not None else None
        if px is None or py is None:
            continue  # no anchor → skip

        # Check excluded regions first
        in_excluded = False
        for exc in excluded:
            l, t, r, b = exc.bbox
            if l <= px <= r and t <= py <= b:
                in_excluded = True
                break
        if in_excluded:
            continue  # discard

        # Assign view_name
        view_name = None
        for view in views:
            l, t, r, b = view.bbox
            if l <= px <= r and t <= py <= b:
                view_name = view.name
                break

        filtered.append(replace(dim, view_name=view_name))

    return filtered
```

### 3. `app/services/reconciler.py` — 视图感知排序

修改 reconcile() 签名，新增 `views` 参数。

```python
def reconcile(
    program_dims: list[ExtractedDimension],
    llm_dims: list[ExtractedDimension],
    views: list[ViewRegion] | None = None,
) -> list[ExtractedDimension]:
    """Merge deduplicated, view-aware sorted list."""

    reconciled: list[ExtractedDimension] = list(program_dims)
    for llm_dim in llm_dims:
        if not _has_match(llm_dim, reconciled):
            reconciled.append(llm_dim)

    if views:
        # Build view order map: view_name → page, y-order
        view_order = {}
        for i, v in enumerate(views):
            view_order[v.name] = (v.page, i, v.bbox[1])  # (page, index, top)
        # Dims without a view_name go last
        reconciled.sort(key=lambda d: (
            d.page,
            view_order.get(d.view_name, (d.page, 999, 999)),
            d.anchor_y if d.anchor_y is not None else 0.0,
            d.anchor_x if d.anchor_x is not None else 0.0,
        ))
    else:
        reconciled.sort(key=lambda d: (
            d.page,
            d.anchor_y if d.anchor_y is not None else 0.0,
            d.anchor_x if d.anchor_x is not None else 0.0,
        ))

    return reconciled
```

### 4. `app/routers/parts.py` — 新 pipeline 串联

替换 `_process_version` 中的 `vision_check()` 为新的四阶段管道：

```python
from app.services.analyzer import analyze_structure, extract_view_dimensions, verify_coverage
from app.services.extractor import filter_by_views

def _process_version(version_id: int, drawing_paths: list[tuple[int, str]]) -> None:
    PDF_SCALE = RASTER_DPI / 72.0
    db: Session = SessionLocal()
    try:
        for drawing_id, pdf_path in drawing_paths:
            try:
                # Phase 1: Structural analysis (LLM)
                if _ANTHROPIC_AVAILABLE:
                    client = anthropic.Anthropic()
                    structure = analyze_structure(pdf_path)
                else:
                    structure = StructureResult(views=[], excluded=[])

                # Phase 2a: Program extraction + view filtering
                program_dims = extract_from_pdf(pdf_path)
                if structure.views:
                    program_dims = filter_by_views(program_dims, structure.views, structure.excluded)

                # Phase 2b: Per-view LLM extraction (replaces 3×3 grid)
                llm_dims: list[ExtractedDimension] = []
                if structure.views and _ANTHROPIC_AVAILABLE:
                    with pdfplumber.open(pdf_path) as pdf:
                        for page_num, page in enumerate(pdf.pages, start=1):
                            page_img = page.to_image(resolution=300)
                            pil_img = page_img.original
                            for view in [v for v in structure.views if v.page == page_num]:
                                view_dims = extract_view_dimensions(pil_img, view, page_num, client)
                                llm_dims.extend(view_dims)

                # Phase 3: Reconcile with view awareness
                final_dims = reconcile(program_dims, llm_dims, structure.views if structure.views else None)

                # Per-view sequence numbering
                view_seq: dict[str, int] = defaultdict(int)
                for dim in final_dims:
                    view_key = dim.view_name or "_nogroup"
                    view_seq[view_key] += 1
                    seq = view_seq[view_key]
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
                db.commit()

                # Phase 4: Verification loop
                if structure.views and _ANTHROPIC_AVAILABLE:
                    with pdfplumber.open(pdf_path) as pdf:
                        for page_num, page in enumerate(pdf.pages, start=1):
                            page_img = page.to_image(resolution=300)
                            pil_img = page_img.original
                            for view in [v for v in structure.views if v.page == page_num]:
                                dims_in_view = [d for d in final_dims if d.view_name == view.name]
                                missing = verify_coverage(pil_img, view, dims_in_view, page_num, client)
                                if missing:
                                    version = db.query(Version).filter(Version.id == version_id).first()
                                    if version:
                                        note = f"[Phase 4] {view.name} 可能遗漏: {', '.join(missing)}"
                                        version.notes = (version.notes or "") + f"\n{note}"
                                        db.commit()

            except Exception:
                db.rollback()
                raise

        # ... rest unchanged: set status to ready ...
```

**Fallback 策略（无 LLM）：**
- `_ANTHROPIC_AVAILABLE = False` → `structure = StructureResult([], [])`
- 空 views → `filter_by_views` 是 no-op（无视图过滤）
- 空 views → `llm_dims` 不运行
- `reconcile(program, [], None)` → 回退到旧的平面排序
- 这意味着**没有 API Key 时，行为完全等同于旧 pipeline**，无损降级

### 5. 前端：PanelA 按视图分组

**核心修改：** 将 PanelA 的尺寸列表改为视图分组显示

```
PanelA
 ├─ Filter tabs (不变: all/pending/confirmed/questionable/rejected)
 ├─ 遍历视图分组 → 显示视图标题
 │   ├─ ─ [主视图] (4 条)
 │   │   ├─ ① ⌀50±0.1 ● anchor dot ● dim detail
 │   │   ├─ ② R12 ...
 │   │   └─ ...
 │   ├─ ─ [俯视图] (3 条)
 │   │   ├─ ① 40±0.1 ...
 │   │   └─ ...
 └─ ConclusionBar (不变)
```

**实现方式（review_workbench.html）：**

```javascript
// 分组函数
function groupByView(dims) {
  const groups = {};
  for (const d of dims) {
    const key = d.view_name || "未归属";
    if (!groups[key]) groups[key] = [];
    groups[key].push(d);
  }
  return groups;
}

// 按视图排序（保持画布上的视图顺序）
// 前端不知道视图排序 → 从后端 API 返回的 dims 推断
// 第一个出现的 view_name 是主视图，以此类推
function orderedViewGroups(dims) {
  const groups = groupByView(dims);
  const order = [];
  const seen = new Set();
  for (const d of dims) {
    const key = d.view_name || "未归属";
    if (!seen.has(key)) {
      seen.add(key);
      order.push(key);
    }
  }
  return order.map(name => ({ name, dims: groups[name] }));
}
```

**渲染：**
```javascript
{orderedViewGroups(filtered).map(group => (
  <div key={group.name} style={{ marginBottom: 8 }}>
    <div style={{
      padding: "6px 14px", fontSize: 10, fontWeight: 600,
      color: "var(--ink-secondary)", textTransform: "uppercase",
      letterSpacing: "0.06em",
      background: "var(--bg-elevated)", borderBottom: "1px solid var(--border-color)",
      display: "flex", alignItems: "center", gap: 6,
    }}>
      <svg width="12" height="12" viewBox="0 0 12 12"><rect x="1" y="1" width="10" height="10" rx="1" stroke="currentColor" fill="none" strokeWidth="1"/></svg>
      {group.name}
      <span style={{ marginLeft: "auto", color: "var(--ink-disabled)" }}>{group.dims.length}</span>
    </div>
    {group.dims.map(dim => (
      <DimListItem key={dim.id} ... />
    ))}
  </div>
))}
```

---

## 实施任务

### Task 1: 创建 `app/services/analyzer.py`

**Step 1: 创建文件骨架**

```python
"""
Phase 1 + 2b + 4: LLM-powered structural analysis and view-based dimension extraction.

Replaces the old 3×3 grid approach (vision.py) with:
- Full-page structural analysis for view/excluded region detection
- Per-view cropped image extraction for better coverage and accuracy
- Verification loop for missing dimension detection
"""

import base64
import io
import json
import os
from collections import defaultdict
from dataclasses import dataclass, replace
from typing import Optional

import pdfplumber
from PIL import Image

from .extractor import ExtractedDimension, _parse_nominal_tol, _infer_type

try:
    import anthropic
    _ANTHROPIC_AVAILABLE = True
except ImportError:
    _ANTHROPIC_AVAILABLE = False

_RESOLUTION = 300
_JPEG_QUALITY = 85


@dataclass
class ViewRegion:
    name: str
    bbox: tuple[int, int, int, int]  # (left, top, right, bottom) in pixels
    page: int


@dataclass
class ExcludedRegion:
    region_type: str  # "title_block" | "technical_notes" | "parts_list"
    bbox: tuple[int, int, int, int]


@dataclass
class StructureResult:
    views: list[ViewRegion]
    excluded: list[ExcludedRegion]


# ── Phase 1: Structural analysis ──

_STRUCTURE_PROMPT = """..."""  # (完整的 Prompt 见上方设计文档)


def analyze_structure(pdf_path: str) -> StructureResult:
    """Phase 1: Full-page structural analysis. Returns views and excluded regions."""
    # ... 实现见上方设计 ...
```

**Step 2: 实现 `analyze_structure()`**

**Step 3: 实现 `extract_view_dimensions()`**

**Step 4: 实现 `verify_coverage()`**

**Step 5: 实现 `_image_to_base64()` 和 `_call_claude()`**

**Step 6: 运行基础检查**

Run: `python -c "from app.services.analyzer import StructureResult, analyze_structure; print('import OK')"`
Expected: `import OK`

**Step 7: 提交**

### Task 2: 修改 `app/services/extractor.py`

**Step 1: 添加 import 和 `filter_by_views()` 函数**

**Step 2: 运行基础检查**

Run: `python -c "from app.services.extractor import filter_by_views; print('import OK')"`
Expected: `import OK`

**Step 3: 提交**

### Task 3: 修改 `app/services/reconciler.py`

**Step 1: 修改 `reconcile()` 签名，添加 `views` 参数**

**Step 2: 修改排序逻辑**

**Step 3: 运行测试**

Run: `python -c "from app.services.reconciler import reconcile; print('import OK')"`
Expected: `import OK`

**Step 4: 提交**

### Task 4: 修改 `app/routers/parts.py` _process_version

**Step 1: 添加 imports**
```python
from app.services.analyzer import analyze_structure, extract_view_dimensions, verify_coverage, StructureResult
from app.services.extractor import filter_by_views
from collections import defaultdict
```

**Step 2: 重构 `_process_version()` 为四阶段管道**

**Step 3: 停用 `vision.py`（注释掉旧的 `llm_dims = vision_check(pdf_path)`）**

**Step 4: 提交**

### Task 5: 前端视图分组

**Step 1: 在 review_workbench.html 添加 `groupByView()` 和 `orderedViewGroups()` 辅助函数**

**Step 2: 修改 PanelA 渲染循环，加入视图分组标题**

**Step 3: 测试：上传一张新图纸 → 检查 PanelA 是否按视图分组显示**

---

## 影响范围

| 文件 | 改动 |
|------|------|
| `app/services/analyzer.py` | **新文件** ~180 行 |
| `app/services/extractor.py` | +30 行（`filter_by_views`） |
| `app/services/reconciler.py` | ~10 行修改（`reconcile` 签名+排序） |
| `app/services/vision.py` | **停用**（保留文件以便回退，标记 deprecated） |
| `app/routers/parts.py` | ~30 行修改（`_process_version` 管道） |
| `app/templates/review_workbench.html` | ~40 行修改（PanelA 视图分组渲染） |

## 风险与注意事项

1. **存量数据不受影响** — 新 pipeline 只在 `_process_version` 中起作用，已有维度的 `view_name=None`、`sequence` 是全局编号。前端需要考虑兼容：`view_name` 为空的维度归入统一组。

2. **LLM API 失败** — 全部通过空 `StructureResult` 优雅降级。任何 LLM 错误都不会中断整个处理流程。

3. **视图边界精度** — bbox 偏差 30-50px 对 point-in-bbox 判断影响不大。但极端情况（两个视图紧邻）下，边界上的尺寸可能归属错误。可接受，因为边界区域的尺寸很少。

4. **协调器匹配** — `_has_match` 按 nominal 值和 dim_type 匹配。同一视图内不同位置的相同值会被去重。这是已有行为，在本方案中不影响。

5. **Phase 4 性能** — 每次验证额外调用 1 次 API per view。对于典型图纸（2 页 × 3 视图 = 6 次调用），总 API 调用量约 1+3+3=7 次，低于旧方案 9 次。

6. **提示词迭代** — 结构分析提示词可能需要根据实际图纸调整。第一个版本使用上述 Prompt，后续根据失败案例优化。
