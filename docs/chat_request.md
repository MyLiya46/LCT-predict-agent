# Chat Request：LLM 规划与执行验收

本文档配套 `backend/tests/chat_request.py`，用于对运行中的 backend 发送多类真实用户问题，观察 LLM 实际选择的工具、工具入参和结果，并回查最终消息与 trace。

这里的“思考链”指可审计的执行链：SSE 状态、`tool_call/tool_result/tool_error`、最终回复和 envelope。模型隐藏思维内容不作为测试输出，也不应该写入日志或测试断言。

## 1. 验收对象

脚本调用工作台接口：

```text
POST /api/chat/stream
        │
        ├─ event: status / delta
        ├─ event: result      ← reply + envelope + steps
        └─ event: done

GET /api/v1/chat/conversations/{session_id}/messages/{message_id}/trace
GET /api/sessions/{session_id}
```

`/api/chat/stream` 是工作台 façade；trace 使用 `/api/v1/chat` 原生接口。两者不能把响应格式混用：前者返回裸 SSE/JSON，后者的 JSON 操作返回 `{code, message, data}`。

脚本会验证：

- SSE 至少有 `result`、`done`，且 `result → done` 顺序正确；
- `result` 返回的 `session_id/message_id` 能回查同一条 trace；
- trace 的 `seq` 按非递减顺序回放，工具并行执行时允许同一批事件共享 seq 边界，工具入参和结果可见；
- `/api/sessions/{session_id}` 中 assistant 的 `result_envelope` 与 SSE 的 envelope 一致；
- `--strict` 模式下，问题对应的 `response_type`、工具顺序和禁止工具调用符合场景契约；
- 输出和可选 JSON 报告会脱敏 JWT、OAuth token、password、API key 等字段。

## 2. LLM loop 是什么

当前 native chat loop 位于 `backend/src/app/engine/loop.py`，入口由 `chat_service.send_message()` 异步启动。一次请求的可观察过程如下：

```text
用户问题
  ↓
start_turn：创建/复用 session，创建 user + running assistant + trace
  ↓
starting
  ↓
组装历史上下文 + 场景 system prompt + enabled tool schemas
  ↓
planning：调用默认 LLM provider
  ├─ stop + 文本 → 生成最终回复
  └─ tool_use → executing：执行一个或多个工具
                    ↓
              tool_result / tool_error
                    ↓
              将工具结果以 role=tool 回灌 LLM
                    └──────────────→ 下一轮 planning
  ↓
done：保存 assistant、result_envelope，并推送 façade result/done
```

关键实现口径：

1. provider 从数据库默认 LLM provider 解析；没有 provider 时会走 `MockProvider`。因此“接口能返回”不等于“真实 LLM 已规划工具”。真实规划验收应配置健康的 provider，并使用 `--require-real-llm`。
2. 每轮循环都会保存 checkpoint（当前实现落在本轮模型返回后、工具结果回灌前）；工具调用可并行执行，系统配置的默认最大并发是 3。Agent 总轮数上限是 10，防止模型重复调用工具不收敛。
3. LLM 错误会按 retry policy 重试；持续失败进入 `retrying/degrading`。工具失败会写 `tool_error`，连续全部失败达到阈值后终止本轮，避免死循环。
4. `message.delta` 只用于在线展示，不写入 trace；最终文本以 `done` 和数据库 assistant 消息为准。
5. `submit_forecast`、`get_history`、`get_forecast_result`、`get_attribution`、`get_whatif_strategies`、`simulate`、`optimize` 是当前冰洗场景的 internal capability tools；它们在 backend 进程内执行，不经过 sandbox daemon。`submit_forecast` 只返回任务状态/版本号，预测明细和 TOP5 只能由 `get_forecast_result` 提供；TOP5 只表示排名趋势，白盒归因必须来自本轮真实的 `get_attribution`，每个成功的归因结果对应一张 waterfall 卡。
6. follow-up 建议是在主流程完成后额外调用一次轻量 `provider.complete()`，失败不会阻断主回复，也不是主规划 loop 的工具证据。

