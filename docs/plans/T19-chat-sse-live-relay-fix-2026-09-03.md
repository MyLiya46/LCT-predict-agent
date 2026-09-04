# T19 · Chat SSE 实时状态转发修复（chat-sse-live-relay-fix）

- 任务 ID：T19
- 标题与目标：让 `/api/chat/stream` 在 Agent 执行期间实时转发 status，保持 `status → result → done` 顺序，并在客户端断开时取消后台收集任务。
- 关联文档章节：`docs/feat-icewash.md` §10.2、§12；T10、T18
- 前置依赖 blockedBy：T18

## 执行画像

- execution_mode：direct
- execution_class：normal
- expected_duration：约 15 分钟
- external_waits：backend、PG、真实 LLM Provider
- checkpoint_phases：实时转发单测、断开清理、真实 SSE 时间验证、构建与回归
- resume_boundary：从最后一个未通过的实时 SSE 阶段继续

## 问题

- 当前 `/api/chat/stream` 先等待 `collect_turn()` 完成，再一次性发送缓存的 status；事件顺序正确但状态不会在 Agent 执行期间到达前端。
- 前端因此只能立即显示本地初始步骤，无法在真实流式处理期间逐步更新思考过程；断开连接时也没有显式取消仍在等待的收集任务。

## 决策

- 在 chat façade 内使用无界 `asyncio.Queue` 接收 `collect_turn(on_status=...)` 的状态回调，独立任务负责收集，响应生成器优先转发已到达的 status，再发送 result 和 done。
- 生成器结束或客户端取消时取消未完成的 collector/queue waiter，并等待任务收敛；不改变消息落库、trace、envelope 或事件字段。
- 只转发后端已发布的状态步骤，不把供应商隐藏思维链或 Authorization/token 写入 SSE。

## 范围

- 包含：`/api/chat/stream` 实时 status 转发、任务取消清理、可测试的 relay helper、实时时间验收脚本。
- 不包含：改变 LLM Provider 协议、修改数据库结构、增加 token 增量字段或改造原生 `/api/v1/chat` SSE 契约。

## 环境预检

- 必需 Shell：git-bash
- 必需命令：`uv`、`pytest`、`ruff`、`curl`
- 必需端口：8000；真实验收还需要 PG 与 LLM Provider
- 必需 URL：`http://127.0.0.1:8000/api/chat/stream`
- 必需 Python 模块：`asyncio`、`fastapi`、`httpx`、`pytest`
- 必需 Docker 容器：`LCT-predict-agent-pg`
- 容器内必需命令：`psql`
- 容器内必需 Python 模块：`PostgreSQL 容器不运行 Python；验收仅使用 psql 查询状态`
- 执行画像：normal
- 启动超时（秒）：30
- 空闲超时（秒）：60
- 硬截止（秒）：900
- 最大 checkpoint 间隔（秒）：120
- 预检命令：
  ```bash
  test -f backend/src/app/api/chat_facade.py && test -f backend/tests/test_chat_stream_facade.py
  ```

## 风险与回滚

- 风险：队列任务清理不完整可能让真实 Provider 请求继续运行；响应生成器若先消费 result 可能丢失末尾 status。
- 回滚：只回退 `backend/src/app/api/chat_facade.py` 与 `backend/tests/test_chat_stream_facade.py` 的本任务 diff，再重启 8000 backend 并运行定向测试。

## 实施步骤

### 步骤 1：实现 status 实时 relay

- 对象：`backend/src/app/api/chat_facade.py` 的 `chat_stream` 生成器。
- 动作：新增 `_live_turn_events` 异步 relay；以 `asyncio.create_task(collect_turn(...))` 收集结果，以 `asyncio.Queue` 接收状态回调，按到达顺序 yield status，并在 collector 完成后 drain 队列再 yield result。
- 参数：沿用 `CHAT_TURN_TIMEOUT_S=300`；终态固定为 `event=status* → event=result → event=done`；断开时 cancel collector 和 queue waiter。
- 核心修改文件：`backend/src/app/api/chat_facade.py`
- 必要集成文件：`backend/tests/test_chat_stream_facade.py`
- 命令：
  ```bash
  cd backend && uv run pytest tests/test_chat_stream_facade.py -q
  ```

### 步骤 2：补充实时顺序与清理回归

- 对象：relay helper 的 fake collector 测试。
- 动作：让 fake collector 在返回 result 前延迟，断言首个 status 已被消费且 collector 尚未结束；再断言所有 status 位于 result 之前，并覆盖正常完成路径。
- 参数：状态数量至少 2；结果 payload 包含 `session_id`、`message_id`、`ok`；测试不连接真实 Provider、不写 PG。
- 核心修改文件：`backend/tests/test_chat_stream_facade.py`
- 必要集成文件：`backend/src/app/api/chat_facade.py`
- 命令：
  ```bash
  cd backend && uv run pytest tests/test_chat_stream_facade.py -q
  ```

### 步骤 3：执行真实时间验收与质量门禁

- 对象：当前 8000 backend 的 `/api/chat/stream` 和前端 status 消费路径。
- 动作：使用 `.env` email 账号发起一条短 history 请求，记录各 SSE 事件到达时间；断言首个 status 早于 result，响应顺序完整且不含 token；随后回查 trace 并删除临时会话。
- 参数：curl/httpx 总超时 180 秒；只输出事件名、相对时间和布尔断言；离线测试、ruff、frontend build 全部通过。
- 核心修改文件：`backend/tests/test_chat_stream_facade.py`
- 必要集成文件：`frontend/src/store.ts`、`frontend/src/components/ChatPanel.tsx`
- 命令：
  ```bash
  cd backend && uv run ruff check src/app/api/chat_facade.py tests/test_chat_stream_facade.py && uv run pytest tests/test_chat_stream_facade.py tests/test_llm_stream_regressions.py -q
  ```

## 完成标准

- 验收类型：mixed
- 离线验收命令：
  ```bash
  cd backend && uv run ruff check src/app/api/chat_facade.py tests/test_chat_stream_facade.py && uv run pytest tests/test_chat_stream_facade.py tests/test_llm_stream_regressions.py tests/test_chat_trace_regressions.py -q
  ```
- 外部环境验收命令：
  ```bash
  curl -fsS http://127.0.0.1:8000/api/health/agent
  ```
- 通过条件：fake collector 测试证明 status 在 collector 返回前可消费；真实 SSE 的首个 status 到达时间早于 result，顺序保持 `status → result → done`；取消路径不遗留 collector；无 token 泄露且既有 LLM、trace、沙箱和前端回归继续通过。
