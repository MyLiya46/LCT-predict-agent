# 冰洗预测模型接入通用智能体框架 — 最终方案（feat-icewash）

> 日期：2026-08-31

---

## 1. 核心目标

独立运行的 icewash 预测模型接入通用 agent 框架，暴露 **history / forecast / explain / simulate / optimize** 五个 capability；前端**双入口**；simulate/optimize 走**规则式**（引擎归 `services/icewash-model`，backend 仅 taskid 转发）；数据分两层——**history / forecast / explain 落 PG 中转（只读持久）**，**simulate / optimize 走 taskid 直连异步**；前端按 **`response_type` 约定**分派渲染器（首期不建 `service_model` 实体）。

**触发**：用户以自然语言描述需求（查历史/看预测/问原因/调策略/求目标销量），LLM 规划 → internal 工具 → SSE 推送 → 前端按 `response_type` 渲染。

### 1.1 双入口

1. **工作台入口**（业务用户/分析师）：直连 icewash-model，传统系统交互（筛选/表格/图表）。以 `frontend-ref` 的 WorkbenchPage 为交互参考，在 `frontend/` 原地实现；能力域 `/api/workbench/*`、`/api/whatif/*`、`/api/attribution/*`、`/api/forecast/*`。
2. **聊天入口**（非业务用户）：LLM 桥接用户 ↔ 模型接口（意图分析、默认字段、对话记忆）。以现有 engine 循环为底座，参考 ref 的槽位/意图/报告服务的意图，在 `backend/` 原地实现并入。

两入口共用同一数据与模型层（icewash-model + PG）。

---

## 2. 能力现状 → 决定

| 能力 | 现状 | 决定 |
| --- | --- | --- |
| history | 已产出（pipeline.py:360 `history_results`） | PG 中转只读（T51） |
| forecast | 已产出（pipeline.py:362） | PG 中转只读（T52） |
| explain | 已产出（pipeline.py:352 `WhiteboxAttributor`） | forecast 并列产物，**异步**，落 PG 中转 + 报告 |
| simulate | 零实现（predictor.py:68-93） | **规则式**：icewash 新增 `whatif.py`（`STRATEGY_CATALOG` 8 条策略 + 弹性系数经验公式），backend 仅转发 |
| optimize | 零实现（`new_old_product_optimizer.py` 非逆向优化） | **规则式**：复用 icewash `whatif.py`，`STRATEGY_CATALOG` 作候选空间逐条 simulate 取最优 |
| 前端分派 | `card_type: line/bar/table` 硬编码（DashboardCards.vue:33） | `response_type` → 渲染器注册表 |

---

## 3. 能力细化

### 3.1 history

用户描述品类+时间 → `get_history` → 前端历史看板。数据路径：CSV 离线灌 `fcst_history`（T50 `pg_sync_history.py`）→ `query_history` → 工具 → SSE。契约：`GET /chat/history?category&sku&channel&start&end`。

### 3.2 forecast

用户描述品类+时间 → `submit_forecast`（taskid）→ `get_task_status` 轮询 → `get_forecast_result` 读 PG → 预测看板。契约：`GET /chat/forecast/{sn}?horizon=`。

### 3.3 explain（与 forecast 绑定）

- 归因随 forecast 一并异步产出；产物两层：summary（类型级占比，走 SSE）与 factors（SKU×渠道×月×Top10 因子明细，按需下钻）。
- 落库：`fcst_attribution` 中转表。
- **报告**：template + LLM 生成 → SSE 正文 markdown 流 + 落 `Message.content` 可导出（复用 message.py:40 + export_trace_markdown，不新建表/机制）。样例：`services/icewash-model/冰箱预测分析报告_202608.md`、`洗衣机预测分析报告_202608.md`。需要在后端建好`template.md`。

### 3.4 simulate（规则式，引擎归 icewash）

