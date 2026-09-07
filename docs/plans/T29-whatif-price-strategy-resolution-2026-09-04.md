# T29 · What-if 规则策略基准价与缺失价处理（whatif-price-strategy-resolution）

- 任务 ID：T29
- 标题与目标：让规则式策略以已解析的历史基准价计算，并保证“维持现状”与其它策略的价格、销售额和毛利结果可追溯。
- 关联文档章节：`docs/feat-icewash.md` §3.4、§3.5；T27、T28
- 前置依赖 blockedBy：T27、T28

## 执行画像

- execution_mode：worker
- execution_class：normal
- expected_duration：约 35 分钟
- external_waits：无；icewash HTTP 回归可选
- checkpoint_phases：价格回退、策略公式、缺失值语义、前端结果回写、模型测试
- resume_boundary：从最后一个未通过的策略或前端契约验收项继续

## 问题

- `whatif.py` 的 `_simulate_details()` 使用了含义不清的 `forecast_price`/`plan_price` 混合字段；空价格回退行为不可见。
- 旧路径把空价格 `float(plan_price or 0)`，使维持现状、折扣、套购的销售额被算成 0；销售额目标评分还可能因空值异常或错误选策略。
- 页面把模型返回的空 `sim_price` 强制成 0，无法区分“没有价格”和“价格为 0”。

## 决策

- `maintain` 直接沿用 T28 解析出的历史最后有效月基准价；未来六个月和所有渠道明细使用该明细基准价，不重新读取当前月份价格。
- `price_cut`、`eol_clearance`、`bundle` 在基准价上调整；`traffic_boost`、`trade_in`、`gift`、`prelaunch` 价格保持基准价；数量公式和候选目录保持现状。
- 有效价格为空时，数量仍可模拟，但 `sim_price`、`sim_amount`、毛利保持 null，并暴露覆盖状态；绝不以 0 充当未知价格。
- optimize 传入销售额目标但候选销售额不可计算时，退回销量目标评分并将 `amount_gap` 标为 null，不能抛异常或伪造销售额；有有效价格时继续使用 T25 的销量/销售额归一化双目标评分。
- 前端类型、结果回写和 KPI 保留 null；金额显示使用已有的缺失提示，维持历史价格时显示实际价格。

## 范围

- 包含：icewash 规则计算、明细级价格回退、缺失金额/毛利语义、双目标缺价 fallback、frontend What-if 结果类型与回写、策略回归测试。
- 不包含：大模型策略生成、策略目录增删、历史价格数据导入、库存周转数据建模。

## 环境预检

- 必需 Shell：git-bash
- 必需命令：`backend/.venv/Scripts/python.exe`、`python`、`npm`
- 必需端口：8001（外部 HTTP 验收可选）
- 必需 URL：`http://127.0.0.1:8001/health`
- 必需 Python 模块：无
- 必需 Docker 容器：无
- 容器内必需命令：无
- 容器内必需 Python 模块：无
- 执行画像：normal
- 启动超时（秒）：20
- 空闲超时（秒）：45
- 硬截止（秒）：240
- 最大 checkpoint 间隔（秒）：45
- 预检命令：
  ```bash
  python C:/Users/jie32.guo/.codex/skills/plan-executor/scripts/preflight.py check --plan docs/plans/T29-whatif-price-strategy-resolution-2026-09-04.md --format json
  ```

## 风险与回滚

- 风险：缺价格后由“0”改为 null，部分前端金额显示会从数字变为缺失提示；这是数据真实性变化，需由覆盖状态和测试确认。规则目录的既有数量结果不应改变。
- 回滚：保留 T28 的价格来源和数据库迁移；如需回退，仅反向应用 `whatif.py`、前端类型/回写和相关测试变更，不回退历史金额迁移，不删除已同步数据。

## 实施步骤

### 步骤 1：修正模型明细价格解析和策略计算

