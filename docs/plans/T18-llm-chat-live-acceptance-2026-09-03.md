# T18 · LLM 聊天与沙箱追溯联调验收（llm-chat-live-acceptance）

- 任务 ID：T18
- 标题与目标：在当前 PG、backend、sandbox、icewash 和 frontend 栈上验证双登录、LLM 流式聊天、思考步骤、沙箱错误归一、trace 回查和会话交互契约。
- 关联文档章节：`docs/feat-icewash.md` §5、§10.2、§12；`docs/feat-sandbox.md`；T15、T16、T17
- 前置依赖 blockedBy：T16、T17

## 执行画像

- execution_mode：direct
- execution_class：e2e
- expected_duration：约 10 分钟，LLM/模型冷启动时按服务实际响应等待
- external_waits：PG、icewash、backend、sandbox daemon、frontend、LLM Provider
- checkpoint_phases：服务健康、email 登录、SSE 流、trace/沙箱、前端构建
- resume_boundary：保留临时响应文件，从失败的验收阶段继续

## 问题

- T15 已验证 email-only 主链路，但独立的流式事件顺序、追溯读取、沙箱 daemon 状态和前端智能跟随/思考展开尚未形成一组可重复的回归证据。
- 真实聊天使用 PG 默认 Provider；验收需要同时证明健康徽标、SSE 结果和数据库 trace 指向同一条消息，且响应不泄露 token。

## 决策

- 使用 `backend/.env` 中已有账号和服务配置，凭据仅由 shell 环境变量读取，命令输出只保留状态码、事件名和字段断言。
- 通过 `/api/chat/stream` 验证 `status → result → done`；从 SSE 的 `message_id/session_id` 回查 `/api/v1/chat/conversations/{cid}/messages/{mid}/trace`，再检查 `messages.result_envelope`。
- 沙箱先验证 `/healthz`，再使用离线 pytest 的 respx 三态结果作为执行证据；若 Docker 工具镜像不可用，只记录外部执行阻塞，不改变代码状态。

## 范围

- 包含：运行栈健康、email 登录、流式聊天、trace 查询/导出、sandbox health、前端构建和用户可见状态。
- 不包含：打印账号密码/token、修改生产数据、OA 外部网关强依赖或新增数据库迁移。

## 环境预检

- 必需 Shell：git-bash
- 必需命令：`curl`、`python`、`uv`、`npm`、`docker`
- 必需端口：8000、8001、9000、5173
- 必需 URL：`/healthz`、`/api/health/agent`、`/api/chat/stream`、`/api/sessions`
- 必需 Python 模块：`httpx`、`pytest`
- 必需 Docker 容器：`LCT-predict-agent-pg`
- 容器内必需命令：`LCT-predict-agent-pg:psql`
- 容器内必需 Python 模块：无
- 执行画像：e2e
- 启动超时（秒）：30
- 空闲超时（秒）：120
- 硬截止（秒）：1200
- 最大 checkpoint 间隔（秒）：180
- 预检命令：
  ```bash
  curl -fsS http://127.0.0.1:8000/healthz >/dev/null && curl -fsS http://127.0.0.1:9000/healthz >/dev/null && curl -fsS http://127.0.0.1:5173 >/dev/null
  ```

## 风险与回滚

- 风险：真实 LLM Provider、预测模型或 Docker 工具镜像可能暂时不可用；外部失败只标记对应证据为 blocked_external，不能用凭据失败替代离线回归结果。
- 回滚：本任务只写 `/tmp/lct-*` 响应文件和验收日志；清理命令为 `rm -f /tmp/lct-llm-* /tmp/lct-chat-* /tmp/lct-trace-*`，不删除仓库数据或容器。

## 实施步骤

### 步骤 1：验证服务健康与登录契约

- 对象：PG、icewash、backend、sandbox、frontend 和 email 登录接口。
- 动作：检查固定端口健康响应，读取 `.env` 的 admin 账号完成 email 登录，只将 access token 放入当前 shell 变量和请求头。
- 参数：登录请求为 `POST /api/v1/auth/login`；不打印 response body 中的 token；无认证请求 `/api/sessions` 必须为 401。
- 核心修改文件：`backend/tests/smoke_e2e.py`
- 必要集成文件：`docs/plans/T18-llm-chat-live-acceptance-2026-09-03.md`
- 命令：
  ```bash
  curl -fsS http://127.0.0.1:8000/healthz >/dev/null && curl -fsS http://127.0.0.1:9000/healthz >/dev/null && curl -fsS http://127.0.0.1:5173 >/dev/null
  ```

