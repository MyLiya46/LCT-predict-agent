# T31 · Agent 预测/归因工作流与证据闭环（agent-forecast-attribution-workflow）

- 任务 ID：T31
- 标题与目标：让 Agent 根据自然语言严格选择历史查询、预测查询、预测归因和 What-if 能力，并把预测证据与归因证据完整回灌给最终报告。
- 关联文档章节：`docs/feat-icewash.md` §3.2、§3.3、§3.4、§4；`docs/PRD.md` §5、§7.1；T09、T10、T30
- 前置依赖 blockedBy：T30

## 执行画像

- execution_mode：worker
- execution_class：normal
- expected_duration：约 45 分钟
- external_waits：无；真实 LLM 与 icewash 服务用于后续验收
- checkpoint_phases：工具 schema、工作流提示词、预测/归因工具、离线回归
- resume_boundary：从最后一个未通过的阶段继续

## 问题

- 当前 `sales_query_predict` 的 system prompt 只描述工具用途，没有把“历史”“未来预测”“预测归因”“策略模拟”区分成可执行工作流；自然语言“预测洗衣机未来 3 个月销量”可能错误调用 `get_history`。
- `get_forecast_result` 的结果有预测月汇总和 TOP5，但 `get_attribution` 只返回单个 SKU/周期的因子表；Agent 在“TOP5 型号趋势并分析”场景中没有稳定的预测结果→归因查询链。
- `get_history`、`submit_forecast`、`get_forecast_result`、`get_attribution` 的工具结果会被分别回灌，最终报告没有强制依据预测结果和归因结果；当前 envelope 也无法表达本轮使用过的多项证据。
- What-if 场景需要查询模型策略目录后再把自然语言转换为可执行 `strategy_id/param`，当前场景没有内部策略目录工具，模型容易生成模型服务不认识的自由文本策略。

## 决策

- 保留 backup-native engine loop，不新增正则意图分类、第二套 planner 或 `prior_intent` 路由；工作流约束写入工具 description、input schema 和 `sales_query_predict` system prompt，最终执行仍由 LLM tool call 完成。
- 固定工具工作流：
  - 包含“历史、过去、近半年实际销售”的请求只调用 `get_history`。
  - 包含“预测、未来、趋势预测、未来 N 个月”的请求必须先调用 `submit_forecast`（已有同品类/基准月的完整结果时复用），再调用 `get_forecast_result`；不得用 `get_history` 替代未来预测。
  - 包含“预测并分析、TOP5 趋势并分析”的请求，根据 `get_forecast_result.top_skus` 选择型号，在请求预测期首月或用户指定期调用 `get_attribution`；报告必须同时使用预测量、预测排名和归因因子。
  - 包含“制定计划、推荐最佳策略”的请求调用 `optimize`；包含“如果调整某策略之后会怎样”的请求调用 `simulate`；`get_attribution` 只负责白盒归因，不承担策略优化。
- 固定参数默认值：品类或预测基准月缺失时分别返回 `need_input(category)` / `need_input(forecast_month)`，不隐式填充；普通预测 horizon 缺失时使用 `3`；What-if 使用工作台既有的 `N+1…N+6` 六个月口径，目标缺失时由 T33 以全量基线汇总作为默认目标并在报告中披露。
- 新增内部 `get_whatif_strategies` 工具，唯一读取 icewash `/whatif/strategies` 的策略目录；Agent 只能从返回的 `id/name/status/param_kind/default_param` 中选择策略。
- 预测、归因和策略工具的输出保留结构化证据字段（`source_tool`、`system_forecast_number`、`category`、`period/horizon`、`sku`），不把 LLM 自己推断的数字写入结构化结果。

## 范围

- 包含：场景 system prompt 与七项既有工具 schema 的工作流约束；`get_forecast_result` 的预测点/TOP5 输出；`get_attribution` 的预测关联字段和白盒数据；内部策略目录工具；工具注册、权限、参数校验和回归测试。
- 不包含：预测模型 `y_pred` 公式、What-if 策略公式、PG 价格/成本同步、六个月 KPI 聚合；这些由 T22–T30 保持为唯一实现来源。

## 环境预检

- 必需 Shell：git-bash
- 必需命令：`python`、`backend/.venv/Scripts/python.exe`、`uv`
- 必需端口：无；外部服务在 T35 验收
- 必需 URL：无
- 必需 Python 模块：pytest、sqlalchemy、pydantic、httpx
- 模块检查解释器：backend/.venv/Scripts/python.exe
- 必需 Docker 容器：无
- 容器内必需命令：无
- 容器内必需 Python 模块：无
- 执行画像：normal
- 启动超时（秒）：20
- 空闲超时（秒）：30
- 硬截止（秒）：240
- 最大 checkpoint 间隔（秒）：45
- 预检命令：
  ```bash
  python C:/Users/jie32.guo/.codex/skills/plan-generator/scripts/preflight.py check --plan docs/plans/T31-agent-forecast-attribution-workflow-2026-09-04.md --format json
  ```

## 风险与回滚

