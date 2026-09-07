# T33 · 聊天 What-if 策略矩阵与达成趋势（chat-whatif-strategy-envelope）

- 任务 ID：T33
- 标题与目标：让 Agent 把“制定销售计划”和“如果调整策略会怎样”转换为可执行的 What-if 请求，并返回策略矩阵、达成趋势和可追溯的分析报告。
- 关联文档章节：`docs/feat-icewash.md` §3.4、§4、§10.2；`docs/PRD.md` §7.1；T21、T25、T30、T32
- 前置依赖 blockedBy：T32

## 执行画像

- execution_mode：worker
- execution_class：normal
- expected_duration：约 50 分钟
- external_waits：无；icewash 任务在 T35 验收
- checkpoint_phases：策略参数解析、优化/模拟投影、矩阵/趋势契约、离线回归
- resume_boundary：从最后一个未通过的 What-if 契约测试继续

## 问题

- 当前 `optimize`/`simulate` internal tool 虽然已经调用 icewash 异步任务，但最终只返回任务 payload；聊天 envelope 没有 `result.rows` 里的 Agent 建议策略、六个月达成曲线和 KPI 证据。
- 用户说“帮我制定冰箱下月销售计划”时通常没有目标销量、销售额或策略参数；当前 schema 把 `target_qty`、`strategy_id` 当成必填，Agent 既不能用明确默认值完成，也不能把缺失信息解释给用户。
- What-if 页面已经实现策略目录、六个月型号聚合、双目标优化和价格/成本缺失状态；聊天端如果重新计算或只取前 200 行，会再次产生页面与 Agent 结果不一致。
- “如果我调整了某某策略，之后会怎么样”需要调用 `simulate`；如果 Agent 直接拼接自由文本而不是模型目录中的策略 ID，模型服务会返回错误或执行错误策略。

## 决策

- `optimize` 专用于“制定/推荐/最佳策略”，`simulate` 专用于“如果调整/假设采用某策略”；两者都复用 T22–T30 的 `build_whatif_rows` 和 icewash 公式，不在聊天层复制计算。
- What-if 聊天默认使用工作台相同的 `N+1…N+6` 全量预测期。明确采用【假设：用户说“下月销售计划”时，报告以 N+1 为重点，但目标、矩阵和达成曲线仍按工作台六个月累计口径，避免把月度值和累计目标混画】。
- 缺少优化目标时，使用工作台现有默认目标：`target_qty=80000` 台、`target_revenue=50000000` 元；价格覆盖不足时销售额目标保持缺失并在报告中说明。用户语义中的显式目标优先，例如“4 万台、500 万元”规范化为 `40000`、`5000000`，不被默认值覆盖。
- What-if 的 `system_forecast_number` 优先使用用户已确认的会话/工作区版本；没有已确认版本时，按品类选择 PG 中最新的完整预测基线并在 `meta.assumptions` 披露版本来源；没有完整基线时返回 `need_input(system_forecast_number)`，不静默猜测或调用空基线。
- `simulate` 缺少策略时先调用 T31 的策略目录工具；无法从用户描述唯一映射到 `strategy_id` 时返回带有效候选 ID 的 `need_input`，不调用模型。`param`、`traffic_tier` 只能使用策略目录允许的参数；用户指定 SKU、系列或“主销/新品”等筛选条件时，只对匹配行下发该策略，其余行显式使用 `maintain`。
- 统一 What-if envelope：`response_type=optimization` 或 `simulation`；`chart.type=strategy_dashboard`，cards 固定为 `strategy_matrix` 和 `attainment_trend`；`table` 为完整型号矩阵或模型明细分页投影；`text.metrics/meta` 展示目标、基线、模拟结果、覆盖状态和默认假设。

`strategy_dashboard` 固定使用以下数据形状，避免聊天和工作台各自解释字段：

```json
{
  "type": "strategy_dashboard",
  "cards": [
    {"type": "strategy_matrix", "data": {"columns": [], "rows": [], "total": 0}},
    {"type": "attainment_trend", "data": {
      "months": [], "cumulative": true,
      "baseline": {"qty": [], "amount": []},
      "simulated": {"qty": [], "amount": []},
      "target": {"qty": [], "amount": []}
    }}
  ]
}
```

