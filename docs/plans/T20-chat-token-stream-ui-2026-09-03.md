# T20 · 聊天 token 流式输出闭环（chat-token-stream-ui）

- 任务 ID：T20
- 标题与目标：让模型文本增量从 Agent 引擎经 `/api/chat/stream` 实时到达聊天框，并在最终结果到达时无重复收口。
- 关联文档章节：`docs/PRD.md` §5、§7.1、§12.4；`docs/feat-icewash.md` §10.2；T19
- 前置依赖 blockedBy：T19

## 执行画像

- execution_mode：direct
- execution_class：normal
- expected_duration：约 25 分钟
- external_waits：无；真实 LLM 可选
- checkpoint_phases：delta 桥接单测、SSE 解析单测、前端构建、真实流式验收
- resume_boundary：从最后一个未通过的单测或构建阶段继续

## 问题

- `backend/src/app/engine/loop.py` 已发布 `message.delta`，但 `chat_bridge.collect_turn` 只消费状态和终态事件，增量文本被丢弃。
- `backend/src/app/api/chat_facade.py` 只把状态和最终结果序列化为 SSE，浏览器无法收到中间文本。
- `frontend/src/api.ts` 只解析 `status` 与 `result`，`frontend/src/store.ts` 也只在结果到达后追加助手消息，因此聊天框表现为阻塞输出。

## 决策

- 保留现有 fetch + SSE 协议和认证方式，新增 `event: delta`，载荷固定为 `{text: string}`；不引入 EventSource，以继续携带 Bearer token 和复用刷新令牌逻辑。
- `collect_turn` 通过现有 `on_status` 回调转发增量，桥接层按 `delta` 字段分类为 `delta` 事件，保证自定义 collector 兼容现有测试签名。
- Zustand 增加本轮 `streamingReply`，每个 delta 到达即累加并渲染临时助手气泡；`result` 到达后用持久化回复替换临时内容并清空增量状态。
- delta 仅用于在线展示，不写入追溯事件和数据库；最终 `done` 仍由现有引擎落库，避免半截文本污染会话历史。

## 范围

- 包含：桥接层 delta 分类、facade SSE 帧、前端 SSE 解析回调、store 临时回复、ChatPanel 流式助手气泡、回归测试和构建验收。
- 不包含：LLM provider 的上游协议改造、数据库迁移、native `/api/v1/chat` 会话流协议改造、聊天业务回答内容改写。

## 环境预检

- 必需 Shell：git-bash
- 必需命令：`python`、`uv`、`npm`
- 必需端口：8000（外部验收时）
- 必需 URL：外部验收使用 `http://127.0.0.1:8000/api/chat/stream`
- 必需 Python 模块：backend `pytest`、`httpx`、`fastapi`
- 必需 Docker 容器：无
- 容器内必需命令：无
- 容器内必需 Python 模块：无
- 执行画像：normal
- 启动超时（秒）：20
- 空闲超时（秒）：30
- 硬截止（秒）：180
- 最大 checkpoint 间隔（秒）：45
- 预检命令：
  ```bash
  python C:/Users/jie32.guo/.codex/skills/plan-generator/scripts/preflight.py check --plan docs/plans/T20-chat-token-stream-ui-2026-09-03.md --format json
  ```

## 风险与回滚

- 风险：delta 帧在代理或浏览器端被拆分、使用 CRLF 或空数据行时，解析器可能丢字符；流中断时临时助手消息可能停留在半句。通过分块解析测试、错误态清理和最终结果替换监测。
- 回滚：保留 `status/result/done` 帧兼容路径；若外部验收发现增量协议异常，可将 facade 的 delta 分类关闭并恢复仅发送终态，源码回滚范围限定为本计划列出的文件。

## 实施步骤

### 步骤 1：桥接引擎增量并分类 SSE 事件

- 对象：`collect_turn`、`_live_turn_events` 的事件处理。
- 动作：识别 `message.delta`，将非空文本放入回调载荷 `delta`；facade 将带 `delta` 的载荷转为 `event: delta`，其余仍转为 `event: status`，终态保持 `result → done`。
- 参数：单帧文本使用 UTF-8 字符串；空 delta 不下发；保留最近 40 条步骤；客户端断开时继续取消 collector。
- 核心修改文件：`backend/src/app/services/chat_bridge.py`、`backend/src/app/api/chat_facade.py`。
- 必要集成文件：`backend/src/app/sse/events.py`（仅在需要补充事件常量时接线）。
- 命令：
  ```bash
  cd backend && uv run pytest -q tests/test_chat_stream_facade.py tests/test_chat_trace_regressions.py
  ```

### 步骤 2：前端消费增量并显示临时助手回复

- 对象：`sendChatStream`、AppState、`ChatPanel` 消息列表。
- 动作：为流式 API 增加 `onDelta` 回调；store 在请求期间累加 `streamingReply`；聊天框在加载状态显示可复制的临时助手文本，并在 result 到达时以服务端回复替换且清空。
- 参数：每次 delta 直接追加，不按字符二次切分；刷新 token 后继续使用同一回调；请求失败清空临时回复并保留错误提示。
- 核心修改文件：`frontend/src/api.ts`、`frontend/src/store.ts`、`frontend/src/components/ChatPanel.tsx`。
- 必要集成文件：无。
- 命令：
  ```bash
  cd frontend && npm run build
  ```

### 步骤 3：回归事件顺序与半流状态

- 对象：facade 测试和 stream 解析边界。
- 动作：补充首个 delta 先于 collector 完成、多个 delta 顺序保持、最终 result 替换临时回复的断言，并验证 CRLF/分块读取。
- 参数：事件顺序为 `status/delta* → result → done`；禁止把上游密钥或原始错误体放入帧。
- 核心修改文件：`backend/tests/test_chat_stream_facade.py`、`backend/tests/test_chat_trace_regressions.py`。
- 必要集成文件：无。
- 命令：
  ```bash
  cd backend && uv run pytest -q tests/test_chat_stream_facade.py tests/test_chat_facade.py tests/test_chat_trace_regressions.py
  ```

## 完成标准

- 验收类型：mixed
- 离线验收命令：
  ```bash
  cd backend && uv run pytest -q tests/test_chat_stream_facade.py tests/test_chat_facade.py tests/test_chat_trace_regressions.py && uv run ruff check src/app/services/chat_bridge.py src/app/api/chat_facade.py tests/test_chat_stream_facade.py
  cd ../frontend && npm run build
  ```
- 外部环境验收命令：登录后对 `POST http://127.0.0.1:8000/api/chat/stream` 使用 `curl -N`，记录到首个 `event: delta` 的时间，并确认后续出现 `event: result` 与 `event: done`。
- 通过条件：离线测试和构建退出码为 0；真实流在最终结果前至少收到一帧 delta，前端逐段可见，最终历史只保留一条完整助手消息。
