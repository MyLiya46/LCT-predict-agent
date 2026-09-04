# T21 · What-if 基线与异步策略工作流（whatif-async-simulation-workflow）

- 任务 ID：T21
- 标题与目标：把 `/workbench/what-if` 重构为“选择基线 → 编辑 custom strategy → 调 icewash 异步模拟 → Agent 异步优化”的可验证闭环，并把日志移到矩阵和趋势图下方。
- 关联文档章节：`docs/feat-icewash.md` §3.4、§3.5、§10.2；`docs/PRD.md` §5；T05、T14、T20
- 前置依赖 blockedBy：T05、T14、T20

## 执行画像

- execution_mode：direct
- execution_class：external
- expected_duration：约 45 分钟
- external_waits：PG、icewash model、HTTP 异步任务、前端构建
- checkpoint_phases：基线序列、模型逐行策略契约、simulate/optimize 轮询、页面布局、端到端验收
- resume_boundary：从最后一个未通过的 what-if 阶段继续

## 问题

- 当前页面在浏览器本地用 `whatifSimulate.ts` 计算结果，点击“运行沙盘模拟预估”没有请求 icewash model，无法证明模型异步推理链路。
- 基线接口只返回月份列表，没有 `qty_series/amount_series`；页面因此无法在选定文件后稳定绘制趋势。
- baseline 默认策略对新品返回不存在的 `plan_launch`，Agent 建议列使用 `--`，不符合“建议为空、最终执行维持现状”的初始状态。
- 模型 simulate/optimize 请求是全局单策略/单目标，无法承载矩阵中每一行独立的策略、参数和按比例分配的销量目标。
- 推导日志嵌在策略矩阵底部，会压缩表格并遮挡策略区域。

## 决策

- 策略目录和公式继续以 `services/icewash-model/cbg_fcst_month/whatif.py` 为唯一来源；模型服务扩展请求行的可选 `strategy_id/param/traffic_tier/target_qty`，按行覆盖全局默认值，仍以一个异步 task 完成批量计算。
- 基线服务按 `period` 聚合已加载 SKU，返回 `summary.months`、`summary.qty_series`、`summary.amount_series`，同时输出标准化弹性字段供模型计算。
- 前端不再执行 simulate/optimize 本地公式：baseline 只初始化维持现状；手动模拟提交每行 custom strategy，轮询 `/api/whatif/tasks/{task_id}`；Agent 提交按基线占比分配的逐行销量目标，直接使用模型返回的最优策略和预测量。
- 页面以阶段状态控制曲线：仅基线时显示基线曲线；模拟完成后增加当前模拟结果；Agent 完成后增加设定目标。目标输入默认为销量 `8`、销售额 `50`，重置按钮只清空两个输入框，不发请求。
- 日志改为页面主内容全宽底部固定高度面板，位于策略矩阵和趋势图之后；主区域允许滚动，避免遮挡矩阵。

## 范围

- 包含：PG 基线趋势序列、icewash 模型逐行请求契约、backend what-if 代理兼容、frontend API 及轮询、WhatIfPage 状态与布局、后端/模型回归测试。
- 不包含：策略目录新增、价格弹性算法重写、数据库表结构迁移、真实预测文件上传流程、其他工作台页面重构。

## 环境预检

- 必需 Shell：git-bash
- 必需命令：`python`、`uv`、`npm`
- 必需端口：8000（backend）、8001（icewash model）、5173（frontend）
- 必需 URL：`http://127.0.0.1:8000/api/whatif/baseline`、`http://127.0.0.1:8000/api/whatif/simulate`、`http://127.0.0.1:8001/whatif/strategies`
- 必需 Python 模块：backend `pytest`、`sqlalchemy`、`httpx`；model `fastapi`、`numpy`
- 必需 Docker 容器：无
- 容器内必需命令：无
- 容器内必需 Python 模块：无
- 执行画像：external
- 启动超时（秒）：30
- 空闲超时（秒）：60
- 硬截止（秒）：300
- 最大 checkpoint 间隔（秒）：60
- 预检命令：
  ```bash
  python C:/Users/jie32.guo/.codex/skills/plan-generator/scripts/preflight.py check --plan docs/plans/T21-whatif-async-simulation-workflow-2026-09-03.md --format json
  ```

## 风险与回滚

- 风险：PG 中存在多个预测月份或成本数据缺失时，序列与毛利可能出现空值；icewash 不可用或任务失败时，页面可能停留在 loading。通过按月聚合测试、任务失败日志和保留上一版结果监测。
- 回滚：保留 `/api/whatif` 现有全局字段兼容，并将模型行级字段设为可选；若外部模型无法升级，可暂时关闭逐行覆盖并由 backend 返回明确错误，源码回滚限定为基线服务、模型 server、API、WhatIfPage 及对应测试文件。

## 实施步骤

### 步骤 1：补齐基线趋势和标准化弹性数据

- 对象：`load_baseline` 返回体与 `WhatIfBaseline` 前端类型。
- 动作：按月份聚合已截取 items 的销量/销售额，返回 `qty_series`、`amount_series`；将弹性系数映射为 `coefficient/elasticity_class/ed/ed_source`。
- 参数：序列顺序与 `months` 一致；`ed` 使用 icewash `resolve_ed` 语义；无价格时销售额按 0 计；baseline 行默认 `maintain`。
- 核心修改文件：`backend/src/app/services/whatif_workbench.py`、`frontend/src/api.ts`、`frontend/src/whatifSimulate.ts`。
- 必要集成文件：`backend/tests/test_attribution_whatif_service.py`。
- 命令：
  ```bash
  cd backend && uv run pytest -q tests/test_attribution_whatif_service.py
  ```

