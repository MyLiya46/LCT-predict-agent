# LCT-predict-agent · 缝合重构实施任务清单（docs/todo.md）

> 日期：2026-09-01
> 状态：全新开局——缝合 `reference_repo/predict-agent/backend-backup`（通用 Agent 后端壳）+ `reference_repo/predict-agent/frontend-ref`（冰洗工作台 React 前端），旧 plans/todo 已悉数删除，本清单从 T01 起。
> 计划文件目录：docs/plans/
> 说明：本清单与 docs/plans/ 下任务计划一一对应（`一任务一文件`），以「拓扑顺序」排列（前置任务在前）。

---

## 一、任务总览（拓扑顺序 = 建议执行顺序）

| 序号 | 任务 ID | 标题（英文短名） | blockedBy | 状态 | 验收要点（摘要） | 计划文件 |
|---|---|---|---|---|---|---|
| 1 | T01 | 后端壳就位（backend-scaffold） | 无 | **reviewed** | backend-backup/ref 环境键合并；backend/ 只留一个 `.env` 和 `.env.example`；Git Bash 复用 `scripts/dev_db_pg.sh`；5 个快速壳测试（25 项）通过 | [backend-scaffold-2026-09-01.md](plans/T01-backend-scaffold-2026-09-01.md) |
| 2 | T02 | 前端就位（frontend-scaffold） | 无 | **reviewed** | frontend-ref → frontend/；保留 lockfile 并 `npm ci`；vite proxy `/api`→8000；`npm run build` 基线绿 | [frontend-scaffold-2026-09-01.md](plans/T02-frontend-scaffold-2026-09-01.md) |
| 3 | T03 | 能力域+聊天域数据模型并入 PG（domain-pg-models） | T01 | **reviewed** | 工作台 3 表 + icewash `fcst_*` 3 表 + forecast/attribution/what-if 4 语义表；聊天域加列、users.oa；Alembic 0003；剔 SQLite | [domain-pg-models-2026-09-01.md](plans/T03-domain-pg-models-2026-09-01.md) |
| 4 | T04 | 工作台域服务迁入（workbench-service） | T03 | **reviewed** | 模型侧持有并导出 3 个 Excel/知识源；成本/价格弹性同步 PG 缓存；策略知识经模型接口读取；JSONB 查询、权限和工作台路由 | [workbench-service-2026-09-01.md](plans/T04-workbench-service-2026-09-01.md) |
| 5 | T06 | 预测模型客户端+Excel 适配（forecast-model-client） | T03 | **reviewed** | 直连目标模型 `/predict`+`/tasks/{id}`；PG relay → 语义表为主链；五 Sheet Excel adapter 为离线入口 | [forecast-model-client-2026-09-01.md](plans/T06-forecast-model-client-2026-09-01.md) |
| 6 | T05 | 归因+whatif 域服务迁入（attribution-whatif-service） | T03、T06 | **reviewed** | PG-only attribution/baseline；代理目标模型策略与 taskid；JSONB 查询、权限和 API 契约 | [attribution-whatif-service-2026-09-01.md](plans/T05-attribution-whatif-service-2026-09-01.md) |
| 7 | T07 | 认证双通道（auth-dual-channel） | T03 | **reviewed** | OAuth 客户端迁入 + users.oa + `POST /api/auth/login`；backup JWT 与 OAuth token 分离；email 登录零回归 | [auth-dual-channel-2026-09-01.md](plans/T07-auth-dual-channel-2026-09-01.md) |
| 8 | T08 | LLM 网关适配与分析增强（llm-gateway） | T03 | **reviewed** | backup LLM/engine 不变；薄网关客户端 + Turing 分析增强 + `/api/health/agent`；不迁移 planner/memory | [llm-gateway-2026-09-01.md](plans/T08-llm-gateway-2026-09-01.md) |
| 9 | T09 | backup 原生聊天上下文与能力工具（chat-context-capability-tools） | T04、T05、T06、T08 | **reviewed** | backup engine + Conversation/Message；七项内部工具覆盖五 capability；无 intent/planner/向量记忆 | [chat-context-capability-tools-2026-09-01.md](plans/T09-chat-context-capability-tools-2026-09-01.md) |
| 10 | T10 | 聊天 envelope 编排+SSE+落库（chat-envelope-service） | T09、T07 | **reviewed** | `/api/sessions`+`/api/chat`+`/api/chat/stream`（status/result/done + envelope）；结果落 messages.result_envelope | [chat-envelope-service-2026-09-01.md](plans/T10-chat-envelope-service-2026-09-01.md) |
| 11 | T11 | 管理端 API 对齐验证（admin-api-align） | T03 | **reviewed** | 复用 backup `/api/v1/admin` 七模块；seed admin+10 权限点；越权留痕核验 | [admin-api-align-2026-09-01.md](plans/T11-admin-api-align-2026-09-01.md) |
| 12 | T12 | 前端双登录改造（login-dual-entry） | T02、T07 | **reviewed** | LoginPage OA+email 双入口；AuthStore 双 token；api.ts 加 email 登录 | [login-dual-entry-2026-09-01.md](plans/T12-login-dual-entry-2026-09-01.md) |
| 13 | T13 | 管理端六页 React 新建（admin-pages-react） | T02、T11、T12 | **reviewed** | AdminLayout+Users/Tools/Datasources/LLM/Audits/Config 六页；api.ts admin 封装；路由守卫 | [admin-pages-react-2026-09-01.md](plans/T13-admin-pages-react-2026-09-01.md) |
| 14 | T14 | icewash 栈联调自检（icewash-stack-check） | T03 | **reviewed** | 启动 icewash server → /health /predict /tasks/{id} /whatif/strategies /simulate /optimize；pg_sync 写 PG 三表 | [icewash-stack-check-2026-09-01.md](plans/T14-icewash-stack-check-2026-09-01.md) |
| 15 | T15 | 端到端验收（e2e-acceptance） | T04、T05、T06、T10、T11、T12、T13、T14 | **reviewed** | 双登录→聊天(真实 LLM+真实 icewash 预测)→结果落 PG+工作台真实数据→管理端可用；T01 25 项快速壳测试通过，全量 pytest 仅收集不自动执行 | [e2e-acceptance-2026-09-01.md](plans/T15-e2e-acceptance-2026-09-01.md) |

