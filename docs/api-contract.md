# 接口契约文档（LCT-predict-agent）

> **版本**：v1.0 · 2026-08-21
> **文档性质**：前后端 + AI 工具三方唯一对接依据（字段级）。
> **事实来源**：`backend/src/` 实际代码（**唯一信源**）；`docs/tech_design.md` 仅交叉参照。
> **标注体系**：
> - `【与 tech_design 偏差】` —— 代码与 tech_design 不一致处，以代码为准，不静默纠正。
> - `【待核验】` —— 需运行时才能确定的返回结构，照代码推演并给代码依据位置。
> - `【待代码落盘后复核】` —— T38/T43 计划内但代码未落地，据 `docs/plans/` 补充，字段以最终代码为准。
> - `【drift/bug】` —— 代码内部不一致（参数接收但未生效等），联调需规避。

---

## 0. 关键命名与约定

### 0.1 统一响应壳

除 SSE、`/healthz`、`/readyz`、`/trace/export` 外，所有 HTTP 接口用统一壳：

```json
{ "code": "0", "message": "ok", "data": { } }
```

- 成功：`code="0"`、`message="ok"`、`data` 为业务载荷（见各接口）。
- 失败（业务异常）：`code` 为七错误码之一，`message` 为中文可读文案，`data` 为附加详情（多为 `null`，少数带 `{code, ...}`）。

### 0.2 命名映射（snake_case / camelCase）

**本项目前端不做 camelCase 转换，直接消费后端 snake_case 字段**（`frontend/src/api/*.ts` 中 TS interface 亦为 snake_case：`message_id`、`trace_id`、`next_cursor`、`created_at` 等）。因此：

> **约定：HTTP/SSE 字段名 = 数据库 snake_case 字段名（同名直通），无需转 camelCase。**

仅以下字段存在「数据库列名 ↔ API 字段名」**不同名**（需显式转换）：

| 数据库列名（snake_case） | API 对外字段 | 说明 |
|---|---|---|
| `credential_encrypted` | `credential_encrypted`（值恒 `"***"`） | 数据源凭据密文，列表脱敏 |
| `api_key_encrypted` | `api_key_encrypted`（值恒 `"***"`） | LLM api_key 密文，脱敏 |
| `password_hash` | （**不对外**） | 永不出现在任何 API 响应 |

### 0.3 鉴权术语

| 依赖 / 机制 | 语义 |
|---|---|
| 无 | 无需令牌 |
| `get_current_user` | 有效 `Authorization: Bearer <access_token>`（token_type=access），否则 401 |
| `require_perm("x")` | `get_current_user` + 校验 `x ∈ perms`；特殊：`adm:*` 权限点在 `is_admin` 下亦放行（含 `admin` 角色）；否则 403 + `authz.denied` 审计 |
| `require_owner` | 数据级 owner 校验骨架；实际 owner 校验在各 `chat_service` 内做（越权/不存在统一 404，不泄露存在性） |
| `/admin/**` 中间件 | `AdminPrefixMiddleware` 类级硬化：无 token→401；token 合法但非 admin→403 + 审计（在路由函数执行前拦截） |

**权限点全量字典**（seed `v1__base_seed.py`）：

```
用户域：chat:read / chat:send / chat:stop / chat:delete / trace:read
管理域：adm:user.manage / adm:tool.manage / adm:llm.manage / adm:config.manage / audit:read
角色：user（5 权限）/ admin（全部 10 权限）
```

### 0.4 统一错误码（对齐 tech_design 附录 D）

| code | HTTP | 含义 |
|---|---|---|
| `400_VALIDATION` | 400 | 参数校验失败 |
| `401_UNAUTHORIZED` | 401 | 未认证或凭证失效 |
| `403_FORBIDDEN` | 403 | 权限不足（越权触发审计） |
| `404_NOT_FOUND` | 404 | 资源不存在 |
| `409_CONFLICT` | 409 | 资源状态冲突（含 `FLOW_ACTIVE`、幂等冲突） |
| `500_INTERNAL` | 500 | 内部错误 |
| `429_RATE_LIMIT` | 429 | 请求过于频繁或临时锁定 |

- **补充业务码（非七错误码）**：`POST /admin/audits/export` 返回 `code="501_NOT_IMPLEMENTED"`（P1 占位，HTTP 仍 200）。
- **`429` 语义**：代码定义 `RateLimitError`，但**无实际限流中间件触发点**【与 tech_design 偏差：§5.1 的 60 req/min 令牌桶未实现】。

### 0.5 通用请求约定

- `Authorization: Bearer <access_token>`（JWT HS256，claims：`sub/email/roles/perms/token_type/iat/exp/jti`）。
- `Idempotency-Key`：仅 `POST /chat/conversations/{cid}/messages` 支持；入库键 = `SHA-256(user_id|conversation_id|client_key)`。
- `X-Request-Id`：请求头透传（无则 uuid4），响应头回填。
- `X-Refresh-Token`：仅 `POST /auth/logout` 携带（吊销 refresh）。

---

## 1. 认证接口（auth）

### 1.1 POST /auth/register — 无鉴权

请求体：

| 字段 | 类型 | 必填 | 默认 | 示例 |
|---|---|---|---|---|
| email | string | 是 | — | `"zhang.san@corp.com"` |
| password | string | 是 | — | `"Passw0rd123"` |
| nickname | string | 否 | null（→邮箱前缀） | `"张三"` |

响应 `data`：

| 字段 | 类型 | 说明 | 示例 |
|---|---|---|---|
| user_id | string | 用户 UUID | `"8f7c...uuid"` |
| email | string | 规范化邮箱（strip+lower） | `"zhang.san@corp.com"` |

错误：`400_VALIDATION`（密码政策≥10 位含大小写数字 / 邮箱后缀不在白名单）；`404_NOT_FOUND`（预置角色 user 未初始化）；`409_CONFLICT`（该邮箱已注册）。

### 1.2 POST /auth/login — 无鉴权

请求体：`email`（string，必填）、`password`（string，必填）。

响应 `data`：

