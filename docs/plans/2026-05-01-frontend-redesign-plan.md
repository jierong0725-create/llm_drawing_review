# 前端页面优化重设计 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 将工程图纸审核系统前端全面升级为浅色主题、JSX 语法，新增汇总统计条、分段筛选、进度条、右键上下文菜单、驳回状态，移除版本结论功能，同步清理旧 JSX 文件。

**Architecture:** 采用方案 B——保留 `marker_label.jsx` 和新建 `shared.jsx`（AppShell + StatusDot），其余逻辑内联各页面模板。浅色主题 CSS 变量直接挂 `:root`，页面加载链：spa.html → shared.jsx → marker_label.jsx（仅工作台）→ 各页面内联脚本。

**Tech Stack:** React 18 (UMD), Babel Standalone (JSX), FastAPI + Jinja2 模板, SQLAlchemy + SQLite

---

### Task 1：后端 — ReviewStatus 枚举增加 `rejected`

**Files:**
- Modify: `app/models.py:36-40`

**背景：** `PATCH /api/dimensions/{id}` 的处理代码调用 `ReviewStatus(data["review_status"])`，若传入 `"rejected"` 但枚举中不存在该值会抛 ValueError。SQLite 不强制 Enum 约束，只需更新 Python 枚举，无需 DB migration。

**Step 1: 更新 ReviewStatus 枚举**

在 `app/models.py` 中将：
```python
class ReviewStatus(str, enum.Enum):
    pending = "pending"
    confirmed = "confirmed"
    questionable = "questionable"
```
改为：
```python
class ReviewStatus(str, enum.Enum):
    pending = "pending"
    confirmed = "confirmed"
    questionable = "questionable"
    rejected = "rejected"
```

**Step 2: 验证服务器启动无报错**

```bash
cd /Users/rongjie/llm_projects/llm_drawing_review
uvicorn app.main:app --reload --port 8000
```
预期：无 import 错误，正常启动。

**Step 3: Commit**

```bash
git add app/models.py
git commit -m "feat: add rejected to ReviewStatus enum"
```

---

### Task 2：更新 spa.html — 浅色主题 + 加载 shared.jsx

**Files:**
- Modify: `app/templates/spa.html`

**背景：** spa.html 是所有页面的基础模板，当前只加载 design_tokens.jsx 注入 CSS 变量。改造后 CSS 变量内联在 `<style>` 中（浅色主题），并引入新的 shared.jsx。

**Step 1: 重写 spa.html**

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
  <style>
    /* ── 浅色主题 ── */
    :root {
      --bg-canvas: #f1f3f7;
      --bg-surface: #ffffff;
      --bg-elevated: #f8f9fc;
      --bg-hover: rgba(0,0,0,0.03);
      --bg-selected: rgba(220,130,0,0.07);
      --signal-green: #16a34a;
      --signal-red: #dc2626;
      --signal-amber: #d97706;
      --signal-gray: #6b7280;
      --signal-blue: #2563eb;
      --accent-primary: #c97f00;
      --accent-hover: #a66800;
      --accent-dim: rgba(201,127,0,0.12);
      --ink: #1e2635;
      --ink-secondary: #4b5668;
      --ink-disabled: #9ca3af;
      --border-color: #e2e6ed;
      --border-strong: #cbd2dc;
      --shadow-card: 0 2px 12px rgba(0,0,0,0.10);
      --space-4: 4px; --space-8: 8px; --space-12: 12px;
      --space-16: 16px; --space-24: 24px; --space-32: 32px;
      --font-display: "DIN Alternate", "Helvetica Neue", sans-serif;
      --font-mono: "SF Mono", "JetBrains Mono", "Fira Code", monospace;
      --font-ui: -apple-system, system-ui, sans-serif;
      --radius: 2px;
    }

    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    html, body, #root { height: 100%; overflow: hidden; }
    body {
      font-family: var(--font-ui);
      font-size: 13px;
      color: var(--ink);
      background: var(--bg-canvas);
      -webkit-font-smoothing: antialiased;
      font-feature-settings: "tnum";
    }

    ::-webkit-scrollbar { width: 5px; height: 5px; }
    ::-webkit-scrollbar-track { background: transparent; }
    ::-webkit-scrollbar-thumb { background: var(--border-strong); border-radius: 3px; }

    @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.35} }
    @keyframes fadeIn { from{opacity:0;transform:translateY(4px)} to{opacity:1;transform:translateY(0)} }
    @keyframes stampIn { 0%{opacity:0;transform:rotate(-14deg) scale(0.7)} 60%{transform:rotate(-12deg) scale(1.08)} 100%{opacity:1;transform:rotate(-12deg) scale(1)} }
    @keyframes contextMenuIn { from{opacity:0;transform:scale(0.92)} to{opacity:1;transform:scale(1)} }

    .fade-in { animation: fadeIn 0.18s ease; }

    table.industrial { width: 100%; border-collapse: collapse; }
    table.industrial th {
      text-align: left; padding: 8px 14px;
      font-size: 10px; font-weight: 600;
      color: var(--ink-secondary); text-transform: uppercase; letter-spacing: 0.07em;
      border-bottom: 1px solid var(--border-color);
      background: var(--bg-elevated);
    }
    table.industrial td {
      padding: 10px 14px; border-bottom: 1px solid var(--border-color);
      font-variant-numeric: tabular-nums; color: var(--ink);
    }
    table.industrial tbody tr { cursor: pointer; transition: background 0.1s; }
    table.industrial tbody tr:hover { background: var(--bg-hover); }
    table.industrial tbody tr.selected { background: var(--bg-selected); }

    .ctx-menu {
      position: fixed; z-index: 9999;
      background: var(--bg-surface); border: 1px solid var(--border-strong);
      border-radius: 6px; padding: 4px; min-width: 160px;
      box-shadow: var(--shadow-card);
      animation: contextMenuIn 0.12s ease;
    }
    .ctx-item {
      display: flex; align-items: center; gap: 8px;
      padding: 7px 10px; border-radius: 4px; cursor: pointer;
      font-size: 12px; color: var(--ink); transition: background 0.1s;
    }
    .ctx-item:hover { background: var(--bg-hover); }
    .ctx-dot { width: 8px; height: 8px; border-radius: 2px; flex-shrink: 0; }
    .ctx-divider { height: 1px; background: var(--border-color); margin: 3px 0; }

    .progress-track { background: var(--border-color); border-radius: 2px; overflow: hidden; }
    .progress-fill { height: 100%; border-radius: 2px; transition: width 0.4s ease; }
  </style>
