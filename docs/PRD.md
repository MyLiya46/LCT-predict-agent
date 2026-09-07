# PRD：LCT Predict Agent 销售预测与分析工作台

> 版本：v1.0
> 日期：2026-09-07
> 文档状态：基于当前代码与数据事实重写
> 适用范围：内部私有化部署的业务分析、预测、归因和 What-if 决策工作台

本文替代旧版《通用 AI Agent 平台（内部人机对话助手）》PRD。旧版以通用平台骨架为主，已经不能准确描述当前产品的数据边界、模型结果缓存、工作台页面和 HTTP API。

本文以以下资料为事实依据：

1. docs/prd_workbench.md：工作台业务心智模型和计算口径；
2. docs/data-inspect.md：开发期数据来源、PG 落点、数据完整性和已知限制；
3. backend/src/app/api/：当前注册的 FastAPI 路由、权限和请求模型；
4. docs/api-contract.md：当前 HTTP 字段、返回结构和实现限制的详细契约。

本文中的“已实现”表示当前 API 或服务已有对应实现；“迁移中”表示代码已有部分能力，但尚未满足统一数据事实或发布验收；“目标”表示产品必须达到的行为。

---

## 1. 产品定义

### 1.1 产品定位

LCT Predict Agent 是面向内部业务人员的销售预测与分析工作台。它把历史销售事实、未来预测、预测归因、价格 What-if 和策略优化放在同一条 SKU 月度时间轴上，并提供自然语言入口和可追溯执行过程。

产品的最小业务单元是：

~~~text
SKU × 渠道 × 月份
~~~

没有渠道维度时退化为 SKU × 月份。历史和未来不能被拆成两个互不相干的页面：历史销售提供背景，预测提供 baseline，归因解释预测变化，What-if 和优化在 baseline 上评估有限策略。

### 1.2 用户价值

用户完成一次分析时，应能够回答以下问题：

- 过去某个品类、SKU、渠道和月份实际卖了多少、卖了多少钱？
- 某个预测版本未来数月预计卖多少、使用什么价格？
- 预测结果相对历史基线为什么变化？哪些因子贡献最大？
- 如果采用某种价格或流量策略，销量、销售额和毛利会怎样变化？
- 在销量或销售额目标下，系统推荐哪一个有限策略？
- 这些数字来自哪一份数据、哪个预测版本、哪个工具调用？

### 1.3 本期目标

| 目标 | 验收方向 |
|---|---|
| 建立统一数据事实 | 七张开发基座表同步并标准化到 PostgreSQL；业务查询、模型输入和 What-if 基线优先使用 PG |
| 提供可用分析工作台 | 支持数据集浏览、筛选、分页表格、预测趋势和结果详情 |
| 打通预测到归因 | 预测结果和归因结果按版本、月份、SKU、渠道写入/同步为 PG 结果缓存 |
| 提供规则式决策模拟 | 基于预测 baseline 执行有限策略模拟和离散策略搜索，不重新训练预测模型 |
| 提供自然语言入口 | Chat 可以复用同一套 PG 语义数据、预测、归因、模拟和优化能力 |
| 保留全过程证据 | 用户看到执行状态和结构化结果；追溯事件能够还原工具、入参、结果和错误 |
| 保证内部数据隔离 | 普通用户只能访问自己的会话和追溯；管理员操作可审计，敏感配置脱敏 |

### 1.4 非目标

本期不将以下能力描述为已交付范围：

- 公网开放、计费、开放注册市场、多租户隔离；
- 业务用户直接连接任意 SQL 数据库；
- 文档 RAG、知识库问答和通用插件市场；
- What-if 过程中重新训练或重新运行预测模型；
- 把归因结果宣传为严格因果效应；
- 没有未来库存和 COGS 数据时计算真实库存周转或库存优化；
- 连续空间中的全局最优定价；
- 通过上传文件临时改变任意历史事实而不产生版本和审计；
- 将当前接口中的占位字段、历史兜底价或模型任务结果误称为完整业务事实。

### 1.5 产品原则

1. **一个事实源**：开发期 CSV/XLSX 是导入渠道，启动同步后的业务事实源是 PostgreSQL。
2. **结果不反推**：预测和归因读取已经写入 PG 的模型结果缓存，不从历史表临时反推预测结果。
3. **粒度先于展示**：关联前先按各数据源自身粒度去重或聚合，再用 LEFT JOIN 形成 SKU 月度视图。
4. **缺失可见**：价格、成本、弹性和毛利必须带覆盖率、来源或状态，缺失不能静默变成 0 或假装完整。
5. **对话与页面同源**：Chat 返回的数字、表格和图表必须来自页面使用的语义数据和服务。
6. **可追溯优先**：每次预测、工具调用、上游失败和管理员查看都能够定位到请求、用户和时间。

---

## 2. 用户、角色与核心流程

### 2.1 角色

| 角色 | 主要任务 | 数据范围 |
|---|---|---|
| 业务分析人员 | 浏览历史、查看预测、阅读归因、运行 What-if、通过 Chat 提问 | 自己的会话；业务数据按产品授权范围使用 |
| 预测/定价人员 | 选择版本和 SKU，比较计划价、模拟策略和目标差距 | 与分析人员相同，重点使用预测、归因和 What-if 页面 |
| 技术管理员 | 管理用户、数据源、工具、场景、LLM provider 和系统参数；排查执行链路 | 全量会话和审计只读查询；管理动作写审计 |
| 平台运维人员 | 维护 PostgreSQL、模型服务、Agent 网关、What-if 服务和沙箱 daemon | 通过健康检查、日志和部署配置操作，不绕过应用权限读取业务数据 |

