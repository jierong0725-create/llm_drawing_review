# 审核工作台优化实现计划

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 对齐参考设计 `llm_drawing_review.html`，全面优化审核工作台页面的视觉和功能

**Architecture:** 只改一个文件 `review_workbench.html`。保留现有 REST API 调用和数据结构。视觉上使用 CSS 变量主题体系。按组件模块化新增/重写，不破坏现有数据加载逻辑。

**Tech Stack:** React 18 + Babel standalone (in-browser JSX), Jinja2 template with `{% raw %}` blocks

---

### Task 1: 添加辅助函数和常量

**Files:**
- Modify: `app/templates/review_workbench.html:5-55` (开头区域)

**Step 1: 在 `{% raw %}` 内，`const { useState... } = React;` 之后，添加按钮风格辅助函数**

```javascript
function btnStyle(variant, extra = {}) {
  const base = { border:"none", borderRadius:4, cursor:"pointer", fontWeight:600, padding:"6px 14px", fontSize:12, transition:"all 0.15s" };
  const variants = {
    accent: { background:"var(--accent-primary)", color:"#1a1a1a" },
    ghost: { background:"transparent", border:"1px solid var(--border-color)", color:"var(--ink-secondary)" },
    green: { background:"var(--signal-green)", color:"#fff" },
    red: { background:"var(--signal-red)", color:"#fff" },
  };
  return { ...base, ...(variants[variant]||{}), ...extra };
}
```

**Step 2: 统一 STATUS_COLOR 和 REVIEW_STATUSES**

将现有的 `REVIEW_STATUSES` 和局部 `colorMap` 合并为全局常量：

```javascript
const STATUS_COLOR = {
  pending: "var(--signal-gray)",
  confirmed: "var(--signal-green)",
  questionable: "var(--signal-amber)",
  rejected: "var(--signal-red)",
  nok: "var(--signal-red)",
};
const DIM_COLORS = STATUS_COLOR;
const REVIEW_STATUSES = [
  { value: "confirmed",    label: "确认/OK",  color: "var(--signal-green)" },
  { value: "questionable", label: "存疑",     color: "var(--signal-amber)" },
  { value: "rejected",     label: "驳回/NOK", color: "var(--signal-red)"   },
  { value: "pending",      label: "待审",     color: "var(--signal-gray)"  },
];
```

**Step 3: 写完后确认文件没有语法错误**

不必单独运行，等全写完后再验证。

---

### Task 2: 重写 MarkerLabel（圆形 + SVG 引线）

**Files:**
- Modify: `app/templates/review_workbench.html` (替换现有 MarkerLabel)

**Step 1: 替换现有 MarkerLabel 为参考文件实现**

关键变化：
- 形状从方形改为圆形（`borderRadius: "50%"`）
- 尺寸公式：`Math.round(Math.max(20, Math.min(32, 24 / Math.sqrt(Math.max(zoom, 0.15)))))`
- 字号公式：`Math.round(Math.max(9, Math.min(13, 10 / Math.sqrt(Math.max(zoom, 0.15)))))`
- 新增 SVG 引线：连接标记位置 `(cx, cy)` 到原始锚点 `(tx, ty)`，仅当两者距离 > size*0.6 时显示
- 选中态：scale(1.18) + 外发光 `0 0 0 4px var(--accent-dim)`
- 引线样式：选中时实线 strokeWidth=1.5，未选中虚线 strokeDasharray="4 3"