</head>
<body>
  <div id="root"></div>
  <script type="text/babel" src="/static/jsx/shared.jsx"></script>
  {% block scripts %}{% endblock %}
</body>
</html>
```

**Step 2: 启动服务器，访问任意页面确认无 CSS 报错**

```bash
uvicorn app.main:app --reload --port 8000
```
访问 `http://localhost:8000/parts/` — 预期：页面加载，无 console 错误（即使样式还不对，因为旧 JSX 文件还在）。

**Step 3: Commit**

```bash
git add app/templates/spa.html
git commit -m "feat: replace design_tokens with inline light theme CSS in spa.html"
```

---

### Task 3：新建 shared.jsx — AppShell + StatusDot

**Files:**
- Create: `app/static/jsx/shared.jsx`

**背景：** 替代旧的 app_shell.jsx 和 status_dot.jsx，使用 JSX 语法，加入 DRAWREV SVG 图标，支持 `actions` 插槽。

**Step 1: 创建 shared.jsx**

```jsx
// shared.jsx — AppShell + StatusDot

function AppShell({ breadcrumbs, actions, children }) {
  return (
    <div style={{ height: "100%", display: "flex", flexDirection: "column" }}>
      <nav style={{
        display: "flex", alignItems: "center", gap: 8, height: 36,
        padding: "0 16px", background: "var(--bg-surface)",
        borderBottom: "1px solid var(--border-color)", flexShrink: 0,
      }}>
        <a href="/parts/" style={{
          color: "var(--accent-primary)", fontWeight: 700, fontSize: 13,
          fontFamily: "var(--font-display)", letterSpacing: "0.06em",
          textDecoration: "none",
          display: "flex", alignItems: "center", gap: 6,
        }}>
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
            <rect x="1" y="1" width="14" height="14" rx="2" stroke="currentColor" strokeWidth="1.5"/>
            <line x1="1" y1="5.5" x2="15" y2="5.5" stroke="currentColor" strokeWidth="1"/>
            <line x1="5.5" y1="5.5" x2="5.5" y2="15" stroke="currentColor" strokeWidth="1"/>
          </svg>
          DRAWREV
        </a>
        {breadcrumbs?.map((b, i) => (
          <span key={i} style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span style={{ color: "var(--ink-disabled)", fontSize: 11 }}>›</span>
            {b.href
              ? <a href={b.href} style={{ color: "var(--ink-secondary)", fontSize: 12, textDecoration: "none" }}>{b.label}</a>
              : <span style={{ color: "var(--ink)", fontSize: 12 }}>{b.label}</span>
            }
          </span>
        ))}
        <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 8 }}>
          {actions}
        </div>
      </nav>
      <div style={{ flex: 1, overflow: "hidden", display: "flex", flexDirection: "column" }}>
        {children}
      </div>
    </div>
  );
}

const STATUS_COLORS = {
  ready: "var(--signal-green)",
  confirmed: "var(--signal-green)",
  rejected: "var(--signal-red)",
  pending: "var(--signal-gray)",
  questionable: "var(--signal-amber)",
  processing: "var(--accent-primary)",
};

const STATUS_LABELS = {
  ready: "就绪", confirmed: "已确认", rejected: "已驳回",
  pending: "待审", questionable: "存疑", processing: "处理中",
};

function StatusDot({ status, label, pulse = false }) {
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
      <span style={{
        width: 7, height: 7, borderRadius: 2, flexShrink: 0,
        backgroundColor: STATUS_COLORS[status] || STATUS_COLORS.pending,
        animation: pulse && status === "processing" ? "pulse 1.5s ease-in-out infinite" : "none",
      }} />
      <span style={{ fontSize: 11, color: "var(--ink-secondary)" }}>
        {label ?? STATUS_LABELS[status] ?? status}
      </span>
    </span>
  );
}

Object.assign(window, { AppShell, StatusDot, STATUS_COLORS, STATUS_LABELS });
```

**Step 2: 验证 shared.jsx 加载无语法错误**

访问 `http://localhost:8000/parts/` 并打开浏览器 DevTools → Console。
预期：无 Babel 编译错误（旧的 app_shell.jsx 还在，但不影响 shared.jsx 加载）。

**Step 3: Commit**

```bash
git add app/static/jsx/shared.jsx
git commit -m "feat: add shared.jsx with AppShell and StatusDot (light theme, JSX)"
```

---

### Task 4：更新 marker_label.jsx — 加入 rejected 颜色 + onContextMenu

**Files:**
- Modify: `app/static/jsx/marker_label.jsx`

**背景：** 需要支持 `rejected` 状态颜色，以及传递右键事件给父组件（用于显示 ContextMenu）。

**Step 1: 重写 marker_label.jsx**

```jsx
// app/static/jsx/marker_label.jsx
function MarkerLabel({ dim, zoom, offsetX, offsetY, isSelected, onClick, onContextMenu }) {
  const colorMap = {
    pending: "var(--signal-gray)",
    confirmed: "var(--signal-green)",
    questionable: "var(--signal-amber)",
    rejected: "var(--signal-red)",
  };
  const x = dim.anchor_x * zoom + offsetX;
  const y = dim.anchor_y * zoom + offsetY;
  const size = Math.max(22, 26 / Math.sqrt(Math.max(zoom, 0.1)));
  const fontSize = Math.max(11, 11 / Math.sqrt(Math.max(zoom, 0.1)));

  return (
    <div
      data-marker="true"
      style={{
        position: "absolute", left: x, top: y,
        width: size, height: size,
        transform: "translate(-50%, -50%)",
        backgroundColor: colorMap[dim.review_status] || colorMap.pending,
        color: "#fff", display: "flex", alignItems: "center", justifyContent: "center",
        fontFamily: "var(--font-mono)", fontSize,
        fontWeight: 700, borderRadius: "var(--radius)",
        border: isSelected ? "2px solid var(--accent-primary)" : "1px solid rgba(0,0,0,0.15)",
        cursor: "pointer", zIndex: isSelected ? 20 : 10,
        boxShadow: isSelected ? "0 0 0 3px rgba(201,127,0,0.25)" : "0 1px 3px rgba(0,0,0,0.15)",
        transition: "box-shadow 0.15s, border-color 0.15s",
        userSelect: "none",
      }}
      onClick={(e) => { e.stopPropagation(); onClick(dim.id); }}
      onContextMenu={(e) => { e.preventDefault(); e.stopPropagation(); onContextMenu && onContextMenu(e, dim); }}
      title={dim.value}
    >
      {dim.sequence}
    </div>
  );
}

Object.assign(window, { MarkerLabel });
```

**Step 2: Commit**

```bash
git add app/static/jsx/marker_label.jsx
git commit -m "feat: add rejected color and onContextMenu to MarkerLabel"
```

