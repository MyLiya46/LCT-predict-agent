# T13 · 管理端六页 React 新建（admin-pages-react）

- **任务 ID**：T13
- **标题与目标**：在 frontend-ref 上新建管理端六页和管理员路由守卫，消费 T11 固定的 backup `/api/v1/admin/*` 契约；不复制 backend-ref 管理逻辑，不把管理员 token 或敏感配置写入 localStorage。
- **关联文档章节**：`docs/feat-icewash.md` §10.1 增量 2、§3.11.4；T11；frontend-ref `src/App.tsx`、`src/api.ts`、`src/authStore.ts`
- **前置依赖 blockedBy**：T02、T11、T12

## 实施要点

### 1. 管理端请求封装

- 在 `frontend/src/api.ts` 新增 `adminJson<T>(url, init)`：复用 T12 的 backup JWT Authorization 注入和 `{code,message,data}` 解包；HTTP 401 清理/跳转由认证层处理，HTTP 403 将后端 `message` 原样转为页面错误提示。
- 新增类型与函数，路径和返回值严格对齐 T11：
  - users：`adminListUsers(q, role, status, limit=100)` → `data.items`；`adminCreateUser(email,nickname,initial_password,role)`；`adminPatchUser(id,{nickname?,role?,status?})`；`adminResetPassword(id,new_password)`；
  - tools：`adminListTools()` → `data` 数组；`adminCreateTool({name,description,input_schema,output_schema,execution,scenario_id?})`；`adminPatchTool(id,{status?,description?,execution?})`；`adminDeleteTool(id)`；`adminTestTool(id)`；
  - datasources：`adminListDatasources()` → `data` 数组；`adminCreateDatasource({name,type="http_api",base_url,credential,whitelist,enabled=true})`；`adminPatchDatasource(id,{name?,base_url?,enabled?})`；`adminTestDatasource(id)`；
  - llm：`adminListLlm()`、`adminCreateLlm({name,vendor="openai_compat",base_url,api_key,models,default_model,fallback_provider_id?})`、`adminPatchLlm(id,{name?,base_url?,api_key?,models?,default_model?,fallback_provider_id?})`、`adminDeleteLlm(id)`、`adminHealthLlm(id)`、`adminDefaultLlm()`；
  - audits：`adminListSessions(filters)`、`adminListMessages(filters)`、`adminListTraces(filters)`、`adminTraceDetail(trace_id)`、`adminListAudits(filters)`、`adminAuditDetail(id)`；读取 `data.items/events`；
  - config：`adminGetConfig()` 返回 9 个键值对象；`adminPatchConfig(key,value)` 请求 `{key,value}`。
- `adminJson()` 的 POST/PATCH body 使用 `JSON.stringify`，Content-Type 固定为 `application/json`；不在 `api.ts` 或 React state 中记录 `api_key`、datasource `credential`、用户密码、refresh token 或 OAuth token。
- `api.ts` 保留 T11 的 `/api/v1/admin/scenarios` 访问能力为 `adminListScenarios/adminPatchScenario`，但 T13 不创建 scenarios 页面；engine 场景由 seed/T11 和后续管理 API 使用。

### 2. 管理员路由守卫与布局

- 新建 `frontend/src/components/RequireAdmin.tsx`：先检查 T12 `isAuthenticated()`；已 hydration 但未登录时导航到 `/login`；已登录时请求 `GET /api/v1/auth/me`，从 `data.roles` 和 `data.perms` 判断 `roles.includes("admin") || perms.some(p => p.startsWith("adm:"))`；不满足时导航到 `/workbench/input`，不渲染管理页面。
- `RequireAdmin` 固定有 `checking` 状态，检查期间显示“管理员权限校验中…”；请求失败、HTTP 401 或 HTTP 403 统一清理页面级错误并导航到 `/workbench/input`，不通过前端状态绕过后端 RBAC。
- 新建 `frontend/src/components/AdminLayout.tsx`：使用现有 Tailwind token 和 `@phosphor-icons/react`，左侧固定六个入口 `/admin/users`、`/admin/tools`、`/admin/datasources`、`/admin/llm`、`/admin/audits`、`/admin/config`；`/admin` 重定向到 `/admin/users`；顶部显示当前 email 或 OA 和退出按钮，退出调用 T12 `logout()`。
- 修改 `frontend/src/App.tsx` 增加顶层路由：`<Route path="/admin/*" element={<RequireAdmin><AdminLayout /></RequireAdmin>}>`，六个子路由分别渲染六页；不把管理页嵌入工作台 `AppShell` 的普通导航。

### 3. 六个页面的可执行功能