## 3. 运行前准备

从 Git Bash 执行。backend、PostgreSQL、冰洗模型服务和需要的 LLM provider 应已启动：

```bash
bash scripts/start_dev_stack.sh
```

如果栈已经启动，也可以只检查：

```bash
curl -fsS http://127.0.0.1:8000/healthz
curl -fsS http://127.0.0.1:8000/api/health/agent
curl -fsS http://127.0.0.1:8001/health
```

认证二选一：

```bash
# 推荐：使用现有 JWT，不把 token 写进命令历史
export CHAT_ACCESS_TOKEN='仅在当前 shell 中设置'

# 或使用开发账号登录；密码只通过环境变量读取
export CHAT_TEST_EMAIL='user@corp.com'
export CHAT_TEST_PASSWORD='开发环境密码'
```

测试脚本不会自动读取 `backend/.env` 中的账号或 key，也不会打印 token。若使用 email 账号首次注册，可额外加 `--register`；仅建议用于开发库。

预测问题默认使用运行时下一个自然月。为了复用已有预测版本、避免触发新的模型任务，建议显式指定已存在的月份：

```bash
export CHAT_FORECAST_MONTH=2026-10
```

真实预测/What-if 可能等待模型冷启动或任务完成，默认每个场景最多等待 360 秒。历史查询可单独用较短超时运行。

## 4. 执行命令

先查看内置问题：

```bash
cd backend
uv run python tests/chat_request.py --list-cases
```

快速验证历史问题：

```bash
cd backend
uv run python tests/chat_request.py \
  --case history \
  --strict \
  --timeout 60
```

完整场景验收（真实 provider + 真实工具执行）：

```bash
cd backend
uv run python tests/chat_request.py \
  --case history \
  --case forecast \
  --case attribution \
  --case optimization \
  --case optimization_target \
  --case simulation \
  --case missing \
  --forecast-month "${CHAT_FORECAST_MONTH:-2026-10}" \
  --strict \
  --require-real-llm \
  --report /tmp/lct-chat-request.json \
  --trace-dir /tmp/lct-chat-trace
```

也可以直接运行默认的全部主场景：

```bash
cd backend && uv run python tests/chat_request.py --strict
```

验证多轮上下文：先完成历史查询，再在同一 session 发送“把时间范围改为最近3个月”：

```bash
cd backend && uv run python tests/chat_request.py \
  --case history \
  --include-follow-up \
  --strict
```

退出码：`0` 表示协议和当前断言都通过；`1` 表示至少一个场景失败；`2` 表示认证、服务或参数未准备好；`130` 表示手动中断。没有 `--strict` 时，协议错误仍失败，但工具链/response_type 不匹配只显示 warning，适合先探索真实模型行为。

## 5. 内置问题与预期可观察结果

以下是测试 oracle。它们约束工具证据和结构化结果，不约束 LLM 的自然语言措辞，也不写死销量数值。

| 场景 | 用户问题 | 主要工具链（允许前后有启动/规划/收尾事件） | 预期结果 |
|---|---|---|---|
| `history` | `查询冰箱近半年销售情况` | `get_history`；禁止 `submit_forecast/get_forecast_result/get_attribution` | `response_type=history`，通常有历史趋势 chart 和按月 table |
| `forecast` | `预测冰箱以 2026-10 为基准未来3个月销量` | `submit_forecast → get_forecast_result` | `response_type=forecast`，只有 `line_band`；不应出现 TOP5 或 waterfall |
| `attribution` | `预测冰箱以 2026-10 为基准的 TOP5 型号销售趋势并分析` | `submit_forecast → get_forecast_result → get_attribution × 5`（可并行） | 通常仍为 `response_type=forecast`，同时有 TOP5 line series、5 条归因 evidence 和 5 张型号 waterfall；归因版本必须与预测版本一致 |
| `optimization` | `帮我制定冰箱下月销售计划` | `submit_forecast → get_forecast_result → get_whatif_strategies → optimize` | `response_type=optimization`；`chart.type=strategy_dashboard` 且包含 `strategy_matrix`、`attainment_trend`；趋势同时有 baseline、target、simulated；无目标时披露工作台默认目标：8 万台、5000 万元（销售额数据覆盖不足时保留缺失状态） |
| `optimization_target` | `帮我制定冰箱下月销售计划，目标销量 4 万台，目标销售额 500 万元` | `submit_forecast → get_forecast_result → get_whatif_strategies → optimize` | `optimize` 入参/结果使用 `target_qty=40000`、`target_revenue=5000000`，不能被默认目标覆盖；同样输出 baseline、target、simulated 三条趋势 |
| `simulation` | `如果我把冰箱主销型号降价8%，之后会怎么样` | `get_whatif_strategies → simulate` | `response_type=simulation`，策略必须来自目录；价格/成本/库存缺失应保留 `null/status/reason` |
| `missing` | `预测未来3个月销量` | 不要求固定工具；应询问/声明缺少品类 | `response_type=report` 或可读的输入提示，不能猜测品类 |