---

### Task 5：重写 parts_list.html

**Files:**
- Modify: `app/templates/parts_list.html`

**背景：** 全量重写为 JSX 语法，加入汇总统计条、分段筛选控件、审核进度条。不再引入旧的 app_shell.jsx / status_dot.jsx / data_table.jsx（spa.html 已加载 shared.jsx）。

**Step 1: 重写 parts_list.html**

```html
{% extends "spa.html" %}
{% block scripts %}
<script type="text/babel">
const { useState, useEffect } = React;

function SummaryStrip({ parts }) {
  const totalPending = parts.reduce((a, p) => a + (p.pending_count || 0), 0);
  const totalReady = parts.filter(p => p.current_version?.status === "ready").length;
  const totalProcessing = parts.filter(p => p.current_version?.status === "processing").length;
  const stats = [
    { label: "全部零件", value: parts.length, color: "var(--ink)" },
    { label: "待审标注", value: totalPending, color: "var(--signal-amber)" },
    { label: "可审核", value: totalReady, color: "var(--signal-green)" },
    { label: "处理中", value: totalProcessing, color: "var(--accent-primary)" },
  ];
  return (
    <div style={{
      display: "flex", background: "var(--bg-surface)",
      borderBottom: "1px solid var(--border-color)", padding: "0 20px",
    }}>
      {stats.map((s, i) => (
        <div key={i} style={{
          padding: "10px 24px", borderRight: "1px solid var(--border-color)",
          display: "flex", flexDirection: "column", gap: 2,
        }}>
          <span style={{ fontSize: 10, color: "var(--ink-secondary)", textTransform: "uppercase", letterSpacing: "0.06em" }}>{s.label}</span>
          <span style={{ fontSize: 20, fontWeight: 700, color: s.color, fontFamily: "var(--font-mono)" }}>{s.value}</span>
        </div>
      ))}
    </div>
  );
}

const FILTER_OPTIONS = [
  { value: "all", label: "全部" },
  { value: "ready", label: "就绪" },
  { value: "processing", label: "处理中" },
  { value: "confirmed", label: "已确认" },
  { value: "pending", label: "待上传" },
];

function SegmentedFilter({ value, onChange }) {
  return (
    <div style={{ display: "flex", gap: 2, background: "var(--bg-elevated)", borderRadius: 4, padding: 2 }}>
      {FILTER_OPTIONS.map(opt => (
        <button key={opt.value} onClick={() => onChange(opt.value)} style={{
          padding: "4px 10px", borderRadius: 3, border: "none", cursor: "pointer", fontSize: 11,
          background: value === opt.value ? "var(--bg-surface)" : "transparent",
          color: value === opt.value ? "var(--ink)" : "var(--ink-secondary)",
          boxShadow: value === opt.value ? "0 1px 3px rgba(0,0,0,0.12)" : "none",
          transition: "all 0.15s",
        }}>{opt.label}</button>
      ))}
    </div>
  );
}

function NewPartModal({ isOpen, onClose, onCreated }) {
  const [name, setName] = useState("");
  const [drawingNumber, setDrawingNumber] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError(""); setSubmitting(true);
    const fd = new FormData();
    fd.append("name", name); fd.append("drawing_number", drawingNumber);
    try {
      const resp = await fetch("/parts/api/create", { method: "POST", body: fd });
      if (!resp.ok) { const d = await resp.json(); throw new Error(d.detail || "创建失败"); }
      onCreated(await resp.json());
      setName(""); setDrawingNumber(""); onClose();
    } catch (err) { setError(err.message); }
    finally { setSubmitting(false); }
  };

  if (!isOpen) return null;
  return (
    <div onClick={onClose} style={{ position: "fixed", inset: 0, zIndex: 100, background: "rgba(0,0,0,0.3)", display: "flex", alignItems: "center", justifyContent: "center" }}>
      <div onClick={e => e.stopPropagation()} style={{ background: "var(--bg-surface)", borderRadius: 4, padding: 24, width: 420, maxWidth: "90vw", border: "1px solid var(--border-color)", boxShadow: "var(--shadow-card)" }}>
        <h2 style={{ fontSize: 15, fontWeight: 600, color: "var(--ink)", marginBottom: 16, fontFamily: "var(--font-display)" }}>新增零件</h2>
        <form onSubmit={handleSubmit}>
          {[["零件名称", name, setName, "例：发动机缸体"], ["图号", drawingNumber, setDrawingNumber, "例：ENG-001-A"]].map(([label, val, setter, ph]) => (
            <div key={label} style={{ marginBottom: 12 }}>
              <label style={{ display: "block", fontSize: 11, color: "var(--ink-secondary)", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 4 }}>{label}</label>
              <input value={val} onChange={e => setter(e.target.value)} placeholder={ph} required
                style={{ width: "100%", padding: "6px 10px", background: "var(--bg-elevated)", border: "1px solid var(--border-color)", borderRadius: 2, color: "var(--ink)", fontSize: 13, outline: "none" }} />
            </div>
          ))}
          {error && <div style={{ color: "var(--signal-red)", fontSize: 12, marginBottom: 8 }}>{error}</div>}
          <div style={{ display: "flex", gap: 8, justifyContent: "flex-end", marginTop: 16 }}>
            <button type="button" onClick={onClose} style={{ padding: "6px 16px", background: "transparent", border: "1px solid var(--border-color)", borderRadius: 2, color: "var(--ink-secondary)", cursor: "pointer", fontSize: 13 }}>取消</button>
            <button type="submit" disabled={submitting} style={{ padding: "6px 16px", background: "var(--accent-primary)", border: "none", borderRadius: 2, color: "#fff", cursor: "pointer", fontSize: 13, fontWeight: 600, opacity: submitting ? 0.5 : 1 }}>{submitting ? "创建中..." : "创建零件"}</button>
          </div>
        </form>
      </div>
    </div>
  );
}

function App() {
  const [parts, setParts] = useState([]);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
  const [modalOpen, setModalOpen] = useState(false);
  const [selectedId, setSelectedId] = useState(null);

  useEffect(() => { fetch("/parts/api/list").then(r => r.json()).then(setParts); }, []);

  const filtered = parts.filter(p => {
    const q = search.toLowerCase();
    const matchSearch = !q || p.name.toLowerCase().includes(q) || p.drawing_number.toLowerCase().includes(q);
    const v = p.current_version;
    const matchStatus = statusFilter === "all"
      || (v ? v.status === statusFilter : statusFilter === "pending");
    return matchSearch && matchStatus;
  });

  const handleRowClick = p => {
    const v = p.current_version;
    window.location.href = v ? `/parts/${p.id}/versions/${v.id}/review` : `/parts/${p.id}`;
  };

  return (
    <div style={{ height: "100%", display: "flex", flexDirection: "column" }}>
      <AppShell
        breadcrumbs={[{ label: "零件列表" }]}
        actions={
          <button onClick={() => setModalOpen(true)} style={{ padding: "5px 14px", background: "var(--accent-primary)", border: "none", borderRadius: 2, color: "#fff", cursor: "pointer", fontSize: 12, fontWeight: 600 }}>
            + 新增零件
          </button>
        }
      >
        <SummaryStrip parts={parts} />
        <div style={{ display: "flex", gap: 12, padding: "10px 20px", background: "var(--bg-canvas)", borderBottom: "1px solid var(--border-color)", alignItems: "center" }}>
          <div style={{ position: "relative", flex: 1, maxWidth: 340 }}>
            <svg style={{ position: "absolute", left: 10, top: "50%", transform: "translateY(-50%)", color: "var(--ink-disabled)" }} width="13" height="13" viewBox="0 0 13 13" fill="none">
              <circle cx="5.5" cy="5.5" r="4.5" stroke="currentColor" strokeWidth="1.3"/>
              <line x1="9.5" y1="9.5" x2="12" y2="12" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round"/>
            </svg>
            <input value={search} onChange={e => setSearch(e.target.value)} placeholder="搜索零件名称或图号…"
              style={{ width: "100%", padding: "6px 10px 6px 30px", background: "var(--bg-surface)", border: "1px solid var(--border-color)", borderRadius: 4, color: "var(--ink)", fontSize: 12, outline: "none" }} />
          </div>
          <SegmentedFilter value={statusFilter} onChange={setStatusFilter} />
          <span style={{ marginLeft: "auto", fontSize: 11, color: "var(--ink-disabled)", fontFamily: "monospace" }}>{filtered.length} / {parts.length} 条</span>
        </div>
        <div style={{ flex: 1, overflow: "auto", padding: "0 20px 20px" }}>
          <table className="industrial" style={{ marginTop: 12 }}>
            <thead>
              <tr>
                <th>图号</th><th>零件名称</th><th>当前版本</th><th>状态</th>
                <th>待审 / 总计</th><th>审核进度</th><th>创建时间</th>
              </tr>
            </thead>
            <tbody>
              {filtered.length === 0
                ? <tr><td colSpan={7} style={{ textAlign: "center", color: "var(--ink-disabled)", padding: 40 }}>暂无数据</td></tr>
                : filtered.map(p => {
                    const pct = p.total_count > 0 ? Math.round(((p.total_count - p.pending_count) / p.total_count) * 100) : 0;
                    return (
                      <tr key={p.id} className={selectedId === p.id ? "selected" : ""} onClick={() => { setSelectedId(p.id); handleRowClick(p); }}>
                        <td><span style={{ fontFamily: "monospace", fontSize: 11, color: "var(--ink-secondary)" }}>{p.drawing_number}</span></td>
                        <td><span style={{ fontWeight: 600 }}>{p.name}</span></td>
                        <td>{p.current_version
                          ? <span style={{ fontFamily: "monospace", fontSize: 11 }}>{p.current_version.version_code}</span>
                          : <span style={{ color: "var(--ink-disabled)" }}>—</span>}
                        </td>
                        <td>{p.current_version
                          ? <StatusDot status={p.current_version.status} pulse={p.current_version.status === "processing"} />
                          : <StatusDot status="pending" label="待上传" />}
                        </td>
                        <td>
                          <span style={{ fontFamily: "monospace", fontSize: 12 }}>
                            <span style={{ color: p.pending_count > 0 ? "var(--signal-amber)" : "var(--signal-green)" }}>{p.pending_count}</span>
                            <span style={{ color: "var(--ink-disabled)" }}> / {p.total_count}</span>
                          </span>
                        </td>
                        <td style={{ width: 120 }}>
                          {p.total_count > 0 ? (
                            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                              <div className="progress-track" style={{ flex: 1, height: 4 }}>
                                <div className="progress-fill" style={{ width: `${pct}%`, background: pct === 100 ? "var(--signal-green)" : "var(--accent-primary)" }} />
                              </div>
                              <span style={{ fontSize: 10, fontFamily: "monospace", color: "var(--ink-secondary)", minWidth: 28 }}>{pct}%</span>
                            </div>
                          ) : <span style={{ color: "var(--ink-disabled)", fontSize: 11 }}>—</span>}
                        </td>
                        <td><span style={{ color: "var(--ink-secondary)", fontSize: 11 }}>{p.created_at}</span></td>
                      </tr>
                    );
                  })
              }
            </tbody>
          </table>
        </div>
      </AppShell>
      <NewPartModal isOpen={modalOpen} onClose={() => setModalOpen(false)} onCreated={() => fetch("/parts/api/list").then(r => r.json()).then(setParts)} />
    </div>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<App />);
</script>
{% endblock %}
```