数组按 `N+1…N+6` 排序；`amount`、毛利或库存数据缺失时使用 `null`，不以 0 代替。

## 范围

- 包含：优化/模拟工具的结果解包、默认目标、策略参数校验、完整型号矩阵与六个月累计趋势投影、缺价格/成本/库存状态、工具和投影测试。
- 不包含：修改 `whatif.py` 的策略公式、重新设计 What-if 页面、补造库存周转数据、把 `get_attribution` 改成优化接口；模型与工作台已有实现继续作为数据源。

## 环境预检

- 必需 Shell：git-bash
- 必需命令：`python`、`backend/.venv/Scripts/python.exe`、`uv`
- 必需端口：无；真实 icewash 服务在 T35 验收
- 必需 URL：无
- 必需 Python 模块：pytest、sqlalchemy、httpx
- 模块检查解释器：backend/.venv/Scripts/python.exe
- 必需 Docker 容器：无
- 容器内必需命令：无
- 容器内必需 Python 模块：无
- 执行画像：normal
- 启动超时（秒）：20
- 空闲超时（秒）：30
- 硬截止（秒）：300
- 最大 checkpoint 间隔（秒）：45
- 预检命令：
  ```bash
  python C:/Users/jie32.guo/.codex/skills/plan-generator/scripts/preflight.py check --plan docs/plans/T33-chat-whatif-strategy-envelope-2026-09-04.md --format json
  ```

## 风险与回滚

- 风险：基线价格或成本覆盖不足会使金额/毛利为空；目标默认值可能被误读成用户明确目标；全量型号矩阵会增大响应体；模型任务超时会让聊天等待过久。通过 coverage/status 字段、默认假设 metadata、前端分页和 120 秒 What-if 轮询监测。
- 回滚：保留现有 `/api/whatif/simulate`、`/api/whatif/optimize` 的任务 ID 和 payload 兼容；若聊天投影失败，退回只返回 task status/error，不影响工作台页面和 T22–T30 已通过的模型任务链路。

## 实施步骤

### 步骤 1：把自然语言策略映射为可执行模型参数

- 对象：`get_whatif_strategies`、`simulate`、`optimize` 的输入校验和 Agent tool message。
- 动作：在调用模型前校验策略 ID、适用状态、参数类型和投流档位；优化缺目标时通过 PG-only baseline helper 读取不受 `limit` 影响的完整 baseline，用工作台默认目标计算目标差距；模拟的策略/参数来自用户描述或策略目录，不把中文策略名称直接发送给模型；策略筛选条件转成逐行 `strategy_id/param`，未命中行使用 `maintain`。
- 参数：优化保留 `system_forecast_number/category` 必填，但将 `target_qty` 改为可选以兼容“制定计划”自然语言；缺失时使用 `target_qty=80000`，价格覆盖完整时使用 `target_revenue=50000000`，显式用户目标优先；优化不要求 `strategy_id`，候选策略仍由 icewash 依据自身目录和行状态选择；模拟缺少唯一策略时返回 `need_input(strategy_id)`；策略参数使用目录 `default_param` 或经过目录范围校验的用户值；What-if 任务轮询间隔 `1s`、最大 `120s`。
- 核心修改文件：`backend/src/app/tools/internal/optimize/tool.py`、`backend/src/app/tools/internal/simulate/tool.py`、`backend/src/app/tools/internal/_capability.py`、`backend/src/app/services/whatif_workbench.py`
- 必要集成文件：`backend/src/app/tools/internal/get_whatif_strategies/tool.py`、`backend/src/app/seed/v2__icewash_tools.py`、`backend/tests/test_capability_tools.py`
- 命令：
  ```bash
  cd backend && uv run pytest -q tests/test_capability_tools.py tests/test_icewash_whatif_contract.py
  ```

### 步骤 2：投影模型结果为完整策略矩阵和累计达成趋势

