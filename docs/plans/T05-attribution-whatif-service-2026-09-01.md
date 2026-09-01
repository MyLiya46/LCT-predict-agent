# T05 · 归因+whatif 域服务迁入（attribution-whatif-service）

- **任务 ID**：T05
- **标题与目标**：让 backend 从 PG 语义表提供归因工作台和 What-if baseline，并代理 `services/icewash-model/cbg_fcst_month/server.py` 的策略目录与 taskid 接口；T05 不直接读取模型 Excel，也不复制 What-if 规则。
- **关联文档章节**：`docs/feat-icewash.md` §3.3、§3.4、§3.5；`backend-ref/app/services/attribution_workbench.py`、`backend-ref/app/services/whatif_workbench.py`、`backend-ref/app/api/routes.py`；`services/icewash-model/cbg_fcst_month/whatif.py`、`pg_sync.py`、`server.py`
- **前置依赖 blockedBy**：T03、T06
- **状态**：reviewed

## 实施要点

### 1. 归因和 baseline 服务只读 PG
- 新建 `backend/src/app/services/attribution_workbench.py`，只迁入 `filter_options`、`list_skus`、`sku_detail`、`trend_series`；查询 T03 的 `AttributionAnalysisRow` 与 `ForecastHistoryRow`，删除 `MODEL_DIR`、`find_excel_files`、`read_excel` 和 Excel 入库函数。
- T06 的 `forecast_ingest.py` 是预测输出 Excel 写入 `attribution_analysis_rows`/`forecast_history_rows` 的唯一 backend 入口；目标模型 `pg_sync.py` 继续写 `fcst_forecast_result`/`fcst_attribution`/`fcst_history` 中转表，T05 不重复解析输出文件。
- 迁入 `backend/src/app/services/whatif_workbench.py` 的 `load_baseline` 时删除 `find_excel_by_version`、`_pick_detail_sheet`、`_read_detail_df` 和 Excel 优先分支；基线按 PG 查询：预测量来自 `AttributionAnalysisRow`，计划价格来自 `WorkbenchDatasetRow(dataset='fcst_detail')`，缺失时再从 `price_data` 取 `daily_price_n/min_price_n`，价格弹性来自 T04 的 `price_elasticity`。
- baseline 返回 `ok/source/category/version/period/months/items/summary/total/elasticity_hits`；`source` 固定为 `db`，每个 item 保留 frontend-ref 所需的 `sku/status/series/plan_price/baseline_qty/baseline_amount/sim_qty/elasticity`。
- 归因查询直接使用 SQLAlchemy PG 列和 Python `payload` 字典，不引入 SQLite `json_each` 或新的 JSON SQL 方言转换。

### 2. 对齐 frontend-ref 的归因 API
- 新建 `backend/src/app/api/attribution.py`，所有接口使用 `Depends(require_perm("chat:read"))`：
  - `GET /api/attribution/options`：无参数，返回非空的 `category/version/status` 数组；
  - `GET /api/attribution/skus`：必填 `category/version`，可选 `status/keyword/period/tag/limit`，`limit` 默认 `200`，保留 `tag=全部|新品|主销|淘汰|Top5|Top10`；
  - `GET /api/attribution/detail`：必填 `category/version/sku`，可选 `channel_l1/channel_l3/period`，返回 `waterfall/type_impacts/meta/y_pred/qty_lag1`；
  - `GET /api/attribution/trend`：必填 `category/version/sku`，可选 `channel_l1/channel_l3`，返回 `periods/history/forecast/horizons/split_period`。
- 将 `AttributionAnalysisRow.horizon` 限定为 `N+1` 至 `N+6` 的预测行；`sku_detail` 按 `qty_lag1` 为基线、按 `attr_type` 汇总影响量，排除 payload 中 `影响因子=MA_vs_qty_lag1` 的重复解释项。

### 3. 代理 icewash What-if 契约
- 新建 `backend/src/app/services/icewash_whatif_client.py`，固定使用 `ICEWASH_BASE_URL`（默认 `http://127.0.0.1:8001`），请求超时 10 秒，失败最多重试 3 次、间隔 1 秒；不 import 或复制 `whatif.py` 的 `STRATEGY_CATALOG` 和公式。
- 新建 `backend/src/app/api/whatif.py`：
  - `GET /api/whatif/strategies?status=` → 转发 `GET /whatif/strategies?status=`，返回模型原始 `strategies/traffic_tiers/total`；
  - `GET /api/whatif/baseline` → 调用 PG-only `load_baseline`，必填 `category/version`，可选 `period`，`limit` 默认 `200`；
  - `POST /api/whatif/simulate` → 使用模型 `SimulateRequest` 字段 `strategy_id/param/traffic_tier/rows` 转发 `POST /simulate`，只返回模型的 `task_id/status`；
  - `POST /api/whatif/optimize` → 使用模型 `OptimizeRequest` 字段 `target_qty/param/traffic_tier/rows` 转发 `POST /optimize`，只返回模型的 `task_id/status`；
  - `GET /api/whatif/tasks/{task_id}` → 转发 `GET /tasks/{task_id}`，返回 `status/progress/result/error_message`。
