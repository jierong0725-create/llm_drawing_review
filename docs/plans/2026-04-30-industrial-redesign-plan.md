# 工业精密风重设计 · 实施计划

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 将工程图纸审核系统前端从 Jinja2+Tailwind 重写为 React SPA（工业精密风），信息架构从三级精简为两极（Dashboard → 审核工作台）。

**Architecture:** FastAPI 后端不变，路由改为返回 SPA 壳 + JSON API。前端用 React 18.3 + Babel standalone（CDN pinned），每个页面一个自包含 HTML，共享组件抽到 `static/jsx/`。Jinja2 退化只为最简 HTML 容器。

**Tech Stack:** FastAPI, SQLAlchemy, React 18.3, Babel standalone 7.24, SF Mono / DIN Alternate 字体

---

### Task 1: 设计令牌与 SPA 壳

**Files:**
- Create: `app/static/jsx/design_tokens.jsx`
- Create: `app/templates/spa.html`
- Modify: `app/static/drawings/.gitkeep` (ensure dir tracked)

**Step 1: 创建设计令牌文件**

`app/static/jsx/design_tokens.jsx` 注入全局 CSS 变量和基础重置样式：

```jsx
// 设计令牌 — 工业精密风
const designTokens = `
  :root {
    /* 底盘 */
    --bg-canvas: #1e2127;
    --bg-surface: #282c34;
    --bg-elevated: #323741;

    /* 信号色 */
    --signal-green: #2ecc71;
    --signal-red: #e74c3c;
    --signal-amber: #f39c12;
    --signal-gray: #6b7280;

    /* Accent */
    --accent-primary: #f0a500;
    --accent-hover: #f5c842;

    /* 文字 */
    --ink: #e8e8e8;
    --ink-secondary: #9ca3af;
    --ink-disabled: #555b66;

    /* 边框 */
    --border-color: #3a3f4a;

    /* 间距 */
    --space-4: 4px;
    --space-8: 8px;
    --space-12: 12px;
    --space-16: 16px;
    --space-24: 24px;
    --space-32: 32px;

    /* 字体 */
    --font-display: "DIN Alternate", "Helvetica Neue", sans-serif;
    --font-mono: "SF Mono", "JetBrains Mono", "Fira Code", monospace;
    --font-ui: -apple-system, system-ui, sans-serif;

    /* 形状 */
    --radius: 2px;
  }

  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  html, body { height: 100%; }
  body {
    font-family: var(--font-ui);
    font-size: 13px;
    color: var(--ink);
    background: var(--bg-canvas);
    -webkit-font-smoothing: antialiased;
    font-feature-settings: "tnum";
  }
  input, button, textarea, select {
    font-family: inherit; font-size: inherit; color: inherit;
  }

  /* 表格全局样式 */
  table.industrial {
    width: 100%; border-collapse: collapse;
    font-family: var(--font-mono); font-size: 13px;
  }
  table.industrial th {
    text-align: left; padding: 8px 12px;
    font-family: var(--font-ui); font-size: 11px;
    font-weight: 600; color: var(--ink-secondary);
    text-transform: uppercase; letter-spacing: 0.05em;
    border-bottom: 1px solid var(--border-color);
  }
  table.industrial td {
    padding: 8px 12px; border-bottom: 1px solid var(--border-color);
    font-variant-numeric: tabular-nums;
  }
  table.industrial tbody tr:hover { background: rgba(255,255,255,0.03); }
`;

// Inject into document head
const styleTag = document.createElement('style');
styleTag.textContent = designTokens;
document.head.appendChild(styleTag);

// Export
Object.assign(window, { designTokens });
```

**Step 2: 创建 SPA 壳模板**

`app/templates/spa.html` — 最简 HTML 容器，所有页面共用：

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{{ title }} — 工程图纸审核</title>
  <script src="https://unpkg.com/react@18.3.1/umd/react.production.min.js" crossorigin></script>
  <script src="https://unpkg.com/react-dom@18.3.1/umd/react-dom.production.min.js" crossorigin></script>
  <script src="https://unpkg.com/@babel/standalone@7.24.5/babel.min.js" crossorigin></script>
</head>
<body>
  <div id="root"></div>
  <script type="text/babel" src="/static/jsx/design_tokens.jsx"></script>
  {% block scripts %}{% endblock %}