- 风险：system prompt 变更可能使已有 mock provider 的 tool-call 序列变化；预测结果过大时完整明细回灌会增加 LLM 上下文；归因数据缺失时可能使分析请求无法闭环。通过固定工作流测试、输出摘要上限和结构化 `need_input/tool_error` 监测。
- 回滚：保留现有七项工具 schema 与 handler 的兼容字段；若新工作流导致回归，将 `sales_query_predict` 的 prompt 恢复为上一版本、禁用 `get_whatif_strategies` 场景绑定，并保留已落库工具结果，不回滚 T22–T30 的数据契约。

## 实施步骤

### 步骤 1：固化聊天能力工作流与工具 schema

- 对象：`sales_query_predict` system prompt、`backend/seed/v2__icewash_tools.py` 的工具 schema 和场景绑定。
- 动作：补充历史/预测/归因/优化/模拟的触发语义、调用顺序、证据约束、默认参数和失败处理；注册 `get_whatif_strategies`，保持 PG advisory lock、幂等 upsert、`additionalProperties=false` 和 `execution.kind=internal`。
- 参数：`category` 或 `forecast_month` 缺失分别返回结构化 `need_input`，不调用预测接口；预测 `horizon` 缺失默认 `3`；工具超时仍使用预测 `300s`、其它查询/What-if `120s`；策略目录工具超时 `30s`。
- 核心修改文件：`backend/seed/v2__icewash_tools.py`、`backend/src/app/tools/internal/get_whatif_strategies/tool.py`
- 必要集成文件：`backend/src/app/tools/internal/__init__.py`、`backend/tests/test_icewash_tool_seed.py`、`backend/tests/test_capability_tools.py`
- 命令：
  ```bash
  cd backend && uv run pytest -q tests/test_icewash_tool_seed.py tests/test_capability_tools.py
  ```

### 步骤 2：补齐预测结果到归因查询的证据字段

- 对象：`get_forecast_result`、`get_attribution` 及其调用的 `forecast_model_client`/`attribution_workbench` 查询。
- 动作：让预测结果返回按 `horizon/period` 排序的预测点、品类总量和 `top_skus` 月度序列；让归因结果返回 `y_pred`、`qty_lag1`、`waterfall/type_impacts`、预测曲线所需的 `trend` 和因子明细，并保留单 SKU/单期输入兼容。
- 参数：预测输出至少包含 `system_forecast_number/category/horizon/period/sku/forecast_qty`；TOP5 按预测请求范围内的累计 `forecast_qty` 降序、SKU 升序打破并列；归因默认期为首个预测期 `N+1`，用户显式提供 `period` 时优先使用；缺数据返回 `tool_error` 或结构化空结果，不用历史销量替代预测值。
- 核心修改文件：`backend/src/app/tools/internal/get_forecast_result/tool.py`、`backend/src/app/tools/internal/submit_forecast/tool.py`、`backend/src/app/tools/internal/get_attribution/tool.py`、`backend/src/app/services/attribution_workbench.py`
- 必要集成文件：`backend/src/app/tools/internal/_capability.py`、`backend/tests/test_capability_tools.py`、`backend/tests/test_attribution_whatif_service.py`
- 命令：
  ```bash
  cd backend && uv run pytest -q tests/test_capability_tools.py tests/test_attribution_whatif_service.py
  ```

### 步骤 3：验证“预测不是历史、报告使用预测和归因”工作流

- 对象：backup mock provider 的多轮 tool call、engine tool message 回灌和工具结果事件。
- 动作：新增固定序列测试：普通历史问题只调用 `get_history`；普通预测问题依次调用 `submit_forecast/get_forecast_result`；TOP5 分析问题先取预测 TOP5，再逐个或按约定期调用 `get_attribution`；断言最终模型可见的 tool message 同时包含预测证据和归因证据。
- 参数：预测场景最多执行 `submit_forecast + get_forecast_result + 5` 个归因调用；总轮数不超过现有 `MAX_AGENT_ROUNDS=10`；报告文本中的数字只从 mock 工具输出读取，不能从 history 输出读取。
- 核心修改文件：`backend/tests/test_agent_forecast_workflow.py`、`backend/src/app/engine/loop.py`
- 必要集成文件：`backend/tests/test_engine_capability_flow.py`、`backend/src/app/services/chat_context.py`
- 命令：
  ```bash
  cd backend && uv run pytest -q tests/test_agent_forecast_workflow.py tests/test_engine_capability_flow.py
  ```

## 完成标准

- 验收类型：offline
- 离线验收命令：
  ```bash
  python C:/Users/jie32.guo/.codex/skills/plan-generator/scripts/plan_state.py lint-plan --plan docs/plans/T31-agent-forecast-attribution-workflow-2026-09-04.md
  cd backend && uv run pytest -q tests/test_icewash_tool_seed.py tests/test_capability_tools.py tests/test_attribution_whatif_service.py tests/test_agent_forecast_workflow.py tests/test_engine_capability_flow.py
  ```
- 外部环境验收命令：无
- 通过条件：计划 lint 退出码为 0；历史问题不触发预测工具；预测问题不触发 `get_history`；TOP5 分析的 tool message 同时含预测结果和归因结果；缺少品类返回 `need_input(category)`；策略目录工具只返回 icewash 目录中的有效策略。