### 2.2 用户端主流程

#### 流程 A：历史数据分析

1. 用户打开工作台并选择数据集；
2. 通过品类、渠道、SKU、月份、系列、版本或状态筛选；
3. 读取分页表格，必要时查看图表；
4. 历史价格按有效销量和销售额派生；
5. 用户可将同一问题发送给 Chat，Chat 返回同源表格、图表或摘要。

#### 流程 B：预测和归因

1. 用户选择品类、预测月份、渠道/SKU、预测窗口；
2. 提交预测任务或通过 Chat 发起预测；
3. 模型完成后，后端校验预测和归因行并 relay 到 PG；
4. 工作台按版本读取 fcst_detail；
5. 归因页按版本和 SKU 读取 attribution_analysis_rows；
6. 用户查看预测曲线、历史对照、因子 waterfall 和趋势。

#### 流程 C：What-if 和策略优化

1. 用户选择品类和预测版本；
2. 后端从 PG 加载 baseline、价格、成本和弹性覆盖状态；
3. 用户读取有效策略目录；
4. simulate 对 baseline 明细应用一个有限策略；
5. optimize 在有限策略目录中搜索接近目标的方案；
6. 用户查看任务进度、结果、假设、来源和覆盖率。

#### 流程 D：可追溯 Chat

1. 用户在会话中发送自然语言；
2. Agent 判断历史、预测、归因、模拟或优化意图；
3. Agent 调用内部工具并把结构化结果投影为统一 envelope；
4. 前端通过同步接口或 SSE 显示文本、状态、工具步骤和最终表格/图表；
5. 用户可以打开追溯面板或导出 Markdown 报告。

### 2.3 管理流程

管理员登录后可以：

- 创建、停用或测试内部数据源；
- 注册、修改、停用和测试工具；
- 修改场景的提示词、模型引用和启用状态；
- 管理 LLM provider、默认模型、fallback 和健康状态；
- 管理用户和密码；
- 查询会话、消息、trace、审计记录和管理员实时流；
- 修改允许热更新的系统参数。

会话、消息、trace、审计查询和管理员实时流属于查看审计范围，应写入 audit.view；查看行为不应改变业务会话和消息。

---

## 3. 数据基座和事实边界

### 3.1 目标数据流

~~~text
CSV/XLSX 开发期输入
    → 读取、校验、标准化、版本化导入
    → PostgreSQL 七张基座表
          ├─ 工作台数据集查询
          ├─ 预测模型输入
          └─ What-if baseline 和参考参数

预测模型
    → fcst_forecast_result / fcst_attribution
    → backend relay：版本替换 + 行数/字段校验
    → fcst_detail / attribution_analysis_rows
          ├─ 预测页
          ├─ 归因页
          ├─ Chat 内部工具
          └─ What-if baseline

用户请求
    → FastAPI API / Chat façade
    → PG 语义查询或模型/What-if 上游
    → 结构化 envelope、SSE 状态和追溯事件
~~~

文件只负责提供开发期或受控上传的输入。业务接口不得在请求处理中自行打开 CSV/XLSX，也不能在字段缺失时临时切换到另一套未标准化字段。

### 3.2 当前迁移状态

当前代码已提供 workbench_sync_on_startup 和 seed_workbench，但默认配置关闭；seed_workbench 仍存在 ROW_CAPS，模型 loader 仍有直接读取 CSV 的路径。因此当前 PG 快照只能视为开发样本，不能宣称为七张基座的完整业务事实。

发布前必须完成：

- 将正式启动同步设为明确的部署入口，并在同步失败时阻止服务使用陈旧缓存；
- 取消各数据集导入行数截断，保留源行数、导入行数和校验结果；
- 统一模型输入 loader，从 PG 标准化数据读取；
- 对预测和归因 relay 执行版本、月份、SKU、渠道和行数的一致性校验；
- 使用版本化、原子替换，避免半版本数据被页面或 What-if 读取；
- 将成本和价格弹性参考数据纳入同一套可追溯导入流程。

### 3.3 七张开发基座表

| dataset | 主要来源 | 业务粒度/核心字段 | 主要用途 |
|---|---|---|---|
| raw_data | ads_cbg_rt_fcst_retail_stat.csv | 品类 × SKU × 渠道 × 月份；period_id、category_name、product_mode_code、channel_name_l3、retail_qty、retail_amt | 历史销量、销售额和历史均价 |
| master_data | tof_fcst_product_info.csv | 品类 × SKU × 渠道；product_series、product_status 等 | 系列、在售状态、生命周期和预测特征 |
| price_data | tof_fcst_product_plan_price.csv | 品类 × SKU × 月份 × 版本；min_price_n…n6、daily_price_n…n6；当前没有渠道键 | 未来计划价和价格展开 |
| dsi_data | dwd_cbg_sl_tb_fcst_dsi_price_detail.csv | 模型所需的原始粒度 | 预测模型输入；当前不直接进入 SKU 月度 What-if 关联 |
| rebate_data | dwd_cbg_sl_tb_fcst_channel_rebate_detail.csv | 品类/渠道/产线等粒度，无稳定 SKU 月度键 | 预测模型输入；不直接计算 SKU 毛利 |
| cost_data | data/reference/cost_data.xlsx | 品类 × SKU；品类、型号、成本价；当前无月份和渠道 | 毛利、What-if 和策略优化 |
| price_elasticity | data/reference/price_elasticity.xlsx | 品类 × 系列 × SKU；价格弹性系数、弹性分类；当前无月份和渠道 | What-if 和策略优化 |