### 当前真实验收摘要（2026-09-07）

对运行中的真实 provider 执行等价问题后，观察到：

- 普通预测：`submit_forecast → get_forecast_result`；用户只说“未来3个月”时，LLM 曾把 `2026-09` 填入工具入参，工具层将其纠正为下一个自然月 `2026-10`，最终版本为 `AG_洗衣机_2026-10-H3`，预测结果为 2026-10/11/12 分别 9,298、12,245、11,020 台，envelope 只有 `line_band`。
- TOP5 归因：`submit_forecast → get_forecast_result → get_attribution × 5`；5 个型号归因均沿用同一版本和首个预测月，最终 envelope 同时有 1 张 `line_band`、TOP5 series 和 5 张按型号命名的 `waterfall`，`meta.evidence.attribution_count=5`。
- 这两条结果说明：预测结果中的排名数据不再自动变成 TOP5 图；归因图必须有真实 `get_attribution` 工具证据。
- 无目标销售计划：真实 provider 实际走通 `submit_forecast → get_forecast_result → get_whatif_strategies → optimize`；`target_source` 为 `default_workbench`，本次数据的 baseline 销量为 24,915 台、默认目标为 80,000 台，baseline 到目标差距为 55,085 台，矩阵包含 61 个型号，最终 LLM 回复包含基线、目标差距、策略样例、模拟结果和库存缺失说明。
- 显式目标销售计划：同一工具链中 `optimize` 实际入参为 `target_qty=40000`、`target_revenue=5000000`，结果 `target_source` 为 `tool_input`，最终 LLM 回复明确说明目标来自用户输入；两种销售计划的 envelope 都是 `strategy_dashboard`，包含 `strategy_matrix` 与 `attainment_trend`，数量趋势包含 baseline/target/simulated。金额模拟明细不完整时保持 `null`，不把缺失金额填成 0。

`optimization` 和 `simulation` 可能先创建或读取预测版本，再进入 What-if 工具；脚本只断言关键子序列，而不把所有 LLM 回合写死。销售计划场景的 `optimize` 结果必须是工作台同源的完整基线、目标差距、有限策略推荐和模拟结果，最后由 LLM 汇总为报告；脚本不把模型隐藏思维内容当作测试输出。

## 6. 如何读脚本输出

一次通过的控制台输出结构类似下面这样（数值和型号必须以本次真实服务返回为准）：

