# T17 · 聊天会话与交互体验修复（chat-ux-session-auth-fix）

- 任务 ID：T17
- 标题与目标：补齐会话删除/重命名/置顶与注册入口，实现智能跟随滚动、可展开思考过程，并让健康状态徽标与真实聊天来源一致。
- 关联文档章节：`docs/feat-icewash.md` §5.1、§12.4；T12、T15、T16
- 前置依赖 blockedBy：T16

## 执行画像

- execution_mode：direct
- execution_class：normal
- expected_duration：约 20 分钟
- external_waits：frontend dev server；T16 的后端健康契约
- checkpoint_phases：会话 CRUD、注册入口、智能滚动、思考面板、构建验收
- resume_boundary：从最后一个未通过的前端阶段继续

## 问题

- 原生后端已有会话软删除能力，但工作台 `/api/sessions` 门面和前端均没有 delete 契约与按钮；重命名/置顶无法完整使用。
- `/api/v1/auth/register` 可用，登录页没有用户注册入口，普通用户无法从 UI 完成注册。
- ChatPanel 的滚动容器没有根据用户滚动位置切换自动跟随；流式状态更新会打断用户浏览历史。
- 思考过程只依赖内部状态，缺少稳定的展开/收起语义和可访问关联；健康状态显示仍沿用 `mcp` 文案，无法表达 T16 的 Provider 模式。

## 决策

- 新增 `DELETE /api/sessions/{session_id}` 门面，复用 domain owner 校验和软删除；删除后前端从列表、最近标签和当前会话中同步移除。
- 登录页保留 OA/账号登录 tab，并增加账号注册视图：邮箱、昵称、密码、确认密码；注册成功后切回账号登录并保留邮箱，不在前端保存密码或 token。
- 使用 48px “接近底部”阈值：发送消息时强制滚到底部；用户上滑后暂停跟随；用户回到底部或点击“回到底部”后恢复跟随；加载历史会话后定位到底部。
- 思考过程默认收起，按钮使用 `aria-expanded`/`aria-controls`，展开后展示步骤列表、旋转箭头和“收起”文案；不展示供应商隐藏思维链，只展示后端已发布的状态步骤。

## 范围

- 包含：会话删除 API/状态同步、注册 UI/API、ChatPanel 智能滚动和思考面板、AppShell 健康徽标文案与类型适配。
- 不包含：改变认证协议、放宽注册邮箱白名单、将未发布的模型内部 reasoning 写入数据库或浏览器。

## 环境预检

- 必需 Shell：git-bash
- 必需命令：`npm`、`npm run build`、`rg`
- 必需端口：5173；API 联调可选 8000
- 必需 URL：`http://127.0.0.1:5173`、`http://127.0.0.1:8000/api/health/agent`
- 必需 Python 模块：无
- 必需 Docker 容器：无
- 容器内必需命令：无
- 容器内必需 Python 模块：无
- 执行画像：normal
- 启动超时（秒）：30
- 空闲超时（秒）：60
- 硬截止（秒）：900
- 最大 checkpoint 间隔（秒）：120
- 预检命令：
  ```bash
  test -d frontend/node_modules && test -f frontend/src/components/ChatPanel.tsx && test -f frontend/src/pages/LoginPage.tsx
  ```

## 风险与回滚

- 风险：删除当前会话或注册表单状态处理错误会影响本地 UI 状态；滚动监听若未清理会造成重复 listener；前端类型若未同步会阻断构建。
- 回滚：实施前执行 `git diff -- frontend/src > /tmp/lct-t17.patch`；若前端回归超出范围，执行 `git apply -R /tmp/lct-t17.patch` 并重新运行构建。

## 实施步骤

### 步骤 1：补齐会话删除门面和前端状态