工作台数据集列表还包含输出数据集 fcst_detail。归因结果使用独立的语义表和 /api/attribution 查询，不把归因结果误计入七张输入基座表。

### 3.4 预测与归因输出缓存

| 输出 | 上游事实 | PG 落点 | 查询粒度 |
|---|---|---|---|
| 预测明细 | fcst_forecast_result | relay 到 fcst_detail | 版本 × 品类 × SKU × 渠道 × 月份 × horizon |
| 归因因子 | fcst_attribution | relay 到 attribution_analysis_rows | 预测基础粒度 × 因子 |

预测查询至少需要版本、预测月份、品类、渠道、SKU、final_value、预测价/计划价和状态。归因查询至少需要版本、horizon、SKU、预测值、滞后销量、因子层级、因子名、影响量、类型汇总和贡献比例。

归因字段口径：

- shap_value 是单个因子对预测销量的影响量，单位为台；
- type_impact 是同一 SKU/月/因子类型的影响量合计；
- contribution_pct 是影响量绝对值占比；
- value_T 和 value_T_1 是解释影响的当期值和基准值，不是影响量；
- 标准化输出应使用 impact_qty，并由 factor_layer + factor_name 生成稳定 factor_id；
- 当前没有完整的 delta_price，因此不能声称已经支持完整的价格归因。

### 3.5 计算口径

~~~text
历史均价 = sum(retail_amt) / sum(retail_qty)       （有效销量大于 0）
预测销售额 = forecast_qty × forecast_price
模拟销售额 = sim_qty × sim_price
毛利 = (price - cost_price) × qty
~~~

毛利、毛利率和库存指标必须同时返回覆盖率或状态：

- price_coverage：有价格的数量覆盖；
- cost_coverage：有成本的数量覆盖；
- gross_coverage：价格和成本同时存在的数量覆盖；
- price_status、cost_status、gross_profit_status：完整、部分或缺失；
- 缺少未来库存和 COGS 时，inventory_turnover_days 必须为 null，并标记不可用原因，不能使用占位文本作为真实指标。

### 3.6 未来价格解析规则

未来价格必须按以下优先级解析，并在明细中保留来源：

1. 同版本、同 SKU、同月份、同渠道的 forecast_price 或 plan_price；
2. 展开后的同版本 SKU/月 price_data 计划价；
3. 无渠道计划价，标记 channel_fallback；
4. 历史最后有效渠道价；
5. 历史最后有效 SKU 价；
6. 无法匹配时返回 null。

每条结果必须带 price_source、price_base_month、price_status 和 coverage。当前实现存在“先使用历史最后有效价，再尝试预测价/计划价”的风险，发布前必须修正，防止历史兜底覆盖未来计划价。

### 3.7 价格弹性导入责任

目标责任边界如下：

~~~text
模型服务读取并校验 price_elasticity.xlsx
    → 标准化、版本化、原子替换 PG price_elasticity
    → backend 只从 PG 读取弹性
    → backend 将弹性参数放入 simulate/optimize 请求
    → What-if 服务执行计算
~~~

运行时不允许 backend 重新读取 Excel，也不允许模型在缺字段时临时回退到 Excel。当前实现仍是模型参考 API 读取文件、backend 拉取并写 PG 的迁移形态，需在发布前收敛到上述责任边界。

---

## 4. 功能范围和优先级

### 4.1 P0 发布范围

| 编号 | 功能 | 当前状态 | 发布要求 |
|---|---|---|---|
| P0-01 | 认证、JWT、刷新、登出、密码和昵称 | 已实现 | access/refresh 轮换、内部邮箱白名单、密码策略和脱敏必须可用 |
| P0-02 | 普通用户/管理员 RBAC | 已实现 | 路由权限、资源 owner 校验和 admin 前缀保护同时生效 |
| P0-03 | 七表数据同步和工作台浏览 | 迁移中 | 取消行数截断，PG 快照完整且可分页遍历 |
| P0-04 | 预测运行、任务查询、模型健康 | 已实现 | wait=true 完成 relay 并验证行数；失败不得返回假成功 |
| P0-05 | 预测结果展示 | 已实现 | 读取 fcst_detail，支持版本、月份、SKU、渠道筛选 |
| P0-06 | 归因列表、详情、趋势和 waterfall | 已实现 | 缺失值使用 null；明确当前不支持完整价格归因 |
| P0-07 | What-if baseline、策略、模拟和优化 | 已实现/迁移中 | 读取 PG baseline，价格来源和覆盖状态透明，任务结果可追踪 |
| P0-08 | Chat façade、SSE、结构化结果 | 已实现 | 与工作台同源，支持 history/forecast/attribution/simulation/optimization |
| P0-09 | 原生追溯、会话流和 Markdown 导出 | 已实现 | 事件可还原工具调用、结果、错误、停止和完成状态 |
| P0-10 | 管理员治理和运维健康 | 已实现/部分占位 | 管理操作留痕；审计导出明确标记为未实现 |

### 4.2 P1 计划

- 归因价格变化字段 delta_price 和稳定的价格影响拆解；
- 成本、弹性增加有效期和渠道口径；
- 未来库存、COGS、库存周转和库存约束优化；
- What-if 场景、策略、baseline 版本和结果持久化到 PG；
- 工作台除 fcst_detail 外的通用图表查询；
- 真正生效的分页游标和后台筛选；
- 审计文件导出；
- 完整的参考数据版本管理、导入报告和回滚；
- 面向更多业务品类和更多模型 provider 的场景化编排。

