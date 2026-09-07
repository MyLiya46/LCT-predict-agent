# T35 · Agent 预测与 What-if 场景闭环验收（agent-prediction-scenarios-acceptance）

- 任务 ID：T35
- 标题与目标：用离线 mock、真实 backend/icewash/PG 和浏览器页面验证四类聊天请求都桥接到工作台能力并输出正确的三子栏。
- 关联文档章节：`docs/feat-icewash.md` §3、§4、§10.2、§11.2；T30、T31、T32、T33、T34
- 前置依赖 blockedBy：T31、T32、T33、T34

## 执行画像

- execution_mode：direct
- execution_class：e2e
- expected_duration：约 60 分钟
- external_waits：PG、backend、icewash model、frontend、可选真实 LLM
- checkpoint_phases：计划校验、离线回归、服务健康、四类聊天请求、页面复核
- resume_boundary：从最后一个未通过的验收场景继续，不重复已通过场景

## 问题

- 单个工具或单个页面构建通过，不能证明 Agent 没有把预测请求误路由为 history，也不能证明预测结果和归因结果都进入最终报告与图表。
- What-if 的模型结果、策略矩阵、六个月累计 KPI 和聊天三子栏跨 backend、icewash、frontend 三层，必须在同一真实会话中验证字段和口径。
- 真实价格/成本覆盖或库存数据不足时，系统应明确显示缺失状态，不能因验收数据缺失而把金额、毛利或周转天数默认为 0/固定数值。

## 决策

- 以 T31–T34 的结构化契约为验收真值：工具序列决定能力，PG/model 结果决定数字，backend projection 决定 envelope，frontend 只负责复用展示。
- 四类固定场景：
  1. `查询冰箱近半年销售情况`：history，分析解读/历史趋势图/数据表。
  2. `预测洗衣机未来3个月销量`：先验证缺少 `forecast_month` 时返回结构化 `need_input` 或用户可理解的补充月份请求；再发送带明确“以 YYYY-MM 为基准”的同义请求，必须出现 `submit_forecast/get_forecast_result`，输出分析解读/预测曲线/数据表。
  3. `预测洗衣机以 YYYY-MM 为基准的 TOP5 型号销售趋势并分析`：forecast + attribution，报告引用预测 TOP5 和归因因子，图表包含预测曲线与至少一个白盒 waterfall，数据表包含预测明细。
  4. `帮我制定冰箱下月销售计划` 与 `如果我把冰箱主销型号降价8%，之后会怎么样`：分别走 optimize/simulate，输出策略矩阵、累计达成趋势和分析解读。
- 外部验收只读已有完整预测/归因版本时优先使用 `冰箱`；不为外部验收新建预测任务或上传文件，缺少洗衣机版本时将该外部场景记为 `external_blocked`，由离线 mock 覆盖工作流，不清理 PG、不提交 git。
- 外部 LLM 凭据不可用时，使用固定 tool-call mock 完成离线闭环；真实 LLM 场景单独记录为外部环境结果，不覆盖离线通过状态。

## 范围

- 包含：plan/state 校验、backend 定向回归、model 编译、frontend 构建、seed 同步、真实健康检查、认证聊天 SSE/envelope、Attribution/What-if 页面加载和四类结果核对。
- 不包含：生产部署、git commit/push、预测模型公式重写、价格/成本/库存源数据补录。

## 环境预检

- 必需 Shell：git-bash
- 必需命令：`python`、`backend/.venv/Scripts/python.exe`、`npm`、`curl`
- 必需端口：8000（backend）、8001（icewash model）、5173（frontend）
- 必需 URL：`http://127.0.0.1:8000/healthz`、`http://127.0.0.1:8001/health`、`http://127.0.0.1:5173/workbench/attribution`、`http://127.0.0.1:5173/workbench/what-if`
- 必需 Python 模块：pytest、sqlalchemy、httpx、fastapi、numpy
- 模块检查解释器：backend/.venv/Scripts/python.exe；model 使用 services/icewash-model/.venv/Scripts/python.exe
- 必需 Docker 容器：无
- 容器内必需命令：无
- 容器内必需 Python 模块：无
- 执行画像：e2e
- 启动超时（秒）：30
- 空闲超时（秒）：60
- 硬截止（秒）：600
- 最大 checkpoint 间隔（秒）：60
- 预检命令：
  ```bash
  python C:/Users/jie32.guo/.codex/skills/plan-generator/scripts/preflight.py check --plan docs/plans/T35-agent-prediction-scenarios-acceptance-2026-09-04.md --format json
  ```

## 风险与回滚

- 风险：PG、模型服务、LLM 网关或认证 token 不可用会阻断外部场景；真实数据价格/成本覆盖不完整会使金额/毛利为 null；浏览器构建环境差异会影响页面检查。分别记录 offline、external_blocked 和 external_pass，不修改业务数据。
- 回滚：验收步骤只读，失败时从最后一个场景重跑；如需恢复 schema，使用 T31–T34 各自的兼容分支，不执行数据库清理、不删除模型任务、不回滚 T22–T30 的迁移。