- 对象：icewash `result.rows`、每型号 `details`、T32 的 `chat_result_projection`。
- 动作：解包 `result.rows`，按 SKU 保留 `strategy_id/strategy_name/param/status/baseline_qty/sim_qty/plan_price/sim_price/sim_amount/sim_gross_profit` 和 coverage；从月份明细生成基线、模拟、目标的累计销量/销售额序列，并按上方固定形状生成 `strategy_dashboard` chart cards。
- 参数：矩阵按全量型号输出，前端负责分页；KPI 汇总使用模型结果和 T23/T25 的全量口径，不受表格页大小影响；`attainment_trend` 的目标数组按总目标在每月的累计分配生成，不能把六个月总目标画成每月固定线；缺价格/成本/库存显示 `null` 与 `status/reason`，库存真实天数为空时不得把 `45天（固定回退标签）` 当作数值；`text.metrics` 只引用模型/PG 返回的结构化结果。
- 核心修改文件：`backend/src/app/services/chat_result_projection.py`、`backend/src/app/tools/internal/optimize/tool.py`、`backend/src/app/tools/internal/simulate/tool.py`、`backend/src/app/services/whatif_workbench.py`
- 必要集成文件：`services/icewash-model/cbg_fcst_month/server.py`、`backend/tests/test_chat_whatif_projection.py`、`backend/tests/test_icewash_whatif_contract.py`
- 命令：
  ```bash
  cd backend && uv run pytest -q tests/test_chat_whatif_projection.py tests/test_icewash_whatif_contract.py
  python -m py_compile services/icewash-model/cbg_fcst_month/server.py services/icewash-model/cbg_fcst_month/whatif.py
  ```

### 步骤 3：验证优化、模拟和缺失数据的聊天 envelope

- 对象：`build_envelope` 的 optimization/simulation 分支和聊天工具事件。
- 动作：固定 fixture 覆盖无目标优化、明确销量/销售额双目标优化、`price_cut`/`traffic_boost` 模拟、主销型号筛选、缺策略、无价格、无成本和无库存数据；断言报告可以引用模型结果，矩阵每行有 Agent 建议策略，图表包含矩阵与累计趋势。
- 参数：优化 fixture 至少 3 个 SKU、6 个月明细；模拟 fixture 至少包含 `maintain` 和一个价格/投流策略，且未命中筛选的 SKU 必须保持 `maintain`；目标达成率分别按销量与销售额展示，不用一个综合布尔值覆盖两个指标；库存状态必须为 `unavailable` 并带原因；目标缺失时断言 `meta.assumptions` 明确披露 8 万台/5000 万元工作台默认目标，显式目标 fixture 断言用户目标优先。
- 核心修改文件：`backend/tests/test_chat_whatif_projection.py`、`backend/tests/test_chat_envelope.py`
- 必要集成文件：`backend/tests/test_capability_tools.py`
- 命令：
  ```bash
  cd backend && uv run pytest -q tests/test_chat_whatif_projection.py tests/test_chat_envelope.py tests/test_capability_tools.py
  ```

## 完成标准

- 验收类型：offline
- 离线验收命令：
  ```bash
  python C:/Users/jie32.guo/.codex/skills/plan-generator/scripts/plan_state.py lint-plan --plan docs/plans/T33-chat-whatif-strategy-envelope-2026-09-04.md
  cd backend && uv run pytest -q tests/test_chat_whatif_projection.py tests/test_chat_envelope.py tests/test_capability_tools.py tests/test_icewash_whatif_contract.py
  python -m py_compile services/icewash-model/cbg_fcst_month/server.py services/icewash-model/cbg_fcst_month/whatif.py
  ```
- 外部环境验收命令：无
- 通过条件：无目标优化使用明确的工作台默认目标并披露；显式用户目标优先且报告包含 baseline/target/simulated 差距；显式策略模拟调用正确的 icewash strategy ID；optimization/simulation envelope 均含 report、strategy matrix、累计达成趋势和数据表；矩阵/KPI 不受 `limit=200` 影响；缺价格、成本、库存不产生虚假 0 或 45 天数值。
