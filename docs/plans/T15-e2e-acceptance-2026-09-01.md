# T15 · 端到端验收（e2e-acceptance）

- 任务 ID：T15
- **标题与目标**：在统一 PG 数据源上验收双登录、backup 原生聊天编排、真实 LLM 网关、真实 `services/icewash-model` 五项能力、工作台和管理端；记录每条链路的请求、响应和落库证据。
- **关联文档章节**：`docs/feat-icewash.md` §1、§3、§8、§10.1、§10.2、§11.1、§11.2
- 前置依赖 blockedBy：T04、T05、T06、T10、T11、T12、T13、T14

## 验收边界

1. 所有命令在仓库根目录使用 Git Bash 执行；本计划不使用 PowerShell 命令。
2. PG 初始化唯一使用 `bash scripts/dev_db_pg.sh`。脚本执行前，PostgreSQL 容器名固定为 `LCT-predict-agent-pg`，数据库固定为 `agent_platform`，端口固定为 `127.0.0.1:5432`。
3. 本地验收采用三个固定端口：icewash `127.0.0.1:8001`、backend `127.0.0.1:8000`、frontend `127.0.0.1:5173`。模型容器的 `8002:8000` 映射属于独立 Docker 验收，不与本地验收混用。
4. backend 使用 `backend/.env` 中已配置的真实 `AGENT_API_KEY`、`AGENT_API_URL`、`ICEWASH_BASE_URL=http://127.0.0.1:8001` 和 `FORECAST_MODEL_BASE_URL=http://127.0.0.1:8001`；真实密钥只存在环境文件，不写入命令、日志提交物或报告。
5. `TEST_EMAIL`、`TEST_PASSWORD` 是已由 seed 创建且状态为 `active` 的普通用户；`ADMIN_EMAIL`、`ADMIN_PASSWORD` 是状态为 `active` 且具有 `admin` 角色的用户；`TEST_OA` 是可通过 OA 网关验证的 OA。验收 shell 只从环境变量读取这些值，不把密码或 token 打印到终端。
6. 不在本任务自动执行完整 pytest 套件。pytest 执行范围固定为 T01 的 5 个快速壳测试；完整测试清单先用 `--collect-only` 输出，再由后续测试批次单独选择执行。

## 问题
- 任务 T15 当前需要完成本计划标题对应的交付；旧版计划结构无法被 plan-generator v1.2.0 的结构化校验直接读取。

## 决策
- 保留本计划既有技术边界、参数、实施内容和验收命令；仅补齐 v1.2.0 要求的元数据、章节与结构化执行入口。

## 范围
- 包含：本计划既有实施要点、涉及路径、接口、数据约束和验收项。
- 不包含：改变任务目标、blockedBy 依赖、代码实现或项目业务口径。

## 风险与回滚
- 风险：旧计划正文中的命令或外部服务依赖可能在执行环境中不可用，导致该任务验收失败。
- 回滚：执行前保存本任务涉及文件的补丁；失败时使用 `git apply -R /tmp/T15-plan.patch` 反向应用补丁并恢复前一阶段。

## 实施步骤

### 步骤 1：执行原计划实施内容
- 对象：T15 对应的目标模块、接口和验收对象。
- 动作：按下方保留的原实施内容执行，并使用其中的命令完成验证。
- 参数：严格使用正文中给出的路径、端口、字段、超时、权限和命令参数。
- 文件：docs/plans/T15-e2e-acceptance-2026-09-01.md
- 命令：
  ```bash
  python /c/Users/jie32.guo/.codex/skills/plan-generator/scripts/plan_state.py lint-plan --plan docs/plans/T15-e2e-acceptance-2026-09-01.md
  ```
## 1. 启动和健康检查

#### 1.1 准备 PG、依赖和迁移

在仓库根目录执行：

```bash
set -euo pipefail

docker ps --format '{{.Names}}' | grep -qx 'LCT-predict-agent-pg' || {
  echo 'LCT-predict-agent-pg 未运行；先按 README 创建或启动该容器' >&2
  exit 1
}

cd backend
uv sync
cd ..
bash scripts/dev_db_pg.sh
```

