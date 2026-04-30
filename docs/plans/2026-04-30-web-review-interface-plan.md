# Web 端图纸审核界面 — 实现计划

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 实现 Web 端交互式图纸审核界面：左侧可缩放 JPG 图纸 + 可拖拽标注，右侧标注列表 + 逐条讨论 + 审核结论。

**Architecture:** FastAPI 后端新增 review 路由和 API 端点，Jinja2 模板渲染页面骨架，全部交互逻辑用内联 Vanilla JS + CSS 实现，零外部前端依赖。

**Tech Stack:** FastAPI, SQLAlchemy, Jinja2, pdfplumber (PDF→JPG), Vanilla JS, CSS Transform

---

### Task 1: PDF → JPG 图片生成服务

**Files:**
- Create: `app/services/image_gen.py`

**Step 1: 创建 image_gen.py**

```python
"""PDF → JPG rasterisation for web display."""

import os
import pdfplumber


def generate_drawing_images(drawing_id: int, pdf_path: str, output_dir: str) -> list[str]:
    """Rasterise each page of a PDF to JPG. Returns list of JPG filenames."""
    os.makedirs(output_dir, exist_ok=True)
    jpg_names: list[str] = []

    with pdfplumber.open(pdf_path) as pdf:
        for page_num, page in enumerate(pdf.pages, start=1):
            img = page.to_image(resolution=300)
            jpg_name = f"page_{page_num}.jpg"
            jpg_path = os.path.join(output_dir, jpg_name)
            img.save(jpg_path, format="JPEG", quality=85)
            jpg_names.append(jpg_name)

    return jpg_names
```

**Step 2: 在版本处理流程中调用图片生成**

修改 `app/routers/parts.py:_process_version()`，处理 PDF 同时生成 JPG 到 `static/drawings/{drawing_id}/`。

**Step 3: Commit**

---

### Task 2: 数据模型变更

**Files:**
- Modify: `app/models.py`

**Step 1: Dimension 新增 review_status 字段**

在 `Dimension` 类中添加：

```python
class ReviewStatus(str, enum.Enum):
    pending = "pending"
    confirmed = "confirmed"
    questionable = "questionable"
```

在 `Dimension` 表添加列：

```python
review_status = Column(Enum(ReviewStatus), default=ReviewStatus.pending)
```

**Step 2: 新增 ReviewMessage 表**

```python
class ReviewMessage(Base):
    __tablename__ = "review_messages"

    id = Column(Integer, primary_key=True, index=True)
    dimension_id = Column(Integer, ForeignKey("dimensions.id"), nullable=False)
    author = Column(String(100), nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    dimension = relationship("Dimension", back_populates="messages")
```

在 `Dimension` 类添加反向关系：

```python
messages = relationship("ReviewMessage", back_populates="dimension", order_by="ReviewMessage.created_at")
```

**Step 3: Commit**

---

### Task 3: 审核 API 路由

**Files:**
- Create: `app/routers/review.py`

所有 API 以 `/api` 为前缀。需要实现的端点：

| 方法 | 路由 | 功能 |
|------|------|------|
| GET | `/parts/{part_id}/versions/{version_id}/review` | 渲染审核页面 |
| GET | `/api/versions/{version_id}/drawings/{drawing_id}/dimensions` | 获取标注列表 |
| POST | `/api/dimensions` | 手动新增标注 |
| PATCH | `/api/dimensions/{dimension_id}` | 更新标注（坐标、值、review_status） |
| DELETE | `/api/dimensions/{dimension_id}` | 删除标注 |
| GET | `/api/dimensions/{dimension_id}/messages` | 获取讨论记录 |
| POST | `/api/dimensions/{dimension_id}/messages` | 发送讨论消息 |
| PATCH | `/api/versions/{version_id}/conclusion` | 提交审核结论 |

**Step 1: 创建 review.py 路由骨架**

```python
from fastapi import APIRouter, Depends, HTTPException, Request, Form
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from datetime import datetime
import os

from ..database import get_db
from ..models import (
    Part, Version, Drawing, Dimension, ReviewMessage,
    ProcessingStatus, ConfirmResult, DimensionType, DimensionSource, ReviewStatus,
)

router = APIRouter(prefix="/parts", tags=["review"])
api = APIRouter(prefix="/api")
templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "../templates"))
```

**Step 2: 实现审核页面路由**