| 字段 | 类型 | 示例 |
|---|---|---|
| access_token | string | `"eyJhbGciOi..."` |
| expires_in | number | `900`（15min，秒） |
| refresh_token | string | `"eyJhbGciOi..."` |
| user.id / user.email / user.nickname | string | `"8f7c...uuid"` / `"zhang.san@corp.com"` / `"张三"` |

错误：`401_UNAUTHORIZED`（邮箱或密码错误 / 账号已被禁用）；`429` 语义（登录失败锁定，代码 `assert_not_locked`）。

### 1.3 GET /auth/me — `get_current_user`

响应 `data`（`UserContext.to_dict()`，nickname/email 从库中实时值覆盖）：

| 字段 | 类型 | 示例 |
|---|---|---|
| id | string | `"8f7c...uuid"` |
| email | string | `"zhang.san@corp.com"` |
| nickname | string | `"张三"` |
| roles | string[] | `["user"]` |
| perms | string[] | `["chat:read","chat:send",...]` |

### 1.4 POST /auth/refresh — 无鉴权

请求体：`refresh_token`（string，必填）。

响应 `data`（与 login 同结构）：`access_token` / `refresh_token`（轮换）/ `expires_in` / `user{id,email,nickname}`。

错误：`401_UNAUTHORIZED`（令牌类型错误 / 刷新令牌已失效 / 已过期 / 用户不存在）。

### 1.5 POST /auth/logout — `get_current_user` + `X-Refresh-Token` 头

请求：无 body；**Header `X-Refresh-Token`（必填）**。

响应 `data`：`{ "ok": true }`。

错误：`400_VALIDATION`（缺少 X-Refresh-Token 头）。注意：refresh 无效时**静默返回 ok**（不报错）。

### 1.6 PATCH /auth/password — `get_current_user`

请求体：`old_password`（string，必填）、`new_password`（string，必填）。

响应 `data`：`{ "ok": true }`。

错误：`400_VALIDATION`（新密码政策）；`401_UNAUTHORIZED`（原密码错误）。

### 1.7 PATCH /auth/me — `get_current_user`

请求体：`nickname`（string，必填，≤32 字符，可中文）。

响应 `data`：`{ "id": "8f7c...uuid", "nickname": "新昵称" }`。

错误：`400_VALIDATION`（昵称为空 / 超 32 字符）；`404_NOT_FOUND`（用户不存在）。

---

## 2. 用户端 chat 接口

### 2.1 GET /chat/conversations — `require_perm("chat:read")`

查询参数：`cursor`（string?，no-op）、`limit`（int，默认 20，上限 100）。

响应 `data`：

| 字段 | 类型 | 示例 |
|---|---|---|
| items[] | array | 见下 |
| next_cursor | string\|null | `"8f7c...uuid"`（has_more 时最后一个 id，否则 null） |

每个 item：

| 字段 | 类型 | 说明 |
|---|---|---|
| id | string | 会话 UUID |
| title | string | `"新会话"` |
| status | string | `active/archived/deleted`（列表只含 active/archived） |
| pinned | bool | 是否置顶 |
| pinned_at | string\|null | ISO8601（置顶时间） |
| created_at | string\|null | ISO8601 |
| updated_at | string\|null | ISO8601 |

排序：置顶项在前（pinned_at 倒序），未置顶按 updated_at 倒序。

### 2.2 POST /chat/conversations — `require_perm("chat:read")`

请求体：`title`（string?，≤255，默认 `"新会话"`）。

响应 `data`：`{ "id", "title", "created_at" }`。

### 2.3 GET /chat/conversations/{cid} — `require_perm("chat:read")` + owner 校验

响应 `data`：`{ "id", "title", "status", "created_at" }`。

错误：`404_NOT_FOUND`（会话不存在 / 非本人，不区分）。

### 2.4 PATCH /chat/conversations/{cid} — `require_perm("chat:read")` + owner 校验

请求体：`title`（string，必填，≤255）。

响应 `data`：`{ "id", "title" }`。

### 2.5 PATCH /chat/conversations/{cid}/pin — `require_perm("chat:read")` + owner 校验

【与 tech_design 偏差：§5.2 接口表未列此置顶接口（T29 新增）】。

请求体：`pinned`（bool，必填）。

响应 `data`：`{ "id", "pinned", "pinned_at" }`（置顶记录 pinned_at，取消清空为 null）。不写审计。

### 2.6 DELETE /chat/conversations/{cid} — `require_perm("chat:delete")` + owner 校验

响应 `data`：`{ "ok": true }`。级联软删：conversation.status=deleted + deleted_at，关联 message 置 status=failed。

### 2.7 GET /chat/conversations/{cid}/messages — `require_perm("chat:read")` + owner 校验

查询参数：`cursor`（no-op）、`limit`（默认 20，上限 100）。

响应 `data.items[]`：

| 字段 | 类型 | 说明 |
|---|---|---|
| id | string | 消息 UUID |
| role | string | `user/assistant/system/tool` |
| content | string | 消息正文 |
| trace_id | string\|null | 追溯链 ID |
| status | string | `sent/running/interrupted/completed/failed` |
| created_at | string\|null | ISO8601 |

`next_cursor`：has_more 时最后一条 id，否则 null。消息按 created_at 倒序。

### 2.8 POST /chat/conversations/{cid}/messages — `require_perm("chat:send")` + owner 校验

请求体：`content`（string，必填，≤65536）；Header `Idempotency-Key`（string?）。

异步提交（202 语义，HTTP 实为 200）。响应 `data`：

| 字段 | 类型 | 说明 |
|---|---|---|
| message_id | string | assistant 消息载体 id（前端据此打开 SSE） |
| trace_id | string | 追溯链 UUID |
| conversation_id | string | 会话 UUID |
| idempotent | bool | 是否幂等命中 |

幂等命中时（同 Idempotency-Key 已存在）：返回 `{ message_id, trace_id, idempotent:true }`。

错误：`400_VALIDATION`（内容为空）；`404_NOT_FOUND`（会话不存在/非本人）；`409_CONFLICT`（`FLOW_ACTIVE`，该会话已有执行中流程，`data.detail.code="FLOW_ACTIVE"`）。

### 2.9 POST /chat/conversations/{cid}/messages/{mid}/stop — `require_perm("chat:stop")` + owner 校验

