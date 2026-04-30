# Web 端图纸审核界面 — 设计文档

## 概述

为工程图纸审核系统实现 Web 端交互式审核界面。审核人在单页面内完成：查看图纸、管理尺寸标注、逐条讨论、提交审核结论。

## 技术选型

纯 Vanilla JS + CSS Transform，零外部依赖。基于现有 FastAPI + Jinja2 架构。

## 页面布局

左右分栏（65%/35%），新路由 `GET /parts/{id}/versions/{vid}/review`。

### 左侧：图纸显示区

- PDF 每页自动转为 300 DPI JPG，存 `static/drawings/{drawing_id}/`
- 多张图纸用标签页切换
- 鼠标滚轮缩放（0.5x~5x），以鼠标位置为中心
- 按住空白区域拖拽平移
- 双击空白恢复 100% 适应窗口
- 标注圆圈绝对定位在图片容器内：
  - 三态颜色：灰=待审 / 绿=确认 / 黄=存疑
  - 序号数字反比例缩放保持可读
  - 悬停显示尺寸值气泡
  - 拖拽移动、× 删除
- 新增标注：进入添加模式→点击图面→弹出表单（类型+值）
- 筛选联动：非当前筛选态标注 opacity 0.2

### 右侧：审核面板（三区）

**上区 — 标注索引列表**（固定高度 40%）
- 筛选栏：全部 | 待审 | 存疑 | 确认
- 每行：序号圆圈 + 尺寸值 + 类型 + 来源 + 状态
- 点击选中，与图像双向联动（平移+高亮）

**中区 — 详情+讨论**（弹性高度）
- 选中标注的完整信息
- 讨论消息列表 + 输入框
- 快捷状态切换按钮

**下区 — 审核结论**（固定底部）
- 标注统计（确认/存疑/待审数量）
- 通过/驳回 + 备注
- 有存疑标注时禁用通过按钮

## 数据模型变更

### Dimension 新增字段
- `review_status`: Enum(pending/confirmed/questionable)，默认 pending

### 新增 ReviewMessage 表
- id, dimension_id (FK), author (String), content (Text), created_at

## API 端点

| 方法 | 路径 | 用途 |
|------|------|------|
| GET | /parts/{id}/versions/{vid}/review | 审核页面 |
| GET | /api/versions/{vid}/drawings/{did}/dimensions | 获取标注列表 |
| POST | /api/dimensions | 新增标注 |
| PATCH | /api/dimensions/{id} | 更新标注 |
| DELETE | /api/dimensions/{id} | 删除标注 |
| GET | /api/dimensions/{id}/messages | 讨论记录 |
| POST | /api/dimensions/{id}/messages | 发送消息 |
| PATCH | /api/versions/{id}/conclusion | 提交审核结论 |

## 撤销机制

操作历史栈（最近 10 步），支持新增/移动/删除标注的撤销。Ctrl+Z 或 UI 按钮触发。每步记录操作类型 + 之前状态，撤销时还原。

## 新增文件

```
app/
├── routers/review.py       # 审核路由 + API
├── templates/review/
│   └── index.html          # 审核页面（内联 CSS + JS）
├── services/image_gen.py   # PDF → JPG 转换
```