### 步骤 2：扩展 icewash 异步 simulate/optimize 的逐行策略契约

- 对象：`SimulateRow`、`OptimizeRequest` 和 `/simulate`、`/optimize` 后台任务。
- 动作：增加可选行级 `strategy_id/param/traffic_tier/target_qty`；每行优先使用自身字段，否则使用请求级默认值；返回每行实际策略、目标、模拟量、模拟价和 effect_note。
- 参数：全局 `strategy_id` 保持必填且默认请求使用 `maintain`；行级目标允许为 0 以上浮点数；candidate 搜索继续过滤 status，候选公式只调用 `whatif.py`。
- 核心修改文件：`services/icewash-model/cbg_fcst_month/server.py`。
- 必要集成文件：`backend/src/app/services/icewash_whatif_client.py`、`backend/src/app/api/whatif.py`（仅保持代理字段透传）。
- 命令：
  ```bash
  python -m py_compile services/icewash-model/cbg_fcst_month/server.py services/icewash-model/cbg_fcst_month/whatif.py
  cd backend && uv run pytest -q tests/test_icewash_whatif_client.py
  ```

### 步骤 3：将前端模拟与 Agent 推荐改为真实异步模型任务

- 对象：`frontend/src/api.ts` 和 `WhatIfPage` 的 `runSimulation/runAgent`。
- 动作：增加 simulate/optimize 提交类型和 task 轮询；提交矩阵行策略和参数；把模型结果按 SKU 合并回矩阵，更新模拟量、模拟价、Agent 建议、最终策略和 KPI。
- 参数：轮询间隔 500ms、最大 120 次；状态 `pending/running` 继续轮询，`completed` 读取 `result.rows`，`failed` 抛出模型错误；Agent 行目标按 `goalVol / baselineTotal` 乘以各行 baseline_qty 分配。
- 核心修改文件：`frontend/src/api.ts`、`frontend/src/pages/WhatIfPage.tsx`。
- 必要集成文件：无。
- 命令：
  ```bash
  cd frontend && npm run build
  ```

### 步骤 4：重构三阶段页面状态与底部日志布局

- 对象：WhatIfPage 的 baseline 初始化、目标输入、策略矩阵、趋势图和日志 DOM。
- 动作：基线完成后所有行显示 baseline 结果、建议列为空、最终策略为维持现状；模拟和 Agent 按阶段显示曲线；目标重置只清空输入；将日志移出矩阵卡片，放到主内容全宽底部。
- 参数：初始目标销量 `8`、销售额 `50`；初始 chart 只展示基线；目标曲线仅在 Agent 完成且目标为正数时显示；策略矩阵和图表共享上方 flex 区域，日志高度 `7rem`。
- 核心修改文件：`frontend/src/pages/WhatIfPage.tsx`。
- 必要集成文件：无。
- 命令：
  ```bash
  cd frontend && npm run build
  ```

### 步骤 5：离线契约和页面行为验收

- 对象：backend what-if 测试、icewash what-if 计算测试、前端类型构建。
- 动作：验证 baseline 序列对齐、行级 simulate/optimize 覆盖、任务结果结构和页面关键文案/阶段条件。
- 参数：至少覆盖 maintain、price_cut、traffic_boost 三类策略，覆盖新品/淘汰状态和空目标输入。
- 核心修改文件：`backend/tests/test_attribution_whatif_service.py`、`backend/tests/test_icewash_whatif_client.py`、`services/icewash-model/cbg_fcst_month/whatif.py` 的既有测试入口。
- 必要集成文件：无。
- 命令：
  ```bash
  cd backend && uv run pytest -q tests/test_attribution_whatif_service.py tests/test_icewash_whatif_client.py
  cd ../frontend && npm run build
  ```

## 完成标准

- 验收类型：mixed
- 离线验收命令：
  ```bash
  python -m py_compile services/icewash-model/cbg_fcst_month/server.py services/icewash-model/cbg_fcst_month/whatif.py
  cd backend && uv run pytest -q tests/test_attribution_whatif_service.py tests/test_icewash_whatif_client.py && uv run ruff check src/app/services/whatif_workbench.py src/app/api/whatif.py tests/test_attribution_whatif_service.py
  cd ../frontend && npm run build
  ```
- 外部环境验收命令：登录后选择一个 category/version，确认 baseline 响应包含 `summary.months`、`summary.qty_series`、`summary.amount_series`；提交含两种行级 strategy 的 `/api/whatif/simulate`，轮询 task 至 completed；再提交逐行目标的 `/api/whatif/optimize` 并确认每行返回 `strategy_id` 与 `sim_qty`。
- 通过条件：基线阶段矩阵建议为空且最终策略全为维持现状、图表只显示基线；模拟和 Agent 请求均实际经过 icewash task；模型结果刷新矩阵与曲线；日志位于矩阵和图表下方且不覆盖表格；离线命令和前端构建退出码为 0。