`dev_db_pg.sh` 成功后执行 PG 结构检查：

```bash
pg() { docker exec LCT-predict-agent-pg psql -U app -d agent_platform -Atqc "$1"; }

test "$(pg "SELECT to_regclass('public.workbench_dataset_rows')")" = 'workbench_dataset_rows'
test "$(pg "SELECT to_regclass('public.fcst_forecast_result')")" = 'fcst_forecast_result'
test "$(pg "SELECT to_regclass('public.fcst_attribution')")" = 'fcst_attribution'
test "$(pg "SELECT to_regclass('public.fcst_history')")" = 'fcst_history'
test "$(pg "SELECT to_regclass('public.messages')")" = 'messages'
```

#### 1.2 启动目标模型

目标模型只从 `services/icewash-model/cbg_fcst_month` 启动，不读取、import 或引用已删除的旧模型目录：

```bash
MODEL_LOG=/tmp/lct_icewash_e2e.log
(cd services/icewash-model/cbg_fcst_month && \
  nohup uv run uvicorn server:app --host 127.0.0.1 --port 8001 \
  >"$MODEL_LOG" 2>&1 &)

for i in $(seq 1 30); do
  curl -fsS http://127.0.0.1:8001/health >/tmp/lct_icewash_health.json && break
  sleep 2
done
grep -q 'healthy' /tmp/lct_icewash_health.json
```

模型健康响应必须包含 `status=healthy`。若 60 秒内没有响应，保留 `/tmp/lct_icewash_e2e.log` 并停止验收。

#### 1.3 启动 backend、sandbox daemon 和 frontend

启动前检查 `backend/.env` 中没有旧模型地址，且目标地址为 `http://127.0.0.1:8001`：

```bash
grep -q '^ICEWASH_BASE_URL=http://127.0.0.1:8001$' backend/.env
grep -q '^FORECAST_MODEL_BASE_URL=http://127.0.0.1:8001$' backend/.env
```

然后使用 Git Bash 后台进程启动三个组件：

```bash
BACKEND_LOG=/tmp/lct_backend_e2e.log
FRONTEND_LOG=/tmp/lct_frontend_e2e.log
DAEMON_LOG=/tmp/lct_sandbox_e2e.log

(cd backend && nohup uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 \
  >"$BACKEND_LOG" 2>&1 &)

(cd services/sandbox-daemon && \
  MSYS_NO_PATHCONV=1 PYTHONPATH=src API_INTERNAL_TOKEN=dev_internal_token_001 \
  nohup uv run python -m sd.main >"$DAEMON_LOG" 2>&1 &)

(cd frontend && nohup npm run dev -- --host 127.0.0.1 --port 5173 \
  >"$FRONTEND_LOG" 2>&1 &)
```

等待并检查：

```bash
for url in \
  http://127.0.0.1:8000/healthz \
  http://127.0.0.1:8000/api/health/agent \
  http://127.0.0.1:9000/healthz \
  http://127.0.0.1:5173; do
  curl -fsS --max-time 10 "$url" >/dev/null
done

curl -fsS http://127.0.0.1:8000/api/health/agent | grep -q '"mode"'
```

`/api/health/agent` 必须报告 `mode=live`、`ok=true`；否则不进入真实 LLM 验收。后端、前端、daemon 启动失败时分别检查对应 `/tmp/lct_*_e2e.log`。

## 2. 双登录和权限证据

先设置凭据变量；变量值由验收环境注入，不在命令行和报告中回显：