</body>
</html>
```

**Step 3: 确保静态目录存在**

```bash
mkdir -p app/static/jsx app/static/drawings app/static/uploads
touch app/static/uploads/.gitkeep
```

**Step 4: Commit**

```bash
git add app/static/jsx/design_tokens.jsx app/templates/spa.html app/static/uploads/.gitkeep
git commit -m "feat: add design tokens and SPA shell template"
```

---

### Task 2: 后端路由改造 — 零件列表页

**Files:**
- Modify: `app/routers/parts.py`
- Create: `app/static/parts_list.html`

**Step 1: 改造 list_parts 路由**

修改 `app/routers/parts.py` 的 `list_parts` 函数，返回 SPA 壳：

```python
# 将原来的
return templates.TemplateResponse(request, "parts/list.html", {"parts": parts})
# 改为
return templates.TemplateResponse(request, "spa.html", {"title": "零件列表"})
```

同时新增 JSON API：

```python
@router.get("/api/list")
def list_parts_json(db: Session = Depends(get_db)):
    parts = db.query(Part).order_by(Part.created_at.desc()).all()
    return [{
        "id": p.id, "name": p.name, "drawing_number": p.drawing_number,
        "current_version": _get_current_version_info(p),
        "pending_count": _get_pending_count(p),
        "total_count": _get_total_dimension_count(p),
    } for p in parts]
```

**Step 2: 创建零件列表页 SPA**

`app/static/parts_list.html` — 自包含 React SPA：

- `App` 组件从 `/parts/api/list` 获取数据
- 渲染 DataTable（先用内联渲染，后续 Task 4 抽出共用组件）
- 搜索框 + 新增零件弹窗
- 点击行跳转到 `/parts/{id}/review`

```jsx
function App() {
  const [parts, setParts] = React.useState([]);
  const [search, setSearch] = React.useState("");
  const [statusFilter, setStatusFilter] = React.useState("all");

  React.useEffect(() => {
    fetch("/parts/api/list").then(r => r.json()).then(setParts);
  }, []);

  // render table, search, modal...
}

const root = ReactDOM.createRoot(document.getElementById("root"));
root.render(<App />);
```

**Step 3: 更新 main.py 路由**

在 `app/main.py` 中确保 `/parts/` 重定向到正确页面，SPA HTML 由 StaticFiles 或路由提供。

**Step 4: 新增零件 API 改为返回 JSON**

`create_part` 函数改为返回 JSON（不再返回完整 HTML）：

```python
@router.post("/api/create")
def create_part_json(name: str = Form(...), drawing_number: str = Form(...), ...):
    # ... same logic ...
    return {"id": part.id, "name": part.name, "drawing_number": part.drawing_number}
```

**Step 5: Commit**

```bash
git add app/routers/parts.py app/static/parts_list.html app/main.py
git commit -m "feat: rewrite part list as React SPA with JSON API"
```

---

### Task 3: 共享组件 — AppShell, StatusDot, Stamp

**Files:**
- Create: `app/static/jsx/app_shell.jsx`
- Create: `app/static/jsx/status_dot.jsx`
- Create: `app/static/jsx/stamp.jsx`

**Step 1: AppShell 组件**

```jsx
// app/static/jsx/app_shell.jsx
function AppShell({ breadcrumbs, children }) {
  return React.createElement("div", null,
    React.createElement("nav", { style: appShellStyles.nav },
      React.createElement("a", { href: "/parts/", style: appShellStyles.brand }, "⚙ 工程图纸审核"),
      breadcrumbs && breadcrumbs.map((crumb, i) =>
        React.createElement("span", { key: i },
          React.createElement("span", { style: appShellStyles.separator }, " / "),
          crumb.href
            ? React.createElement("a", { href: crumb.href, style: appShellStyles.link }, crumb.label)
            : React.createElement("span", { style: appShellStyles.current }, crumb.label)
        )
      )
    ),
    React.createElement("main", { style: appShellStyles.main }, children)
  );
}