- `GET` 查询接口使用 `chat:read`；simulate/optimize 提交使用 `chat:send`；未登录返回 401，缺少对应权限返回 403，icewash 非 2xx 转换为 backend 明确的 502 错误。
- T09 的聊天工具不得把 `system_forecast_number`、`assumptions` 或 `candidate_strategy_ids` 直接发送到 icewash；新增共享 `build_whatif_rows(system_forecast_number, category, limit=200)`，从 PG baseline 生成每个 SKU 的 `sku/channel_l3/category/status/baseline_qty/plan_price/elasticity_coef/elasticity_class`，再由 T05 client 组装 icewash 的标准请求体：simulate 使用 `strategy_id/param/traffic_tier/rows`，optimize 使用 `target_qty/param/traffic_tier/rows`。

### 4. 测试和数据验证
- 新增 `backend/tests/test_attribution_whatif_service.py`：使用 PG 测试数据验证 options 三组非空、`tag=Top5` 最多 5 行、detail waterfall、trend 的历史/预测分界、baseline 的 `source=db` 和 `elasticity_hits`。
- 新增 `backend/tests/test_icewash_whatif_client.py`：使用固定 mock response 验证 strategies、simulate、optimize、task status 的路径、请求体、超时重试和错误码映射。
- 测试夹具只写 T03 的 PG 表，不读取 `docs/`、`reference_repo/` 或 `services/icewash-model` 下的 Excel；T06 完成后再用真实模型产物做集成验收。

## 验收标准
- [ ] `cd backend && uv run pytest -q tests/test_attribution_whatif_service.py tests/test_icewash_whatif_client.py` 通过。
- [ ] curl 验收前执行 `: "${ACCESS_TOKEN:?export backup access JWT}"`、`VERSION=$(psql agent_platform -Atqc "SELECT version FROM attribution_analysis_rows WHERE version IS NOT NULL ORDER BY version DESC LIMIT 1")`、`CATEGORY=$(psql agent_platform -Atqc "SELECT category FROM attribution_analysis_rows WHERE version='$VERSION' AND category IS NOT NULL LIMIT 1")`、`SKU=$(psql agent_platform -Atqc "SELECT sku FROM attribution_analysis_rows WHERE version='$VERSION' AND sku IS NOT NULL LIMIT 1")`，并断言三个变量非空；后续命令使用 `$VERSION/$CATEGORY/$SKU`，不依赖固定历史版本或 SKU。
- [ ] `curl -s -H "Authorization: Bearer $ACCESS_TOKEN" "http://127.0.0.1:8000/api/attribution/options"` 返回 `category/version/status` 三组非空数组。
- [ ] `curl -s -H "Authorization: Bearer $ACCESS_TOKEN" "http://127.0.0.1:8000/api/attribution/skus?category=${CATEGORY}&version=${VERSION}&tag=Top5&limit=200"` 返回 `items/total`，且 `items` 数量不超过 5。
- [ ] `curl -s -H "Authorization: Bearer $ACCESS_TOKEN" "http://127.0.0.1:8000/api/attribution/detail?category=${CATEGORY}&version=${VERSION}&sku=${SKU}"` 返回 `ok=true`、`waterfall` 和 `type_impacts`。
- [ ] `curl -s -H "Authorization: Bearer $ACCESS_TOKEN" "http://127.0.0.1:8000/api/whatif/baseline?category=${CATEGORY}&version=${VERSION}"` 返回 `source=db`、`items/summary/elasticity_hits`，且 `items` 非空。
- [ ] `curl -s -H "Authorization: Bearer $ACCESS_TOKEN" "http://127.0.0.1:8000/api/whatif/strategies"` 返回目标模型的 8 条策略；`POST /api/whatif/simulate` 与 `POST /api/whatif/optimize` 返回 `task_id`，轮询 `/api/whatif/tasks/{task_id}` 最终得到 `status=completed`。
- [ ] `psql agent_platform -c "SELECT count(*) FROM attribution_analysis_rows"` 和 `psql agent_platform -c "SELECT count(*) FROM forecast_history_rows"` 均大于 0；`grep -RInE "MODEL_DIR|read_excel|冰洗预测模型|reference_repo" backend/src/app/services/attribution_workbench.py backend/src/app/services/whatif_workbench.py` 零命中。
