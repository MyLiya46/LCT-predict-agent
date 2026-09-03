# T06 · 预测模型客户端 + Excel/PG 适配（forecast-model-client）

- 任务 ID：T06
- **标题与目标**：backend 直连目标模型 `services/icewash-model` 的 `/predict` 与 `/tasks/{id}`，以模型 `pg_sync.py` 写入的 `fcst_*` 为正常结果链路，规范化写入工作台 PG 语义表；Excel adapter 仅服务已有文件提取和离线兼容。
- **关联文档章节**：`docs/feat-icewash.md` §3.2；`backend-ref/app/services/forecast_model_client.py`、`forecast_excel_adapter.py`、`forecast_ingest.py`；`services/icewash-model/cbg_fcst_month/main.py`、`pg_sync.py`、`server.py`、`output.py`
- 前置依赖 blockedBy：T03

## 问题
- 任务 T06 当前需要完成本计划标题对应的交付；旧版计划结构无法被 plan-generator v1.2.0 的结构化校验直接读取。

## 决策
- 保留本计划既有技术边界、参数、实施内容和验收命令；仅补齐 v1.2.0 要求的元数据、章节与结构化执行入口。

## 范围
- 包含：本计划既有实施要点、涉及路径、接口、数据约束和验收项。
- 不包含：改变任务目标、blockedBy 依赖、代码实现或项目业务口径。

## 风险与回滚
- 风险：旧计划正文中的命令或外部服务依赖可能在执行环境中不可用，导致该任务验收失败。
- 回滚：执行前保存本任务涉及文件的补丁；失败时使用 `git apply -R /tmp/T06-plan.patch` 反向应用补丁并恢复前一阶段。

## 实施步骤

### 步骤 1：执行原计划实施内容
- 对象：T06 对应的目标模块、接口和验收对象。
- 动作：按下方保留的原实施内容执行，并使用其中的命令完成验证。
- 参数：严格使用正文中给出的路径、端口、字段、超时、权限和命令参数。
- 文件：docs/plans/T06-forecast-model-client-2026-09-01.md
- 命令：
  ```bash
  python /c/Users/jie32.guo/.codex/skills/plan-generator/scripts/plan_state.py lint-plan --plan docs/plans/T06-forecast-model-client-2026-09-01.md
  ```
#### 1. 迁入异步模型客户端并统一配置
- 新建 `backend/src/app/services/forecast_model_client.py`：实现 `ensure_run`、`poll_events`、`submit`、`get_task`、`refresh`；唯一上游地址使用 `settings.forecast_model_base_url`，默认 `http://127.0.0.1:8001`。
- `_build_payload` 固定生成目标模型 `PredictionRequest` 所需字段：`systemForecastNumber`、`productLine`、`reporter`、`generateTime`、`customCallbackUrl=null`、`forecastMonth=YYYY-MM-01`、`saveTestData=false`、`categoryBatchMappingDTOList`；批次号从 `FORECAST_CATEGORY_BATCH_MAP_JSON` 读取。
- `backend/src/app/config.py` 和 `backend/.env.example` 统一使用以下字段：`FORECAST_MODEL_ENABLED`、`FORECAST_MODEL_BASE_URL`、`FORECAST_MODEL_OUTPUT_DIR`、`FORECAST_CATEGORY_BATCH_MAP_JSON`、`FORECAST_DEFAULT_PRODUCT_LINE=PL003`、`FORECAST_REPORTER=forecast-agent`、`FORECAST_POLL_INTERVAL_SEC=5.0`、`FORECAST_POLL_TIMEOUT_SEC=3600.0`。
- `resolve_output_dir()` 在 `FORECAST_MODEL_OUTPUT_DIR` 为空时固定返回仓库根目录下的 `services/icewash-model`；不得回退到任何旧模型路径。`output_path_for(system_forecast_number)` 固定拼接 `output_{system_forecast_number}.xlsx`。
- 任务完成判定同时检查模型 `/tasks/{id}` 的 `status=completed`、`result.data.saved_success=true`、`result.pg_write.forecast_rows>0`、`result.pg_write.attribution_rows>0`；任一条件失败时 backend 返回明确错误并不写入语义表。

#### 2. 以目标模型 `fcst_*` 为正常结果链路
- 新建 `backend/src/app/services/forecast_relay_ingest.py`，使用 T03 的 PG session，按 `system_forecast_number` 读取目标模型已写入的 `fcst_forecast_result`、`fcst_attribution`；读取 `fcst_history` 时按本次 `category` 和 `sku` 范围过滤历史行。
- 将 `fcst_forecast_result` 映射为 `WorkbenchDatasetRow(dataset='fcst_detail')`：`forecast_month→period`、`category→category`、`series→series`、`status→payload['状态']`、`channel_l3→channel_l3`、`sku→sku`、`final_value→payload['最终预测值']`，payload 保留源行全部英文列并补充 `版本号=system_forecast_number`。
- 将 `fcst_attribution` 映射为 `AttributionAnalysisRow`：`system_forecast_number→version`、`forecast_month→period`、`horizon→horizon`、`category/series/status/channel_l3/sku` 同名映射、`factor_type→attr_type`、`y_pred→y_pred`、`delta_y→impact`；`qty_lag1` 使用 `y_pred-delta_y`，payload 保留源行全部列。
- 将 `fcst_history` 映射为 `ForecastHistoryRow`：`version=system_forecast_number`、`period/category/channel_l3/sku/qty` 映射到 `period/category/channel_l3/sku/retail_qty`，`retail_amt` 为 null，payload 保留源行全部列。
- 同一 `system_forecast_number` 在同一事务内先删除 `fcst_detail`、`AttributionAnalysisRow.version`、`ForecastHistoryRow.version` 的旧语义行，再 append 新行；重复同步不增加行数，事务失败整体回滚。
- `forecast_ingest.py` 保留 `persist_forecast_version_to_workbench(output_path)` 作为离线 Excel 兼容入口；正常 `/api/forecast/runs` 完成后调用 `forecast_relay_ingest.py`，不依赖 backend 读取模型容器内 Excel。