```bash
: "${TEST_EMAIL:?set TEST_EMAIL}"
: "${TEST_PASSWORD:?set TEST_PASSWORD}"
: "${ADMIN_EMAIL:?set ADMIN_EMAIL}"
: "${ADMIN_PASSWORD:?set ADMIN_PASSWORD}"
: "${TEST_OA:?set TEST_OA}"
export TEST_EMAIL TEST_PASSWORD ADMIN_EMAIL ADMIN_PASSWORD TEST_OA

EMAIL_LOGIN_JSON=/tmp/lct_email_login.json
ADMIN_LOGIN_JSON=/tmp/lct_admin_login.json
OA_LOGIN_JSON=/tmp/lct_oa_login.json

curl -fsS -X POST http://127.0.0.1:8000/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d "$(python -c 'import json,os; print(json.dumps({"email":os.environ["TEST_EMAIL"],"password":os.environ["TEST_PASSWORD"]}))')" \
  >"$EMAIL_LOGIN_JSON"

curl -fsS -X POST http://127.0.0.1:8000/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d "$(python -c 'import json,os; print(json.dumps({"email":os.environ["ADMIN_EMAIL"],"password":os.environ["ADMIN_PASSWORD"]}))')" \
  >"$ADMIN_LOGIN_JSON"

curl -fsS -X POST http://127.0.0.1:8000/api/auth/login \
  -H 'Content-Type: application/json' \
  -d "$(python -c 'import json,os; print(json.dumps({"oa":os.environ["TEST_OA"]}))')" \
  >"$OA_LOGIN_JSON"

EMAIL_JWT=$(python - "$EMAIL_LOGIN_JSON" <<'PY'
import json, sys
print(json.load(open(sys.argv[1], encoding='utf-8'))['data']['access_token'])
PY
)
ADMIN_JWT=$(python - "$ADMIN_LOGIN_JSON" <<'PY'
import json, sys
print(json.load(open(sys.argv[1], encoding='utf-8'))['data']['access_token'])
PY
)
OA_JWT=$(python - "$OA_LOGIN_JSON" <<'PY'
import json, sys
print(json.load(open(sys.argv[1], encoding='utf-8'))['access_token'])
PY
)
OA_TOKEN=$(python - "$OA_LOGIN_JSON" <<'PY'
import json, sys
print(json.load(open(sys.argv[1], encoding='utf-8'))['oauth_access_token'])
PY
)
test -n "$EMAIL_JWT"; test -n "$ADMIN_JWT"; test -n "$OA_JWT"; test -n "$OA_TOKEN"
```

验证 email 和 OA token 的职责分离：

```bash
curl -fsS -H "Authorization: Bearer $EMAIL_JWT" \
  http://127.0.0.1:8000/api/v1/auth/me | grep -q '"email"'
curl -fsS -H "Authorization: Bearer $OA_JWT" \
  http://127.0.0.1:8000/api/v1/auth/me | grep -q '"roles"'

NO_AUTH_CODE=$(curl -sS -o /dev/null -w '%{http_code}' \
  http://127.0.0.1:8000/api/workbench/datasets)
test "$NO_AUTH_CODE" = 401

USER_ADMIN_CODE=$(curl -sS -o /dev/null -w '%{http_code}' \
  -H "Authorization: Bearer $EMAIL_JWT" \
  http://127.0.0.1:8000/api/v1/admin/users)
test "$USER_ADMIN_CODE" = 403
```

## 3. 真实预测聊天主链路

#### 3.0 history 能力

先用同一 email 用户验证 history 工具和工作台真实数据都来自 PG：

```bash
HISTORY_JSON=/tmp/lct_history_chat.json
curl -fsS --max-time 120 \
  -H "Authorization: Bearer $EMAIL_JWT" \
  -H 'Content-Type: application/json' \
  -X POST http://127.0.0.1:8000/api/chat \
  -d '{"message":"查询冰箱历史销量","session_id":null,"params":{}}' \
  >"$HISTORY_JSON"
python - "$HISTORY_JSON" <<'PY'
import json, sys
obj = json.load(open(sys.argv[1], encoding='utf-8'))
env = obj.get('envelope', obj.get('result', {}).get('envelope', {}))
assert env.get('response_type') == 'history'
assert env.get('table', {}).get('rows') or env.get('rows')
PY
```

#### 3.1 通过 stream 入口提交预测

使用 email backup JWT 发起预测；email 模式不把 backup JWT 放入 `access_token`：

```bash
PREDICT_SSE=/tmp/lct_predict_stream.sse
curl -sS --max-time 180 -N \
  -H "Authorization: Bearer $EMAIL_JWT" \
  -H 'Content-Type: application/json' \
  -X POST http://127.0.0.1:8000/api/chat/stream \
  -d '{"message":"预测冰箱2026年8月销量，future 3个月","session_id":null,"params":{}}' \
  >"$PREDICT_SSE"

grep -q '^event: status$' "$PREDICT_SSE"
grep -q '^event: result$' "$PREDICT_SSE"
grep -q '^event: done$' "$PREDICT_SSE"
grep -q '"response_type"' "$PREDICT_SSE"
grep -q '"forecast"' "$PREDICT_SSE"
```

