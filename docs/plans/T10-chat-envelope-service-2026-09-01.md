# T10 · 聊天 façade、envelope 归一化与兼容 SSE（chat-envelope-service）

- 任务 ID：T10
- **标题与目标**：在 backup 原生会话/消息/engine loop 之上增加 `/api` 工作台 façade，把 native trace/SSE 事件归一为 frontend-ref 可消费的裸 JSON 与 `status/result/done` SSE，并将最终 `response_type` envelope 写入 `messages.result_envelope`。
- **关联文档章节**：`docs/feat-icewash.md` §3、§6、§10.2、§11.2；backup `src/app/domain/chat_service.py`、`src/app/engine/loop.py`、`src/app/api/chat.py`、`src/app/sse/hub.py`；frontend-ref `src/api.ts`、`src/store.ts`；T07、T08、T09
- 前置依赖 blockedBy：T09、T07

## 问题
- 任务 T10 当前需要完成本计划标题对应的交付；旧版计划结构无法被 plan-generator v1.2.0 的结构化校验直接读取。

## 决策
- 保留本计划既有技术边界、参数、实施内容和验收命令；仅补齐 v1.2.0 要求的元数据、章节与结构化执行入口。

## 范围
- 包含：本计划既有实施要点、涉及路径、接口、数据约束和验收项。
- 不包含：改变任务目标、blockedBy 依赖、代码实现或项目业务口径。

## 风险与回滚
- 风险：旧计划正文中的命令或外部服务依赖可能在执行环境中不可用，导致该任务验收失败。
- 回滚：执行前保存本任务涉及文件的补丁；失败时使用 `git apply -R /tmp/T10-plan.patch` 反向应用补丁并恢复前一阶段。

## 实施步骤

### 步骤 1：执行原计划实施内容
- 对象：T10 对应的目标模块、接口和验收对象。
- 动作：按下方保留的原实施内容执行，并使用其中的命令完成验证。
- 参数：严格使用正文中给出的路径、端口、字段、超时、权限和命令参数。
- 文件：docs/plans/T10-chat-envelope-service-2026-09-01.md
- 命令：
  ```bash
  python /c/Users/jie32.guo/.codex/skills/plan-generator/scripts/plan_state.py lint-plan --plan docs/plans/T10-chat-envelope-service-2026-09-01.md
  ```
#### 1. 固定聊天底座与 façade 边界

- 保留 backup `backend/src/app/domain/chat_service.py` 的 `create_conversation`、`get_conversation`、`list_conversations`、`rename_conversation`、`pin_conversation`、`send_message`、`stop_message`，保留 `backend/src/app/engine/loop.py` 的 `run_flow`、工具调用、retry、checkpoint、trace、owner 隔离和 native Hub 广播。
- 保留 backup 原生 `/api/v1/chat/conversations/*` 路由及其 `{code,message,data}` 响应；T10 新增的 `/api/*` 路由不调用 backend-ref `run_chat`/`run_chat_sse`，不创建 `ChatSession`、`ChatMessage` 或第二套 agent loop。
- 新建 `backend/src/app/services/chat_bridge.py` 作为唯一 façade 适配层，并新建 `backend/src/app/api/chat_facade.py` 注册 `/api/sessions`、`/api/chat`、`/api/chat/stream`、`/api/products`；所有工作台路由均通过 `get_current_user` 和 `require_perm` 取得当前用户。
- `/api` façade 返回 frontend-ref 当前 `api.ts` 需要的裸 JSON；backup 的 `/api/v1` 路由继续使用壳的统一响应格式，两个响应格式不得混用。
- `ChatRequest` 固定接受 `message`（1~65536 字符）、`session_id`（UUID 字符串或 null）、`params`（对象）、`oa`（可选字符串）和 `access_token`（可选 OAuth access token）。HTTP `Authorization` 只接受 T07 签发的 backup JWT；`access_token` 只作为 T08 网关的 `inputs.new_token`，不得写入 PG、不得替代 HTTP JWT。
- 为支持上述请求级 token，在 backup `domain/chat_service.py` 的 `send_message()` 增加 `oa: str | None`、`oauth_access_token: str | None` 参数，在 `engine/loop.py` 的 `RunContext` 增加同名临时字段，并把非空值仅放入本轮 provider config；T08 gateway provider 读取 `oauth_access_token` 生成 `inputs.new_token`，普通 backup provider 忽略这两个字段。请求完成后不把字段写入 `Conversation`、`Message`、`MessageEvent`、checkpoint 或日志。