---

## 二、拓扑顺序注释（blockedBy 依据摘要）

- **源**：`reference_repo/predict-agent/backend-backup`（通用 Agent 后端壳：FastAPI + SQLAlchemy2 async + PG + JWT 双令牌 + RBAC + engine loop + 沙箱 + SSE + 追溯）**为后端底座**；`reference_repo/predict-agent/frontend-ref`（React18 + Tailwind + zustand + echarts，11 页 + 10 组件）**为前端主体**；`reference_repo/predict-agent/backend-ref`（独立 FastAPI 冰洗平台：OA 登录 / 会话 / Agent 桥 / 异步预测 client / workbench / attribution / whatif 能力域）**为能力域与聊天 envelope 源的参考实现**；`services/icewash-model`（cbg_fcst_month）**为冰洗预测模型独立服务（已就绪，几乎不改）**。reference_repo 三目录**只读参考、永不 import**；实现全部落根目录无后缀 `backend/`、`frontend/`，模型落 `services/icewash-model/`。
- **层 0（可并行）**：`T01（后端壳就位）`、`T02（前端就位）`无前置，天然并行。
- **层 1（数据底座）**：`T03（能力域+聊天域数据模型并入 PG）`依赖 `T01`——单一 PG 数据源，新增能力域表 + 聊天域加列 + `users.oa`，剔除 backend-ref 的 SQLite（aiosqlite/PRAGMA/json_each）。
- **层 2（能力域/横切服务，依赖 T03）**：`T04（workbench）`、`T06（预测模型客户端）`、`T07（认证双通道）`、`T08（LLM 网关接入）`、`T11（管理端 API 对齐）`、`T14（icewash 栈自检）` 可并行；`T05（attribution+whatif）` 在 `T06` 完成后执行，读取 T06 写入的 PG 语义表。
- **层 3（chat 编排聚合）**：`T09（backup 原生上下文+五 capability 工具）`依赖 `T04+T05+T06+T08`（原生 engine 上下文接入能力域和 LLM 网关）；`T10（chat envelope 编排+SSE+落库）`依赖 `T09+T07`——把 backup 原生上下文、能力工具和 LLM 结果组装成 `/api/chat/stream` 的 `status/result/done + envelope` 通道。
- **层 4（前端入口与管理端，依赖后端）**：`T12（前端双登录）`依赖 `T02+T07`；`T13（管理端六页）`依赖 `T02+T11+T12`，复用 T12 的认证请求基座。
- **收口**：`T15（端到端验收）`依赖 `T04+T05+T06+T10+T11+T12+T13+T14`。
- **关键口径（落为硬约束）**：① **单一数据源 = PG**——能力域表（workbench_dataset_rows / attribution_analysis_rows / forecast_history_rows 等）与聊天域（并入 conversations/messages 加列）与壳 17 表全在一个 PG，剔 backend-ref 的 SQLite/aiosqlite/PRAGMA/json_each（`json_each`→PG `jsonb_each`）；② **前端契约不破坏**：frontend-ref `api.ts` 的 `/api/auth/login`、`/api/sessions`、`/api/chat`、`/api/chat/stream`、`/api/workbench/*`、`/api/attribution/*`、`/api/whatif/*`、`/api/whatif/baseline`、`/api/whatif/strategies`、`/api/products`、`/api/agent/probe*`、`/api/health/agent` 全部按现字段实现，SSE 为 `status→result→done + envelope(response_type/text/chart/table)`；`/api/agent/probe*` 由 T10 以 frontend-ref `api.ts` 的实际 method/path/body/response 为准兼容，不新增第二套契约；③ **聊天数据并入 conversations/messages**——不新建 backend-ref 的 chat_sessions/chat_messages/session_memory_chunks，`messages` 加 `result_envelope(JSONB)`、`conversations` 加 `agent_conversation_id/memory_summary/memory_slots/summary_upto_id`；④ **聊天底座以 backend-backup 为准**——LLMProvider、engine loop、tool registry、SSE、trace、Conversation/Message 全部保留，backend-ref 的 intent/planner/regex 规则/向量 memory 不迁移；⑤ **认证双通道**——email+password（backup `/api/v1/auth/*` 全保留）+ OA（`POST /api/auth/login`，OAuth 网关换取 `oauth_access_token` → 按规范化 oa 建/关联 user → 签 backup 的 JWT 双令牌；工作台 Authorization 使用 backup JWT，LLM `new_token` 使用 OAuth token）；⑥ **策略目录唯一来源 = icewash-model**——`/api/whatif/strategies` 只转发 icewash `/whatif/strategies`，`/api/whatif/baseline` 只读 PG，`simulate/optimize` 只转发 icewash `/simulate` `/optimize`；backend 不复制策略目录或演算公式；⑦ **真实端到端**——真实 LLM 网关（backup LLMProvider/engine 作为聊天编排底座，ml-api-gw 客户端和 Turing 作为网关/分析增强）+ 真实 icewash 预测（`POST /predict` + `GET /tasks/{id}` 轮询）→ 结果落 PG + 工作台展示真实数据。
- **T04 参考数据口径**：`docs/UI设计稿/*.xlsx` 和 `docs/知识库/*.md` 只作为初始迁移输入；运行时副本归 `services/icewash-model/data/reference/`，由模型 loader 校验并通过内部接口导出；`cost_data`、`price_elasticity` 仅以模型导出结果同步到 PG `workbench_dataset_rows`，策略 Excel/Markdown 不入 PG，前后端不得直接读取 `docs/`。
- **已决补充口径**：`/api/products` 保留 T10 的 PG 兼容投影，表为空时返回 `[]`；管理端六页前端无 React 现成版，T13 全量新写；T10 负责兼容 frontend-ref 已声明的 `/api/agent/probe*` 路径。

---

## 三、交付物核对（对照任务要求）

- [x] docs/plans/ 下生成任务计划文件，文件名符合 `T{n}-description-of-the-plan-YYYY-MM-DD.md`，互不重名
- [x] 任一计划文件可独立开工（含 blockedBy/步骤/涉及文件/可运行验收项）
- [x] todo.md 按拓扑顺序列出全部任务（上表排序），字段完整，状态均 reviewed
- [x] 每任务验收标准至少含 1 条可运行验证项
- [x] 本次计划已逐条评审通过，未决策略来源和 What-if 请求字段已收口