- 对象：`simulate_row()`、`_simulate_details()`、`optimize_row()`。
- 动作：模型只接收后端解析后的 `baseline_price`；将策略价格计算统一应用于该基准价；聚合金额/毛利时保留缺失状态。
- 参数：`maintain` 价格乘数 1；`price_cut` 使用 `1+pct` 与 `min(0.8, Ed×abs(pct))`；`bundle` 数量乘 1.10、价格乘 `1+max(0, atv)`；缺价格返回 `sim_price=None`、`sim_amount=None`。
- 核心修改文件：`services/icewash-model/cbg_fcst_month/whatif.py`
- 必要集成文件：`services/icewash-model/cbg_fcst_month/server.py`
- 命令：
  ```bash
  python -m py_compile services/icewash-model/cbg_fcst_month/whatif.py services/icewash-model/cbg_fcst_month/server.py
  ```

### 步骤 2：保持双目标优化在缺价时可运行

- 对象：`optimize_row()` 的候选评分和 server 返回行。
- 动作：当 `target_revenue` 存在且候选 `sim_amount` 不可用时使用销量误差评分，返回 `amount_gap=null` 与价格覆盖状态；有效金额时保持 T25 归一化双目标评分。
- 参数：销量评分仍为 `abs(sim_qty-target_qty)`；双目标评分仍为 `qty_gap/max(target_qty,1)+amount_gap/max(target_revenue,1)`；不得把 null 转换为 0。
- 核心修改文件：`services/icewash-model/cbg_fcst_month/whatif.py`、`services/icewash-model/cbg_fcst_month/server.py`
- 必要集成文件：无
- 命令：
  ```bash
  backend/.venv/Scripts/python.exe -m pytest -q backend/tests/test_icewash_whatif_contract.py
  ```

### 步骤 3：修正前端 null 结果回写与展示

- 对象：What-if API 类型、`runAgent`、`runSimulation`、`rowMetrics` 与策略模拟兼容函数。
- 动作：`sim_price`/`sim_amount` 使用 nullable 类型；模型返回 null 时原样保留；基线历史价格显示实际解析值；金额和毛利缺失时显示已有缺失文案，不计算为 0。
- 参数：`maintain` 的页面基线 `sim_price` 必须等于 `baseline_price`；`Number(... ?? 0)` 只允许用于数量图表，不得用于价格或金额字段。
- 核心修改文件：`frontend/src/api.ts`、`frontend/src/pages/WhatIfPage.tsx`、`frontend/src/whatifSimulate.ts`
- 必要集成文件：无
- 命令：
  ```bash
  cd frontend && npm run build
  ```

### 步骤 4：覆盖基准价与策略公式回归

- 对象：icewash What-if 测试和前端/后端契约测试。
- 动作：添加历史基准价下 maintain、price_cut、bundle 的金额断言；添加 detail `baseline_price` null 但行级基线价有值的回退断言；添加全缺价时金额 null、销量优化不报错的断言。
- 参数：基准价 100、数量 100 时 maintain 为 100/10000；降价 10% 且 Ed=1 时价格 90、销量 110、销售额 9900；bundle 默认价格按 +15%、销量按 +10%。
- 核心修改文件：`backend/tests/test_icewash_whatif_contract.py`
- 必要集成文件：`frontend/src/pages/WhatIfPage.tsx`
- 命令：
  ```bash
  backend/.venv/Scripts/python.exe -m pytest -q backend/tests/test_icewash_whatif_contract.py
  ```

## 完成标准

- 验收类型：mixed
- 离线验收命令：
  ```bash
  python C:/Users/jie32.guo/.codex/skills/plan-generator/scripts/plan_state.py lint-plan --plan docs/plans/T29-whatif-price-strategy-resolution-2026-09-04.md
  python -m py_compile services/icewash-model/cbg_fcst_month/whatif.py services/icewash-model/cbg_fcst_month/server.py
  backend/.venv/Scripts/python.exe -m pytest -q backend/tests/test_icewash_whatif_contract.py
  cd frontend && npm run build
  ```
- 外部环境验收命令：调用 `POST http://127.0.0.1:8001/optimize`，传入含历史基准价的六个月 details，并轮询 `/tasks/{task_id}`。
- 通过条件：maintain 使用历史基准价；价格策略基于该价调整；有价时金额/毛利正确；无价时返回 null 而非 0；Agent 规则枚举在有/无销售额目标两种请求下都能完成。
