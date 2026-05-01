# 审核工作台页面优化设计

## 背景

对 `review_workbench.html` 进行全面优化，视觉和功能对齐参考设计文件 `llm_drawing_review.html`。只改一个文件，保留现有 API 调用和数据结构。

## 架构

```
App
 ├─ ThemeRoot
 ├─ AppShell (shared.jsx, 不动)
 ├─ 导航栏 actions
 │   └─ ReviewProgress        ← 新增：状态药丸 + 进度条
 │   └─ VersionSelector       ← 已有
 ├─ 主体区域 (flex row)
 │   ├─ 左侧画布区
 │   │   ├─ DrawingTabs       ← 不动
 │   │   └─ DrawingCanvas     ← 增强
 │   │       └─ MarkerLabel × N  ← 重写
 │   └─ 右侧面板 (320px)
 │       └─ PanelA            ← 新建
 │           ├─ Filter tabs
 │           ├─ Dim list (含消息角标 + AI 标记)
 │           ├─ Dim detail (含 AIBadge)
 │           ├─ Discussion
 │           └─ ConclusionBar (底部固定)
 └─ ContextMenu               ← 已有
```

## 各节设计

### 画布区

**MarkerLabel 重写**：圆形标记 + SVG 引线连接到原始锚点位置，尺寸公式 `24/Math.sqrt(max(zoom,0.15))`，选中态外发光 + scale(1.18)，引线实线/虚线交替。

**DrawingCanvas 增强**：右上角缩放工具栏替换为 SVG 图标，低缩放指引线，底部 HintBar（3s 淡出）。

### 右侧面板 (PanelA)

宽度 280 → 320px。Filter bar + 滚动列表 + 详情区 + ConclusionBar 底部固定。

新组件：
- **AIBadge**：显示 AI 建议，可折叠，刷新按钮
- **ConclusionBar**：状态统计 + 备注 + 通过/驳回 + 确认弹窗
- **Stamp**：结论后的印章动画 (APPROVED/REJECTED)

## API 对接

- ConclusionBar → `PATCH /api/versions/{version_id}/conclusion`（已有）
- Discussion → `GET/POST /api/dimensions/{dimId}/messages`（已有）
- 版本切换、图纸加载、标注状态更新 → 全部走现有 API

## 文件变更

只改 `app/templates/review_workbench.html`。`shared.jsx`、`spa.html` 不动。