响应 `data`：`{ "ok": true }`。触发 `flow.cancel()`，若在运行则推 `done(status=interrupted)`。

### 2.10 GET /chat/conversations/{cid}/messages/{mid}/stream — `require_perm("chat:read")` + owner 校验（SSE）

响应：`200, Content-Type: text/event-stream`，响应头 `Cache-Control: no-store`、`X-Accel-Buffering: no`。连接建立即落库 `sse_opened` 事件（不对外 publish）。事件帧格式见 §6。

### 2.11 GET /chat/conversations/{cid}/messages/{mid}/trace — `require_perm("trace:read")` + owner 校验

响应 `data`：

| 字段 | 类型 | 说明 |
|---|---|---|
| trace_id | string\|null | 追溯链 ID |
| status | string | 消息当前状态 |
| conversation_id | string | 会话 UUID |
| message_id | string | 消息 UUID |
| events[] | array | 事件链（seq 升序） |

每个 event：`{ seq, type, payload, anomaly, created_at }`（`type` 为内部字典，见 §6.4；`payload` 为 JSONB）。

### 2.12 GET /chat/conversations/{cid}/messages/{mid}/trace/export — `require_perm("trace:read")` + owner 校验

响应：`text/markdown`，`Content-Disposition: attachment; filename="trace-{mid}.md"`。**不走统一响应壳**。

---

## 3. 运维接口（ops，无鉴权）

### 3.1 GET /healthz — 无鉴权（内网暴露）

**不走统一响应壳**，直接返回：

```json
{
  "status": "ok" | "degraded",
  "checks": {
    "db": { "status": "ok" | "error", "detail?": "..." },
    "llm": { "status": "ok" | "unhealthy" | "not_configured" | "error", "detail?": "..." },
    "sandbox_daemon": { "status": "ok" | "error" | "unreachable", "detail?": "..." }
  }
}
```

`status = "ok"` 当且仅当所有子项 status ∈ {ok, not_configured}，否则 `"degraded"`。

### 3.2 GET /readyz — 无鉴权

返回 `{"status": "ok"}`（HTTP 200）；DB 不可用返回 `{"status":"not_ready"}`（HTTP 503）。**不走统一响应壳**。

---

## 4. 管理员端接口（admin，前缀 `/api/v1/admin`）

> 全部受 `AdminPrefixMiddleware` 类级硬化 + 各 router 的 `require_perm`。

### 4.1 用户管理（users）— 类级 `require_perm("adm:user.manage")`

#### GET /admin/users

查询参数：`q`（string?，email/nickname 模糊）、`role`（string?，**no-op 未用**）、`status`（string?）、`cursor`（no-op）、`limit`（默认 20，上限 100）。

响应 `data`：`{ "items": [ { id, email, nickname, status, roles[], created_at } ] }`。

#### POST /admin/users

请求体：

| 字段 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| email | string | 是 | — | ≤255 |
| nickname | string | 否 | null（→""） | |
| initial_password | string | 是 | — | ≥10，≤128，密码政策 |
| role | string | 否 | `"user"` | 仅 `user/admin` |

响应 `data`：`{ "id", "email" }`。

错误：`409_CONFLICT`（邮箱已存在）；`400_VALIDATION`（角色非法 / 密码政策）；`404_NOT_FOUND`（角色不存在）。

#### PATCH /admin/users/{user_id}

请求体（均可空）：`nickname`（string?）、`role`（string?）、`status`（string?）。

响应 `data`：`{ "id" }`。

错误：`404_NOT_FOUND`（用户不存在）；`409_CONFLICT`（不能禁用自身账号 / 不能移除最后一名管理员）。

#### POST /admin/users/{user_id}/reset-password

请求体：`new_password`（string，必填，≥10≤128，密码政策）。

响应 `data`：`{ "ok": true }`。

错误：`404_NOT_FOUND`（用户不存在）；`400_VALIDATION`（密码政策）。

### 4.2 工具管理（tools）— 类级 `require_perm("adm:tool.manage")`

#### GET /admin/tools

响应 `data`：工具数组（每项）：

| 字段 | 类型 | 说明 |
|---|---|---|
| id | string | |
| name | string | `^[a-z][a-z0-9_]{1,63}$` |
| description | string | |
| status | string | `enabled/disabled` |
| input_schema | object | JSON Schema |
| output_schema | object | JSON Schema |
| execution | object | `{kind,image,handler,timeout_s,warm_pool,env_from_datasource,...}` |
| scenario_id | string\|null | |
| created_at / updated_at | string\|null | |

#### POST /admin/tools

请求体：

| 字段 | 类型 | 必填 | 默认 |
|---|---|---|---|
| name | string | 是 | — |
| description | string | 否 | `""` |
| input_schema | object | 是 | — |
| output_schema | object | 否 | `{}` |
| execution | object | 是 | — |
| scenario_id | string | 否 | null |

响应 `data`：`{ "id", "name" }`。

错误：`409_CONFLICT`（工具名已存在）；`400_VALIDATION`（schema/execution/name 非法，详见 §7.1）。

#### PATCH /admin/tools/{tool_id}

请求体（均可空）：`status`（`enabled/disabled`）、`description`、`execution`（局部合并更新）。

响应 `data`：`{ "id", "status" }`。

#### DELETE /admin/tools/{tool_id}

响应 `data`：`{ "ok": true }`。

错误：`409_CONFLICT`（有 sandbox_instances 引用 / 未先禁用）；`404_NOT_FOUND`（不存在）。

#### POST /admin/tools/{tool_id}/test

连通性测试。响应 `data`：`{ "<alias>": {"ok": bool, "detail": "..."} }`（逐数据源别名；数据源未注册时 `{"ok":false,"detail":"数据源未注册"}`）。

### 4.3 场景管理（scenarios）— 类级 `require_perm("adm:tool.manage")`

#### GET /admin/scenarios

响应 `data`：场景数组，每项 `{ id, code, name, model_ref, system_prompt, enabled }`（`model_ref` 为 `{provider_id, model}`）。

#### PATCH /admin/scenarios/{scenario_id}

请求体（均可空）：`name`、`system_prompt`、`enabled`（bool?）、`model_ref`（object? `{provider_id?, model}`）。

响应 `data`：`{ "id", "code" }`。