### 4.3 明确不在本期展开

任何需求如果会引入公网开放、跨租户数据、任意 SQL、文档 RAG、连续定价求解或未验证的因果结论，应单独立项，不得在 P0 需求中隐式扩张。

---

## 5. 用户端功能需求

### 5.1 工作台数据浏览

工作台必须提供数据集目录、数据集说明、筛选器、分页表格和必要的结果图表。

当前数据集目录：

| key | 展示名称 | 分组 | 当前支持的主要筛选 |
|---|---|---|---|
| raw_data | 零售统计 | input | category、channel、sku、period |
| master_data | 产品主数据 | input | category、sku、version、status |
| price_data | 计划价格 | input | category、sku、version、period |
| rebate_data | 渠道返利 | input | category、channel、product_line |
| dsi_data | DSI 价格 | input | category、channel、sku、period |
| cost_data | 商品成本 | input | category、sku |
| price_elasticity | 价格弹性表 | whatif | category、series、sku |
| fcst_detail | 预测明细 | output | category、channel、sku、period、series、version、status |

功能要求：

1. 先调用数据集目录，再按数据集加载 filter options；
2. 表格查询使用 page/page_size，默认 50，最大 200；
3. 返回固定优先列和当前 payload 中出现的字段；
4. 空值保持空值，不能用 0 代替；
5. charts 当前只对 fcst_detail 提供月份、预测数量和销售额序列；其他数据集暂返回明确的业务错误；
6. “全量查看”表示可以通过分页遍历完整快照，不要求单次响应返回全部行；
7. 筛选字段必须与数据集粒度一致，不能把没有渠道键的计划价、成本或弹性伪装成渠道事实。

对应 API：

- GET /api/workbench/datasets
- GET /api/workbench/filter-options/{dataset}
- GET /api/workbench/tables/{dataset}
- GET /api/workbench/charts/{dataset}
- GET /api/workbench/knowledge/strategy
- POST /api/workbench/upload/cost_data

成本上传只接受 CSV/XLSX，经模型参考接口校验后同步 PG；模型已接受但 PG 同步失败时必须返回失败状态，不能显示为同步成功。

### 5.2 预测

预测运行参数：

| 参数 | 要求 |
|---|---|
| category | 必填、非空 |
| forecast_month | 可选，传给模型 |
| wait | 默认 true |
| channel、sku | 可选过滤 |
| start、end | 可选模型范围 |
| horizon | API 默认 7，范围 1 至 7 |
| intent | 可选业务意图 |

行为要求：

- 模型未启用或上游失败时返回 502 业务错误；
- wait=true：等待模型完成，relay 预测、归因和历史行，再返回版本、任务、relay 计数和 fcst_detail 表格；
- relay 行数不足或版本不一致时，整个运行判定失败；
- wait=false：只返回任务信息，调用方通过任务接口和工作台查询后续状态，不得假定结果表已经有数据；
- 同一业务版本的预测和归因必须可通过 system_forecast_number 关联；
- 离线 XLSX 只允许读取 output 目录内的安全文件名，禁止路径穿越。

对应 API：

- POST /api/forecast/runs
- GET /api/forecast/tasks/{task_id}
- GET /api/forecast/model/health
- POST /api/forecast/extract

### 5.3 归因

归因页按品类、版本、SKU 和可选渠道/月份展示：

- 预测值 y_pred 与滞后销量 qty_lag1；
- 因子详情、因子类型汇总和 waterfall；
- 历史/预测趋势，缺失月份使用 null；
- 因子名称、层级和影响量；
- 当前数据是否包含价格影响，不能用其他因子代替。

对应 API：

- GET /api/attribution/options
- GET /api/attribution/skus
- GET /api/attribution/detail
- GET /api/attribution/trend

detail 没有匹配数据时可以返回 HTTP 200，但必须返回 ok=false 和可理解的错误信息；前端不得把它当作零影响。

### 5.4 What-if 模拟和策略优化

#### Baseline

GET /api/whatif/baseline 必须以 PG 中选定版本的预测销量为 baseline，保留 SKU、渠道、月份和 horizon 明细。响应至少包含：

- baseline 数量、金额和月份序列；
- 价格、成本、毛利覆盖率；
- 每条明细的价格来源、基准月份和匹配状态；
- 弹性命中情况；
- 缺库存数据时的不可用状态。

当前接口参数为 category、version 必填，period 可选，limit 默认 200 且最大 200。产品要支持完整分析时，应补充可遍历的分页或场景快照，而不是让用户误以为 200 行就是全量。

#### Simulate

用户先从 GET /api/whatif/strategies 选择有效策略，再提交：

- rows：至少一条 baseline 行；
- strategy_id：必填；
- param：策略参数；
- traffic_tier：可选流量层级。

接口当前返回 task_id 和 status，用户通过任务接口读取结果。策略应用于 baseline 的月份/渠道明细后，结果应包含 sim_qty、sim_price、sim_amount、毛利、价格来源和 coverage。

#### Optimize

用户提交：

- rows：至少一条 baseline 行；
- target_qty：必填；
- target_revenue：可选且不得小于 0；
- param、traffic_tier：可选。

优化是有限策略目录上的离散搜索，不是连续价格优化。结果必须展示推荐策略、目标值、baseline 对比、销量/销售额/毛利变化和假设。

对应 API：

