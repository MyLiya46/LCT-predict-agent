# T14 · icewash 栈联调自检（icewash-stack-check）

- **任务 ID**：T14
- **标题与目标**：确认 `services/icewash-model`（cbg_fcst_month）独立服务就绪——`/health`、`/predict`+`/tasks/{id}`、`/whatif/strategies`、`/simulate`、`/optimize`、pg_sync 写 PG 三表，为 O end-to-end 真实预测清障。
- **关联文档章节**：feat-icewash.md §2/§3（icewash capabilities）；services/icewash-model server.py、pg_sync.py、main.py
- **前置依赖 blockedBy**：T03

## 实施要点

### 1. 启动 icewash server（已有容器）
- `docker ps` 确认 `icewash-model` 容器在跑（start_dev_stack.sh 已覆盖）；否则进入 `services/icewash-model/cbg_fcst_month` 手动 `uvicorn server:app --port 8001`。
- 确认 `BACKEND_PG_URL` 指向 `postgresql+psycopg2://app:app@127.0.0.1:5432/agent_platform`（pg_sync 默认值）。

### 2. 端点自检
- `curl -s http://127.0.0.1:8001/health` → `status:healthy`。
- `curl -s http://127.0.0.1:8001/whatif/strategies` → 8 条策略。
- 提交预测：`POST /predict`（body 见 server.py PredictionRequest 示例，categoryBatchMappingDTOList 含冰箱/洗衣机批次号）→ 返回 `task_id`。
- 轮询 `GET /tasks/{id}` 至 `status=completed`，`result.data.saved_success` 真。
- `POST /simulate` / `POST /optimize`（body 见 SimulateRequest/OptimizeRequest）→ 返回 task_id → 轮询 completed。

### 3. pg_sync 落库
- 预测完成后 `psql agent_platform -c "SELECT count(*) FROM fcst_forecast_result WHERE system_forecast_number='<sn>'"` > 0；`fcst_attribution` 同理。
- `sync_history_csv`（`python -m pg_sync --pg-url <pn>`）跑一次，`fcst_history` 灌入 > 0 行（T03 后该表已建）。
- 注意 `fcst_*` 表由 backend 侧 T03 的 Alembic 建（三张能力域表之外的独立 pg_sync 表），若 icewash 先写需确认表已存在（否则 pg_sync 静默告警跳过）。

## 验收标准
- [ ] `curl -s http://127.0.0.1:8001/health` 返回 `status:healthy`。
- [ ] `/predict` 提交后 `GET /tasks/{id}` 一路 `running→completed`，`result.saved_success=true`；重启 icewash 进程后同 task 仍可查询（SQLite task_store 跨重启）。
- [ ] `/whatif/strategies` 返回策略目录；`/simulate`/`/optimize` 各自 completed。
- [ ] `psql` 三表 `fcst_forecast_result`/`fcst_attribution`/`fcst_history` 有本次写入的行（`system_forecast_number` 对应）。