# 工程图纸审核系统 · 工业精密风重设计

> 设计方向：A — 工业精密风（Pentagram 信息建筑 + DIN 工程标准）
> 日期：2026-04-30

## 一、设计系统

### 色彩

```
底盘（背景层级）
  Canvas 深灰   #1e2127    主背景
  Surface 中灰  #282c34    卡片、面板、弹窗
  Elevated 浅灰 #323741    悬浮层（tooltip、下拉菜单）

信号色（工业信号灯语义 — 色盲友好：颜色+填充双编码）
  通过/确认      #2ecc71    绿
  驳回/危险      #e74c3c    红
  存疑/待审      #f39c12    琥珀黄
  待处理/中性    #6b7280    灰

Accent
  Primary        #f0a500    按钮、选中态、关键数据高亮
  Primary-hover  #f5c842    悬浮态

文字
  Ink            #e8e8e8    深底正文（非纯白，护眼）
  Secondary      #9ca3af    辅助信息
  Disabled       #555b66    不可用/占位
```

### 字体

| 角色 | 字体 | 理由 |
|------|------|------|
| Display | DIN Alternate / "Helvetica Neue" condensed | 德国工业标准字体 |
| Body/Data | SF Mono / JetBrains Mono / monospace | 等宽数字，尺寸值自然对齐 |
| UI | `-apple-system, system-ui, sans-serif` | 小字号渲染最清晰 |

### 间距与形状

- 间距栅格：4px 基准（4, 8, 12, 16, 24, 32, 48）
- 圆角：2px（工业感小圆角，不用 Material 的 8px）
- 边框：1px solid #3a3f4a
- 阴影：几乎不用，用 1px 边框 + 色差区分层级

## 二、信息架构

从三级（列表→详情→审核）精简为两极：

```
零件列表（Dashboard）
  └── 审核工作台（唯一工作面，支持版本切换）
```

- **去掉零件详情页**——其信息并入审核工作台的版本下拉和侧栏
- **审核结论只在审核工作台做**——消除重复操作入口
- **审核工作台支持版本切换**——历史版本自动只读
- **零件列表升级为 Dashboard**——每行显示待审数/总数

## 三、页面布局

### 零件列表（Dashboard）

- 真表格（非 Material 卡片），每行 40px 高
- 列：图号 | 名称 | 当前版本 | 状态 | 待审/总数 | 操作
- 状态用信号灯色点（绿/黄/灰），不是彩色标签
- 搜索 + 状态筛选栏
- 新增零件弹窗

### 审核工作台

```
┌── 图纸区（flex: 6）──────┬── 审核面板（flex: 4, min-w: 380, max-w: 500）──┐
│ 图纸标签切换              │ 标注列表（筛选 + 虚拟滚动）                    │
│ 图纸图片 + pan/zoom       │ 选中标注详情 + 状态切换                        │
│ 标注铭牌标签 + SVG 引导线 │ 讨论区（消息列表 + 输入框）                    │
│ 工具栏（添加/适应/撤销）  │ 审核结论盖章                                    │
└──────────────────────────┴─────────────────────────────────────────────────┘
```

- 顶栏：面包屑 + 版本下拉切换
- 历史版本只读模式（隐藏审核按钮和讨论框）

### 审核结论盖章

- 通过 = 绿色边框方章，驳回 = 红色边框方章
- 模拟真实盖章的微旋转（rotate ~15deg）
- 盖章后页面进入只读态，结论不可逆

## 四、交互细节

### 标注铭牌标签

- 缩略态：小方块 + 数字（非圆点），填充色 + 边框色双编码
- 选中态：展开小卡片显示尺寸值和类型，细引导线连到图纸锚点
- 重叠时：排斥算法分散 + SVG 引导线

### 版本切换

- 下拉列出所有版本，当前版本可读写，历史版本只读
- 切换版本时保留当前图纸编号的选中状态

## 五、技术架构

### 方案

- 后端：FastAPI 不变，路由改为返回 JSON + SPA 壳
- 前端：React 18.3 + Babel standalone（CDN pinned 版本）
- Jinja2 退化为最简 HTML 壳：`<!DOCTYPE>` + CDN + `<div id="root">`
- 每个页面一个 HTML，共享组件抽到 `static/jsx/` 下

### 文件结构

```
app/
├── static/
│   ├── jsx/                    ← 共享 React 组件
│   │   ├── design_tokens.jsx    # :root 变量 + 全局样式
│   │   ├── app_shell.jsx        # 顶栏导航 + 面包屑
│   │   ├── data_table.jsx       # 通用工程表格
│   │   ├── status_dot.jsx       # 信号灯指示器
│   │   └── stamp.jsx            # 审核盖章
│   ├── drawings/               ← 生成的 JPG（drawing_id 目录）
│   └── uploads/                ← 原 PDF 持久存储（新增）
├── templates/                  ← Jinja2 壳
│   └── spa.html                # 共用 SPA 挂载页
├── routers/
│   ├── parts.py                ← API 返回 JSON，页面返回 spa.html
│   └── review.py
└── services/                   ← 不变
```

### React 组件树

```
零件列表页
├── AppShell
├── PartTable → StatusDot
├── SearchFilter
└── NewPartModal

审核工作台
├── AppShell
├── WorkbenchHeader → VersionDropdown
├── DrawingCanvas
│   ├── DrawingTabs
│   ├── CanvasViewport
│   └── MarkerLabel
├── ReviewPanel
│   ├── DimensionList
│   ├── DimensionDetail
│   ├── DiscussionThread
│   └── MessageInput
└── ConclusionStamp
```

### 技术约束（huashu-design 红线）

1. style 对象名必须唯一（如 `canvasStyles`，不能用 `styles`）
2. 多 script 标签组件用 `Object.assign(window, {...})` 导出
3. 不用 `scrollIntoView`
4. Babel standalone + React 版本必须 pinned

## 六、与现有计划的整合

已有的 `2026-04-30-review-page-fixes-design.md` 中的修复点（图片加载失败兜底、标注排斥算法）将作为本次重设计的一部分一并实现，不单独修。