```python
@router.get("/{part_id}/versions/{version_id}/review", response_class=HTMLResponse)
def review_page(request: Request, part_id: int, version_id: int, db: Session = Depends(get_db)):
    part = db.query(Part).filter(Part.id == part_id).first()
    if not part:
        raise HTTPException(status_code=404, detail="零件不存在")
    version = db.query(Version).filter(Version.id == version_id, Version.part_id == part_id).first()
    if not version:
        raise HTTPException(status_code=404, detail="版本不存在")
    return templates.TemplateResponse("review/index.html", {
        "request": request, "part": part, "version": version,
    })
```

**Step 3: 实现标注 CRUD API**

```python
@api.get("/versions/{version_id}/drawings/{drawing_id}/dimensions")
def list_dimensions(version_id: int, drawing_id: int, db: Session = Depends(get_db)):
    dims = db.query(Dimension).filter(Dimension.drawing_id == drawing_id).order_by(Dimension.sequence).all()
    return JSONResponse([{
        "id": d.id, "sequence": d.sequence, "value": d.value,
        "nominal": d.nominal, "tolerance": d.tolerance, "dim_type": d.dim_type.value,
        "source": d.source.value, "anchor_x": d.anchor_x, "anchor_y": d.anchor_y,
        "view_name": d.view_name,
        "review_status": d.review_status.value if d.review_status else "pending",
        "message_count": len(d.messages) if d.messages else 0,
    } for d in dims])

@api.post("/dimensions")
async def create_dimension(request: Request):
    data = await request.json()
    # data: drawing_id, sequence, value, nominal, tolerance, dim_type, anchor_x, anchor_y
    db: Session = next(get_db())
    try:
        dim = Dimension(
            drawing_id=data["drawing_id"], sequence=data["sequence"],
            value=data["value"], nominal=data.get("nominal"),
            tolerance=data.get("tolerance"),
            dim_type=DimensionType(data["dim_type"]),
            anchor_x=data.get("anchor_x"), anchor_y=data.get("anchor_y"),
            source=DimensionSource.llm, review_status=ReviewStatus.pending,
        )
        db.add(dim)
        db.commit()
        db.refresh(dim)
        return JSONResponse({"id": dim.id, "sequence": dim.sequence}, status_code=201)
    finally:
        db.close()

@api.patch("/dimensions/{dimension_id}")
async def update_dimension(dimension_id: int, request: Request):
    data = await request.json()
    db: Session = next(get_db())
    try:
        dim = db.query(Dimension).filter(Dimension.id == dimension_id).first()
        if not dim:
            raise HTTPException(status_code=404)
        for key in ("sequence", "value", "nominal", "tolerance", "anchor_x", "anchor_y", "view_name"):
            if key in data:
                setattr(dim, key, data[key])
        if "dim_type" in data:
            dim.dim_type = DimensionType(data["dim_type"])
        if "review_status" in data:
            dim.review_status = ReviewStatus(data["review_status"])
        db.commit()
        return JSONResponse({"ok": True})
    finally:
        db.close()

@api.delete("/dimensions/{dimension_id}")
def delete_dimension(dimension_id: int, db: Session = Depends(get_db)):
    dim = db.query(Dimension).filter(Dimension.id == dimension_id).first()
    if not dim:
        raise HTTPException(status_code=404)
    # 先删关联消息，再删标注
    db.query(ReviewMessage).filter(ReviewMessage.dimension_id == dimension_id).delete()
    db.delete(dim)
    db.commit()
    return JSONResponse({"ok": True})
```

**Step 4: 实现讨论消息 API**

```python
@api.get("/dimensions/{dimension_id}/messages")
def list_messages(dimension_id: int, db: Session = Depends(get_db)):
    msgs = db.query(ReviewMessage).filter(
        ReviewMessage.dimension_id == dimension_id
    ).order_by(ReviewMessage.created_at).all()
    return JSONResponse([{
        "id": m.id, "author": m.author, "content": m.content,
        "created_at": m.created_at.strftime("%Y-%m-%d %H:%M"),
    } for m in msgs])

@api.post("/dimensions/{dimension_id}/messages")
async def create_message(dimension_id: int, request: Request):
    data = await request.json()
    db: Session = next(get_db())
    try:
        msg = ReviewMessage(
            dimension_id=dimension_id, author=data["author"],
            content=data["content"],
        )
        db.add(msg)
        db.commit()
        db.refresh(msg)
        return JSONResponse({
            "id": msg.id, "author": msg.author, "content": msg.content,
            "created_at": msg.created_at.strftime("%Y-%m-%d %H:%M"),
        }, status_code=201)
    finally:
        db.close()
```

