# 审核页面修复设计

## 问题 1：图纸图片加载失败

### 根本原因
`_process_version` 后台任务中 `generate_drawing_images()` 的异常被 `except Exception: pass` 静默吞掉，错误信息丢失；图片文件不存在时前端 `<img>` 只显示破损图标。

### 修复方案 B

**后端**：将 `except Exception: pass` 改为捕获后写入 `version.notes`（追加，不覆盖），保留详细错误信息供排查。

**前端**：
- `<img id="drawingImage">` 加 `onerror` 事件，触发时隐藏 `<img>`，展示一个占位卡片（居中图标 + "图纸图片未生成，请重新上传版本" 提示）。
- 图片正常加载后自动隐藏占位卡片。

由于临时 PDF 文件在处理后即删除，现有坏记录无法服务端重新渲染；用户需重新上传 PDF 版本。

---

## 问题 2：标注点重叠

### 根本原因
85 个标注的 `anchor_x/anchor_y` 由 PDF 提取，许多坐标在物理上靠近；`renderMarkers()` 按原始坐标渲染，没有排斥算法，低缩放时大量标注堆叠无法点击。

### 修复方案 A（径向分散 + 引导线）

在 `renderMarkers()` 之前插入 `spreadPositions(dims)` 函数：

1. 将每个标注的屏幕坐标 `(anchor_x * zoom + offsetX, anchor_y * zoom + offsetY)` 作为初始位置。
2. 迭代检测：若两点距离 < `MARKER_DIAM`（28px），将它们加入同一冲突组。
3. 对每个冲突组：以组内各点质心为圆心，按标注序号均匀分布在半径 `r = max(MARKER_DIAM, n * MARKER_DIAM / (2π))` 的圆上。
4. 渲染时使用分散后的屏幕坐标作为标注位置。
5. 对被移位的标注（原坐标 ≠ 分散坐标），在 `<svg>` overlay 上画一条细引导线从标注圆心指向原始坐标。

SVG overlay 与 `canvasInner` 同层（`position:absolute; top:0; left:0`），`pointer-events:none`，随 zoom/pan 同步更新。
