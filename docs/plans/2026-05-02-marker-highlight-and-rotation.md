# Marker 高亮配色 + 跟随尺寸旋转 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 让 review workbench 上的尺寸标注框（MarkerBox）在 pending 状态下使用区别于图纸黑灰和审查状态色（绿/黄/红）的浅高亮色；并让矩形框跟随尺寸文字方向旋转、序号 badge 缩到比图纸尺寸文字小一号、置于尺寸文本前端。

**Architecture:**
1. **配色**：仅修改 `STATUS_COLOR.pending`（前端常量），从灰色改为浅高亮色（cyan/teal 类，半透明描边 + 极淡底色），其他状态色不动。
2. **旋转**：extractor 的 token 已带 `theta`（弧度→度，line 395）。把 dimension 的主导 theta 持久化到 `Dimension.rotation_deg`，由 API 透传给前端；`MarkerBox` 用 CSS `transform: rotate(...)` 围绕 bbox 中心旋转矩形+badge，badge 锚到旋转后矩形的"前端"（文本起点侧）。
3. **字号**：badge 字号从 `max(9, min(11, ...))` 降一档到 `max(8, min(10, ...))`，并参考同 dim 的 token `eff_size` 做"比图纸尺寸小一号"的细化。

**Tech Stack:** SQLAlchemy (SQLite, dev.db / review.db) · FastAPI · Jinja + React (Babel in-template) · pdfplumber

**关键文件速览：**
- `app/templates/review_workbench.html:18-25` — `STATUS_COLOR` 常量
- `app/templates/review_workbench.html:28-75` — `MarkerBox` 组件
- `app/models.py:88-108` — `Dimension` ORM
- `app/services/extractor.py:325-399` — token 抽取（含 `theta`）
- `app/services/extractor.py:55-90` — `ExtractedDimension` dataclass
- `app/services/analyzer.py:330-360` — tile-based pipeline 把 ExtractedDimension 写库
- `app/routers/review.py` / `app/routers/parts.py` — 给前端发 dim JSON 的接口

---

## Task 1: 引入 pending 高亮配色

**Files:**
- Modify: `app/templates/review_workbench.html:18-25`

**Step 1: 在 spa.html 或 review_workbench.html 中确认是否已有 CSS variable `--signal-highlight`**

Run: `grep -n "signal-highlight\|signal-gray" app/templates/*.html app/static/**/*.css 2>/dev/null`
Expected: 看到 `--signal-gray` 定义、确认没有 `--signal-highlight`。

**Step 2: 在 spa.html 的 `:root` 处添加新色变量**

`app/templates/spa.html`（找到 `:root { ... --signal-gray: ...; }` 处追加）：

```css
--signal-highlight: #38bdf8;       /* sky-400 — 浅高亮，区别于灰黑图纸与绿/黄/红状态 */
--signal-highlight-soft: rgba(56, 189, 248, 0.12);
```

**Step 3: 修改 STATUS_COLOR.pending**

`app/templates/review_workbench.html:18-24`：

```js
const STATUS_COLOR = {
  pending: "var(--signal-highlight)",
  confirmed: "var(--signal-green)",
  questionable: "var(--signal-amber)",
  rejected: "var(--signal-red)",
  nok: "var(--signal-red)",
};
```

**Step 4: pending 状态下让矩形底色更显眼**

修改 `MarkerBox` 描边/填充（line 46-49）：未选中时给 pending 一层极淡底色，避免只有描边在浅色里"消失"。

```js
const isPending = dim.review_status === "pending" || !dim.review_status;
// ... 在 box 的 style 里：
backgroundColor: isSelected
  ? "rgba(255,255,255,0.04)"
  : (isPending ? "var(--signal-highlight-soft)" : "transparent"),
```

**Step 5: 启动 dev server 人工验证**

Run: `uvicorn app.main:app --reload --port 8000`
打开任一含 dimensions 的 part 页，肉眼检查 pending 框为浅蓝色、底色淡蓝；改一个为 confirmed/questionable/rejected 后颜色保持原绿/黄/红。

**Step 6: Commit**

```bash
git add app/templates/spa.html app/templates/review_workbench.html
git commit -m "feat(workbench): use sky highlight color for pending markers"
```

---

## Task 2: badge 字号缩小一档

**Files:**
- Modify: `app/templates/review_workbench.html:35-36, 60-72`

**Step 1: 调整 labelFont 计算**

把 line 35 改为：

```js
const labelFont = Math.round(Math.max(8, Math.min(10, 9 / Math.sqrt(Math.max(zoom, 0.15)))));
const labelH = labelFont + 3;
```

（基础下移 1px、上限下调 1px、内边距收紧。"比图纸尺寸小一号"——图纸 token `eff_size` 在 PDF 点；以 zoom 估算屏幕字号，9/√zoom 大约比 token 视觉小 1pt）