const appShellStyles = {
  nav: { display: "flex", alignItems: "center", gap: "var(--space-8)",
         height: 32, padding: "0 var(--space-16)", background: "var(--bg-surface)",
         borderBottom: "1px solid var(--border-color)", fontSize: 13 },
  brand: { color: "var(--accent-primary)", textDecoration: "none", fontWeight: 600,
           fontFamily: "var(--font-display)", letterSpacing: "0.04em" },
  link: { color: "var(--ink-secondary)", textDecoration: "none" },
  current: { color: "var(--ink)" },
  separator: { color: "var(--ink-disabled)" },
  main: { height: "calc(100vh - 32px)", display: "flex", flexDirection: "column" },
};

Object.assign(window, { AppShell, appShellStyles });
```

**Step 2: StatusDot 组件**

```jsx
// app/static/jsx/status_dot.jsx
// status: "approved" | "rejected" | "pending" | "questionable" | "processing"
function StatusDot({ status, label, pulse = false }) {
  const colorMap = {
    approved: "var(--signal-green)",
    rejected: "var(--signal-red)",
    pending: "var(--signal-gray)",
    questionable: "var(--signal-amber)",
    processing: "var(--accent-primary)",
  };
  return React.createElement("span", { style: statusDotStyles.wrapper },
    React.createElement("span", {
      style: {
        ...statusDotStyles.dot,
        backgroundColor: colorMap[status] || colorMap.pending,
        animation: pulse && status === "processing" ? "pulse 1.5s ease-in-out infinite" : "none",
      }
    }),
    label && React.createElement("span", { style: statusDotStyles.label }, label)
  );
}

const statusDotStyles = {
  wrapper: { display: "inline-flex", alignItems: "center", gap: 6 },
  dot: { width: 8, height: 8, borderRadius: "var(--radius)" },
  label: { fontSize: 12, color: "var(--ink-secondary)" },
};

Object.assign(window, { StatusDot, statusDotStyles });
```

**Step 3: Stamp 组件**

```jsx
// app/static/jsx/stamp.jsx
function Stamp({ type, date }) {
  // type: "approved" | "rejected"
  const isApproved = type === "approved";
  return React.createElement("div", {
    style: {
      ...stampStyles.base, transform: `rotate(${isApproved ? -12 : 12}deg)`,
      color: isApproved ? "var(--signal-green)" : "var(--signal-red)",
      borderColor: isApproved ? "var(--signal-green)" : "var(--signal-red)",
    }
  },
    React.createElement("div", { style: stampStyles.icon }, isApproved ? "✓" : "✕"),
    React.createElement("div", { style: stampStyles.label }, isApproved ? "APPROVED" : "REJECTED"),
    React.createElement("div", { style: stampStyles.date }, date)
  );
}

const stampStyles = {
  base: {
    display: "inline-flex", flexDirection: "column", alignItems: "center", gap: 2,
    border: "2px solid", borderRadius: 4, padding: "8px 20px",
    fontFamily: "var(--font-display)", letterSpacing: "0.1em",
    opacity: 0.85, userSelect: "none", pointerEvents: "none",
  },
  icon: { fontSize: 24, fontWeight: 700 },
  label: { fontSize: 10, fontWeight: 700 },
  date: { fontSize: 9, color: "var(--ink-secondary)", letterSpacing: "0.05em" },
};

Object.assign(window, { Stamp, stampStyles });
```

**Step 4: 更新 spa.html 加载共享组件**

在 `spa.html` 的 `{% block scripts %}` 前加默认加载：

```html
<script type="text/babel" src="/static/jsx/app_shell.jsx"></script>
<script type="text/babel" src="/static/jsx/status_dot.jsx"></script>
<script type="text/babel" src="/static/jsx/stamp.jsx"></script>
```

**Step 5: Commit**

```bash
git add app/static/jsx/app_shell.jsx app/static/jsx/status_dot.jsx app/static/jsx/stamp.jsx app/templates/spa.html
git commit -m "feat: add shared React components (AppShell, StatusDot, Stamp)"
```

---

### Task 4: 零件列表页收尾 + 通用 DataTable

**Files:**
- Create: `app/static/jsx/data_table.jsx`
- Modify: `app/static/parts_list.html`
- Modify: `app/routers/parts.py`

**Step 1: DataTable 通用组件**

```jsx
// app/static/jsx/data_table.jsx
// columns: [{ key, label, render? }]
// data: array of objects
// onRowClick: (row) => void
function DataTable({ columns, data, onRowClick, emptyText = "暂无数据" }) {
  return React.createElement("table", { className: "industrial" },
    React.createElement("thead", null,
      React.createElement("tr", null,
        columns.map(col => React.createElement("th", { key: col.key }, col.label))
      )
    ),
    React.createElement("tbody", null,
      data.length === 0
        ? React.createElement("tr", null,
            React.createElement("td", { colSpan: columns.length, style: { textAlign: "center", color: "var(--ink-disabled)", padding: 40 } }, emptyText))
        : data.map((row, i) =>
            React.createElement("tr", {
              key: row.id || i,
              onClick: () => onRowClick && onRowClick(row),
              style: onRowClick ? { cursor: "pointer" } : {},
            },
              columns.map(col =>
                React.createElement("td", { key: col.key },
                  col.render ? col.render(row[col.key], row) : row[col.key]
                )
              )
            )
          )
    )
  );
}