**Step 2: 验证零件列表页**

访问 `http://localhost:8000/parts/`，确认：
- [ ] DRAWREV Logo 显示在左上角
- [ ] 汇总统计条（4 个数字）显示在导航栏下方
- [ ] 分段控件（全部/就绪/处理中/已确认/待上传）正常切换
- [ ] 表格每行有进度条
- [ ] 新增零件弹窗正常

**Step 3: Commit**

```bash
git add app/templates/parts_list.html
git commit -m "feat: rewrite parts_list with JSX, summary strip, segmented filter, progress bars"
```

---

### Task 6：重写 review_workbench.html

**Files:**
- Modify: `app/templates/review_workbench.html`

**背景：** 全量重写。主要变化：JSX 语法、4 种标注状态（加驳回）、右键 ContextMenu、移除 ConclusionBar、画布底色浅灰。

**注意：** `review_workbench.html` 还额外引入 `marker_label.jsx`，需在 `{% block scripts %}` 中保留该 script 标签。

**Step 1: 重写 review_workbench.html**

完整文件内容（分段说明各组件）：

```html
{% extends "spa.html" %}
{% block scripts %}
<script type="text/babel" src="/static/jsx/marker_label.jsx"></script>
<script type="text/babel">
const { useState, useEffect, useRef, useCallback, useMemo } = React;

const pathParts = window.location.pathname.split("/");
const partId = Number(pathParts[2]);
const versionId = Number(pathParts[4]);

// ── 状态配置 ────────────────────────────────────────────────────────────────
const REVIEW_STATUSES = [
  { value: "confirmed",    label: "确认",  color: "var(--signal-green)" },
  { value: "questionable", label: "存疑",  color: "var(--signal-amber)" },
  { value: "rejected",     label: "驳回",  color: "var(--signal-red)"   },
  { value: "pending",      label: "待审",  color: "var(--signal-gray)"  },
];

// ── usePanZoom ───────────────────────────────────────────────────────────────
function usePanZoom(containerRef) {
  const [zoom, setZoom] = useState(0.85);
  const [offset, setOffset] = useState({ x: 0, y: 0 });
  const isPanning = useRef(false);
  const lastMouse = useRef({ x: 0, y: 0 });

  const fitScreen = useCallback((imgEl) => {
    const c = containerRef.current;
    if (!c) return;
    const el = imgEl || c.querySelector("img");
    if (!el || !el.naturalWidth) { setZoom(1); setOffset({ x: 0, y: 0 }); return; }
    const scale = Math.min(c.clientWidth / el.naturalWidth, c.clientHeight / el.naturalHeight, 1.5) * 0.92;
    setZoom(scale);
    setOffset({ x: (c.clientWidth - el.naturalWidth * scale) / 2, y: (c.clientHeight - el.naturalHeight * scale) / 2 });
  }, [containerRef]);

  const handleWheel = useCallback(e => {
    e.preventDefault();
    const factor = e.deltaY > 0 ? 0.91 : 1.1;
    setZoom(z => {
      const nz = Math.min(10, Math.max(0.1, z * factor));
      const rect = containerRef.current.getBoundingClientRect();
      const mx = e.clientX - rect.left, my = e.clientY - rect.top;
      setOffset(o => ({ x: mx - (mx - o.x) * (nz / z), y: my - (my - o.y) * (nz / z) }));
      return nz;
    });
  }, [containerRef]);

  const onMouseDown = useCallback(e => {
    if (e.button !== 0) return;
    if (e.target.closest("[data-marker]")) return;
    isPanning.current = true;
    lastMouse.current = { x: e.clientX, y: e.clientY };
    e.currentTarget.style.cursor = "grabbing";
  }, []);

  const onMouseMove = useCallback(e => {
    if (!isPanning.current) return;
    const dx = e.clientX - lastMouse.current.x, dy = e.clientY - lastMouse.current.y;
    lastMouse.current = { x: e.clientX, y: e.clientY };
    setOffset(o => ({ x: o.x + dx, y: o.y + dy }));
  }, []);

  const onMouseUp = useCallback(e => {
    isPanning.current = false;
    if (e.currentTarget) e.currentTarget.style.cursor = "grab";
  }, []);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    el.addEventListener("wheel", handleWheel, { passive: false });
    return () => el.removeEventListener("wheel", handleWheel);
  }, [handleWheel]);

  return { zoom, offset, fitScreen, onMouseDown, onMouseMove, onMouseUp, setOffset, setZoom };
}

// ── 标注重叠分离 ─────────────────────────────────────────────────────────────
function applyRepulsion(dims, zoom) {
  if (zoom >= 0.55) return dims.map(d => ({ ...d, _gx: 0, _gy: 0 }));
  const gap = 30 / Math.max(zoom, 0.1);
  const adj = dims.map(d => ({ ...d, _gx: 0, _gy: 0 }));
  for (let iter = 0; iter < 12; iter++) {
    let moved = false;
    for (let i = 0; i < adj.length; i++) {
      for (let j = i + 1; j < adj.length; j++) {
        const dx = (adj[i].anchor_x + adj[i]._gx) - (adj[j].anchor_x + adj[j]._gx);
        const dy = (adj[i].anchor_y + adj[i]._gy) - (adj[j].anchor_y + adj[j]._gy);
        const dist = Math.sqrt(dx * dx + dy * dy);
        if (dist < gap && dist > 0.01) {
          const p = (gap - dist) / dist * 0.5;
          adj[i]._gx += dx * p; adj[i]._gy += dy * p;
          adj[j]._gx -= dx * p; adj[j]._gy -= dy * p;
          moved = true;
        }
      }
    }
    if (!moved) break;
  }
  return adj;
}

// ── ContextMenu ──────────────────────────────────────────────────────────────
function ContextMenu({ x, y, dim, onClose, onStatusChange }) {
  const menuRef = useRef(null);
  const [pos, setPos] = useState({ x, y });

  useEffect(() => {
    const handler = () => onClose();
    window.addEventListener("click", handler);
    return () => window.removeEventListener("click", handler);
  }, [onClose]);

  useEffect(() => {
    if (!menuRef.current) return;
    const rect = menuRef.current.getBoundingClientRect();
    setPos({
      x: x + rect.width > window.innerWidth ? window.innerWidth - rect.width - 8 : x,
      y: y + rect.height > window.innerHeight ? window.innerHeight - rect.height - 8 : y,
    });
  }, [x, y]);

  const items = REVIEW_STATUSES.filter(s => s.value !== dim.review_status);

  return (
    <div ref={menuRef} className="ctx-menu" style={{ left: pos.x, top: pos.y }} onClick={e => e.stopPropagation()}>
      <div style={{ padding: "4px 10px 6px", fontSize: 10, color: "var(--ink-disabled)", textTransform: "uppercase", letterSpacing: "0.06em" }}>
        #{String(dim.sequence).padStart(2, "0")} {dim.value}
      </div>
      <div className="ctx-divider" />
      {items.map(it => (
        <div key={it.value} className="ctx-item" onClick={() => { onStatusChange(dim.id, it.value); onClose(); }}>
          <span className="ctx-dot" style={{ background: it.color }} />
          {it.label}
        </div>
      ))}
    </div>
  );
}

// ── DrawingCanvas ────────────────────────────────────────────────────────────
function DrawingCanvas({ drawing, dims, selectedDimId, onSelectDim, onContextMenuDim, readOnly }) {
  const containerRef = useRef(null);
  const { zoom, offset, fitScreen, onMouseDown, onMouseMove, onMouseUp } = usePanZoom(containerRef);
  const [imageError, setImageError] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => { setImageError(false); fitScreen(); }, [drawing?.id]);

  const showGuides = zoom < 0.5;
  const adjustedDims = useMemo(() =>
    showGuides ? applyRepulsion(dims, zoom) : dims.map(d => ({ ...d, _gx: 0, _gy: 0 })),
    [dims, zoom, showGuides]
  );

  const imgSrc = drawing ? `/static/drawings/${drawing.id}/page_1.jpg?t=${reloadKey}` : null;

  return (
    <div
      ref={containerRef}
      onMouseDown={onMouseDown} onMouseMove={onMouseMove} onMouseUp={onMouseUp} onMouseLeave={onMouseUp}
      onDoubleClick={() => fitScreen()}
      style={{ flex: 1, position: "relative", overflow: "hidden", background: "#e8eaed", cursor: "grab" }}
    >
      <div style={{ position: "absolute", top: 8, right: 8, zIndex: 30, display: "flex", alignItems: "center", gap: 8, background: "rgba(255,255,255,0.85)", border: "1px solid var(--border-color)", borderRadius: 2, padding: "4px 8px", backdropFilter: "blur(4px)" }}>
        <span style={{ fontFamily: "var(--font-mono)", fontSize: 12, color: "var(--ink-secondary)", minWidth: 42, textAlign: "center" }}>{Math.round(zoom * 100)}%</span>
        <button onClick={() => fitScreen()} style={{ background: "transparent", border: "1px solid var(--border-color)", borderRadius: 2, color: "var(--ink-secondary)", cursor: "pointer", fontSize: 14, padding: "2px 6px", lineHeight: 1 }} title="适应窗口">⊞</button>
      </div>
      {imageError ? (
        <div style={{ position: "absolute", inset: 0, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", color: "var(--ink-disabled)" }}>
          <div style={{ fontSize: 48, marginBottom: 12, opacity: 0.5 }}>📐</div>
          <div style={{ fontSize: 15, fontWeight: 600, color: "var(--ink-secondary)", marginBottom: 4 }}>图纸图片未生成</div>
          <div style={{ fontSize: 12, marginBottom: 16 }}>请重新上传版本或点击下方按钮重新生成</div>
          <button onClick={async () => {
            const resp = await fetch(`/parts/${partId}/versions/${versionId}/reprocess`, { method: "POST" });
            if (resp.ok) { setReloadKey(k => k + 1); setImageError(false); }
          }} style={{ padding: "6px 20px", background: "var(--accent-primary)", border: "none", borderRadius: 2, color: "#fff", cursor: "pointer", fontSize: 13, fontWeight: 600 }}>重新生成图片</button>
        </div>
      ) : imgSrc && (
        <img src={imgSrc} onError={() => setImageError(true)} onLoad={e => fitScreen(e.target)}
          style={{ position: "absolute", top: 0, left: 0, pointerEvents: "none", userSelect: "none", transform: `translate(${offset.x}px, ${offset.y}px) scale(${zoom})`, transformOrigin: "0 0" }}
          draggable={false} />
      )}
      {showGuides && (
        <svg style={{ position: "absolute", top: 0, left: 0, width: "100%", height: "100%", pointerEvents: "none", zIndex: 5 }}>
          {adjustedDims.filter(d => Math.abs(d._gx) > 1 || Math.abs(d._gy) > 1).map(d => (
            <line key={`g-${d.id}`}
              x1={(d.anchor_x + d._gx) * zoom + offset.x} y1={(d.anchor_y + d._gy) * zoom + offset.y}
              x2={d.anchor_x * zoom + offset.x} y2={d.anchor_y * zoom + offset.y}
              stroke="var(--ink-disabled)" strokeWidth={1} strokeDasharray="3 3" opacity={0.5} />
          ))}
        </svg>
      )}
      {adjustedDims.map(d => (
        <MarkerLabel key={d.id}
          dim={{ ...d, anchor_x: d.anchor_x + d._gx, anchor_y: d.anchor_y + d._gy }}
          zoom={zoom} offsetX={offset.x} offsetY={offset.y}
          isSelected={d.id === selectedDimId}
          onClick={onSelectDim}
          onContextMenu={!readOnly ? onContextMenuDim : undefined}
        />
      ))}
    </div>
  );
}

// ── DrawingTabs ──────────────────────────────────────────────────────────────
function DrawingTabs({ drawings, activeDrawingId, onSelect }) {
  return (
    <div style={{ display: "flex", gap: 1, background: "var(--bg-surface)", borderBottom: "1px solid var(--border-color)", padding: "0 12px", overflowX: "auto" }}>
      {drawings.map(d => (
        <button key={d.id} onClick={() => onSelect(d.id)} style={{
          padding: "6px 14px", background: "transparent", border: "none",
          borderBottom: `2px solid ${d.id === activeDrawingId ? "var(--accent-primary)" : "transparent"}`,
          cursor: "pointer", fontSize: 12,
          color: d.id === activeDrawingId ? "var(--ink)" : "var(--ink-secondary)",
          whiteSpace: "nowrap",
        }}>图纸 {d.sequence} · {d.filename}</button>
      ))}
    </div>
  );
}

// ── DimensionList ────────────────────────────────────────────────────────────
const DIM_FILTERS = [
  { value: "all", label: "全部" },
  { value: "pending", label: "待审" },
  { value: "confirmed", label: "确认" },
  { value: "questionable", label: "存疑" },
  { value: "rejected", label: "驳回" },
];

const DIM_COLORS = {
  pending: "var(--signal-gray)", confirmed: "var(--signal-green)",
  questionable: "var(--signal-amber)", rejected: "var(--signal-red)",
};

function DimensionList({ dims, selectedDimId, onSelect, filter, onFilterChange }) {
  const filtered = filter === "all" ? dims : dims.filter(d => d.review_status === filter);
  return (
    <div>
      <div style={{ display: "flex", gap: 1, padding: "0 12px", borderBottom: "1px solid var(--border-color)", alignItems: "center" }}>
        {DIM_FILTERS.map(opt => (
          <button key={opt.value} onClick={() => onFilterChange(opt.value)} style={{
            padding: "6px 10px", background: "transparent", border: "none",
            borderBottom: `2px solid ${filter === opt.value ? "var(--accent-primary)" : "transparent"}`,
            cursor: "pointer", fontSize: 12,
            color: filter === opt.value ? "var(--accent-primary)" : "var(--ink-secondary)",
          }}>{opt.label}</button>
        ))}
        <span style={{ marginLeft: "auto", fontSize: 11, color: "var(--ink-disabled)", fontFamily: "monospace" }}>{filtered.length}/{dims.length}</span>
      </div>
      <div style={{ maxHeight: 240, overflowY: "auto" }}>
        {filtered.length === 0
          ? <div style={{ padding: 24, textAlign: "center", color: "var(--ink-disabled)", fontSize: 12 }}>暂无标注</div>
          : filtered.map(d => (
              <div key={d.id} onClick={() => onSelect(d.id)} style={{
                display: "flex", alignItems: "center", gap: 8,
                padding: "6px 12px", cursor: "pointer",
                borderBottom: "1px solid var(--border-color)",
                background: d.id === selectedDimId ? "var(--bg-selected)" : "transparent",
              }}>
                <span style={{ fontFamily: "var(--font-mono)", fontSize: 12, fontWeight: 700, color: "var(--ink-disabled)", minWidth: 22 }}>{String(d.sequence).padStart(2, "0")}</span>
                <span style={{ fontFamily: "var(--font-mono)", fontSize: 13, color: "var(--ink)", flex: 1 }}>{d.value}</span>
                <span style={{ width: 7, height: 7, borderRadius: 2, flexShrink: 0, backgroundColor: DIM_COLORS[d.review_status] || DIM_COLORS.pending }} />
                {d.message_count > 0 && (
                  <span style={{ fontSize: 10, background: "var(--accent-primary)", color: "#fff", borderRadius: 2, minWidth: 16, height: 16, display: "inline-flex", alignItems: "center", justifyContent: "center", fontWeight: 600 }}>{d.message_count}</span>
                )}
              </div>
            ))
        }
      </div>
    </div>
  );
}

// ── DimensionDetail ──────────────────────────────────────────────────────────
function DimensionDetail({ dim, readOnly, onStatusChange }) {
  if (!dim) return (
    <div style={{ padding: 16, color: "var(--ink-disabled)", fontSize: 12, textAlign: "center" }}>选择一个标注</div>
  );
  return (
    <div style={{ padding: 16, borderBottom: "1px solid var(--border-color)" }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 8, marginBottom: 12 }}>
        <span style={{ fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--ink-disabled)" }}>#{String(dim.sequence).padStart(2, "0")}</span>
        <span style={{ fontFamily: "var(--font-mono)", fontSize: 16, fontWeight: 600, color: "var(--ink)" }}>{dim.value}</span>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginBottom: 12 }}>
        {[["类型", dim.dim_type], ["来源", dim.source], ["视图", dim.view_name || "—"], ["坐标", dim.anchor_x ? `${Math.round(dim.anchor_x)}, ${Math.round(dim.anchor_y)}` : "—"]].map(([label, value]) => (
          <div key={label}>
            <div style={{ fontSize: 10, color: "var(--ink-disabled)", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 2 }}>{label}</div>
            <div style={{ fontSize: 12, color: "var(--ink)", fontFamily: "var(--font-mono)" }}>{value}</div>
          </div>
        ))}
      </div>
      {!readOnly && (
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <span style={{ fontSize: 11, color: "var(--ink-secondary)", textTransform: "uppercase", letterSpacing: "0.05em" }}>状态</span>
          <div style={{ display: "flex", gap: 4 }}>
            {REVIEW_STATUSES.map(s => (
              <button key={s.value} onClick={() => onStatusChange(dim.id, s.value)} style={{
                padding: "3px 10px", border: "1px solid",
                borderRadius: 2, cursor: "pointer", fontSize: 11, fontWeight: 600,
                background: dim.review_status === s.value ? s.color : "transparent",
                color: dim.review_status === s.value ? "#fff" : "var(--ink-secondary)",
                borderColor: dim.review_status === s.value ? s.color : "var(--border-color)",
              }}>{s.label}</button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ── DiscussionThread ─────────────────────────────────────────────────────────
function DiscussionThread({ dimId, readOnly }) {
  const [messages, setMessages] = useState([]);
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);

  useEffect(() => {
    if (!dimId) { setMessages([]); return; }
    fetch(`/api/dimensions/${dimId}/messages`).then(r => r.json()).then(setMessages);
  }, [dimId]);

  const handleSend = async () => {
    if (!text.trim() || sending) return;
    setSending(true);
    try {
      const resp = await fetch(`/api/dimensions/${dimId}/messages`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ author: "审核员", content: text.trim() }),
      });
      if (resp.ok) { setMessages(prev => [...prev, await resp.json()]); setText(""); }
    } finally { setSending(false); }
  };

  return (
    <div style={{ borderBottom: "1px solid var(--border-color)" }}>
      <div style={{ padding: 12, maxHeight: 200, overflowY: "auto" }}>
        {messages.length === 0
          ? <div style={{ color: "var(--ink-disabled)", fontSize: 12, textAlign: "center", padding: 16 }}>暂无讨论</div>
          : messages.map(m => (
              <div key={m.id} style={{ background: "var(--bg-elevated)", borderRadius: 2, padding: "8px 12px", marginBottom: 8 }}>
                <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
                  <span style={{ fontSize: 11, fontWeight: 600, color: "var(--accent-primary)" }}>{m.author}</span>
                  <span style={{ fontSize: 10, color: "var(--ink-disabled)" }}>{m.created_at}</span>
                </div>
                <div style={{ fontSize: 12, color: "var(--ink)", lineHeight: 1.5 }}>{m.content}</div>
              </div>
            ))
        }
      </div>
      {!readOnly && (
        <div style={{ display: "flex", gap: 8, padding: "8px 12px", borderTop: "1px solid var(--border-color)" }}>
          <input value={text} onChange={e => setText(e.target.value)}
            onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); handleSend(); } }}
            placeholder="输入讨论内容..." style={{ flex: 1, padding: "5px 10px", background: "var(--bg-elevated)", border: "1px solid var(--border-color)", borderRadius: 2, color: "var(--ink)", fontSize: 12, outline: "none" }} />
          <button onClick={handleSend} disabled={sending || !text.trim()} style={{ padding: "5px 14px", background: "var(--accent-primary)", border: "none", borderRadius: 2, color: "#fff", cursor: "pointer", fontSize: 12, fontWeight: 600, opacity: sending || !text.trim() ? 0.5 : 1 }}>发送</button>
        </div>
      )}
    </div>
  );
}

// ── App ──────────────────────────────────────────────────────────────────────
function App() {
  const [versions, setVersions] = useState([]);
  const [currentVersionId, setCurrentVersionId] = useState(versionId);
  const [drawings, setDrawings] = useState([]);
  const [activeDrawingId, setActiveDrawingId] = useState(null);
  const [dims, setDims] = useState([]);
  const [selectedDimId, setSelectedDimId] = useState(null);
  const [versionInfo, setVersionInfo] = useState(null);
  const [dimFilter, setDimFilter] = useState("all");
  const [ctxMenu, setCtxMenu] = useState(null);

  useEffect(() => {
    fetch(`/api/parts/${partId}/versions`).then(r => r.json()).then(data => {
      setVersions(data);
      const cv = data.find(v => v.id === currentVersionId);
      if (cv) setVersionInfo(cv);
    });
  }, []);

  useEffect(() => {
    fetch(`/api/versions/${currentVersionId}/drawings`).then(r => r.json()).then(data => {
      setDrawings(data);
      if (data.length > 0) setActiveDrawingId(data[0].id);
    });
  }, [currentVersionId]);

  useEffect(() => {
    if (!activeDrawingId) { setDims([]); return; }
    fetch(`/api/versions/${currentVersionId}/drawings/${activeDrawingId}/dimensions`).then(r => r.json()).then(setDims);
  }, [currentVersionId, activeDrawingId]);

  const handleVersionChange = vid => {
    setCurrentVersionId(vid); setActiveDrawingId(null); setSelectedDimId(null); setDimFilter("all");
    window.history.replaceState(null, "", `/parts/${partId}/versions/${vid}/review`);
    setVersionInfo(versions.find(v => v.id === vid) || null);
  };

  const handleStatusChange = async (dimId, newStatus) => {
    await fetch(`/api/dimensions/${dimId}`, {
      method: "PATCH", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ review_status: newStatus }),
    });
    setDims(prev => prev.map(d => d.id === dimId ? { ...d, review_status: newStatus } : d));
  };

  const handleContextMenuDim = (e, dim) => {
    setCtxMenu({ x: e.clientX, y: e.clientY, dim });
    setSelectedDimId(dim.id);
  };

  const selectedDim = dims.find(d => d.id === selectedDimId);
  const activeDrawing = drawings.find(d => d.id === activeDrawingId);
  const isReadOnly = versionInfo?.confirm_result != null && !versionInfo?.is_current;

  return (
    <div style={{ height: "100%", display: "flex", flexDirection: "column" }}>
      <AppShell
        breadcrumbs={[{ label: "零件列表", href: "/parts/" }, { label: "审核工作台" }]}
        actions={
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            {versionInfo && <StatusDot status={versionInfo.status} pulse={versionInfo.status === "processing"} />}
            <select value={currentVersionId} onChange={e => handleVersionChange(Number(e.target.value))} style={{ padding: "4px 8px", background: "var(--bg-elevated)", border: "1px solid var(--border-color)", borderRadius: 2, color: "var(--ink)", fontSize: 12, outline: "none", cursor: "pointer", fontFamily: "var(--font-mono)" }}>
              {versions.map(v => (
                <option key={v.id} value={v.id}>{v.version_code}{v.is_current ? " (当前)" : ""}</option>
              ))}
            </select>
          </div>
        }
      >
        <div style={{ flex: 1, display: "flex", overflow: "hidden" }}>
          <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}>
            {drawings.length > 1 && <DrawingTabs drawings={drawings} activeDrawingId={activeDrawingId} onSelect={setActiveDrawingId} />}
            <DrawingCanvas
              drawing={activeDrawing} dims={dims} selectedDimId={selectedDimId}
              onSelectDim={setSelectedDimId} onContextMenuDim={handleContextMenuDim}
              readOnly={isReadOnly}
            />
          </div>
          <div style={{ width: 280, borderLeft: "1px solid var(--border-color)", display: "flex", flexDirection: "column", overflow: "hidden", background: "var(--bg-surface)" }}>
            <DimensionList dims={dims} selectedDimId={selectedDimId} onSelect={setSelectedDimId} filter={dimFilter} onFilterChange={setDimFilter} />
            <div style={{ flex: 1, overflowY: "auto" }}>
              <DimensionDetail dim={selectedDim} readOnly={isReadOnly} onStatusChange={handleStatusChange} />
              {selectedDimId && <DiscussionThread dimId={selectedDimId} readOnly={isReadOnly} />}
            </div>
          </div>
        </div>
      </AppShell>
      {ctxMenu && (
        <ContextMenu x={ctxMenu.x} y={ctxMenu.y} dim={ctxMenu.dim}
          onClose={() => setCtxMenu(null)} onStatusChange={handleStatusChange} />
      )}
    </div>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<App />);
</script>
{% endblock %}
```

