# T30 · What-if Agent 与基准价闭环验收（whatif-agent-price-integration-acceptance）

- 任务 ID：T30
- 标题与目标：验证 Agent 推荐、六个月基线销售额、历史基准价、规则策略和页面展示在真实本地链路中闭环。
- 关联文档章节：`docs/feat-icewash.md` §3、§10；T27、T28、T29
- 前置依赖 blockedBy：T27、T28、T29

## 执行画像

- execution_mode：worker
- execution_class：external
- expected_duration：约 45 分钟
- external_waits：PG、backend、icewash model、frontend；LLM 聊天链路可选
- checkpoint_phases：计划/迁移检查、离线回归、seed、baseline、Agent optimize、页面构建
- resume_boundary：从最后一个未通过的验收阶段继续，不重复已通过阶段

## 问题

- 单元测试分别通过不能证明聊天工具传入了品类、基线不是空列表、历史价格确实进入六个月明细、策略返回非空且页面未把 null 改成 0。
- 需要区分“实现失败”和本地 PG/服务不可用；外部环境不可用只能记录为 external blocked，不覆盖离线结果。

## 决策

- 以 T27–T29 的契约为唯一验收口径：Agent 工具必须有 category；baseline 必须返回非空型号与 detail；价格来源必须可追溯；optimize 返回至少一个策略行。
- 选择一条真实已有预测版本和品类（优先 `冰箱`），只读调用 baseline/optimize 与页面健康检查；不触发预测、不上传文件、不清空业务数据。
- seed 使用既有 `app.seed_icewash_tools`，迁移检查确认 `0006` head；不提交、不 push。

## 范围

- 包含：计划 lint/state 校验、PG migration、离线回归、Agent 工具 seed、backend/model/frontend 健康和 What-if API 运行态检查。
- 不包含：生产部署、git commit/push、修改预测历史数据、自由式 LLM 策略生成。

## 环境预检

- 必需 Shell：git-bash
- 必需命令：`python`、`backend/.venv/Scripts/python.exe`、`npm`、`curl`
- 必需端口：8000、8001、5173
- 必需 URL：`http://127.0.0.1:8000/healthz`、`http://127.0.0.1:8001/health`、`http://127.0.0.1:5173/workbench/what-if`
- 必需 Python 模块：无
- 必需 Docker 容器：无
- 容器内必需命令：无
- 容器内必需 Python 模块：无
- 执行画像：external
- 启动超时（秒）：30
- 空闲超时（秒）：60
- 硬截止（秒）：360
- 最大 checkpoint 间隔（秒）：60
- 预检命令：
  ```bash
  python C:/Users/jie32.guo/.codex/skills/plan-executor/scripts/preflight.py check --plan docs/plans/T30-whatif-agent-price-integration-acceptance-2026-09-04.md --format json
  ```

## 风险与回滚

- 风险：本地服务、PG 或认证环境不可用会使运行态检查无法完成；需分别记录离线通过和外部阻断。真实数据价格覆盖率可能小于 100%，不能把部分覆盖误判为全链路失败。
- 回滚：验收只读，失败时保留源码和测试改动，从失败阶段重跑；若迁移验证发现问题，按 T28 执行 `alembic downgrade 0005`，不执行删除业务数据的命令。

## 实施步骤

### 步骤 1：校验计划、依赖和迁移状态

- 对象：T27–T30 计划、规范任务状态文件、backend Alembic 状态。
- 动作：执行 plan validate/lint、确认任务依赖拓扑和 migration head；检查工作区只包含本轮 What-if 相关改动。
- 参数：T27–T30 必须在执行前为 reviewed；迁移目标为 `0006`；不修改 T01–T26 状态内容。
- 核心修改文件：`docs/plans/T30-whatif-agent-price-integration-acceptance-2026-09-04.md`
- 必要集成文件：无
- 命令：
  ```bash
  python C:/Users/jie32.guo/.codex/skills/plan-generator/scripts/plan_state.py validate --state "$(find docs -maxdepth 1 -type f -name '*.json' -print -quit)"
  cd backend && .venv/Scripts/python.exe -m alembic current
  ```

### 步骤 2：运行离线回归和前端构建

- 对象：历史 relay、baseline、Agent tool、icewash strategy、模型编译和 frontend build。
- 动作：按依赖顺序执行全量 What-if 定向测试和构建。
- 参数：必须覆盖 category 缺失、空基线、历史金额、历史最后月价格、六个月多渠道、maintain、价格策略、缺价 fallback、销量-only 和双目标。
- 核心修改文件：`backend/tests/test_capability_tools.py`、`backend/tests/test_icewash_whatif_contract.py`
- 必要集成文件：无
- 命令：
  ```bash
  backend/.venv/Scripts/python.exe -m pytest -q backend/tests/test_forecast_relay_ingest.py backend/tests/test_prediction_detail_contract.py backend/tests/test_attribution_whatif_service.py backend/tests/test_capability_tools.py backend/tests/test_icewash_whatif_contract.py
  python -m py_compile services/icewash-model/cbg_fcst_month/pg_sync.py services/icewash-model/cbg_fcst_month/whatif.py services/icewash-model/cbg_fcst_month/server.py
  cd frontend && npm run build
  ```

### 步骤 3：运行 seed 与 What-if 运行态闭环

- 对象：Agent tool registry、backend baseline/optimize proxy、icewash task、前端路由。
- 动作：执行 seed；获取真实品类/预测版本；调用 baseline 并检查 summary 与 detail；通过 internal optimize 或 `/api/whatif/optimize` 传 category、销量目标和销售额目标，轮询至 completed。
- 参数：baseline 必须 `total > 0`；summary 的销售额由有价明细汇总；已有历史 SKU 的 `price_source=historical_last_valid_month`；返回行数等于型号数且每行 `strategy_id` 非空；若价格覆盖不足，`amount_gap` 可为 null 但任务不得空结果完成。
- 核心修改文件：`backend/seed/v2__icewash_tools.py`
- 必要集成文件：`backend/seed/v2__icewash_tools.py`
- 命令：
  ```bash
  cd backend && .venv/Scripts/python.exe -m app.seed_icewash_tools
  curl -fsS http://127.0.0.1:8000/healthz
  curl -fsS http://127.0.0.1:8001/health
  curl -fsS http://127.0.0.1:5173/workbench/what-if
  ```

## 完成标准

- 验收类型：mixed
- 离线验收命令：
  ```bash
  python C:/Users/jie32.guo/.codex/skills/plan-generator/scripts/plan_state.py lint-plan --plan docs/plans/T30-whatif-agent-price-integration-acceptance-2026-09-04.md
  backend/.venv/Scripts/python.exe -m pytest -q backend/tests/test_forecast_relay_ingest.py backend/tests/test_prediction_detail_contract.py backend/tests/test_attribution_whatif_service.py backend/tests/test_capability_tools.py backend/tests/test_icewash_whatif_contract.py
  cd frontend && npm run build
  ```
- 外部环境验收命令：健康检查、认证后的 `/api/whatif/baseline`、`/api/whatif/optimize` 任务轮询和页面 URL；必要时直接调用 internal optimize 验证 Agent 工具。
- 通过条件：Agent 不再因缺品类产生空策略；基线六个月销售额不因空价格归零；维持现状等于历史最后有效月价格；价格策略基于该价调整；有价明细销售额/毛利可汇总；无价明细明确缺失且任务仍可诊断完成；页面成功构建。
