# 工作台功能定义

## 1. 核心心智模型

工作台的最小业务单元是 **SKU × 渠道 × 月份**；没有渠道时退化为 SKU × 月份。历史和未来应被看成同一条月度时间轴：开发期的七张基座数据表先同步到 PostgreSQL，业务查询和模型计算都从 PG 读取；预测和归因则来自已经写入 PG 的结果缓存，不在工作台重新计算，也不从历史表反推。

七张基座表可以分别全量浏览和筛选，`/workbench/what-if/elasticity` 就是 `price_elasticity` 的全量查询入口。关联视图只保留后续计算真正需要的字段；关联时应先按各自粒度去重/聚合，再以 `LEFT JOIN` 合成 SKU 月度视图。预测和归因结果是输出缓存，不计入七张基座表。

## 2. 数据基座：七张表的核心字段

| dataset | 关联视图保留的核心字段 | 用途 |
|---|---|---|
| `raw_data` | `period_id`、`category_name`、`product_mode_code`、`channel_name_l3`、`retail_qty`、`retail_amt` | 历史月份、SKU、渠道、销量和销售额；历史价格由金额/销量派生 |
| `master_data` | `category_name`、`product_mode_code`、`channel_name_l3`、`product_series`、`product_status` | 补充系列和在售状态，支持生命周期及策略判断 |
| `price_data` | `period_id`、`category_name`、`product_mode_code`、`version_number`、`min_price_n…n6`、`daily_price_n…n6` | 未来月份的计划价；当前没有渠道键 |
| `dsi_data` | 当前不纳入 SKU 月度核心视图 | 预测模型输入；当前 What-if 基线不直接读取它 |
| `rebate_data` | 当前不纳入 SKU 月度核心视图 | 预测模型输入；表中没有 SKU 键，不能直接用于 SKU 毛利计算 |
| `cost_data` | `品类`、`型号`、`成本价` | 为 SKU 挂接成本；当前粒度没有月份和渠道 |
| `price_elasticity` | `品类`、`系列`、`型号`、`价格弹性系数`、`弹性分类` | What-if 和策略优化的弹性基座；当前粒度没有月份和渠道 |

## 3. 预测与归因缓存

预测结果由 `fcst_forecast_result` 写入，再 relay 到工作台的 `fcst_detail`；归因结果由 `fcst_attribution` 写入，再 relay 到 `attribution_analysis_rows`。两者都按版本、月份、SKU（及渠道）全量查询。

| 结果 | 查询所需的核心字段 | 能产出什么 |
|---|---|---|
| 预测 | `version/system_forecast_number`、`horizon`、`forecast_month`、`category`、`channel_l3`、`sku`、`final_value`、`plan_price`、`status` | `forecast_qty`、模型使用的计划价、销售额和状态；无扰动未来六个月可作为 `fcst_baseline` |
| 归因 | 版本、月份、`horizon`、SKU、`y_pred`、`qty_lag1`、`delta_y/impact`、`factor_layer`、`factor_id`、`factor_name`、`factor_type`、`shap_value/impact_qty`、`type_impact`、`contribution_pct` | 单因子影响量、类型汇总和 waterfall；当前没有 `delta_price` |

## 4. 功能—输入—产出

| 功能 | 需要的核心数据 | 能产出什么 |
|---|---|---|
| 数据浏览与关联查询 | 七张基座表；筛选键为品类、渠道、SKU、月份、版本等 | 原始表全量查看，以及一行一 SKU 月份的基础视图 |
| 历史分析 | `raw_data` + 主数据 + 成本 | 每个 SKU 每月的销量、销售额、历史均价、系列/状态、成本及可计算的毛利 |
| 预测结果 | `fcst_detail` 缓存 | 未来月份预测销量、计划价和销售额；不触发新预测 |
| 归因分析 | `attribution_analysis_rows` 缓存 | 预测值、滞后销量、因子影响、类型汇总和瀑布图；价格影响目前不完整 |
| What-if 模拟 | 历史时间轴 + `fcst_baseline` + `baseline_price` + 成本 + 弹性 | 调整价格后的 `sim_qty`、`sim_price`、`sim_amount`、毛利及 coverage/status |
| 策略优化 | 同上，加目标、约束和策略参数 | 推荐价格/销量/销售额/毛利，以及与 baseline 的差异 |
| AI Chat | 复用上述 PG 语义数据和模拟/优化结果 | 用自然语言返回同一套指标、表格或图表，不另造一套数据源 |

## 5. 计算口径与完整性结论

What-if 的产品口径是：**基于预测 baseline 的规则式 What-if 模拟 + 离散策略搜索**。`simulate` 把有限策略作用到 baseline 的月份/渠道明细；`optimize` 在有限策略目录中选择目标差距较小的方案，不重新训练或重新运行预测模型。

模型不预测价格：`plan_price` 是预测时使用的计划输入价。What-if 后端将计划价解析为实际基线价 `baseline_price`；计划价缺失时才使用历史最后有效价格兜底。`forecast_price` 不再作为结果字段，避免把计划输入误称为模型预测价格。

```text
历史价格 = sum(retail_amt) / sum(retail_qty)       （销量有效时）
预测销售额 = forecast_qty × plan_price
What-if 基线销售额 = baseline_qty × baseline_price
模拟销售额 = sim_qty × sim_price
毛利 = (price - cost_price) × qty
```

当前设计可以支撑历史查询、PG 缓存预测查询和数量维度的归因；七张基座表同步完整且成本与弹性匹配时，可以运行基础模拟和优化。要称为“完整可用”，还必须保证启动同步无行数截断、预测/归因 relay 的版本与行数一致，并补齐：计划价的渠道维度、成本/弹性的有效期或渠道口径、归因 `delta_price`/价格影响，以及未来库存和 COGS（若要做库存或周转优化）。
