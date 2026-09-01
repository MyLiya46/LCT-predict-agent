# T09 · backup 原生聊天上下文与能力工具（chat-context-capability-tools）

- **任务 ID**：T09
- **标题与目标**：以 backend-backup 的 `LLMProvider`、`engine.loop`、`Conversation/Message`、SSE、trace 和工具注册机制为唯一聊天底座，接入冰洗五项 capability；不迁移 backend-ref 的 intent、planner、规则槽位链、向量记忆和独立聊天表。
- **关联文档章节**：feat-icewash.md §1.1、§3、§6、§10.2、§11.2；backend-backup `engine/loop.py`、`domain/chat_service.py`、`tools/registry.py`、`models/conversation.py`、`models/message.py`；T04、T05、T06、T08
- **前置依赖 blockedBy**：T04、T05、T06、T08
- **状态**：reviewed

## 实施要点

### 1. 保留 backup 聊天编排，不新增 planner
- `backend/src/app/engine/loop.py` 保持唯一执行循环：LLM provider 读取消息和工具 schema，执行 tool call，写入 `MessageEvent`，发布 SSE，执行 retry、checkpoint、连续工具失败熔断和 `MAX_AGENT_ROUNDS=10` 收敛。
- `backend/src/app/domain/chat_service.py` 继续负责创建 `Conversation/Message`、owner 隔离、幂等键、状态机和助手消息终态；T09 不创建新的 `ChatSession`、`ChatMessage`、`chat_sessions` 或 `chat_messages`。
- 不迁移 backend-ref 的 `intent.py`、`planner_react.py`、`planner_tools.py`、`request_analyzer.py`、`dialogue_context.py`、`memory.py`、`session_memory_chunks`；不增加 Turing ReAct planner、正则意图分类或五意图测试。
- LLM 选择 capability 通过 backup 已有 provider 的工具 schema 完成；backend 只校验工具参数、执行工具和归一化输出，不先运行一套 intent/planner 再调用 LLM。

### 2. 新增 backup 原生会话上下文与记忆服务
- 新建 `backend/src/app/services/chat_context.py`，公开 `build_context(session, conversation_id, prompt)`：复用 backup `engine.loop.build_messages_for` 的语义，读取当前用户拥有的 `Conversation` 与 `Message`，按 `conversation.user_max_messages` 默认 48 条取最近 `user/assistant` 消息，按时间正序拼接当前 prompt。
- 新建或扩展 `backend/src/app/services/memory.py`，只使用 T03 已加入的 `Conversation.memory_summary`、`Conversation.memory_slots` 和最近消息；不创建 embedding、向量表或 `memory_chunks` 列。
- `memory_slots` 固定允许键：`category`、`forecast_month`、`horizon`、`sku`、`channel`、`last_capability`、`system_forecast_number`；未知键丢弃，字符串最大 128 字符，`horizon` 限制为 1~12。
- `memory_summary` 最大 2400 个 Unicode 字符；每次完成 assistant 消息后由 `update_memory()` 在同一业务 session 中更新 summary/slots，summary 只保留用户已确认的品类、月份、预测版本、最近 capability 和未完成输入，不生成销量数字。
- 首期不调用 embedding 或 Turing 做记忆检索；T08 的 Turing 仅用于报告/归因解读增强，不参与会话路由和记忆管理。