**Step 2: 减少 badge 内边距**

把 line 61 的 `padding: "0 4px"` 改 `padding: "0 3px"`。

**Step 3: 人工验证**

刷新页面，对比一个序号 badge 和它紧邻的图纸尺寸文字，badge 应明显小一号。

**Step 4: Commit**

```bash
git add app/templates/review_workbench.html
git commit -m "feat(workbench): shrink marker badge to be smaller than drawing dim text"
```

---

## Task 3: 后端 — 给 Dimension 加 rotation_deg 字段

**Files:**
- Modify: `app/models.py:88-108`
- Modify: `app/services/extractor.py:55-90`（`ExtractedDimension`）
- Modify: `app/services/extractor.py:325-399`（聚合 dim 时记录主导 theta）
- Modify: `app/services/analyzer.py:330-360`（写库时填入 rotation）

**Step 1: 在 ExtractedDimension 上加 rotation_deg**

`app/services/extractor.py`（dataclass 区）：

```python
@dataclass
class ExtractedDimension:
    # ... existing fields ...
    rotation_deg: float = 0.0   # 主导 token 的 theta，CCW 度数（0 = 水平）
```

**Step 2: 聚合时把 token theta 透传**

在把多个 token 合并为 dimension 的位置（搜 `ExtractedDimension(` 实例化处），从该 dimension 关联的 token 列表里取 `theta` 的中位数（多 token）或唯一值（单 token）赋给 `rotation_deg`。

**Step 3: 在 Dimension ORM 加列**

`app/models.py:104` 后面：

```python
rotation_deg = Column(Float, nullable=False, default=0.0)
```

**Step 4: SQLite 加列迁移（dev.db / review.db）**

项目无 alembic，直接写一次性迁移脚本 `scripts/migrations/2026-05-02_add_rotation_deg.py`：

```python
import sqlite3, sys
for db in ("dev.db", "review.db"):
    try:
        con = sqlite3.connect(db)
        cols = [r[1] for r in con.execute("PRAGMA table_info(dimensions)").fetchall()]
        if "rotation_deg" not in cols:
            con.execute("ALTER TABLE dimensions ADD COLUMN rotation_deg REAL NOT NULL DEFAULT 0.0")
            con.commit()
            print(f"{db}: added rotation_deg")
        else:
            print(f"{db}: already has rotation_deg")
        con.close()
    except sqlite3.OperationalError as e:
        print(f"{db}: skipped ({e})", file=sys.stderr)
```

Run: `python scripts/migrations/2026-05-02_add_rotation_deg.py`
Expected: 两个 db 各打印 added 或 already has。

**Step 5: 写库处填值**

`app/services/analyzer.py` 内把 ExtractedDimension 转 Dimension 的位置（找 `Dimension(`），把 `rotation_deg=ed.rotation_deg` 加进 kwargs。

**Step 6: 接口序列化**

确认 `app/routers/review.py` / `app/routers/parts.py` 里发给前端的 dim 字典/Pydantic schema 包含 `rotation_deg`（grep `bbox_x0` 找模型，加 `rotation_deg`）。

**Step 7: 跑一次 tile 抽取并抽查**

Run: `python run_tile_extraction.py <一份测试 part 的 drawing id>`（或用 web UI 重新触发）
然后：
```bash
sqlite3 dev.db "SELECT id, value, rotation_deg FROM dimensions WHERE drawing_id=<X> AND rotation_deg!=0 LIMIT 10;"
```
Expected: 至少能看到一些斜置/竖直尺寸的 rotation_deg 非零（例如 ±90 或 ~30°）。

**Step 8: Commit**

```bash
git add app/models.py app/services/extractor.py app/services/analyzer.py scripts/migrations/2026-05-02_add_rotation_deg.py app/routers
git commit -m "feat(model): persist per-dimension rotation_deg from token theta"
```

---

## Task 4: 前端 — MarkerBox 跟随旋转 + badge 置于前端

**Files:**
- Modify: `app/templates/review_workbench.html:28-75`

**Step 1: 在 MarkerBox 里读取 rotation_deg**

```js
const rot = Number(dim.rotation_deg) || 0;     // 度数，CCW 正
```

**Step 2: 用 transform-origin = 中心 让矩形旋转**

外层 box（line 39-54）改为：

```js
const cx = x + Math.max(w, 4) / 2;
const cy = y + Math.max(h, 4) / 2;
// ... style:
transform: `rotate(${-rot}deg)`,           // 屏幕 y 轴向下，需要取反让视觉与文本一致
transformOrigin: `${Math.max(w, 4)/2 + 2}px ${Math.max(h, 4)/2 + 2}px`,
```

