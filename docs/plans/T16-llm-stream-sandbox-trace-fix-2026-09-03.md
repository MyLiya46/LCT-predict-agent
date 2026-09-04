# T16 · LLM 流式、沙箱与追溯联调修复（llm-stream-sandbox-trace-fix）

- 任务 ID：T16
- 标题与目标：修复真实聊天 Provider 健康状态误报、流式 SSE 兼容、沙箱异常归一和无 trace 消息查询，并补齐可重复的后端回归测试。
- 关联文档章节：`docs/feat-icewash.md` §10.2、§12.4；`docs/feat-sandbox.md`；T08、T10、T15
- 前置依赖 blockedBy：T15

## 执行画像

- execution_mode：direct
- execution_class：normal
- expected_duration：约 20 分钟
- external_waits：PG、backend、sandbox daemon、LLM Provider
- checkpoint_phases：健康状态、流式解析、沙箱与追溯、离线验收
- resume_boundary：从最后一个未通过的测试阶段继续

## 问题

- `/api/health/agent` 只检查独立 `AGENT_API_KEY`，而当前聊天引擎实际使用 PG `llm_providers` 默认 Provider；Provider 正常时前端仍显示 `Agent disabled · 异常`。
- OpenAI 兼容流式适配器只接受带空格的 `data: ` 行，部分上游使用 `data:`；流式正文和工具调用因此可能被静默丢弃。
- 沙箱响应不是 JSON 时会直接抛出解析异常，无法归一为可追溯的 `SANDBOX` 错误。
- 没有 `trace_id` 的普通消息会因 `str(None)` 为真而进入 trace 查询，追溯接口无法稳定返回空事件结果。

## 决策

- 健康接口同时表达两类聊天可用来源：独立 Agent 网关 key 存在时返回 `mode=live`；否则检查 PG 默认 Provider，健康 Provider 返回 `mode=provider`；两者都不可用才返回 `mode=disabled`。响应只返回 URL/provider 标识，不返回任何密钥或 token。
- 流式解析接受 `data:` 与 `data: `、CRLF 和 `[DONE]`，保留当前 tool-call 聚合和最终 `done_reason` 语义；上游错误继续由引擎重试/降级处理。
- 沙箱客户端在 HTTP 非 200、超时、网络异常和无效 JSON 下统一返回 `ToolExecutionResult`，错误文本不包含请求凭据；trace 查询按 `trace_id is not None` 分支。

## 范围

- 包含：后端健康投影、OpenAI 兼容 SSE、ML gateway 相关回归、沙箱客户端错误归一、消息追溯边界和对应 pytest。
- 不包含：更换 LLM Provider、把独立 ML gateway 编排接入 backup engine、修改数据库结构或改变沙箱容器安全参数。

## 环境预检

- 必需 Shell：git-bash
- 必需命令：`uv`、`python`、`pytest`、`ruff`、`curl`
- 必需端口：8000、9000；离线测试不依赖端口
- 必需 URL：`http://127.0.0.1:8000/api/health/agent`、`http://127.0.0.1:9000/healthz`
- 必需 Python 模块：`fastapi`、`httpx`、`pytest`、`respx`、`sqlalchemy`
- 必需 Docker 容器：`LCT-predict-agent-pg`
- 容器内必需命令：`LCT-predict-agent-pg:psql`
- 容器内必需 Python 模块：无
- 执行画像：normal
- 启动超时（秒）：30
- 空闲超时（秒）：60
- 硬截止（秒）：900
- 最大 checkpoint 间隔（秒）：120
- 预检命令：
  ```bash
  python C:/Users/jie32.guo/.codex/skills/plan-generator/scripts/preflight.py check --plan docs/plans/T16-llm-stream-sandbox-trace-fix-2026-09-03.md --format json
  ```

## 风险与回滚

- 风险：真实 Provider 或 sandbox daemon 不可达时，外部联调会失败，但离线 mock/respx 验收仍应可运行；健康接口查询 PG 失败时必须退回 disabled，不得阻塞 `/healthz`。
- 回滚：实施前执行 `git diff -- backend/src/app backend/tests > /tmp/lct-t16.patch`；若回归超出本任务边界，执行 `git apply -R /tmp/lct-t16.patch`。

## 实施步骤

### 步骤 1：修正聊天健康状态投影