#### 2. 会话 façade 与 owner 隔离

- `GET /api/sessions` 调用 backup `list_conversations(session, ctx.id, limit=100)`，返回其中的 `items` 数组本身，字段固定为 `id/title/status/pinned/pinned_at/created_at/updated_at`；不返回 `{code,message,data}`。
- `PATCH /api/sessions/{id}` 接受 `{title?: string, pinned?: boolean}`，至少提供一个字段；`title` 最大 255 字符并调用 `rename_conversation`，`pinned=true` 前查询当前用户已置顶会话数，达到 5 个且目标未置顶时返回 HTTP 400，`pinned` 变更调用 `pin_conversation`，最后返回完整会话摘要。
- `GET /api/sessions/{id}` 先调用 backup `get_conversation(session, id, ctx.id)` 做 owner 校验，再按 `Message.created_at ASC` 查询该会话的 `user/assistant` 消息，返回 `{id,title,messages}`；每条消息返回 `id/role/content/result_envelope/created_at`，助手消息直接透传 T10 写入的 JSONB envelope。
- 会话不存在、已删除或访问其他用户会话统一返回 HTTP 404；不通过错误内容泄漏会话是否存在。无认证返回 HTTP 401，无 `chat:read`/`chat:send` 权限分别返回 HTTP 403。

#### 3. 统一 turn 生命周期与 native Hub 事件消费

- `chat_bridge.start_turn()` 在 `session_id=null` 时先用 backup `create_conversation(ctx.id, "新会话")` 创建会话；已有 `session_id` 时先用 `get_conversation` 校验 owner。随后创建 `SSEStreamer(conversation_id)`，通过 backup `domain.chat_service._get_hub()` attach，再调用 `send_message(..., content=body.message, idem_key=Idempotency-Key, oa=body.oa, oauth_access_token=body.access_token)`；attach 必须发生在 `send_message` 前，避免丢失后台 `run_flow` 的首个事件。
- `chat_bridge.collect_turn()` 只消费该 streamer 的 native 事件，最长等待固定为 `CHAT_TURN_TIMEOUT_S=120` 秒；`agent.process`、`agent.status`、`tool.call`、`tool.result`、`tool.error`、`message.delta`、`done` 和 `error` 均保留在 backup trace/MessageEvent 中，façade 只做外部事件转换，不改写 native 事件协议。
- `agent.process`/`agent.status` 转换为工作台 `status`，状态文案固定映射：`starting=正在启动对话…`、`planning=正在分析问题…`、`executing=正在调用数据能力…`、`retrying=正在重试…`、`degrading=模型服务降级处理中…`、`interrupted=已停止处理`、`done=处理完成`；`tool.call` 转为 `正在调用 {name}…`，`tool.result` 转为 `已完成 {name}`，每次 status 保留最近 40 条 `steps`。
- 收到 native `done` 后停止消费，使用其 `message_id/final_text/status` 查询 assistant `Message` 和本轮 `tool.result` 事件；收到 `error`、超时或取消时调用 backup `stop_message`，生成唯一失败结果，随后 detach streamer。无论成功或失败，`collect_turn` 只允许产生一个终态 `result` 和一个 `done`。
- `asyncio.CancelledError`、客户端断开和正常结束都执行 `Hub.detach`；不能留下同一会话的孤立 streamer 或继续向已关闭响应写入数据。

#### 4. response envelope 归一化与落库