**Step 2: 验证审核工作台**

访问 `http://localhost:8000/parts/1/versions/1/review`，确认：
- [ ] 浅色主题（白底），画布区为浅灰 `#e8eaed`
- [ ] 顶部版本选择下拉在导航栏右侧
- [ ] 标注圆点颜色正确（绿/黄/红/灰）
- [ ] 右键点击标注圆点弹出 ContextMenu，选项排除当前状态
- [ ] 侧栏筛选 tab 包含"驳回"
- [ ] ConclusionBar（通过/驳回按钮）已消失
- [ ] 讨论线程正常加载和发送

**Step 3: Commit**

```bash
git add app/templates/review_workbench.html
git commit -m "feat: rewrite workbench with JSX, 4 statuses, context menu, remove ConclusionBar"
```

---

### Task 7：删除旧 JSX 文件

**Files:**
- Delete: `app/static/jsx/design_tokens.jsx`
- Delete: `app/static/jsx/app_shell.jsx`
- Delete: `app/static/jsx/status_dot.jsx`
- Delete: `app/static/jsx/stamp.jsx`
- Delete: `app/static/jsx/data_table.jsx`

**Step 1: 删除文件**

```bash
rm app/static/jsx/design_tokens.jsx \
   app/static/jsx/app_shell.jsx \
   app/static/jsx/status_dot.jsx \
   app/static/jsx/stamp.jsx \
   app/static/jsx/data_table.jsx
```

