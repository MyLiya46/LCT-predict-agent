# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概览

**LCT-predict-agent** 是一个内部销售数据查询 + 预测的通用 AI Agent 平台。自然语言 → Agent 循环 → LLM 规划 → 沙箱执行工具 → SSE 流式展示；用户端/管理员端双端 RBAC，全链路追溯。

- **权威文档**（改代码前先读）：
  - [docs/PRD.md](docs/PRD.md) —— 需求
  - [docs/todo.md](docs/todo.md) —— 任务拓扑与状态
- 文档为中文；架构约定（表名、事件名、错误码、键名）与 tech_design 精确对齐，不要自造。

## 架构总览

### 后端（backend/src/app/）
请求流：`api/` 路由 → `api/deps`（require_perm 依赖）→ `domain/` 领域服务 → `engine/`、`llm/`、`sandbox/`、`tools/`、`tracing/`。

| 目录 | 职责 |
|---|---|
| `api/` | FastAPI 路由（auth / chat / admin 七模块 / health / deps） |
| `api/deps.py` | `get_current_user` + `require_perm(code)` 鉴权依赖 |
| `domain/` | `chat_service` / `auth_service`：组织持久化 + 业务规则 |
| `engine/` | **Agent 执行循环**（loop.py）、单会话互斥（flow.py）、状态机（state.py）、checkpoint、重试降级 |
| `llm/` | `LLMProvider` 抽象（providers.py）→ `adapter_openai`（OpenAICompat 事件流）；无配置时降级 `mock_provider` |
| `sandbox/` | daemon HTTP 客户端（client.py，三态归一 ToolExecutionResult）+ 实例生命周期 |
| `tools/` | 注册中心（registry.py，30s TTL 缓存）、schema 校验（validate.py）、场景编排（scenario.py） |
| `tracing/` | 事件链追加（trace.py）+ 还原/导出/审计写库（audit.py write_audit） |
| `sse/` | Hub（进程内 conversation_id → streamer 注册表）+ 事件协议（events.py） |
| `auth/` | password（bcrypt）/ tokens（JWT 双令牌）/ lockout |
| `rbac/` | `load_user_ctx` 身份组装（30s TTL 缓存）+ 权限判断（service.py） |
| `middleware/` | RequestIDMiddleware、AdminPrefixRBAC（/admin 前缀硬化） |
| `datasource/` | 数据源凭据 AES-256-GCM（security.py/decrypt）+ service.py prepare_env |
| `models/` | 17 表 ORM（base.py 为基座）；`models/types.py` 方言感知类型 |
| `background/` | 每日保留清理/供应商健康校正（APScheduler） |
| `config.py` | pydantic-settings 全量环境变量 + `get_settings()` 单例 + system_config 热更新缓存失效 |
| `config_service.py` | `get_sys_config(session, key, default)` 运行时系统参数读取 |

关键横切约定：
- **统一响应** `{code, message, data}`（`utils/errors.py to_uni`），业务码用 `00` 成功 / 七错误码（400_VALIDATION 等，附录 D）。
- **审计**：管理操作与越权 403 均经 `write_audit` 留痕，恰写一次（异常处理器与 AdminPrefix 中间件分工）。
- **中间件链**（main.py §5.4）：CORS → RequestID → auth 解析 → AdminPrefixRBAC → 路由 → 统一异常。
- **幂等**：`POST /chat/.../messages` 用 `Idempotency-Key` 头（utils/idem.py）。

### Agent 执行引擎（engine/loop.py）——平台核心
`run_flow` 循环：PLANNING → LLM 流式（content_delta/tool_call.batch/done_reason）→ 工具并行执行（`_execute_tools_parallel`，并发读 `sandbox.max_concurrent`，默认 3）→ 结果回灌 OpenAI tool role 格式 → 收敛保障（`MAX_AGENT_ROUNDS=10`、连续工具失败熔断=2）→ checkpoint（每轮 SavePoint 落库）→ 中断（SafePoint 检查 `flow.cancelled`）。事件一路 `append_event`（trace 链）+ `hub.publish`（SSE）。失败/超时语义与 retry 表见 §3.4。

