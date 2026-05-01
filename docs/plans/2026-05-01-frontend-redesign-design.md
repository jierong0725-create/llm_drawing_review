# 前端页面优化重设计

> 日期：2026-05-01
> 方向：参考模版移植 · 浅色主题 · 方案 B（保留共享文件）

## 一、文件结构

### 删除
- `app/static/jsx/design_tokens.jsx`
- `app/static/jsx/app_shell.jsx`
- `app/static/jsx/status_dot.jsx`
- `app/static/jsx/stamp.jsx`
- `app/static/jsx/data_table.jsx`

### 新增
- `app/static/jsx/shared.jsx` — 跨页共享组件：AppShell、StatusDot

### 保留
- `app/static/jsx/marker_label.jsx` — 工作台专用，不变

### 更新
- `app/templates/spa.html` — 浅色主题 CSS 变量 + 加载 shared.jsx
- `app/templates/parts_list.html` — 全量重写为 JSX 语法
- `app/templates/review_workbench.html` — 全量重写为 JSX 语法

---

## 二、主题系统

浅色主题 CSS 变量直接挂 `:root`，不需要主题切换。

```css
--bg-canvas: #f1f3f7
--bg-surface: #ffffff
--bg-elevated: #f8f9fc
--bg-hover: rgba(0,0,0,0.03)
--bg-selected: rgba(220,130,0,0.07)
--signal-green: #16a34a
--signal-red: #dc2626
--signal-amber: #d97706
--signal-gray: #6b7280
--signal-blue: #2563eb
--accent-primary: #c97f00
--accent-hover: #a66800
--accent-dim: rgba(201,127,0,0.12)
--ink: #1e2635
--ink-secondary: #4b5668
--ink-disabled: #9ca3af
--border-color: #e2e6ed
--border-strong: #cbd2dc
--shadow-card: 0 2px 12px rgba(0,0,0,0.10)
```

字体、间距栅格、圆角（2px）与原设计一致。

---

## 三、shared.jsx

包含两个组件，挂载到 `window`：

**AppShell**
- 顶部导航栏高度 36px
- SVG 图标 + `DRAWREV` 品牌文字（accent-primary 色）
- breadcrumbs 面包屑
- 右侧 actions 插槽

**StatusDot**
- 7×7px 方点（border-radius: 2px）
- 支持 pulse 动画（processing 状态）
- 状态：ready / processing / confirmed / pending / questionable / rejected

---

## 四、零件列表页（parts_list.html）

### 4.1 汇总统计条
紧贴 AppShell 下方，横向排列 4 个指标：

| 指标 | 数据来源 |
|------|----------|
| 全部零件 | `parts.length` |
| 待审标注 | `sum(pending_count)` |
| 可审核 | `status === "ready"` 的零件数 |
| 处理中 | `status === "processing"` 的零件数 |

### 4.2 筛选栏
- 左：带搜索图标的文本输入框
- 右：分段控件（全部 / 就绪 / 处理中 / 已确认 / 待上传）
- 最右：`x / total 条` 计数

### 4.3 表格列
图号 · 零件名称 · 当前版本 · 状态 · 待审/总计 · 审核进度（进度条+%） · 创建时间

进度条：`(total - pending) / total`，100% 时绿色，否则 accent-primary。

---

## 五、审核工作台页（review_workbench.html）

### 5.1 标注状态（4 种）

| 值 | 显示名 | 颜色 |
|----|--------|------|
| `pending` | 待审 | signal-gray |
| `confirmed` | 确认 | signal-green |
| `questionable` | 存疑 | signal-amber |
| `rejected` | 驳回 | signal-red |

后端 PATCH `/api/dimensions/:id` 的 `review_status` 枚举需增加 `rejected`。

### 5.2 右键上下文菜单
- 触发：右键点击画布上的标注圆点
- 显示：标注序号 + 当前值，4 个状态选项（排除当前状态）
- 关闭：点击任意其他区域
- 位置：自动检测视口边界，防止溢出

### 5.3 移除
- `ConclusionBar`（版本通过/驳回/印章）整体删除
- `Stamp` 组件不再使用

### 5.4 画布区
- 底色：`#e8eaed`（浅灰，与白底工程图纸形成边界感）
- 标注圆点 `confirmed` 状态在浅色底下使用 `signal-green: #16a34a`，对比度充足

### 5.5 侧栏布局（从上到下）
1. 标注列表（含筛选 tab：全部/待审/确认/存疑/驳回）
2. 标注详情（序号、值、类型、来源、视图、坐标、状态按钮）
3. 讨论线程
