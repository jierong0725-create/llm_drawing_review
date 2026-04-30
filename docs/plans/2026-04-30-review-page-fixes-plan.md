# 审核页面修复实现计划

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 修复审核页面两个核心问题：图纸图片加载失败时显示友好占位符并记录错误；标注点密集重叠时自动径向分散并绘制引导线。

**Architecture:** 后端在 `_process_version` 中捕获图像生成错误并写入 `version.notes`；前端给 `<img>` 加 `onerror` 占位逻辑；在 `renderMarkers()` 前插入 `spreadPositions()` 分散算法，用 SVG overlay 绘制引导线。

**Tech Stack:** FastAPI + Jinja2 模板 + 原生 JS（无框架）+ SVG

---

## Task 1：后端 — 图像生成错误记录到 version.notes

**Files:**
- Modify: `app/routers/parts.py:140-148`

**Step 1：定位目标代码**

打开 `app/routers/parts.py`，找到 `_process_version` 函数中图像生成部分（约 141-145 行）：

```python
try:
    generate_drawing_images(drawing_id, pdf_path, output_dir)
except Exception:
    pass  # Non-fatal: image generation failure shouldn't block dimension extraction
```

**Step 2：替换为带错误记录的版本**

将上面的代码替换为：

```python
try:
    generate_drawing_images(drawing_id, pdf_path, output_dir)
except Exception as img_exc:
    # Record image generation failure in notes for diagnosis;
    # dimension data is still valid and usable.
    try:
        img_err_msg = f"[图像生成失败 drawing {drawing_id}: {img_exc}]"
        ver = db.query(Version).filter(Version.id == version_id).first()
        if ver:
            ver.notes = (ver.notes + "\n" + img_err_msg) if ver.notes else img_err_msg
            db.commit()
    except Exception:
        pass
```

**Step 3：手动验证（无测试框架，目视检查）**

启动服务器，重新上传一个 PDF，故意让 image_gen 失败（可临时在 `generate_drawing_images` 第一行加 `raise RuntimeError("test")`），确认 version.notes 字段有错误信息，然后还原临时代码。

**Step 4：Commit**

```bash
git add app/routers/parts.py
git commit -m "fix: record image generation errors in version.notes instead of silently discarding"
```

---

## Task 2：前端 — 图片加载失败时显示占位卡片

**Files:**
- Modify: `app/templates/review/index.html`

**Step 1：在 canvas-inner 内添加占位卡片 HTML**

找到模板中：
```html
<div class="canvas-inner" id="canvasInner">
  <img id="drawingImage" src="" alt="图纸" draggable="false">
</div>
```

替换为：
```html
<div class="canvas-inner" id="canvasInner">
  <img id="drawingImage" src="" alt="图纸" draggable="false">
  <div id="drawingPlaceholder" style="display:none;width:600px;height:400px;background:#f9fafb;border-radius:8px;display:none;align-items:center;justify-content:center;flex-direction:column;gap:12px;color:#9ca3af;font-size:14px;border:2px dashed #d1d5db;">
    <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
      <path d="M4 16l4-4 4 4 4-8 4 4"/>
      <rect x="3" y="3" width="18" height="18" rx="2"/>
    </svg>
    <span>图纸图片未生成</span>
    <span style="font-size:12px;color:#d1d5db">请在零件详情页重新上传此版本的 PDF</span>
  </div>
</div>
```

**Step 2：在 `<style>` 块中添加占位符样式**

在已有的 `<style>` 块末尾（`</style>` 之前）添加：

```css
#drawingPlaceholder {
  display: none;
  width: 600px;
  height: 400px;
  background: #f9fafb;
  border-radius: 8px;
  align-items: center;
  justify-content: center;
  flex-direction: column;
  gap: 12px;
  color: #9ca3af;
  font-size: 14px;
  border: 2px dashed #d1d5db;
}
#drawingPlaceholder.visible {
  display: flex;
}
```

**Step 3：修改 `switchDrawing` 函数中的图片加载逻辑**

找到（约 398 行）：
```javascript
drawingImage.src = `/static/drawings/${drawingId}/page_1.jpg`;
drawingImage.onload = () => {
  imgNaturalW = drawingImage.naturalWidth;
  imgNaturalH = drawingImage.naturalHeight;
  fitScreen();
};
```

替换为：
```javascript
const placeholder = document.getElementById("drawingPlaceholder");
drawingImage.style.display = "block";
placeholder.classList.remove("visible");

drawingImage.onload = () => {
  imgNaturalW = drawingImage.naturalWidth;
  imgNaturalH = drawingImage.naturalHeight;
  placeholder.classList.remove("visible");
  fitScreen();
};
drawingImage.onerror = () => {
  drawingImage.style.display = "none";
  placeholder.classList.add("visible");
};
drawingImage.src = `/static/drawings/${drawingId}/page_1.jpg`;
```

