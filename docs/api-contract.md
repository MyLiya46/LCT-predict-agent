# LCT-predict-agent API 契约

本文只描述当前后端注册的 HTTP 路由和当前已注册的 Agent 内部工具。字段、状态码和返回结构以当前源码为准；未列出的接口不属于当前契约。

当前 OpenAPI 注册了 69 个路径、83 个 HTTP 操作。

## 1. 全局约定

### 1.1 响应格式

以下接口成功响应使用统一响应壳：

- /api/v1/auth/*
- /api/v1/chat/* 的 JSON 操作
- /api/v1/admin/* 的 JSON 操作

格式：

~~~json
{
  "code": "0",
  "message": "ok",
  "data": {}
}
~~~

成功时 code 固定为字符串 0，业务载荷位于 data。SSE、追溯 Markdown 导出、健康检查、工作台、预测、归因、What-if、产品列表和 façade 接口返回裸载荷，不套此壳。

所有时间字段均为 ISO 8601 字符串或 null。字段名保持 snake_case，不做 camelCase 转换。

### 1.2 鉴权与请求头

需要登录的接口使用：

    Authorization: Bearer <access_token>

access token 默认有效 15 分钟，refresh token 默认有效 7 天并在刷新时轮换。/api/v1/admin/** 除有效 access token 外，还要求管理员身份；非管理员请求在路由执行前返回 403。

通用请求头：

| 请求头 | 适用接口 | 说明 |
|---|---|---|
| Authorization | 所有受保护接口 | 仅接受 access token |
| X-Request-Id | 所有 HTTP 请求，可选 | 未提供时后端生成 UUID；响应始终回写同名响应头 |
| Idempotency-Key | 原生/ façade 发送消息 | 用于同一用户、会话和客户端键的幂等 |
| X-Refresh-Token | /api/v1/auth/logout | 必填，放 refresh token |

口令、API key、数据源 credential、JWT 和 OAuth token 不应写入日志、追溯事件或管理列表。管理列表中的密文字段固定显示为三个星号；登录接口返回 token 是认证流程的必要结果，调用方必须按敏感凭据处理。

### 1.3 错误

领域异常使用统一错误体：

~~~json
{
  "code": "400_VALIDATION",
  "message": "参数校验失败",
  "data": null
}
~~~

当前业务错误码：

| code | HTTP | 语义 |
|---|---:|---|
| 400_VALIDATION | 400 | 业务参数或业务规则校验失败 |
| 401_UNAUTHORIZED | 401 | 未认证、token 无效或凭据错误 |
| 403_FORBIDDEN | 403 | 权限不足；会写 authz.denied 审计 |
| 404_NOT_FOUND | 404 | 资源不存在或 owner 不匹配 |
| 409_CONFLICT | 409 | 状态冲突、重复资源或会话已有运行流程 |
| 500_INTERNAL | 500 | 未处理的后端错误 |
| 502_UPSTREAM | 502 | 模型或参考服务不可用，使用统一错误壳的上游错误 |
| 429_RATE_LIMIT | 429 | 预留的限流/锁定错误码 |
| 501_NOT_IMPLEMENTED | 200 | 仅审计导出占位接口使用 |

FastAPI/Pydantic 请求结构校验仍返回默认 422：

~~~json
{
  "detail": [
    {"loc": ["body", "field"], "msg": "Field required", "type": "missing"}
  ]
}
~~~

What-if 上游代理失败使用 FastAPI 原生 HTTPException，返回 HTTP 502：

~~~json
{"detail": "icewash What-if 请求失败: ..."}
~~~

工作台知识接口、成本同步和预测同步失败属于领域异常，返回统一错误壳并使用 502_UPSTREAM。

## 2. 认证

### 2.1 POST /api/v1/auth/register

无需鉴权。

请求 JSON：

| 字段 | 类型 | 必填 | 约束 |
|---|---|---:|---|
| email | string | 是 | 最长 255；服务端 strip + lower |
| password | string | 是 | 最长 128；至少 10 位，且包含大小写字母和数字 |
| nickname | string/null | 否 | 省略时使用邮箱前缀 |

成功 data：

~~~json
{"user_id": "uuid", "email": "user@corp.com"}
~~~

邮箱后缀必须在系统白名单内，默认是 @corp.com。邮箱重复返回 409。

### 2.2 POST /api/v1/auth/login

无需鉴权。

请求 JSON：email 和 password 均为必填 string。

成功 data：

~~~json
{
  "access_token": "…",
  "expires_in": 900,
  "refresh_token": "…",
  "user": {
    "id": "uuid",
    "email": "user@corp.com",
    "nickname": "用户"
  }
}
~~~

当前实现没有返回 token_type 字段。凭据错误或账号禁用返回 401；连续失败锁定逻辑可能返回 429。

### 2.3 GET /api/v1/auth/me

需要 access token。

成功 data：

~~~json
{
  "id": "uuid",
  "email": "user@corp.com",
  "nickname": "用户",
  "roles": ["user"],
  "perms": ["chat:read", "chat:send", "chat:stop", "chat:delete", "trace:read"]
}
~~~

昵称和邮箱以数据库当前值为准。

### 2.4 POST /api/v1/auth/refresh

无需 access token。

请求 JSON：

~~~json
{"refresh_token": "…"}
~~~

成功 data 与登录接口相同，包含 access_token、expires_in、refresh_token 和 user；当前实现同样不返回 token_type。旧 refresh token 会被吊销。

### 2.5 POST /api/v1/auth/logout

需要 access token，并要求请求头 X-Refresh-Token。

成功 data：

~~~json
{"ok": true}
~~~

缺少请求头返回 400；refresh token 无效时注销操作静默成功。

### 2.6 PATCH /api/v1/auth/password

需要 access token。

请求 JSON：

~~~json
{"old_password": "旧密码", "new_password": "NewPass1234"}
~~~

两个字段均必填；新密码遵循统一口令策略。成功 data 为 {"ok": true}，旧密码错误返回 401。

### 2.7 PATCH /api/v1/auth/me

需要 access token。

请求 JSON：

~~~json
{"nickname": "新昵称"}
~~~

nickname 必填，最长 32 个字符，去除首尾空白后不得为空。成功 data：

~~~json
{"id": "uuid", "nickname": "新昵称"}
~~~

### 2.8 POST /api/auth/login

OA 登录，无本地 access token 鉴权；返回裸 JSON，不使用统一响应壳。

请求 JSON：

~~~json
{"oa": "oa-account"}
~~~

oa 必填，长度 1 到 128。

成功返回：

~~~json
{
  "oa": "oa-account",
  "access_token": "…",
  "refresh_token": "…",
  "token_type": "Bearer",
  "expires_in": 900,
  "oauth_access_token": "…",
  "oauth_token_type": "Bearer",
  "oauth_expires_in": 0
}
~~~

oauth_access_token 是上游 OAuth 凭据，只能由调用方安全保存和转发到受信任流程，不能展示或记录。

## 3. 原生会话、消息和追溯

原生接口前缀为 /api/v1/chat。除 SSE 和 Markdown 导出外，成功响应都使用统一响应壳。会话 owner 越权和不存在统一返回 404，不泄露资源存在性。

### 3.1 会话

#### GET /api/v1/chat/conversations

权限：chat:read。

查询参数：

| 参数 | 类型 | 默认 | 说明 |
|---|---|---:|---|
| cursor | string | null | 当前接收但未参与查询 |
| limit | integer | 20 | 服务端最多返回 100 条 |

成功 data：

~~~json
{
  "items": [
    {
      "id": "uuid",
      "title": "新会话",
      "status": "active",
      "pinned": false,
      "pinned_at": null,
      "created_at": "2026-09-07T10:00:00+00:00",
      "updated_at": "2026-09-07T10:00:00+00:00"
    }
  ],
  "next_cursor": null
}
~~~

只列 active 和 archived 会话；排序为置顶优先、置顶时间倒序，其余按更新时间倒序。

#### POST /api/v1/chat/conversations

权限：chat:read。

请求 JSON：title 可选，最长 255；省略或空值使用 新会话。

成功 data：

~~~json
{"id": "uuid", "title": "新会话", "created_at": "2026-09-07T10:00:00+00:00"}
~~~

#### GET /api/v1/chat/conversations/{cid}

权限：chat:read。

成功 data：

~~~json
{
  "id": "uuid",
  "title": "销售分析",
  "status": "active",
  "created_at": "2026-09-07T10:00:00+00:00"
}
~~~

#### PATCH /api/v1/chat/conversations/{cid}

权限：chat:read。

请求 JSON：{"title": "新标题"}；title 必填，最长 255。

成功 data：{"id": "uuid", "title": "新标题"}。

#### PATCH /api/v1/chat/conversations/{cid}/pin

权限：chat:read。

请求 JSON：{"pinned": true}。

成功 data：

~~~json
{"id": "uuid", "pinned": true, "pinned_at": "2026-09-07T10:00:00+00:00"}
~~~

取消置顶时 pinned_at 为 null。

#### DELETE /api/v1/chat/conversations/{cid}

权限：chat:delete。

成功 data：{"ok": true}。删除是软删除，会话变为 deleted，其消息状态改为 failed。

### 3.2 消息

#### GET /api/v1/chat/conversations/{cid}/messages

权限：chat:read。

查询参数 cursor 当前未生效；limit 默认 20，服务端最多 100。

成功 data：

~~~json
{
  "items": [
    {
      "id": "uuid",
      "role": "user",
      "content": "请查询销量",
      "trace_id": null,
      "status": "sent",
      "created_at": "2026-09-07T10:00:00+00:00"
    }
  ],
  "next_cursor": null
}
~~~

消息顺序为 created_at 倒序。role 由当前消息记录决定，通常为 user 或 assistant，也可能是 system、tool；status 由消息生命周期决定。

#### POST /api/v1/chat/conversations/{cid}/messages

权限：chat:send。

请求 JSON：

~~~json
{"content": "请查询冰箱近半年的实际销量"}
~~~

content 必填，最长 65536，去除空白后不得为空。可选请求头 Idempotency-Key。

成功 data：

~~~json
{
  "message_id": "assistant-message-uuid",
  "trace_id": "trace-uuid",
  "conversation_id": "conversation-uuid",
  "idempotent": false
}
~~~

接口实际 HTTP 状态为 200；语义上是异步提交。幂等命中时 idempotent=true，返回已存在的消息载体。单会话已有运行流程时返回 409，data 中包含 {"code": "FLOW_ACTIVE"}。

#### POST /api/v1/chat/conversations/{cid}/messages/{mid}/stop

权限：chat:stop。

成功 data：{"ok": true}。运行中的流程收到取消信号并最终产生 interrupted 状态。

### 3.3 追溯查询与导出

#### GET /api/v1/chat/conversations/{cid}/messages/{mid}/trace

权限：trace:read。

成功 data：

~~~json
{
  "trace_id": "trace-uuid",
  "status": "completed",
  "conversation_id": "conversation-uuid",
  "message_id": "message-uuid",
  "events": [
    {
      "seq": 1,
      "type": "message_created",
      "payload": {"direction": "in", "content": "…"},
      "anomaly": false,
      "created_at": "2026-09-07T10:00:00+00:00"
    }
  ]
}
~~~

当前持久化事件类型包括 message_created、agent_process、tool_call、tool_result、tool_error、done 和连接内部事件 sse_opened。没有 trace 的消息仍返回 events: [] 和 trace_id: null。

#### GET /api/v1/chat/conversations/{cid}/messages/{mid}/trace/export

权限：trace:read。

成功响应为 text/markdown，不使用统一响应壳，并带：

    Content-Disposition: attachment; filename="trace-{mid}.md"

正文是按事件序号生成的 Markdown 追溯报告。

## 4. 工作台 chat façade

这些接口直接返回裸 JSON，前缀为 /api。它们使用原生会话和 Agent 引擎，但返回面向工作台的投影。

### 4.1 会话 façade

#### GET /api/sessions

权限：chat:read。

返回会话摘要数组，每项字段为：

~~~json
{
  "id": "uuid",
  "title": "新会话",
  "status": "active",
  "pinned": false,
  "pinned_at": null,
  "created_at": "2026-09-07T10:00:00+00:00",
  "updated_at": "2026-09-07T10:00:00+00:00"
}
~~~

当前 façade 固定取最多 100 条，不返回 next_cursor。

#### PATCH /api/sessions/{session_id}

权限：chat:read。

请求 JSON 至少提供一个字段：

| 字段 | 类型 | 约束 |
|---|---|---|
| title | string/null | 最长 255；提供时不得为空 |
| pinned | boolean/null | 置顶状态 |

成功返回完整会话摘要。最多允许置顶 5 个会话。

#### DELETE /api/sessions/{session_id}

权限：chat:delete。

成功返回 {"ok": true}。

#### GET /api/sessions/{session_id}

权限：chat:read。

成功返回：

~~~json
{
  "id": "uuid",
  "title": "销售分析",
  "messages": [
    {
      "id": "uuid",
      "role": "user",
      "content": "请查询销量",
      "result_envelope": null,
      "created_at": "2026-09-07T10:00:00+00:00"
    },
    {
      "id": "uuid",
      "role": "assistant",
      "content": "……",
      "result_envelope": {},
      "created_at": "2026-09-07T10:00:01+00:00"
    }
  ]
}
~~~

这里只返回 user 和 assistant 消息，按时间正序；用户消息的 result_envelope 为 null。

### 4.2 工作台聊天

#### POST /api/chat

权限：chat:send。可选 Idempotency-Key。

请求 JSON：

| 字段 | 类型 | 必填 | 默认/说明 |
|---|---|---:|---|
| message | string | 是 | 1 到 65536；去空白后不得为空 |
| session_id | string/null | 否 | 省略则创建会话 |
| params | object | 否 | 默认 {}；当前 bridge 不读取该字段 |
| oa | string/null | 否 | 传给 Agent 上游的 OA 标识 |
| access_token | string/null | 否 | 传给 Agent 上游的请求 token，不是本地 JWT |

成功返回：

~~~json
{
  "session_id": "uuid",
  "message_id": "uuid",
  "reply": "最终文本",
  "envelope": {
    "response_type": "history",
    "text": {"title": "…", "markdown": "…"},
    "meta": {},
    "follow_ups": [],
    "update_workspace": true,
    "process_steps": [],
    "intent": "history"
  },
  "update_workspace": true
}
~~~

envelope.response_type 当前可能为 history、forecast、attribution、simulation、optimization 或 report。成功的结构化工具结果还可能提供 chart、table 以及对应领域字段。

#### POST /api/chat/stream

权限：chat:send。请求体和请求头同 /api/chat。

响应为 text/event-stream，响应头包含 Cache-Control: no-cache、Connection: keep-alive 和 X-Accel-Buffering: no。帧格式为 event 加单行 JSON data：

| event | data |
|---|---|
| delta | {"text": "增量文本"} |
| status | {"stage": "executing", "text": "正在调用数据能力…", "steps": ["…"]} |
| result | /api/chat 成功返回体，并额外包含 steps |
| done | {"ok": true} |

客户端应以 result 作为最终业务结果，done 只表示 façade 流已结束。

### 4.3 产品与 Agent 配置探测

#### GET /api/products

权限：chat:read。

返回裸数组：

~~~json
[
  {"id": "SKU001", "sku": "SKU001", "name": "SKU001", "category": "冰箱", "brand": ""}
]
~~~

数据来自预测结果表，按 SKU 去重；缺少 SKU 或品类的记录不返回。

#### GET /api/agent/probe/template

权限：chat:read。查询参数 stream: boolean，默认 false。

返回：

~~~json
{
  "url": "https://…",
  "mode": "blocking",
  "headers": {"Content-Type": "application/json"},
  "body": {"query": "", "response_mode": "blocking", "inputs": {}}
}
~~~

stream=true 时 mode 和 body.response_mode 为 streaming。

#### POST /api/agent/probe

权限：chat:read。

请求 JSON：

~~~json
{
  "url": "https://…",
  "headers": {},
  "body": {}
}
~~~

字段均可选。当前实现只返回本地配置状态：

~~~json
{
  "ok": true,
  "mode": "blocking",
  "configured_mode": "blocking",
  "provider": "ml-gateway",
  "url": "https://…"
}
~~~

未配置 Agent key 时增加 error 字段。请求中的 url、headers 和 body 当前不会被转发、校验或回显。

## 5. 健康检查

### GET /api/health/agent

无需鉴权。返回 Agent 配置/供应商状态的裸 JSON，常见结构：

~~~json
{
  "ok": true,
  "mode": "live",
  "configured_mode": "blocking",
  "url": "https://…",
  "provider": "ml-api-gateway"
}
~~~

没有 Agent key 时 mode 为 disabled 并带 error。配置不可用时，后端会检查数据库中的默认 LLM provider；健康的 provider 会返回 mode: provider。

### GET /healthz

无需鉴权，返回：

~~~json
{
  "status": "ok",
  "checks": {
    "db": {"status": "ok"},
    "llm": {"status": "ok"},
    "sandbox_daemon": {"status": "ok", "detail": 200}
  }
}
~~~

子项状态包括：

- db：ok 或 error
- llm：ok、unhealthy、not_configured 或 error
- sandbox_daemon：ok、error 或 unreachable

所有子项为 ok 或 not_configured 时总状态为 ok，否则为 degraded。

### GET /readyz

无需鉴权。数据库可连接时返回 HTTP 200 和 {"status": "ok"}；数据库不可用时返回 HTTP 503 和 {"status": "not_ready"}。

## 6. 工作台数据接口

以下接口均需要 chat:read，返回裸 JSON；上传接口需要 chat:send。

### 6.1 GET /api/workbench/datasets

返回数据集数组，每项包含 key、title、group、filters、column_priority 和 row_count。

当前数据集：

| key | title | group | filter keys |
|---|---|---|---|
| raw_data | 零售统计 | input | category, channel, sku, period |
| master_data | 产品主数据 | input | category, sku, version, status |
| price_data | 计划价格 | input | category, sku, version, period |
| rebate_data | 渠道返利 | input | category, channel, product_line |
| dsi_data | DSI 价格 | input | category, channel, sku, period |
| cost_data | 商品成本 | input | category, sku |
| price_elasticity | 价格弹性表 | whatif | category, series, sku |
| fcst_detail | 预测明细 | output | category, channel, sku, period, series, version, status |

filters 每项格式为 {"key": "category", "label": "品类"}。

### 6.2 GET /api/workbench/filter-options/{dataset}

查询参数：

| 参数 | 类型 | 默认 |
|---|---|---|
| category | string | null |
| version | string | null |
| essential | boolean | false |

返回：

~~~json
{
  "dataset": "fcst_detail",
  "filters": [{"key": "category", "label": "品类"}],
  "filter_options": {
    "category": ["冰箱"],
    "version": ["AG_冰箱_2026-09-H3"]
  }
}
~~~

essential=true 只减少实际查询的 option 键；响应中的 filters 仍返回该数据集的完整定义。

### 6.3 GET /api/workbench/tables/{dataset}

查询参数全部可选：category、channel、channel_l1、sku、period、series、version、status、product_line、page、page_size。

默认 page=1、page_size=50，页大小限制为 1 到 200。成功响应：

~~~json
{
  "dataset": "raw_data",
  "title": "零售统计",
  "columns": [{"key": "period_id", "title": "period_id"}],
  "rows": [{"period_id": "2026-08", "retail_qty": 10}],
  "total": 1,
  "page": 1,
  "page_size": 50,
  "filters": [{"key": "category", "label": "品类"}]
}
~~~

columns 由固定优先列和当前行 payload 中出现的列组成；rows 是原始 payload 对象。

### 6.4 GET /api/workbench/charts/{dataset}

查询过滤参数与 tables 接口相同，但不接受 page、page_size。当前只支持 dataset=fcst_detail，成功返回：

~~~json
{
  "dataset": "fcst_detail",
  "months": ["2026-09", "2026-10"],
  "quantity": [100, 120],
  "amount": [50000, 60000]
}
~~~

数量来自 最终预测值/final_value，金额为数量乘以 计划价格；非 fcst_detail 返回 400 业务错误。

### 6.5 GET /api/workbench/knowledge/strategy

返回模型参考接口原样 JSON，当前预期包含策略知识内容，例如 title、source 和 markdown。上游不可用时返回 502 统一错误。

### 6.6 POST /api/workbench/upload/cost_data

权限：chat:send。请求为 multipart/form-data，必填文件字段 file。

只接受 .csv 或 .xlsx。成功返回裸 JSON：

~~~json
{
  "ok": true,
  "dataset": "cost_data",
  "upserted": 100,
  "skipped": 0,
  "updated_at": "model-source"
}
~~~

文件先提交到模型参考接口，再同步 PG 缓存；模型接受但 PG 同步失败时返回 502。

## 7. 预测接口

前缀 /api/forecast，返回裸 JSON。发送预测需要 chat:send，读取任务/健康/文件需要 chat:read。

### 7.1 POST /api/forecast/runs

请求 JSON：

| 字段 | 类型 | 必填 | 默认/约束 |
|---|---|---:|---|
| category | string | 是 | 非空 |
| forecast_month | string/null | 否 | 支持 YYYY-MM 或日期形式 |
| wait | boolean | 否 | true |
| channel | string/null | 否 | 过滤工作台结果 |
| sku | string/null | 否 | 过滤工作台结果 |
| start | string/null | 否 | 传给模型 |
| end | string/null | 否 | 传给模型 |
| horizon | integer/null | 否 | 默认 7，范围 1 到 7 |
| intent | string/null | 否 | 传给模型 |

额外字段会被忽略。成功返回：

~~~json
{
  "ok": true,
  "envelope": {
    "table": {
      "dataset": "fcst_detail",
      "rows": [],
      "total": 0
    },
    "version": "AG_冰箱_2026-09-H7",
    "relay": {
      "forecast_rows": 100,
      "attribution_rows": 100,
      "history_rows": 100
    }
  },
  "task": {},
  "reused": false
}
~~~

task 是模型任务元数据，具体字段由上游决定。wait=true 时模型完成后同步预测、归因和历史 relay 行；同步失败即返回 502。模型未启用或上游失败也返回 502。

### 7.2 GET /api/forecast/tasks/{task_id}

返回模型任务原样 JSON。上游不可用时返回 502。

### 7.3 GET /api/forecast/model/health

返回：

~~~json
{
  "ok": true,
  "forecast_model_enabled": true,
  "output_dir": "…",
  "upstream": {"ok": true, "response": {}}
}
~~~

上游失败时 upstream 为 {"ok": false, "error": "..."}，总 ok 为 false。

### 7.4 POST /api/forecast/extract

请求 JSON 字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| filename | string/null | output 目录下的 .xlsx 文件名 |
| system_forecast_number | string/null | 与 filename 二选一 |
| category | string/null | 可选筛选 |
| forecast_month | string/null | 可选筛选 |
| channel | string/null | 可选筛选 |
| sku | string/null | 可选筛选 |

必须且只能提供 filename 或 system_forecast_number 之一；文件名不允许目录分隔符。成功返回：

~~~json
{
  "ok": true,
  "filename": "output_....xlsx",
  "sheet_names": [],
  "forecast": {},
  "attribution": {}
}
~~~

forecast 和 attribution 的具体字段由 Excel 适配器按工作簿内容生成。

## 8. 归因接口

前缀 /api/attribution，全部需要 chat:read，返回裸 JSON。

### 8.1 GET /api/attribution/options

返回：

~~~json
{
  "category": ["冰箱"],
  "version": ["AG_冰箱_2026-09-H3"],
  "status": ["主销"]
}
~~~

### 8.2 GET /api/attribution/skus

必填查询参数：category、version。

可选参数：

| 参数 | 说明 |
|---|---|
| status | 精确状态过滤 |
| keyword | SKU 不区分大小写包含匹配 |
| period | 预测月份 |
| tag | 全部、新品、主销、淘汰、Top5、Top10 |
| limit | 默认 200，范围 1 到 200 |

成功返回：

~~~json
{
  "category": "冰箱",
  "version": "AG_冰箱_2026-09-H3",
  "period": "2026-09",
  "months": ["2026-09", "2026-10"],
  "items": [
    {
      "sku": "SKU001",
      "channel_l1": "",
      "channel_l3": "",
      "status": "主销",
      "series": "系列A",
      "y_pred": 100.0,
      "qty_lag1": 90.0,
      "period": "2026-09",
      "meta": "系列：系列A · 渠道：- / -"
    }
  ],
  "total": 1
}
~~~

### 8.3 GET /api/attribution/detail

必填查询参数：category、version、sku。可选 channel_l1、channel_l3、period。

找到数据时返回：

~~~json
{
  "ok": true,
  "sku": "SKU001",
  "channel_l1": "",
  "channel_l3": "",
  "status": "主销",
  "series": "系列A",
  "category": "冰箱",
  "version": "AG_冰箱_2026-09-H3",
  "period": "2026-09",
  "months": ["2026-09"],
  "meta": "品类：冰箱 · 系列：系列A · 状态：主销",
  "y_pred": 100.0,
  "qty_lag1": 90.0,
  "model": null,
  "method": null,
  "attribution_text": "…",
  "waterfall": {
    "xAxis": ["基础销量", "最终预测"],
    "placeholder": [0, 0],
    "values": [90, 100],
    "labels": ["90.0", "100.0"],
    "colors": ["#d9d9d9", "#003a8c"],
    "baseline": 90,
    "final": 100
  },
  "type_impacts": [{"type": "价格", "impact": 10.0}],
  "factors": [],
  "factor_details": []
}
~~~

没有匹配数据时仍是 HTTP 200，返回 {"ok": false, "error": "未找到该型号归因数据"}。

### 8.4 GET /api/attribution/trend

必填查询参数：category、version、sku；可选 channel_l1、channel_l3。

成功返回：

~~~json
{
  "periods": ["2026-08", "2026-09", "2026-10"],
  "history": [80, null, null],
  "forecast": [null, 100, 110],
  "history_count": 1,
  "forecast_count": 2,
  "horizons": ["N+1", "N+2"],
  "split_period": "2026-09",
  "forecast_curve": [
    {"period": "2026-09", "horizon": "N+1", "forecast_qty": 100, "qty": 100}
  ]
}
~~~

缺失的历史/预测值使用 null，不伪造为 0。

## 9. What-if 接口

前缀 /api/whatif。策略目录和基线读取需要 chat:read；模拟和优化提交需要 chat:send。除上游异常外均返回裸 JSON。

### 9.1 GET /api/whatif/strategies

可选查询参数 status。后端将模型服务 /whatif/strategies 的 JSON 对象原样返回，不在此层补字段。

### 9.2 GET /api/whatif/baseline

必填查询参数 category、version。可选 period、limit（默认 200，范围 1 到 200）。

成功返回：

~~~json
{
  "ok": true,
  "source": "db",
  "category": "冰箱",
  "version": "AG_冰箱_2026-09-H3",
  "period": null,
  "months": ["2026-09", "2026-10"],
  "items": [],
  "summary": {
    "baseline_qty": 1000,
    "baseline_amount": 500000,
    "gross_profit": null,
    "gross_margin": null,
    "price_coverage_qty": 1,
    "cost_coverage_qty": 0,
    "gross_coverage_qty": 0,
    "price_status": "complete",
    "cost_status": "missing",
    "gross_profit_status": "missing",
    "item_count": 1,
    "visible_item_count": 1,
    "detail_count": 2,
    "months": ["2026-09", "2026-10"],
    "qty_series": [500, 500],
    "amount_series": [250000, 250000],
    "inventory_turnover_days": null,
    "inventory_turnover_label": "45天（占位）",
    "inventory_turnover_status": "unavailable",
    "inventory_turnover_reason": "缺少未来期末/平均库存与 COGS 数据"
  },
  "total": 1,
  "elasticity_hits": 0
}
~~~

每个 items 项包含 SKU、渠道、基线销量、`baseline_price`、成本、基线金额、价格/成本覆盖率、弹性信息和 details；details 还包含月份、预测期、`plan_price`、`baseline_price`、价格来源和匹配状态。`plan_price` 是模型使用的计划输入价，`baseline_price` 是 What-if 实际采用的价格；模型不输出 `forecast_price`。库存周转天数当前固定为 null，不能当作实测指标。

`simulate`/`optimize` 的 `rows` 使用 `baseline_qty` 和 `baseline_price`；模型服务只按这两个基线字段执行规则式策略计算，不读取或推断价格计划。

### 9.3 POST /api/whatif/simulate

请求 JSON 只允许以下字段：

| 字段 | 类型 | 必填 | 约束 |
|---|---|---:|---|
| rows | object[] | 是 | 至少一行 |
| strategy_id | string | 是 | 策略标识 |
| param | string/null | 否 | 策略参数 |
| traffic_tier | string/null | 否 | 流量层级 |

成功只返回任务投影：

~~~json
{"task_id": "task-id", "status": "pending"}
~~~

### 9.4 POST /api/whatif/optimize

请求 JSON 只允许以下字段：

| 字段 | 类型 | 必填 | 约束 |
|---|---|---:|---|
| rows | object[] | 是 | 至少一行 |
| target_qty | number | 是 | 目标销量 |
| target_revenue | number/null | 否 | 不得小于 0 |
| param | string/null | 否 | 策略参数 |
| traffic_tier | string/null | 否 | 流量层级 |

成功同样只返回 {"task_id": "...", "status": "..."}。

### 9.5 GET /api/whatif/tasks/{task_id}

返回任务状态投影：

~~~json
{
  "status": "completed",
  "progress": "100%",
  "result": {},
  "error_message": null
}
~~~

上游 What-if 请求失败时为 HTTP 502 和裸 detail 错误体。

## 10. 管理接口

管理接口前缀为 /api/v1/admin。所有管理路由要求管理员身份，并同时检查下表中的权限点。成功 JSON 使用统一响应壳。

### 10.1 数据源：adm:tool.manage

#### GET /api/v1/admin/datasources

成功 data 为数组，单项：

~~~json
{
  "id": "uuid",
  "name": "sales-api",
  "type": "http_api",
  "base_url": "https://internal.example",
  "credential_encrypted": "***",
  "whitelist": ["10.0.0.0/8"],
  "enabled": true,
  "created_at": "2026-09-07T10:00:00+00:00"
}
~~~

#### POST /api/v1/admin/datasources

请求 JSON：

| 字段 | 类型 | 必填 | 默认 |
|---|---|---:|---|
| name | string | 是 | 最长 64 |
| type | string | 否 | http_api |
| base_url | string | 是 | — |
| credential | string | 否 | 空字符串 |
| whitelist | string[] | 否 | [] |
| enabled | boolean | 否 | true |

成功 data：{"id": "uuid", "name": "sales-api"}。credential 加密保存，白名单必须属于允许出网集合。

#### PATCH /api/v1/admin/datasources/{ds_id}

请求字段均可选：name、base_url、credential、whitelist、enabled。

成功 data：{"id": "uuid"}。当前只有 name、base_url 和 enabled 会落库；credential、whitelist 会被静默忽略。

#### POST /api/v1/admin/datasources/{ds_id}/test

成功 data：

~~~json
{"ok": true, "detail": "连接成功"}
~~~

失败仍为成功 HTTP 响应，但 ok=false，例如 detail: "连接失败: 超时(>5s)"。

### 10.2 工具：adm:tool.manage

#### GET /api/v1/admin/tools

成功 data 为工具数组，单项包含：

~~~json
{
  "id": "uuid",
  "name": "tool_name",
  "description": "…",
  "status": "enabled",
  "input_schema": {},
  "output_schema": {},
  "execution": {},
  "scenario_id": "uuid",
  "created_at": "2026-09-07T10:00:00+00:00",
  "updated_at": "2026-09-07T10:00:00+00:00"
}
~~~

#### POST /api/v1/admin/tools

请求 JSON：

| 字段 | 类型 | 必填 | 约束 |
|---|---|---:|---|
| name | string | 是 | [a-z][a-z0-9_]{1,63} |
| description | string | 否 | 默认空字符串 |
| input_schema | object | 是 | JSON Schema，type 必须 object，必须有 properties，additionalProperties 必须 false |
| output_schema | object | 否 | 默认 {} |
| execution | object | 是 | kind 为 sandbox 或 internal |
| scenario_id | string/null | 否 | — |

sandbox execution 需要 image、handler、正整数 timeout_s/非负 warm_pool；internal execution 需要 handler 和正整数 timeout_s，不允许 env_from_datasource。成功 data：{"id": "uuid", "name": "tool_name"}。

#### PATCH /api/v1/admin/tools/{tool_id}

请求字段可选：status（enabled/disabled）、description、execution。execution 与已有值局部合并。成功 data：{"id": "uuid", "status": "enabled"}。

#### DELETE /api/v1/admin/tools/{tool_id}

成功 data：{"ok": true}。有执行记录引用，或工具仍为 enabled 时返回 409。

#### POST /api/v1/admin/tools/{tool_id}/test

成功 data 是数据源别名到测试结果的映射：

~~~json
{
  "sales-api": {"ok": true, "detail": "连接成功"},
  "missing-api": {"ok": false, "detail": "数据源未注册"}
}
~~~

### 10.3 场景：adm:tool.manage

#### GET /api/v1/admin/scenarios

成功 data 为数组，每项：

~~~json
{
  "id": "uuid",
  "code": "sales_query_predict",
  "name": "销售查询预测",
  "model_ref": {"provider_id": "uuid", "model": "model-name"},
  "system_prompt": "…",
  "enabled": true
}
~~~

#### PATCH /api/v1/admin/scenarios/{scenario_id}

请求字段均可选：name、system_prompt、enabled、model_ref。model_ref 提供时，model 必须非空；provider_id 若提供必须存在。成功 data：{"id": "uuid", "code": "sales_query_predict"}。

### 10.4 LLM provider：adm:llm.manage

#### GET /api/v1/admin/llm

成功 data 为数组，单项：

~~~json
{
  "id": "uuid",
  "name": "provider",
  "vendor": "openai_compat",
  "base_url": "https://llm.example",
  "api_key_encrypted": "***",
  "models": ["model-name"],
  "default_model": "model-name",
  "status": "healthy",
  "fallback_provider_id": null,
  "healthy_updated_at": "2026-09-07T10:00:00+00:00"
}
~~~

#### POST /api/v1/admin/llm

请求 JSON：name、base_url 必填；vendor 默认 openai_compat；api_key 默认空；models 默认 []；default_model 默认空；fallback_provider_id 可空。成功 data：{"id": "uuid", "name": "provider"}。第一个 provider 自动成为默认 provider。

#### PATCH /api/v1/admin/llm/{provider_id}

可选字段：name、base_url、api_key、models、default_model、fallback_provider_id。成功 data：{"id": "uuid"}。

#### DELETE /api/v1/admin/llm/{provider_id}

成功 data：{"ok": true}。仍被场景引用时返回 409。

#### POST /api/v1/admin/llm/{provider_id}/health

成功 data：

~~~json
{"id": "uuid", "status": "healthy", "healthy": true}
~~~

该操作会更新 provider 状态和健康检查时间。

#### GET /api/v1/admin/llm/default

成功 data 为脱敏 provider 对象，未配置默认 provider 时为 null。

### 10.5 管理查询与审计：audit:read

下列列表查询和会话流会写一条 audit.view 审计记录；查询本身不修改业务数据。追溯详情和审计详情当前只读数据库，不额外写 audit.view。

#### GET /api/v1/admin/conversations/{cid}/stream

返回管理员会话级 SSE。会话只需存在且未删除，不校验 owner；建立连接会写 audit.view。

#### GET /api/v1/admin/sessions

查询参数：q、status、owner_email、cursor、limit。limit 默认 20，最多 100。

成功 data：

~~~json
{
  "items": [
    {
      "id": "uuid",
      "owner_id": "uuid",
      "title": "销售分析",
      "status": "active",
      "updated_at": "2026-09-07T10:00:00+00:00"
    }
  ],
  "next_cursor": null
}
~~~

当前 q、status、owner_email 和 cursor 接收但不参与过滤；只排除 deleted 会话。

#### GET /api/v1/admin/messages

查询参数：q、status、owner_email、cursor、limit。只有 owner_email 生效，且为 owner email 精确匹配；其余筛选参数当前不生效。

成功 data.items[]：

~~~json
{
  "id": "uuid",
  "conversation_id": "uuid",
  "role": "assistant",
  "content": "最多截取 500 个字符",
  "status": "completed",
  "trace_id": "uuid",
  "created_at": "2026-09-07T10:00:00+00:00"
}
~~~

同时返回 next_cursor。

#### GET /api/v1/admin/traces

可选查询参数：trace_id、tool_name、error_code、actor_email。默认最多 20 条，无 cursor。

成功 data：

~~~json
{
  "items": [
    {
      "trace_id": "uuid",
      "message_id": "uuid",
      "seq": 1,
      "type": "tool_result",
      "payload": {},
      "created_at": "2026-09-07T10:00:00+00:00"
    }
  ]
}
~~~

trace_id、tool_name、error_code 和 actor_email 均按当前查询实现过滤；错误码按大写比较，传 ANY 时不按错误码过滤。

#### GET /api/v1/admin/traces/{trace_id}

成功 data：

~~~json
{
  "trace_id": "uuid",
  "events": [
    {
      "seq": 1,
      "type": "done",
      "payload": {},
      "created_at": "2026-09-07T10:00:00+00:00"
    }
  ]
}
~~~

无事件返回 404。

#### GET /api/v1/admin/audits

查询参数：type、actor、target、cursor、limit。type 精确匹配 action；actor 对 actor email 做包含匹配；target 和 cursor 当前不生效。

成功 data.items[]：

~~~json
{
  "id": "uuid",
  "actor_id": "uuid",
  "actor_email": "user@corp.com",
  "action": "audit.view",
  "target_type": "session",
  "target_id": "uuid",
  "ip": "10.0.0.1",
  "detail": {},
  "created_at": "2026-09-07T10:00:00+00:00"
}
~~~

当前不返回 next_cursor；cursor 参数也不参与查询。

#### GET /api/v1/admin/audits/{audit_id}

成功 data 为单条审计对象，字段与列表项相同；记录不存在返回 404。

#### POST /api/v1/admin/audits/export

当前为不可用占位，不生成文件：

~~~json
{
  "code": "501_NOT_IMPLEMENTED",
  "message": "ok",
  "data": {"message": "审计导出为 P1 功能，本期未提供"}
}
~~~

HTTP 状态仍为 200。

### 10.6 用户：adm:user.manage

#### GET /api/v1/admin/users

查询参数：q、role、status、cursor、limit。q 对 email/nickname 做包含匹配，status 精确过滤；role 和 cursor 当前不生效。成功 data：

~~~json
{
  "items": [
    {
      "id": "uuid",
      "email": "user@corp.com",
      "nickname": "用户",
      "status": "active",
      "roles": ["user"],
      "created_at": "2026-09-07T10:00:00+00:00"
    }
  ]
}
~~~

当前不返回 next_cursor。

#### POST /api/v1/admin/users

请求 JSON：

| 字段 | 类型 | 必填 | 默认/约束 |
|---|---|---:|---|
| email | string | 是 | 最长 255 |
| nickname | string/null | 否 | 默认空字符串 |
| initial_password | string | 是 | 10 到 128；另需满足大小写数字政策 |
| role | string | 否 | user；只支持 user/admin |

成功 data：{"id": "uuid", "email": "user@corp.com"}。密码不会出现在响应或审计详情中。

#### PATCH /api/v1/admin/users/{user_id}

请求字段均可选：nickname、role、status。成功 data：{"id": "uuid"}。不能禁用自身，也不能移除最后一名管理员。

#### POST /api/v1/admin/users/{user_id}/reset-password

请求 JSON：{"new_password": "NewPass1234"}；必填，长度 10 到 128 且遵循口令策略。成功 data：{"ok": true}。

### 10.7 系统参数：adm:config.manage

#### GET /api/v1/admin/config

成功 data 是键值映射，当前允许的键及默认值：

~~~json
{
  "retention.conversation_days": 180,
  "retention.audit_days": 365,
  "auth.email_whitelist_suffixes": ["@corp.com"],
  "auth.login_fail_limit": 5,
  "sandbox.max_concurrent": 3,
  "sandbox.timeout_s": 30,
  "llm.default_provider_id": null,
  "llm.default_model": "",
  "conversation.user_max_messages": 48
}
~~~

#### PATCH /api/v1/admin/config

请求 JSON：

~~~json
{"key": "llm.default_model", "value": "model-name"}
~~~

key 和 value 必填，key 必须属于上述 9 个键。成功 data：{"key": "...", "value": ...}，修改立即失效缓存并写审计。

## 11. SSE 协议

通用帧格式：

~~~text
id: <seq>
event: <event-name>
data: {"...": "..."}

~~~

id 只在有追溯序号时出现；空闲期间发送 : ping，原生消息流和会话流的心跳间隔为 5 秒。

### 11.1 原生消息流

#### GET /api/v1/chat/conversations/{cid}/messages/{mid}/stream

连接：

    GET /api/v1/chat/conversations/{cid}/messages/{mid}/stream

需要 chat:read 和 owner 校验。响应头包含 Cache-Control: no-store、X-Accel-Buffering: no。当前可能收到：

| event | data |
|---|---|
| message.delta | {"text": "增量文本"} |
| agent.process | {"state": "planning", "detail": "可选"} |
| agent.status | {"state": "planning"} |
| tool.call | {"name": "...", "input": {}, "plan_index": 0, "request_id": "uuid"} |
| tool.result | {"name": "...", "output_summary": {}, "duration_ms": 100, "status": "ok"} |
| tool.error | {"name": "...", "error_code": "...", "message": "...", "retried": 0} |
| done | {"message_id": "uuid", "final_text": "…", "status": "completed"} |
| error | {"code": "500_INTERNAL", "message": "执行失败"} |
| follow_up.suggestions | {"message_id": "uuid", "suggestions": [{"id": "1", "text": "…"}]} |

done 可能附带 usage: {prompt_tokens, completion_tokens}。internal 工具的 tool.result.output_summary 可携带完整结构化结果；容器工具通常只携带摘要，完整结果在追溯事件中。

当前引擎不会在该消息级流中主动发布 message.created；连接建立会写入内部 sse_opened 事件但不向客户端发送。

### 11.2 会话级实时/回放流

#### GET /api/v1/chat/conversations/{cid}/stream

用户连接：

    GET /api/v1/chat/conversations/{cid}/stream

需要 chat:read 和 owner 校验。

#### GET /api/v1/admin/conversations/{cid}/stream

管理员连接：

    GET /api/v1/admin/conversations/{cid}/stream

需要 audit:read，只要求会话存在且未删除，连接会写 audit.view。

两者都先回放最近最多 200 条可见事件，再发送 session.meta，随后订阅实时事件。

session.pack：

~~~json
{
  "event_type": "tool.result",
  "payload": {},
  "seq": 3,
  "turn_index": 1,
  "ts": "2026-09-07T10:00:00+00:00"
}
~~~

session.meta：

~~~json
{
  "conversation_id": "uuid",
  "event_total": 12,
  "token_total": 300
}
~~~

回放会把持久化 message_created 映射为 message.created，并排除 sse_opened；实时事件统一包装为 session.pack。token_total 只累计 done 事件中 usage 的 prompt/completion token。

### 11.3 工作台 façade 流

连接：

    POST /api/chat/stream

该流使用 delta、status、result、done 四种 façade 事件，协议见 4.2，不与原生消息级流混用。

## 12. 当前 Agent 内部工具

当前 seed 注册并可被默认场景调用的工具只有以下 8 个。它们在后端进程内执行，execution.kind 为 internal，不经过 sandbox daemon，也不把凭据写入工具结果。

工具错误/缺参的通用形态：

~~~json
{
  "response_type": "need_input",
  "status": "need_input",
  "missing": ["category"],
  "need_input": ["category"]
}
~~~

执行失败通常为：

~~~json
{"response_type": "tool_error", "status": "failed", "error": "…"}
~~~

### 12.1 get_history

用途：只回答历史/过去/实际销量。

输入 schema：

| 字段 | 类型 | 必填 |
|---|---|---:|
| category | string | 是 |
| sku | string | 否 |
| channel | string | 否 |
| start | string | 否 |
| end | string | 否 |

成功输出为 response_type: history，包含 category、requested_range、available_range、summary、metrics、series、rows、top_skus、sku_trends 和 envelope。series/rows 的行格式为 {"period": "YYYY-MM", "qty": number}。

### 12.2 submit_forecast

用途：发起未来预测。

输入 schema：

| 字段 | 类型 | 必填 | 默认/约束 |
|---|---|---:|---|
| category | string | 是 | 非空 |
| forecast_month | string | 否 | Agent 引擎缺省时使用下一个自然月；独立调用缺省会要求补充 |
| horizon | integer | 否 | 默认 3，范围 1 到 12 |

成功输出为 response_type: forecast，包含：

- system_forecast_number
- category、horizon、period
- forecast、rows、forecast_points
- monthly_forecast、monthly_totals
- forecast_qty、category_total
- top_skus
- task_id、task、reused、relay
- envelope

预测点至少包含 source_tool、system_forecast_number、category、horizon、period、sku、forecast_qty 和兼容别名 qty。

### 12.3 get_task_status

输入：必填 task_id: string。

输出：

~~~json
{
  "response_type": "task_status",
  "status": "pending",
  "task_id": "task-id",
  "envelope": {}
}
~~~

### 12.4 get_forecast_result

输入 schema：必填 system_forecast_number: string；可选 horizon，默认 3，范围 1 到 12。

输出与 submit_forecast 的预测投影相同，但 source_tool 为 get_forecast_result，包括结构化预测点、月度汇总、总量和按 forecast_qty 排序的 top_skus。

### 12.5 get_attribution

输入 schema：

| 字段 | 类型 | 必填 |
|---|---|---:|
| system_forecast_number | string | 是 |
| category | string | 是 |
| sku | string | 是 |
| period | string | 否 |

输出为 response_type: attribution，包含 system_forecast_number、category、horizon、period、sku、y_pred、qty_lag1、waterfall、type_impacts、factors、factor_details、trend、forecast_curve、rows 和 envelope。

### 12.6 get_whatif_strategies

输入：可选 status: string。

输出只保留可用于后续选择的策略字段：

~~~json
{
  "response_type": "whatif_strategies",
  "source_tool": "get_whatif_strategies",
  "strategies": [
    {
      "id": "strategy-id",
      "name": "策略名",
      "status": "active",
      "param_kind": "percentage",
      "default_param": "5%"
    }
  ],
  "rows": [],
  "envelope": {"strategies": []}
}
~~~

禁用、无 id 或无 name 的目录项不会输出。

### 12.7 simulate

输入 schema 必填 system_forecast_number、category。可选 strategy_id、strategy_name、param、traffic_tier、sku、series、status、filters。

缺少或无法唯一匹配策略时返回 need_input(strategy_id) 和候选策略；策略目录校验通过后，成功输出：

~~~json
{
  "response_type": "simulation",
  "source_tool": "simulate",
  "task_id": "task-id",
  "system_forecast_number": "…",
  "category": "冰箱",
  "meta": {
    "strategy_id": "strategy-id",
    "strategy_name": "策略名",
    "param": "5%",
    "traffic_tier": null,
    "filters": {},
    "matched_rows": 10,
    "unmatched_rows": 0,
    "directory_validated": true
  },
  "envelope": {}
}
~~~

### 12.8 optimize

输入 schema 必填 system_forecast_number、category；可选 target_qty、target_revenue、param、traffic_tier。`target_qty` 单位为台，`target_revenue` 单位为元。当用户没有提供目标时，工具使用工作台默认目标销量 `80000` 台、默认目标销售额 `50000000` 元；如果 baseline 价格覆盖不足，销售额目标保持缺失并在 assumptions 中说明。用户语义目标优先于默认值，例如“4 万台、500 万元”规范化为 `40000`、`5000000`。

成功输出为 response_type: optimization，包含 source_tool、task_id、system_forecast_number、category、meta 和 envelope。工具先基于完整 What-if baseline 计算目标与 baseline 差距，再提交有限策略优化；`meta` 包含 `assumptions`、`target_source`、`target_qty`、`target_revenue`、`goal_vs_baseline`、`baseline_summary` 和 `baseline_source`。

聊天 façade 会复用工作台投影生成：

~~~json
{
  "response_type": "optimization",
  "chart": {
    "type": "strategy_dashboard",
    "cards": [
      {"type": "strategy_matrix", "data": {}},
      {"type": "attainment_trend", "data": {
        "baseline": {"qty": [], "amount": []},
        "target": {"qty": [], "amount": []},
        "simulated": {"qty": [], "amount": []}
      }}
    ]
  },
  "text": {"metrics": {
    "baseline_to_target_qty_gap": 0,
    "simulated_to_target_qty_gap": 0
  }},
  "table": {"rows": []}
}
~~~

`target - baseline` 为正表示 baseline 尚差目标，`target - simulated` 为正表示模拟后仍未达标；缺失金额不转换为 0。

## 13. 当前实现限制

以下行为是当前代码的真实行为，联调时应按此处理：

1. 原生会话和消息列表接收 cursor，但当前查询未使用它；admin sessions 的 q/status/owner_email/cursor、admin messages 的 q/status/cursor、admin audits 的 target/cursor 和 admin users 的 role/cursor 也未生效。
2. /api/sessions 固定取最多 100 条，不返回分页游标。
3. /api/chat 与 /api/chat/stream 接收 params，当前 chat bridge 不读取它。
4. /api/agent/probe 接收 url/headers/body，当前只返回本地配置状态，不执行探测请求。
5. 邮箱登录和 refresh 的返回体没有 token_type；OA 登录才返回 token_type。
6. 数据源创建请求中的 enabled=false 不会生效，服务层始终按 enabled 创建。
7. 数据源 PATCH 接受 credential 和 whitelist，但当前静默忽略。
8. /api/workbench/filter-options/{dataset}?essential=true 只减少 option 查询键，响应的完整 filters 定义不减少。
9. /api/whatif/baseline 的 inventory_turnover_days 是 null 占位，不是库存实测值。
10. /api/v1/admin/audits/export 不返回文件，仅返回 501_NOT_IMPLEMENTED 占位响应。
11. What-if 上游失败是 HTTP 502 的裸 detail，不使用统一响应壳。
12. 预测 run 的 wait=true 才执行 relay 同步；wait=false 返回的工作台 table 可能为空，调用方应继续查询任务和工作台数据。
13. 当前没有实际限流中间件触发 429_RATE_LIMIT；该错误码只保留给登录锁定等领域逻辑。
