# T28 · 历史销售额持久化与 What-if 基准价解析（historical-price-baseline-resolution）

- 任务 ID：T28
- 标题与目标：保存历史销售额并让未来六个月的 What-if 基线价格默认取型号/渠道已知历史最后有效月的成交均价。
- 关联文档章节：`docs/feat-icewash.md` §3.1、§3.2、§3.3；T26
- 前置依赖 blockedBy：T26

## 执行画像

- execution_mode：worker
- execution_class：long-infra
- expected_duration：约 40 分钟
- external_waits：PG migration；真实 CSV/PG 同步可选
- checkpoint_phases：历史列与迁移、模型同步、relay 映射、基准价解析、回归测试
- resume_boundary：从最后一个未通过的数据库或基线价格验收项继续

## 问题

- 原始历史数据有 `retail_qty` 和 `retail_amt`，但 `pg_sync.history_to_pg_frame()` 只写销量；`fcst_history` 和 relay 的 `ForecastHistoryRow.retail_amt` 因此为空。
- 预测结果计划价行按预测版本精确过滤，而预测版本形如 `AG_...`、价格来源版本可能是 `JG_...`，导致 What-if 明细没有可用计划价。当前“真实数据缺少价格”实际是“基线价格解析链没有产出有效价格”，不是原始输入绝对没有价格字段。
- 旧基线把计划/历史价格写入 `forecast_price`，字段存在但语义不清，模型也无法区分有效基线价和缺失价；后续策略会把空价格当成 0，销售额随之失真。

## 决策

- 在 `fcst_history` 增加可空 `retail_amt`，由迁移 `0006`（`down_revision=0005`）管理；同步帧用原始 `retail_amt` 数值写入。
- relay 的历史行完整传递 `retail_amt`，不改变历史版本的现有隔离方式。
- What-if 价格解析顺序固定为：同一预测明细的 `plan_price` → 按型号/月匹配 `price_data` 计划价（允许价格批次版本不同）→ 同型号同渠道在预测开始月之前最后一个有效历史月的 `retail_amt / retail_qty` → `null`；解析结果统一命名为 `baseline_price`。
- 历史价格按型号+渠道优先；渠道没有历史时才回退到同型号跨渠道汇总。找到的历史最后有效月价格作为该型号未来六个月“维持现状”的统一基准，不按每个预测月重新漂移。
- 明细保留 `price_source`、`price_base_month` 和 `price_status`；任何无法计算的价格保持 `null`，不得转成 0。

## 范围

- 包含：模型 `fcst_history` ORM/迁移/历史同步、backend relay 历史金额映射、What-if 历史价格查询与明细契约、价格来源字段和测试。
- 不包含：策略折扣/套购公式、库存周转计算、Agent 自由生成策略、预测模型 LightGBM 逻辑改写。

## 环境预检

- 必需 Shell：git-bash
- 必需命令：`backend/.venv/Scripts/python.exe`、`python`、`git`
- 必需端口：无
- 必需 URL：无
- 必需 Python 模块：无
- 必需 Docker 容器：无
- 容器内必需命令：无
- 容器内必需 Python 模块：无
- 执行画像：long-infra
- 启动超时（秒）：15
- 空闲超时（秒）：60
- 硬截止（秒）：300
- 最大 checkpoint 间隔（秒）：60
- 预检命令：
  ```bash
  python C:/Users/jie32.guo/.codex/skills/plan-executor/scripts/preflight.py check --plan docs/plans/T28-historical-price-baseline-resolution-2026-09-04.md --format json
  ```

## 风险与回滚

- 风险：旧 PG 尚未执行 `0006` 时，模型同步写入 `retail_amt` 会失败；版本不匹配的计划价格若被无条件采用可能污染基线。通过迁移 current、来源字段和“计划优先/匹配月份”测试监测。
- 回滚：执行 `cd backend && .venv/Scripts/python.exe -m alembic downgrade 0005` 回退新列；回退同步/relay/基线解析变更后重新执行 `0005` head，保留已有预测和历史行，不清空业务表。