```javascript
function MarkerLabel({ dim, zoom, offsetX, offsetY, isSelected, onClick, onContextMenu, originalX, originalY }) {
  const cx = dim.anchor_x * zoom + offsetX;
  const cy = dim.anchor_y * zoom + offsetY;
  const tx = originalX * zoom + offsetX;
  const ty = originalY * zoom + offsetY;
  const size = Math.round(Math.max(20, Math.min(32, 24 / Math.sqrt(Math.max(zoom, 0.15)))));
  const fontSize = Math.round(Math.max(9, Math.min(13, 10 / Math.sqrt(Math.max(zoom, 0.15)))));
  const color = STATUS_COLOR[dim.review_status] || STATUS_COLOR.pending;
  const hasLeader = Math.hypot(cx - tx, cy - ty) > size * 0.6;

  return (
    <>
      {hasLeader && (
        <svg style={{ position:"absolute", inset:0, width:"100%", height:"100%",
                      pointerEvents:"none", zIndex:8, overflow:"visible" }}>
          <line x1={cx} y1={cy} x2={tx} y2={ty}
            stroke={color} strokeWidth={isSelected ? 1.5 : 1}
            strokeDasharray={isSelected ? "none" : "4 3"}
            opacity={isSelected ? 0.85 : 0.45} />
          <circle cx={tx} cy={ty} r={isSelected ? 3.5 : 2.5}
            fill={color} opacity={isSelected ? 1 : 0.65} />
        </svg>
      )}
      <div
        data-marker="true"
        onClick={e => { e.stopPropagation(); onClick(dim.id); }}
        onContextMenu={e => { e.preventDefault(); e.stopPropagation(); onContextMenu && onContextMenu(e, dim); }}
        style={{
          position:"absolute", left: cx, top: cy,
          width: size, height: size,
          transform: isSelected ? "translate(-50%,-50%) scale(1.18)" : "translate(-50%,-50%)",
          backgroundColor: color,
          color:"#fff",
          display:"flex", alignItems:"center", justifyContent:"center",
          fontFamily:"var(--font-mono)", fontSize, fontWeight:700,
          borderRadius: "50%",
          border: isSelected ? "2.5px solid var(--accent-primary)" : "2px solid rgba(255,255,255,0.55)",
          cursor:"pointer", zIndex: isSelected ? 25 : 10,
          boxShadow: isSelected
            ? "0 0 0 4px var(--accent-dim), 0 3px 10px rgba(0,0,0,0.3)"
            : "0 1px 5px rgba(0,0,0,0.25)",
          transition:"transform 0.15s, box-shadow 0.15s",
        }}
        title={`#${dim.sequence} ${dim.value}`}
      >
        {dim.sequence}
      </div>
    </>
  );
}
```

**Step 2: 更新 DrawingCanvas 中 MarkerLabel 的调用**

传新增的 `originalX`/`originalY` prop：

```javascript
{dim => (
  <MarkerLabel key={dim.id}
    dim={{ ...dim, anchor_x: dim.anchor_x+dim._gx, anchor_y: dim.anchor_y+dim._gy }}
    originalX={dim.anchor_x} originalY={dim.anchor_y}
    zoom={zoom} offsetX={offset.x} offsetY={offset.y}
    isSelected={dim.id === selectedDimId}
    onClick={onSelectDim}
    onContextMenu={!readOnly ? onContextMenuDim : undefined}
  />
)}
```

---

### Task 3: 增强 DrawingCanvas（缩放工具栏 + 指引线 + HintBar）

**Files:**
- Modify: `app/templates/review_workbench.html` (DrawingCanvas 组件)

**Step 1: 替换缩放工具栏**

从简单文本改为带 SVG 图标的工具栏：

```javascript
<div style={{ position:"absolute", top:10, right:10, zIndex:30,
  display:"flex", alignItems:"center", gap:4,
  background:"rgba(255,255,255,0.85)", border:"1px solid var(--border-color)",
  borderRadius:5, padding:"3px 6px", backdropFilter:"blur(4px)" }}>
  <button onClick={e=>{e.stopPropagation(); fitScreen();}} style={iconBtn} title="适应窗口">
    <svg width="13" height="13" viewBox="0 0 13 13" fill="none" stroke="currentColor" strokeWidth="1.5">
      <path d="M1 4V1h3M9 1h3v3M12 9v3h-3M4 12H1V9"/>
    </svg>
  </button>
  <div style={{ width:1, height:14, background:"var(--border-color)" }} />
  <span style={{ fontSize:11, fontFamily:"var(--font-mono)", color:"var(--ink-secondary)", minWidth:38, textAlign:"center" }}>
    {Math.round(zoom*100)}%
  </span>
  <div style={{ width:1, height:14, background:"var(--border-color)" }} />
  <button onClick={e=>{e.stopPropagation();}} style={iconBtn} title="双击图纸适应窗口 · 滚轮缩放 · 拖拽平移">?</button>
