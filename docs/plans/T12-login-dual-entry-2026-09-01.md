# T12 · 前端双登录改造（login-dual-entry）

- **任务 ID**：T12
- **标题与目标**：将 frontend-ref 的单 OA 登录改为 OA + email/password 双入口，按 T07 的 token 分工保存并续期 backup JWT 与 OAuth token，使所有工作台请求使用 backup JWT、聊天网关 `new_token` 只使用 OAuth token。
- **关联文档章节**：`docs/feat-icewash.md` §11.1；frontend-ref `src/authStore.ts`、`src/pages/LoginPage.tsx`、`src/api.ts`、`src/store.ts`、`src/components/AppShell.tsx`、`src/pages/WorkbenchPage.tsx`；T02、T07、T10
- **前置依赖 blockedBy**：T02、T07

## 实施要点

### 1. 固定前端认证数据结构

- 在 `frontend/src/authStore.ts` 将 `AuthSession` 固定为：`mode: "oa" | "email"`、`oa: string | null`、`email: string | null`、`accessToken: string`（backup JWT）、`refreshToken: string`（backup JWT）、`tokenType: string`、`expiresAt: number`、`oauthAccessToken: string | null`、`oauthTokenType: string | null`、`oauthExpiresAt: number`。
- OA 登录写入 `mode="oa"`、规范化后的 `oa`、backup `access_token/refresh_token`、`expiresAt=Date.now()+expires_in*1000`、OAuth `oauth_access_token/oauth_token_type` 和 `oauthExpiresAt=Date.now()+oauth_expires_in*1000`；email 登录写入 `mode="email"`、email、backup 双令牌，`oa=null`、`oauthAccessToken=null`、`oauthExpiresAt=0`。
- `expires_in` 和 `oauth_expires_in` 必须为正数；小于等于 0 的 token 立即视为过期，不使用固定 12 小时 TTL。续期判断统一预留 `TOKEN_EXPIRY_SKEW_MS=60000`，即剩余 60 秒以内视为过期。
- `localStorage["forecast-agent-auth"]` 只保存上述认证字段，不保存密码、OAuth client secret、HTTP Authorization header 或完整登录响应；`hydrate()` 能恢复 OA/email 两种模式，`isAuthenticated()` 在 backup access token 有效或 refresh token 存在时返回 true。

### 2. `frontend/src/api.ts` 认证请求封装

- 新增 `readBackupToken()`：仅从 `localStorage["forecast-agent-auth"]` 读取 `accessToken`；无 token 返回 null，不从 Zustand store import，避免 `api.ts → authStore.ts → api.ts` 循环依赖。
- `json()` 对受保护请求自动添加 `Authorization: Bearer <backup accessToken>`；下列公开路径不添加该 header：`/api/auth/login`、`/api/v1/auth/login`、`/api/v1/auth/register`、`/api/v1/auth/refresh`、`/api/health/agent`。错误解析同时支持裸 JSON、`{code,message,data}` 和 FastAPI `detail`，优先使用可读的 `message`。
- 受保护 `json()` 请求收到 HTTP 401 时最多执行一次 `refreshBackupTokenOnce()`：从 localStorage 读取当前 `refreshToken`，直接 POST `/api/v1/auth/refresh`，用响应 `data.access_token/refresh_token/expires_in` 更新原 session 的 backup 字段，派发 `forecast-agent-auth-updated` 浏览器事件，再以新 access token 重试原请求；refresh 失败直接返回原 401，不进入递归重试。`authStore.ts` 注册该事件并同步 Zustand 状态。
- `loginWithOa(oa)` 固定请求 `POST /api/auth/login`，返回裸 JSON：`oa/access_token/refresh_token/token_type/expires_in/oauth_access_token/oauth_token_type/oauth_expires_in`。
- `loginWithEmail(email,password)` 固定请求 `POST /api/v1/auth/login`，解包 `data` 后返回 `access_token/refresh_token/token_type/expires_in`；不把 email 登录响应中的 backup JWT 当 OAuth token。新增 `refreshWithToken(refreshToken)` 请求 `POST /api/v1/auth/refresh`，同样解包 `data`。
- `ChatAuth` 固定为 `{oa?: string | null; backupAccessToken: string; oauthAccessToken?: string | null}`。`sendChat()` 和 `sendChatStream()` 都使用 `backupAccessToken` 设置 HTTP Authorization，body 的 `access_token` 只写 `oauthAccessToken` 非空值，email 模式省略该字段；`oa` 只在 OA 模式写入 body。
- `sendChatStream()` 的 fetch 请求头固定为 `Content-Type: application/json` 和 `Authorization: Bearer <backupAccessToken>`；不得继续只依赖 body 中的 `access_token` 认证后端。
- `sendChatStream()` 收到 HTTP 401 时复用 `refreshBackupTokenOnce()`，只重试原请求一次并替换 Authorization；OAuth token 的续期仍由调用前的 `ensureValidToken()` 完成，不把 backup refresh 当成 OAuth refresh。

### 3. `frontend/src/authStore.ts` 双模式登录与续期

- `login(oa)` 调用 `api.loginWithOa(oa.trim())`，校验响应含正数 `expires_in`、`oauth_expires_in` 和非空 backup/OAuth token 后保存 OA 会话；校验失败清除本地会话并抛出“登录响应无效”。
- 新增 `loginEmail(email,password)` 调用 `api.loginWithEmail(email.trim().toLowerCase(), password)`，校验 backup 双令牌和正数 `expires_in` 后保存 email 会话。
- `ensureValidToken()` 固定返回 `{mode, oa, email, backupAccessToken, oauthAccessToken}`：
  1. backup access token 剩余时间大于 60 秒时继续使用；否则先用 `refreshToken` 调用 `/api/v1/auth/refresh` 并替换 backup 双令牌；
  2. OA 模式的 OAuth token 剩余时间大于 60 秒时继续使用，否则调用 `/api/auth/login` 重新取得 OAuth token；若该响应同时返回新的 backup 双令牌，则一并替换；
  3. email 模式不生成 OAuth token；backup refresh 失败、OA 重新登录失败或响应校验失败时清除会话并抛出“登录已过期，请重新登录”。