错误：`404_NOT_FOUND`（场景不存在）；`400_VALIDATION`（model_ref.provider_id 不存在 / model 为空）。

### 4.4 数据源管理（datasources）— 类级 `require_perm("adm:tool.manage")`

#### GET /admin/datasources

响应 `data`：数组，每项 `{ id, name, type, base_url, credential_encrypted:"***", whitelist[], enabled, created_at }`。

#### POST /admin/datasources

请求体：

| 字段 | 类型 | 必填 | 默认 |
|---|---|---|---|
| name | string | 是 | — |
| type | string | 否 | `"http_api"` |
| base_url | string | 是 | — |
| credential | string | 否 | `""` |
| whitelist | string[] | 否 | `[]` |
| enabled | bool | 否 | `true` |

响应 `data`：`{ "id", "name" }`。

错误：`409_CONFLICT`（名称已存在）；`400_VALIDATION`（出网声明不在白名单允许集内）。

#### PATCH /admin/datasources/{ds_id}

请求体（均可空）：`name`、`base_url`、`credential`、`whitelist`、`enabled`。

> 【与 tech_design 偏差 / drift】代码仅落库 `name`/`base_url`/`enabled`；`credential`/`whitelist` 字段 patch 中**未处理**（静默忽略）。

响应 `data`：`{ "id" }`。

#### POST /admin/datasources/{ds_id}/test

响应 `data`：`{ "ok": bool, "detail": "连接成功" | "连接失败: ..." }`（api 直连数据源 `/healthz/custom`，超时 5s）。

### 4.5 LLM 管理（llm）— 类级 `require_perm("adm:llm.manage")`

#### GET /admin/llm

响应 `data`：数组，每项 `{ id, name, vendor, base_url, api_key_encrypted:"***", models[], default_model, status, fallback_provider_id, healthy_updated_at }`。

#### POST /admin/llm

请求体：

| 字段 | 类型 | 必填 | 默认 |
|---|---|---|---|
| name | string | 是 | — |
| vendor | string | 否 | `"openai_compat"` |
| base_url | string | 是 | — |
| api_key | string | 否 | `""` |
| models | string[] | 否 | `[]` |
| default_model | string | 否 | `""` |
| fallback_provider_id | string | 否 | null |

响应 `data`：`{ "id", "name" }`。首供应商自动设为 `llm.default_provider_id`。

错误：`409_CONFLICT`（名称已存在）。

#### PATCH /admin/llm/{provider_id}

请求体（均可空）：`name`、`base_url`、`api_key`、`models`、`default_model`、`fallback_provider_id`。

响应 `data`：`{ "id" }`。

#### DELETE /admin/llm/{provider_id}

响应 `data`：`{ "ok": true }`。

错误：`409_CONFLICT`（被场景 model_ref 引用）；`404_NOT_FOUND`（不存在）。

#### POST /admin/llm/{provider_id}/health

响应 `data`：`{ "id", "status": "healthy"|"unhealthy", "healthy": bool }`（GET 供应商 `/models`）。

#### GET /admin/llm/default

响应 `data`：默认供应商（`provider_list_item`，脱敏）或 `null`（无默认）。

### 4.6 审计 / 会话 / 消息 / 追溯检索（audits）— 类级 `require_perm("audit:read")`

> 该类只读接口每次检索写 `audit.view` 留痕（`_mark_view`）。

#### GET /admin/sessions

查询参数：`q`（**no-op**）、`status`（**no-op**）、`owner_email`（**no-op**）、`cursor`（no-op）、`limit`（默认 20，上限 100）。

> 【与 tech_design 偏差 / drift】`q`/`status`/`owner_email` 路由接收但 `admin_list_sessions` **未按此过滤**（仅 `status != deleted`）。

响应 `data.items[]`：`{ id, owner_id, title, status, updated_at }`；`next_cursor`。

#### GET /admin/messages

查询参数：`q`（**no-op**）、`status`（**no-op**）、`owner_email`（string?，**生效**：join 按 owner email 过滤）、`cursor`（no-op）、`limit`。

响应 `data.items[]`：`{ id, conversation_id, role, content（截断 500 字符）, status, trace_id, created_at }`；`next_cursor`。

#### GET /admin/traces

查询参数：`trace_id`（string?）、`tool_name`（string?，JSONB `payload->>name` 过滤）、`error_code`（string?，`payload->>error_code` 过滤，大小写归一）、`actor_email`（string?，join 过滤）。

响应 `data`：`{ "items": [ { trace_id, message_id, seq, type, payload, created_at } ] }`。默认 limit 20，**无 cursor**。

#### GET /admin/traces/{trace_id}

响应 `data`：`{ "trace_id", "events": [ { seq, type, payload, created_at } ] }`。

错误：`404_NOT_FOUND`（追溯记录不存在）。

#### GET /admin/audits

查询参数：`type`（string?，=`action` 精确）、`actor`（string?，actor_email 模糊）、`target`（**no-op**）、`cursor`（no-op）、`limit`（默认 20）。

响应 `data.items[]`：`{ id, actor_id, actor_email, action, target_type, target_id, ip, detail, created_at }`。

#### GET /admin/audits/{audit_id}

响应 `data`：单条（同上述 item 结构）。

错误：`404_NOT_FOUND`（审计记录不存在）。

#### POST /admin/audits/export

响应 `data`：`{ "message": "审计导出为 P1 功能，本期未提供" }`，且 `code="501_NOT_IMPLEMENTED"`（P1 占位）。

### 4.7 系统参数（config）— 类级 `require_perm("adm:config.manage")`

#### GET /admin/config

响应 `data`：9 个白名单键的 `{ key: value }` 映射（默认值见 §0.5 / seed）：

```
retention.conversation_days=180, retention.audit_days=365,
auth.email_whitelist_suffixes=["@corp.com"], auth.login_fail_limit=5,
sandbox.max_concurrent=3, sandbox.timeout_s=30,
llm.default_provider_id=null, llm.default_model="", conversation.user_max_messages=48
```

#### PATCH /admin/config

请求体：`key`（string，必填，须 ∈ 上述 9 键）、`value`（any）。