**Step 4：用浏览器验证**

访问 `http://localhost:8000/parts/2/versions/1/review`（drawing_id=1，图片不存在），应显示占位卡片。访问其他有图片的版本，应正常显示图纸。

**Step 5：Commit**

```bash
git add app/templates/review/index.html
git commit -m "fix: show placeholder card when drawing image fails to load"
```

---

## Task 3：前端 — 标注点径向分散算法

**Files:**
- Modify: `app/templates/review/index.html`（JS 部分）

**Step 1：在 canvas-inner 中添加 SVG overlay**

找到：
```html
<div class="canvas-inner" id="canvasInner">
```

在其内部、`<img>` 之前添加 SVG（注意 SVG 要放在 img 之后，让 markers 在最上层）：

在 `<img id="drawingImage" ...>` 之后（占位符之后）添加：
```html
<svg id="leaderLines" style="position:absolute;top:0;left:0;width:100%;height:100%;pointer-events:none;overflow:visible;"></svg>
```

**Step 2：在 JS 全局变量区添加常量**

在 `let zoom = 1;` 附近添加：
```javascript
const MARKER_DIAM = 28; // px，标注圆直径
```

**Step 3：添加 `spreadPositions` 函数**

在 `renderMarkers` 函数之前插入以下函数：

```javascript
/**
 * 接收标注数组（含 anchor_x, anchor_y），返回分散后的屏幕坐标映射。
 * key: dim.id, value: {sx, sy} 分散后的屏幕坐标（已含 zoom/offset）。
 * 被移位的标注同时记录原始坐标 {ox, oy}，用于绘制引导线。
 */
function spreadPositions(dims) {
  const R = MARKER_DIAM; // 碰撞半径
  const positions = dims
    .filter(d => d.anchor_x != null && d.anchor_y != null)
    .map(d => ({
      id: d.id,
      ox: d.anchor_x * zoom + offsetX,  // 原始屏幕 x
      oy: d.anchor_y * zoom + offsetY,  // 原始屏幕 y
      sx: d.anchor_x * zoom + offsetX,  // 分散后屏幕 x（初始同原始）
      sy: d.anchor_y * zoom + offsetY,  // 分散后屏幕 y
    }));

  // 找冲突组（贪心 union-find 风格）
  const visited = new Set();
  const groups = [];
  for (let i = 0; i < positions.length; i++) {
    if (visited.has(i)) continue;
    const group = [i];
    visited.add(i);
    for (let j = i + 1; j < positions.length; j++) {
      if (visited.has(j)) continue;
      const dx = positions[i].ox - positions[j].ox;
      const dy = positions[i].oy - positions[j].oy;
      if (Math.sqrt(dx * dx + dy * dy) < R) {
        group.push(j);
        visited.add(j);
      }
    }
    if (group.length > 1) groups.push(group);
  }

  // 对每个冲突组：将成员均匀分布在以质心为圆心的圆上
  for (const group of groups) {
    const cx = group.reduce((s, i) => s + positions[i].ox, 0) / group.length;
    const cy = group.reduce((s, i) => s + positions[i].oy, 0) / group.length;
    const spreadR = Math.max(R, group.length * R / (2 * Math.PI));
    group.forEach((idx, k) => {
      const angle = (2 * Math.PI * k) / group.length - Math.PI / 2;
      positions[idx].sx = cx + spreadR * Math.cos(angle);
      positions[idx].sy = cy + spreadR * Math.sin(angle);
    });
  }

  // 转为 Map<id, position>
  const map = new Map();
  for (const p of positions) map.set(p.id, p);
  return map;
}
```

**Step 4：修改 `renderMarkers` 函数以使用分散坐标**

找到 `renderMarkers` 函数，替换为：