```text
[1] history: 查询冰箱近半年销售情况
  SSE: status×... → delta×... → result → done | 首事件 ...ms | 总耗时 ...ms
  Agent 阶段: starting → planning → executing → ... → done
  Trace 事件: agent_process → tool_call → tool_result → agent_process → done
    [n] TOOL CALL get_history: input={"category":"冰箱",...}
    [n] TOOL RESULT get_history status=ok duration=...ms: output={"response_type":"history","rows":[...]}
  Reply: ...
  Envelope: {"response_type":"history","chart_cards":[...],"table_rows":...}
  判定: PASS

[2] forecast: 预测冰箱以 2026-10 为基准未来3个月销量
  Trace 事件: agent_process → tool_call → tool_result → agent_process → tool_call → tool_result → done
    [n] TOOL CALL submit_forecast: input={"category":"冰箱","forecast_month":"2026-10","horizon":3}
    [n] TOOL RESULT submit_forecast status=ok: output={"system_forecast_number":"AG_冰箱_2026-10-H3","next_tool":"get_forecast_result",...}
    [n] TOOL CALL get_forecast_result: input={"system_forecast_number":"AG_冰箱_2026-10-H3",...}
    [n] TOOL RESULT get_forecast_result status=ok: output={"response_type":"forecast",...}
  Envelope: {"response_type":"forecast","chart_cards":["line_band"],"table_rows":3}
  判定: PASS

[3] attribution: 预测冰箱以 2026-10 为基准的 TOP5 型号销售趋势并分析
  Trace 事件: ... → get_attribution×5 → ... → done
  Envelope: {"response_type":"forecast","chart_cards":["line_band","waterfall","waterfall","waterfall","waterfall","waterfall"],"chart_card_titles":["预测曲线","白盒归因 · SKU-1", "白盒归因 · SKU-2", "白盒归因 · SKU-3", "白盒归因 · SKU-4", "白盒归因 · SKU-5"]}
  判定: PASS
```

脚本输出的 `Trace 事件` 是最重要的实际规划执行证据：

- `tool_call.input`：LLM 本轮实际提交给工具的 JSON，不是测试脚本预写的参数；
- `tool_result.output`：工具实际返回的结构化数据；
- 下一次 `planning`：说明工具结果已回灌给 LLM，进入下一轮决策；
- `Envelope.meta.evidence`：后端 projection 选取的工具、版本、品类和行数；
- `Envelope.chart.cards`：`line_band` 是排名/趋势视图，`waterfall` 才是型号因子归因；TOP5 场景应有 5 张带 SKU 标题的 waterfall；
- `result_envelope`：前端刷新或离开 SSE 后仍能读取的最终投影。

当结果是 `FAIL`，先看三个位置：

1. SSE 是否停在 `status`/`delta`，通常对应上游超时、客户端断开或 stream 没有终态；
2. trace 最后一个事件是 `tool_error` 还是 `degrading/done`，区分工具失败和 LLM/provider 失败；
3. `response_type` 与工具链是否一致，判断是模型规划错误还是 projection/数据问题。

## 7. 常见问题的测试思路

### 7.1 历史问题被误判成预测

用“历史、过去、实际、近半年”类问题，断言必须出现 `get_history`，同时禁止 `submit_forecast`、`get_forecast_result` 和 `get_attribution`。检查结果中的月份和销量都来自 `get_history` 的 `rows`，不能只看自然语言回复中的一句“已完成”。

### 7.2 预测问题被历史数据替代

预测必须观察 `submit_forecast → get_forecast_result`。`submit_forecast` 只负责提交/复用任务，第二个工具的 `system_forecast_number` 应来自第一个工具结果，预测数字、月份和 TOP SKU 都应从 `get_forecast_result` 的结构化结果读取。普通预测即使结果里带有排名字段，最终 envelope 也不能渲染 TOP5；若只看到 `get_history` 或直接生成数字，应判定为规划失败。

### 7.3 预测归因的版本或 SKU 串线

先从 `get_forecast_result.top_skus` 取 TOP5，再检查 5 个 `get_attribution` 的 `sku` 是否逐一在该列表，且 `system_forecast_number` 相同、`period` 在预测期内。最终 envelope 应有预测曲线、TOP5 series 和 5 张按 SKU 标识的 waterfall；没有真实 `get_attribution` 时不能用 TOP5 字段冒充归因。脚本打印工具链和结构化摘要，版本/SKU 核对可在 JSON 报告中完成。

### 7.4 What-if 臆造策略

“降价、投流、以旧换新、之后会怎样”等问题不应让模型直接拼一个未知 `strategy_id`。先观察 `get_whatif_strategies`，再检查 `simulate` 的策略 id/name/参数能在目录中找到。优化问题可以直接进入 `optimize`，但返回的策略矩阵仍必须是工具结果，不能由 LLM 编造。

