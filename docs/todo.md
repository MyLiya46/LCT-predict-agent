<!-- GENERATED FROM docs/todo.json; DO NOT EDIT -->
# LCT-predict-agent · 缝合重构实施任务清单（docs/todo.md）

> 日期：2026-09-01
> 状态：全新开局——缝合 `reference_repo/predict-agent/backend-backup`（通用 Agent 后端壳）+ `reference_repo/predict-agent/frontend-ref`（冰洗工作台 React 前端），旧 plans/todo 已悉数删除，本清单从 T01 起。
> 计划文件目录：docs/plans/
> 说明：本清单与 docs/plans/ 下任务计划一一对应（`一任务一文件`），以「拓扑顺序」排列（前置任务在前）。

---

## 一、任务总览（拓扑顺序 = 建议执行顺序）

| 序号 | 任务 ID | 标题（英文短名） | blockedBy | 状态 | 验收要点（摘要） | 计划文件 |
|---|---|---|---|---|---|---|
| 1 | T01 | 后端壳就位（backend-scaffold） | 无 | completed | - | [plan](plans/T01-backend-scaffold-2026-09-01.md) |
| 2 | T02 | 前端就位（frontend-scaffold） | 无 | completed | - | [plan](plans/T02-frontend-scaffold-2026-09-01.md) |
| 3 | T03 | 能力域+聊天域数据模型并入 PG（domain-pg-models） | T01 | completed | - | [plan](plans/T03-domain-pg-models-2026-09-01.md) |
| 4 | T04 | 工作台域服务迁入（workbench-service） | T03 | completed | - | [plan](plans/T04-workbench-service-2026-09-01.md) |
| 5 | T06 | 预测模型客户端+Excel 适配（forecast-model-client） | T03 | completed | - | [plan](plans/T06-forecast-model-client-2026-09-01.md) |
| 6 | T05 | 归因+whatif 域服务迁入（attribution-whatif-service） | T03、T06 | completed | - | [plan](plans/T05-attribution-whatif-service-2026-09-01.md) |
| 7 | T07 | 认证双通道（auth-dual-channel） | T03 | completed | - | [plan](plans/T07-auth-dual-channel-2026-09-01.md) |
| 8 | T08 | LLM 网关适配与分析增强（llm-gateway） | T03 | completed | - | [plan](plans/T08-llm-gateway-2026-09-01.md) |
| 9 | T09 | backup 原生聊天上下文与能力工具（chat-context-capability-tools） | T04、T05、T06、T08 | completed | - | [plan](plans/T09-chat-context-capability-tools-2026-09-01.md) |
| 10 | T10 | 聊天 envelope 编排+SSE+落库（chat-envelope-service） | T09、T07 | completed | - | [plan](plans/T10-chat-envelope-service-2026-09-01.md) |
| 11 | T11 | 管理端 API 对齐验证（admin-api-align） | T03 | completed | - | [plan](plans/T11-admin-api-align-2026-09-01.md) |
| 12 | T12 | 前端双登录改造（login-dual-entry） | T02、T07 | completed | - | [plan](plans/T12-login-dual-entry-2026-09-01.md) |
| 13 | T13 | 管理端六页 React 新建（admin-pages-react） | T02、T11、T12 | completed | - | [plan](plans/T13-admin-pages-react-2026-09-01.md) |
| 14 | T14 | icewash 栈联调自检（icewash-stack-check） | T03 | completed | - | [plan](plans/T14-icewash-stack-check-2026-09-01.md) |
| 15 | T15 | 端到端验收（e2e-acceptance） | T04、T05、T06、T10、T11、T12、T13、T14 | completed | - | [plan](plans/T15-e2e-acceptance-2026-09-01.md) |
| 16 | T16 | LLM 流式、沙箱与追溯联调修复（llm-stream-sandbox-trace-fix） | T15 | completed | - | [plan](plans/T16-llm-stream-sandbox-trace-fix-2026-09-03.md) |
| 17 | T17 | 聊天会话与交互体验修复（chat-ux-session-auth-fix） | T16 | completed | - | [plan](plans/T17-chat-ux-session-auth-fix-2026-09-03.md) |
| 18 | T18 | LLM 聊天与沙箱追溯联调验收（llm-chat-live-acceptance） | T16、T17 | completed | - | [plan](plans/T18-llm-chat-live-acceptance-2026-09-03.md) |
| 19 | T19 | Chat SSE 实时状态转发修复（chat-sse-live-relay-fix） | T18 | completed | - | [plan](plans/T19-chat-sse-live-relay-fix-2026-09-03.md) |
| 20 | T20 | 聊天 token 流式输出闭环（chat-token-stream-ui） | T19 | completed | - | [plan](plans/T20-chat-token-stream-ui-2026-09-03.md) |
| 21 | T21 | What-if 基线与异步策略工作流（whatif-async-simulation-workflow） | T05、T14、T20 | completed | - | [plan](plans/T21-whatif-async-simulation-workflow-2026-09-03.md) |
| 22 | T22 | 预测明细契约与价格持久化（prediction-detail-contract-price-cost） | T21 | completed | - | [plan](plans/T22-prediction-detail-contract-price-cost-2026-09-04.md) |
| 23 | T23 | 六个月型号级基线汇总（six-month-sku-aggregation） | T22 | completed | - | [plan](plans/T23-six-month-sku-aggregation-2026-09-04.md) |
| 24 | T24 | 毛利覆盖与库存周转展示（margin-inventory-metrics） | T23 | completed | - | [plan](plans/T24-margin-inventory-metrics-2026-09-04.md) |
| 25 | T25 | 销量与销售额双目标优化（sales-target-optimization） | T23、T24 | completed | - | [plan](plans/T25-sales-target-optimization-2026-09-04.md) |
| 26 | T26 | What-if 契约集成验收（whatif-contract-integration-acceptance） | T22、T23、T24、T25 | completed | - | [plan](plans/T26-whatif-contract-integration-acceptance-2026-09-04.md) |
| 27 | T27 | Agent optimize 品类契约与空基线保护（agent-category-contract-empty-baseline） | T26 | completed | - | [plan](plans/T27-agent-category-contract-empty-baseline-2026-09-04.md) |
| 28 | T28 | 历史销售额持久化与 What-if 基准价解析（historical-price-baseline-resolution） | T26 | completed | - | [plan](plans/T28-historical-price-baseline-resolution-2026-09-04.md) |
| 29 | T29 | What-if 规则策略基准价与缺失价处理（whatif-price-strategy-resolution） | T27、T28 | completed | - | [plan](plans/T29-whatif-price-strategy-resolution-2026-09-04.md) |
| 30 | T30 | What-if Agent 与基准价闭环验收（whatif-agent-price-integration-acceptance） | T27、T28、T29 | completed | - | [plan](plans/T30-whatif-agent-price-integration-acceptance-2026-09-04.md) |
| 31 | T31 | Agent 预测/归因工作流与证据闭环（agent-forecast-attribution-workflow） | T30 | completed | - | [plan](plans/T31-agent-forecast-attribution-workflow-2026-09-04.md) |
| 32 | T32 | 聊天预测/白盒归因复合结果契约（chat-forecast-attribution-envelope） | T31 | completed | - | [plan](plans/T32-chat-forecast-attribution-envelope-2026-09-04.md) |
| 33 | T33 | 聊天 What-if 策略矩阵与达成趋势（chat-whatif-strategy-envelope） | T32 | completed | - | [plan](plans/T33-chat-whatif-strategy-envelope-2026-09-04.md) |
| 34 | T34 | 聊天工作台可视化与三子栏复用（chat-workbench-visualization-tabs） | T33 | completed | - | [plan](plans/T34-chat-workbench-visualization-tabs-2026-09-04.md) |
| 35 | T35 | Agent 预测与 What-if 场景闭环验收（agent-prediction-scenarios-acceptance） | T31、T32、T33、T34 | completed | - | [plan](plans/T35-agent-prediction-scenarios-acceptance-2026-09-04.md) |

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
- [x] todo.md 由 docs/todo.json 导出；任务状态、依赖和计划路径以 JSON 为准
- [x] 每任务验收标准至少含 1 条可运行验证项
- [x] 本次计划已逐条评审通过，未决策略来源和 What-if 请求字段已收口
