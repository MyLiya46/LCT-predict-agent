# T23 · 六个月型号级基线汇总（six-month-sku-aggregation）

- 任务 ID：T23
- 标题与目标：把 What-if 的展示和优化最小单元收敛为一个型号，同时保留月份/渠道明细并在分页前完成六个月全量汇总。
- 关联文档章节：`docs/feat-icewash.md` §3.4、§3.5、§10.2；T21、T22
- 前置依赖 blockedBy：T22

## 执行画像

- execution_mode：direct
- execution_class：normal
- expected_duration：约 45 分钟
- external_waits：PG 可选；无外部 HTTP 依赖
- checkpoint_phases：明细契约、型号聚合、分页边界、后端测试
- resume_boundary：从最后一个未通过的聚合验收项继续

## 问题

- 当前 baseline 以 `型号+渠道+月份` 返回并在 `items` 上先截断 `limit=200`，顶部销量和销售额会受分页影响。
- 页面策略矩阵没有稳定表达六个月型号总量；同一型号可能出现多行，销售额和毛利无法直接作为型号级经营指标。
- 价格关联存在跨版本 fallback，可能把其它版本价格用于当前预测版本。

## 决策

- 先生成全量预测明细，再以 `sku` 聚合为页面型号行；每个型号行附带完整 `details`，每条 detail 保留月份、预测期、渠道、预测数量、`baseline_price` 和成本价。
- `summary` 在截断前计算六个月全量销量、销售额、月份序列、价格覆盖率和成本覆盖率；`items` 的 `limit` 只限制页面展示行。
- 销售额严格使用逐明细 `baseline_qty * baseline_price`；没有基线价格的明细不计入可确认销售额，并通过状态字段暴露缺失。

## 范围

- 包含：PG baseline 查询、价格/成本精确关联、型号聚合、明细嵌套、summary 契约、前端 baseline 类型和模型行 details 输入。
- 不包含：毛利率卡片文案和库存周转卡片，由 T24 处理；候选策略评分，由 T25 处理。

## 环境预检

- 必需 Shell：git-bash
- 必需命令：`backend/.venv/Scripts/python.exe`、`npm`
- 必需端口：无
- 必需 URL：无
- 必需 Python 模块：`sqlalchemy`、`pytest`
- 必需 Docker 容器：无
- 容器内必需命令：无
- 容器内必需 Python 模块：无
- 执行画像：normal
- 启动超时（秒）：10
- 空闲超时（秒）：30
- 硬截止（秒）：240
- 最大 checkpoint 间隔（秒）：45
- 预检命令：
  ```bash
  python C:/Users/jie32.guo/.codex/skills/plan-generator/scripts/preflight.py check --plan docs/plans/T23-six-month-sku-aggregation-2026-09-04.md --format json
  ```

## 风险与回滚

- 风险：型号聚合后旧调用方若依赖每月行数，可能出现行数变化；影响限定在 What-if baseline 和内部模型行，保留 `details` 可支持旧口径恢复。通过旧字段兼容和聚合测试监测。
- 回滚：恢复 `load_baseline` 的明细 items 输出并保留 summary 全量计算；回滚前端 `details` 展开逻辑，不删除数据库数据。

## 实施步骤

### 步骤 1：构造全量标准明细
- 对象：`load_baseline` 的 attribution、fcst_detail、cost_data 查询和 join。
- 动作：按 `version+month+forecast_period+sku+channel` 去重/合并，精确关联计划价并解析 `baseline_price`，再关联成本价，输出标准明细字段。
- 参数：预测数量取 `y_pred` 最大值去除归因重复；计划输入价只接受当前版本和同月份匹配，再解析为 `baseline_price`；成本按 `category+sku`；缺失均为 `null`。
- 核心修改文件：`backend/src/app/services/whatif_workbench.py`
- 必要集成文件：`backend/src/app/models/relay.py`
- 命令：
  ```bash
  backend/.venv/Scripts/python.exe -m pytest -q backend/tests/test_attribution_whatif_service.py
  ```

### 步骤 2：聚合型号行并保留六个月 details
- 对象：baseline 返回的 `items`、`summary`、`build_whatif_rows`。
- 动作：按型号聚合数量和逐明细销售额，计算加权展示价格，附带 `details`，并在分页前生成全量 summary。
- 参数：`summary.baseline_qty` 和 `summary.baseline_amount` 不受 `limit` 影响；`total` 为型号数；detail_count 为明细数；一型号一页面行。
- 核心修改文件：`backend/src/app/services/whatif_workbench.py`
- 必要集成文件：`backend/src/app/api/whatif.py`、`backend/src/app/tools/internal/_capability.py`
- 命令：
  ```bash
  backend/.venv/Scripts/python.exe -m pytest -q backend/tests/test_attribution_whatif_service.py backend/tests/test_capability_tools.py
  ```

### 步骤 3：接入前端和模型 details 契约
- 对象：`WhatIfBaselineItem`、`WhatIfModelRow`、`toModelRow` 和 baseline 初始化。
- 动作：增加版本/预测期/成本覆盖/details 字段；页面按型号行展示；模型请求携带六个月明细，以同一策略作用于该型号的所有明细。
- 参数：`details` 为空时兼容旧单行计算；型号行的 baseline 数量为 details 数量之和；baseline amount 使用明细真实金额。
- 核心修改文件：`frontend/src/api.ts`、`frontend/src/pages/WhatIfPage.tsx`
- 必要集成文件：`services/icewash-model/cbg_fcst_month/server.py`、`services/icewash-model/cbg_fcst_month/whatif.py`
- 命令：
  ```bash
  cd frontend && npm run build
  ```

## 完成标准
- 验收类型：mixed
- 离线验收命令：
  ```bash
  cd backend && .venv/Scripts/python.exe -m pytest -q tests/test_attribution_whatif_service.py tests/test_capability_tools.py
  cd ../frontend && npm run build
  ```
- 外部环境验收命令：登录后调用 `/api/whatif/baseline?category=冰箱&version=<版本>&limit=1`，确认 `summary.baseline_qty` 与 `summary.baseline_amount` 不随 limit 变化，且每个 item 含 `details` 和标准字段。
- 通过条件：当前测试夹具中的同一型号跨两个月/两个渠道只产生一行；summary 仍完整累加；模型行能携带 details；前端构建退出码为 0。
