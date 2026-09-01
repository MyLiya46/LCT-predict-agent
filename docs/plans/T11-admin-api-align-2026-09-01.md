# T11 · 管理端 API 对齐验证（admin-api-align）

- **任务 ID**：T11
- **标题与目标**：复用 backup 壳现有 `/api/v1/admin` 路由和 RBAC，完成 7 个管理模块、10 个权限点、seed 幂等性和越权审计的可运行验证，为 T13 管理端六页前端固定 API 契约。
- **关联文档章节**：`docs/feat-icewash.md` §10.2；backup `src/app/main.py`、`src/app/api/admin/*`、`seed/v1__base_seed.py`、`tests/test_rbac.py`、`tests/test_seed.py`；T03、T07、T13
- **前置依赖 blockedBy**：T03

## 实施要点

### 1. 固定管理端路由与响应边界

- 保留 backup `main.py` 对 7 个管理模块的挂载：`datasources`、`tools`、`scenarios`、`llm`、`audits`、`users`、`config`，统一前缀固定为 `/api/v1/admin`；不把管理端路由复制到 `/api`，不引入 backend-ref 管理路由。
- 固定 P0 管理路由清单：
  - users：`GET/POST /users`、`PATCH /users/{user_id}`、`POST /users/{user_id}/reset-password`；
  - tools：`GET/POST /tools`、`PATCH/DELETE /tools/{tool_id}`、`POST /tools/{tool_id}/test`；
  - datasources：`GET/POST /datasources`、`PATCH /datasources/{ds_id}`、`POST /datasources/{ds_id}/test`；
  - scenarios：`GET /scenarios`、`PATCH /scenarios/{scenario_id}`；
  - llm：`GET/POST /llm`、`PATCH/DELETE /llm/{provider_id}`、`POST /llm/{provider_id}/health`、`GET /llm/default`；
  - audits：`GET /sessions`、`GET /messages`、`GET /traces`、`GET /traces/{trace_id}`、`GET /audits`、`GET /audits/{audit_id}`、`GET /conversations/{cid}/stream`；
  - config：`GET/PATCH /config`。
- 以上接口继续返回 backup 统一响应 `{code,message,data}`；`GET /users`、`GET /audits`、`GET /messages`、`GET /traces` 的分页内容放在 `data.items`，`GET /config` 的 `data` 固定包含 9 个 system_config 键。`POST /audits/export` 仍属于 P1，不纳入 T11 的管理页契约。
- T13 只消费 users/tools/datasources/llm/audits/config 六组页面接口；scenarios 保留为 engine 场景管理 API，不为 T13 额外创建页面。

### 2. 运行并验证 v1 seed

- 在 `backend/` 目录执行 `uv run python -m seed.v1__base_seed`；seed 使用固定 PG advisory lock `99102026`，重复执行不产生重复角色、权限、绑定、场景或配置行。
- seed 必须存在角色 `user`、`admin`；必须存在以下 10 个权限点：`chat:read`、`chat:send`、`chat:stop`、`chat:delete`、`trace:read`、`adm:user.manage`、`adm:tool.manage`、`adm:llm.manage`、`adm:config.manage`、`audit:read`。
- `user` 角色固定绑定前 5 个聊天/追溯权限，`admin` 角色固定绑定全部 10 个权限；默认场景固定为 `sales_query_predict` 且 `enabled=true`。
- `system_config` 固定写入 9 个键和值：`retention.conversation_days=180`、`retention.audit_days=365`、`auth.email_whitelist_suffixes=["@corp.com"]`、`auth.login_fail_limit=5`、`sandbox.max_concurrent=3`、`sandbox.timeout_s=30`、`llm.default_provider_id=null`、`llm.default_model=""`、`conversation.user_max_messages=48`。已有值不被 v1 seed 覆盖。
- 管理员初始化沿用 `ADMIN_INITIAL_EMAIL` 与 `ADMIN_INITIAL_PASSWORD`；两个配置为空时只创建 disabled 状态的 `admin.disabled@corp.com`，不得使用该账号做成功登录验收。

### 3. 固定 RBAC 与越权审计行为