- 新建 `backend/src/app/services/chat_envelope.py`，公开 `build_envelope(final_text, tool_outputs, process_steps, status)`；以 T09 internal tool 输出中的 `response_type` 为唯一能力判断来源，不读取 `intent`、`prior_intent`，不运行规则识别或 planner。
- `response_type` 固定允许 `history`、`forecast`、`attribution`、`report`、`simulation`、`optimization`；按本轮最后一个成功能力输出选择类型，若没有结构化能力输出则使用 `report`。`explain` 能力输出归一为 `attribution`，Turing 业务文字归一为 `report`，`simulate/optimize` 分别归一为 `simulation/optimization`。
- 若 tool output 含 `envelope`，先复制其 `text/chart/table/meta/follow_ups/update_workspace/process_steps`，再用 engine `final_text` 覆盖 `text.markdown`；若仅有 `rows`，按首行键名的字典序生成 `{key,title}` columns 并生成 table；没有结构化结果时只生成 report text。`meta.status` 使用 engine 终态 `completed/interrupted/failed`，`meta.tool` 使用最后成功工具名或 `engine`，`process_steps` 最多保留 40 条。
- envelope 顶层必须包含 `response_type/text/meta/follow_ups/update_workspace/process_steps`；`intent` 只作为 frontend-ref 旧类型的兼容字段，按固定映射 `history→history`、`forecast→forecast`、`attribution→attribution`、`simulation→whatif`、`optimization→whatif`、`report→null` 写入，不参与路由。不得新增 `Intent` 枚举、不得读取 `prior_intent`，不得生成 `envelope.input`。
- 在同一业务事务内将 assistant `Message.content=final_text`、`Message.status` 和 `Message.result_envelope=envelope` 写回；调用 T09 的 `update_memory()` 更新当前 `Conversation.memory_summary/memory_slots/summary_upto_id`。完整工具输出仍只写 native `MessageEvent.payload`，不得把 OAuth token、backup JWT 或网关密钥写入消息、trace 或 envelope。

#### 5. 三个聊天入口与 SSE 外部契约

- `POST /api/chat` 使用与 stream 相同的 `start_turn/collect_turn`，等待最多 120 秒后返回 HTTP 200：`{session_id,message_id,reply,envelope,update_workspace}`；成功和失败都与流式入口使用同一 envelope 归一化函数，避免两个入口结果结构漂移。
- `POST /api/chat/stream` 返回 `StreamingResponse(media_type="text/event-stream")`，响应头固定包含 `Cache-Control: no-cache`、`Connection: keep-alive`、`X-Accel-Buffering: no`；事件严格为 `status`（可多条）→`result`→`done`，data 使用 JSON 且 `ensure_ascii=false`。
- `POST /api/chat/stream` 的异步生成器使用 `get_session_factory()()` 自己持有数据库会话完成 `start_turn/collect_turn`，不得依赖已在返回 StreamingResponse 前关闭的路由依赖会话；非流式 `/api/chat` 可使用 request-scoped `get_session`。
- `status` data 固定为 `{stage,text,steps}`，`result` data 固定为 `{session_id,message_id,reply,envelope,update_workspace,steps}`，成功 `done` 为 `{ok:true}`，失败 `done` 为 `{ok:false}`；不把 backup native 的 `agent.status/tool.call/tool.result` 直接发给 frontend-ref 的 `sendChatStream`。
- `frontend-ref/src/api.ts` 的 `sendChatStream` 必须在请求头携带 `Authorization: Bearer <backup JWT>`；body 中的 `access_token` 仅传 T07/T12 保存的 OAuth token，OA 模式传 `oa`，email 模式不伪造 OAuth token。后端将这两个字段交给 T08 网关请求上下文，不落库。
- `/api/v1/chat/conversations/{cid}/stream` 继续作为 backup native trace/live-tail 流；T10 不把 `status/result/done` façade 事件反向写回 native Hub，避免重复事件和 trace 污染。

#### 6. `/api/products` 兼容投影

- 保留 `GET /api/products` 以兼容 frontend-ref `api.ts`，通过 T03 `fcst_forecast_result` 查询 `sku/category` 非空的 distinct 行，按 `sku ASC` 返回 `{id:sku,sku,name:sku,category,brand:""}`；表为空时返回 `[]`。
- 不新建 `products` 表、不从 `docs/` 或 frontend-ref mockup 读取产品数据；该接口只是工作台兼容投影，不作为五项模型 capability 或聊天路由输入。

#### 7. frontend-ref agent probe 兼容入口

- T02 复制 frontend-ref 后，读取 `frontend/src/api.ts` 中全部 `/api/agent/probe*` 声明，按源文件记录每个 method、path、query/body 字段和响应字段；T10 在 `backend/src/app/api/chat_facade.py` 注册同一 method/path，统一使用 backup JWT 和 `require_perm`，不新增未在源文件声明的 probe 路径。
- probe 只作为兼容诊断入口：调用 T08 的网关/分析健康能力，响应不得返回 `AGENT_API_KEY`、OAuth token、backup JWT 或上游完整错误；无有效配置时返回既定 `ok=false` 健康结果，不触发聊天 engine loop。

#### 8. 测试与验收实现