验收器记录 `status → result → done` 顺序，并确认 result 中包含 `session_id`、`message_id`、`envelope.response_type=forecast`、`envelope.table` 或等价预测表。不得出现 `input`、backup JWT、OAuth token 或网关密钥。

#### 3.2 验证模型任务和三张中转表

预测完成后从本次最新模型写入中取得实际版本号，不在计划中硬编码版本：

```bash
FORECAST_SN=$(pg "SELECT system_forecast_number FROM fcst_forecast_result ORDER BY id DESC LIMIT 1")
test -n "$FORECAST_SN"

test "$(pg "SELECT count(*) FROM fcst_forecast_result WHERE system_forecast_number='$FORECAST_SN'")" -gt 0
test "$(pg "SELECT count(*) FROM fcst_attribution WHERE system_forecast_number='$FORECAST_SN'")" -gt 0

ASSISTANT_MESSAGE_ID=$(python - "$PREDICT_SSE" <<'PY'
import json, sys
for line in open(sys.argv[1], encoding='utf-8'):
    if line.startswith('data:'):
        try:
            obj = json.loads(line[5:].strip())
        except json.JSONDecodeError:
            continue
        data = obj.get('message_id') or obj.get('data', {}).get('message_id')
        if data:
            print(data)
            break
PY
)
test -n "$ASSISTANT_MESSAGE_ID"
test "$(pg "SELECT result_envelope IS NOT NULL FROM messages WHERE id='$ASSISTANT_MESSAGE_ID'")" = t
test "$(pg "SELECT count(*) FROM workbench_dataset_rows WHERE dataset='fcst_detail' AND version='$FORECAST_SN'")" -gt 0
```

再用 frontend façade 读取真实数据：

```bash
curl -fsS -H "Authorization: Bearer $EMAIL_JWT" \
  "http://127.0.0.1:8000/api/workbench/tables/fcst_detail?page=1&page_size=5" \
  >/tmp/lct_fcst_detail.json
grep -q '"rows"' /tmp/lct_fcst_detail.json
```

#### 3.3 归因追问

复用上一轮 `session_id`，发送“冰箱为什么涨”，并保存第二轮 SSE：

```bash
ATTR_SSE=/tmp/lct_attribution_stream.sse
curl -sS --max-time 180 -N \
  -H "Authorization: Bearer $EMAIL_JWT" \
  -H 'Content-Type: application/json' \
  -X POST http://127.0.0.1:8000/api/chat/stream \
  -d "$(python - "$PREDICT_SSE" <<'PY'
import json, sys
session_id = None
for line in open(sys.argv[1], encoding='utf-8'):
    if not line.startswith('data:'):
        continue
    try:
        obj = json.loads(line[5:].strip())
    except json.JSONDecodeError:
        continue
    session_id = session_id or obj.get('session_id') or obj.get('data', {}).get('session_id')
print(json.dumps({'message':'冰箱为什么涨','session_id':session_id,'params':{}}, ensure_ascii=False))
PY
  )" >"$ATTR_SSE"

grep -q '^event: result$' "$ATTR_SSE"
grep -q '"response_type"' "$ATTR_SSE"
grep -q 'attribution\|report' "$ATTR_SSE"
```

验收器确认归因结果包含 `envelope.chart` 或瀑布数据、`envelope.text.markdown` 或报告正文，并且 `fcst_attribution` 的本次版本行可回查。能力判断只看 `response_type`；不检查、不引入 `intent`、planner、正则规则或向量记忆。

## 4. 工作台 What-if 真实数据链路

#### 4.1 baseline、策略目录和任务转发

