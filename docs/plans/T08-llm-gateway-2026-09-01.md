# T08 · LLM 网关适配与分析增强（llm-gateway）

- **任务 ID**：T08
- **标题与目标**：在 backend-backup 的 LLM provider、engine loop、SSE 和工具调用底座上增加真实网关客户端与可选 Turing 分析增强；只迁入 backend-ref 的 HTTP 客户端和 envelope 解析，不迁入其独立 Agent 编排、intent、planner 或 memory。
- **关联文档章节**：feat-icewash.md §10.2（不并入 turing_client/oauth_client 的旧结论已变更——本次真接）；backend-ref services/agent_adapter/*、analysis_agent.py、turing_client.py、mcp_adapter/*
- **前置依赖 blockedBy**：T03
- **状态**：reviewed

## 实施要点

### 1. 迁入 LLM 网关客户端，不替换 backup 编排
- 保留 backup 已有的 `backend/src/app/llm/adapter_openai.py`、`service.py`、`providers.py`、`mock_provider.py`、`events.py` 和 `engine/loop.py`；不得覆盖或重命名原有 `app.llm` 模块。
- 新建 `backend/src/app/llm/gateway/ml_api_client.py`，只迁入 backend-ref `agent_adapter/chat_client.py` 的 HTTP blocking/streaming 请求、SSE 解析、`build_inputs` 和 `AgentChatResult`；公共方法固定为 `chat(query, inputs, user, conversation_id, files)`、`stream_chat(...)`、`health()`，不包含 intent、planner、memory 或内部工具执行。
- 新建 `backend/src/app/llm/gateway/response_parser.py`，迁入 `envelope_from_chat_answer` 和 JSON 提取逻辑；输出只负责把上游文本/结构化数据转换为 `AgentResultEnvelope`，不决定调用哪个模型能力。
- 新建 `backend/src/app/llm/gateway/turing.py`，迁入 backend-ref `turing_client.py` 的 `chat_completion` 和 `turing_configured`；不迁入 embedding 记忆链路。Turing 只作为报告/归因解读增强器。
- 新建 `backend/src/app/llm/gateway/analysis_agent.py`，迁入 `enrich_envelope`；同时新建 `result_utils.py`，只保留清理关联追问正文所需的 `strip_related_suggestions`。Turing 不可用或失败时返回原始 envelope。`T10` 仍使用 backup `engine.loop` 负责 LLM → tool schema → internal tool → SSE，T08 不新增第二套循环。
- `mcp_adapter`、`intent.py`、`planner_react.py`、`planner_tools.py`、`request_analyzer.py`、`dialogue_context.py`、backend-ref `memory.py` 和完整 `result_insight.py` 不迁入；simulate/optimize 的调用由 T05/T09 的 internal tool 通过 T04/T06/T05 服务完成。

### 2. config 增加网关与分析字段
- 在 `backend/src/app/config.py` 增加并在 `backend/.env.example` 同步：`agent_api_url="https://ml-api-gw-en.tcl.com/agi/v1/chat-messages"`、`agent_api_key=""`、`agent_response_mode="blocking"`、`agent_timeout_sec=120.0`、`agent_user="forecast-agent-ui"`、`agent_oa=""`、`agent_enable_thinking=""`、`agent_attachment=""`、`agent_extra_inputs_json=""`、`analysis_agent_enabled=True`、`turing_api_base="https://live-turing.cn.llm.tcljd.com/api/v1"`、`turing_api_key=""`、`turing_model="turing/gpt-5.4-mini"`、`turing_timeout_sec=90.0`。
- 迁入代码全部调用 `get_settings()`，不 import backend-ref 的模块级 `settings`；默认 `agent_response_mode="blocking"`、超时 `120.0` 秒。`agent_api_key` 只用于上游 HTTP Authorization。
- T07/T12 登录链路传入的 `oauth_access_token` 仅在调用 `ml_api_client.build_inputs(access_token=...)` 时写入上游 `inputs.new_token`；backup JWT 只放 backend API 的 HTTP `Authorization`，不得写入上游 inputs。

### 3. 健康端点 `backend/src/app/api/health.py` 扩充
- 在现有 `health.py` 中新增独立 `agent_router = APIRouter(prefix="/api/health", tags=["health"])`，注册 `GET /api/health/agent`；主 `health.router` 继续提供 `/healthz`、`/readyz`，两套路由分别 include。
- `ml_api_client.health()` 返回裸 JSON `{ok, mode, configured_mode, url, provider}`；已配置 `AGENT_API_KEY` 时返回 HTTP 200、`ok=true`、`mode="live"`，未配置时返回 HTTP 200、`ok=false`、`mode="disabled"`、`error="AGENT_API_KEY missing"`。响应不得返回任何 API key、OAuth token 或 Authorization header。
- `GET /api/health/agent` 不要求登录，也不向上游发网络请求。

### 4. 请求与降级边界
- `ml_api_client` 使用 `httpx.AsyncClient(timeout=120.0)`；blocking payload 固定包含 `inputs/query/response_mode="blocking"/user/files`，streaming payload 固定包含 `inputs/query/response_mode="streaming"/user/files`，存在会话时追加 `conversation_id`。
- 上游 4xx/5xx、超时和无效 JSON 转换为不泄露 secret 的 `RuntimeError`；T10/engine 继续使用 backup 的 retry、fallback、checkpoint 和 done 语义。
- streaming 忽略 `ping`，将 `agent_thought/node_started/node_finished/agent_message/message_end/error` 映射为 `status` 过程事件；没有最终 answer 时返回明确错误。
- `analysis_agent.enrich_envelope` 在 `ANALYSIS_AGENT_ENABLED=false`、Turing key 缺失、Turing 请求失败或 JSON 不符合 schema 时返回 base envelope，不阻断模型能力结果。

## 验收标准
- [ ] `uv run pytest tests/test_llm_gateway.py tests/test_llm.py` 通过；backup 原有 `LLMProvider`、engine loop 和 LLM 测试全绿。
- [ ] `uv run pytest tests/test_llm_gateway.py -k gateway` 使用 `respx` 或 `httpx.MockTransport` 覆盖 blocking 200、streaming SSE、上游 4xx、超时和无效 JSON；断言 Authorization 使用 `AGENT_API_KEY`，`inputs.new_token` 使用 OAuth token，错误不包含 secret。
- [ ] `uv run pytest tests/test_llm_gateway.py -k analysis` 覆盖 Turing key 缺失、Turing 异常、非法 JSON 和合法 JSON；前三种返回 base envelope，合法 JSON 返回合法 `AgentResultEnvelope`。
- [ ] `uv run pytest tests/test_health.py -k agent` 通过：缺少 key 返回 HTTP 200、`ok=false`，响应不含 key 或 token。
- [ ] `curl -s "http://127.0.0.1:8000/api/health/agent"` 返回裸 JSON，字段含 `ok/mode/configured_mode/url/provider`，不要求 Authorization。
