# T24 · 毛利覆盖与库存周转展示（margin-inventory-metrics）

- 任务 ID：T24
- 标题与目标：让毛利/综合毛利率遵循成本覆盖口径，并在缺少未来库存与 COGS 时显示明确的固定回退标签。
- 关联文档章节：`docs/feat-icewash.md` §3.4、§10.2；T23
- 前置依赖 blockedBy：T23

## 执行画像

- execution_mode：direct
- execution_class：normal
- expected_duration：约 30 分钟
- external_waits：无
- checkpoint_phases：成本状态、KPI 计算、库存标签、页面构建
- resume_boundary：从最后一个未通过的页面指标验收项继续

## 问题

- 当前 `rowMetrics` 对缺失成本使用 0 参与总毛利，页面单行虽然隐藏毛利，顶部综合毛利率却可能被高估。
- 库存原始表有期初/当前库存，但没有未来期末/平均库存和明确 COGS，当前 `45 天` 没有标记为回退值。
- 页面需要同时呈现型号毛利、综合毛利率、成本覆盖率和库存周转数据状态。

## 决策

- 成本缺失的型号不参与“已确认毛利”计算，行级显示 `暂无数据`；总 KPI 显示已确认毛利率和成本覆盖状态，不将缺失成本按零处理。
- 库存周转接口输出 `inventory_turnover_status=unavailable`、原因和展示标签 `45天（固定回退标签）`；前端保留该标签，直到未来库存与 COGS 字段补齐。
- 综合毛利率使用总毛利除以总销售额，不平均各型号毛利率；价格或成本覆盖不完整时标记 `partial`。

## 范围

- 包含：baseline summary 的成本/价格覆盖和库存状态、前端型号毛利、综合毛利率、库存卡片和日志。
- 不包含：新增库存数据采集、未来 COGS 预测、真实周转公式；数据补齐后另行替换状态分支。

## 环境预检

- 必需 Shell：git-bash
- 必需命令：`backend/.venv/Scripts/python.exe`、`npm`
- 必需端口：无
- 必需 URL：无
- 必需 Python 模块：`pytest`、`sqlalchemy`
- 必需 Docker 容器：无
- 容器内必需命令：无
- 容器内必需 Python 模块：无
- 执行画像：normal
- 启动超时（秒）：10
- 空闲超时（秒）：30
- 硬截止（秒）：180
- 最大 checkpoint 间隔（秒）：45
- 预检命令：
  ```bash
  python C:/Users/jie32.guo/.codex/skills/plan-generator/scripts/preflight.py check --plan docs/plans/T24-margin-inventory-metrics-2026-09-04.md --format json
  ```

## 风险与回滚

- 风险：成本覆盖不足会使部分型号毛利不可确认，影响达成卡片的数值完整性；通过覆盖率和状态标签显式提示，不隐藏缺口。
- 回滚：恢复旧 KPI 计算和库存标签；保留新增字段以便后续数据源接入，不删除成本或库存原始数据。

## 实施步骤

### 步骤 1：输出覆盖和库存状态
- 对象：`load_baseline` summary 和前端 baseline 类型。
- 动作：加入价格数量覆盖、成本数量覆盖、毛利状态和库存周转状态字段。
- 参数：缺少未来期末/平均库存或 COGS 时 `inventory_turnover_days=null`，`inventory_turnover_label="45天（固定回退标签）"`，`inventory_turnover_status="unavailable"`。
- 核心修改文件：`backend/src/app/services/whatif_workbench.py`、`frontend/src/api.ts`
- 必要集成文件：`backend/tests/test_attribution_whatif_service.py`
- 命令：
  ```bash
  backend/.venv/Scripts/python.exe -m pytest -q backend/tests/test_attribution_whatif_service.py
  ```

### 步骤 2：修正型号和顶部毛利计算
- 对象：`rowMetrics`、`computeKpi`、毛利 KPI 与矩阵列。
- 动作：成本为空返回 null；已确认毛利按有效明细计算；综合毛利率使用总毛利/总销售额；显示成本覆盖状态。
- 参数：完整覆盖显示百分比；部分覆盖显示百分比和“部分数据”；无有效成本显示 `暂无数据`；销售额为 0 时不除零。
- 核心修改文件：`frontend/src/pages/WhatIfPage.tsx`
- 必要集成文件：无
- 命令：
  ```bash
  cd frontend && npm run build
  ```

### 步骤 3：接入库存回退标签
- 对象：库存周转 KPI 卡片和运行日志。
- 动作：读取 summary 状态并显示固定回退标签及原因，不再显示无标识的 `45 天`。
- 参数：标签精确为 `45天（固定回退标签）`；原因文案说明缺少未来库存与 COGS；真实 days 字段存在时优先显示数值。
- 核心修改文件：`frontend/src/pages/WhatIfPage.tsx`
- 必要集成文件：无
- 命令：
  ```bash
  rg -n "45天（固定回退标签）|inventory_turnover_status|cost_coverage" frontend/src/pages/WhatIfPage.tsx backend/src/app/services/whatif_workbench.py
  ```

## 完成标准
- 验收类型：mixed
- 离线验收命令：
  ```bash
  cd backend && .venv/Scripts/python.exe -m pytest -q tests/test_attribution_whatif_service.py
  cd ../frontend && npm run build
  ```
- 外部环境验收命令：打开 What-if 页面加载一个版本，验证缺成本型号毛利显示 `暂无数据`，库存显示固定回退标签，日志出现成本/价格覆盖率。
- 通过条件：缺失成本不进入总毛利；毛利率分母为总销售额；库存卡片不再显示无标识的固定天数；构建和测试退出码为 0。