- 对象：`/api/sessions/{session_id}` 及 Zustand 会话状态。
- 动作：新增 DELETE 路由、`api.deleteSession` 和 store `deleteSession`；UI 删除前确认，成功后清理 sessions/recent tabs，当前会话回到新对话。
- 参数：沿用 `chat:delete` 权限与 owner 404；响应为 `{ok:true}`；不物理删除消息、trace 或数据库行。
- 核心修改文件：`frontend/src/api.ts`、`frontend/src/store.ts`、`frontend/src/components/ChatPanel.tsx`
- 必要集成文件：`backend/src/app/api/chat_facade.py`、`backend/tests/test_chat_facade.py`
- 命令：
  ```bash
  cd backend && uv run pytest tests/test_chat_facade.py -q
  ```

### 步骤 2：提供账号注册入口

- 对象：登录页账号认证视图和 `/api/v1/auth/register` 前端客户端。
- 动作：增加“注册账号”入口与注册表单，校验邮箱、密码确认和后端口令政策；注册成功后切换账号登录视图并填充邮箱，错误只显示可读 message。
- 参数：注册请求只发送 `email/password/nickname`；不发送 Authorization；密码确认字段不发送后端；保留邮箱白名单由后端决定。
- 核心修改文件：`frontend/src/api.ts`、`frontend/src/pages/LoginPage.tsx`
- 必要集成文件：`backend/src/app/api/auth.py`、`backend/tests/test_auth.py`
- 命令：
  ```bash
  cd frontend && npm run build
  ```

### 步骤 3：实现智能跟随滚动

- 对象：ChatPanel 消息滚动容器和发送/加载/流式状态更新。
- 动作：增加 scroll ref、接近底部判定、requestAnimationFrame 滚底函数和清理后的 scroll listener；发送、切换会话、进入新会话强制跟随，用户主动上滑时暂停，回到底部或点击按钮时恢复。
- 参数：阈值固定 48px；滚动行为使用 `behavior=auto`，不在每个 token 上执行平滑动画；`loading/processSteps/messages` 更新仅在 `followRef=true` 时滚动。
- 核心修改文件：`frontend/src/components/ChatPanel.tsx`
- 必要集成文件：`frontend/src/types.ts`
- 命令：
  ```bash
  rg -n "scrollHeight|scrollTop|scrollTo|回到底部|processSteps" frontend/src/components/ChatPanel.tsx
  ```

### 步骤 4：完善思考过程展开和状态徽标

- 对象：`AssistantMessageBubble` 思考面板与 `AppShell` Agent 状态徽标。
- 动作：为思考列表生成稳定关联 id，按钮切换 `aria-expanded`、`aria-controls`、箭头旋转和收起文案；根据 T16 的 `mode=provider` 显示可用的 Chat Provider 状态，保留 live/disabled/error 三态颜色。
- 参数：步骤仅取 `process_steps`，最多 40 条；`mcpOk=true` 时不得显示“异常”；无健康响应时显示“检测中/异常”而不是伪造已连接。
- 核心修改文件：`frontend/src/components/ChatPanel.tsx`、`frontend/src/components/AppShell.tsx`
- 必要集成文件：`frontend/src/store.ts`、`frontend/src/api.ts`
- 命令：
  ```bash
  cd frontend && npm run build
  ```

## 完成标准

- 验收类型：mixed
- 离线验收命令：
  ```bash
  cd frontend && npm run build && cd .. && rg -n "deleteSession|register|aria-expanded|aria-controls|scrollHeight|scrollTop|回到底部" frontend/src
  ```
- 外部环境验收命令：
  ```bash
  curl -fsS http://127.0.0.1:5173 >/dev/null; curl -fsS http://127.0.0.1:8000/api/health/agent
  ```
- 通过条件：前端构建退出码为 0；删除/重命名/置顶均有可操作入口；注册表单调用正确公共接口；发送时滚底、上滑时流式更新不滚屏、回到底部恢复；思考按钮可展开并呈现 `aria-expanded=true`/“收起”；Provider 模式健康时徽标不显示 disabled/异常。