响应 `data`：`{ "key", "value" }`（PATCH 即生效 + 失效缓存 + `adm.config.update` 审计）。

错误：`400_VALIDATION`（不允许修改系统参数 {key}）。

---

## 5.（随 SSE 章节一并编号，见 §6）

---

## 6. SSE 事件协议

### 6.1 连接与帧格式

- 连接端点：`GET /api/v1/chat/conversations/{cid}/messages/{mid}/stream`（消息级，§2.10）。
- 【待代码落盘后复核，T38】会话级：`GET /chat/conversations/{cid}/stream`（owner）与 `GET /admin/conversations/{cid}/stream`（audit:read + audit.view 留痕）。
- 帧格式：`id: <seq>`（可选）+ `event: <name>` + `data: <单行 JSON>` + 空行；心跳每 5s `: ping`。
- 生命周期：websocket 由前端 fetch-stream 断开 → 降级为 3s trace 轮询兜底（`useSse.startListening`）。

### 6.2 事件名 ↔ payload 全表

| event（wire） | payload 字段 | 触发时机 | 消费方 |
|---|---|---|---|
| `message.delta` | `{ text: string }` | LLM 每个内容增量（`_emit_content_delta`） | Workbench 正文流式追加 |
| `agent.status` | `{ state: string }` | `_emit_agent_state` 第二路（不含 detail） | 前端状态指示 |
| `agent.process` | `{ state: string, detail?: string }` | `_emit_agent_state` 第一路（阶段/重试/降级/中断） | 思考链（T35） |
| `tool.call` | `{ name, input, plan_index: number, request_id }` | 工具开始执行 | ToolCard / 思考链 |
| `tool.result` | `{ name, output_summary, duration_ms, status: "ok" }` | 工具成功 | ToolCard |
| `tool.error` | `{ name, error_code, message, retried }` | 工具失败 | ToolCard（失败态） |
| `done` | `{ message_id, final_text, status }` | run_flow 结束（completed/interrupted/failed） | 前端收尾 |
| `error` | `{ code, message }` | run_flow 顶层异常 | 前端兜底 |
| `follow_up.suggestions` | `{ message_id, suggestions: [{id, text}] }` | done(completed) 后一次轻量 LLM（T32，不落库，失败静默） | follow-up 建议区 |
| `session.meta` | `{ conversation_id, event_total, token_total }` | 【T38，待落盘】连接回放完成时 | Live Tail 头部统计 |
| `session_pack` | `{ event_type, payload, seq, turn_index, ts }` | 【T38，待落盘】回放 + 实时事件包装 | Live Tail |

> 【与 tech_design 偏差】`message.created` 常量在 `events.py` 有定义（载荷 `{message_id}`），但 loop **从不 publish**（仅落库 `message_created`，见 §6.4）；`follow_up.suggestions` 为附录 A 未列的新增事件。

### 6.3 具体 payload 示例

```jsonc
// message.delta
{ "text": "根据查询结果，" }

// agent.process
{ "state": "executing" }          // 或 { "state": "retrying", "detail": "query_sales_data 失败 UPSTREAM，重试 1/2" }

// tool.call
{ "name": "query_sales_data", "input": {"dimensions":["region"],"time_range":{"start":"2026-02-01","end":"2026-07-31"},"filters":{}},
  "plan_index": 0, "request_id": "uuid" }

// tool.result（summary 化，完整数据在 message_event）
{ "name": "query_sales_data", "output_summary": {"rows_count": 6}, "duration_ms": 812, "status": "ok" }

// tool.error
{ "name": "predict_sales", "error_code": "UPSTREAM", "message": "预测服务返回 HTTP 500", "retried": 2 }

// done
{ "message_id": "msg-uuid", "final_text": "…全文…", "status": "completed" }
//【T38，待落盘】done 载荷扩展可选 usage: { prompt_tokens, completion_tokens }

// error
{ "code": "500_INTERNAL", "message": "执行失败" }

// follow_up.suggestions
{ "message_id": "msg-uuid", "suggestions": [ {"id":"1","text":"查看本月销售额"}, ... ] }
```

**`tool.result.output_summary` 摘要规则**（`_summarize`）：dict 含 `rows` → `{rows_count}`；含 `forecast` → 截断为前 5 条；str 超 2000 截断；其余原样。

### 6.4 内部事件字典（message_event.type ↔ SSE event 映射）

`message_events.payload` 落库的内部 type（附录 C）：

| 内部 type（落库） | SSE event | payload 差异 |
|---|---|---|
| `message_created` | （无 SSE） | `{ direction: "in", content }` |
| `agent_process` | `agent.process` | `{ state, detail? }` |
| `tool_call` | `tool.call` | `{ name, input, plan_index, request_id }` |
| `tool_result` | `tool.result` | `{ name, output（完整）, duration_ms, status }` ← **注意落库用 `output`，SSE 用 `output_summary`** |
| `tool_error` | `tool.error` | `{ name, error_code, message, retried }`（同） |
| `sse_opened` | （无 SSE） | `{}` |
| `done` | `done` | `{ final_text, status }`（**无 message_id**） |

---

## 7. 工具衔接（两段）

### 7.1 Agent ↔ 工具协议

#### 7.1.1 工具注册三要素

工具实体由 `input_schema`（JSON Schema）、`output_schema`（JSON Schema）、`execution`（运行时声明）构成。

**execution 结构**（`tools/validate.py` 强制）：

| 字段 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| kind | string | 是 | — | P0 仅 `"sandbox"`；T43 后扩 `"internal"` |
| image | string | 是 | — | 容器镜像 |
| handler | string | 是 | — | 容器内 `tools.<handler>.handle` |
| timeout_s | int | 否 | 30 | 正整数 |
| warm_pool | int | 否 | 0 | 非负整数（预热实例数） |
| env_from_datasource | string[] | 否 | `[]` | 绑定数据源别名（env 注入） |
| max_retries | int | — | 2（引擎读） | 工具重试上限 |

**schema 强制约束**（`validate_tool_schema`）：`input_schema.type=object`、含 `properties`、`required` 存在（缺失自动补全为全部 properties）、`additionalProperties=false`、合法 JSON Schema（Draft 2020-12）。

