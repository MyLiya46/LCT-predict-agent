# T26 · What-if 契约集成验收（whatif-contract-integration-acceptance）

- 任务 ID：T26
- 标题与目标：用离线回归和运行态检查验证预测明细、六个月汇总、毛利覆盖、库存标签和双目标优化形成闭环。
- 关联文档章节：`docs/feat-icewash.md` §3、§10；T22、T23、T24、T25
- 前置依赖 blockedBy：T22、T23、T24、T25

## 执行画像

- execution_mode：direct
- execution_class：external
- expected_duration：约 45 分钟
- external_waits：PG、backend、icewash model、frontend
- checkpoint_phases：plan/state 校验、离线回归、服务健康、What-if API、页面构建
- resume_boundary：从最后一个未通过的验收阶段继续

## 问题

- What-if 改动横跨模型 PG 同步、backend relay/baseline、frontend KPI 和 Agent optimize，单个模块通过不能证明字段口径一致。
- 现有回归测试没有同时验证六个月型号聚合、成本缺失、固定周转标签和销售额目标。

## 决策

- 以 T22–T25 的契约字段为唯一验收口径，统一检查 `version/month/forecast_period/sku/channel/forecast_qty/plan_price/baseline_price/cost_price`。
- 离线验收覆盖无价格、无成本、多月份、多渠道和双目标；外部验收使用现有本地服务和真实 PG 数据，不修改生产数据。
- 工具 schema 更新后执行项目既有 seed 流程，使数据库中的 Agent 能力定义与源码一致。

## 范围

- 包含：契约 lint、后端目标测试、模型编译、前端构建、健康检查、baseline/optimize 运行态验证、seed schema 同步。
- 不包含：提交 git、push、生产部署；不重做已完成 T01–T21。

## 环境预检

- 必需 Shell：git-bash
- 必需命令：`python`、`backend/.venv/Scripts/python.exe`、`npm`、`curl`
- 必需端口：8000、8001、5173
- 必需 URL：`http://127.0.0.1:8000/healthz`、`http://127.0.0.1:8001/health`、`http://127.0.0.1:5173/workbench/what-if`
- 必需 Python 模块：`pytest`、`sqlalchemy`、`fastapi`、`pydantic`
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
  python C:/Users/jie32.guo/.codex/skills/plan-generator/scripts/preflight.py check --plan docs/plans/T26-whatif-contract-integration-acceptance-2026-09-04.md --format json
  ```

## 风险与回滚

- 风险：本地服务或 PG 不可用会阻断外部验收，但不代表离线实现失败；分别记录 offline 与 external 结果。
- 回滚：不改动预测历史数据；若 seed 或服务验收失败，保留源码改动并从失败阶段恢复，必要时按 T22–T25 的回滚步骤反向执行。

## 实施步骤

### 步骤 1：校验计划和离线依赖
- 对象：T22–T26 计划文件和项目测试环境。
- 动作：运行 plan state validate、各计划 lint、Python/前端依赖检查。
- 参数：所有计划章节顺序固定；新任务状态在执行前为 reviewed；不修改 T01–T21。
- 核心修改文件：`docs/plans/T26-whatif-contract-integration-acceptance-2026-09-04.md`
- 必要集成文件：无
- 命令：
  ```bash
  python C:/Users/jie32.guo/.codex/skills/plan-generator/scripts/plan_state.py lint-plan --plan docs/plans/T26-whatif-contract-integration-acceptance-2026-09-04.md
  ```

### 步骤 2：运行全量 What-if 离线验收
- 对象：T22–T25 指定的 backend/model/frontend 测试集合。
- 动作：按依赖顺序执行契约、聚合、毛利、优化回归和前端构建。
- 参数：要求测试覆盖六个月、双渠道、缺价格、缺成本、销量-only 与双目标。
- 核心修改文件：`backend/tests/test_prediction_detail_contract.py`、`backend/tests/test_attribution_whatif_service.py`、`backend/tests/test_icewash_whatif_contract.py`
- 必要集成文件：无
- 命令：
  ```bash
  backend/.venv/Scripts/python.exe -m pytest -q backend/tests/test_forecast_relay_ingest.py backend/tests/test_prediction_detail_contract.py backend/tests/test_attribution_whatif_service.py backend/tests/test_capability_tools.py backend/tests/test_icewash_whatif_contract.py
  cd frontend && npm run build
  ```

### 步骤 3：运行态闭环检查和 seed 同步
- 对象：backend What-if API、icewash model task、frontend 页面和 Agent tool registry。
- 动作：执行工具 seed；调用 baseline 获取标准契约；调用 optimize 传双目标并轮询任务；检查页面可加载。
- 参数：seed 使用项目既有命令；不上传新成本文件、不触发预测任务、不写入业务预测数据。
- 核心修改文件：`backend/seed/v2__icewash_tools.py`
- 必要集成文件：`backend/seed/v2__icewash_tools.py`
- 命令：
  ```bash
  cd backend && .venv/Scripts/python.exe -m app.seed_icewash_tools
  curl -fsS http://127.0.0.1:8000/healthz
  curl -fsS http://127.0.0.1:8001/health
  ```

## 完成标准
- 验收类型：mixed
- 离线验收命令：
  ```bash
  python C:/Users/jie32.guo/.codex/skills/plan-generator/scripts/plan_state.py lint-plan --plan docs/plans/T26-whatif-contract-integration-acceptance-2026-09-04.md
  backend/.venv/Scripts/python.exe -m pytest -q backend/tests/test_forecast_relay_ingest.py backend/tests/test_prediction_detail_contract.py backend/tests/test_attribution_whatif_service.py backend/tests/test_capability_tools.py backend/tests/test_icewash_whatif_contract.py
  cd frontend && npm run build
  ```
- 外部环境验收命令：健康检查、baseline/optimize API 与前端 URL 均返回成功；baseline summary 不受 limit 影响，型号行包含 details，库存显示固定回退标签，双目标 optimize 返回 amount 指标。
- 通过条件：离线命令全部退出码为 0；外部不可用时单独记录 blocked_external，不把已通过的离线实现标为失败；工作区没有生成无关构建源码变更。