</div>
```

添加 `iconBtn` 常量（在组件外）：

```javascript
const iconBtn = {
  background:"transparent", border:"none", color:"var(--ink-secondary)",
  cursor:"pointer", padding:"2px 4px", borderRadius:3, display:"flex", alignItems:"center",
  fontSize:11,
};
```

**Step 2: 添加低缩放指引线（在 MarkerLabel 之前渲染）**

```javascript
{showGuides && (
  <svg style={{ position:"absolute", inset:0, width:"100%", height:"100%", pointerEvents:"none", zIndex:5 }}>
    {adjustedDims.filter(d => Math.abs(d._gx)>2||Math.abs(d._gy)>2).map(d => (
      <line key={`g-${d.id}`}
        x1={(d.anchor_x+d._gx)*zoom+offset.x} y1={(d.anchor_y+d._gy)*zoom+offset.y}
        x2={d.anchor_x*zoom+offset.x} y2={d.anchor_y*zoom+offset.y}
        stroke="var(--ink-disabled)" strokeWidth={0.8} strokeDasharray="3 3" opacity={0.5}
      />
    ))}
  </svg>
)}
```

**Step 3: 添加 HintBar（容器底部）**

```javascript
function HintBar() {
  const [visible, setVisible] = React.useState(true);
  React.useEffect(() => {
    const t = setTimeout(() => setVisible(false), 3000);
    return () => clearTimeout(t);
  }, []);
  if (!visible) return null;
  return (
    <div style={{
      position:"absolute", bottom:10, left:"50%", transform:"translateX(-50%)",
      fontSize:10, color:"var(--ink-disabled)", pointerEvents:"none",
      background:"var(--bg-elevated)", padding:"3px 10px", borderRadius:3,
      border:"1px solid var(--border-color)",
      animation:"fadeIn 0.3s ease", transition:"opacity 0.5s",
    }}>
      滚轮缩放 · 拖拽平移 · 双击适应 · 右键标注改状态
    </div>
  );
}
```

---

### Task 4: 添加 ReviewProgress 组件

**Files:**
- Modify: `app/templates/review_workbench.html` (在 MarkerLabel 附近，组件区域)

```javascript
function ReviewProgress({ dims }) {
  const total = dims.length;
  const confirmed    = dims.filter(d=>d.review_status==="confirmed").length;
  const questionable = dims.filter(d=>d.review_status==="questionable").length;
  const rejected     = dims.filter(d=>d.review_status==="rejected").length;
  const pending      = dims.filter(d=>d.review_status==="pending").length;
  const done = confirmed + questionable + rejected;
  const pct = total > 0 ? Math.round(done/total*100) : 0;

  return (
    <div style={{ display:"flex", alignItems:"center", gap:10 }}>
      <div style={{ display:"flex", gap:4 }}>
        {[
          [confirmed, "var(--signal-green)", "✓"],
          [questionable, "var(--signal-amber)", "?"],
          [rejected, "var(--signal-red)", "✕"],
          [pending, "var(--ink-disabled)", "·"],
        ].filter(([c]) => c > 0).map(([count, color, icon], i) => (
          <span key={i} style={{
            display:"inline-flex", alignItems:"center", gap:3,
            fontSize:11, fontFamily:"var(--font-mono)",
            background: "var(--bg-elevated)",
            border: "1px solid var(--border-color)",
            borderRadius:3, padding:"1px 6px", color,
          }}>
            {icon} {count}
          </span>
        ))}
      </div>
      <div className="progress-track" style={{ height:4, width:80 }}>
        <div className="progress-fill" style={{
          width: pct + "%",
          background: pct===100 ? "var(--signal-green)" : "var(--accent-primary)",
        }} />
      </div>
      <span style={{ fontSize:10, fontFamily:"var(--font-mono)", color: pct===100?"var(--signal-green)":"var(--ink-secondary)", minWidth:28 }}>
        {pct}%
      </span>
    </div>
  );
}
```

---

### Task 5: 添加 Stamp 组件

```javascript
function Stamp({ type, date }) {
  const ok = type === "approved";
  return (
    <div style={{
      display:"inline-flex", flexDirection:"column", alignItems:"center", gap:3,
      border:`2px solid ${ok ? "var(--signal-green)" : "var(--signal-red)"}`,
      borderRadius:4, padding:"10px 28px",
      color: ok ? "var(--signal-green)" : "var(--signal-red)",
      transform:`rotate(${ok ? -12 : 12}deg)`,
      animation:"stampIn 0.45s cubic-bezier(0.34,1.56,0.64,1)",
      opacity:0.88, userSelect:"none",
      fontFamily:"var(--font-display)", letterSpacing:"0.12em",
    }}>
      <div style={{ fontSize:28, fontWeight:700 }}>{ok ? "✓" : "✕"}</div>
      <div style={{ fontSize:11, fontWeight:700 }}>{ok ? "APPROVED" : "REJECTED"}</div>
      {date && <div style={{ fontSize:9, color:"var(--ink-secondary)", letterSpacing:"0.05em" }}>{date}</div>}
    </div>
  );
}
```

---

### Task 6: 添加 AIBadge 组件

```javascript
function AIBadge({ suggestion }) {
  const [expanded, setExpanded] = useState(false);
  const [result, setResult] = useState(suggestion);

  return (
    <div style={{
      background:"var(--accent-dim)", border:"1px solid rgba(201,127,0,0.25)",
      borderRadius:4, padding:"6px 10px", fontSize:11,
    }}>
      <div style={{ display:"flex", alignItems:"center", gap:6, cursor:"pointer" }} onClick={() => setExpanded(e=>!e)}>
        <span style={{ color:"var(--accent-primary)", fontWeight:700, fontSize:10, letterSpacing:"0.06em" }}>AI</span>
        <span style={{ color:"var(--ink-secondary)", flex:1 }}>{result}</span>
      </div>
    </div>
  );
}
```

---

### Task 7: 添加 ConclusionBar 组件

```javascript
function ConclusionBar({ dims, versionInfo, onConfirm, notes, onNotesChange }) {
  const [showConfirm, setShowConfirm] = useState(null);
  const counts = useMemo(() => ({
    total: dims.length,
    confirmed: dims.filter(d=>d.review_status==="confirmed").length,
    questionable: dims.filter(d=>d.review_status==="questionable").length,
    pending: dims.filter(d=>d.review_status==="pending").length,
    rejected: dims.filter(d=>d.review_status==="rejected").length,
  }), [dims]);

  if (versionInfo?.confirm_result) {
    return (
      <div style={{ borderTop:"1px solid var(--border-color)", padding:20, display:"flex", justifyContent:"center" }}>
        <Stamp type={versionInfo.confirm_result} date={versionInfo.confirmed_at || "2026-05-01"} />
      </div>
    );
  }

  return (
    <div style={{ borderTop:"1px solid var(--border-strong)", flexShrink:0, padding:12 }}>
      <div style={{ display:"flex", gap:12, marginBottom:10, fontSize:10, fontFamily:"var(--font-mono)" }}>
        {[["待审",counts.pending,"var(--ink-disabled)"],["确认",counts.confirmed,"var(--signal-green)"],["存疑",counts.questionable,"var(--signal-amber)"],["NOK",counts.rejected,"var(--signal-red)"]]
          .filter(([_,v]) => v > 0)
          .map(([l,v,c]) => (
            <span key={l} style={{ color:c }}>{l} {v}</span>
          ))}
        <span style={{ marginLeft:"auto", color:"var(--ink-disabled)" }}>共 {counts.total} 条</span>
      </div>
      <textarea value={notes} onChange={e=>onNotesChange(e.target.value)}
        placeholder="审核备注…" rows={2} style={{
          width:"100%", padding:"6px 8px", background:"var(--bg-canvas)",
          border:"1px solid var(--border-color)", borderRadius:3,
          color:"var(--ink)", fontSize:11, outline:"none", resize:"none", marginBottom:8,
        }}
      />
      <div style={{ display:"flex", gap:6 }}>
        <button onClick={()=>setShowConfirm("approved")} style={btnStyle("green",{flex:1,fontSize:12})}>✓ 通过</button>
        <button onClick={()=>setShowConfirm("rejected")} style={btnStyle("red",{flex:1,fontSize:12})}>✕ 驳回</button>
      </div>
      {showConfirm && (
        <div style={{ position:"fixed", inset:0, zIndex:300, background:"rgba(0,0,0,0.55)", display:"flex", alignItems:"center", justifyContent:"center" }} onClick={()=>setShowConfirm(null)}>
          <div style={{ background:"var(--bg-elevated)", borderRadius:8, padding:24, width:340, border:"1px solid var(--border-strong)", boxShadow:"var(--shadow-card)" }} onClick={e=>e.stopPropagation()}>
            <div style={{ fontSize:14, fontWeight:700, marginBottom:10, color:"var(--ink)" }}>
              确认{showConfirm==="approved"?"通过":"驳回"}此版本？
            </div>
            <div style={{ fontSize:12, color:"var(--ink-secondary)", marginBottom:16, lineHeight:1.6 }}>
              {showConfirm==="approved" && counts.pending > 0 && (
                <div style={{ background:"rgba(220,38,38,0.08)", border:"1px solid var(--signal-amber)", borderRadius:4, padding:"6px 10px", marginBottom:10, color:"var(--signal-amber)", fontSize:11, fontWeight:600 }}>
                  ⚠ 仍有 {counts.pending} 条标注处于待审状态，确认通过将忽略这些标注。
                </div>
              )}
              当前待审标注 <strong style={{color:"var(--signal-amber)"}}>{counts.pending}</strong> 条。
              {showConfirm==="approved" ? "通过后标注状态将被锁定。" : "驳回后版本将被标记为不合格。"}
            </div>
            <div style={{ display:"flex", gap:8, justifyContent:"flex-end" }}>
              <button onClick={()=>setShowConfirm(null)} style={btnStyle("ghost")}>取消</button>
              <button onClick={()=>{ onConfirm(showConfirm, notes); setShowConfirm(null); }} style={btnStyle(showConfirm==="approved"?"green":"red")}>确认提交</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
```

---

### Task 8: 构建 PanelA（右侧集成面板）

**Files:**
- Modify: `app/templates/review_workbench.html` (在 App 之前，替换现有的 DimensionList/DimensionDetail/DiscussionThread)

PanelA 集成筛选、列表、详情、讨论、结论栏于一体。参考 `llm_drawing_review.html` 的 PanelA 实现，但将消息数据改为通过 API 获取（保留现有 DiscussionThread 的数据流）。

```javascript
function PanelA({ dims, showAI, selectedDimId, onSelectDim, onStatusChange, versionInfo, onConfirm, readOnly }) {
  const [filter, setFilter] = useState("all");
  const [messages, setMessages] = useState({});
  const [text, setText] = useState("");
  const [notes, setNotes] = useState("");
  const [sending, setSending] = useState(false);

  const filtered = filter === "all" ? dims : dims.filter(d => d.review_status === filter);
  const selectedDim = dims.find(d => d.id === selectedDimId);
  const msgs = selectedDim ? (messages[selectedDim.id] || []) : [];

  // Load messages when a dim is selected
  useEffect(() => {
    if (!selectedDimId) return;
    fetch(`/api/dimensions/${selectedDimId}/messages`).then(r => r.json()).then(data => {
      setMessages(prev => ({ ...prev, [selectedDimId]: data }));
    });
  }, [selectedDimId]);

  const handleSend = async () => {
    if (!text.trim() || sending || !selectedDimId) return;
    setSending(true);
    try {
      const resp = await fetch(`/api/dimensions/${selectedDimId}/messages`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ author: "审核员", content: text.trim() }),
      });
      if (resp.ok) { const m = await resp.json(); setMessages(prev => ({...prev, [selectedDimId]: [...(prev[selectedDimId]||[]), m]})); setText(""); }
    } finally { setSending(false); }
  };

  const statusConfig = {
    pending:      { label:"待审",  color:"var(--signal-gray)" },
    confirmed:    { label:"确认",  color:"var(--signal-green)" },
    questionable: { label:"存疑",  color:"var(--signal-amber)" },
    rejected:     { label:"NOK",   color:"var(--signal-red)" },
  };

  return (
    <div style={{ display:"flex", flexDirection:"column", height:"100%", overflow:"hidden" }}>
      {/* Filter bar */}
      <div style={{ display:"flex", alignItems:"center", gap:0, borderBottom:"1px solid var(--border-color)", padding:"0 12px", flexShrink:0 }}>
        {[["all","全部"],["pending","待审"],["confirmed","确认"],["questionable","存疑"],["rejected","NOK"]].map(([v,l]) => (
          <button key={v} onClick={() => { setFilter(v); onSelectDim && onSelectDim(null); }} style={{
            padding:"7px 10px", background:"transparent", border:"none",
            borderBottom:`2px solid ${filter===v?"var(--accent-primary)":"transparent"}`,
            color: filter===v ? "var(--accent-primary)" : "var(--ink-secondary)",
            cursor:"pointer", fontSize:11, transition:"all 0.15s",
          }}>{l}</button>
        ))}
        <span style={{ marginLeft:"auto", fontSize:10, fontFamily:"var(--font-mono)", color:"var(--ink-disabled)" }}>
          {filtered.length}/{dims.length}
        </span>
      </div>

      {/* Dim list */}
      <div style={{ flex:"0 0 auto", maxHeight:220, overflowY:"auto" }}>
        {filtered.length === 0
          ? <div style={{ padding:20, textAlign:"center", color:"var(--ink-disabled)", fontSize:11 }}>暂无标注</div>
          : filtered.map(d => (
            <div key={d.id} onClick={() => onSelectDim(d.id)} style={{
              display:"flex", alignItems:"center", gap:8,
              padding:"7px 12px", cursor:"pointer",
              background: d.id === selectedDimId ? "var(--bg-selected)" : "transparent",
              borderBottom:"1px solid var(--border-color)", transition:"background 0.1s",
            }}>
              <span style={{
                width:20, height:20, borderRadius:3, flexShrink:0,
                background: STATUS_COLOR[d.review_status] || STATUS_COLOR.pending,
                display:"flex", alignItems:"center", justifyContent:"center",
                fontSize:9, fontWeight:700, color:"#fff", fontFamily:"var(--font-mono)",
              }}>{d.sequence}</span>
              <span style={{ fontFamily:"var(--font-mono)", fontSize:12, flex:1, color:"var(--ink)" }}>{d.value}</span>
              {d.message_count > 0 && (
                <span style={{ fontSize:9, background:"var(--accent-primary)", color:"#1a1a1a",
                  borderRadius:2, minWidth:15, height:15,
                  display:"flex", alignItems:"center", justifyContent:"center", fontWeight:700,
                }}>{d.message_count}</span>
              )}
              {showAI && d.ai_suggestion && <span style={{ fontSize:9, color:"var(--accent-primary)", fontWeight:700 }}>AI</span>}
            </div>
          ))
        }
      </div>

      {/* Divider */}
      <div style={{ height:1, background:"var(--border-strong)", flexShrink:0 }} />

      {/* Detail area */}
      <div style={{ flex:1, overflowY:"auto" }}>
        {!selectedDim ? (
          <div style={{ padding:24, textAlign:"center", color:"var(--ink-disabled)", fontSize:11 }}>选择一个标注</div>
        ) : (
          <div style={{ padding:12 }} className="fade-in">
            <div style={{ display:"flex", alignItems:"baseline", gap:8, marginBottom:12 }}>
              <span style={{ fontFamily:"var(--font-mono)", fontSize:10, color:"var(--ink-disabled)" }}>#{String(selectedDim.sequence).padStart(2,"0")}</span>
              <span style={{ fontFamily:"var(--font-mono)", fontSize:15, fontWeight:700, color:"var(--ink)" }}>{selectedDim.value}</span>
            </div>
            <div style={{ display:"grid", gridTemplateColumns:"1fr 1fr", gap:8, marginBottom:12 }}>
              {[["类型",selectedDim.dim_type],["来源",selectedDim.source],["视图",selectedDim.view_name||"—"],["坐标",`${Math.round(selectedDim.anchor_x)},${Math.round(selectedDim.anchor_y)}`]].map(([l,v])=>(
                <div key={l}>
                  <div style={{ fontSize:9, color:"var(--ink-disabled)", textTransform:"uppercase", letterSpacing:"0.06em", marginBottom:2 }}>{l}</div>
                  <div style={{ fontSize:11, fontFamily:"var(--font-mono)", color:"var(--ink)" }}>{v}</div>
                </div>
              ))}
            </div>
            {showAI && selectedDim.ai_suggestion && <div style={{ marginBottom:10 }}><AIBadge suggestion={selectedDim.ai_suggestion} /></div>}
            {/* Status buttons */}
            {!readOnly && (
              <div style={{ display:"flex", gap:4, marginBottom:12 }}>
                {[["confirmed","确认","var(--signal-green)"],["questionable","存疑","var(--signal-amber)"],["rejected","NOK","var(--signal-red)"],["pending","待审","var(--signal-gray)"]].map(([s,l,c])=>(
                  <button key={s} onClick={() => onStatusChange(selectedDim.id, s)} style={{
                    flex:1, padding:"5px 0", border:`1px solid ${selectedDim.review_status===s?c:"var(--border-color)"}`,
                    borderRadius:3, cursor:"pointer", fontSize:11, fontWeight:600,
                    background: selectedDim.review_status===s ? c : "transparent",
                    color: selectedDim.review_status===s ? ((s==="confirmed"||s==="rejected")?"#fff":"#1a1a1a") : "var(--ink-secondary)",
                    transition:"all 0.15s",
                  }}>{l}</button>
                ))}
              </div>
            )}
            {/* Discussion */}
            <div style={{ fontSize:10, color:"var(--ink-secondary)", textTransform:"uppercase", letterSpacing:"0.06em", marginBottom:6 }}>讨论</div>
            <div style={{ maxHeight:120, overflowY:"auto", marginBottom:8 }}>
              {msgs.length === 0
                ? <div style={{ color:"var(--ink-disabled)", fontSize:11, padding:"4px 0" }}>暂无讨论</div>
                : msgs.map(m => (
                  <div key={m.id} style={{ background:"var(--bg-elevated)", borderRadius:4, padding:"6px 8px", marginBottom:5 }}>
                    <div style={{ display:"flex", justifyContent:"space-between", marginBottom:2 }}>
                      <span style={{ fontSize:10, fontWeight:700, color:"var(--accent-primary)" }}>{m.author}</span>
                      <span style={{ fontSize:9, color:"var(--ink-disabled)" }}>{m.created_at}</span>
                    </div>
                    <div style={{ fontSize:11, color:"var(--ink)", lineHeight:1.5 }}>{m.content}</div>
                  </div>
                ))
              }
            </div>
            {!readOnly && (
              <div style={{ display:"flex", gap:6 }}>
                <input value={text} onChange={e=>setText(e.target.value)}
                  onKeyDown={e=>{ if(e.key==="Enter"&&!e.shiftKey&&text.trim()){ e.preventDefault(); handleSend(); } }}
                  placeholder="发送评论 (Enter)" style={{
                    flex:1, padding:"5px 8px", background:"var(--bg-canvas)",
                    border:"1px solid var(--border-color)", borderRadius:3,
                    color:"var(--ink)", fontSize:11, outline:"none",
                  }}
                />
                <button onClick={handleSend} disabled={sending||!text.trim()} style={btnStyle("accent",{fontSize:11,padding:"5px 10px",opacity:(sending||!text.trim())?0.5:1})}>发</button>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Conclusion bar */}
      <ConclusionBar dims={dims} versionInfo={versionInfo} onConfirm={onConfirm} notes={notes} onNotesChange={setNotes} />
    </div>
  );
}
```

注意：每次 selectedDimId 变化时，`useEffect` 会加载该标注的消息。消息状态在 `messages` 对象中缓存（keyed by dimId），切换标注时不会丢失已加载的消息。

---

### Task 9: 重写 App 组件，集成所有新组件

**Step 1: 重写 App 组件**

整合 ReviewProgress 到导航栏 actions 区域，用 PanelA 替换旧的右面板组件串接。

App 组件改动：
- 导航栏 actions 区域新增 `ReviewProgress`（在版本切换下拉之前）
- 右侧面板替换为 `<PanelA>` 一个组件
- 结论提交处理：调用 `PATCH /api/versions/{version_id}/conclusion`
- 保留现有数据加载 `useEffect`（versions、drawings、dims）
- 保留现有版本切换逻辑（`handleVersionChange`）

```javascript
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

  // ...existing useEffect blocks for data loading (keep as-is)...

  const handleConfirm = async (result, notes) => {
    await fetch(`/api/versions/${currentVersionId}/conclusion`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ result, notes }),
    });
    setVersionInfo(prev => ({ ...prev, confirm_result: result, confirmed_at: new Date().toISOString() }));
  };

  const isReadOnly = versionInfo?.confirm_result != null;

  return (
    <div style={{ height: "100%", display: "flex", flexDirection: "column" }}>
      <AppShell
        breadcrumbs={[{ label: "零件列表", href: "/parts/" }, { label: "审核工作台" }]}
        actions={
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            {dims.length > 0 && <ReviewProgress dims={dims} />}
            {versionInfo && <StatusDot status={versionInfo.status} pulse={versionInfo.status === "processing"} />}
            <select value={currentVersionId} onChange={e => handleVersionChange(Number(e.target.value))}
              style={{ padding: "4px 8px", background: "var(--bg-elevated)", border: "1px solid var(--border-color)", borderRadius: 2, color: "var(--ink)", fontSize: 12, outline: "none", cursor: "pointer", fontFamily: "var(--font-mono)" }}>
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
          <div style={{ width: 320, borderLeft: "1px solid var(--border-color)", display: "flex", flexDirection: "column", overflow: "hidden", background: "var(--bg-surface)" }}>
            <PanelA
              dims={dims} showAI={true}
              selectedDimId={selectedDimId}
              onSelectDim={setSelectedDimId}
              onStatusChange={handleStatusChange}
              versionInfo={versionInfo}
              onConfirm={handleConfirm}
              readOnly={isReadOnly}
            />
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
```

**Step 2: 确认渲染入口不变**

```javascript
ReactDOM.createRoot(document.getElementById("root")).render(<App />);
```

---

### Task 10: 验证页面渲染和功能

**Files:**
- Browser: `http://localhost:8000/parts/4/versions/4/review`

**Step 1: 启动服务器**

```bash
cd /Users/rongjie/llm_projects/llm_drawing_review
uvicorn app.main:app --reload --port 8000
```

**Step 2: 在浏览器中加载页面**

验证以下功能：
1. 页面加载无 Babel 语法错误（打开 DevTools Console 检查）
2. 图纸图片正常加载
3. 标注标记为圆形，带引线
4. 缩放/平移/双击适应正常
5. 缩放工具栏显示百分比和SVG按钮
6. HintBar 显示后自动淡出
7. 右侧面板宽度为 320px
8. 筛选标签切换正常，显示计数
9. 标注列表显示序号方块、值、状态圆点、消息角标
10. 选择标注后显示详情（元信息网格、状态按钮、AI 建议）
11. 讨论功能：加载消息、发送消息
12. 结论栏：统计计数、备注输入、通过/驳回弹窗
13. 右键标注弹出上下文菜单，改状态后立即更新
14. 版本切换菜单正常
15. 导航栏显示 ReviewProgress 状态药丸和进度条