- GET /api/whatif/strategies
- GET /api/whatif/baseline
- POST /api/whatif/simulate
- POST /api/whatif/optimize
- GET /api/whatif/tasks/{task_id}

What-if 上游异常返回 HTTP 502。由于 What-if 代理接口当前返回裸 JSON，前端必须同时处理统一错误壳和上游裸 detail。

### 5.5 Chat 工作台

工作台使用 /api façade，原生追溯使用 /api/v1/chat，两套协议不能混用。

Chat 请求字段：

| 字段 | 说明 |
|---|---|
| message | 1 至 65536 个字符，去空白后不能为空 |
| session_id | 可选，省略时创建会话 |
| params | 预留参数；当前 bridge 不读取，不能当作已生效的业务筛选 |
| oa | 传给 Agent 上游的 OA 标识 |
| access_token | 传给 Agent 上游的 token，不是本地 JWT |

成功 envelope 的 response_type 当前包括：

- history：历史事实、指标、序列和表格；
- forecast：预测版本、预测点、月度汇总和任务信息；
- attribution：预测值、因子、waterfall 和趋势；
- simulation：策略模拟结果；
- optimization：策略推荐和目标对比；
- report：综合文本或分析报告。

结构化结果必须提供稳定的 table、chart 或领域字段，不能只把 JSON 拼到 markdown 中。Chat 使用和页面相同的 PG 查询及上游服务，不得另造一份销售数据。

### 5.6 会话、停止和追溯

会话功能：

- 新建、列表、详情、重命名、删除；
- 置顶和取消置顶；
- 消息列表和消息发送；
- 同一会话运行中拒绝第二个并发流程；
- Idempotency-Key 防止重复提交；
- 用户停止运行后，已完成工具结果保留，未完成结果不能伪装为成功。

追溯面板至少显示：

~~~text
用户消息
  → Agent 规划/状态
  → tool_call：工具名、入参、计划序号
  → tool_result：结构化摘要、耗时、状态
  → tool_error：错误码、重试次数、错误信息
  → done：最终文本、状态和可选 token usage
~~~

用户可以获取单条消息 trace 或下载 Markdown；管理员可以按 trace、工具、错误码和用户查询并实时查看会话。

### 5.7 账户和个人设置

- 邮箱+密码注册只接受白名单后缀；
- 登录返回 access token、refresh token、过期时间和用户信息；
- access token 默认 15 分钟，refresh token 默认 7 天并轮换；
- 邮箱只读，不提供修改入口；
- 用户可以修改昵称和密码；
- 密码至少 10 位，满足大小写字母和数字策略；
- 登录、刷新、注销、权限拒绝和管理员修改密码应有必要审计，绝不记录密码、JWT 或 API key。

---

## 6. Agent 执行与工具编排

### 6.1 执行循环

~~~text
接收消息
    → 校验会话 owner、幂等键和并发状态
    → Agent 判断意图和缺失参数
    → 调用内部工具或受控 sandbox 工具
    → 校验工具结果并写 trace event
    → 结果回灌或重试/降级
    → 结果投影为 envelope
    → 持久化 assistant 消息和完成事件
    → 通过 JSON 或 SSE 返回
~~~

Agent 不应直接访问未经授权的数据库表或文件；工具通过服务层读取 PG 或调用受控上游。工具失败应返回结构化错误或 need_input，不要让模型猜测缺失的品类、版本、SKU 或策略。

### 6.2 当前内部工具

当前默认场景可调用 8 个 internal 工具：

| 工具 | 用途 | 关键输入 | 主要输出 |
|---|---|---|---|
| get_history | 查询历史/实际销量 | category，sku/channel/start/end 可选 | history envelope、指标、序列、行和 Top SKU |
| submit_forecast | 发起预测 | category；forecast_month/horizon 可选 | forecast envelope、version、task、relay |
| get_task_status | 查询模型或 What-if 任务 | task_id | 状态、进度、结果或错误 |
| get_forecast_result | 读取已完成预测 | system_forecast_number、horizon | 预测点、月度汇总和 Top SKU |
| get_attribution | 查询 SKU 归因 | version、category、sku、period 可选 | attribution envelope、waterfall、因子和趋势 |
| get_whatif_strategies | 读取策略目录 | status 可选 | 有效策略、参数类型和默认参数 |
| simulate | 执行规则式模拟 | version、category、策略和筛选条件 | simulation envelope、baseline 和任务结果 |
| optimize | 选择有限策略 | version、category、目标和策略参数 | optimization envelope、目标差距和假设 |

工具语义约束：

- get_history 只能回答历史事实，不用预测值冒充实际销量；
- 预测结果必须带版本和来源工具；
- 归因不把 shap_value 等同于因果效应；
- simulate/optimize 必须使用同一版本 baseline；
- 工具结果中的价格必须保留来源和状态；
- 缺参数时返回 need_input、missing 和候选项；
- 结果投影不得丢失 source_tool、version、category、SKU、period 和任务标识。

### 6.3 工具注册和 sandbox

管理员工具接口支持 internal 和 sandbox 两类执行方式：

- internal 工具在后端进程内执行；当前 8 个默认业务工具均属于此类；
- sandbox 工具进入受控 daemon，使用固定镜像、handler、超时、资源和内网出网白名单；
- 工具 input schema 必须是封闭 JSON Schema，禁止未声明字段；
- 数据源凭据通过受控引用注入，不能出现在 tool result、SSE 或审计详情；
- 当前平台默认并发上限 3、超时默认 30 秒，实际值可由管理员系统参数调整。

---

## 7. HTTP API 产品契约

### 7.1 路由分层