### 步骤 2：验证流式聊天、思考步骤与落库

- 对象：`POST /api/chat/stream`、SSE 事件和 `messages.result_envelope`。
- 动作：以 email backup JWT 发起一条 history 或 forecast 请求，保存 SSE 到 `/tmp/lct-chat-stream.sse`，断言状态事件、result、done 顺序和 result 字段；随后从 PG 回查 message/trace。
- 参数：超时 180 秒；事件顺序至少包含 `status`、`result`、`done`；不允许 SSE 文件出现 `Authorization`、`AGENT_API_KEY` 或 token 值；步骤数量不超过 40。
- 核心修改文件：`backend/tests/test_chat_stream_facade.py`
- 必要集成文件：`backend/src/app/api/chat_facade.py`、`frontend/src/components/ChatPanel.tsx`
- 命令：
  ```bash
  cd backend && uv run pytest tests/test_chat_stream_facade.py tests/test_chat_trace_regressions.py -q
  ```

### 步骤 3：验证沙箱与追溯可回查

- 对象：sandbox daemon `/healthz`、backend trace JSON/Markdown 接口和 sandbox 客户端离线三态。
- 动作：检查 daemon 返回 Docker 状态；执行沙箱/追溯定向测试；使用上一步 message id 请求 trace 与 trace/export，断言事件 seq 递增、tool/error/done 可见且 owner 越权为 404。
- 参数：trace export 为 `text/markdown`；异常响应只显示稳定 error code；不显示 secret、Authorization 或 datasource credential。
- 核心修改文件：`backend/tests/test_sandbox_client.py`、`backend/tests/test_tracing.py`
- 必要集成文件：`backend/src/app/tracing/query.py`
- 命令：
  ```bash
  curl -fsS http://127.0.0.1:9000/healthz && cd backend && uv run pytest tests/test_sandbox_client.py tests/test_tracing.py -q
  ```

### 步骤 4：验证前端构建和交互契约

- 对象：ChatPanel 会话菜单、注册入口、滚动跟随、思考展开和 AppShell 状态徽标。
- 动作：运行构建和静态契约检查；在已登录浏览器中手工点击删除/重命名/置顶、注册入口、思考过程按钮，并在流式输出时上滑验证不强制滚底。
- 参数：`npm run build`；思考按钮在展开态必须有 `aria-expanded="true"` 和“收起”；健康 Provider 模式显示可用状态。
- 核心修改文件：`frontend/src/components/ChatPanel.tsx`
- 必要集成文件：`frontend/src/pages/LoginPage.tsx`、`frontend/src/components/AppShell.tsx`
- 命令：
  ```bash
  cd frontend && npm run build && rg -n "注册账号|aria-expanded|aria-controls|回到底部|删除会话|Chat provider" src
  ```

## 完成标准

- 验收类型：mixed
- 离线验收命令：
  ```bash
  cd backend && uv run pytest tests/test_llm.py tests/test_llm_gateway.py tests/test_llm_stream_regressions.py tests/test_sandbox_client.py tests/test_tracing.py tests/test_chat_trace_regressions.py tests/test_chat_stream_facade.py -q && cd ../frontend && npm run build
  ```
- 外部环境验收命令：
  ```bash
  curl -fsS http://127.0.0.1:8000/healthz; curl -fsS http://127.0.0.1:8000/api/health/agent; curl -fsS http://127.0.0.1:9000/healthz; curl -fsS http://127.0.0.1:5173 >/dev/null
  ```
- 通过条件：离线测试与前端构建全部退出码为 0；外部健康端点可达；真实 SSE 在可用 Provider 下按 status/result/done 完成并可回查 trace；沙箱健康与三态归一有证据；前端会话、注册、智能滚动、思考展开和健康徽标满足参数化断言。
