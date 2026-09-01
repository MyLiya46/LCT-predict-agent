# -*- coding: utf-8 -*-
"""
Created on Tue Mar 18 14:41:07 2025

@author: Dylan
"""
import numpy as np
import pandas as pd


class PostProcessor:
    """合并 ML/MA 结果，并记录基线、权重与后处理过程字段。"""

    WEIGHT_KEYS = ('model_weight', '3m_mean_weight', 'lag12_weight', 'model_bias_weight')

    def __init__(self, config):
        self.config = config

    def combine_results(self, ml_results, ma_results, series, skytype):
        """合并预测结果，并附加可审计的过程字段。"""
        parts = []

        if not ml_results.empty:
            parts.append(self._enrich_ml(ml_results.copy(), series, skytype))

        if not ma_results.empty:
            parts.append(self._enrich_ma(ma_results.copy()))

        if not parts:
            return pd.DataFrame()

        combined = pd.concat(parts, ignore_index=True)
        combined = self.EOL_adjustment(combined)
        zero_price = combined.get('avg_price', pd.Series(0, index=combined.index)).fillna(0) == 0
        combined.loc[zero_price, 'y_pred'] = 0
        combined.loc[zero_price, 'post_process_rule'] = (
            combined.loc[zero_price, 'post_process_rule'].astype(str) + '+zero_price'
        )
        return combined

    def _enrich_ml(self, df, series, skytype):
        series_config = self.config.SERIES_CONFIG.get(skytype + series, {})
        weights = series_config.get('WEIGHTS', {})

        prep_cols = ['qty_lag12', 'qty_lag1_3m_mean', 'model_pred', 'pred_bias']
        for col in prep_cols:
            if col not in df.columns:
                df[col] = 0
        df[prep_cols] = df[prep_cols].fillna(0)
        df['model_pred'] = df['model_pred'].clip(lower=0)

        for key in self.WEIGHT_KEYS:
            df[f'weight_{key}'] = float(weights.get(key, 0) or 0)

        df['baseline_model'] = 'LGB'
        df['baseline_pred'] = df['model_pred']
        df['term_model'] = df['model_pred'] * df['weight_model_weight']
        df['term_3m_mean'] = df['qty_lag1_3m_mean'] * df['weight_3m_mean_weight']
        df['term_lag12'] = df['qty_lag12'] * df['weight_lag12_weight']
        df['term_bias'] = -df['pred_bias'] * df['weight_model_bias_weight']

        strategy_mapping = {
            '冰箱V': self._v_series_strategy,
            '冰箱T': self._t_series_strategy,
            '冰箱L': self._l_series_strategy,
            '冰箱S': self._s_series_strategy,
            '洗衣机V': self._v_wm_strategy,
            '洗衣机T': self._t_wm_strategy,
            '洗衣机L': self._l_wm_strategy,
            '洗衣机Q': self._s_wm_strategy,
            '洗衣机S': self._s_wm_strategy,
        }
        strategy_func = strategy_mapping.get(skytype + series, lambda d, w: d['model_pred'])
        strategy_pred = strategy_func(df, weights)
        df['strategy_pred'] = strategy_pred.round(0).astype(float).clip(lower=0)
        df['y_pred'] = df['strategy_pred']
        df['post_process_rule'] = 'series_strategy'
        df['method'] = df.get('method', 'LGB')
        return df

    def _enrich_ma(self, df):
        df = df.copy()
        if 'model_pred' not in df.columns:
            df['model_pred'] = np.nan
        df['baseline_model'] = 'MA'
        df['baseline_pred'] = df['y_pred']
        df['strategy_pred'] = df['y_pred']
        for key in self.WEIGHT_KEYS:
            df[f'weight_{key}'] = np.nan
        df['term_model'] = np.nan
        df['term_3m_mean'] = np.nan
        df['term_lag12'] = np.nan
        df['term_bias'] = np.nan
        df['pred_bias'] = df.get('pred_bias', np.nan)
        df['post_process_rule'] = 'MA'
        df['method'] = 'MA'
        return df

    def EOL_adjustment(self, df):
        """淘汰/新品后处理，并写入 post_process_rule。"""
        df = df.copy()
        df['qty_lag1'] = df['qty_lag1'].fillna(0) if 'qty_lag1' in df.columns else 0
        if 'lag1_diff1' not in df.columns:
            df['lag1_diff1'] = 0
        df['lag1_diff1'] = df['lag1_diff1'].fillna(0)
        df['qty_lag1_3m_mean'] = df['qty_lag1_3m_mean'].fillna(0) if 'qty_lag1_3m_mean' in df.columns else 0
        df['model_pred'] = df['model_pred'].fillna(0)
        df['y_pred'] = df['y_pred'].fillna(0)

        denom = df['qty_lag1'] - df['lag1_diff1']
        df['eol_ratio'] = (df['qty_lag1'] / denom.replace(0, np.nan)).replace([np.inf, -np.inf], 0).fillna(0)

        def _row_adjust(row):
            status = row.get('status')
            if status in ('预淘汰', '淘汰'):
                if row['eol_ratio'] > 1:
                    pred = row['qty_lag1'] * 0.9
                else:
                    pred = row['eol_ratio'] * row['qty_lag1']
                    pred = pred if pred > 0 else 0
                return pred, 'EOL_decline'

            if status == '新品':
                if row['qty_lag1'] == 0:
                    return row['model_pred'], 'new_product_blend'
                if row['model_pred'] > 0 and row['qty_lag1_3m_mean'] == 0:
                    return 0.7 * row['qty_lag1'] + 0.3 * row['model_pred'], 'new_product_blend'
                if row['model_pred'] == 0 and row['qty_lag1_3m_mean'] > 0:
                    return 0.7 * row['qty_lag1'] + 0.3 * row['qty_lag1_3m_mean'], 'new_product_blend'
                if row['model_pred'] == 0 and row['qty_lag1_3m_mean'] == 0:
                    return row['qty_lag1'] * 1.1, 'new_product_blend'
                return (
                    0.5 * row['qty_lag1'] + 0.2 * row['model_pred'] + 0.3 * row['qty_lag1_3m_mean'],
                    'new_product_blend',
                )

            return row['y_pred'], row.get('post_process_rule', 'series_strategy')

        adjusted = df.apply(_row_adjust, axis=1, result_type='expand')
        df['y_pred'] = adjusted[0].round(0).astype(float).clip(lower=0)
        df['post_process_rule'] = adjusted[1]
        return df

    def _v_series_strategy(self, df, weights):
        common_term = (
            df['qty_lag1_3m_mean'] * weights['3m_mean_weight']
            + df['qty_lag12'] * weights['lag12_weight']
            - df['pred_bias'] * weights['model_bias_weight']
        )
        is_target = df['3级渠道'].isin([
            '淘系直营', '天猫大官旗', '淘系分销', '京东自营', '拼多多品旗', '拼多多大官旗', '拼多多分销',
            '抖音分销', '抖音直营', '会员商城', '京东POP大官旗', '京东POP分销', '京东POP',
        ])
        return df['model_pred'] * weights['model_weight'] + common_term.where(is_target, 0)

    def _t_series_strategy(self, df, weights):
        common_term = (
            df['qty_lag1_3m_mean'] * weights['3m_mean_weight']
            - df['pred_bias'] * weights['model_bias_weight']
        )
        is_target = df['3级渠道'].isin(['淘系直营', '天猫大官旗', '淘系分销', '京东自营', '抖音分销', '抖音直营'])
        return df['model_pred'] * weights['model_weight'] + common_term.where(is_target, 0)

    def _l_series_strategy(self, df, weights):
        common_term = (
            df['qty_lag1_3m_mean'] * weights['3m_mean_weight']
            - df['pred_bias'] * weights['model_bias_weight']
            + df['qty_lag12'] * weights['lag12_weight']
        )
        is_target = df['3级渠道'].isin(['京东自营', '拼多多品旗', '拼多多大官旗', '拼多多分销'])
        return df['model_pred'] * weights['model_weight'] + common_term.where(is_target, 0)

    def _s_series_strategy(self, df, weights):
        common_term = (
            df['qty_lag1_3m_mean'] * weights['3m_mean_weight']
            - df['pred_bias'] * weights['model_bias_weight']
            + df['qty_lag12'] * weights['lag12_weight']
        )
        is_target = df['3级渠道'].isin(['京东自营', '会员商城'])
        return df['model_pred'] * weights['model_weight'] + common_term.where(is_target, 0)

    def _l_wm_strategy(self, df, weights):
        common_term = (
            df['qty_lag1_3m_mean'] * weights['3m_mean_weight']
            - df['pred_bias'] * weights['model_bias_weight']
            + df['qty_lag12'] * weights['lag12_weight']
        )
        is_target = df['3级渠道'].isin([
            '淘系直营', '天猫大官旗', '淘系分销', '京东自营', '拼多多品旗', '拼多多大官旗', '拼多多分销',
            '抖音分销', '抖音直营', '会员商城', '京东POP大官旗', '京东POP分销', '京东POP',
        ])
        return df['model_pred'] * weights['model_weight'] + common_term.where(is_target, 0)

    def _v_wm_strategy(self, df, weights):
        return self._l_wm_strategy(df, weights)

    def _t_wm_strategy(self, df, weights):
        common_term = (
            df['qty_lag1_3m_mean'] * weights['3m_mean_weight']
            - df['pred_bias'] * weights['model_bias_weight']
            + df['qty_lag12'] * weights['lag12_weight']
        )
        is_jd_self = df['3级渠道'] == '京东自营'
        return df.apply(
            lambda row: row['model_pred'] * weights['model_weight'] + common_term[row.name]
            if is_jd_self[row.name]
            else row['qty_lag1_3m_mean'],
            axis=1,
        )

    def _s_wm_strategy(self, df, weights):
        return self._t_wm_strategy(df, weights)
