# 数据检查与工作台数据事实

本文记录工作台的数据基座和当前实现事实；功能边界和核心字段见 [工作台功能定义](./prd_workbench.md)。统一口径是：七张开发基座表在启动阶段从 `services/icewash-model/data`（含 `reference/`）同步到 PG，后续业务只通过 PG 交互；关联视图只取能参与 SKU 月度计算的字段，预测和归因直接读 PG 缓存。

## 1. 数据边界

开发期的七个基座 dataset 及文件来源如下：

| dataset | 当前来源 | 角色 |
|---|---|---|
| `raw_data` | `data/ads_cbg_rt_fcst_retail_stat.csv` | 历史销量与销售额 |
| `master_data` | `data/tof_fcst_product_info.csv` | SKU 系列和状态 |
| `price_data` | `data/tof_fcst_product_plan_price.csv` | 未来计划价 |
| `rebate_data` | `data/dwd_cbg_sl_tb_fcst_channel_rebate_detail.csv` | 离线模型输入 |
| `dsi_data` | `data/dwd_cbg_sl_tb_fcst_dsi_price_detail.csv` | 离线模型/渠道价格输入 |
| `cost_data` | `data/reference/cost_data.xlsx` | SKU 成本 |
| `price_elasticity` | `data/reference/price_elasticity.xlsx` | What-if/优化弹性输入；页面 `/workbench/what-if/elasticity` 全量查询此表 |

预测和归因的事实来源则是 `fcst_forecast_result`、`fcst_attribution`，经 backend relay 后分别形成 `fcst_detail` 和 `attribution_analysis_rows`；它们是预测输出缓存，不属于七张基座表。

## 2. 基座同步与业务数据流

```text
services/icewash-model/data
    └─ 模型侧启动同步：读取、校验、标准化七张基座表
         └─ PostgreSQL 基座数据
              ├─ 工作台七个 dataset 全量查询
              ├─ 模型特征/预测读取
              └─ What-if baseline 读取

模型预测/归因
    └─ 写入 PostgreSQL 结果缓存
         ├─ forecast_fact → 预测结果
         └─ attribution_fact → 归因、baseline、What-if
```

这是统一后的目标架构：文件只负责提供开发期基座，PG 是启动同步后的业务事实源，后续工作台、模型、What-if 和 AI Chat 都通过 PG 或 PG 语义结果交互。已生成的架构展示文件见 [ice-wash-query-compute.html](../ice-wash-query-compute.html)。

当前代码仍处于迁移中：backend 的 `workbench_sync_on_startup` 可以触发 `seed_workbench`，但默认配置为关闭；模型 `dataloader.py` 仍有直接读取 CSV 的路径。因此要完全落地上述架构，还需将启动同步设为正式入口、取消快照行数截断，并让模型输入 loader 改为读取 PG 标准化数据。该迁移应一次性建立统一 loader，不应继续在各业务接口增加临时补丁。

工作台查询接口是 `/api/workbench/tables/{dataset}`，接口分页返回；本文所说的“全量”是完整快照可被遍历，不是单次响应不分页。

### `price_elasticity` 的当前责任边界

当前实现不是 backend 直接打开 Excel，链路是：

```text
price_elasticity.xlsx
    → icewash 的 reference_data.py 读取并校验
    → icewash /reference/workbench/price_elasticity 返回规范化行
    → backend model_reference_client.py 拉取并写入 workbench_dataset_rows
    → backend whatif_workbench.py 从 PG 读取弹性系数/类别
    → backend 将弹性参数放入 simulate/optimize 请求
    → icewash What-if 计算
```

所以当前的责任是：**模型服务读取文件，backend 负责写 PG，What-if 基线由 backend 读 PG，模型只消费请求中的弹性参数并执行计算**。What-if 计算阶段不会再次读取 Excel。

目标实现应调整为：**模型服务拥有参考数据导入职责**。模型侧读取并校验 Excel，将标准化的 `price_elasticity` 以版本化、原子替换方式写入 PG；backend 只读取 PG 并调用模拟/优化。运行时不允许 backend 重新拉取文件内容，也不允许模型在缺字段时临时回退到 Excel。这样文件仍是开发期输入渠道，但业务计算只依赖 PG 中的标准化数据。

## 3. 文件到业务数据的映射