```bash
BASELINE=/tmp/lct_whatif_baseline.json
curl -fsS -H "Authorization: Bearer $EMAIL_JWT" \
  "http://127.0.0.1:8000/api/whatif/baseline?category=冰箱&version=$FORECAST_SN" \
  >"$BASELINE"
grep -q '"source":"db"' "$BASELINE"
grep -q '"items"' "$BASELINE"

STRATEGIES=/tmp/lct_whatif_strategies.json
curl -fsS -H "Authorization: Bearer $EMAIL_JWT" \
  http://127.0.0.1:8000/api/whatif/strategies >"$STRATEGIES"
python - "$STRATEGIES" <<'PY'
import json, sys
obj = json.load(open(sys.argv[1], encoding='utf-8'))
actual = {x['id'] for x in obj['strategies']}
expected = {'maintain','price_cut','traffic_boost','trade_in','gift','bundle','prelaunch','eol_clearance'}
assert actual == expected, (actual, expected)
PY
```

从 baseline 第一条真实 item 生成模型所需的完整请求体，避免 backend 复制公式：

```bash
python - "$BASELINE" > /tmp/lct_simulate.json <<'PY'
import json, sys
item = json.load(open(sys.argv[1], encoding='utf-8'))['items'][0]
row = {
    'sku': item['sku'],
    'channel_l3': item.get('channel_l3', ''),
    'category': item['category'],
    'status': item.get('status', '主销'),
    'baseline_qty': float(item['baseline_qty']),
    'plan_price': float(item['plan_price']),
    'elasticity_coef': float(item.get('elasticity', item.get('elasticity_coef', 1.0))),
    'elasticity_class': item.get('elasticity_class', '普通'),
}
print(json.dumps({'strategy_id':'maintain','param':'','traffic_tier':'medium','rows':[row]}, ensure_ascii=False))
PY

SIMULATE_JSON=$(curl -fsS -H "Authorization: Bearer $EMAIL_JWT" \
  -H 'Content-Type: application/json' -X POST \
  http://127.0.0.1:8000/api/whatif/simulate \
  --data-binary @/tmp/lct_simulate.json)
SIMULATE_TASK=$(python -c 'import json,sys; print(json.load(sys.stdin)["task_id"])' <<<"$SIMULATE_JSON")
test -n "$SIMULATE_TASK"
```

#### 4.2 轮询 What-if 任务

使用固定 120 秒上限，终态只接受 `completed`；失败时输出最后一次响应和模型日志：

```bash
poll_task() {
  local task_id="$1" out status
  for i in $(seq 1 120); do
    out=$(curl -fsS -H "Authorization: Bearer $EMAIL_JWT" \
      "http://127.0.0.1:8000/api/whatif/tasks/$task_id")
    status=$(python -c 'import json,sys; print(json.load(sys.stdin).get("status", ""))' <<<"$out")
    case "$status" in
      completed) printf '%s\n' "$out"; return 0 ;;
      failed|error) printf '%s\n' "$out" >&2; return 1 ;;
    esac
    sleep 1
  done
  printf '%s\n' "$out" >&2
  return 1
}

poll_task "$SIMULATE_TASK" >/tmp/lct_simulate_result.json
grep -q '"status":"completed"' /tmp/lct_simulate_result.json
```

构造 optimize 请求时复用同一 `rows`，增加 `target_qty`：

```bash
python - /tmp/lct_simulate.json > /tmp/lct_optimize.json <<'PY'
import json, sys
obj = json.load(open(sys.argv[1], encoding='utf-8'))
obj.pop('strategy_id', None)
obj['target_qty'] = obj['rows'][0]['baseline_qty']
print(json.dumps(obj, ensure_ascii=False))
PY

OPTIMIZE_JSON=$(curl -fsS -H "Authorization: Bearer $EMAIL_JWT" \
  -H 'Content-Type: application/json' -X POST \
  http://127.0.0.1:8000/api/whatif/optimize \
  --data-binary @/tmp/lct_optimize.json)
OPTIMIZE_TASK=$(python -c 'import json,sys; print(json.load(sys.stdin)["task_id"])' <<<"$OPTIMIZE_JSON")
test -n "$OPTIMIZE_TASK"
poll_task "$OPTIMIZE_TASK" >/tmp/lct_optimize_result.json
grep -q '"status":"completed"' /tmp/lct_optimize_result.json
```