- `logout()` 清除 `localStorage` 和 Zustand 状态；若存在 backup access/refresh token，先以 `POST /api/v1/auth/logout`、`Authorization: Bearer <backup JWT>` 和 `X-Refresh-Token: <backup refresh JWT>` 发起 best-effort 登出，网络失败不阻止本地退出。
- `applySession()` 同步写入 `oa/email/mode/accessToken/refreshToken/expiresAt/oauthAccessToken/oauthExpiresAt`；刷新后不能丢失另一种 token，email 模式始终保持 `oauthAccessToken=null`。

### 4. `frontend/src/pages/LoginPage.tsx` 双入口

- 页面新增两个互斥 tab：`OA 登录` 和 `账号登录`；默认打开 OA tab，tab 切换清空当前错误和 loading 状态。
- OA tab 保留 `oa` 输入框和 `login(oa)`；账号 tab 新增 `email`、`password` 输入框和 `loginEmail(email,password)`，两个表单均禁止空值提交、提交期间按钮 disabled，并显示同一错误区域。
- 任一登录成功都执行 `navigate("/", {replace:true})`；失败只展示 API 返回的可读 message，不把 token 或上游响应渲染到页面。
- 账号 tab 不新增注册流程；后端 `/api/v1/auth/register` 保留原生 API，T12 只负责已有账号登录。

### 5. 适配现有工作台调用方

- 修改 `frontend/src/store.ts`：`ensureValidToken()` 失败时提示“请先登录”或“登录已过期，请重新登录”，成功后调用 `sendChatStream(..., {oa: token.oa, backupAccessToken: token.backupAccessToken, oauthAccessToken: token.oauthAccessToken})`；删除把 backup JWT 作为 OAuth `access_token` 的旧调用。
- 修改 `frontend/src/components/AppShell.tsx` 与 `frontend/src/pages/WorkbenchPage.tsx`：显示身份时使用 `oa || email || "未登录"`，标题从“当前登录 OA”改为“当前登录账号”；email 用户不得显示空白或 `undefined`。
- `App.tsx` 的路由守卫继续使用 `hydrated` + `isAuthenticated()`；刷新页面后 email 用户和 OA 用户均能进入工作台，过期 token 在首次受保护请求前按 `ensureValidToken()` 续期。

### 6. 测试与契约验收

- 在 `frontend/` 执行 `npm run build`，覆盖 TypeScript 对双模式 `AuthSession`、`ChatAuth` 和现有工作台调用方的类型检查。
- 浏览器网络面板验证 OA 登录请求为 `POST /api/auth/login` 且无 Authorization header；email 登录请求为 `POST /api/v1/auth/login` 且无 OAuth 字段；受保护的 `/api/sessions`、`/api/workbench/*` 请求使用 backup JWT。
- 浏览器网络面板验证 OA 聊天请求的 HTTP Authorization 是 backup JWT，JSON body 的 `access_token` 是 OAuth token；email 聊天请求仍带 backup JWT，body 不含 `access_token`。
- 使用两个独立浏览器会话验证 `localStorage["forecast-agent-auth"]`：OA 会话包含 `mode/oa/accessToken/refreshToken/oauthAccessToken`，email 会话包含 `mode=email/email/accessToken/refreshToken` 且 `oauthAccessToken=null`；刷新页面后两者都通过路由守卫。
- 将 email 会话的 backup access token 改为过期值后访问任一工作台接口，验证只发送一次 `/api/v1/auth/refresh`、原请求自动重试一次并更新 Zustand；让 refresh 返回 401，验证不循环请求并回到登录页。

## 验收标准

- [ ] `cd frontend && npm run build` 通过。
- [ ] OA 登录成功后，`localStorage["forecast-agent-auth"]` 同时含 `mode="oa"`、backup `accessToken/refreshToken`、`oauthAccessToken`，两个过期时间分别使用响应中的 `expires_in` 和 `oauth_expires_in`；email 登录成功后含 `mode="email"`、email 和 backup 双令牌，`oauthAccessToken` 为 null。
- [ ] 账号 tab 请求 `/api/v1/auth/login`，OA tab 请求 `/api/auth/login`；两个登录请求都不携带旧会话的 Authorization header。
- [ ] 让 backup access token 剩余时间小于 60 秒后发送受保护请求，email 模式调用 `/api/v1/auth/refresh` 并替换 access/refresh；让 OA OAuth token 剩余时间小于 60 秒后发送聊天请求，OA 模式重新调用 `/api/auth/login` 并只更新 OAuth token 或按响应替换整组 token。
- [ ] Git Bash 中设置 `BACKUP_JWT` 后执行 `curl -sS -H "Authorization: Bearer $BACKUP_JWT" http://127.0.0.1:8000/api/sessions`，返回 HTTP 200；不设置该 header 访问同一路径返回 HTTP 401。
- [ ] `grep -RInE "accessToken.*new_token|new_token.*accessToken|请先登录 OA 账号|TOKEN_TTL_MS" frontend/src` 无命中；`grep -RIn "Authorization" frontend/src/api.ts` 至少命中 `sendChatStream` 和受保护 JSON 请求注入逻辑。
