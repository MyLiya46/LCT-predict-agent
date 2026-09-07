# T34 · 聊天工作台可视化与三子栏复用（chat-workbench-visualization-tabs）

- 任务 ID：T34
- 标题与目标：复用 Attribution/What-if 工作台已有的图表和矩阵视觉语义，让聊天结果按 envelope 稳定渲染分析解读、可视化图表、数据表三个子栏。
- 关联文档章节：`docs/feat-icewash.md` §4、§5、§10.2；`docs/PRD.md` §7.1、§12.4；T20、T32、T33
- 前置依赖 blockedBy：T33

## 执行画像

- execution_mode：worker
- execution_class：normal
- expected_duration：约 45 分钟
- external_waits：无；页面运行态在 T35 验收
- checkpoint_phases：类型合同、图表组件抽取、聊天卡片、工作台回归、前端构建
- resume_boundary：从最后一个未通过的 TypeScript 构建或组件契约检查继续

## 问题

- 当前 `MessageResultCard` 已按是否存在 `chart/table/text` 动态建 tab，但 `ChartBody` 只能渲染单个 `chart.option`；T32 新增的预测曲线+白盒归因和 T33 的策略矩阵+达成趋势无法显示。
- AttributionPage 内联实现了历史/预测衔接曲线和 waterfall，WhatIfPage 内联实现了策略矩阵和达成曲线；聊天端如果另写一套 option，会产生颜色、指标口径和空值处理漂移。
- `AgentResultEnvelope` 仍以旧 `intent` 为必填类型，`response_type`/复合 chart/coverage metadata 没有 TypeScript 类型；follow-up 还会把旧 `prior_intent` 拼入请求，容易让产品误以为聊天由手动意图筛选驱动。

## 决策

- 抽取工作台已有的纯展示逻辑为共享组件/option builder：预测曲线沿用 AttributionPage 的历史实线、预测虚线、预测起点和无值断点；waterfall 沿用其颜色与标注；策略矩阵和累计达成趋势沿用 WhatIfPage 的列和标签。
- 扩展前端 chart 类型但保留旧格式：`legacy option`、`composite`、`strategy_dashboard` 均由 `ChartBody` 渲染；未知 chart 类型显示可诊断的“暂无可用图表”，不阻塞分析和数据表。
- `MessageResultCard` 的 tab 以 `text.markdown/chart/table` 是否存在为准，并支持复合 chart card；预测和 What-if 成功结果必须分别拥有三种内容，空价格/成本/库存只影响内容状态，不隐藏图表或表格。
- 聊天发送继续以用户自然语言为路由输入；前端不再为 follow-up 发送 `prior_intent`，旧 envelope 的 `intent` 仅用于下载文件名和历史兼容，后端不读取它。

## 范围

- 包含：AgentResultEnvelope 类型、复合 chart card 类型、共享预测/归因/What-if 图表组件、MessageResultCard/ChartPanel/TablePanel、ChatPanel follow-up 参数清理、工作台页面改为复用共享 builder、前端构建与静态契约检查。
- 不包含：后端 tool workflow、预测/归因/What-if 数值计算、SSE 协议和工作台 API 路径；这些由 T31–T33 与既有 T20 负责。

## 环境预检

- 必需 Shell：git-bash
- 必需命令：`npm`、`node`
- 必需端口：无；页面运行态在 T35
- 必需 URL：无
- 必需 Python 模块：无
- 必需 Docker 容器：无
- 容器内必需命令：无
- 容器内必需 Python 模块：无
- 执行画像：normal
- 启动超时（秒）：20
- 空闲超时（秒）：30
- 硬截止（秒）：240
- 最大 checkpoint 间隔（秒）：45
- 预检命令：
  ```bash
  python C:/Users/jie32.guo/.codex/skills/plan-generator/scripts/preflight.py check --plan docs/plans/T34-chat-workbench-visualization-tabs-2026-09-04.md --format json
  ```

## 风险与回滚

- 风险：抽取 ECharts option 时可能改变工作台现有 tooltip、坐标轴或空值行为；复合卡片可能在小屏聊天栏溢出；旧历史消息缺少新字段。通过工作台页面构建、fixture 渲染契约和旧 envelope 分支测试监测。
- 回滚：保留 AttributionPage/WhatIfPage 的旧 option 调用路径和 `chart.option` fallback；若复用组件破坏工作台，先停用共享抽取，仅让聊天复合卡使用独立适配器，不回滚后端数据。

## 实施步骤

### 步骤 1：扩展前端 envelope 与 chart card 类型