**Step 5: 实现审核结论 API**

```python
@api.patch("/versions/{version_id}/conclusion")
async def submit_conclusion(version_id: int, request: Request):
    data = await request.json()
    db: Session = next(get_db())
    try:
        version = db.query(Version).filter(Version.id == version_id).first()
        if not version:
            raise HTTPException(status_code=404)
        version.confirm_result = ConfirmResult(data["result"])  # "approved" / "rejected"
        version.status = ProcessingStatus.confirmed
        version.notes = data.get("notes", "")
        version.confirmed_at = datetime.utcnow()
        db.commit()
        return JSONResponse({"ok": True})
    finally:
        db.close()
```

**Step 6: 注册路由**

在 `app/main.py` 中 `from .routers import review` 并 `app.include_router(review.router)` 和 `app.include_router(review.api)`。

**Step 7: Commit**

---

### Task 4: 修改版本处理流程（集成 JPG 生成）

**Files:**
- Modify: `app/routers/parts.py`

**Step 1: 在 _process_version 中调用图片生成**

在 `app/routers/parts.py` 顶部添加导入：
```python
from ..services.image_gen import generate_drawing_images
```

在 `_process_version` 函数中，处理每个 PDF 后生成 JPG：
```python
STATIC_DIR = os.path.join(os.path.dirname(__file__), "..", "static", "drawings")

# 在 for drawing_id, pdf_path in drawing_paths: 循环内，pdfplumber 提取之后
output_dir = os.path.join(STATIC_DIR, str(drawing_id))
try:
    jpg_names = generate_drawing_images(drawing_id, pdf_path, output_dir)
except Exception:
    pass  # 非致命，图片生成失败不影响尺寸提取
```

**Step 2: Commit**

---

### Task 5: 审核页面模板 — HTML 骨架 + CSS 布局

**Files:**
- Create: `app/templates/review/index.html`

**Step 1: 创建基础 HTML 骨架**