文件是开发期的正式输入渠道：CSV/XLSX 由导入器读取、校验和标准化后写入 PG；业务代码只读取标准化后的业务数据，不在接口里再次读文件，也不依赖某个字段不存在时临时换另一个字段。

下表描述的是业务逻辑映射，数据库采用分表还是统一 `workbench_dataset_rows` 不影响业务契约。当前输入快照使用统一表的 `dataset + 索引列 + payload` 保存原始行；`payload` 是溯源，不是业务代码的长期字段映射入口。

| 输入 dataset/文件 | 核心源字段 | 标准化业务对象与粒度 | 当前 PG 落点 | 主要使用方 |
|---|---|---|---|---|
| `raw_data` / `ads_cbg_rt_fcst_retail_stat.csv` | `period_id`、`category_name`、`product_mode_code`、`channel_name_l3`、`retail_qty`、`retail_amt` | `history_fact`：品类×SKU×渠道×月份；金额和销量先聚合 | `workbench_dataset_rows(dataset=raw_data)`；预测 relay 另有历史语义表 | 历史查询、历史价格、baseline |
| `master_data` / `tof_fcst_product_info.csv` | `category_name`、`product_mode_code`、`channel_name_l3`、`product_series`、`product_status` | `sku_profile`：品类×SKU×渠道 | `workbench_dataset_rows(dataset=master_data)` | 预测特征、系列/状态展示 |
| `price_data` / `tof_fcst_product_plan_price.csv` | `period_id`、`category_name`、`product_mode_code`、`version_number`、`min_price_n…n6`、`daily_price_n…n6` | `price_plan`：品类×SKU×月份×版本；宽列先展开成长表 | `workbench_dataset_rows(dataset=price_data)` | 未来计划价、baseline、What-if |
| `dsi_data` / `dwd_cbg_sl_tb_fcst_dsi_price_detail.csv` | 模型所需的 DSI 原始列 | `model_dsi`：按模型要求保留原始粒度 | `workbench_dataset_rows(dataset=dsi_data)` | 离线预测模型；当前不直接进入 What-if 关联 |
| `rebate_data` / `dwd_cbg_sl_tb_fcst_channel_rebate_detail.csv` | 模型所需的返利原始列 | `model_rebate`：品类/渠道/产线粒度，无 SKU 月度事实 | `workbench_dataset_rows(dataset=rebate_data)` | 离线预测模型；不直接计算 SKU 毛利 |
| `cost_data` / `data/reference/cost_data.xlsx` | `品类`、`型号`、`成本价` | `sku_cost`：品类×SKU；当前为静态成本 | `workbench_dataset_rows(dataset=cost_data)` | 毛利、What-if、优化 |
| `price_elasticity` / `data/reference/price_elasticity.xlsx` | `品类`、`系列`、`型号`、`价格弹性系数`、`弹性分类` | `sku_elasticity`：品类×系列×SKU；当前为静态弹性 | `workbench_dataset_rows(dataset=price_elasticity)` | What-if、策略优化 |

预测与归因输出采用同一原则：

| 模型输出 | 核心源字段 | 标准化业务对象与粒度 | 当前 PG 落点 |
|---|---|---|---|
| 预测明细 | `system_forecast_number`、`horizon`、`forecast_month`、`category`、`channel_l3`、`sku`、`final_value`、`plan_price`、`status` | `forecast_fact`：版本×品类×SKU×渠道×月份×horizon | `fcst_forecast_result` → relay → `fcst_detail` |
| 归因因子 | 预测键 + `factor_layer`、`factor_name`、`shap_value`、`type_impact`、`contribution_pct`、`value_T`、`value_T_1` | `attribution_fact`：预测基础粒度×因子 | `fcst_attribution` → relay → `attribution_analysis_rows` |

`fcst_forecast_result` 和 `fcst_attribution` 是模型结果缓存；relay 只做一次完整版本替换并校验行数，不通过旧记录追加、缺字段补写或接口级 fallback 修补结果。

预测版本与价格批次仍是两个概念：`plan_price` 是本次预测实际采用的计划输入价，`price_version` 应由预测请求中的 `priceBatchNumber` 独立绑定和留痕，不能用 `system_forecast_number` 代替。当前中转结果已保存 `plan_price`，批次绑定字段仍是需要补齐的追溯项。

## 4. 核心字段事实

