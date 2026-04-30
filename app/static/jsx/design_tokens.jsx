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
