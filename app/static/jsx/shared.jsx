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