## 实施步骤

### 步骤 1：校验计划、依赖和离线回归

- 对象：T31–T35 计划、canonical JSON 状态拓扑、backend/model/frontend 定向测试。
- 动作：运行 state validate、每个新增计划 lint、Agent workflow/projection/What-if 测试、模型编译和 frontend build。
- 参数：新增任务在执行前为 `reviewed`；要求覆盖 history、forecast、forecast+attribution、optimization、simulation、缺价/缺成本/库存不可用；不修改 T01–T30 状态。
- 核心修改文件：`backend/tests/test_agent_forecast_workflow.py`、`backend/tests/test_chat_forecast_projection.py`、`backend/tests/test_chat_whatif_projection.py`
- 必要集成文件：`frontend/src/types.ts`、`frontend/src/components/MessageResultCard.tsx`
- 命令：
  ```bash
  python C:/Users/jie32.guo/.codex/skills/plan-generator/scripts/plan_state.py validate --state "$(find docs -maxdepth 1 -type f -name '*.json' -print -quit)"
  for plan in docs/plans/T31-agent-forecast-attribution-workflow-2026-09-04.md docs/plans/T32-chat-forecast-attribution-envelope-2026-09-04.md docs/plans/T33-chat-whatif-strategy-envelope-2026-09-04.md docs/plans/T34-chat-workbench-visualization-tabs-2026-09-04.md docs/plans/T35-agent-prediction-scenarios-acceptance-2026-09-04.md; do python C:/Users/jie32.guo/.codex/skills/plan-generator/scripts/plan_state.py lint-plan --plan "$plan" || exit 1; done
  cd backend && uv run pytest -q tests/test_agent_forecast_workflow.py tests/test_chat_forecast_projection.py tests/test_chat_whatif_projection.py tests/test_chat_envelope.py tests/test_capability_tools.py tests/test_icewash_whatif_contract.py
  python -m py_compile ../services/icewash-model/cbg_fcst_month/server.py ../services/icewash-model/cbg_fcst_month/whatif.py
  cd ../frontend && npm run build
  ```

### 步骤 2：执行服务健康、seed 和只读数据预检

- 对象：backend seed、backend/icewash/frontend 运行态和已有 PG 预测版本。
- 动作：同步 `sales_query_predict` 工具 schema；检查三服务健康；确认至少一个品类存在完整 forecast/attribution 版本和六个月 What-if baseline；不触发新预测、不修改源数据。
- 参数：工具 seed 重复执行两次仍保持幂等；优先品类 `冰箱`；认证 token 通过环境变量 `AGENT_TEST_JWT` 提供，不把 token 写入计划、日志或消息。
- 核心修改文件：`backend/seed/v2__icewash_tools.py`
- 必要集成文件：`backend/src/app/api/chat_facade.py`、`backend/src/app/services/whatif_workbench.py`
- 命令：
  ```bash
  cd backend && .venv/Scripts/python.exe -m app.seed_icewash_tools && .venv/Scripts/python.exe -m app.seed_icewash_tools
  curl -fsS http://127.0.0.1:8000/healthz
  curl -fsS http://127.0.0.1:8001/health
  curl -fsS http://127.0.0.1:5173/workbench/attribution
  curl -fsS http://127.0.0.1:5173/workbench/what-if
  ```

### 步骤 3：验证四类聊天结果和工具序列