- 对象：`GET /api/health/agent` 与默认 LLM Provider 查询。
- 动作：在 Agent key 缺失时读取 PG 默认 Provider；Provider 存在且 `status=healthy` 时返回 `ok=true`、`mode=provider`、`configured_mode`、`url`、`provider`，异常或无 Provider 时保留 disabled 响应；所有分支过滤 secret。
- 参数：Provider 检查只读数据库，不主动调用上游；独立网关 key 分支保持 `mode=live`。
- 核心修改文件：`backend/src/app/api/health.py`
- 必要集成文件：`backend/tests/test_health.py`
- 命令：
  ```bash
  cd backend && uv run pytest tests/test_health.py -q
  ```

### 步骤 2：修正并覆盖 LLM 流式解析

- 对象：`OpenAICompatProvider.chat` 和 `MLApiClient.stream_chat` 的 SSE 行解析。
- 动作：接受 `data:`/`data: ` 两种前缀和 CRLF，忽略 ping，累计正文与分段 tool-call arguments，并在 `[DONE]` 后产出唯一终态；无最终答案时抛出不泄露凭据的 RuntimeError。
- 参数：保留 `stream=true`、`read timeout=30s`、总超时 180s；测试同时覆盖正文流、工具调用流、上游 4xx、超时和无效 JSON。
- 核心修改文件：`backend/src/app/llm/adapter_openai.py`、`backend/src/app/llm/gateway/ml_api_client.py`
- 必要集成文件：`backend/tests/test_llm.py`、`backend/tests/test_llm_gateway.py`、`backend/tests/test_llm_stream_regressions.py`
- 命令：
  ```bash
  cd backend && uv run pytest tests/test_llm.py tests/test_llm_gateway.py tests/test_llm_stream_regressions.py -q
  ```

### 步骤 3：统一沙箱失败与追溯边界

- 对象：沙箱 API 客户端和 `get_message_trace`。
- 动作：从当前 settings 读取 daemon URL；将无效 JSON、HTTP 错误、连接错误和超时归一为 `SANDBOX`/`TIMEOUT` 结果；无 `trace_id` 的消息返回空事件列表，不执行带 `None` 的 trace 查询；保留 owner 404 隔离。
- 参数：错误消息不包含 `API_INTERNAL_TOKEN`、数据源凭据或上游响应正文；成功结果保留 `container_id/reused_warm/exit_code`。
- 核心修改文件：`backend/src/app/sandbox/client.py`、`backend/src/app/domain/chat_service.py`
- 必要集成文件：`backend/tests/test_sandbox_client.py`、`backend/tests/test_tracing.py`、`backend/tests/test_chat_trace_regressions.py`
- 命令：
  ```bash
  cd backend && uv run pytest tests/test_sandbox_client.py tests/test_tracing.py tests/test_chat_trace_regressions.py -q
  ```

### 步骤 4：执行离线质量门禁

- 对象：T16 涉及的 Python 模块和测试集合。
- 动作：运行 ruff、compileall 和完整聊天/流式/沙箱/追溯定向测试，确认没有 secret 泄露和既有 engine/SSE 回归。
- 参数：pytest 使用仓库默认 `asyncio_mode=auto`；PG 测试库使用 `TEST_DATABASE_URL` 或 conftest 默认地址。
- 核心修改文件：`backend/tests`
- 必要集成文件：`backend/pyproject.toml`
- 命令：
  ```bash
  cd backend && uv run ruff check src tests && uv run python -m compileall -q src && uv run pytest tests/test_llm.py tests/test_llm_gateway.py tests/test_sandbox_client.py tests/test_tracing.py tests/test_chat_stream_facade.py -q
  ```

## 完成标准

- 验收类型：mixed
- 离线验收命令：
  ```bash
  cd backend && uv run ruff check src tests && uv run pytest tests/test_llm.py tests/test_llm_gateway.py tests/test_llm_stream_regressions.py tests/test_sandbox_client.py tests/test_tracing.py tests/test_chat_trace_regressions.py tests/test_chat_stream_facade.py -q
  ```
- 外部环境验收命令：
  ```bash
  curl -fsS http://127.0.0.1:9000/healthz; curl -fsS http://127.0.0.1:8000/api/health/agent
  ```
- 通过条件：离线命令退出码为 0；无 key 但 PG healthy Provider 存在时健康响应为 `ok=true, mode=provider` 且不含 key/token；流式正文、工具调用、沙箱三态和 trace owner 隔离断言全部通过。