- 对象：`AgentResultEnvelope`、`ChartType`、复合 chart card data 和 What-if metrics/table 类型。
- 动作：增加 `response_type`、`composite`、`strategy_dashboard`、`line_band`、`waterfall`、`strategy_matrix`、`attainment_trend` 的静态类型；保留 `intent` 可选兼容和旧 `chart.option` 结构；为 null/coverage/status/reason 定义可渲染字段。
- 参数：复合 chart card 必须有 `type/title/data`；line card 至少有 `periods/history/forecast/top_skus`，数组允许 `number|null`；waterfall data 保留 `sku/xAxis/placeholder/values/labels/colors`；strategy matrix 至少有 `columns/rows/total`；累计趋势至少有 `months/cumulative/baseline/simulated/target`，其中三者均含 `qty/amount` 数组且允许 `null`；`meta` 定义 `evidence/assumptions/coverage/status/reason` 可渲染字段；未知字段允许读取但不得用 `any` 绕过基础校验。
- 核心修改文件：`frontend/src/types.ts`、`frontend/src/api.ts`
- 必要集成文件：`frontend/src/store.ts`、`frontend/src/components/TablePanel.tsx`
- 命令：
  ```bash
  cd frontend && npm run build
  ```

### 步骤 2：抽取并复用 Attribution/What-if 图表与矩阵组件

- 对象：AttributionPage 的 `trendOption/waterfallOption`、WhatIfPage 的 `chartOption`/策略矩阵 DOM。
- 动作：将 option builder 与可复用展示组件迁移到 `frontend/src/components/agent/` 或等价共享路径；工作台页面改为调用共享 builder；聊天 chart renderer 根据 card type 渲染多个 ECharts 或矩阵表。
- 参数：预测曲线保留历史/预测颜色、预测起点 markLine、缺失值断点和 tooltip；waterfall 至少显示基础销量、Top 因子、最终预测；What-if 趋势显示累计基线、累计模拟、累计目标，矩阵显示型号、状态、Agent 建议策略、参数、销量/销售额结果和覆盖状态。
- 核心修改文件：`frontend/src/components/ChartPanel.tsx`、`frontend/src/components/MessageResultCard.tsx`、`frontend/src/components/agent/ForecastAttributionChart.tsx`、`frontend/src/components/agent/StrategyDashboard.tsx`
- 必要集成文件：`frontend/src/pages/AttributionPage.tsx`、`frontend/src/pages/WhatIfPage.tsx`、`frontend/src/components/ChartPanel.tsx`
- 命令：
  ```bash
  cd frontend && npm run build
  ```

### 步骤 3：保证聊天三个子栏和自然语言 follow-up 行为

- 对象：`MessageResultCard`、`ChartBody`、`ChatPanel`、`store` 的 envelope/workspace 更新逻辑。
- 动作：复合 chart 进入“可视化图表” tab；forecast/optimization/simulation 有 text/chart/table 时稳定生成三个 tab；history/report/旧消息保持兼容；follow-up 请求只发送自然语言和 params，不注入 `prior_intent`；修正 `hasInlineResult`/workspace 更新分支，使 `update_workspace=false` 只影响右侧工作区。
- 参数：默认 tab 仍为“分析解读”；图表卡按 backend `cards` 顺序渲染；`attainment_trend` 同时提供销量和销售额两组累计线，价格缺失时销售额线保留断点/状态；数据表保留分页和 CSV 导出；响应无图表时不创建空 tab；`update_workspace=false` 不隐藏聊天内结果卡。
- 核心修改文件：`frontend/src/components/MessageResultCard.tsx`、`frontend/src/components/ChartPanel.tsx`、`frontend/src/components/ChatPanel.tsx`、`frontend/src/store.ts`
- 必要集成文件：`frontend/src/components/TablePanel.tsx`、`frontend/src/types.ts`
- 命令：
  ```bash
  cd frontend && npm run build
  rg -n "strategy_dashboard|composite|line_band|waterfall" src
  ```

### 步骤 4：离线 fixture 检查三子栏和工作台不回归

- 对象：预测、预测+归因、optimization、simulation、旧 history envelope 的前端 fixture 与共享组件。
- 动作：为 card/tab 生成最小可读 fixture；断言 forecast/What-if 的 tab 顺序为“分析解读→可视化图表→数据表”，复合 card 数量和空值展示正确；保留工作台页面的 import/build 检查。
- 参数：fixture 覆盖三个月预测、TOP5 归因（含 5 条 `top_skus` 线和 waterfall）、六个月累计 What-if（含 qty/amount 两组序列）、缺价格/成本/库存状态和旧 `{chart:{option}}`；不得通过把 null 转为 `0` 来让 fixture 通过。
- 核心修改文件：`frontend/src/components/MessageResultCard.tsx`、`frontend/src/components/ChartPanel.tsx`
- 必要集成文件：`frontend/src/components/agent/agentChartFixtures.ts`、`frontend/package.json`
- 命令：
  ```bash
  cd frontend && npm run build
  ```

## 完成标准

- 验收类型：offline
- 离线验收命令：
  ```bash
  python C:/Users/jie32.guo/.codex/skills/plan-generator/scripts/plan_state.py lint-plan --plan docs/plans/T34-chat-workbench-visualization-tabs-2026-09-04.md
  cd frontend && npm run build
  ! rg -n "prior_intent" src
  ```
- 外部环境验收命令：无
- 通过条件：前端构建退出码为 0；预测 fixture 和 What-if fixture 都显示三个子栏；复合预测图同时可见预测曲线与白盒归因；策略图同时可见矩阵与累计达成趋势；工作台 Attribution/What-if 页面仍能构建并使用共享展示逻辑；聊天发送路径没有 `prior_intent` 注入。