- 新建 `frontend/src/pages/admin/UsersPage.tsx`：加载 `adminListUsers`；提供 email/nickname/role/initial_password 创建表单（password 最少 10 字符）、按 q/status 筛选；每行提供角色切换、active/disabled 切换和重置密码，调用对应 PATCH/POST 后重新加载列表；禁止对当前登录用户发送禁用请求，后端冲突信息直接展示。
- 新建 `frontend/src/pages/admin/ToolsPage.tsx`：渲染工具 name/status/description/execution；创建表单要求 name 匹配 `^[a-z][a-z0-9_]{1,63}$`，`input_schema`、`output_schema`、`execution` 使用 JSON 文本框并在提交前执行 `JSON.parse`；提供 enabled/disabled、测试、删除按钮，测试结果展示 `ok/detail`，不展示或持久化密钥。
- 新建 `frontend/src/pages/admin/DatasourcesPage.tsx`：渲染 name/type/base_url/enabled；创建表单固定 type 默认 `http_api`、base_url、credential、whitelist JSON/文本输入和 enabled；credential 只在 HTTPS 请求体中发送，页面 state 清空后不回填，前端不执行 AES；提供启停和连通测试，测试返回值只展示成功/失败与 detail。
- 新建 `frontend/src/pages/admin/LlmPage.tsx`：渲染 provider name/vendor/base_url/models/default_model/status；新增/编辑表单允许输入 api_key 但只显示 password 控件，提交后清空；列表只展示 backend 返回的 `api_key_encrypted="***"`；提供 health、删除和 default provider 查看，删除失败信息直接展示。
- 新建 `frontend/src/pages/admin/AuditsPage.tsx`：使用四个 tab `sessions/messages/traces/audits`；会话和消息支持 q/status/owner_email/limit，traces 支持 trace_id/tool_name/error_code/actor_email，audits 支持 type/actor/target；trace detail 展示 `seq/type/payload/created_at`，audit detail 展示 `actor/action/target/detail/created_at`，payload/detail 用 JSON 折叠显示，不渲染 token 或 credential 字段。
- 新建 `frontend/src/pages/admin/ConfigPage.tsx`：加载 9 个 system_config 键值；仅允许编辑 T11 后端白名单中的键，`sandbox.max_concurrent` 使用整数输入且限制 1~32，`sandbox.timeout_s` 使用整数输入且限制 1~300，其他键使用 JSON 文本框；提交调用 `adminPatchConfig` 后重新读取并显示成功状态。

### 4. 统一交互、错误和敏感字段边界

- 每页使用 `loading/error/saving` 状态；首次加载显示 skeleton/“加载中…”，请求失败显示 `message`，写操作期间禁用对应按钮，成功后重新请求当前列表。
- 所有页面使用可复用的 `AdminTable`、`AdminDialog`、`JsonViewer` 小组件；这些组件只存当前表单值，不写 localStorage，不把 password/api_key/credential 放入 URL、console 或错误上报。
- `AdminLayout` 只能由 RequireAdmin 渲染；后端仍以 `/api/v1/admin/**` middleware 和每个 router 的 `require_perm` 为最终权限边界，前端隐藏按钮不视为授权。

### 5. 构建与浏览器验收

- 在 `frontend/` 执行 `npm run build`，确认六页、路由守卫、admin API 类型和现有工作台页面无 TypeScript/Vite 回归。
- 使用 admin backup JWT 验证 `/admin/users`、`/admin/tools`、`/admin/config` 的加载和写回；使用 user backup JWT 直接访问 `/admin/users` 时由 `RequireAdmin` 导航到 `/workbench/input`，直接 curl 同一后端 API 仍返回 403。
- 不为 T13 新增 scenarios 页面；不修改 T11 的后端路由、权限或响应 envelope。

## 验收标准

- [ ] `cd frontend && npm run build` 通过。
- [ ] admin 用户访问 `/admin/users` 后，浏览器请求 `GET /api/v1/admin/users` 返回 `data.items`；创建用户、切换 status、重置密码后列表重新加载，网络请求路径分别为 `POST/PATCH /api/v1/admin/users` 和 `POST /api/v1/admin/users/{id}/reset-password`。
- [ ] `/admin/tools` 能加载并切换 enabled/disabled，创建表单的三个 JSON 字段非法时不发送请求，测试和删除分别调用 `/tools/{id}/test`、`DELETE /tools/{id}`。
- [ ] `/admin/datasources` 能创建、启停、连通测试；credential 不出现在 DOM 之外的持久化存储、URL、console 和错误文本中。
- [ ] `/admin/llm` 能加载 provider、提交 api_key、执行 health；列表不显示明文 api_key，前端 localStorage 不出现 `api_key` 或 `credential`。
- [ ] `/admin/audits` 四个 tab 分别请求 `/sessions`、`/messages`、`/traces`、`/audits`，trace/audit detail 能展示后端 `data.events/detail`。
- [ ] `/admin/config` 编辑 `sandbox.max_concurrent=5` 后执行 `GET /api/v1/admin/config` 返回 `5`；输入 `0` 或 `33` 时前端阻止提交。
- [ ] 普通 user 访问 `/admin/users` 被导航到 `/workbench/input`；直接执行 `curl -sS -H "Authorization: Bearer $USER_TOKEN" http://127.0.0.1:8000/api/v1/admin/users` 仍返回 HTTP 403，证明前端守卫未替代后端 RBAC。