### 7.5 缺少品类、月份或目标

分别测试“预测未来3个月销量”“预测冰箱未来3个月但不提供基准月”“帮我制定销售计划但不给目标”。缺少品类时期望 `need_input` 或明确可操作的追问；不得默认猜一个品类、版本号或 SKU。相对时间表达（“未来”“下月”）在当前 engine context 下允许默认下一个自然月，因此缺少基准月不一定失败；测试应记录实际入参并确认月份来源。

销售计划没有显式目标时不追问：`optimize` 使用工作台当前默认目标销量 8 万台、默认目标销售额 5000 万元，并在 `meta.target_source` 和 `meta.assumptions` 披露。若 baseline 的价格覆盖不足，销售额目标和金额曲线应为 `null`/缺失状态，不能补造金额。用户语义包含目标时优先使用用户目标，例如“4 万台”和“500 万元”分别规范化为 `40000` 和 `5000000`。

### 7.6 工具失败、LLM 重试和降级

不要只断言 HTTP 200。检查 trace 中的 `tool_error.error_code`、`retried`，以及状态是否出现 `retrying/degrading`。失败场景应该有可读的终态，不能把上游完整错误 body、token 或堆栈原样返回给用户；连续失败需要收敛，不能无限重复工具调用。

### 7.7 多轮上下文污染

先问“查询冰箱近半年销售情况”，再在同一 session 问“把时间范围改为最近3个月”。第二轮应从上下文保留品类并重新调用 `get_history`，不能把上一轮回答中的销量数字当作新事实。使用 `--include-follow-up` 验证这一点。

### 7.8 空数据和数据缺失

历史/预测无行时，结果应明确为空或缺失，不应把空集合变成 0。What-if 的价格、成本、库存覆盖不足时，检查 table 和 metrics 中的 `null`、`price_status`、`cost_status`、`inventory_status`、`inventory_reason`；不接受固定假数字。

## 8. MockProvider 与真实 LLM 的区别

当前引擎没有数据库默认 provider 时会回退到 `MockProvider`。这个回退用于离线联调，但它不是当前冰洗 capability 的真实规划验收替代品：脚本化 mock 可能只返回固定文本或识别旧工具名，无法证明当前 `get_history/submit_forecast/...` 工具链由真实 LLM 选择。

因此建议分开记录：

- 离线/无 provider：验证 API、SSE、trace、envelope 的协议稳定性；允许 warning，但不要声称完成真实 LLM 规划验收；
- 有健康 DB provider：使用 `--require-real-llm --strict`，把实际工具顺序、入参、结果和版本作为验收证据；
- provider 或模型服务不可用：保留脚本的 `FATAL`/`tool_error`/`degrading` 输出，记录为外部环境阻塞，不用伪造数字代替。

## 9. 结果保存与敏感信息

写 JSON 报告和 trace Markdown 时使用临时目录：

```bash
cd backend
uv run python tests/chat_request.py \
  --case history \
  --report /tmp/lct-chat-request.json \
  --trace-dir /tmp/lct-chat-trace
```

不要把含真实销售数据的报告、token、`.env`、数据库 dump 或生成日志提交到 Git。报告已经对常见 credential 字段做了脱敏，但仍应按业务数据处理；脚本不会自动删除这些文件。

## 10. 相关实现与契约

- `backend/tests/chat_request.py`：本脚本；
- `backend/src/app/api/chat_facade.py`：工作台 chat / stream façade；
- `backend/src/app/services/chat_bridge.py`：native event → status/result 的桥接；
- `backend/src/app/engine/loop.py`：LLM planning、工具执行、回灌、重试、checkpoint 和终态；
- `backend/src/app/services/chat_envelope.py`、`chat_result_projection.py`：结构化结果投影；
- `docs/api-contract.md` §3、§4、§14：原生 chat、工作台 façade 和 SSE 契约；
- `backend/tests/test_agent_forecast_workflow.py`、`test_chat_*`：离线固定 provider 和 projection 回归。
