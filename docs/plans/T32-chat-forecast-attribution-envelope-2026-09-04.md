# T32 · 聊天预测/白盒归因复合结果契约（chat-forecast-attribution-envelope）

- 任务 ID：T32
- 标题与目标：把预测结果和白盒归因结果合并为一个可渲染的聊天 envelope，使预测类回答稳定呈现“分析解读、可视化图表、数据表”三个子栏。
- 关联文档章节：`docs/feat-icewash.md` §3.2、§3.3、§4、§10.2；`docs/PRD.md` §7.1；T10、T20、T31
- 前置依赖 blockedBy：T31

## 执行画像

- execution_mode：worker
- execution_class：normal
- expected_duration：约 50 分钟
- external_waits：无；真实服务在 T35 验收
- checkpoint_phases：结果投影契约、复合图表数据、envelope 聚合、离线回归
- resume_boundary：从最后一个未通过的契约测试继续

## 问题

- `backend/src/app/services/chat_envelope.py` 当前只选择最后一个成功工具输出；预测后再查归因时，最终 envelope 会丢失预测曲线或归因图。
- `submit_forecast/get_forecast_result` 当前基础 envelope 只有简单折线和预测表，不能表达 Attribution 工作台的“历史实线 + 预测虚线 + 预测起点”曲线，也不能带白盒 waterfall。
- `MessageResultCard` 的图表 tab 只接受单个 ECharts `option`；预测场景缺少复合 chart 数据时只有分析解读和数据表，正是“预测洗衣机未来 3 个月销量”少一个子栏的直接原因。

## 决策

- 以 backend 结构化工具结果为唯一数据源，新增一个纯投影模块把所有成功 tool output 组装成 envelope；不让 LLM 生成 ECharts option、销量、金额或归因数值。
- 保持 `response_type=forecast` 作为预测主类型，`response_type=attribution` 作为仅归因类型；预测+归因仍使用 `forecast`，通过 `meta.evidence` 和复合 chart 表达已合并的两类证据，避免破坏已有响应分派。
- 扩展 `chart` JSON 合同，保留旧 `{type, option}` 兼容形式，同时支持：
  ```json
  {
    "type": "composite",
    "cards": [
      {"type": "line_band", "title": "预测曲线", "data": {"periods": [], "history": [], "forecast": [], "split_period": null, "top_skus": []}},
      {"type": "waterfall", "title": "白盒归因", "data": {"sku": "", "xAxis": [], "placeholder": [], "values": [], "labels": [], "colors": []}}
    ]
  }
  ```
  `line_band.data` 的 `history/forecast` 与 `periods` 等长，缺失值统一为 JSON `null`；`top_skus` 为 `[{"rank": 1, "sku": "", "periods": [], "forecast": []}]` 形状，纯预测无 TOP5 证据时为空。纯预测至少有 `line_band` card；只有在本轮收到归因证据时才加入 waterfall card。
- 预测表使用完整请求 horizon 的预测行；图表按请求范围展示总趋势，TOP5 分析额外展示 `top_skus` 线或首个选中 SKU 的白盒归因。所有 KPI 和表格明细均保持 T22–T30 的全量/缺失值口径，`limit` 只能影响分页展示。
- 最终 LLM 文本继续覆盖 `text.markdown`，但 envelope `meta.evidence` 必须记录实际成功工具和预测版本；没有预测证据时不能把 history 结果标为 forecast。

## 范围

- 包含：多工具输出聚合、预测/归因 chart data builder、复合 envelope、工具结果落库与 façade SSE/非流式返回的一致性、backend 契约测试。
- 不包含：前端 ECharts 组件实现、What-if 策略矩阵、预测模型公式和归因模型计算；前端渲染在 T34，What-if 投影在 T33。

## 环境预检

- 必需 Shell：git-bash
- 必需命令：`python`、`backend/.venv/Scripts/python.exe`、`uv`
- 必需端口：无；外部聊天验收在 T35
- 必需 URL：无
- 必需 Python 模块：pytest、pydantic、sqlalchemy
- 模块检查解释器：backend/.venv/Scripts/python.exe
- 必需 Docker 容器：无
- 容器内必需命令：无
- 容器内必需 Python 模块：无
- 执行画像：normal
- 启动超时（秒）：20
- 空闲超时（秒）：30
- 硬截止（秒）：300
- 最大 checkpoint 间隔（秒）：45
- 预检命令：
  ```bash
  python C:/Users/jie32.guo/.codex/skills/plan-generator/scripts/preflight.py check --plan docs/plans/T32-chat-forecast-attribution-envelope-2026-09-04.md --format json
  ```

## 风险与回滚

- 风险：复合 chart 数据结构改变前端类型；多工具顺序或重复归因可能造成重复 card；历史会话中旧 envelope 没有 `response_type` 或仍使用 `intent`。通过旧格式兼容测试、按 `sku/period` 去重和固定 card 快照监测。
- 回滚：保留旧 `{type, option}` chart 分支和 `intent` 映射；若复合结果在运行态异常，临时只返回预测 line card 和原预测表，恢复范围限定为结果投影、chat envelope 和对应测试，不回滚 T31 工具契约。