```html
{% extends "base.html" %}
{% block title %}{{ part.name }} — 图纸审核{% endblock %}

{% block content %}
<style>
  /* 全宽布局覆盖 base.html 的 max-w-5xl */
  main.max-w-5xl { max-width: none !important; padding: 0 !important; }

  .review-layout {
    display: flex;
    height: calc(100vh - 52px);  /* nav 高度 */
  }

  /* 左侧：图纸区 */
  .review-left {
    flex: 65;
    display: flex;
    flex-direction: column;
    background: #e5e7eb;
    overflow: hidden;
    position: relative;
  }

  .drawing-tabs {
    display: flex;
    gap: 2px;
    padding: 8px 12px 0;
  }
  .drawing-tab {
    padding: 6px 16px;
    background: #d1d5db;
    border-radius: 6px 6px 0 0;
    font-size: 13px;
    cursor: pointer;
    border: none;
    color: #6b7280;
  }
  .drawing-tab.active {
    background: #f3f4f6;
    color: #111827;
    font-weight: 600;
  }

  .canvas-container {
    flex: 1;
    position: relative;
    overflow: hidden;
    cursor: grab;
    margin: 0 12px 12px;
    border-radius: 8px;
    background: #d1d5db;
  }
  .canvas-container:active { cursor: grabbing; }
  .canvas-container.grabbing { cursor: grabbing; }
  .canvas-container.adding { cursor: crosshair; }

  .canvas-inner {
    position: absolute;
    transform-origin: 0 0;
  }
  .canvas-inner img {
    display: block;
    pointer-events: none;
    user-select: none;
    box-shadow: 0 4px 24px rgba(0,0,0,0.15);
  }

  /* 标注圆圈 */
  .anno-marker {
    position: absolute;
    width: 28px;
    height: 28px;
    border-radius: 50%;
    border: 2px solid;
    display: flex;
    align-items: center;
    justify-content: center;
    cursor: move;
    font-size: 12px;
    font-weight: 700;
    color: #fff;
    z-index: 10;
    transform: translate(-50%, -50%);
    user-select: none;
    transition: box-shadow 0.15s;
  }
  .anno-marker:hover { box-shadow: 0 0 0 4px rgba(0,0,0,0.15); }
  .anno-marker.pending  { background: #9ca3af; border-color: #6b7280; }
  .anno-marker.confirmed { background: #22c55e; border-color: #16a34a; }
  .anno-marker.questionable { background: #eab308; border-color: #ca8a04; }
  .anno-marker.selected { box-shadow: 0 0 0 4px #3b82f6; }
  .anno-marker.filtered-out { opacity: 0.2; pointer-events: none; }

  .anno-delete {
    position: absolute;
    top: -6px;
    right: -6px;
    width: 16px;
    height: 16px;
    border-radius: 50%;
    background: #ef4444;
    color: #fff;
    font-size: 10px;
    line-height: 16px;
    text-align: center;
    cursor: pointer;
    display: none;
  }
  .anno-marker:hover .anno-delete { display: block; }

  .anno-tooltip {
    position: absolute;
    bottom: 120%;
    left: 50%;
    transform: translateX(-50%);
    background: #1f2937;
    color: #fff;
    padding: 4px 8px;
    border-radius: 4px;
    font-size: 12px;
    white-space: nowrap;
    display: none;
    pointer-events: none;
  }
  .anno-marker:hover .anno-tooltip { display: block; }

  /* 新增标注弹窗 */
  .anno-popup {
    position: absolute;
    background: #fff;
    border: 1px solid #d1d5db;
    border-radius: 8px;
    padding: 12px;
    box-shadow: 0 4px 12px rgba(0,0,0,0.15);
    z-index: 20;
    min-width: 180px;
  }

  /* 底部工具栏 */
  .toolbar {
    display: flex;
    gap: 8px;
    padding: 8px 12px;
    background: #f9fafb;
    border-top: 1px solid #e5e7eb;
  }
  .toolbar button {
    padding: 6px 14px;
    border-radius: 6px;
    border: 1px solid #d1d5db;
    background: #fff;
    font-size: 13px;
    cursor: pointer;
  }
  .toolbar button:hover { background: #f3f4f6; }
  .toolbar button.primary { background: #2563eb; color: #fff; border-color: #2563eb; }

  /* 右侧：审核面板 */
  .review-right {
    flex: 35;
    display: flex;
    flex-direction: column;
    background: #fff;
    border-left: 1px solid #e5e7eb;
    min-width: 360px;
    max-width: 480px;
  }

  /* 上区：标注列表 */
  .anno-list-panel {
    flex: 4;
    display: flex;
    flex-direction: column;
    overflow: hidden;
    border-bottom: 1px solid #e5e7eb;
  }
  .filter-bar {
    display: flex;
    gap: 4px;
    padding: 10px 12px;
  }
  .filter-btn {
    flex: 1;
    padding: 5px 0;
    border: 1px solid #e5e7eb;
    border-radius: 6px;
    background: #fff;
    font-size: 12px;
    cursor: pointer;
    text-align: center;
  }
  .filter-btn.active { background: #2563eb; color: #fff; border-color: #2563eb; }

  .anno-list {
    flex: 1;
    overflow-y: auto;
    padding: 0 12px;
  }
  .anno-row {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 8px;
    border-radius: 6px;
    cursor: pointer;
    font-size: 13px;
    border: 1px solid transparent;
  }
  .anno-row:hover { background: #f9fafb; }
  .anno-row.selected { background: #eff6ff; border-color: #93c5fd; }
  .anno-row .mini-circle {
    width: 24px; height: 24px;
    border-radius: 50%;
    font-size: 11px; font-weight: 700;
    display: flex; align-items: center; justify-content: center;
    color: #fff; flex-shrink: 0;
  }
  .anno-row .mini-circle.pending { background: #9ca3af; }
  .anno-row .mini-circle.confirmed { background: #22c55e; }
  .anno-row .mini-circle.questionable { background: #eab308; }

  /* 中区：详情+讨论 */
  .detail-panel {
    flex: 5;
    display: flex;
    flex-direction: column;
    overflow: hidden;
    border-bottom: 1px solid #e5e7eb;
  }
  .detail-header {
    padding: 12px;
    border-bottom: 1px solid #e5e7eb;
    font-size: 13px;
  }
  .detail-header .meta { color: #6b7280; font-size: 12px; }
  .status-btns { display: flex; gap: 6px; margin-top: 8px; }
  .status-btn {
    flex: 1; padding: 5px; border-radius: 6px; border: 1px solid #d1d5db;
    font-size: 12px; cursor: pointer; background: #fff;
  }
  .status-btn.active.pending { background: #6b7280; color: #fff; border-color: #6b7280; }
  .status-btn.active.confirmed { background: #22c55e; color: #fff; border-color: #16a34a; }
  .status-btn.active.questionable { background: #eab308; color: #fff; border-color: #ca8a04; }

  .messages-list {
    flex: 1;
    overflow-y: auto;
    padding: 12px;
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  .msg-bubble {
    background: #f3f4f6;
    padding: 8px 10px;
    border-radius: 8px;
    font-size: 13px;
    max-width: 90%;
    align-self: flex-start;
  }
  .msg-author { font-weight: 600; font-size: 12px; color: #374151; }
  .msg-time { font-size: 11px; color: #9ca3af; margin-left: 8px; }
  .msg-input-row {
    display: flex; gap: 6px; padding: 8px 12px;
    border-top: 1px solid #e5e7eb;
  }
  .msg-input-row input {
    flex: 1; padding: 8px; border-radius: 6px; border: 1px solid #d1d5db;
    font-size: 13px;
  }
  .msg-input-row button {
    padding: 8px 14px; border-radius: 6px; background: #2563eb;
    color: #fff; border: none; font-size: 13px; cursor: pointer;
  }

  /* 下区：审核结论 */
  .conclusion-panel {
    padding: 12px;
    background: #fafafa;
  }
  .conclusion-stats {
    font-size: 13px; margin-bottom: 8px; color: #374151;
  }
  .conclusion-actions { display: flex; gap: 8px; align-items: center; }
  .conclusion-actions textarea {
    flex: 1; padding: 8px; border-radius: 6px; border: 1px solid #d1d5db;
    font-size: 13px; resize: none; height: 48px;
  }
</style>

<!-- HTML 骨架 -->
<div class="review-layout">
  <div class="review-left">
    <div class="drawing-tabs" id="drawingTabs"></div>
    <div class="canvas-container" id="canvasContainer">
      <div class="canvas-inner" id="canvasInner">
        <img id="drawingImage" src="" alt="图纸" draggable="false">
      </div>
    </div>
    <div class="toolbar">
      <button id="btnAddAnno" class="primary">+ 添加标注</button>
      <button id="btnFitScreen">适应窗口</button>
      <button id="btnUndo" disabled>↶ 撤销</button>
    </div>
  </div>

  <div class="review-right">
    <!-- 上区 -->
    <div class="anno-list-panel">
      <div class="filter-bar">
        <button class="filter-btn active" data-filter="all">全部</button>
        <button class="filter-btn" data-filter="pending">待审</button>
        <button class="filter-btn" data-filter="questionable">存疑</button>
        <button class="filter-btn" data-filter="confirmed">确认</button>
      </div>
      <div class="anno-list" id="annoList"></div>
    </div>

    <!-- 中区 -->
    <div class="detail-panel" id="detailPanel">
      <div class="detail-header" id="detailHeader">选择一个标注</div>
      <div class="messages-list" id="messagesList"></div>
      <div class="msg-input-row">
        <input id="messageInput" placeholder="输入讨论内容...">
        <button id="btnSendMsg">发送</button>
      </div>
    </div>

    <!-- 下区 -->
    <div class="conclusion-panel">
      <div class="conclusion-stats" id="conclusionStats"></div>
      <div class="conclusion-actions">
        <textarea id="conclusionNotes" placeholder="审核备注..."></textarea>
        <button id="btnApprove" class="status-btn" style="background:#22c55e;color:#fff;border-color:#16a34a;">通过</button>
        <button id="btnReject" class="status-btn" style="background:#ef4444;color:#fff;border-color:#dc2626;">驳回</button>
      </div>
    </div>
  </div>
</div>
{% endblock %}
```