> 注：`dim.bbox_x0..y1` 是轴对齐外接框，对斜置 token 会偏大；这一版先复用它做近似的"以中心旋转"。后续若发现明显偏差，再把 oriented bbox（中心+宽高+角度）传到前端。

**Step 3: badge 置于矩形"前端"（文本起点侧）**

把 badge（line 55-72）从"框上方左对齐"改成"框在旋转后文本起点的左外侧"：

```js
// 在未旋转坐标系里，badge 放矩形左外侧、垂直居中
const badgeW = String(dim.sequence).length * (labelFont * 0.6) + 6;
// outer wrapper 套住 box+badge 一起旋转：
<div style={{
  position:"absolute",
  left: x - 2 - badgeW - 2,
  top: y - 2,
  width: Math.max(w + 4, 8) + badgeW + 2,
  height: Math.max(h + 4, 8),
  transform: `rotate(${-rot}deg)`,
  transformOrigin: `${badgeW + 2 + Math.max(w,4)/2 + 2}px ${Math.max(h,4)/2 + 2}px`,
  pointerEvents: "none",   // 让内部各自负责点击
}}>
  {/* badge — 左侧 */}
  <div style={{ position:"absolute", left:0, top:"50%", transform:"translateY(-50%)",
                height:labelH, padding:"0 3px", backgroundColor: color, color:"#fff",
                fontFamily:"var(--font-mono)", fontSize:labelFont, fontWeight:700,
                lineHeight:`${labelH}px`, borderRadius:2, pointerEvents:"auto",
                cursor:"pointer", whiteSpace:"nowrap" }}
       onClick={...} onContextMenu={...}>
    {dim.sequence}
  </div>
  {/* rectangle */}
  <div style={{ position:"absolute", left: badgeW + 2, top:0,
                width: Math.max(w + 4, 8), height: Math.max(h + 4, 8),
                border: `${isSelected ? 2.5 : 1.5}px solid ${color}`,
                borderRadius: 2, backgroundColor: ..., pointerEvents:"auto",
                cursor:"pointer", boxSizing:"border-box" }}
       onClick={...} onContextMenu={...} />
</div>
```

> 关键：把 box+badge 装进同一个 wrapper 一起旋转，badge 自然跟到文本起点那一侧；transformOrigin 设为旋转中心 = 矩形中心。

**Step 4: 人工验证（核心场景）**

Run: `uvicorn app.main:app --reload`
找截图里的 #3 / #54 / #62 / #66 这种斜置/竖直尺寸：
- 矩形与文字方向平行（不再斜穿文字）
- 序号在尺寸文本起点的那一头（不是末尾）
- 字号比图纸尺寸文字小一号

**Step 5: 边界用例**

- rotation_deg ≈ 0 的水平尺寸：行为应与改动前几乎一致（badge 在左侧而不是上方——这是新设计，确认接受）。
- rotation_deg = 180（反向）：badge 别跑到尺寸末尾。如果出错，按 `((rot % 360) + 360) % 360 > 90 && < 270` 时把 badge 改放右侧并 `rotate(180deg)`。
- 选中态：旋转 wrapper 不能截断 boxShadow 高亮——把 `boxShadow` 留在内层 rectangle div 上即可（已是）。

**Step 6: Commit**

```bash
git add app/templates/review_workbench.html
git commit -m "feat(workbench): rotate marker box with dim text and place badge at start"
```

---

## Task 5: 回归 + PR 准备

**Step 1: 跑现有测试**

Run: `pytest -q`
Expected: 全绿（仅前端改动 + 一个新列默认 0，不应破坏后端测试）。

**Step 2: 浏览器人工最后扫一遍**

打开 ≥2 个 part 的 review workbench：
- pending 浅蓝、状态切换后正常变绿/黄/红
- 旋转尺寸框平行、序号在前端
- 缩放/平移、右键菜单、点击切换状态、选中态高亮均正常

**Step 3: Commit 任何回归修复后**

```bash
git status
# 若有清理性修改：
git commit -m "fix(workbench): <具体>"
```

---

## 备注 / 风险

- **轴对齐 bbox + 整体旋转** 是近似方案。对长尺寸文本+大角度，旋转后矩形可能略大于真实文字外框。如果用户验收觉得偏差大，下一版再让 extractor 输出 oriented bbox（中心 cx,cy + 宽 w + 高 h + 角度 θ），改动局限在 extractor 聚合段和前端尺寸计算。
- **历史 dimensions** rotation_deg 默认 0；想让旧数据也旋转，需重新跑 tile 抽取。可在 PR 描述里写一句迁移说明。
- **颜色可访问性**：sky-400 (#38bdf8) 在白底对比度 ~2.4:1，作为描边可读但作为文字不够。badge 文字用白色 on highlight，OK。