- 新增 `backend/tests/test_chat_facade.py`：mock backup `send_message`/Hub/Message 查询，验证新会话与已有会话、owner 越权 404、裸 JSON 会话摘要、title/pinned 更新和 5 个置顶上限。
- 新增 `backend/tests/test_chat_envelope.py`：使用固定 native tool outputs 验证六种 `response_type`、`intent` 兼容映射、`rows→table`、`final_text` 覆盖、40 条 steps 上限、`result_envelope` 写回和不产生 `input` 字段。
- 新增 `backend/tests/test_chat_stream_facade.py`：注入 `starting→planning→tool.call→tool.result→done` native 事件，断言 façade 只输出 `status→result→done`；注入 error、超时和客户端取消，断言只输出一个失败 result/done 并执行 detach/stop。
- 新增 `backend/tests/test_chat_auth_contract.py`：断言 HTTP Authorization 使用 backup JWT、body `access_token` 原样传给 T08 OAuth 输入、JWT 不进入网关 inputs/PG/trace；断言 A 用户访问 B 用户 session 返回 404。
- 新增 `backend/tests/test_agent_probe_contract.py`：从 frontend-ref `api.ts` 的 probe 声明建立 method/path 快照，验证 backend 每条声明均有对应路由、鉴权边界和 `ok/mode/configured_mode/url/provider` 或源文件声明的响应字段；错误响应不包含 secret/token。
- 继续运行 backup `tests/test_engine.py`、`tests/test_chat.py`、`tests/test_session_stream.py`，确认 engine loop、native SSE、trace、checkpoint 和状态机无回归。

## 完成标准
- 验收命令：
  ```bash
  python /c/Users/jie32.guo/.codex/skills/plan-generator/scripts/plan_state.py lint-plan --plan docs/plans/T10-chat-envelope-service-2026-09-01.md
  ```
- 通过条件：命令退出码为 0，且本节保留的原验收项全部满足。

- [ ] `cd backend && uv run pytest tests/test_chat_facade.py tests/test_chat_envelope.py tests/test_chat_stream_facade.py tests/test_chat_auth_contract.py` 全绿。
- [ ] `cd backend && uv run pytest tests/test_engine.py tests/test_chat.py tests/test_session_stream.py` 全绿，backup native engine/SSE/trace 无回归。
- [ ] Git Bash 中执行 `curl -sS -H "Authorization: Bearer <backup-jwt>" http://127.0.0.1:8000/api/sessions`，HTTP 200 body 为 JSON 数组；执行 `curl -sS -H "Authorization: Bearer <backup-jwt>" http://127.0.0.1:8000/api/sessions/<other-user-session-id>`，HTTP 404。
- [ ] Git Bash 中执行 `curl -N -H "Authorization: Bearer <backup-jwt>" -H "Content-Type: application/json" -X POST http://127.0.0.1:8000/api/chat/stream -d '{"message":"查询冰箱历史销量","session_id":null,"params":{},"access_token":"<oauth-token>"}'`，输出顺序包含 `event: status`、`event: result`、`event: done`，且 result 同时含 `response_type/text/meta`，不含 `input`。
- [ ] Git Bash 中执行非流式同款请求 `curl -sS -H "Authorization: Bearer <backup-jwt>" -H "Content-Type: application/json" -X POST http://127.0.0.1:8000/api/chat -d '{"message":"查询冰箱历史销量","session_id":null,"params":{},"access_token":"<oauth-token>"}'`，返回 `session_id/message_id/reply/envelope`，并与 stream 使用相同 envelope 字段。
- [ ] `psql agent_platform -c "SELECT result_envelope IS NOT NULL FROM messages WHERE role='assistant' ORDER BY created_at DESC LIMIT 1"` 返回 `t`；`psql agent_platform -c "SELECT COUNT(*) FROM messages WHERE result_envelope::text LIKE '%input%'"` 返回 `0`。
- [ ] `grep -RInE "run_chat|run_chat_sse|ChatSession|ChatMessage|planner_react|request_analyzer|prior_intent" backend/src/app/api/chat_facade.py backend/src/app/services/chat_bridge.py backend/src/app/services/chat_envelope.py` 无命中。
- [ ] `cd backend && uv run pytest tests/test_agent_probe_contract.py` 全绿；且 `rg -n "agent/probe" frontend/src/api.ts` 的每条声明都能被对应 backend route 快照覆盖。