### 3. 接入五项 capability internal tools
- 在 `backend/src/app/tools/internal/` 增加或汇聚以下工具，工具 schema 由工具文件定义并由 backup registry 暴露给 engine：
  - `get_history`：调用 T04 history 查询，入参 `category` 必填，`sku/channel/start/end` 可选；输出 `response_type="history"` 和 rows。
  - `submit_forecast`：调用 T06 预测提交，入参 `category`、`forecast_month`、`horizon`；输出 `task_id/system_forecast_number`。
  - `get_task_status`：调用 T06 任务查询，入参 `task_id`；输出 `pending/running/completed/failed`。
  - `get_forecast_result`：调用 T06 PG 结果查询，入参 `system_forecast_number`、`horizon`；输出 `response_type="forecast"`、forecast rows 和 envelope。
  - `get_attribution`：调用 T05 PG-only 归因查询，入参 `system_forecast_number`、`category`、`sku`、`period`；输出 `response_type="attribution"` 和 factors。
  - `simulate`：工具入参为 `system_forecast_number`、`strategy_id`、可选 `param`、可选 `traffic_tier`；调用 T05 的 `build_whatif_rows` 从 PG baseline 生成 `sku/channel_l3/category/status/baseline_qty/plan_price/elasticity_coef/elasticity_class` 行，再以 icewash `SimulateRequest(strategy_id,param,traffic_tier,rows)` 提交，输出 task id，不在 backend 计算公式。
  - `optimize`：工具入参为 `system_forecast_number`、`target_qty`、可选 `param`、可选 `traffic_tier`；调用同一 `build_whatif_rows`，再以 icewash `OptimizeRequest(target_qty,param,traffic_tier,rows)` 提交；候选策略由 icewash 根据每行状态和策略目录处理，工具不传 `candidate_strategy_ids`，不在 backend 维护策略目录。
- capability 映射只存在于工具 schema、工具输出的 `response_type` 和前端 renderer；不定义 `Intent` 枚举，不接受 `prior_intent` 作为后端路由条件。
- 五项 capability 的权限固定：history/forecast/explain 查询使用 `chat:read`；simulate/optimize 提交使用 `chat:send`；未登录返回 401，权限不足返回 403，并沿用 backup audit/trace。
- 缺少必填参数时，工具返回结构化 `need_input` 结果并停止当前工具调用；不执行 backend-ref 的正则补槽，不隐式填充品类、月份或 SKU。

### 4. 幂等注册工具与默认场景
- 新增 `backend/seed/v2__icewash_tools.py`，使用 PG advisory lock 和按工具名/场景幂等 upsert，将七个工具绑定到 `sales_query_predict` 场景；重复执行不得创建重复 `tools` 行或重复场景绑定。
- 七个工具的 `execution` 固定为 `{"kind":"internal","handler":"<tool_name>","timeout_s":120}`；`input_schema.type` 固定为 `object`、`additionalProperties=false`，必填字段只列实际调用需要的字段。
- 种子同步写入每个工具的 `description`、`input_schema`、`output_schema` 和 `status="enabled"`；工具 schema 交给 backup `validate_tool_schema` 校验，handler 由 `app.tools.internal.<tool_name>.tool.handle` 加载。
- 更新 `sales_query_predict` 的 system prompt：要求模型直接根据工具 schema 选择 `get_history/submit_forecast/get_attribution/simulate/optimize`，不得输出 intent、planner action 或虚构模型结果；`get_task_status/get_forecast_result` 只作为任务查询辅助工具。

### 5. 聊天工具的异步任务边界
- 工作台 API 保留 taskid 直连契约：`/api/forecast/tasks/{task_id}`、`/api/whatif/tasks/{task_id}` 由前端轮询；聊天 internal tool 不把 taskid 暴露为最终答案的唯一结果。
- `submit_forecast` 在聊天调用中固定调用 T06 `POST /api/forecast/runs` 的 `wait=true`，模型任务完成后直接返回 forecast envelope；失败或超时返回 `tool_error`。
- `simulate` 和 `optimize` 在聊天调用中先调用 T05 提交接口，再以 1 秒间隔调用任务查询，最长等待 120 秒；`completed` 返回 simulation/optimization envelope，`failed` 或超时返回 `tool_error`。
- `get_task_status`、`get_forecast_result` 可由 LLM 在已有 taskid 时调用，但不承担首轮预测的规划职责；T09 不实现第二个 planner loop。