- **规则引擎落在 icewash**：新增 `services/icewash-model/cbg_fcst_month/whatif.py`——`STRATEGY_CATALOG`（维持现状/降价促销/加大投流/以旧换新/赠品促销/套购/提前铺货/清仓退市，各带经验公式如 `%ΔQty = Ed × |ΔP|`）+ `simulate_row()` 演算公式（Python 版）。baseline（最终预测值/计划价/弹性系数）就近读 icewash 当前预测产物。
- **backend 只做胶水**：LLM 解析「调价格/策略」→ `POST /simulate` 拿 taskid → 轮询 → 结果进 PG/SSE → 前端对比看板。backend 不重复维护策略目录与公式。
- 精度限制：弹性系数+经验 lift 近似（非 LGBM 重推）。
- 升级路径（备用）：模型侧「可拨变量契约 + 特征重推入口」作为后续增强；因引擎本就在 icewash 内，升级只改 icewash 内部、taskid 契约不变，backend 零改动。

### 3.5 optimize（规则式，引擎归 icewash）

给定目标销量 → icewash `/optimize`（taskid）内复用 `whatif.py` 的 `STRATEGY_CATALOG`（按 statuses 过滤）逐条 simulate → `argmin|销量-目标|` 返回最优策略 + 对应销量。候选空间与演算公式单一事实来源（`whatif.py`）；参数可调（降价幅度 %），baseline/elasticity 映射已就绪。backend 仅转发 taskid。

---

## 4. 前端 response_type 分派

> 参考图 `docs/example/前端数据看板-预测归因.png`（SKU 列表+曲线+标签+依据切换）、`前端数据看板-预测报告.png`（指标卡行+叙述正文）。
> ⚠ 图内统计口径（稳定型/趋势型/间歇型/稀疏型/衰退型/新品、WAPE、零值率、CV、非零期、月均、消基期、近6期移动平均、MA6）在 icewash 现有代码**零命中**（grep 验证）——带 ⚠ 数据列 = 需模型侧新增（§9 第 3 项）；图仅取交互形态。

### 4.1 response_type → 渲染器映射

| response_type | 触发工具 | 渲染组件 | 数据列 |
| --- | --- | --- | --- |
| `history` | `get_history` | HistoryCard | 已有：月份/品类/3级渠道/型号/数量 |
| `forecast` | `get_forecast_result` | ForecastCard | 已有：预测期/预测月份/品类/系列/状态/3级渠道/型号/最终预测值 |
| `attribution` | `get_attribution` | AttributionCard | 已有：归因类型/影响因子/影响量_台/影响占比/因子当期值 |
| `report` | `get_attribution` | ReportCard | ⚠ 需模型侧新增统计口径 |
| `simulation` | `simulate` | SimulationCard | 模拟销量序列 + 变量变更说明 |
| `optimization` | `optimize` | OptimizationCard | 策略名/变量值/模拟销量/离目标差 |


### 4.2 渲染器注册表

- 新增 `frontend/src/components/response/registry.ts`：`Record<ResponseType, Component>` + `resolveRenderer(type)`（React 版）。
- 主链路（ConversationView / DashboardCards）只调 `resolveRenderer(type)`，不感知具体组件；新类型 = 一个 .tsx + 注册一行。

### 4.3 渲染器规格（ECharts）

- React 侧用 echarts-for-react 按需 import（LineChart/BarChart/CustomChart + Grid/Tooltip/Legend），**不引新依赖**；复用 Chart / RealtimeTable / Markdown 组件（React 侧重写）。
- AttributionCard（图一）：左 SKU 列表（搜索+分类 Tab+表格）→ 右预测曲线卡（多序列）+ 顶部「分类/型号/指标」标签行 + 底部「预测依据」切换组（⚠ 候选需模型侧）。
- ReportCard（图二）：顶部指标卡行（⚠ 全部口径需模型侧）+ LLM 叙述 markdown 正文。

### 4.4 归因交互分层