| 领域 | 路径 | 主要权限 | 响应特点 |
|---|---|---|---|
| 认证 | /api/v1/auth/* | 登录相关例外，其余需登录 | JSON 使用 {code,message,data} |
| OA 登录 | /api/auth/login | 无本地 JWT | 裸 JSON，包含 OA 上游 token |
| 原生会话/消息 | /api/v1/chat/* | chat:read/send/stop/delete、trace:read | JSON 统一壳；SSE 和 Markdown 导出除外 |
| 工作台 Chat façade | /api/sessions、/api/chat* | chat:read/send/delete | 裸 JSON；/api/chat/stream 使用 façade SSE |
| 工作台数据 | /api/workbench/* | chat:read；上传需要 chat:send | 裸 JSON |
| 预测 | /api/forecast/* | chat:read/send | 裸 JSON；上游错误为统一 502 业务错误 |
| 归因 | /api/attribution/* | chat:read | 裸 JSON |
| What-if | /api/whatif/* | chat:read/send | 裸 JSON；上游错误为 HTTP 502 detail |
| 管理 | /api/v1/admin/* | 管理员 + 具体 admin 权限 | JSON 使用统一壳 |
| 运维 | /healthz、/readyz、/api/health/agent | 无需鉴权 | 裸 JSON |

当前完整字段以 docs/api-contract.md 和 OpenAPI 为准；本节只定义产品分层和必须保持的语义。

当前关键操作清单：

- 认证：/api/v1/auth/register、login、me、refresh、logout、password、me；OA 登录为 /api/auth/login；
- 原生会话：/api/v1/chat/conversations 及其 messages、stream、trace 和 trace/export；
- 工作台 façade：/api/sessions、/api/chat、/api/chat/stream、/api/products、/api/agent/probe/template、/api/agent/probe；
- 管理：/api/v1/admin/datasources、tools、scenarios、llm、sessions、messages、traces、audits、users、config；
- 健康：/healthz、/readyz、/api/health/agent。

### 7.2 通用请求头和错误

| Header | 用途 |
|---|---|
| Authorization: Bearer access_token | 受保护接口 |
| X-Request-Id | 可选请求关联 ID；服务端未提供时生成并回写 |
| Idempotency-Key | 原生/ façade 消息发送幂等 |
| X-Refresh-Token | /api/v1/auth/logout 注销 refresh token |

统一错误码：

| code | HTTP | 语义 |
|---|---:|---|
| 400_VALIDATION | 400 | 业务参数或规则错误 |
| 401_UNAUTHORIZED | 401 | 未登录、token 无效或凭据错误 |
| 403_FORBIDDEN | 403 | 权限不足，并写权限拒绝审计 |
| 404_NOT_FOUND | 404 | 资源不存在或 owner 不匹配 |
| 409_CONFLICT | 409 | 并发流程、重复资源或状态冲突 |
| 500_INTERNAL | 500 | 未处理后端错误 |
| 502_UPSTREAM | 502 | 模型、参考服务或同步服务不可用 |
| 429_RATE_LIMIT | 429 | 预留的限流/登录锁定语义 |
| 501_NOT_IMPLEMENTED | 200 | 当前仅用于审计导出占位响应 |

FastAPI/Pydantic 结构校验仍可能返回原生 422。所有时间使用 ISO 8601 字符串或 null，字段保持 snake_case。

### 7.3 SSE

原生消息级流：

GET /api/v1/chat/conversations/{cid}/messages/{mid}/stream

可能事件：

| event | 内容 |
|---|---|
| message.delta | 文本增量 |
| agent.process / agent.status | 规划和执行状态 |
| tool.call | 工具名、入参、计划序号、request_id |
| tool.result | 工具名、结果摘要、耗时和状态 |
| tool.error | 工具名、错误码、消息、重试次数 |
| done | 消息 ID、最终文本、完成状态和可选 usage |
| error | 统一错误码和消息 |
| follow_up.suggestions | 后续建议 |

工作台 façade 流：

POST /api/chat/stream

只使用以下四类帧：

| event | 内容 |
|---|---|
| delta | {text} |
| status | 当前阶段、文本和步骤 |
| result | 与 /api/chat 相同的最终 envelope，并附 steps |
| done | {ok}，只表示流结束 |

会话级流会先回放最近事件，再发送 session.meta，随后推送实时 session.pack。管理员会话流只读且建立连接即写 audit.view。

### 7.4 API 实现边界

当前接口可联调，但下列参数或能力仍不能作为已完成能力使用：

- 原生会话/消息的 cursor 当前未真正分页；
- /api/sessions 固定最多返回 100 条；
- 部分 admin 查询参数尚未生效；
- /api/chat 的 params 当前未被 bridge 读取；
- /api/agent/probe 只返回本地配置状态，不真正转发探测请求；
- wait=false 预测返回时，工作台 table 可能为空；
- /api/workbench/charts 当前仅支持 fcst_detail；
- /api/v1/admin/audits/export 只是 P1 占位，不生成文件；
- What-if baseline 的库存周转字段当前始终不可用；
- 数据源 PATCH 对 credential 和 whitelist 的落库行为尚未完整；
- What-if 上游错误体与其他领域的统一错误壳不一致。

这些限制必须在前端提示、联调文档和发布验收中显式处理。

---

## 8. 权限、安全与审计

### 8.1 权限矩阵

| 权限点 | 普通用户 | 管理员 | 典型接口 |
|---|---:|---:|---|
| chat:read | ✓ | ✓ | 会话读取、工作台、预测任务、归因、What-if 读取 |
| chat:send | ✓ | ✓ | 发送消息、预测运行、模拟/优化、成本上传 |
| chat:stop | ✓ | ✓ | 停止消息 |
| chat:delete | ✓ | ✓ | 删除自己的会话 |
| trace:read | ✓ | ✓ | 自己消息追溯 |
| adm:tool.manage | — | ✓ | 数据源、工具、场景 |
| adm:llm.manage | — | ✓ | LLM provider |
| audit:read | — | ✓ | 全量会话、trace、审计和管理员流 |
| adm:user.manage | — | ✓ | 用户和密码 |
| adm:config.manage | — | ✓ | 系统参数 |

### 8.2 数据和资源隔离

- 普通用户的会话、消息、trace 必须按 owner 查询；
- owner 不匹配和资源不存在统一返回 404，不泄露资源存在性；
- 管理员可以只读查看未删除的全量会话；
- 按当前审计实现，管理员查看会话、消息、trace、审计列表和管理员会话流写 audit.view；
- 软删除会话不应继续出现在普通列表，历史消息状态按实现转为 failed；
- 同一会话不能并发运行多个活动流程。

### 8.3 凭据和网络

- API key、数据源 credential、JWT、OAuth token 和密码禁止写入日志、trace、SSE 或响应列表；
- 管理列表只返回掩码，例如 ***；
- sandbox 只能访问内网白名单和明确允许的目标；
- OA 上游 token 只能在受信任流程中转发，不能展示；
- forecast/extract 必须防止路径穿越，只能读取 output 目录；
- 生产环境配置从环境变量或密钥系统注入，不提交 .env、凭据和数据 dump。

---

## 9. 技术架构和部署要求

### 9.1 组件

~~~text
React/Vite 工作台
    │ JSON / SSE
FastAPI backend
    ├─ auth / RBAC / admin / audit
    ├─ chat native + chat façade
    ├─ workbench / attribution / what-if API
    ├─ forecast client + relay
    └─ PG semantic query and result projection
        │
        ├─ PostgreSQL
        ├─ icewash forecast / What-if service
        ├─ Agent LLM gateway or OpenAI-compatible provider
        └─ sandbox daemon
~~~

后端与模型/What-if 服务均通过受控 client 通信。前端不直接访问数据库、模型文件或内部服务。

### 9.2 启动顺序

1. PostgreSQL 可连接并完成 Alembic migration；
2. 执行七张基座表和参考数据同步；
3. 完成必要的字段、行数、版本和唯一键校验；
4. 启动 FastAPI；
5. 验证 /readyz、/healthz 和 /api/health/agent；
6. 验证模型、Agent provider、What-if 服务和 sandbox daemon 的可用状态；
7. 允许前端进入工作台。

当正式同步开启且基座同步失败时，后端必须阻止继续使用陈旧缓存。同步过程应支持原子替换和可审计的版本信息。

### 9.3 配置和健康检查

必需配置包括：

- PostgreSQL URL；
- JWT secret；
- backend 与 sandbox daemon 的内部 token；
- 模型、What-if、Agent gateway 和 LLM provider 的地址及密钥；
- 内网出网白名单；
- 工作台同步开关、超时、并发和保留策略。

健康检查：

- /readyz：数据库可连接才返回 200，否则 503；
- /healthz：聚合 DB、LLM 和 sandbox daemon，返回 ok 或 degraded；
- /api/health/agent：返回 Agent/默认 provider 的可用投影，不暴露密钥；
- /api/forecast/model/health：返回预测模型开关和上游健康状态。

### 9.4 保留、备份和监控

默认系统参数：

| 参数 | 默认值 |
|---|---:|
| retention.conversation_days | 180 |
| retention.audit_days | 365 |
| auth.login_fail_limit | 5 |
| sandbox.max_concurrent | 3 |
| sandbox.timeout_s | 30 |
| conversation.user_max_messages | 48 |

预测版本、基座快照、relay 计数、What-if 任务和审计记录必须能关联。生产环境至少监控数据库连接、上游错误率、任务耗时、SSE 中断、同步行数差异和权限拒绝事件。

---

## 10. 发布验收

### 10.1 数据事实验收

- [ ] 七张基座表均可列出、筛选和分页浏览；
- [ ] 源文件行数与 PG 导入行数有可审计的校验结果；
- [ ] 移除 ROW_CAPS 后，分页可以遍历完整快照；
- [ ] 工作台、模型输入和 What-if baseline 使用同一 PG 标准化数据；
- [ ] 模型不再在业务运行时直接读取 CSV；
- [ ] price_data 宽列已展开为按月份可匹配的长表；
- [ ] 成本和弹性缺失不会被当作 0；
- [ ] 每条未来价格都有 source、base month、status 和 coverage；
- [ ] 预测和归因 relay 为完整版本替换，版本与行数一致。

### 10.2 业务功能验收

- [ ] 历史查询返回真实月份、销量、销售额和派生均价；
- [ ] 预测运行成功后返回 version、task、relay 计数和 fcst_detail；
- [ ] wait=false 的任务可通过任务接口和结果接口继续查询；
- [ ] 归因列表、详情、趋势和 waterfall 可按版本/SKU 查询；
- [ ] 缺失归因返回明确状态，不伪造零影响；
- [ ] What-if baseline 能展示价格、成本、弹性和毛利 coverage；
- [ ] simulate/optimize 使用选定版本的 baseline，不触发预测重算；
- [ ] What-if 结果展示策略、目标差距、价格来源和假设；
- [ ] Chat 的历史、预测、归因、模拟和优化结果与页面数据一致。

### 10.3 交互和追溯验收

- [ ] Chat 同步和 SSE 两种模式均能返回最终 envelope；
- [ ] SSE 能显示 delta、状态、工具调用、工具结果、错误和完成事件；
- [ ] 用户可以停止运行，已完成结果保留，未完成结果不落为成功；
- [ ] Idempotency-Key 不会创建重复消息或重复任务；
- [ ] trace 能还原消息、工具、参数、结果、错误、重试和完成状态；
- [ ] trace Markdown 可以下载；
- [ ] 会话之间上下文隔离，越权访问返回 404。

### 10.4 安全和运维验收

- [ ] 无 token、无权限和失效 token 的返回语义符合契约；
- [ ] admin 接口拒绝普通用户，并写权限拒绝审计；
- [ ] 管理员查看全量数据写 audit.view；
- [ ] API key、credential、密码和 OAuth token 不出现在列表、日志和 trace；
- [ ] /readyz、/healthz、Agent 和预测模型健康检查可用；
- [ ] 数据库、模型、What-if 或 sandbox 不可用时有明确降级和错误；
- [ ] 审计导出未完成时前端显示“未实现”，不能显示下载成功。

---

## 11. 发布门槛与已知差距

| 差距 | 当前事实 | 发布动作 |
|---|---|---|
| PG 不是默认启动事实源 | workbench_sync_on_startup 默认关闭 | 纳入正式启动/部署流程，并在失败时阻止陈旧缓存 |
| 导入仍可能截断 | seed_workbench 有 ROW_CAPS | 取消截断，增加源/目标行数校验 |
| 模型仍有 CSV 读取路径 | dataloader.py 尚未完全 PG 化 | 统一 loader，模型从 PG 标准化数据读取 |
| 弹性导入责任未收敛 | 当前由模型参考 API 读取文件、backend 拉取同步 | 改为模型侧导入 PG，运行时双方只读标准化数据 |
| 未来价格优先级风险 | 当前历史有效价可能覆盖计划/预测价 | 按 3.6 的优先级实现并测试 |
| 价格归因不完整 | 当前没有可靠 delta_price | P1 补齐前不得宣称完整价格归因 |
| 库存指标不可用 | 没有未来库存和 COGS | 继续返回 null/status，不展示为实测值 |
| What-if 结果主要在任务存储 | 场景、策略、baseline、结果尚未形成完整 PG 业务闭环 | P1 建立版本化场景结果表 |
| 部分页/筛选参数只是兼容字段 | 原生 cursor、部分 admin filter 尚未生效 | 在前端禁用误导性控件或补齐后端实现 |
| 图表范围有限 | charts 当前只支持 fcst_detail | 扩展前保持明确错误，不返回空图 |
| 审计导出是占位 | /api/v1/admin/audits/export 返回 501 语义但 HTTP 200 | P1 实现文件导出或保持显式占位 |
| Chat 探测不是实际探测 | /api/agent/probe 只报告本地配置 | 需要真实探测时单独实现安全的白名单探测 |

---

## 12. 风险与决策记录

### 12.1 主要风险

| 风险 | 后果 | 缓解 |
|---|---|---|
| 七表快照不完整 | 页面和模型使用不同样本，预测无法复现 | 同步前后行数、键和版本校验；取消截断 |
| 计划价无渠道键 | 渠道级 What-if 可能误用同一价格 | 标记 channel fallback，展示覆盖状态 |
| 成本/弹性无有效期 | 长期分析可能使用过期参考值 | P1 增加有效期/版本/渠道口径 |
| 归因字段语义混淆 | 用户将解释结果当作因果结论 | 统一 impact_qty，并在 UI 标注解释性 |
| 上游模型或 What-if 中断 | 任务悬挂、结果半写入 | 明确超时、任务状态、relay 原子替换和 502 |
| 管理查询参数未生效 | 管理员误以为已过滤，造成审计误判 | 契约标注限制，补齐真实过滤 |
| Agent 生成错误业务数字 | 误导决策 | 工具只返回结构化数据，Chat 只做投影和解释 |

### 12.2 必须保持的决策

- PostgreSQL 是业务运行时事实源；
- fcst_detail 和 attribution_analysis_rows 是模型结果缓存，不是输入基座；
- What-if 是基于 baseline 的规则式模拟和有限策略搜索；
- 库存周转在数据不足时返回不可用；
- 页面 API 和 Chat 工具必须共享服务层和数据口径；
- API 契约中标记为当前限制的行为，在修复前不能被前端或 PRD 重新包装成能力。

---

## 13. 术语和参考

| 术语 | 含义 |
|---|---|
| baseline | 选定预测版本的未扰动预测明细 |
| relay | 将模型结果完整校验并写入 backend PG 语义表的过程 |
| coverage | 某指标有有效数据的数量或行覆盖比例 |
| What-if | 在 baseline 上施加有限策略后的规则式模拟 |
| strategy | What-if 可选择的有限策略目录项 |
| attribution | 对预测结果进行因子分解的解释性结果 |
| façade | 面向工作台的简化 API 投影层 |
| trace | 一次消息执行的有序事件集合 |
| internal tool | 后端进程内执行的受控工具 |
| sandbox tool | 通过 sandbox daemon 隔离执行的工具 |

参考文件：

- [工作台功能定义](./prd_workbench.md)
- [数据检查与工作台数据事实](./data-inspect.md)
- [LCT-predict-agent API 契约](./api-contract.md)