**工具到 OpenAI tools 协议**（`adapter_openai._normalize_tools`）：`{type:"function", function:{name, description, parameters: input_schema}}`。

#### 7.1.2 query_sales_data

- **input**（schema.json）：`dimensions: string[]`（必填，如 region/product/channel）、`time_range: {start, end: ISO日期}`（必填）、`filters: object`（可选，additionalProperties）。
- **output**：`{ rows: array, columns: string[], query_time: string }`。
- 容器 handler 调数据源 `POST {DS_BASE_URL}/query`（Bearer `DS_TOKEN_SALES_DATA`）。

示例：

```jsonc
// input
{ "dimensions": ["region"], "time_range": {"start":"2026-02-01","end":"2026-07-31"}, "filters": {} }
// output
{ "rows": [{"region":"华东区","product":"A","amount":123400,"month":"2026-02"}, ...],
  "columns": ["region","product","amount","month"], "query_time": "2026-08-21T09:00:00" }
```

#### 7.1.3 predict_sales

- **input**：`model: string`（默认 "default"）、`horizon: integer`（必填，≥1，预测期数）、`base: object`（预测基础 `{region, period}`）。
- **output**：`{ forecast: [{period, value}], meta: object }`。
- 容器 handler 调 `POST {base_url}/predict`。

示例：

```jsonc
// input
{ "model": "default", "horizon": 3, "base": {"region":"华东","period":"近6月"} }
// output
{ "forecast": [{"period":"2026-09","value":273000}, ...], "meta": {"model":"default","horizon":3,"unit":"元"} }
```

#### 7.1.4 render_dashboard（T43，【待代码落盘后复核】）

据 `docs/plans/render-dashboard-tool-2026-08-21.md`：

- **execution**：`{ kind: "internal", handler: "render_dashboard", timeout_s: 5 }`（进程内执行，**不进容器、不写 sandbox_instances**）。
- **input schema**：

```jsonc
{
  "layout": "single" | "grid",           // 可选
  "cards": [{
    "card_type": "line" | "bar" | "table",   // 必填
    "title": "…",                            // 必填
    "description": "…",                      // 可选
    "data": {
      "labels": ["2026-02","2026-03", ...],  // 必填
      "series": [{ "name": "销量", "values": [123, 456, ...] }]  // 必填
    }
  }]
}
```

- **输出**：与 input **同构**的统一 spec（缺失字段补默认值；非法输入 → 归一 error）。
- **透传**：render_dashboard 输出即 spec，`tool.result` SSE 载荷**完整携带不截断**；完整 spec 亦落 message_event payload。
- 工具描述（供 LLM 绑定引导）：「当用户查询/预测销售数据且需要可视化展示时调用」。

#### 7.1.5 工具调用事件与回灌

引擎 `_execute_tools_parallel`：模型 `tool_call.batch` → 逐工具 `tool_call` 事件 → 沙箱（或 internal）执行 → `tool_result`/`tool_error` 事件 → **结果回灌 OpenAI tool role**：

```jsonc
{ "role": "tool", "content": "{\"tool_call_id\":\"...\",\"tool_name\":\"...\",\"result\":{...}}", "tool_call_id": "..." }
```

### 7.2 后端 ↔ sandbox-daemon 协议

鉴权：`X-Internal-Token`（`api_internal_token` 与 daemon `API_INTERNAL_TOKEN` 互认；`/healthz` 豁免）。Base URL `{sandbox_daemon_url}`（默认 `http://127.0.0.1:9000`）。

#### POST /run

请求（api `sandbox/client.py` 构造）：

| 字段 | 类型 | 说明 |
|---|---|---|
| tool_execution | object | 工具 execution 声明 |
| datasource_creds | object | `{DS_TOKEN_<NAME>, DS_BASE_URL_<NAME>}` 注入容器 env（不落日志） |
| input | object | 工具入参（→ 容器 env `TOOL_INPUT_JSON`） |
| request_id | string | uuid |
| timeout_s | int | 有效超时（execution.timeout_s 或 settings） |

响应（daemon 200）：

```jsonc
// 成功
{ "ok": true, "output": {…}, "container_id": "abc123…", "request_id": "…",
  "reused_warm": false, "exit_code": 0, "duration_ms": 812, "mode": "docker" }
// 失败
{ "ok": false, "error": { "code": "SANDBOX"|"TIMEOUT", "message": "…", "retryable": true },
  "container_id": "…", "request_id": "…", "exit_code": 1, "duration_ms": 812, "mode": "docker" }
```

#### POST /warm

Query/form：`image`（string?，默认 `TOOL_BASE_IMAGE`）。

响应：`{ "ok": bool, "image": "…", "detail": "pulled"|"already warm"|"pull-failed" }`（TTL 60s 幂等）。

#### GET /healthz

响应（**豁免鉴权**）：`{ "status": "ok"|"degraded", "docker_engine": bool, "mode": "docker", "whitelist": "…", "tool_base_image": "…" }`。

#### POST /stop-request

请求：`{ "request_id": "…" }`。响应：`{ "ok": true, "request_id": "…", "detail": "cancellation handshake (P0)" }`（P0 占位）。

#### ToolExecutionResult 三态归一（api 侧）

`ToolExecutionResult`（`sandbox/client.py`）三个成功/失败来源归一：

| 结果 | ok | error_code | retryable | 触发 |
|---|---|---|---|---|
| 业务成功 | true | — | — | daemon `body.ok=true` |
| 业务 error | false | `error.code`（如 `UPSTREAM`/`VALIDATION`/`SANDBOX`） | `error.retryable` | daemon `ok=false` 透传 |
| HTTP 超时 | false | `TIMEOUT` | true | `httpx.TimeoutException` |
| daemon 不可达/HTTP ≠200 | false | `SANDBOX` | true | `httpx.HTTPError` / 非 200 |

`to_dict()`（回灌 message）：`{ ok, output, error:{code,message,retryable}|null, duration_ms, request_id, container_id, exit_code, reused_warm }`。

容器运行时硬约束（`sd/runner.py`）：只读 rootfs、`cap_drop all`+`cap_add NET_BIND_SERVICE`、`no-new-privileges`、非 root(`1000:1000`)、`sandbox-net` + iptables 白名单、内存/cpu/pids 限制。工具 handler 输出协议见 `sd/tool_runtime.py`：`{ok, data}` 或 stdout 非 JSON 时包 `{data:{stdout}}`。

