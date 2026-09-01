# 数据画像 · 关键发现 Top 10

> 生成：2026-08-26 · 品类 PL003（冰箱/洗衣机）· 输入 7 CSV + 输出 2 Excel（各 5 sheet）

1. **唯一训练标签**：`ads_cbg_rt_fcst_retail_stat.csv` 50.9 万行 × 24 列，是模型训练标签 + 历史 lag/rolling 特征来源（训练+推理）。
2. **最小表**：`dwd_cbg_sl_tb_fcst_channel_rebate_detail.csv` 仅 28 行（品类×渠道费率汇总，折算进 avg_price 特征）。
3. **死数据**：`dwd_cbg_bd_cmp_zyk_detail.csv`（中怡康竞品，约 19 万行）配置了但代码从未读取，训练/推理都不用。
4. **仅推理两张表**：`dwd_cbg_rt_fcst_result_month_detail.csv`（往期预测存底，当月流速法混合）与 `dwd_cbg_sl_tb_fcst_dsi_price_detail.csv`（仅落盘展示出货价），均不参与 LightGBM 训练。
5. **输出核心**：`result`（SKU×渠道 宽表）+ `白盒归因`（TreeSHAP 明细，冰箱 18909 行）。
6. **计划价七期口径**：`tof_fcst_product_plan_price.csv` 的 min/daily/plus_coupon 各含 n..n6 七列（avg_price 进特征）。
7. **版本管理**：`tof_fcst_product_info.csv` 含 version_number（对应 productBatchNumber 筛选），type/series/status 作为分类特征进训练。
8. **DSI 售价**：`dwd_cbg_sl_tb_fcst_dsi_price_detail.csv` 月粒度售价 15012 行。
9. **字段类型**：名称类为中文字符串，数量/金额/价格为数值列，可直接分布可视化。

## 用途区分：模型训练 vs 推理

| 表 | 用途 | 说明 |
|---|---|---|
| `ads_cbg_rt_fcst_retail_stat.csv` | 训练+推理 | 销量标签 + lag/rolling 特征（唯一标签源） |
| `tof_fcst_product_info.csv` | 训练+推理 | type/series/status 分类变量 + 新老品/EOL/新品判定 |
| `tof_fcst_product_plan_price.csv` | 训练+推理 | avg_price 价格特征 + 当月计划价 |
| `dwd_cbg_sl_tb_fcst_channel_rebate_detail.csv` | 训练+推理 | 渠道扣点折算进 avg_price |
| `dwd_cbg_rt_fcst_result_month_detail.csv` | 仅推理 | 当月流速法（15%手工+25%模型+60%实销） |
| `dwd_cbg_sl_tb_fcst_dsi_price_detail.csv` | 仅推理 | 结果落盘展示「出货价」 |
| `dwd_cbg_bd_cmp_zyk_detail.csv` | 未使用 | 中怡康竞品，死数据 |
