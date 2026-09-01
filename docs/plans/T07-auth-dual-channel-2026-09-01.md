# T07 · 认证双通道（auth-dual-channel）

- **任务 ID**：T07
- **标题与目标**：新增 `/api/auth/login` OA 登录（OAuth 网关验证 → 按规范化 oa 建/关联 user → 签发 backup 的 JWT 双令牌），与既有 email+password 并存；`users.oa` 列已由 T03 加好，本任务接入认证服务。
- **关联文档章节**：feat-icewash.md §11.1（OA 换 JWT）；backend-ref services/oauth_client.py；backend-backup auth/tokens.py、domain/auth_service.py
- **前置依赖 blockedBy**：T03
- **状态**：reviewed

## 实施要点

### 1. 迁入 OAuth 客户端 `backend/src/app/auth/oauth.py`
- 由 backend-ref `oauth_client.py` 迁入 `fetch_access_token(username)`：httpx `application/x-www-form-urlencoded`（`files=` 传 form），向 `OAUTH_BASE_URL + OAUTH_TOKEN_PATH` 换 token；抽取 `access_token`（兼容 `{access_token}` 与 `{data:{access_token}}`），返回上游 token、`token_type`、`expires_in`。
- config 增加 `oauth_base_url="https://aigc-gateway.tcl.com"`、`oauth_token_path="/oauth/oauth/token"`、`oauth_grant_type="username"`、`oauth_client_id="ai-client"`、`oauth_client_secret="secret"`、`oauth_source_type="app"`、`oauth_user_type="P"`、`oauth_login_field="username"`、`oauth_device_id=""`（`.env.example` 同步）。
- OA 输入先执行 `strip().lower()`，空值或超过 128 个字符时抛出 `ValidationError`；OAuth HTTP 异常、4xx/5xx 响应和缺失 `access_token` 统一转换为 `ValidationError("OA 登录失败：OAuth 网关未通过验证")`，响应体不得包含 client secret、完整上游响应或 token。

### 2. 认证服务扩展 `backend/src/app/domain/auth_service.py`
- 新增 `login_by_oa(session, oa, ip, user_agent)`：
  1. 将 `oa` 规范化为 `oa.strip().lower()`，调用 `fetch_access_token(username=oa)`；网关不可达、403、4xx/5xx 或响应缺少 token 时返回 `ValidationError`，HTTP 状态为 400，message 固定为 `OA 登录失败：OAuth 网关未通过验证`，并写入 `auth.login_failed` 审计；
  2. 在同一 PG 事务内执行 `SELECT pg_advisory_xact_lock(hashtextextended(:oa, 0))`，再查询 `select(User).where(User.oa == oa)`；无用户时创建 `email=f"{oa}@tcl.com"`、`nickname=oa`、`password_hash=hash_password(secrets.token_urlsafe(32))`、`status="active"` 的用户，绑定 `user` 角色。此自动创建路径不执行 email 白名单校验；
  3. 已存在且 `status != "active"` 时返回 `UnauthorizedError("账号已被禁用")`；已存在的 active 用户沿用其现有角色；
  4. 抽取 `_issue_tokens` 与 `_store_refresh` 的公共签发逻辑，签发 backup `access_token` JWT 和 `refresh_token` JWT，写入 `refresh_tokens`，成功后写入 `auth.login` 审计并提交事务；
  5. 返回原始 JSON（不包 `to_uni`），字段固定为 `oa`、`access_token`（backup JWT）、`refresh_token`（backup JWT）、`token_type`、`expires_in`、`oauth_access_token`、`oauth_token_type`、`oauth_expires_in`。OAuth 网关 token 只随本次登录响应返回，不写入 `users`、`refresh_tokens` 或其它 PG 表。
- `register_user`、`login_user`、`refresh_login` 的 email+password 行为保持不变；`users.oa` 为空只允许 email 注册路径产生。

### 3. 路由 `backend/src/app/api/auth.py` 新增
- 新建独立 `oa_router = APIRouter(prefix="/auth", tags=["auth"])`；`OaLoginIn` 定义 `oa: str = Field(..., min_length=1, max_length=128)`；在该 router 新增 `POST /api/auth/login`，body 为 `{ "oa": "..." }`，直接返回 `login_by_oa` 的原始 JSON。主 `auth.router` 只挂 `/api/v1`，不得把整套路由重复挂到 `/api`。
- 保留既有 `/api/v1/auth/*`（email 注册/登录/refresh/logout/me/password/me）走壳路径；OA 路由与 email 路由不冲突：前者挂在 `/api`，后者挂在 `/api/v1`。`/api/auth/me` 不新增，统一使用既有 `/api/v1/auth/me` 验证 backup JWT。

## 验收标准
- [ ] `uv run pytest tests/test_oauth_login.py tests/test_auth.py`（新增 OA 测试 + 既有 email 回归）通过：mock `fetch_access_token` 返回 token 时，`POST /api/auth/login` 返回 200，响应含 backup `access_token`、`refresh_token` 和独立的 `oauth_access_token`。
- [ ] 首次登录与二次登录同一规范化 oa 后，`SELECT count(*) FROM users WHERE oa='test'` 等于 1；并发首次登录测试不产生第二个 user，两个请求均能拿到 JWT。
- [ ] OA 自动用户的 `load_user_ctx` 含 `user` 角色、`chat:read`、`chat:send`；使用 backup `access_token` 请求 `/api/v1/auth/me` 返回 200。
- [ ] 网关不可达、403、响应缺少 token 时，`POST /api/auth/login` 返回 HTTP 400、`code=400_VALIDATION` 和固定可读 message，非 500，且新增一条 `auth.login_failed` 审计。
- [ ] 成功 OA 登录新增一条 `auth.login` 审计；email 登录注册/刷新/登出测试全部通过。
- [ ] `curl -s -X POST http://127.0.0.1:8000/api/auth/login -H "Content-Type: application/json" -d '{"oa":"test"}'`（网关未可达时）返回 HTTP 400、`code` 为 `400_VALIDATION`，响应中不出现 OAuth secret 或完整上游响应。