- `/api/v1/admin/**` 先由 `AdminPrefixMiddleware` 检查 backup access JWT：无 token 或 token 类型不是 `access` 返回 HTTP 401；token 合法但角色/权限不含 admin 或 `adm:*` 返回 HTTP 403，响应 code 固定为 `403_FORBIDDEN`。
- 管理路由继续保留各自的 `require_perm`：users 使用 `adm:user.manage`，tools/datasources/scenarios 使用 `adm:tool.manage`，llm 使用 `adm:llm.manage`，config 使用 `adm:config.manage`，audits 使用 `audit:read`。
- 每次 middleware 级越权只写一条 `audit_logs.action='authz.denied'`，detail 固定包含 `reason='permission_denied'`、path、method 和 `perm='adm:*'`；T11 测试不得把 middleware 403 与路由级 403 叠加计算为两条。
- 管理员访问任一 P0 管理模块返回 HTTP 200；普通 user 访问 `/api/v1/admin/users`、`/api/v1/admin/config` 和 `/api/v1/admin/audits` 均返回 HTTP 403，且不读取或修改管理数据。

### 4. 测试文件与测试数据

- 保留并运行 backup `backend/tests/test_rbac.py`、`backend/tests/test_seed.py`；不修改其测试语义，不引入 SQLite/aiosqlite。
- 新增 `backend/tests/test_admin_api.py`，使用 PG 测试 fixture 和 `create_token(..., token_type="access")` 创建 admin/user 两个测试身份，覆盖 7 个模块的路由注册、统一响应结构、admin 200、user 403、未认证 401 和 `audit_logs` 单条越权留痕。
- `test_admin_api.py` 对每个模块至少调用一个只读接口：`/users`、`/tools`、`/datasources`、`/scenarios`、`/llm`、`/audits`、`/config`；对 users/tools/datasources/llm/config 各调用一个写接口的 schema 校验，写入使用事务回滚 fixture，不改变后续测试数据。
- 新增断言验证 T03 合并后的 PG 模型仍能被 admin 路由导入；测试只从 `app.models` 导入壳模型，不从 `reference_repo/predict-agent/backend-backup` 或 `backend-ref` import。

### 5. 管理端联调命令

- 本任务只验证 backup 管理 API，不实现 T13 React 页面；T13 依赖本计划列出的路径、权限和 `{code,message,data}` 结构。
- 真实联调使用已配置的 email admin 通过 `/api/v1/auth/login` 获取 backup JWT；OA 自动创建的 `user` 角色 token 不得作为管理端 token。
- 管理 API 仍使用 backup JWT 的 `Authorization: Bearer`，不接受 OAuth `oauth_access_token` 作为管理端认证，也不把 OAuth token 写入管理审计。

## 验收标准

- [ ] `cd backend && uv run pytest tests/test_rbac.py tests/test_seed.py tests/test_admin_api.py` 全绿；PG 中角色数量为 2、权限数量为 10、user/admin role_permission 数量分别为 5/10，v1 seed 连续执行两次无重复行。
- [ ] `cd backend && uv run python -m seed.v1__base_seed` 连续执行两次成功；`psql agent_platform -c "SELECT key,value FROM system_config ORDER BY key"` 返回固定 9 个键，`sales_query_predict` 场景存在且 enabled=true。
- [ ] Git Bash 中设置 `ADMIN_TOKEN` 后执行 `curl -sS -H "Authorization: Bearer $ADMIN_TOKEN" http://127.0.0.1:8000/api/v1/admin/users`，HTTP 200 且 body 含 `code`、`message`、`data.items`；对 `/tools`、`/datasources`、`/scenarios`、`/llm`、`/audits`、`/config` 各执行一次 GET，均返回 HTTP 200。
- [ ] Git Bash 中设置普通 user 的 `USER_TOKEN` 后执行 `curl -sS -o /tmp/admin-denied.json -w "%{http_code}" -H "Authorization: Bearer $USER_TOKEN" http://127.0.0.1:8000/api/v1/admin/users`，HTTP 状态为 403，`/tmp/admin-denied.json` 的 `code` 为 `403_FORBIDDEN`；`psql agent_platform -c "SELECT count(*) FROM audit_logs WHERE action='authz.denied'"` 比请求前增加 1。
- [ ] Git Bash 中不带 Authorization 请求 `/api/v1/admin/users` 返回 HTTP 401；携带 OAuth `oauth_access_token` 而不携带 backup JWT 仍返回 HTTP 401。
- [ ] `grep -RInE "aiosqlite|PRAGMA|sqlite" backend/src/app/api/admin backend/tests/test_admin_api.py` 无命中；`grep -RIn "reference_repo/predict-agent" backend/src backend/tests` 无命中。