**Step 2: Commit**

---

### Task 6: 审核页面模板 — JavaScript 交互逻辑

**Files:**
- Modify: `app/templates/review/index.html` (在 `{% endblock %}` 前添加 `<script>` 块)

**Step 1: 初始化状态与数据加载**

JS 脚本读取代办数据（从模板变量中通过 `{{ version.id }}` 等获取），加载图纸列表和第一张图纸的标注数据。

关键状态变量：
- `currentDrawingId` — 当前显示的图纸 ID
- `dimensions` — 当前图纸的全部标注数组
- `selectedDimId` — 当前选中的标注 ID
- `filterStatus` — 当前筛选状态（all/pending/confirmed/questionable）
- `zoom/pan` — `{scale, offsetX, offsetY}`
- `undoStack` — 操作历史栈（最多 10 步）
- `addingMode` — 是否在添加标注模式

**Step 2: 实现图片缩放与平移**

- `wheel` 事件：`event.preventDefault()` + 以鼠标位置为中心更新 scale
- `mousedown/mousemove/mouseup` 在 canvas-container 上：区分拖拽空白（平移）vs 拖拽标注圆圈
- `dblclick`：恢复到适应窗口缩放比
- "适应窗口"按钮：计算容器与图片比例，设置 scale 使图片完整显示

