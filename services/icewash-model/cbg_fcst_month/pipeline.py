# -*- coding: utf-8 -*-
"""
Created on Tue Mar 18 14:42:23 2025

@author: Dylan
"""
import pandas as pd
import numpy as np
from dateutil.relativedelta import relativedelta
from featureEngireneer import DataProcessing, FeatureEngineering
from dataloader import SalesDataProcessor, DailySalesProcessor, SKUDataProcessor, PlanningPrice, FCST_Results
from predictability_checker import PredictabilityChecker
from predictor import MLPredictor, MAPredictor
from post_processor import PostProcessor
from attribution import WhiteboxAttributor

from sqlalchemy import create_engine
from new_old_product_optimizer import NewOldProductOptimizer


class SalesForecastingPipeline:
    def __init__(self, config):
        self.config = config
        # self.engine = create_engine(self.config.ENGINE_URL)

        self.predictability_checker = PredictabilityChecker(config)
        self.ml_predictor = MLPredictor(config)
        self.ma_predictor = MAPredictor(config)
        self.optimizer = NewOldProductOptimizer(config)
        self.post_processor = PostProcessor(config)
        self.sales_process = SalesDataProcessor(config)
        self.daily_sales = DailySalesProcessor(config)
        self.master_process = SKUDataProcessor(config)
        self.price_process = PlanningPrice(config)

        self.fcst_process = FCST_Results(config)
        self._shap_long_parts = []

    @staticmethod
    def _restore_own_retail(df, source_sales):
        """用替代关系拼接前的真实零售量/额覆盖展示列，避免新老品同时展示合并求和。"""
        if df is None or getattr(df, 'empty', True) or source_sales is None or getattr(source_sales, 'empty', True):
            return df

        key_columns = ['月份', '3级渠道', '型号-CRM最新名称']
        if any(col not in source_sales.columns for col in key_columns + ['数量']):
            return df
        if any(col not in df.columns for col in key_columns):
            return df

        src = source_sales.copy()
        src['月份'] = pd.to_datetime(src['月份'])
        work = df.copy()
        work['月份'] = pd.to_datetime(work['月份'])

        agg = {'数量': 'sum'}
        if '实收金额' in src.columns:
            agg['实收金额'] = 'sum'
        own = src.groupby(key_columns, as_index=False).agg(agg)
        own = own.rename(columns={col: f'_{col}_自身' for col in agg})

        restored = pd.merge(work, own, on=key_columns, how='left')
        restored['数量'] = restored['_数量_自身'].fillna(0)
        if '实收金额' in restored.columns and '_实收金额_自身' in restored.columns:
            restored['实收金额'] = restored['_实收金额_自身'].fillna(0)
            qty = pd.to_numeric(restored['数量'], errors='coerce').fillna(0)
            amt = pd.to_numeric(restored['实收金额'], errors='coerce').fillna(0)
            restored['avg_price'] = np.where(qty != 0, amt / qty, 0)
        drop_cols = [c for c in restored.columns if c.startswith('_') and c.endswith('_自身')]
        return restored.drop(columns=drop_cols)

    @staticmethod
    def _restore_current_month_own_sales(current_month_results, source_sales):
        """用替代关系拼接前的当月销量覆盖输出，避免新品展示老品继承量。"""
        return SalesForecastingPipeline._restore_own_retail(current_month_results, source_sales)

    def run(self, target_month, progress_callback=None, forecast_horizon=None):
        def _report(message: str) -> None:
            if progress_callback:
                progress_callback(message)

        # todo:在 run 函数中修改 forecast_months 循环逻辑：
        # 数据准备
        _report("数据加载中：历史销量/价格/主数据/返点/上月预测")
        historical_sales_data = self.sales_process.process_all_years()
        try:
            price_data = self.price_process.process_price_data()
        except Exception as e:
            print(f'===> 错误：{e}')
            price_data = self.price_process.process_price_data()
        master_data = self.master_process.load_master_data(target_month)
        # ==================== (加载返点数据) ====================
        rebate_data = self.price_process.process_rebate_date()

        # 读取历史预测结果
        fcst_results, sg_results = self.fcst_process.load_fcst_results()
        print('=' * 40)
        print(f'上月模型结果数：{len(fcst_results)} 条')
        print(f'上月手工结果数：{len(sg_results)} 条')
        print('=' * 40)
        _report(
            f"数据加载完成：上月模型结果 {len(fcst_results)} 条，手工结果 {len(sg_results)} 条"
        )

        child_to_parent_map = self.sales_process.child_to_parent_map
        combo_rules = self.sales_process.combo_rules

        # 筛选当月数据
        _report("当月流速推算与历史数据合并中")
        current_month_data = self.sales_process.filter_current_month_data(historical_sales_data, target_month)
        # updated_current_month_data = self.sales_process.update_current_month_data(current_month_sales_data)

        # 当月销售明细获取逻辑
        corrected_month_data, cumulative_data = self.daily_sales.process_daily_sales(
            current_month_data,
            fcst_results,
            sg_results,
            price_data,
            rebate_data,
            child_to_parent_map,
            combo_rules
        )

        # 保存当月销量数据（用于第二个sheet）
        monthly_sales_dict = {}      # 当月累计销量
        monthly_estimated_dict = {}  # 当月推算销量

        if not corrected_month_data.empty:
            # 使用推算数据填充推算字典
            for _, row in corrected_month_data.iterrows():
                key = (row['3级渠道'], row['型号-CRM最新名称'])
                monthly_estimated_dict[key] = row['数量']

        if not cumulative_data.empty:
            # 使用累计数据填充累计字典
            for _, row in cumulative_data.iterrows():
                key = (row['3级渠道'], row['型号-CRM最新名称'])
                monthly_sales_dict[key] = row['当月累计销量']
            # 保存流速法推算的当月销量
            for _, row in corrected_month_data.iterrows():
                key = (row['3级渠道'], row['型号-CRM最新名称'])
                monthly_estimated_dict[key] = row['数量']  # 流速法推算的当月销量

        # d. 将历史数据和处理好的当月数据简单合并
        if not corrected_month_data.empty:
            update_month = corrected_month_data['月份'].iloc[0]
            print(f"信息: Pipeline正在合并 {update_month.strftime('%Y-%m')} 月的带价预估数据。")

            # 从历史数据中移除可能存在的不完整当月数据
            historical_sales_data = historical_sales_data[historical_sales_data['月份'] != update_month]
            historical_sales_data.drop('最后更新时间', axis=1, inplace=True)
            
            # 合并成一个完整的、截至当月的初始数据集
            initial_full_data = pd.concat([historical_sales_data, corrected_month_data], ignore_index=True)
            initial_full_data.sort_values(by='月份', inplace=True)
        else:
            initial_full_data = historical_sales_data

        _report("当月流速推算与历史数据合并完成")

        # 生成预测月份。接口请求可以缩短模型计算范围；未指定时保持
        # Config.FORECAST_MONTHS 的既有默认口径（当前为 N+1~N+7）。
        horizon = int(forecast_horizon or self.config.FORECAST_MONTHS)
        horizon = max(1, min(horizon, 12))
        forecast_months = [
            (pd.to_datetime(target_month) + relativedelta(months=i)).strftime('%Y-%m-%d')
            for i in range(horizon)
        ]

        current_data = initial_full_data.query('月份 >= "2021-01-01" and 月份 < @target_month').copy()
        final_results = pd.DataFrame()
        # N+1~N+7 预测明细（同维度多行）
        all_forecast_details = []
        self._shap_long_parts = []

        skutype_mapping = {
            '洗衣机': ['L', 'Q', 'T', 'V', 'S'],
            '冰箱': ['V', 'L', 'S', 'T']
        }

        # todo：记录基准预测月份(N+1)，用于后续严格阻断特征泄露
        base_target_month = forecast_months[0]
        current_month = None
        current_month_results = pd.DataFrame()
        history_feature_df = pd.DataFrame()
        price_original = self.price_process.process_price_data()

        total_horizons = len(forecast_months)
        for idx, forecast_month_str in enumerate(forecast_months):
            print(f">>>> predicting: {forecast_month_str} (N{idx + 1})")
            _report(
                f"模型预测中：N+{idx + 1}月(共{total_horizons})（{forecast_month_str}）"
            )
            # 准备动态更新的特征数据
            # todo：注意：current_data 始终只有真实的历史数据，不再包含上一轮的预测值
            dataprocess = DataProcessing(current_data, master_data, forecast_month_str, optimizer=self.optimizer)
            df, skulist = dataprocess.data_processing()

            # 将返点数据(rebate_data)传递给FeatureEngineering
            # todo: 传入 horizon_offset=idx
            pipeline = FeatureEngineering(df, master_data, price_data, forecast_month_str, skulist, rebate_data,
                                          self.config, horizon_offset=idx)

            final_data = pipeline.run_feature_engineer()
            print(f"预测期：{idx}，{forecast_month_str}")
            # 创建空 DataFrame 来存储所有系列的结果
            all_series_forecast = pd.DataFrame()

            # 遍历所有系列
            for skutype, series_set in skutype_mapping.items():
                for series in series_set:
                    print(f">>>> object: {skutype},{series}")
                    series_data = final_data.query("series == @series and 品类 == @skutype")

                    if series_data.empty:
                        continue

                    # 可预测性判断
                    predictable_skus, unpredictable_skus = self.predictable(series_data, forecast_month_str)
                    print(f">>>> predictable_skus: {len(predictable_skus)}, {len(unpredictable_skus)}")
                    # 模型预测（按 horizon N1~N7 分模型训练/加载）
                    ml_results = pd.DataFrame()
                    if predictable_skus:
                        ml_results = self.run_ml_prediction(
                            series_data, predictable_skus, forecast_month_str,
                            skutype, series, base_target_month, horizon_offset=idx
                        )

                    ma_results = pd.DataFrame()
                    if unpredictable_skus:
                        ma_results = self.ma_predictor.predict(unpredictable_skus, series_data, forecast_month_str, series,
                                                               skutype)
                    # 处理结果
                    series_forecast = self.post_processor.combine_results(
                        ml_results, ma_results, series, skutype
                    )
                    # 预测值还原
                    if not series_forecast.empty:
                        series_forecast['y_pred'] = series_forecast['y_pred'].fillna(0).round()

                    # 将当前系列的结果添加到空的 DataFrame中
                    all_series_forecast = pd.concat([all_series_forecast, series_forecast])
            print(f"{all_series_forecast.groupby(['月份','品类'])['y_pred'].sum()}")

            # 新老品过渡前保留一版预测，便于明细审计
            pre_transition_pred = (
                all_series_forecast['y_pred'].copy()
                if not all_series_forecast.empty and 'y_pred' in all_series_forecast.columns
                else None
            )
            all_series_forecast = self.optimizer.apply_transition_split(
                all_series_forecast, historical_sales_data, master_data, forecast_month_str
            )
            if pre_transition_pred is not None and not all_series_forecast.empty:
                # apply_transition_split 可能重置/打乱 index，必须按位置对齐
                pre_vals = np.nan_to_num(pre_transition_pred.to_numpy(copy=False), nan=0.0)
                post_vals = np.nan_to_num(
                    all_series_forecast['y_pred'].to_numpy(copy=False), nan=0.0
                )
                if len(pre_vals) == len(post_vals):
                    all_series_forecast['y_pred_before_transition'] = pre_vals
                    changed_mask = pd.Series(
                        post_vals != pre_vals, index=all_series_forecast.index
                    )
                    if 'post_process_rule' in all_series_forecast.columns and changed_mask.any():
                        all_series_forecast.loc[changed_mask, 'post_process_rule'] = (
                            all_series_forecast.loc[changed_mask, 'post_process_rule'].astype(str)
                            + '+transition'
                        )
                else:
                    all_series_forecast['y_pred_before_transition'] = np.nan

            # 收集 N+1~N+7 明细（含全量输入特征 + 基线/权重/后过程）
            if not all_series_forecast.empty:
                detail_df = self._prepare_detail_data(
                    all_series_forecast,
                    final_data,
                    forecast_month_str,
                    horizon_idx=idx,
                    monthly_sales_dict=monthly_sales_dict,
                    monthly_estimated_dict=monthly_estimated_dict,
                    price_original=price_original,
                )
                all_forecast_details.append(detail_df)

            if idx == 0:
                # N+1 特征集已含完整历史，截取窗口供「历史数据」sheet
                history_feature_df = self._slice_history_from_features(final_data, target_month)

                current_month = pd.to_datetime(forecast_months[0]) - pd.DateOffset(months=1)
                current_month_results = final_data[final_data['月份'] == current_month]

                tmp_category_results = pd.DataFrame()
                for category in self.config.CATEGORY_LIST:
                    series_list = skutype_mapping[category]
                    tmp_month_results = current_month_results[(current_month_results['品类'] == category) & \
                                                                  (current_month_results['series'].isin(series_list))]
                    tmp_category_results = pd.concat([tmp_category_results, tmp_month_results])
                current_month_results = tmp_category_results

                # retail_qty_n 使用替代关系拼接前的型号自身当月销量；
                # 历史继承数据仍保留在 final_data 中，仅供后续预测特征使用。
                current_month_source = initial_full_data[
                    pd.to_datetime(initial_full_data['月份']) == current_month
                ].copy()
                current_month_results = self._restore_current_month_own_sales(
                    current_month_results, current_month_source
                )

            # 合并所有预测结果
            if final_results.empty:
                tmp_results = pd.concat([all_series_forecast, current_month_results], ignore_index=True, sort=False)
                # 使用推算值填充当月预测值
                mask = tmp_results['月份'] == current_month
                tmp_results.loc[mask, 'y_pred'] = current_month_results['数量'].values
                tmp_results = tmp_results[all_series_forecast.columns]
                final_results = pd.concat([final_results, tmp_results]).sort_values(['月份'])
            else:
                final_results = pd.concat([final_results, all_series_forecast])

        print(
            f">>>> LGBM summary: trained={self.ml_predictor.train_count}, "
            f"loaded={self.ml_predictor.load_count}"
        )
        _report(
            f"多期预测完成：LGBM trained={self.ml_predictor.train_count}, "
            f"loaded={self.ml_predictor.load_count}"
        )
        detailed_results = (
            pd.concat(all_forecast_details, ignore_index=True)
            if all_forecast_details else pd.DataFrame()
        )
        if not detailed_results.empty:
            detailed_results = detailed_results.sort_values(
                by=['品类', '3级渠道', '型号-CRM最新名称', 'horizon_offset', '月份']
            ).reset_index(drop=True)

        shap_long = (
            pd.concat(self._shap_long_parts, ignore_index=True)
            if self._shap_long_parts else pd.DataFrame()
        )
        # 把 horizon 挂到 shap 长表（按 月份+键 对齐明细）
        if not shap_long.empty and not detailed_results.empty:
            hz = detailed_results[
                ['3级渠道', '型号-CRM最新名称', '月份', 'horizon', 'horizon_offset']
            ].drop_duplicates()
            hz['月份'] = pd.to_datetime(hz['月份'])
            shap_long['月份'] = pd.to_datetime(shap_long['月份'])
            shap_long = shap_long.drop(columns=['horizon', 'horizon_offset'], errors='ignore')
            shap_long = shap_long.merge(
                hz, on=['3级渠道', '型号-CRM最新名称', '月份'], how='left'
            )

        _report("白盒归因计算中")
        _, attribution_factors = WhiteboxAttributor(top_k=10).build(detailed_results, shap_long)
        print(f">>>> 白盒归因因子行数: {len(attribution_factors)}")
        _report(f"白盒归因完成：因子行数={len(attribution_factors)}")

        history_results = self._align_history_to_detail(history_feature_df, detailed_results)
        history_results = self._restore_own_retail(history_results, initial_full_data)
        history_results = self._expand_history_with_related_own_rows(
            history_results, initial_full_data, detailed_results, master_data, target_month
        )
        print(f">>>> 历史数据行数: {len(history_results)}")
        return final_results, detailed_results, attribution_factors, history_results

    @staticmethod
    def history_window_bounds(target_month):
        """历史展示窗口：近6个月 与 本年至今，取更长的一段（去最大）。"""
        target = pd.to_datetime(target_month).replace(day=1)
        end_month = target - pd.DateOffset(months=1)
        six_start = end_month - pd.DateOffset(months=5)
        ytd_start = pd.Timestamp(year=end_month.year, month=1, day=1)
        start_month = min(six_start, ytd_start)
        return start_month, end_month

    def _slice_history_from_features(self, feature_data, target_month) -> pd.DataFrame:
        """从特征工程后的表截取历史月份，不再重算销量/金额/均价。"""
        if feature_data is None or feature_data.empty:
            return pd.DataFrame()

        start_month, end_month = self.history_window_bounds(target_month)
        df = feature_data.copy()
        df['月份'] = pd.to_datetime(df['月份'])
        mask = (df['月份'] >= start_month) & (df['月份'] <= end_month)
        if '品类' in df.columns and getattr(self.config, 'CATEGORY_LIST', None):
            mask &= df['品类'].isin(self.config.CATEGORY_LIST)
        df = df.loc[mask]
        keep = [
            '月份', 'product_line_code', 'product_line_name',
            '品类', 'series', 'status', '1级渠道', '3级渠道', '型号-CRM最新名称',
            '数量', '实收金额', 'avg_price',
        ]
        keep = [c for c in keep if c in df.columns]
        if not keep:
            return pd.DataFrame()
        out = df[keep].copy()
        if '数量_自身' in df.columns:
            out['数量'] = pd.to_numeric(df.loc[out.index, '数量_自身'], errors='coerce').fillna(0)
        if '实收金额_自身' in df.columns:
            out['实收金额'] = pd.to_numeric(df.loc[out.index, '实收金额_自身'], errors='coerce').fillna(0)
        if '数量' in out.columns and '实收金额' in out.columns:
            qty = pd.to_numeric(out['数量'], errors='coerce').fillna(0)
            amt = pd.to_numeric(out['实收金额'], errors='coerce').fillna(0)
            out['avg_price'] = np.where(qty != 0, amt / qty, 0)
        if '1级渠道' not in out.columns and '3级渠道' in out.columns:
            mapping = getattr(self.config, 'CHANNEL_MAPPING', {}) or {}
            out['1级渠道'] = out['3级渠道'].map(mapping).fillna(out['3级渠道'])
        print(
            f">>>> 历史窗口: {start_month.strftime('%Y-%m')} ~ {end_month.strftime('%Y-%m')} "
            f"(近6个月 vs 本年，取更长)"
        )
        return out.reset_index(drop=True)

    @staticmethod
    def _align_history_to_detail(history_df, detailed_results) -> pd.DataFrame:
        """颗粒度对齐预测详情：月份+品类+渠道+型号；SKU/渠道集合与预测详情一致。"""
        if history_df is None or history_df.empty:
            return pd.DataFrame()
        if detailed_results is None or getattr(detailed_results, 'empty', True):
            return history_df
        keys = [c for c in ['3级渠道', '型号-CRM最新名称'] if c in history_df.columns and c in detailed_results.columns]
        if not keys:
            return history_df
        detail_keys = detailed_results[keys].drop_duplicates()
        return history_df.merge(detail_keys, on=keys, how='inner').reset_index(drop=True)

    def _related_sku_names(self, skus) -> set:
        """预测型号对应的新老品集合（含多代穿透）。"""
        related = {str(s).strip() for s in skus if str(s).strip()}
        chain = getattr(self.optimizer, 'replacement_chain', None) or {}
        old_to_new = getattr(self.optimizer, 'old_to_new_map', None) or {}
        for sku in list(related):
            for old in chain.get(sku, []) or []:
                name = str(old).strip()
                if name:
                    related.add(name)
            parent = old_to_new.get(sku)
            if parent:
                related.add(str(parent).strip())
        return related

    def _sku_attr_frame(self, history_df, detailed_results, master_data) -> pd.DataFrame:
        """型号(+渠道)基础属性：品类/系列/状态/产线。"""
        attr_cols = [
            '3级渠道', '型号-CRM最新名称', '品类', 'series', 'status',
            '1级渠道', 'product_line_code', 'product_line_name',
        ]
        frames = []
        for src in (history_df, detailed_results):
            if src is None or getattr(src, 'empty', True):
                continue
            cols = [c for c in attr_cols if c in src.columns]
            if '型号-CRM最新名称' not in cols:
                continue
            frames.append(src[cols].drop_duplicates())
        if master_data is not None and not getattr(master_data, 'empty', True):
            md = master_data.rename(columns={
                'channel_name_l3': '3级渠道',
                'category_name': '品类',
                'product_series': 'series',
                'product_status': 'status',
            })
            cols = [c for c in attr_cols if c in md.columns]
            if '型号-CRM最新名称' in cols:
                frames.append(md[cols].drop_duplicates())
        if not frames:
            return pd.DataFrame()
        out = pd.concat(frames, ignore_index=True, sort=False)
        subset = [c for c in ['3级渠道', '型号-CRM最新名称'] if c in out.columns]
        return out.drop_duplicates(subset=subset, keep='first')

    def _expand_history_with_related_own_rows(
        self, history_df, source_sales, detailed_results, master_data, target_month
    ) -> pd.DataFrame:
        """补齐预测型号对应新老品的真实零售行（未进入特征表的老品也会写出）。"""
        if source_sales is None or getattr(source_sales, 'empty', True):
            return history_df if history_df is not None else pd.DataFrame()
        if detailed_results is None or getattr(detailed_results, 'empty', True):
            return history_df if history_df is not None else pd.DataFrame()
        if '型号-CRM最新名称' not in detailed_results.columns or '3级渠道' not in detailed_results.columns:
            return history_df if history_df is not None else pd.DataFrame()

        detail_pairs = detailed_results[['3级渠道', '型号-CRM最新名称']].drop_duplicates()
        extra_pairs = []
        existing = set()
        if history_df is not None and not history_df.empty:
            existing = set(zip(
                history_df['3级渠道'].astype(str),
                history_df['型号-CRM最新名称'].astype(str),
            ))
        for _, row in detail_pairs.iterrows():
            ch = str(row['3级渠道'])
            sku = str(row['型号-CRM最新名称']).strip()
            for rel in self._related_sku_names([sku]):
                pair = (ch, rel)
                if pair not in existing:
                    extra_pairs.append(pair)
                    existing.add(pair)
        if not extra_pairs:
            return history_df if history_df is not None else pd.DataFrame()

        start_month, end_month = self.history_window_bounds(target_month)
        src = source_sales.copy()
        src['月份'] = pd.to_datetime(src['月份'])
        src = src[(src['月份'] >= start_month) & (src['月份'] <= end_month)]
        extra_df = pd.DataFrame(extra_pairs, columns=['3级渠道', '型号-CRM最新名称'])
        own = src.merge(extra_df, on=['3级渠道', '型号-CRM最新名称'], how='inner')
        if own.empty:
            return history_df if history_df is not None else pd.DataFrame()

        agg = {'数量': 'sum'}
        if '实收金额' in own.columns:
            agg['实收金额'] = 'sum'
        group_keys = ['月份', '3级渠道', '型号-CRM最新名称']
        if '1级渠道' in own.columns:
            group_keys.append('1级渠道')
        own = own.groupby(group_keys, as_index=False).agg(agg)
        qty = pd.to_numeric(own['数量'], errors='coerce').fillna(0)
        if '实收金额' in own.columns:
            amt = pd.to_numeric(own['实收金额'], errors='coerce').fillna(0)
            own['avg_price'] = np.where(qty != 0, amt / qty, 0)
        else:
            own['avg_price'] = 0

        attrs = self._sku_attr_frame(history_df, detailed_results, master_data)
        if not attrs.empty:
            attr_keys = [c for c in ['3级渠道', '型号-CRM最新名称'] if c in attrs.columns]
            own = own.merge(attrs, on=attr_keys, how='left', suffixes=('', '_attr'))
            for col in list(own.columns):
                if col.endswith('_attr'):
                    base = col[:-5]
                    if base in own.columns:
                        own[base] = own[base].combine_first(own[col])
                    own.drop(columns=[col], inplace=True)
        if '1级渠道' not in own.columns and '3级渠道' in own.columns:
            mapping = getattr(self.config, 'CHANNEL_MAPPING', {}) or {}
            own['1级渠道'] = own['3级渠道'].map(mapping).fillna(own['3级渠道'])

        keep = [
            '月份', 'product_line_code', 'product_line_name',
            '品类', 'series', 'status', '1级渠道', '3级渠道', '型号-CRM最新名称',
            '数量', '实收金额', 'avg_price',
        ]
        own = own[[c for c in keep if c in own.columns]]
        if history_df is None or history_df.empty:
            combined = own
        else:
            hist = history_df.copy()
            hist['月份'] = pd.to_datetime(hist['月份'])
            combined = pd.concat([hist, own], ignore_index=True, sort=False)
        combined = combined.drop_duplicates(
            subset=['月份', '3级渠道', '型号-CRM最新名称'], keep='first'
        )
        print(f">>>> 历史数据补齐新老品真实零售行: +{len(own)} 行")
        return combined.reset_index(drop=True)

    def _prepare_detail_data(self, forecast_df, feature_source, forecast_month_str, horizon_idx,
                             monthly_sales_dict, monthly_estimated_dict, price_original):
        """组装单期预测明细：维度键 + 全量模型输入特征 + 基线/权重/后处理过程。"""
        forecast_month = pd.to_datetime(forecast_month_str)
        feature_data = feature_source[feature_source['月份'] == forecast_month].copy()

        # 按出现的品类×系列汇总 MODEL_FEATURES
        feature_cols = set()
        for _, row in forecast_df[['品类', 'series']].drop_duplicates().iterrows():
            cfg_key = f"{row['品类']}{row['series']}"
            feature_cols.update(self.config.SERIES_CONFIG.get(cfg_key, {}).get('MODEL_FEATURES', []))
        feature_cols = [c for c in sorted(feature_cols) if c in feature_data.columns]

        id_cols = ['月份', '品类', '1级渠道', '3级渠道', 'series', 'status', '型号-CRM最新名称']
        process_cols = [
            'method', 'baseline_model', 'baseline_pred', 'model_pred', 'strategy_pred',
            'y_pred_before_transition', 'y_pred',
            'pred_bias', 'eol_ratio', 'post_process_rule',
            'weight_model_weight', 'weight_3m_mean_weight', 'weight_lag12_weight', 'weight_model_bias_weight',
            'term_model', 'term_3m_mean', 'term_lag12', 'term_bias',
            'product_line_code', 'product_line_name',
        ]
        keep_forecast = [c for c in id_cols + process_cols if c in forecast_df.columns]

        merge_keys = ['3级渠道', '型号-CRM最新名称']
        feat_keep = list(dict.fromkeys(merge_keys + feature_cols))
        forecast_part = forecast_df[[c for c in keep_forecast if c in forecast_df.columns]].copy()

        detail_df = pd.merge(
            forecast_part,
            feature_data[feat_keep].drop_duplicates(merge_keys),
            on=merge_keys,
            how='left',
            suffixes=('', '_feat'),
        )
        for col in feature_cols:
            feat_col = f'{col}_feat'
            if feat_col in detail_df.columns:
                if col in detail_df.columns:
                    detail_df[col] = detail_df[feat_col].combine_first(detail_df[col])
                else:
                    detail_df[col] = detail_df[feat_col]
                detail_df.drop(columns=[feat_col], inplace=True)

        price_month_data = price_original[price_original['月份'] == forecast_month]
        if not price_month_data.empty and '型号' in price_month_data.columns:
            detail_df = pd.merge(
                detail_df,
                price_month_data[['型号', 'avg_price']].rename(
                    columns={'型号': '型号-CRM最新名称', 'avg_price': 'plan_price'}
                ).drop_duplicates('型号-CRM最新名称'),
                on='型号-CRM最新名称',
                how='left',
            )

        detail_df['horizon'] = f'N+{horizon_idx + 1}'
        detail_df['horizon_offset'] = horizon_idx
        detail_df['当月累计销量'] = detail_df.apply(
            lambda row: monthly_sales_dict.get((row['3级渠道'], row['型号-CRM最新名称']), 0),
            axis=1,
        )
        detail_df['当月推算销量'] = detail_df.apply(
            lambda row: monthly_estimated_dict.get((row['3级渠道'], row['型号-CRM最新名称']), 0),
            axis=1,
        )
        return detail_df

    def predictable(self, final_data, target_month):
        """执行可预测性检查"""
        predictable_skus = []
        unpredictable_skus = []

        for sku, sku_data in final_data.groupby(['3级渠道', '型号-CRM最新名称']):
            is_predictable_flag, avg_sales = self.predictability_checker.check_predictability(
                sku_data, pd.to_datetime(target_month)
            )
            if is_predictable_flag:
                predictable_skus.append(sku)
            else:
                unpredictable_skus.append((sku, avg_sales))

        return predictable_skus, unpredictable_skus

    def run_ml_prediction(
        self,
        final_data,
        predictable_skus,
        target_month,
        skutype,
        series,
        base_target_month,
        horizon_offset: int = 0,
    ):
        """执行机器学习预测（同品类×系列×horizon(N1~N7) 复用已训练模型）"""
        predictable_df = final_data[
            final_data.apply(lambda row: (row["3级渠道"], row["型号-CRM最新名称"]) in predictable_skus, axis=1)
        ]
        predictable_df.sort_values(['月份', '3级渠道', '型号-CRM最新名称'], ascending=False, inplace=True)
        series_type = skutype + series
        train_result, result, bias_gap = self.ml_predictor.predict(
            predictable_df, target_month, series_type, base_target_month, skutype, series,
            horizon_offset=horizon_offset,
        )
        if result is None or result.empty:
            return pd.DataFrame()

        # 优先使用与模型配套的 bias；缺失时回退到训练集现算
        if bias_gap is None or bias_gap.empty:
            if train_result is None or train_result.empty:
                return pd.DataFrame()
            train_result = train_result.copy()
            train_result['pred_bias'] = train_result['model_pred'] - train_result['数量']
            bias_gap = train_result.groupby(
                ['3级渠道', '型号-CRM最新名称'], as_index=False
            )['pred_bias'].mean()

        result = result.merge(bias_gap, on=['3级渠道', '型号-CRM最新名称'], how='left')
        result['method'] = 'LGB'

        # TreeSHAP：相对目标月上月基准
        try:
            shap_df = self.ml_predictor.shap_relative_to_prior_month(predictable_df, target_month)
            if shap_df is not None and not shap_df.empty:
                shap_df = shap_df.copy()
                shap_df['品类'] = skutype
                shap_df['series'] = series
                self._shap_long_parts.append(shap_df)
                n_keys = shap_df.drop_duplicates(['3级渠道', '型号-CRM最新名称']).shape[0]
                print(f"SHAP ok ({skutype}{series}): rows={len(shap_df)}, keys={n_keys}")
            else:
                print(f"SHAP 空结果 ({skutype}{series})")
        except Exception as e:
            print(f"SHAP 计算跳过 ({skutype}{series}): {e}")

        return result.query('月份 == @target_month')[
            ['月份', 'product_line_code', 'product_line_name', '品类', '1级渠道', '3级渠道', 'series', 'status', '型号-CRM最新名称', '数量','avg_price',
             'method', 'model_pred', 'qty_lag1', 'qty_lag12', 'lag1_diff1', 'qty_lag1_3m_mean', 'pred_bias']]