```javascript
function renderMarkers() {
  canvasInner.querySelectorAll(".anno-marker").forEach(el => el.remove());
  canvasInner.querySelectorAll(".anno-popup").forEach(el => el.remove());

  const svgEl = document.getElementById("leaderLines");
  svgEl.innerHTML = "";

  const visibleDims = filteredDimensions().filter(d => d.anchor_x != null && d.anchor_y != null);
  const posMap = spreadPositions(visibleDims);

  visibleDims.forEach(d => {
    const pos = posMap.get(d.id);
    if (!pos) return;

    // 绘制引导线（仅当位置被移动时）
    const moved = Math.abs(pos.sx - pos.ox) > 1 || Math.abs(pos.sy - pos.oy) > 1;
    if (moved) {
      const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
      line.setAttribute("x1", pos.sx);
      line.setAttribute("y1", pos.sy);
      line.setAttribute("x2", pos.ox);
      line.setAttribute("y2", pos.oy);
      line.setAttribute("stroke", "#9ca3af");
      line.setAttribute("stroke-width", "1");
      line.setAttribute("stroke-dasharray", "3,3");
      svgEl.appendChild(line);

      // 原始位置小圆点
      const dot = document.createElementNS("http://www.w3.org/2000/svg", "circle");
      dot.setAttribute("cx", pos.ox);
      dot.setAttribute("cy", pos.oy);
      dot.setAttribute("r", "3");
      dot.setAttribute("fill", "#9ca3af");
      svgEl.appendChild(dot);
    }

    const markerSize = Math.max(20, MARKER_DIAM / Math.sqrt(zoom));
    const fontSize = Math.max(10, 12 / zoom);

    const marker = document.createElement("div");
    marker.className = `anno-marker ${d.review_status}`;
    if (d.id === selectedDimId) marker.classList.add("selected");
    marker.style.left = pos.sx + "px";
    marker.style.top = pos.sy + "px";
    marker.style.width = markerSize + "px";
    marker.style.height = markerSize + "px";
    marker.style.fontSize = fontSize + "px";
    marker.dataset.dimId = d.id;
    marker.innerHTML = `
      <span>${d.sequence}</span>
      <span class="anno-tooltip">${d.value}</span>
      <span class="anno-delete">&times;</span>
    `;

    marker.addEventListener("click", (e) => {
      e.stopPropagation();
      setSelected(d.id);
    });

    marker.querySelector(".anno-delete").addEventListener("click", (e) => {
      e.stopPropagation();
      deleteDimension(d.id);
    });

    marker.addEventListener("pointerdown", (e) => {
      e.stopPropagation();
      e.preventDefault();
      marker.setPointerCapture(e.pointerId);
      const startX = e.clientX;
      const startY = e.clientY;
      const origAnchorX = d.anchor_x;
      const origAnchorY = d.anchor_y;

      const onMove = (ev) => {
        const dx = (ev.clientX - startX) / zoom;
        const dy = (ev.clientY - startY) / zoom;
        d.anchor_x = origAnchorX + dx;
        d.anchor_y = origAnchorY + dy;
        marker.style.left = (d.anchor_x * zoom + offsetX) + "px";
        marker.style.top = (d.anchor_y * zoom + offsetY) + "px";
      };

      const onUp = async () => {
        marker.removeEventListener("pointermove", onMove);
        marker.removeEventListener("pointerup", onUp);
        const prev = { anchor_x: origAnchorX, anchor_y: origAnchorY };
        pushUndo({ type: "update", dimId: d.id, prev });
        await fetch(`/api/dimensions/${d.id}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ anchor_x: d.anchor_x, anchor_y: d.anchor_y }),
        });
        renderMarkers();
      };

      marker.addEventListener("pointermove", onMove);
      marker.addEventListener("pointerup", onUp);
    });

    canvasInner.appendChild(marker);
  });
}
```

**Step 5：用浏览器验证**

访问 `http://localhost:8000/parts/2/versions/1/review`（85 条标注），缩小视图，确认：
- 密集区域的标注点被分散，彼此不重叠
- 被移位的标注有虚线引导线指向原始位置
- 引导线终点有小圆点
- 点击标注可正常选中
- 缩放/平移后标注重新分散（因为屏幕坐标随 zoom 变化）

**Step 6：Commit**

```bash
git add app/templates/review/index.html
git commit -m "fix: spread overlapping annotation markers with radial layout and leader lines"
```

---

## Task 4：端到端验证

**Step 1：重启服务器，用浏览器打开各页面**

```bash
# 停止旧进程（如有）
pkill -f "uvicorn app.main" 2>/dev/null || true
# 重启
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

**Step 2：检查清单**

- [ ] `/parts/2/versions/1/review` — 图纸区显示占位卡片（图片 404）
- [ ] `/parts/3/versions/3/review` — 图纸正常显示，85 条标注分散，无重叠
- [ ] 缩放后标注重新分散
- [ ] 点击列表中的标注，地图标注高亮
- [ ] 存疑/确认状态切换后颜色变化
- [ ] 通过/驳回按钮跳回详情页

**Step 3：截图记录最终效果**

```bash
python -c "
from playwright.sync_api import sync_playwright
import os
os.makedirs('/tmp/final_screenshots', exist_ok=True)
with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    pg = b.new_context(viewport={'width':1280,'height':900}).new_page()
    pg.goto('http://localhost:8000/parts/2/versions/1/review', wait_until='networkidle')
    pg.screenshot(path='/tmp/final_screenshots/fix1_placeholder.png', full_page=True)
    pg.goto('http://localhost:8000/parts/3/versions/3/review', wait_until='networkidle')
    pg.screenshot(path='/tmp/final_screenshots/fix2_spread.png', full_page=True)
    b.close()
    print('done')
"
```