Object.assign(window, { DataTable });
```

**Step 2: 完善零件列表页**

引用 DataTable 组件，替换内联表格为 DataTable。添加 SearchFilter 和 NewPartModal 组件：

- `SearchFilter`：输入框 + 状态下拉（全部 / ready / 处理中 / 已确认）
- `NewPartModal`：零件名称 + 图号输入，提交到 `/parts/api/create`

**Step 3: 提交零件创建改用 JSON + 前端刷新**

提交成功后关闭弹窗，刷新列表数据，不刷新整页。

**Step 4: 更新 create_part API 路径**

`parts.py` 原 `@router.post("/")` 改为 `@router.post("/api/create")`，返回 JSON。

**Step 5: Commit**

```bash
git add app/static/jsx/data_table.jsx app/static/parts_list.html app/routers/parts.py
git commit -m "feat: add DataTable component and finalize part list page"
```

---

### Task 5: 审核工作台 — 后端路由改造

**Files:**
- Modify: `app/routers/review.py`
- Modify: `app/routers/parts.py` (detail page redirect)

**Step 1: 审核工作台页面路由**

修改 `review.py` 的 `review_page` 函数，返回 SPA 壳：

```python
@router.get("/{part_id}/versions/{version_id}/review", response_class=HTMLResponse)
def review_page(request: Request, part_id: int, version_id: int, db: Session = Depends(get_db)):
    # validation ...
    return templates.TemplateResponse(request, "spa.html", {
        "title": f"{part.name} — 图纸审核",
    })
```

**Step 2: 新增版本列表 API**

```python
@api.get("/parts/{part_id}/versions")
def list_versions(part_id: int, db: Session = Depends(get_db)):
    versions = db.query(Version).filter(Version.part_id == part_id).order_by(Version.created_at.desc()).all()
    return [{"id": v.id, "version_code": v.version_code, "is_current": v.is_current,
             "status": v.status.value, "confirm_result": v.confirm_result.value if v.confirm_result else None}
            for v in versions]
```

**Step 3: 零件详情页重定向**

`app/routers/parts.py` 里的 `part_detail` 路由重定向到审核工作台（默认打开当前版本的 review）：

```python
@router.get("/{part_id}", response_class=HTMLResponse)
def part_detail(request: Request, part_id: int, db: Session = Depends(get_db)):
    part = db.query(Part).filter(Part.id == part_id).first()
    if not part:
        raise HTTPException(status_code=404)
    # Redirect to latest version review (or first version)
    current = next((v for v in part.versions if v.is_current), None)
    if current:
        return RedirectResponse(url=f"/parts/{part_id}/versions/{current.id}/review")
    return RedirectResponse(url="/parts/")