## 5. 管理端六页和 frontend 构建

先完成定向构建与快速壳测试：

```bash
cd frontend
npm run build
cd ../backend
uv run pytest -q tests/test_config.py tests/test_errors.py tests/test_dashboard_spec.py tests/test_llm.py tests/test_sse.py
```

使用 `ADMIN_JWT` 检查六个前端路由均能返回 SPA 入口，并检查后端管理员 API 与普通用户越权：

```bash
for page in users tools datasources llm audits config; do
  code=$(curl -sS -o /dev/null -w '%{http_code}' "http://127.0.0.1:5173/admin/$page")
  test "$code" = 200
done

for endpoint in users tools datasources llm sessions messages traces audits config; do
  curl -fsS -H "Authorization: Bearer $ADMIN_JWT" \
    "http://127.0.0.1:8000/api/v1/admin/$endpoint" >/dev/null
done

USER_ADMIN_CODE=$(curl -sS -o /dev/null -w '%{http_code}' \
  -H "Authorization: Bearer $EMAIL_JWT" \
  http://127.0.0.1:8000/api/v1/admin/users)
test "$USER_ADMIN_CODE" = 403
```

浏览器手工确认 admin 用户可以进入六页、普通 user 被导航到 `/workbench/input`；API 层的 403 检查以上述 curl 为准，不能以页面隐藏按钮替代后端权限。

## 6. 低耗时测试清单和单数据源审计

先只收集测试项，不执行全量套件：

```bash
cd backend
uv run pytest --collect-only -q > /tmp/lct_pytest_inventory.txt
grep -E '^[0-9]+ tests? collected|test_' /tmp/lct_pytest_inventory.txt | head -120
```

最后执行单数据源和旧目录隔离审计：

```bash
if grep -RInE 'sqlite|aiosqlite|PRAGMA|json_each' backend/src; then exit 1; fi
if grep -RInE 'reference_repo|服务/冰洗预测模型|冰洗预测模型' backend/src frontend/src; then exit 1; fi
if grep -RInE 'docs/UI设计稿|docs/知识库' backend/src frontend/src; then exit 1; fi
test "$(find backend -type f \( -name '.env' -o -name '.env.example' \) | wc -l)" -eq 2
```

## 完成标准
- 验收命令：
  ```bash
  python /c/Users/jie32.guo/.codex/skills/plan-generator/scripts/plan_state.py lint-plan --plan docs/plans/T15-e2e-acceptance-2026-09-01.md
  ```
- 通过条件：命令退出码为 0，且本节保留的原验收项全部满足。

- [ ] Git Bash 启动链成功：PG 由 `scripts/dev_db_pg.sh` 迁移/种子，icewash `8001`、backend `8000`、frontend `5173`、sandbox `9000` 健康。
- [ ] email 登录和 OA 登录都返回 backup JWT；OA 响应额外返回 OAuth token；工作台 HTTP Authorization 始终使用 backup JWT。
- [ ] email 用户自然语言预测产生 `status → result → done`，result 的 `envelope.response_type=forecast`，真实模型任务完成，`messages.result_envelope`、`fcst_forecast_result`、`fcst_attribution`、`workbench_dataset_rows(dataset=fcst_detail)` 均可按本次版本回查。
- [ ] 同一会话的归因追问返回 `attribution` 或 `report` envelope，包含归因图表或报告正文；能力判断不依赖 intent/planner/正则规则/向量记忆。
- [ ] What-if baseline 的 `source=db` 且有真实 item；模型返回且完成 `simulate`、`optimize` 两个 task；策略 ID 精确为 8 个模型目录中的 ID。
- [ ] frontend `npm run build` 和 T01 的 25 项快速壳测试通过；全量 pytest 仅完成收集并记录，不在本任务自动运行。
- [ ] 管理端六页路由返回 200，admin API 可访问，普通 user 访问 admin API 返回 403；无 token 工作台接口返回 401。
- [ ] backend/frontend 不直接读取 `docs/` 或 `reference_repo/`，backend/src 无 SQLite 访问痕迹，backend 仅保留根级 `.env` 与 `.env.example`。