#### 3. 保留五 Sheet Excel adapter 作为离线提取
- 新建 `backend/src/app/services/forecast_excel_adapter.py`，固定支持目标模型 `output_{systemForecastNumber}.xlsx` 的 `result`、`预测详情`、`历史数据`、`白盒归因`、`归因映射` 五个 Sheet；缺失 Sheet 返回空结果而不伪造字段。
- 保留 `ExcelResultAdapter.extract_forecast()`、`extract_attribution()`、`sheet_names()` 和 `normalizer`；日期统一为 `YYYY-MM`，预测期统一为 `N+1` 至 `N+7`，型号/品类/渠道筛选使用显式列候选表。
- `POST /api/forecast/extract` 只允许读取 `FORECAST_MODEL_OUTPUT_DIR` 下的文件名或 `system_forecast_number`，拒绝客户端传入目录穿越路径；Docker 模式通过挂载 `services/icewash-model` 到模型容器 `/app` 保证离线文件可见，正常预测链路不依赖该挂载。

#### 4. 预测 API 和权限
- 新建 `backend/src/app/api/forecast.py`：
  - `POST /api/forecast/runs`：请求字段为 `category/forecast_month/wait/channel/sku/start/end/horizon/intent`，`wait` 默认 true；提交或复用任务，完成后执行 relay sync 并返回 `ok/envelope`；
  - `GET /api/forecast/tasks/{task_id}`：代理目标模型 `/tasks/{task_id}`；
  - `GET /api/forecast/model/health`：检查目标模型 `/health`、配置的 output dir 和 `forecast_model_enabled`；
  - `POST /api/forecast/extract`：仅执行 Excel adapter，不触发预测。
- `/forecast/runs` 使用 `chat:send`；task/health/extract 使用 `chat:read`；上游不可达返回 502，上游任务失败返回 502 并保留模型错误文本。
- `scripts/start_dev_stack.sh` 的 icewash 容器启动配置挂载 `$(pwd)/services/icewash-model:/app`；模型容器工作目录固定为 `/app/cbg_fcst_month`，生成的 `output_*.xlsx` 位于宿主机 `services/icewash-model/`。

#### 5. 测试和幂等校验
- 新增 `backend/tests/test_forecast_model_client.py`：验证 `_normalize_month('2026-08') == '2026-08-01'`、批次 JSON 解析、payload 字段、run key、任务失败和 output dir 路径。
- 新增 `backend/tests/test_forecast_excel_adapter.py`：使用五 Sheet fixture 验证 Sheet 列表、预测期/月份规范化、品类/型号筛选和归因抽取。
- 新增 `backend/tests/test_forecast_relay_ingest.py`：验证三张 `fcst_*` 表到三类语义表的字段映射、PG 事务回滚和同一版本重复同步不增行。

## 完成标准
- 验收命令：
  ```bash
  python /c/Users/jie32.guo/.codex/skills/plan-generator/scripts/plan_state.py lint-plan --plan docs/plans/T06-forecast-model-client-2026-09-01.md
  ```
- 通过条件：命令退出码为 0，且本节保留的原验收项全部满足。
- [ ] `cd backend && uv run pytest -q tests/test_forecast_model_client.py tests/test_forecast_excel_adapter.py tests/test_forecast_relay_ingest.py` 通过。
- [ ] `curl -s http://127.0.0.1:8001/health` 返回 `status=healthy`；`curl -s http://127.0.0.1:8000/api/forecast/model/health` 返回 `upstream.ok=true`、`output_dir` 包含 `services/icewash-model`。
- [ ] Git Bash 执行 `curl -s -X POST http://127.0.0.1:8000/api/forecast/runs -H "Authorization: Bearer $ACCESS_TOKEN" -H "Content-Type: application/json" -d '{"category":"冰箱","forecast_month":"2026-08-01","wait":true}'` 返回 `ok=true` 且 `envelope.table.rows` 非空。
- [ ] 最近一次模型任务完成后，`psql agent_platform -c "SELECT count(*) FROM fcst_forecast_result WHERE system_forecast_number LIKE 'AG_冰箱_%'"`、`psql agent_platform -c "SELECT count(*) FROM fcst_attribution WHERE system_forecast_number LIKE 'AG_冰箱_%'"` 均大于 0；`workbench_dataset_rows` 的 `fcst_detail` 行数、`attribution_analysis_rows` 行数、`forecast_history_rows` 行数也均大于 0。
- [ ] 对同一个 `system_forecast_number` 重复执行 relay sync，三类语义表行数前后一致；`GET /api/forecast/tasks/{task_id}` 在模型重启后仍能返回任务状态。
- [ ] `grep -RInE "reference_repo|冰洗预测模型|services/冰洗预测模型" backend/src/app/services/forecast_model_client.py backend/src/app/services/forecast_excel_adapter.py backend/src/app/services/forecast_relay_ingest.py` 零命中。
