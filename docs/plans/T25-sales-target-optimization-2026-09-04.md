# T25 · 销量与销售额双目标优化（sales-target-optimization）

- 任务 ID：T25
- 标题与目标：把页面经营目标中的销量和销售额同时传入 Agent optimize，并让候选策略按两个目标选择。
- 关联文档章节：`docs/feat-icewash.md` §3.4、§3.5；T23、T24
- 前置依赖 blockedBy：T23、T24

## 执行画像

- execution_mode：direct
- execution_class：normal
- expected_duration：约 35 分钟
- external_waits：icewash model task 可选
- checkpoint_phases：请求字段、明细模拟、双目标评分、Agent 工具 schema、回归测试
- resume_boundary：从最后一个未通过的优化契约测试继续

## 问题

- 页面已有销售额目标输入，但现有 Agent 请求只传 `target_qty`。
- `whatif.py` 的候选选择只计算 `abs(sim_qty-target_qty)`，销售额策略目标没有进入评分。
- 型号聚合后需要对一个型号的多月/多渠道明细应用同一策略，并用明细销售额汇总评分。

## 决策

- `target_revenue` 单位固定为元；页面输入的百万元在提交前乘以 `1e6`。
- 没有销售额目标时保持旧销量-only 逻辑；两个目标同时存在时，评分为销量相对误差与销售额相对误差之和，各自分母至少为 1。
- 页面按基线销量和基线销售额分别把总目标分配到型号行；模型服务对 details 逐条模拟后再返回型号级 `sim_qty/sim_price/sim_amount`。
- 内部 Agent 工具 schema 将销售额目标设为可选，已有只传销量的调用继续有效。

## 范围

- 包含：前端请求、backend API/工具透传、模型服务 Pydantic 契约、details 聚合模拟、双目标评分、seed schema 和测试。
- 不包含：策略目录和弹性公式改写；销量/销售额权重仍为等权归一化误差。

## 环境预检

- 必需 Shell：git-bash
- 必需命令：`backend/.venv/Scripts/python.exe`、`npm`
- 必需端口：8001（icewash model 可选）
- 必需 URL：`http://127.0.0.1:8001/health`
- 必需 Python 模块：`fastapi`、`pydantic`、`pytest`
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
  python C:/Users/jie32.guo/.codex/skills/plan-generator/scripts/preflight.py check --plan docs/plans/T25-sales-target-optimization-2026-09-04.md --format json
  ```

## 风险与回滚

- 风险：价格缺失时销售额评分无法区分候选策略，影响降价/套购推荐；通过价格覆盖状态和销量-only fallback 监测。
- 回滚：客户端不传 `target_revenue` 即恢复销量-only；模型服务保留可选字段和旧函数签名，回滚只需撤销前端字段及评分分支。

## 实施步骤

### 步骤 1：贯通双目标请求
- 对象：`WhatIfModelRow`、`/api/whatif/optimize`、icewash `OptimizeRequest`、内部 optimize tool。
- 动作：新增可选 `target_revenue`，按元透传；seed schema 同步字段。
- 参数：字段最小值 0；请求级目标在没有行级分配时按基线金额权重分配，基线金额全缺失时按销量权重分配。
- 核心修改文件：`frontend/src/api.ts`、`backend/src/app/api/whatif.py`、`backend/src/app/tools/internal/optimize/tool.py`、`services/icewash-model/cbg_fcst_month/server.py`
- 必要集成文件：`backend/seed/v2__icewash_tools.py`
- 命令：
  ```bash
  backend/.venv/Scripts/python.exe -m pytest -q backend/tests/test_capability_tools.py
  ```

### 步骤 2：按型号 details 评分
- 对象：`simulate_row`、`optimize_row/search_optimize`、icewash server task worker。
- 动作：支持 details 逐条执行同一策略，汇总模拟量、模拟价和销售额；候选使用双目标归一化评分。
- 参数：无 `target_revenue` 时 `score=abs(qty_gap)`；有目标时 `score=qty_gap/max(target_qty,1)+amount_gap/max(target_revenue,1)`；返回 `gap`、`amount_gap`、`score`、`sim_amount`。
- 核心修改文件：`services/icewash-model/cbg_fcst_month/whatif.py`、`services/icewash-model/cbg_fcst_month/server.py`
- 必要集成文件：`frontend/src/pages/WhatIfPage.tsx`
- 命令：
  ```bash
  backend/.venv/Scripts/python.exe -m pytest -q backend/tests/test_icewash_whatif_contract.py
  ```

### 步骤 3：更新 Agent 页面提交和结果回写
- 对象：`runAgent`、目标分配、模型结果 rows 和 KPI。
- 动作：将总销量/销售额目标按型号行分配，提交 details，回写型号级模拟数量/价格/销售额和建议策略。
- 参数：销售额单位百万元转元；目标分配权重优先基线销售额；页面默认保留销量 8、销售额 50。
- 核心修改文件：`frontend/src/pages/WhatIfPage.tsx`
- 必要集成文件：无
- 命令：
  ```bash
  cd frontend && npm run build
  ```

## 完成标准
- 验收类型：mixed
- 离线验收命令：
  ```bash
  python -m py_compile services/icewash-model/cbg_fcst_month/whatif.py services/icewash-model/cbg_fcst_month/server.py
  cd backend && .venv/Scripts/python.exe -m pytest -q tests/test_capability_tools.py tests/test_icewash_whatif_contract.py
  cd ../frontend && npm run build
  ```
- 外部环境验收命令：调用 `/api/whatif/optimize` 同时传 `target_qty` 和 `target_revenue`，轮询 `/api/whatif/tasks/{task_id}`，确认返回 `sim_amount`、`amount_gap` 和策略；页面日志应同时记录两个目标。
- 通过条件：销售额字段从页面/Agent 到模型服务完整可见；双目标测试能选出不同于销量-only 的候选；不传销售额时旧测试保持通过。