---

## 8. 数据库字段对照（17 表）

> 仅字段对照 + 约束；完整 DDL 见 tech_design §4.1。**API 对外字段 = 同名 snake_case**（§0.2），此处列「API 暴露情况」。

### 8.1 users

| 列 | 类型 | 约束 | API 暴露 |
|---|---|---|---|
| id | String(36) PK | | `id` |
| email | String(255) | unique, not null | `email` |
| password_hash | String(255) | not null | ❌（永不） |
| nickname | String(64) | not null, default "" | `nickname` |
| status | String(16) | check active/disabled | `status` |
| created_at/updated_at | timestamptz | | `created_at`（部分接口） |

索引：`idx_users_status(status)`。

### 8.2 refresh_tokens

| 列 | 类型 | 约束 | API 暴露 |
|---|---|---|---|
| id | String(36) PK | | ❌ |
| user_id | String(36) FK | not null | ❌ |
| token_hash | String(64) | unique（SHA-256） | ❌ |
| expires_at | timestamptz | not null | ❌ |
| revoked_at | timestamptz | null | ❌ |
| replaced_by | String(36) | 自引用 FK | ❌ |
| created_at / ip / user_agent | | | ❌ |

索引：`idx_refresh_user(user_id, revoked_at)`。

### 8.3 roles

| 列 | 类型 | 约束 | API 暴露 |
|---|---|---|---|
| id | String(36) PK | | ❌（仅 code） |
| code | String(64) | unique | `roles[]`（`/auth/me`、`admin users`） |
| name | String(64) | | ❌ |
| builtin | bool | default true | ❌ |
| created_at | | | ❌ |

### 8.4 permissions

| 列 | 类型 | 约束 | API 暴露 |
|---|---|---|---|
| id | String(36) PK | | ❌ |
| code | String(128) | unique | `perms[]`（`/auth/me`） |
| name / scope / desc | String | | ❌ |

### 8.5 role_permissions（复合主键）

| 列 | 类型 | 约束 | API 暴露 |
|---|---|---|---|
| role_id | String(36) PK FK | ondelete cascade | ❌ |
| permission_id | String(36) PK FK | | ❌ |

### 8.6 user_roles

| 列 | 类型 | 约束 | API 暴露 |
|---|---|---|---|
| id | String(36) PK | | ❌ |
| user_id / role_id | FK | `UNIQUE(user_id, role_id)` | ❌ |
| created_at | | | ❌ |

### 8.7 conversations

| 列 | 类型 | 约束 | API 暴露 |
|---|---|---|---|
| id | String(36) PK | | `id` |
| owner_id | String(36) FK | not null | `owner_id`（仅 admin sessions 列表） |
| title | String(255) | | `title` |
| status | String(16) | check active/archived/deleted | `status` |
| pinned | bool | default false | `pinned` |
| pinned_at | timestamptz | null | `pinned_at` |
| created_at/updated_at | | onupdate | `created_at`/`updated_at` |
| deleted_at | timestamptz | null | ❌ |

索引：`idx_conv_owner(owner_id, updated_at)`、`idx_conv_owner_pin(owner_id, pinned, pinned_at, updated_at)`、`idx_conv_status(status)`。

### 8.8 messages

| 列 | 类型 | 约束 | API 暴露 |
|---|---|---|---|
| id | String(36) PK | | `id` |
| conversation_id | String(36) FK | | `conversation_id`（admin） |
| role | String(16) | check user/assistant/system/tool | `role` |
| content | String | | `content` |
| trace_id | String(36) | null | `trace_id` |
| status | String(16) | check sent/running/interrupted/completed/failed | `status` |
| idem_key | String(64) | 部分唯一（非空时） | ❌ |
| created_at/updated_at | | | `created_at` |

索引：`uq_msg_idem(idem_key)`、`idx_msg_conv(conversation_id, created_at)`、`idx_msg_trace(trace_id)`。

### 8.9 message_events

| 列 | 类型 | 约束 | API 暴露 |
|---|---|---|---|
| id | String(36) PK | | ❌ |
| trace_id | String(36) | not null | `trace_id`（trace 还原） |
| message_id | String(36) FK | | `message_id` |
| seq | int | not null（同 trace 递增） | `seq` |
| type | String(32) | §6.4 字典 | `type` |
| payload | JSONB | | `payload` |
| anomaly | bool | default false | `anomaly` |
| created_at | | | `created_at` |

索引：`idx_evt_trace(trace_id, seq)`、`idx_evt_msg(message_id, seq)`、`idx_evt_type(type)`、`idx_evt_payload(payload GIN)`。

### 8.10 checkpoints

| 列 | 类型 | 约束 | API 暴露 |
|---|---|---|---|
| id | String(36) PK | | ❌ |
| conversation_id / message_id | FK | | ❌ |
| seq | int | `UNIQUE(message_id, seq)` | ❌ |
| state | JSONB | 消息快照/游标/场景/供应商 | ❌ |
| trace_id | String(36) | | ❌ |

索引：`uq_ckpt_msg_seq(message_id, seq)`、`idx_ckpt_conv(conversation_id, seq)`。

### 8.11 scenarios

| 列 | 类型 | 约束 | API 暴露 |
|---|---|---|---|
| id | String(36) PK | | `id` |
| code | String(64) | unique | `code` |
| name | String(128) | | `name` |
| model_ref | JSONB | `{provider_id, model}` | `model_ref` |
| system_prompt | String | | `system_prompt` |
| enabled | bool | | `enabled` |
| created_at/updated_at | | | ❌（列表未含） |

### 8.12 tools

| 列 | 类型 | 约束 | API 暴露 |
|---|---|---|---|
| id | String(36) PK | | `id` |
| name | String(64) | unique | `name` |
| description | String | | `description` |
| status | String(16) | check enabled/disabled | `status` |
| input_schema | JSONB | | `input_schema` |
| output_schema | JSONB | | `output_schema` |
| execution | JSONB | | `execution` |
| scenario_id | String(36) FK | null | `scenario_id` |
| created_at/updated_at | | | `created_at`/`updated_at` |