**Step 3: 实现标注圆圈渲染**

函数 `renderMarkers()`：根据当前 dimensions、filterStatus、selectedDimId 清空并重建 DOM。每个 marker 是绝对定位的 div，坐标通过 `(anchor_x * scale + offsetX, anchor_y * scale + offsetY)` 计算。序号文字大小用 `1/scale` 反缩放。

**Step 4: 实现标注拖拽移动**

在 marker 上处理 `pointerdown` → `pointermove` → `pointerup`：
- 记录偏移量
- 移动时更新 CSS left/top
- 松手时根据当前 scale/offset 反算新的 anchor_x/anchor_y → PATCH API

**Step 5: 实现标注新增**

点击"+ 添加标注"→进入 addingMode → canvas 光标变 crosshair → 点击图面 → 弹出 popup 表单（类型下拉+值输入）→ 确认 → POST API → 刷新。

**Step 6: 实现标注删除**

点击 marker 的 × → confirm → DELETE API → 刷新。

**Step 7: 实现撤销栈**

操作封装函数包装 push/pop：
```js
function pushUndo(action) {
  undoStack.push(action);
  if (undoStack.length > 10) undoStack.shift();
  updateUndoButton();
}
```
撤销时根据 action.type（create/update/delete）调用对应 API 还原。

**Step 8: 实现右侧面板联动**

- 点击 anno-row → setSelected(dimId) → 高亮 marker + 加载消息列表 + 填充 detail header
- 点击 marker → 同上
- filter 按钮 → 更新 filterStatus → 重渲染 markers + 重渲染列表
- 状态切换按钮 → PATCH review_status → 刷新
- 发送消息 → POST messages API → 刷新消息列表

**Step 9: 实现审核结论提交**

点击通过/驳回 → PATCH conclusion API → 提示成功 → 跳转回零件详情页。

**Step 10: Commit**

---

### Task 7: 注册路由并集成

**Files:**
- Modify: `app/main.py`

**Step 1: 注册新路由**

在 `app/main.py` 中：
```python
from .routers import parts, review

app.include_router(parts.router)
app.include_router(review.router)
app.include_router(review.api)
```

**Step 2: 从详情页添加审核入口**

在 `app/templates/parts/detail.html` 中，version 状态为 `ready` 时旁边加一个"进入审核"按钮，链接到 `/parts/{part_id}/versions/{version_id}/review`。

**Step 3: 确保 static/drawings 目录存在**

在 `app/main.py` 启动时创建目录：
```python
os.makedirs(os.path.join(os.path.dirname(__file__), "static", "drawings"), exist_ok=True)
```

**Step 4: Commit**

---

### Task 8: 端到端验证

不写自动化测试（纯 UI 交互），手动验证以下流程：

1. 创建零件 → 上传 PDF 版本 → 等待处理完成（status=ready）
2. 检查 `static/drawings/{drawing_id}/` 下有 JPG 文件生成
3. 点击"进入审核" → 左侧显示图纸，标注圆圈在正确位置
4. 鼠标滚轮缩放正常
5. 拖拽标注圆圈移动，刷新后位置保持
6. 点击 + 添加标注，在图上点击放置，弹窗填写后创建成功
7. 删除标注，撤销恢复
8. 筛选按钮切换正常
9. 点击标注 → 右侧显示详情，发送讨论消息
10. 提交审核结论（通过/驳回），零件详情页状态更新

**Step 2: 修复验证中发现的问题**

**Step 3: Final commit**

---

### 执行顺序

任务 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8，顺序依赖，不可并行。