- 上层：类型级 summary → SSE `tool.result` 推（瀑布 bar）。
- 下层：因子明细不随 SSE；前端点击行/类型 → 复用已加载 rows 前端过滤【假设：数据量可控时优先，避免增接口面】。
- 报告：`report` 类型，LLM 依 template + summary 生成 → SSE markdown 流 + 落 `Message.content`。

---

## 5. 改动文件清单

### backend（`backend/src/app/`）

| 文件 | 动作 | 职责 |
| --- | --- | --- |
| `models/fcst_relay.py` | 改 | T49 两表之上新增 `FcstAttribution` |
| `alembic/versions/0003_fcst_relay.py` | 改 | 迁移补归因表 |
| `tools/internal/{submit_forecast,get_task_status,get_forecast_result,get_history}` | 新 | T53 4 工具（沿用） |
| `tools/internal/{get_attribution,simulate,optimize}` | 新 | 3 新工具（explain 读 PG；simulate/optimize 走 taskid 直连） |
| `tools/dashboard_spec.py` | 改 | 白名单 + `build_attribution_spec` 等 |
| `domain/chat_service.py` | 改 | 新增 `query_attribution` |
| `api/chat.py` | 改 | 只读路由 + 新增 `GET /attribution` |
| `api/auth.py` + `models/user.py` | 改 | `/oauth-login` + `users.oa` 列（§12.1） |
| `models/conversation.py`、`models/message.py` | 改 | 加列 memory/slots/envelope（§12.2） |
| `config.py` + `.env.example` | 改 | `ICEWASH_BASE_URL`、`OAUTH_*`（两处同步） |


### icewash（`services/icewash-model/cbg_fcst_month/`）

| 文件 | 动作 | 职责 |
| --- | --- | --- |
| `server.py` | 改 | `task_store` 持久化（内存 → SQLite/本地文件，server.py:34-35）；新增 `/whatif/strategies`、`/simulate`、`/optimize` 端点 |
| `whatif.py` | 新 | simulate/optimize 规则引擎（策略目录 + `simulate_row` 演算 + optimize 逐条 argmin 搜索）——策略目录单一事实来源 |
| `main.py` | 改 | 归因落库写入（return 前追加）；统计模块挂接 |
| `stats_module.py` | 新 | 统计口径模块（§9）：A 类导出 + B 类派生 + WAPE 近似，SQU→SKU 聚合分类 |
| `pg_sync_history.py` | 新 | 历史 CSV 灌库（T50） |


参照 `services/冰洗预测模型`（与 icewash-model 内容一致），仅作基准视图，只读不动。

### 前端（React 原地重建后，以 ref 结构为参考）

| 文件 | 动作 | 职责 |
| --- | --- | --- |
| `frontend/`（React 重建） | 重建 | 以 `frontend-ref` 为结构参考，React 18 + Tailwind + zustand + echarts-for-react（11 页 + 10 组件）原地实现 |
| `src/components/Registry.tsx` | 新 | response_type → 渲染器注册表（React 版） |
| `src/components/*ResponseCard.tsx` | 新 | 六类渲染器（Attribution/Report/Simulation/Optimization…，或直接扩展 MessageResultCard） |
| `src/stores/trace.ts`（React 版） | 重写 | `stores/trace.ts` Vue 版重写；LiveTailView / ThinkingChain 及 `views/chat/trace/` 5 组件一并重写（§10.1 增量 1） |
| `src/views/admin/*`（React 版） | 迁移 | 管理端六页：AdminLayout / Users / Tools / Datasources / LLM / Audits / Config（§10.1 增量 2，契约对齐现有 `/admin/*` 路由） |
| echarts 接入 | 沿用 | 零新增注册（ref 用 echarts-for-react，按需 import） |


---

## 6. 接缝

**复用**：SSE hub + `tool.result`；trace `append_event`；`_execute_internal_tool`；`build_dashboard_spec` 白名单；`to_uni` + `require_perm`；`IdMixin`；DashboardCards/Chart/RealtimeTable/Markdown；`Message.content` + `export_trace_markdown`（报告导出，不新建表）。