## 实施步骤

### 步骤 1：建立多工具结果投影和证据选择规则

- 对象：聊天终态的 tool output 集合、`build_envelope` 和 `collect_turn` 的落库路径。
- 动作：新建共享结果投影模块，按 `forecast → attribution` 识别主结果并合并所有成功输出；将 `response_type/text/meta/follow_ups/update_workspace/process_steps` 统一写入 envelope，避免 engine、facade、历史会话读取到不同结果。
- 参数：同一 `sku + period + system_forecast_number` 的归因只保留一次；主预测版本取最后一个成功预测工具且必须与归因版本一致；`meta.evidence` 至少记录工具名、版本、品类和证据计数；工具错误不进入 chart/table。
- 核心修改文件：`backend/src/app/services/chat_envelope.py`、`backend/src/app/services/chat_result_projection.py`、`backend/src/app/services/chat_bridge.py`
- 必要集成文件：`backend/src/app/engine/loop.py`、`backend/src/app/api/chat_facade.py`、`backend/tests/test_chat_envelope.py`
- 命令：
  ```bash
  cd backend && uv run pytest -q tests/test_chat_envelope.py tests/test_chat_stream_facade.py
  ```

### 步骤 2：生成预测曲线和白盒归因 chart data

- 对象：预测点、TOP5 月度序列、`get_attribution` 返回的 trend/waterfall 数据。
- 动作：在结果投影模块中生成 `composite` chart；按 Attribution 工作台语义构造历史实线、预测虚线、预测起点标线和无值断点；历史序列由 PG-only `attribution_workbench` 的既有历史表查询/新增聚合 helper 提供，不能由 LLM 或模型任务结果猜测；按归因 waterfall 的 `xAxis/placeholder/values/labels/colors` 保留白盒数据。
- 参数：预测曲线 `periods` 与 `history/forecast` 一一对齐；历史值缺失统一为 JSON `null` 且不补零；预测期从 `N+1` 开始；`top_skus` 每个序列的 `periods/forecast` 一一对齐；waterfall 只接受工具返回的数值，默认最多保留绝对影响最大的 10 个因子并保留“基础销量/最终预测”端点；归因版本与主预测版本不一致时丢弃该归因 card 并记录 evidence mismatch；无归因结果时不得伪造 waterfall card。
- 核心修改文件：`backend/src/app/services/chat_result_projection.py`、`backend/src/app/tools/internal/get_forecast_result/tool.py`、`backend/src/app/tools/internal/get_attribution/tool.py`、`backend/src/app/services/attribution_workbench.py`
- 必要集成文件：`backend/tests/test_chat_forecast_projection.py`、`backend/tests/test_capability_tools.py`
- 命令：
  ```bash
  cd backend && uv run pytest -q tests/test_chat_forecast_projection.py tests/test_capability_tools.py
  ```

### 步骤 3：覆盖预测、TOP5 分析和旧 envelope 兼容

- 对象：`build_envelope`、`/api/chat`、`/api/chat/stream` 的 result payload 和 Message JSONB。
- 动作：新增 fixture 测试：只有预测结果时输出分析/line chart/table；预测+五个归因结果时输出一个 composite chart、预测表和证据 metadata；TOP5 fixture 的 `line_band.data.top_skus` 保留 5 条完整预测序列；旧 history/report envelope 仍按旧 UI 合同返回；非流式和 SSE result 使用同一投影函数。
- 参数：预测 3 个月 fixture 必须有 3 个 period 行；TOP5 fixture 必须保留 5 个 SKU 的趋势序列和至少 1 个 waterfall；最终文本为空时使用投影生成的安全标题/摘要，不能让 `MessageResultCard` 因 markdown 为空而丢失其它两栏。
- 核心修改文件：`backend/tests/test_chat_forecast_projection.py`、`backend/tests/test_chat_envelope.py`
- 必要集成文件：`backend/tests/test_chat_stream_facade.py`、`backend/tests/test_chat_facade.py`
- 命令：
  ```bash
  cd backend && uv run pytest -q tests/test_chat_forecast_projection.py tests/test_chat_envelope.py tests/test_chat_stream_facade.py tests/test_chat_facade.py
  ```

## 完成标准

- 验收类型：offline
- 离线验收命令：
  ```bash
  python C:/Users/jie32.guo/.codex/skills/plan-generator/scripts/plan_state.py lint-plan --plan docs/plans/T32-chat-forecast-attribution-envelope-2026-09-04.md
  cd backend && uv run pytest -q tests/test_chat_forecast_projection.py tests/test_chat_envelope.py tests/test_chat_stream_facade.py tests/test_chat_facade.py
  ```
- 外部环境验收命令：无
- 通过条件：预测 fixture 的 envelope 同时含 `text/chart/table`；`chart.type=composite` 且 line card 存在；预测+归因 fixture 还含 waterfall card；历史查询不被误标为 forecast；stream 与非流式结果字段一致；旧 envelope 可正常读取。