### 沙箱工具执行（api → sandbox-daemon → 工具 handler）
1. engine 从 `Tool.execution` 取 `{image, handler, timeout_s, warm_pool, env_from_datasource, kind}`。
2. `sandbox/client.py` POST `{daemon}/run`（X-Internal-Token 互认），结果归一化 `ToolExecutionResult`（ok / 业务 error / HTTP/超时→SANDBOX/TIMEOUT）。
3. daemon（services/sandbox-daemon/src/sd/）唯一形态：**docker** 受限容器（只读 rootfs、cap_drop ALL、非 root、sandbox-net + iptables 白名单、预热池），依赖宿主 Docker 引擎，无降级路径。
4. 工具包在 `tools/`：`query_sales_data` / `predict_sales`（schema.json/execution.json/tool.py + Dockerfile），`services/mock-sales/mock_internal.py` 为联调 mock 销售服务（:8001）。数据源凭据 `DS_TOKEN_*`/`DS_BASE_URL_*` 逐字节注入容器 env，不落日志。

### 追溯（tracing/）
行式事件模型：`message_event(seq, type, payload)`，seq 同 trace 内递增。事件字典在 `tracing/trace.py`（message_created / agent_process / tool_call / tool_result / tool_error / sse_opened / done）。还原/导出/管理查询见 `query.py`/`admin_query.py`。

### SSE（sse/hub.py）
conversation_id → SSEStreamer（每个 asyncio.Queue）；`publish` 尽力投递 + 5s 心跳；断连重放靠前端 fetch-stream + 3s trace 轮询兜底（不用 Redis）。事件名与附录 A 对齐。

### 前端（frontend/src/）
- 单一 SPA 双端分流（router 守卫：未登录→login，/admin/* 要求 admin）。
- `api/` axios 封装 + `composables/useSse`（fetch-stream + 轮询兜底）；`stores/` Pinia（user/conversation）。
- `views/chat/`：Workbench（对话）+ TracePanel（追溯面板）+ ToolCard/RealtimeTable/Chart 渲染。
- `views/admin/`：Users / Tools / Datasources / LLM / Audits / Config 六页。

## 注意事项

- 新增业务环境变量必须在 `config.py` 与 `.env.example` 一起补。
- SSE hub、ActiveFlowRegistry、`tools/registry.py` 缓存的 `_ENABLED_CACHE`、`rbac/service.py` 的 `_CACHE` 全是**进程内单例**；多 worker / 新变量装配时注意这点。
- 工具输出完整数据走 `message_event.payload`，SSE `tool.result` 只发摘要（`engine/loop.py _summarize`）。
- 生产部署 `uvicorn --workers 1`（进程内 asyncio 语义依赖单 worker）。

## 常用命令

### 数据库（本地开发，先于后端启动）
```bash
# 一条 docker run 拉起 PG（库/用户/密码默认值与 .env.example「数据库」节一致；命名卷持久化）
docker run -d --name LCT-predict-agent-pg -p 5432:5432 \
  -e POSTGRES_DB=agent_platform -e POSTGRES_USER=app -e POSTGRES_PASSWORD=app \
  -v pg-data:/var/lib/postgresql/data postgres:16-alpine
# 首次 / 换库后：建表 + 种子（幂等，可重复运行）
bash scripts/dev_db_pg.sh
```

### 后端（backend/）
```bash
cd backend
uv sync                                    # 安装依赖（uv 管理，含 pytest/ruff dev 组）
uv run pytest                              # 全量测试，当前 45 passed（PostgreSQL 测试库，见 tests/conftest.py）
uv run pytest tests/test_engine.py -k send # 单个测试文件 / 关键字过滤
uv run ruff check .                        # lint
cp .env.example .env                       # 填必填项（JWT_SECRET>=32B、API_INTERNAL_TOKEN、DATABASE_URL）
uv run uvicorn app.main:app --port 8000    # 启动（conftest 已注入 src 到 path）
```
- 测试 fixture（`tests/conftest.py`）：每测试先建独立的 PG 测试 schema（`DROP/CREATE SCHEMA public`）+ create_all + 种子，`set_database_url` 切换全局引擎；TestClient 场景引擎走 NullPool（跨事件循环安全）。新增测试直接用 `get_session`/`db_session_factory`。
- 联调依赖：mock 内部服务（`:8001`）、sandbox-daemon（`:9000`），见 README「快速开始」。
- 迁移/种子单步执行：`uv run alembic upgrade head`、`uv run python -m seed.v1__base_seed`（一般不必手动：`bash scripts/dev_db_pg.sh` 已串两者）。