**新建**：`fcst_attribution` 转表、7 个 internal 工具、前端注册表 + 6 渲染器、icewash `task_store` 持久化 + **whatif 规则引擎**（策略目录/演算/优化搜索）、五能力域（workbench/whatif/attribution/forecast/chat 桥）在 backend 原地实现（§11.2）。

**不新建**：渲染框架、工具注册机制、SSE 协议、鉴权体系、LLM 抽象、ECharts 图型注册。

**单一事实来源**：simulate/optimize 的策略目录与演算公式押 icewash（`whatif.py`），backend 与前端工作台的下拉选项、LLM 解析均从 `/whatif/strategies` 读取，不各维护一份。

---

## 7. 边界与异常

- 空数据：history/forecast/attribution 空 → 空 items，前端不渲染。
- 失败：icewash 不可达 → 工具 `{ok:False, error}`，不抛未捕获异常。
- 越权：只读 `require_perm("chat:read")`；simulate/optimize 提交需 `chat:send`。
- 并发：`task_store` 持久化保留线程锁写；不违背单 worker 语义。
- task 跨重启：持久化后可恢复。
- 报告双写一致性：SSE 正文与 PG 落库同一份；断连经 list_messages/trace 导出兜底。
- 渲染器缺失兜底：`resolveRenderer` 未命中 → 降级 T44 `line/bar/table` 渲染，不白屏；⚠ 口径未到 → 报告区骨架占位「统计口径待续」。

---

## 8. 验收标准

- [ ] forecast 后 `fcst_attribution` 有归因行，字段对齐中文列映射。
- [ ] `GET /attribution` + `get_attribution` 返回归因 rows；「冰箱7月销量为什么涨」→ 前端归因看板。
- [ ] 报告 markdown 流经 SSE 推送 + 落 `Message.content` 可导出；导出一致。
- [ ] simulate：提交 → taskid → 前端转圈 → 轮询 `GET /tasks/{id}` → 结果；icewash 重启后任务仍在。
- [ ] optimize：给定目标 → 逐条 simulate → 最优策略 + 销量。
- [ ] `response_type` 注册表：新类型只加渲染器 + 注册一行。
- [ ] `icewash.enabled=false`：mock 2 工具照常（T54 并存不破坏）。
- [ ] response_type 前端：attribution / report 呈现图一/图二形态。
- [ ] ECharts 零新增：`git diff` 中 `plugins/echarts.ts` 无 `echarts.use` 新增项。
- [ ] OA 登录（§12.1）、聊天归一（§12.2）、SSE 适配（§12.3）各自验收见对应小节。

---

## 9. 统计口径（已决：icewash 内新增统计模块）

> 口径原料在 pipeline 内基本已存在（CV/均值/MA 方法/趋势/状态/可预测性均已算），缺的是「SQU 级 → SKU 级」的聚合、分类与导出——新增模块即可满足，非新增计算。

- **[模型侧，已解除] 可拨变量契约** —— 规则式取代；仅作「模型真重推」升级路径保留。
- **[模型侧，已解除] optimize 优先级表** —— `STRATEGY_CATALOG` 即为搜索空间。
- **统计口径模块**（新，icewash `cbg_fcst_month/` 内，pipeline 出口挂接）：
  - 口径归类（已核实）：
    - **A 已有**：MA6 依据（`method:MA`）、月均/CV/波动（`qty_lag{3,6,12}m_{mean,cv,std,skew,kurt}` 特征列）、近3月均/去年同期（`term_3m_mean`/`term_lag12`）、方法占比（`method`/`baseline_model`）、近期趋势（`delta_y`）；
    - **B 可派生**：零值率、非零期（历史 rows 按 SKU 计数）、SKU 构成分类（`status`/`eol_ratio` + CV + `predictability_checker` 组合判据）；
    - **C 真正新计算（仅 1 项）**：WAPE 交叉验证——需「预测 vs 实际」成对回测；现仅训练期 `pred_bias`，以**训练期回测近似**【假设】，真回测口径待模型侧确认后升级。
  - 产出：每项「字段名 + 层级（批次/SKU/型号×渠道）」；模块输出对 report/attribution 卡片及 LLM 报告正文可用。
  - **待模型侧拍板项（低风险）**：SKU 分类阈值（稳定/趋势/间歇/稀疏界限），先用默认值【假设】，配置化可调。