```

**Step 4: Commit**

```bash
git add app/routers/review.py app/routers/parts.py
git commit -m "feat: redirect part detail to review workbench, add version list API"
```

---

### Task 6: 审核工作台 — 图纸画布（Canvas + Markers）

**Files:**
- Create: `app/static/review_workbench.html`
- Create: `app/static/jsx/marker_label.jsx`

**Step 1: 创建审核工作台 SPA**

`app/static/review_workbench.html` — 主页面，从 URL path 解析 `partId` 和 `versionId`：

```jsx
const pathParts = window.location.pathname.split("/");
const partId = Number(pathParts[2]);
const versionId = Number(pathParts[4]);
```

**Step 2: DrawingCanvas 组件**

提取现有审核页面的 pan/zoom 逻辑到 React：

- `usePanZoom` hook：管理 `zoom`, `offsetX`, `offsetY` 状态
- 滚轮缩放、拖拽平移、双击适应窗口
- 适应窗口按钮

```jsx
function usePanZoom(containerRef) {
  const [zoom, setZoom] = React.useState(1);
  const [offsetX, setOffsetX] = React.useState(0);
  const [offsetY, setOffsetY] = React.useState(0);
  // ... pan/zoom event handlers
  return { zoom, offsetX, offsetY, fitScreen, applyTransform };
}
```

**Step 3: MarkerLabel 组件（工业铭牌标签）**

`app/static/jsx/marker_label.jsx` — 替代现有圆形标注：

```jsx
function MarkerLabel({ dim, zoom, offsetX, offsetY, isSelected, onClick }) {
  const colorMap = {
    pending: "var(--signal-gray)",
    confirmed: "var(--signal-green)",
    questionable: "var(--signal-amber)",
  };
  const x = dim.anchor_x * zoom + offsetX;
  const y = dim.anchor_y * zoom + offsetY;
  const size = Math.max(22, 26 / Math.sqrt(zoom));

  return React.createElement("div", {
    style: {
      position: "absolute", left: x, top: y,
      width: size, height: size,
      transform: "translate(-50%, -50%)",
      backgroundColor: colorMap[dim.review_status] || colorMap.pending,
      color: "#fff", display: "flex", alignItems: "center", justifyContent: "center",
      fontFamily: "var(--font-mono)", fontSize: Math.max(11, 11 / Math.sqrt(zoom)),
      fontWeight: 700, borderRadius: "var(--radius)",
      border: isSelected ? "2px solid var(--accent-primary)" : "1px solid transparent",
      cursor: "pointer", zIndex: isSelected ? 20 : 10,
      boxShadow: isSelected ? "0 0 0 3px rgba(240,165,0,0.3)" : "none",
    },
    onClick: (e) => { e.stopPropagation(); onClick(dim.id); },
    title: dim.value,
  }, dim.sequence);
}

Object.assign(window, { MarkerLabel });
```

**Step 4: SVG overlay 引导线 & 排斥算法**

- 当 zoom < 0.5 时触发表注排斥算法
- 对位移的标注画 SVG 引导线（`pointer-events: none`）
- 排斥算法逻辑来自已有设计文档

**Step 5: 图片加载失败兜底**

`<img onError>` → 隐藏图片，显示占位卡片：「图纸图片未生成，请重新上传版本」

**Step 6: Commit**

```bash
git add app/static/review_workbench.html app/static/jsx/marker_label.jsx
git commit -m "feat: add review workbench with industrial marker labels and canvas"
```

---

### Task 7: 审核工作台 — 右侧面板（标注列表 + 讨论 + 结论）

**Files:**
- Modify: `app/static/review_workbench.html`

**Step 1: DimensionList 组件**

- 筛选栏：全部 / 待审 / 存疑 / 确认
- 虚拟滚动（超过 50 项时，固定行高 36px）
- 每行：方型序号 + 尺寸值 + 状态点
- 点击选中

**Step 2: DimensionDetail 组件**

- 显示选中标注：序号、尺寸值、类型、来源、坐标
- 状态切换按钮组（待审 / 确认 / 存疑）
- 调用 `PATCH /api/dimensions/{id}` 更新状态

**Step 3: DiscussionThread + MessageInput**

- 加载 `/api/dimensions/{id}/messages`
- 消息气泡列表（深底风格）
- 输入框 + 发送按钮，支持 Enter 快捷发送

**Step 4: ConclusionStamp 区域**

- 底栏显示统计数据（共 N 条 · 待审 X · 确认 Y · 存疑 Z）
- 备注 textarea
- 通过/驳回按钮 → 点击弹出确认对话框 → 提交后显示 Stamp 盖章动画 → 页面只读

**Step 5: 版本切换逻辑**

- 顶部下拉切换版本
- 当前版本（`is_current`）：读写模式
- 历史版本：只读模式（隐藏状态按钮、讨论框、结论按钮，已有结论显示 Stamp）

**Step 6: Commit**

```bash
git add app/static/review_workbench.html
git commit -m "feat: add review panel (dimension list, detail, discussion, conclusion stamp)"
```

---

### Task 8: PDF 持久化 & 服务端重新渲染

**Files:**
- Modify: `app/routers/parts.py`
- Modify: `app/services/image_gen.py`

**Step 1: 保留上传的 PDF**

修改 `app/routers/parts.py` 的 `create_version`：将 PDF 复制到 `app/static/uploads/{version_id}/` 而非仅存临时目录：

```python
upload_dir = os.path.join(STATIC_DIR, "..", "uploads", str(version.id))
os.makedirs(upload_dir, exist_ok=True)
# ... save PDF to upload_dir ...
```

**Step 2: 新增重新渲染 API**

```python
@router.post("/{part_id}/versions/{version_id}/reprocess")
def reprocess_images(version_id: int):
    # For each drawing, regenerate JPG from saved PDF
    version = db.query(Version).filter(Version.id == version_id).first()
    for drawing in version.drawings:
        pdf_path = os.path.join(UPLOAD_DIR, str(version_id), f"{drawing.id}_{drawing.filename}")
        output_dir = os.path.join(STATIC_DIR, str(drawing.id))
        generate_drawing_images(drawing.id, pdf_path, output_dir)
    return {"ok": True}