| 工作台要回答的问题 | 实际字段 |
|---|---|
| 某 SKU 某月卖了多少、卖了多少钱 | `raw_data.period_id`、`product_mode_code`、`channel_name_l3`、`retail_qty`、`retail_amt` |
| 某 SKU 的历史价格 | `retail_amt / retail_qty` 派生，不另造历史价格字段 |
| SKU 属于哪个系列、是否在售 | `master_data.product_series`、`product_status` |
| 未来月份用什么计划价 | `price_data.period_id`、`product_mode_code`、`min_price_n…n6`、`daily_price_n…n6` |
| 某 SKU 的成本和价格弹性 | `cost_data.品类`、`型号`、`成本价`；`price_elasticity.品类`、`系列`、`型号`、`价格弹性系数`、`弹性分类` |
| 预测和归因结果 | `fcst_detail` 的 `forecast_qty`、`plan_price`；What-if 解析后的 `baseline_price`；`attribution_analysis_rows` 的 `y_pred`、`qty_lag1`、`delta_y/impact`、`shap_value`（单因子影响量）、`type_impact`、`contribution_pct` 和因子字段 |

`rebate_data` 和 `dsi_data` 仍属于七个可浏览、可供模型读取的开发基座数据源，但当前不向核心 SKU 月度关联视图追加未使用的列。

## 5. 关联和可用性判断

基础粒度是 `category + sku + channel + month`。`raw_data` 提供历史销量和金额，历史价格按 `retail_amt / retail_qty` 派生；`master_data`、`cost_data`、`price_data` 和弹性表按各自粒度补充属性、成本、未来价格和弹性。`rebate_data` 没有 SKU 键，不能直接拼入 SKU 毛利；成本和弹性也没有月份/渠道，当前只能按 SKU 级静态参考使用。

归因的计算口径是：`shap_value` 为单个因子对预测销量的影响量（单位：台）；`type_impact` 为同一 SKU/月/因子类型的影响量合计；`contribution_pct` 为影响量绝对值占比；`value_T`、`value_T_1` 是解释影响的当期值和基准值，不是影响量。模型可以计算这些值，但应在标准化输出中统一命名为 `impact_qty`，并由 `factor_layer + factor_name` 生成稳定的 `factor_id`。这些是模型分解结果，不等同于严格因果效应。

功能结论：历史查询、预测缓存查询和归因查询可实现；What-if 可以实现规则式模拟和有限策略搜索，但不重新运行预测模型。要称为完整可用，仍需保证价格、成本、弹性覆盖状态可见，并补齐 `delta_price`（若要做价格归因）以及未来库存和 COGS（若要做库存/周转优化）。

## 6. What-if 口径与价格解析

What-if 的产品口径固定为：**基于预测 baseline 的规则式 What-if 模拟 + 离散策略搜索**。

- baseline 取所选 `version` 的预测销量，保留 SKU、渠道、月份、horizon 明细。
- `simulate` 将有限策略逐条应用到月份/渠道明细，再汇总展示 `sim_qty`、`sim_price`、`sim_amount` 和毛利。
- `optimize` 在有限策略目录中搜索目标差距较小的策略，不是连续价格优化，也不是重新训练/重新运行预测模型。

未来价格建议采用以下优先级：

```text
预测明细中已绑定 price_version 的 `fcst_detail.plan_price`
    → 该 price_version 对应的 price_data SKU/月计划价
    → 无渠道计划价（标记 channel_fallback）
    → 历史最后有效渠道价
    → 历史最后有效 SKU 价
    → null
```

`plan_price` 是模型使用的计划输入价，不是模型预测出的价格；模型只输出 `forecast_qty`。What-if 后端按上述顺序解析实际用于基线计算的 `baseline_price`，历史成交价只作为兜底。`price_source`、`price_base_month`、`price_status` 和 coverage 用于内部校验；计划价的 `n…n6` 宽列必须先展开为月份长表，才能按未来月份准确匹配。`forecast_price` 不再属于新契约。

## 7. 实现限制

“全量查询”是工作台目标口径，但当前 [seed_workbench.py](../backend/src/app/seed_workbench.py) 的 `ROW_CAPS` 仍限制 `raw_data`、`master_data`、`price_data`、`rebate_data`、`dsi_data` 等导入行数。因此当前 PG 快照只能视为开发样本，移除截断并完成版本/月份/SKU 行数校验后，才能对外宣称七表全量可查。模拟和优化结果当前主要由模型任务存储返回，若要形成完整业务闭环，还应把场景、策略、baseline 版本和结果写入 PG。