### 6. 能力输出与 frontend 契约
- 工具结果经 backup `tools/dashboard_spec.py` 和 T10 envelope 适配，`response_type` 固定使用 `history`、`forecast`、`attribution`、`report`、`simulation`、`optimization`。
- `explain` 是模型 capability 名称；归因数据使用 `response_type="attribution"`，Turing 生成的业务文字使用 `response_type="report"`，两者都不通过 `intent` 路由。
- `Message.result_envelope` 写入最终 envelope；原始工具完整输出进入 `MessageEvent.payload`，SSE 沿用 backup `status/tool.call/tool.result/done` 事件，不新增 backend-ref 的四事件协议。
- `intent` 若因 frontend-ref 类型仍存在，只作为 nullable 兼容字段，不参与后端执行；旧值映射固定为 `history→history`、`forecast→forecast`、`attribution→attribution`、`whatif→simulation`。后端执行和前端渲染均以 `response_type` 为准，不新增 `Intent` 枚举，不读取 `prior_intent`。

### 7. 测试与迁移边界
- 新增 `backend/tests/test_chat_context.py`：验证 owner 隔离、最近 48 条消息顺序、当前 prompt 拼接、`memory_slots` 白名单/长度/horizon 校验、summary 2400 字符上限。
- 新增 `backend/tests/test_capability_tools.py`：使用 mock T04/T05/T06/icewash client，验证七个工具的 schema、权限、参数透传、`need_input` 和 response_type；断言 simulate/optimize 先按 `system_forecast_number` 读取 PG baseline，再分别透传 `SimulateRequest(strategy_id,param,traffic_tier,rows)` 和 `OptimizeRequest(target_qty,param,traffic_tier,rows)`；断言 backend 不包含策略公式。
- 新增 `backend/tests/test_icewash_tool_seed.py`：重复执行 `seed/v2__icewash_tools.py` 两次，断言默认场景下七个工具各只有一行且 `execution.kind="internal"`。
- 新增 `backend/tests/test_engine_capability_flow.py`：使用 backup mock provider 触发 tool call，验证 `MessageEvent.tool_call/tool_result`、`Message.result_envelope`、SSE done 和连续失败熔断。
- 继续执行 backup 既有 `tests/test_engine.py`、`tests/test_chat.py`、`tests/test_session_stream.py`；不引入 backend-ref SQLite/aiosqlite/`ChatSession`/`ChatMessage`/embedding 依赖。

## 验收标准

- [ ] `uv run pytest tests/test_chat_context.py tests/test_capability_tools.py tests/test_engine_capability_flow.py` 全绿。
- [ ] `uv run pytest tests/test_icewash_tool_seed.py` 全绿；重复执行 seed 后 `SELECT name, count(*) FROM tools GROUP BY name` 的七个工具计数均为 1。
- [ ] `uv run pytest tests/test_engine.py tests/test_chat.py tests/test_session_stream.py` 全绿，backup engine loop、SSE、trace 和状态机无回归。
- [ ] 对五个 capability 各执行一次 mock tool call：history/forecast/explain/simulate/optimize 均进入正确 internal tool；simulate 请求体只含 `strategy_id/param/traffic_tier/rows`，optimize 请求体只含 `target_qty/param/traffic_tier/rows`，两者 rows 均由 PG baseline 生成；backend 源码不含 `%ΔQty`、`STRATEGY_CATALOG` 或 `argmin`。
- [ ] 在同一 PG 中验证 `Conversation.memory_summary`、`Conversation.memory_slots` 可写回并按 owner 隔离；数据库不存在 `chat_sessions`、`chat_messages`、`session_memory_chunks` 表。
- [ ] 缺少 `category` 或 `forecast_month` 时返回 `need_input` 结构化结果，不触发预测接口；请求中携带 `prior_intent` 不改变工具选择。
- [ ] 聊天预测使用 `wait=true` 返回最终 forecast envelope；simulate/optimize 最多每秒轮询一次、总等待不超过 120 秒，任务失败或超时只产生一个 `tool_error`，不启动 planner 重试链。
- [ ] `grep -RInE "from app\.services\.(intent|planner_react|planner_tools|request_analyzer|dialogue_context)|ChatSession|ChatMessage|SessionMemoryChunk|aiosqlite|json_each" backend/src/app/services backend/src/app/tools` 无命中。