**Step 2: 确认页面无 404 加载错误**

刷新零件列表页和审核工作台页，打开 DevTools → Network 标签，确认无红色 404 请求。

**Step 3: Commit**

```bash
git add -A
git commit -m "chore: remove obsolete JSX files replaced by shared.jsx"
```

---

### Task 8：完整功能验收

**Step 1: 全流程验证清单**

零件列表页 (`/parts/`):
- [ ] DRAWREV SVG Logo 显示
- [ ] 汇总统计条数字正确
- [ ] 分段控件筛选有效
- [ ] 表格进度条显示
- [ ] 新增零件弹窗能创建并刷新列表
- [ ] 点击行跳转到工作台

审核工作台 (`/parts/:id/versions/:id/review`):
- [ ] 浅色主题整体正确
- [ ] 图纸显示在浅灰画布上
- [ ] 双击画布重置缩放
- [ ] 标注圆点四色正确（待审=灰/确认=绿/存疑=琥珀/驳回=红）
- [ ] 左键选中标注，侧栏详情更新
- [ ] 侧栏状态按钮改状态，圆点颜色同步更新
- [ ] 右键标注圆点弹出菜单，通过菜单改状态有效
- [ ] 侧栏筛选 tab 包含"驳回"
- [ ] 讨论线程加载、发送消息正常
- [ ] 无 ConclusionBar

**Step 2: Commit（若无额外修复则直接最终 commit）**

```bash
git add -A
git commit -m "feat: complete frontend redesign - light theme, 4 statuses, context menu"
```