- 对象：`POST /api/chat/stream` 的 status/result/done、Message envelope、tool trace 和前端 ChatPanel。
- 动作：使用认证 token 逐一发送固定问题及一次缺月份输入契约请求；记录实际 tool.call/tool.result 顺序和 result envelope，检查 tabs、图表 cards、表格行和分析文字的证据来源。
- 参数：每个独立场景只创建一个临时 session；SSE 必须包含 `status → result → done`；补充明确基准月后，forecast 3 个月结果必须含 3 个预测期；TOP5 请求必须含同一预测版本的 forecast 与 attribution 证据；What-if 结果必须含 `strategy_dashboard` 两类 card，simulate 还必须记录 `get_whatif_strategies → simulate`；失败时保留原始错误响应供诊断。
- 核心修改文件：`backend/tests/test_agent_prediction_scenarios.py`、`frontend/src/components/MessageResultCard.tsx`
- 必要集成文件：`backend/src/app/api/chat_facade.py`、`backend/src/app/services/chat_envelope.py`
- 命令：
  ```bash
  test -n "${AGENT_TEST_JWT:-}" || { echo "AGENT_TEST_JWT is required" >&2; exit 2; }
  [[ "${AGENT_TEST_FORECAST_MONTH:-}" =~ ^[0-9]{4}-(0[1-9]|1[0-2])$ ]] || { echo "AGENT_TEST_FORECAST_MONTH=YYYY-MM is required" >&2; exit 2; }
  auth=(-H "Authorization: Bearer ${AGENT_TEST_JWT}" -H 'Content-Type: application/json')
  curl -fsS -N "${auth[@]}" -X POST http://127.0.0.1:8000/api/chat/stream --data '{"message":"预测洗衣机未来3个月销量","session_id":null,"params":{}}' || exit 1
  washing_version="AG_洗衣机_${AGENT_TEST_FORECAST_MONTH}"
  if command -v psql >/dev/null 2>&1 && [ "$(psql agent_platform -Atqc "SELECT EXISTS (SELECT 1 FROM fcst_forecast_result f JOIN fcst_attribution a ON a.system_forecast_number=f.system_forecast_number WHERE f.system_forecast_number='${washing_version}' AND f.category='洗衣机' AND a.category='洗衣机')")" = "t" ]; then
    curl -fsS -N "${auth[@]}" -X POST http://127.0.0.1:8000/api/chat/stream --data "{\"message\":\"预测洗衣机以 ${AGENT_TEST_FORECAST_MONTH} 为基准未来3个月销量\",\"session_id\":null,\"params\":{}}" || exit 1
    curl -fsS -N "${auth[@]}" -X POST http://127.0.0.1:8000/api/chat/stream --data "{\"message\":\"预测洗衣机以 ${AGENT_TEST_FORECAST_MONTH} 为基准的TOP5型号销售趋势并分析\",\"session_id\":null,\"params\":{}}" || exit 1
  else
    echo "external_blocked: no complete washing-machine version ${washing_version}; offline mock remains required" >&2
  fi
  curl -fsS -N "${auth[@]}" -X POST http://127.0.0.1:8000/api/chat/stream --data '{"message":"查询冰箱近半年销售情况","session_id":null,"params":{}}' || exit 1
  curl -fsS -N "${auth[@]}" -X POST http://127.0.0.1:8000/api/chat/stream --data '{"message":"帮我制定冰箱下月销售计划","session_id":null,"params":{}}' || exit 1
  curl -fsS -N "${auth[@]}" -X POST http://127.0.0.1:8000/api/chat/stream --data '{"message":"如果我把冰箱主销型号降价8%，之后会怎么样","session_id":null,"params":{}}' || exit 1
  ```

### 步骤 4：核对数据口径与回归边界

- 对象：What-if baseline/optimization 结果、聊天 envelope 和工作台页面。
- 动作：对比聊天 summary 与 `/api/whatif/baseline` 的六个月全量汇总；确认价格/成本缺失显示 null/status，库存显示 unavailable/reason；确认工作台 Attribution 曲线和聊天 forecast curve 使用相同预测起点和归因因子。
- 参数：销量、销售额分别比较目标和达成；策略矩阵行数等于型号数；表格分页不能改变 summary；不把页面固定回退标签当作真实库存周转天数。
- 核心修改文件：`backend/tests/test_agent_prediction_scenarios.py`、`backend/tests/test_chat_whatif_projection.py`
- 必要集成文件：`backend/src/app/services/whatif_workbench.py`、`frontend/src/pages/AttributionPage.tsx`、`frontend/src/pages/WhatIfPage.tsx`
- 命令：
  ```bash
  cd backend && uv run pytest -q tests/test_agent_prediction_scenarios.py tests/test_chat_whatif_projection.py
  cd ../frontend && npm run build
  ```

## 完成标准

- 验收类型：mixed
- 离线验收命令：
  ```bash
  python C:/Users/jie32.guo/.codex/skills/plan-generator/scripts/plan_state.py validate --state "$(find docs -maxdepth 1 -type f -name '*.json' -print -quit)"
  backend/.venv/Scripts/python.exe -m pytest -q backend/tests/test_agent_forecast_workflow.py backend/tests/test_chat_forecast_projection.py backend/tests/test_chat_whatif_projection.py backend/tests/test_chat_envelope.py backend/tests/test_capability_tools.py backend/tests/test_agent_prediction_scenarios.py
  python -m py_compile services/icewash-model/cbg_fcst_month/server.py services/icewash-model/cbg_fcst_month/whatif.py
  cd frontend && npm run build
  ```
- 外部环境验收命令：
  ```bash
  curl -fsS http://127.0.0.1:8000/healthz
  curl -fsS http://127.0.0.1:8001/health
  curl -fsS http://127.0.0.1:5173/workbench/attribution
  curl -fsS http://127.0.0.1:5173/workbench/what-if
  ```
- 通过条件：离线命令全部通过；真实或 mock 聊天中历史/预测/预测归因/优化/模拟工具序列符合契约；预测和 What-if 结果均显示分析解读、可视化图表、数据表；预测图包含预测曲线，含归因时包含白盒 waterfall；策略结果包含每型号 Agent 建议策略和累计达成趋势；六个月总量、销售额、毛利和库存缺失状态与 T22–T30 口径一致。
