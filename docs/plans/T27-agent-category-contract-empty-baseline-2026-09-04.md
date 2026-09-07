# T27 · Agent optimize 品类契约与空基线保护（agent-category-contract-empty-baseline）

- 任务 ID：T27
- 标题与目标：让聊天 Agent 的 simulate/optimize 始终按明确品类读取 What-if 基线，并在基线为空时返回可诊断错误。
- 关联文档章节：`docs/feat-icewash.md` §3.4、§3.5；T26
- 前置依赖 blockedBy：T26

## 执行画像

- execution_mode：worker
- execution_class：normal
- expected_duration：约 25 分钟
- external_waits：无；seed/运行态检查可选
- checkpoint_phases：工具 schema、空基线保护、契约测试、seed 校验
- resume_boundary：从最后一个未通过的离线验收项继续

## 问题

- `backend/seed/v2__icewash_tools.py` 的 simulate/optimize schema 没有声明 `category`，聊天模型不会稳定提供品类。
- 两个 internal tool 将缺失品类传给 `build_whatif_rows`，精确查询返回空列表；icewash 服务当前允许空 `rows`，任务仍可能被标记为 completed，前端因此看不到推荐策略。
- 该问题发生在 Agent 工具与基线查询的协调层，不是固定候选策略枚举算法失效；页面直接调用 `/api/whatif/optimize` 已能返回候选结果。

## 决策

- 将 `category` 设为 simulate/optimize 工具的必填字符串；缺少时统一返回 `need_input`，不猜测品类。
- internal tool 构造基线后要求至少一行；为空直接返回 `tool_error`，错误包含预测版本和品类，且不调用模型服务。
- icewash `SimulateRequest.rows` 与 `OptimizeRequest.rows` 使用 `min_length=1`；保留当前规则式候选枚举和按目标选择逻辑，不改为大模型生成策略。
- seed schema、工具执行器和回归测试使用相同字段契约；运行 seed 后数据库中的能力定义必须与源码一致。

## 范围

- 包含：Agent 工具 schema/参数校验、simulate/optimize 空基线保护、模型请求 rows 非空约束、工具与模型契约测试、seed 校验。
- 不包含：历史价格回填、策略价格公式、库存周转口径、LLM provider 或候选策略目录改写。

## 环境预检

- 必需 Shell：git-bash
- 必需命令：`backend/.venv/Scripts/python.exe`、`python`、`git`
- 必需端口：无
- 必需 URL：无
- 必需 Python 模块：无
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
  python C:/Users/jie32.guo/.codex/skills/plan-executor/scripts/preflight.py check --plan docs/plans/T27-agent-category-contract-empty-baseline-2026-09-04.md --format json
  ```

## 风险与回滚

- 风险：旧的自然语言调用可能没有品类，改为必填后会进入询问流程；这是避免跨品类读取错误基线所需的行为。通过 need_input 测试和 seed schema 检查监测。
- 回滚：保留模型服务的规则算法不变；如需暂时恢复旧工具调用，可回退 seed/tool schema 与空基线断言，数据库能力定义重新执行 `python -m app.seed_icewash_tools`，不删除预测数据。

## 实施步骤

### 步骤 1：补齐 Agent 工具输入契约

- 对象：`simulate`、`optimize` 的 seed schema 与 internal handler。
- 动作：增加 `category` 字段并列入 required；handler 的 missing 校验包含 `category`，读取基线时传入该值；保持 `target_revenue` 可选。
- 参数：`category` 类型为非空字符串；`system_forecast_number`、`strategy_id`/`target_qty` 原有必填项不变；不将空字符串视为有效品类。
- 核心修改文件：`backend/seed/v2__icewash_tools.py`、`backend/src/app/tools/internal/simulate/tool.py`、`backend/src/app/tools/internal/optimize/tool.py`
- 必要集成文件：无
- 命令：
  ```bash
  backend/.venv/Scripts/python.exe -m pytest -q backend/tests/test_capability_tools.py
  ```

### 步骤 2：阻断空基线进入模型任务

- 对象：simulate/optimize internal handler 与 icewash Pydantic 请求模型。
- 动作：基线行列表为空时返回 `tool_error` 并停止调用；模型请求 `rows` 增加 `min_length=1`，让直接 HTTP 调用也拒绝空任务。
- 参数：错误至少包含 `system_forecast_number`、`category` 和“基线为空”信息；非空 rows 的现有异步 task 结构不变。
- 核心修改文件：`backend/src/app/tools/internal/simulate/tool.py`、`backend/src/app/tools/internal/optimize/tool.py`、`services/icewash-model/cbg_fcst_month/server.py`
- 必要集成文件：无
- 命令：
  ```bash
  backend/.venv/Scripts/python.exe -m pytest -q backend/tests/test_capability_tools.py backend/tests/test_icewash_whatif_contract.py
  ```

### 步骤 3：补充回归断言并校验 schema

- 对象：工具测试、模型请求校验测试和 `v2__icewash_tools` schema。
- 动作：覆盖缺 category 的 need_input、空基线不调用上游、simulate/optimize 的 category 传入和空 rows 被拒绝；校验 `additionalProperties=false` 下 schema 仍合法。
- 参数：至少覆盖 simulate 与 optimize 各一条空基线；非空测试仍断言规则模型被调用且返回原有 response_type。
- 核心修改文件：`backend/tests/test_capability_tools.py`、`backend/tests/test_icewash_whatif_contract.py`
- 必要集成文件：`backend/seed/v2__icewash_tools.py`
- 命令：
  ```bash
  backend/.venv/Scripts/python.exe -m pytest -q backend/tests/test_capability_tools.py backend/tests/test_icewash_whatif_contract.py
  ```

## 完成标准

- 验收类型：offline
- 离线验收命令：
  ```bash
  python C:/Users/jie32.guo/.codex/skills/plan-generator/scripts/plan_state.py lint-plan --plan docs/plans/T27-agent-category-contract-empty-baseline-2026-09-04.md
  backend/.venv/Scripts/python.exe -m pytest -q backend/tests/test_capability_tools.py backend/tests/test_icewash_whatif_contract.py
  python -m py_compile services/icewash-model/cbg_fcst_month/server.py
  ```
- 外部环境验收命令：无
- 通过条件：缺 category 返回 need_input；空基线返回 tool_error 且上游未被调用；非空基线仍能创建任务；模型 rows 空列表在请求校验阶段被拒绝。