## 实施步骤

### 步骤 1：持久化历史销售额

- 对象：`FcstHistory`、`fcst_history` 表、模型历史 CSV 转换。
- 动作：增加 nullable `retail_amt` 列和 `0006` 迁移；`history_to_pg_frame()` 读取原始 `retail_amt` 并进行数值化。
- 参数：列名固定为 `retail_amt`；迁移 `revision=0006`、`down_revision=0005`；空金额仍为 SQL `NULL`；同步继续按原有 delete + append 事务执行。
- 核心修改文件：`backend/src/app/models/fcst_relay.py`、`backend/alembic/versions/0006_fcst_history_retail_amt.py`、`services/icewash-model/cbg_fcst_month/pg_sync.py`
- 必要集成文件：无
- 命令：
  ```bash
  cd backend && .venv/Scripts/python.exe -m alembic current
  ```

### 步骤 2：relay 历史金额并扩展价格来源字段

- 对象：`_add_history()`、`load_baseline()` 的数据读取和明细构造。
- 动作：将 `FcstHistory.retail_amt` 映射到 `ForecastHistoryRow.retail_amt`；查询同品类相关历史行，按 SKU/渠道和预测开始月解析最后有效均价；修正价格行存在但值为 null 时的回退顺序。
- 参数：有效历史价要求 `retail_qty > 0` 且 `retail_amt` 非空；均价为同月 `sum(retail_amt)/sum(retail_qty)`；历史周期必须严格早于首个预测月；优先 exact channel，次选 SKU 全渠道；价格计划 fallback 必须匹配 SKU 与预测月。
- 核心修改文件：`backend/src/app/services/forecast_relay_ingest.py`、`backend/src/app/services/whatif_workbench.py`
- 必要集成文件：`backend/src/app/models/relay.py`（仅在字段契约需要时保持 `retail_amt` 映射）
- 命令：
  ```bash
  backend/.venv/Scripts/python.exe -m pytest -q backend/tests/test_forecast_relay_ingest.py backend/tests/test_attribution_whatif_service.py backend/tests/test_prediction_detail_contract.py
  ```

### 步骤 3：锁定价格来源契约

- 对象：PG 帧、relay payload、What-if baseline 测试。
- 动作：增加历史金额、历史最后月价格、计划价格 fallback、无价格四类夹具；断言六个月明细均带解析价格或明确缺失状态，且 `baseline_amount` 只由有效价格参与。
- 参数：至少覆盖历史 `retail_qty=90、retail_amt=900` 得到基线价格 10；覆盖预测版本与价格批次版本不同；覆盖 `plan_price=None` 仍能得到历史基线或明确缺失状态。
- 核心修改文件：`backend/tests/test_forecast_relay_ingest.py`、`backend/tests/test_attribution_whatif_service.py`、`backend/tests/test_prediction_detail_contract.py`
- 必要集成文件：无
- 命令：
  ```bash
  backend/.venv/Scripts/python.exe -m pytest -q backend/tests/test_forecast_relay_ingest.py backend/tests/test_attribution_whatif_service.py backend/tests/test_prediction_detail_contract.py
  ```

## 完成标准

- 验收类型：mixed
- 离线验收命令：
  ```bash
  python C:/Users/jie32.guo/.codex/skills/plan-generator/scripts/plan_state.py lint-plan --plan docs/plans/T28-historical-price-baseline-resolution-2026-09-04.md
  python -m py_compile services/icewash-model/cbg_fcst_month/pg_sync.py
  backend/.venv/Scripts/python.exe -m pytest -q backend/tests/test_forecast_relay_ingest.py backend/tests/test_attribution_whatif_service.py backend/tests/test_prediction_detail_contract.py
  ```
- 外部环境验收命令：`cd backend && .venv/Scripts/python.exe -m alembic current`
- 通过条件：migration head 为 `0006`；历史金额可在 fcst_history/relay 中追踪；已有历史的 SKU 价格来源为最后有效历史月；价格批次版本不同仍能按 SKU/月 fallback；无价格保持 null 且不产生虚假销售额。