- **不作为阻塞**：history/forecast 可先落地；报告区以骨架占位，统计模块到位后填充。

---

## 10. 代码合并策略

> 备份/参考目录统一在 `reference_repo/predict-agent/`：`frontend-ref`（React 完整工作台）、`frontend-backup`（Vue dist 产物）、`backend-ref`（独立 FastAPI 冰洗平台）、`backend-backup`（与现有 backend/ **逐字节一致**，`diff -rq` 零输出已核实）。
>
> **`reference_repo/` 全部四个目录只作写代码参考，永不 import / 直接引用其中的代码与文件**；所有实现重新落到根目录无后缀 `backend/`、`frontend/` 与 `services/icewash-model/`。

### 10.1 前端：以 ref 为参考原地重建 + 两项增量（trace 重写、管理端六页迁移）

- **主体以 ref 为结构参考**：`frontend-ref`（React 18 + Tailwind + zustand + echarts-for-react）在 `frontend/` 原地重建（11 页 + 10 组件，含 Workbench/Chat/Attribution/WhatIf 及 `processSteps` 可折叠思考链，参考 [ChatPanel.tsx:675-722](reference_repo/predict-agent/frontend-ref/src/components/ChatPanel.tsx#L675-L722) 的交互意图）。
- **增量 1 · trace（重写为 React）**：现有 Vue 实现 8 文件（`stores/trace.ts`、`views/chat/LiveTailView.vue`、`ThinkingChain.vue`、`views/chat/trace/` 下 TraceDetailDrawer/TraceEventItem/TraceMetricBar/TraceTimeline/TraceTurnGroup 5 组件，均 T46~T48 已实现并 A 暂存）**以 React 重写**。增量内容：事件级追溯（tool.call/tool.result 全链，ref 无）、还原/导出（getTrace / export markdown，ref 无）、LiveTail 实时气泡、诊断指标与时间轴（ref 思考链仅覆盖 agent.status 之面）。
- **增量 2 · 管理端六页（迁移为 React）**：现有 Vue 实现 7 文件（`views/admin/`：AdminLayout / Users / Tools / Datasources / LLM / Audits / Config）迁为 React；无 React 现成版（已核实 ref 无 admin 页、reference_repo 无 admin 前端源码）。功能与 API 契约对齐现有 `/admin/*` 路由，不重新设计。
- **其余**：T34~T48 其余 UX 计划需重排（trace 相关已入增量，其余延期/作废待定）。

### 10.2 后端：现有 backend 为壳，以 backend-ref 为参考原地实现

- 壳不变：现有 `backend/`（PG 17 表 RBAC / JWT 双令牌 / 沙箱 / 工具注册 / SSE / 追溯，52 测试）。
- ref 增量并入（`backend-ref`）：

  1. 工作台：`workbench.py` → `/workbench/*` 只读路由（表入 PG，`fcst_*` 命名【假设】）；
  2. whatif 转发：backend 仅加 simulate/optimize 的 taskid 直连转发（internal 工具 + `/whatif/strategies` 代理读 icewash）；规则引擎归 icewash（§3.4/§3.5），不并入 backend；
  3. attribution 工作台：`attribution_workbench.py`（Excel 灌库）→ `fcst_attribution`；
  4. forecast run 管理：`forecast_model_client.py` + `forecast_excel_adapter.py` + `forecast_ingest.py`（taskid + Excel 抽取）→ icewash 直连 + PG 落库；
  5. chat 桥：`intent.py`/`forecast_agent.py`/`request_analyzer.py`/`result_insight.py` 槽位规则层并入现有 engine（前置槽位/意图解释），不替换 LLM 循环。
- 不并入：现有 engine loop、sandbox daemon、17 表 RBAC、trace、SSE 协议；ref 的 `turing_client.py`/`oauth_client.py`（接入点改为 §12.1 OA 换 JWT）/`analysis_agent.py`/`mcp_adapter/`。

### 10.3 冰洗模型

`services/冰洗预测模型` 为基准视图（只读）；改动一律落 `services/icewash-model/`（§5）。

### 10.4 验收补充

- [ ] `diff -rq reference_repo/predict-agent/backend-backup/src backend/src` 零差异（壳未漂移，首期执行）。
- [ ] 前端为 React 工程，`npm run build` 通过；Vue 功能点在 React 侧有页面/路由点位。
- [ ] `/workbench/*`、`/whatif/*`、`/attribution/*`、`/forecast/*` 路由可用。
- [ ] simulate 规则式全链：「选策略 → 调参 → 出对比图」。

---

## 11. 制度性冲突决定

### 11.1 认证：OA 换 JWT

- 新增 `POST /auth/oauth-login {oa}`：`fetch_access_token` 向 TCL 网关验证 → 按 oa 在 `users` 表关联/建用户 → 签发现有双令牌 JWT → 全链路走现有 RBAC/审计/吊销。
- 改动：`api/auth.py` 路由；`users.oa` 列（可空唯一，Alembic 0004【假设】）；`auth_service.login_by_oa`；`src/app/auth/oauth.py` 在 backend 原地实现（参考 ref `oauth_client.py` 的验证意图，不搬文件）【假设】；`config.py`+`.env.example` 补 `OAUTH_BASE_URL/OAUTH_TOKEN_PATH/OAUTH_CLIENT_ID/OAUTH_CLIENT_SECRET`；前端 `LoginPage.tsx` 调 `/api/auth/oauth-login`。
- 边界：网关不可达 → 非 500 明确 message；建用户失败 → 整体失败可重试（事务）；登录成功/失败均 `write_audit`。
- 验收：OA 账号 200 返双令牌 + `/auth/me` 通；二次登录不重复建用户；网关不可达非 500；email+password 零回归（52 测试）。

### 11.2 存储：并入 PG + 聊天归一

- ref 能力域表全部入 PG（`workbench_dataset_rows`/`attribution_analysis_rows`/`forecast_history_rows`/`whatif_scenarios`/`forecast_runs`/`forecast_points`/`attribution_results`，`fcst_*` 命名【假设】；与现有 17 表零同名已核实）。迁移 `0004_workbench_relay`。
- **聊天域不新表**：ref `chat_sessions`/`chat_messages`/`session_memory_chunks`/`mcp_call_logs` 废弃；`memory_summary/memory_slots/result_envelope` 加列并入 `conversations`/`messages`（保留 owner 隔离/幂等/trace/状态机；记忆语义迁移到 conversations 加列）。

### 11.3 SSE：附录 A 为底座 + 薄适配层

- 底座不变：`sse/events.py` 11 事件 + `{seq, event, payload}` 结构（payload 可挂 dashboard_spec/envelope）。
- ref 四事件（status/result/done/error）**服务端不实现**；ref 前端 `api.ts:118-184` fetch+getReader 做事件名映射：`status→agent.status`、`result→message.delta+tool.result(附 envelope)`、`done→done`。
- envelope（intent/metrics/table/chart/process_steps）附加在 payload（同 dashboard_spec 位置），React 侧 `MessageResultCard` 直接取；现有 3s 轮询/管理端/追溯不受影响；适配层仅重映射+提取，不做协议转换。
- 验收：React ChatPage 端到端收全（delta 正文/envelope 卡/done）；现有用户端/管理端/trace 零改动；react-markdown 正文+envelope 混排无误。
