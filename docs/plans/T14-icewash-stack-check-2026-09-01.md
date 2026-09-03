# T14 · icewash 栈联调自检（icewash-stack-check）

- 任务 ID：T14
- **标题与目标**：确认 `services/icewash-model`（cbg_fcst_month）独立服务就绪——`/health`、`/predict`+`/tasks/{id}`、`/whatif/strategies`、`/simulate`、`/optimize`、pg_sync 写 PG 三表，为 O end-to-end 真实预测清障。
- **关联文档章节**：feat-icewash.md §2/§3（icewash capabilities）；services/icewash-model server.py、pg_sync.py、main.py
- 前置依赖 blockedBy：T03

## 问题
- 任务 T14 当前需要完成本计划标题对应的交付；旧版计划结构无法被 plan-generator v1.2.0 的结构化校验直接读取。

## 决策
- 保留本计划既有技术边界、参数、实施内容和验收命令；仅补齐 v1.2.0 要求的元数据、章节与结构化执行入口。

## 范围
- 包含：本计划既有实施要点、涉及路径、接口、数据约束和验收项。
- 不包含：改变任务目标、blockedBy 依赖、代码实现或项目业务口径。

## 风险与回滚
- 风险：旧计划正文中的命令或外部服务依赖可能在执行环境中不可用，导致该任务验收失败。
- 回滚：执行前保存本任务涉及文件的补丁；失败时使用 `git apply -R /tmp/T14-plan.patch` 反向应用补丁并恢复前一阶段。

## 实施步骤

### 步骤 1：执行原计划实施内容
- 对象：T14 对应的目标模块、接口和验收对象。
- 动作：按下方保留的原实施内容执行，并使用其中的命令完成验证。
- 参数：严格使用正文中给出的路径、端口、字段、超时、权限和命令参数。
- 文件：docs/plans/T14-icewash-stack-check-2026-09-01.md
- 命令：
  ```bash
  python /c/Users/jie32.guo/.codex/skills/plan-generator/scripts/plan_state.py lint-plan --plan docs/plans/T14-icewash-stack-check-2026-09-01.md
  ```
#### 1. 启动 icewash server（已有容器）
- `docker ps` 确认 `icewash-model` 容器在跑（start_dev_stack.sh 已覆盖）；否则进入 `services/icewash-model/cbg_fcst_month` 手动 `uvicorn server:app --port 8001`。
- 确认 `BACKEND_PG_URL` 指向 `postgresql+psycopg2://app:app@127.0.0.1:5432/agent_platform`（pg_sync 默认值）。

#### 2. 端点自检
- `curl -s http://127.0.0.1:8001/health` → `status:healthy`。
- `curl -s http://127.0.0.1:8001/whatif/strategies` → 8 条策略。
- 提交预测：`POST /predict`（body 见 server.py PredictionRequest 示例，categoryBatchMappingDTOList 含冰箱/洗衣机批次号）→ 返回 `task_id`。
- 轮询 `GET /tasks/{id}` 至 `status=completed`，`result.data.saved_success` 真。
- `POST /simulate` / `POST /optimize`（body 见 SimulateRequest/OptimizeRequest）→ 返回 task_id → 轮询 completed。

#### 3. pg_sync 落库
- 预测完成后 `psql agent_platform -c "SELECT count(*) FROM fcst_forecast_result WHERE system_forecast_number='<sn>'"` > 0；`fcst_attribution` 同理。
- `sync_history_csv`（`python -m pg_sync --pg-url <pn>`）跑一次，`fcst_history` 灌入 > 0 行（T03 后该表已建）。
- 注意 `fcst_*` 表由 backend 侧 T03 的 Alembic 建（三张能力域表之外的独立 pg_sync 表），若 icewash 先写需确认表已存在（否则 pg_sync 静默告警跳过）。

## 完成标准
- 验收命令：
  ```bash
  python /c/Users/jie32.guo/.codex/skills/plan-generator/scripts/plan_state.py lint-plan --plan docs/plans/T14-icewash-stack-check-2026-09-01.md
  ```
- 通过条件：命令退出码为 0，且本节保留的原验收项全部满足。
- [ ] `curl -s http://127.0.0.1:8001/health` 返回 `status:healthy`。
- [ ] `/predict` 提交后 `GET /tasks/{id}` 一路 `running→completed`，`result.saved_success=true`；重启 icewash 进程后同 task 仍可查询（SQLite task_store 跨重启）。
- [ ] `/whatif/strategies` 返回策略目录；`/simulate`/`/optimize` 各自 completed。
- [ ] `psql` 三表 `fcst_forecast_result`/`fcst_attribution`/`fcst_history` 有本次写入的行（`system_forecast_number` 对应）。
