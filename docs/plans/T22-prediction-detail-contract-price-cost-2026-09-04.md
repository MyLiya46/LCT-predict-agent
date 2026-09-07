# T22 · 预测明细契约与价格持久化（prediction-detail-contract-price-cost）

- 任务 ID：T22
- 标题与目标：让 What-if 可读取的预测明细稳定包含版本、月份、预测期、型号、渠道、预测销量、计划输入价，并为成本价关联预留明确状态。
- 关联文档章节：`docs/feat-icewash.md` §3.1、§3.2、§3.3；T21
- 前置依赖 blockedBy：T21

## 执行画像

- execution_mode：direct
- execution_class：normal
- expected_duration：约 30 分钟
- external_waits：PG migration、模型服务离线编译
- checkpoint_phases：PG 中转列、模型同步帧、预测明细契约测试
- resume_boundary：从最后一个未通过的离线验收项继续

## 问题

- `pipeline.py` 已生成 `plan_price`，但 `pg_sync.py` 写入 `fcst_forecast_result` 时丢弃该字段。
- `FcstForecastResult` 与对应迁移未声明计划输入价，relay 后的 `fcst_detail` 只能可靠提供预测数量。
- What-if 需要在同一条明细上区分版本、月份、预测期、型号、渠道、预测销量和计划输入价，当前字段名称分散在英文列、中文 payload 和兼容别名中。

## 决策

- 在模型中转表 `fcst_forecast_result` 增加可空 `plan_price` 数值列；使用模型流水线的月度计划价格，不从其它价格批次隐式回填。
- relay payload 输出标准字段：`version`、`month`、`forecast_period`、`sku`、`channel`、`forecast_qty`、`plan_price`；What-if 解析后另产出 `baseline_price`，不再把计划价命名为 `forecast_price`。
- 成本价继续由 `cost_data` 按品类+型号关联；没有匹配时传递 `null` 和覆盖状态，不按零成本处理。

## 范围

- 包含：模型 PG 同步帧、`fcst_forecast_result` ORM 与 Alembic 迁移、relay 明细 payload、契约单元测试。
- 不包含：库存周转计算、页面聚合布局、策略评分算法；这些由 T23–T25 处理。

## 环境预检

- 必需 Shell：git-bash
- 必需命令：`python`、`backend/.venv/Scripts/python.exe`、`git`
- 必需端口：无
- 必需 URL：无
- 必需 Python 模块：`pandas`、`sqlalchemy`、`alembic`
- 必需 Docker 容器：无
- 容器内必需命令：无
- 容器内必需 Python 模块：无
- 执行画像：normal
- 启动超时（秒）：10
- 空闲超时（秒）：30
- 硬截止（秒）：180
- 最大 checkpoint 间隔（秒）：45
- 预检命令：
  ```bash
  python C:/Users/jie32.guo/.codex/skills/plan-generator/scripts/preflight.py check --plan docs/plans/T22-prediction-detail-contract-price-cost-2026-09-04.md --format json
  ```

## 风险与回滚

- 风险：旧 PG 环境尚未运行新迁移时，模型写入价格列可能失败；影响是新预测无法通过 relay 提供价格，但历史数量数据仍可保留。通过迁移前后 schema 检查和同步帧测试监测。
- 回滚：执行 Alembic downgrade 回退 `plan_price` 列，并回滚 `pg_sync.py`、relay payload 与对应测试；不删除已有预测行。

## 实施步骤

### 步骤 1：增加计划价格中转列
- 对象：`FcstForecastResult` ORM、Alembic 迁移 `0005`。
- 动作：增加 nullable `plan_price FLOAT`，并保持 pandas append 可写入旧版本数据。
- 参数：迁移 revision 按当前 head 创建；列名固定为 `plan_price`；down_revision 指向 `0004`。
- 核心修改文件：`backend/src/app/models/fcst_relay.py`、`backend/alembic/versions/0005_fcst_forecast_plan_price.py`
- 必要集成文件：无
- 命令：
  ```bash
  cd backend && .venv/Scripts/python.exe -m alembic current
  ```

### 步骤 2：保存并暴露预测明细契约
- 对象：`forecast_to_pg_frame`、`_add_detail` 和模型预测明细 payload。
- 动作：保存 `plan_price`；relay 后生成统一字段，月份统一为 `YYYY-MM`，预测期取 `horizon`，数量取 `final_value`。
- 参数：版本取 `system_forecast_number`；渠道取 `channel_l3`；价格为空保持 `null`；不得从无版本匹配的价格批次回填。
- 核心修改文件：`services/icewash-model/cbg_fcst_month/pg_sync.py`、`backend/src/app/services/forecast_relay_ingest.py`
- 必要集成文件：`backend/src/app/models/relay.py`
- 命令：
  ```bash
  backend/.venv/Scripts/python.exe -m pytest -q backend/tests/test_forecast_relay_ingest.py
  ```

### 步骤 3：锁定同步帧契约
- 对象：预测 PG 帧和 relay payload 测试夹具。
- 动作：添加带计划价格、空计划价格、多渠道、多月份的断言，验证七个预测字段和版本字段均可追踪。
- 参数：至少覆盖 `plan_price=1999.0` 与 `plan_price=None` 两种输入；断言空价格不被转换为 `0`。
- 核心修改文件：`backend/tests/test_forecast_relay_ingest.py`、`backend/tests/test_prediction_detail_contract.py`
- 必要集成文件：无
- 命令：
  ```bash
  backend/.venv/Scripts/python.exe -m pytest -q backend/tests/test_forecast_relay_ingest.py backend/tests/test_prediction_detail_contract.py
  ```

## 完成标准
- 验收类型：offline
- 离线验收命令：
  ```bash
  python -m py_compile services/icewash-model/cbg_fcst_month/pg_sync.py
  cd backend && .venv/Scripts/python.exe -m pytest -q tests/test_forecast_relay_ingest.py tests/test_prediction_detail_contract.py
  .venv/Scripts/python.exe -m alembic current
  ```
- 外部环境验收命令：无
- 通过条件：迁移 current 显示 `0005 (head)`；同步帧和 relay 测试全部通过；价格有值时保留原数值，价格缺失时返回 `null`。