索引：`idx_tools_scenario(scenario_id)`。

### 8.13 data_sources

| 列 | 类型 | 约束 | API 暴露 |
|---|---|---|---|
| id | String(36) PK | | `id` |
| name | String(64) | unique | `name` |
| type | String(16) | default http_api | `type` |
| base_url | String | | `base_url` |
| credential_encrypted | String | | `credential_encrypted` → `"***"` |
| whitelist | TEXT[] | | `whitelist` |
| enabled | bool | | `enabled` |
| created_at/updated_at | | | `created_at` |

### 8.14 llm_providers

| 列 | 类型 | 约束 | API 暴露 |
|---|---|---|---|
| id | String(36) PK | | `id` |
| name | String(64) | unique | `name` |
| vendor | String(32) | default openai_compat | `vendor` |
| base_url | String | | `base_url` |
| api_key_encrypted | String | | `api_key_encrypted` → `"***"` |
| models | JSONB | | `models` |
| default_model | String(128) | | `default_model` |
| status | String(16) | check healthy/unhealthy | `status` |
| fallback_provider_id | String(36) | null | `fallback_provider_id` |
| updated_at / healthy_updated_at | | | `healthy_updated_at` |

索引：`idx_llm_status(status)`。

### 8.15 sandbox_instances

| 列 | 类型 | 约束 | API 暴露 |
|---|---|---|---|
| id | String(36) PK | | ❌ |
| tool_id | String(36) FK | | ❌ |
| trace_id / message_id | String(36) | null | ❌ |
| request_id | String(64) | | ❌ |
| container_id | String(64) | | ❌ |
| status | String(16) | check created/running/completed/timeout/error/aborted | ❌ |
| reused_warm | bool | default false | ❌ |
| image | String(255) | | ❌ |
| exit_code | int | null | ❌ |
| started_at / terminated_at | | | ❌ |

索引：`idx_sb_trace(trace_id)`、`idx_sb_status(status, started_at)`。

### 8.16 audit_logs

| 列 | 类型 | 约束 | API 暴露 |
|---|---|---|---|
| id | String(36) PK | | `id` |
| actor_id / actor_email | String | | `actor_id`/`actor_email` |
| action | String(64) | | `action`（见 §8.17 action 字典） |
| target_type / target_id | String | | `target_type`/`target_id` |
| ip | String(64) | | `ip` |
| detail | JSONB | | `detail` |
| created_at | | | `created_at` |

索引：`idx_audit_actor(actor_id, created_at)`、`idx_audit_action(action, created_at)`、`idx_audit_target(target_type, target_id)`、`idx_audit_created(created_at)`。

### 8.17 system_config

| 列 | 类型 | 约束 | API 暴露 |
|---|---|---|---|
| key | String(128) PK | | `key`（§4.7） |
| value | JSONB | | `value` |
| updated_by | String(36) | null | ❌ |
| updated_at | | onupdate | ❌ |

### 8.18 audit action 字典（`tracing/audit.py`）

`auth.register / auth.login / auth.login_failed / auth.logout / auth.password / auth.profile_update / authz.denied / audit.view / chat.conversation.delete / chat.conversation.update / adm.user.create / adm.user.update / adm.user.reset_password / adm.tool.create / adm.tool.update / adm.tool.delete / adm.tool.test / adm.datasource.create / adm.datasource.update / adm.datasource.test / adm.llm.create / adm.llm.update / adm.llm.health / adm.config.update / adm.scenario.update / system.retention / system.llm.probe`

---

## 9. 偏差清单（代码 ↔ tech_design）

| # | 项 | 代码实际 | tech_design | 影响 |
|---|---|---|---|---|
| 1 | 分页协议 | 响应体 `next_cursor` 字段 | §5.1 响应头 `X-Next-Cursor` | 前端按 body 取值 |
| 2 | 限流 | 无触发点（仅定义错误类） | §5.1 60 req/min 令牌桶 | 429 永不触发 |
| 3 | SSE 事件 | 新增 `follow_up.suggestions` | 附录 A 未列 | 前端需消费 |
| 4 | SSE `message.created` | 有常量但从不 publish | 附录 A 列了 | 前端勿依赖 |
| 5 | 会话置顶 | `PATCH /chat/conversations/{cid}/pin` | §5.2 未列（T29） | 前端已封装 |
| 6 | 改昵称 | `PATCH /auth/me` | §5.2 未列（T28） | 前端已封装 |
| 7 | 成功码 | `code="0"` | 未明示 | 前端 `code!=='0'` 判错 |
| 8 | audits/export | `code="501_NOT_IMPLEMENTED"`（HTTP 200） | P1-7 | 前端勿当成功 |
| 9 | admin/sessions 过滤 | `q`/`status`/`owner_email` 未生效 | §3.11.4 | 检索结果偏全集 |
| 10 | datasource patch | `credential`/`whitelist` 未落库（静默忽略） | §3.6 | 前端慎用 |
| 11 | cursor 游标 | 各处 `cursor` 参数 no-op（仅 limit 生效） | §5.1 | 无限下拉可能重复 |
| 12 | tool_result 落库 vs SSE | 落库 `payload.output`（完整），SSE `output_summary`（摘要） | 附录 B 未区分 | 追溯还原用落库 |
| 13 | healthz/readyz | 直接 dict，不走统一壳 | §5.2 未显式例外 | 前端需单独解析 |
| 14 | 健康检查 llm not_configured | `healthz.checks.llm.status` 有 `not_configured` 枚举 | 未列 | 前端状态机覆盖 |
| 15 | render_dashboard | 未落盘（T43 计划） | §3.14 规范缺口 | 待实施 |
| 16 | 会话级 stream + session.meta | 未落盘（T38 计划） | 附录 A 无 | 待实施 |
| 17 | mock `usage` 未定义 | `mock_provider` 传 `DoneReasonEvent(usage=…)` 但该 dataclass 无 `usage` 字段 | T38 | 【drift/bug】T38 半成品，mock 下可能抛 TypeError |

---

> **文档结束。** 任一接口/事件/表可经关键词检索：接口小标题均含「方法 + 路径」，SSE 事件名、工具名、表名均为独立小节。