```

**Step 3: 前端重新渲染按钮**

在图片加载失败的占位卡片上加一个「重新生成」按钮，调用上述 API 后刷新。

**Step 4: 修改 _process_version 错误处理**

将 `except Exception: pass` 改为记录错误到 `version.notes`：

```python
try:
    generate_drawing_images(drawing_id, pdf_path, output_dir)
except Exception as e:
    version = db.query(Version).filter(Version.id == version_id).first()
    if version:
        version.notes = (version.notes or "") + f"\n[图片生成失败] drawing {drawing_id}: {e}"
        db.commit()
```

**Step 5: Commit**

```bash
git add app/routers/parts.py app/services/image_gen.py
git commit -m "feat: perserve uploaded PDF and add reprocess API"
```

---

### Task 9: 收尾 — 清理旧模板 & 全流程验证

**Files:**
- Remove: `app/templates/parts/detail.html` (功能已合并到审核工作台)
- Modify: `app/templates/base.html` (保留但标记 deprecated)
- Modify: `app/main.py` (确认路由)

**Step 1: 清理旧模板**

- `parts/detail.html` 不再需要（零件详情已重定向到审核工作台）
- `base.html` 保留但不再作为 extends 父模板（spa.html 是新的壳）

**Step 2: 验证完整流程**

在浏览器中手动走通全流程：
1. 打开 `/parts/` → 显示零件列表（React 表格）
2. 新增零件 → 弹窗填写 → 列表刷新
3. 点击零件 → 重定向到审核工作台
4. 上传版本 PDF → 等待处理 → 刷新出现 ready 状态
5. 进入审核 → 图纸加载、标注渲染、pan/zoom
6. 标注重叠排斥 → SVG 引导线可见
7. 点击标注 → 右侧面板显示详情
8. 切换标注状态 → marker 颜色实时更新
9. 发送讨论消息
10. 审核结论 → 盖章动画 → 只读态
11. 切换历史版本 → 只读模式
12. 图片加载失败 → 占位卡片 + 重新生成按钮

**Step 3: 修复发现的问题**

在验证过程中发现的所有 UI bug 当场修复。

**Step 4: Commit**

```bash
git add -A app/
git commit -m "feat: cleanup old templates, finalize industrial redesign"
```

---

### 任务依赖图

```
Task 1 (tokens + shell) ──┬── Task 2 (parts list backend)
                          │       │
                          │       └── Task 4 (DataTable + parts page)
                          │
                          ├── Task 3 (shared components)
                          │       │
                          │       └── Task 4, Task 6, Task 7 共用
                          │
                          ├── Task 5 (review backend)
                          │       │
                          │       ├── Task 6 (canvas + markers)
                          │       └── Task 7 (right panel)
                          │
                          └── Task 8 (PDF persistence)

Task 6 + Task 7 → Task 9 (cleanup + validation)
Task 8 → Task 9
```

Task 1 必须最先执行，Task 9 最后。Task 2-5 可部分并行，Task 6-7 依赖 Task 5。
