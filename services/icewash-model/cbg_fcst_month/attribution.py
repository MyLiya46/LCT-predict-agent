# -*- coding: utf-8 -*-
"""白盒归因：TreeSHAP（基准=目标预测月上月）+ 后处理过程差分。"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd


KEY_COLS = ['3级渠道', '型号-CRM最新名称']

# ---------------------------------------------------------------------------
# 供应链计划视角：特征 → 归因类型映射
# ---------------------------------------------------------------------------

ATTRIBUTION_TYPE_DEFINITIONS = {
    '近期销售趋势': '近 1~3 月销量水平、波动与环比动能，反映短期动销',
    '中期销售趋势': '近半年销量形态与稳定性，反映中期趋势',
    '同比与年度趋势': '同比/年度基线与长周期波动',
    '季节性': '月份节奏与春节等季节性因素',
    '价格影响': '价格水平、调价幅度与价格弹性',
    '渠道与份额': '渠道位置、份额及系列池流量结构',
    '产品属性': '型号/品类结构、容积、在售状态等产品侧属性',
    '模型基线': '树模型截距及未进入 Top-K 的残余 SHAP',
    '规则与后处理': 'MA/新品合成/淘汰下滑/过渡/零价门禁等业务规则调整',
    '其他未分类': '未命中映射规则的因子，便于发现映射缺口',
}

# 精确因子名（优先匹配）
_EXACT_FACTOR_TYPE = {
    'lag1_diff1': '近期销售趋势',
    'month': '季节性',
    'year': '同比与年度趋势',
    'is_spring_festival': '季节性',
    'avg_price': '价格影响',
    'price_change': '价格影响',
    'price_elasticity': '价格影响',
    'price_lag1': '价格影响',
    '3级渠道': '渠道与份额',
    'total_series_lag1_qty': '渠道与份额',
    '型号-CRM最新名称': '产品属性',
    'type': '产品属性',
    'volume': '产品属性',
    'is_onsale': '产品属性',
    'SHAP_bias': '模型基线',
    'other_shap': '模型基线',
    'MA_vs_qty_lag1': '规则与后处理',
    'new_product_blend': '规则与后处理',
    'EOL_decline': '规则与后处理',
    'series_strategy': '规则与后处理',
    'MA': '规则与后处理',
    'rule': '规则与后处理',
}

# 前缀规则：(匹配方式, 模式, 归因类型) — 按顺序首次命中
_PREFIX_FACTOR_TYPE = [
    ('prefix', 'qty_lag1_3m_', '近期销售趋势'),
    ('prefix', 'qty_lag1_6m_', '中期销售趋势'),
    ('prefix', 'qty_lag1_12m_', '同比与年度趋势'),
    ('prefix', 'share_', '渠道与份额'),
    ('prefix', 'price_', '价格影响'),
]

# 规则层常用子串 → 规则与后处理
_RULE_SUBSTRINGS = (
    'zero_price', 'transition', 'EOL', 'new_product', 'series_strategy', 'blend', 'MA',
)


def resolve_attribution_type(factor_name, factor_layer: Optional[str] = None) -> str:
    """将影响因子映射为供应链计划视角的归因类型。"""
    name = '' if factor_name is None or (isinstance(factor_name, float) and np.isnan(factor_name)) else str(factor_name)
    layer = '' if factor_layer is None else str(factor_layer)

    if name in _EXACT_FACTOR_TYPE:
        return _EXACT_FACTOR_TYPE[name]

    # qty_lag 精确匹配（长阶数优先，避免 lag1 误伤 lag10+）
    for lag_n, typ in (
        (12, '同比与年度趋势'), (11, '同比与年度趋势'), (10, '同比与年度趋势'),
        (9, '同比与年度趋势'), (8, '同比与年度趋势'), (7, '同比与年度趋势'),
        (6, '中期销售趋势'), (5, '中期销售趋势'), (4, '中期销售趋势'),
        (3, '近期销售趋势'), (2, '近期销售趋势'), (1, '近期销售趋势'),
    ):
        if name == f'qty_lag{lag_n}':
            return typ

    for mode, pattern, typ in _PREFIX_FACTOR_TYPE:
        if mode == 'prefix' and name.startswith(pattern):
            return typ

    if layer in ('rule', 'ma'):
        return '规则与后处理'

    for sub in _RULE_SUBSTRINGS:
        if sub in name:
            return '规则与后处理'

    return '其他未分类'


def annotate_attribution_types(factors: pd.DataFrame) -> pd.DataFrame:
    """为归因明细写入 factor_type、type_impact（同键同类型影响量合计）。"""
    if factors is None or factors.empty:
        return factors
    out = factors.copy()
    layers = out['factor_layer'] if 'factor_layer' in out.columns else pd.Series('', index=out.index)
    out['factor_type'] = [
        resolve_attribution_type(n, ly)
        for n, ly in zip(out.get('factor_name', pd.Series(index=out.index)), layers)
    ]
    group_keys = [c for c in KEY_COLS + ['月份', 'factor_type'] if c in out.columns]
    if 'shap_value' in out.columns and group_keys:
        out['type_impact'] = out.groupby(group_keys, dropna=False)['shap_value'].transform('sum')
    else:
        out['type_impact'] = out.get('shap_value', np.nan)
    return out


def build_attribution_mapping_sheet() -> pd.DataFrame:
    """导出「归因映射」Sheet：类型定义 + 特征/规则模式对照。"""
    rows = []
    # 类型总览
    for i, (typ, desc) in enumerate(ATTRIBUTION_TYPE_DEFINITIONS.items(), 1):
        rows.append({
            '序号': i,
            '归因类型': typ,
            '业务含义': desc,
            '影响因子或规则模式': '（类型定义）',
            '匹配方式': '类型说明',
            '备注': '',
        })

    # 精确映射
    for name, typ in sorted(_EXACT_FACTOR_TYPE.items(), key=lambda x: (x[1], x[0])):
        rows.append({
            '序号': '',
            '归因类型': typ,
            '业务含义': ATTRIBUTION_TYPE_DEFINITIONS.get(typ, ''),
            '影响因子或规则模式': name,
            '匹配方式': '精确匹配',
            '备注': '',
        })

    # lag 精确
    for lag_n, typ in (
        (1, '近期销售趋势'), (2, '近期销售趋势'), (3, '近期销售趋势'),
        (4, '中期销售趋势'), (5, '中期销售趋势'), (6, '中期销售趋势'),
        (7, '同比与年度趋势'), (8, '同比与年度趋势'), (9, '同比与年度趋势'),
        (10, '同比与年度趋势'), (11, '同比与年度趋势'), (12, '同比与年度趋势'),
    ):
        rows.append({
            '序号': '',
            '归因类型': typ,
            '业务含义': ATTRIBUTION_TYPE_DEFINITIONS.get(typ, ''),
            '影响因子或规则模式': f'qty_lag{lag_n}',
            '匹配方式': '精确匹配',
            '备注': '销量滞后阶数',
        })

    # 前缀规则（统计特征）
    for mode, pattern, typ in _PREFIX_FACTOR_TYPE:
        if mode != 'prefix':
            continue
        rows.append({
            '序号': '',
            '归因类型': typ,
            '业务含义': ATTRIBUTION_TYPE_DEFINITIONS.get(typ, ''),
            '影响因子或规则模式': f'{pattern}*',
            '匹配方式': '前缀匹配',
            '备注': '',
        })

    rows.append({
        '序号': '',
        '归因类型': '规则与后处理',
        '业务含义': ATTRIBUTION_TYPE_DEFINITIONS['规则与后处理'],
        '影响因子或规则模式': '含 zero_price/transition/EOL/new_product/series_strategy/blend/MA 等',
        '匹配方式': '子串匹配或因子层=rule/ma',
        '备注': '后处理规则名常带组合后缀',
    })
    rows.append({
        '序号': '',
        '归因类型': '其他未分类',
        '业务含义': ATTRIBUTION_TYPE_DEFINITIONS['其他未分类'],
        '影响因子或规则模式': '*',
        '匹配方式': '兜底',
        '备注': '未命中以上规则时落入此类',
    })
    return pd.DataFrame(rows)


class ShapExplainer:
    """基于 LightGBM pred_contrib 的 TreeSHAP；相对基准为上一月同键特征。"""

    @staticmethod
    def resolve_feature_names(gbm, feature_names: Optional[list] = None) -> list:
        """优先使用 Booster 内特征序，与训练一致。"""
        names = None
        if gbm is not None:
            try:
                names = list(gbm.feature_name())
            except Exception:
                names = None
        if names:
            return names
        return list(feature_names or [])

    @staticmethod
    def absolute_shap(gbm, X: pd.DataFrame, feature_names: list) -> pd.DataFrame:
        """返回绝对 SHAP 贡献宽表（不含主键），列 = feature_names + contrib_bias。"""
        if X is None or X.empty or gbm is None:
            return pd.DataFrame()
        ordered = list(feature_names)
        matrix = gbm.predict(X[ordered], pred_contrib=True)
        cols = ordered + ['contrib_bias']
        # 用 RangeIndex，避免与 meta 拼接时因同名特征列冲突
        return pd.DataFrame(matrix, columns=cols)

    @classmethod
    def relative_to_prior_month(
        cls,
        gbm,
        curr_rows: pd.DataFrame,
        prior_rows: pd.DataFrame,
        feature_names: list,
        meta_cols: Optional[list] = None,
    ) -> pd.DataFrame:
        """
        对当期每一行，相对「目标月上月」同 SKU×渠道 计算 φ_j^(T|T-1)。

        主键与 SHAP 贡献列分离，避免 MODEL_FEATURES 含主键时出现重复列。
        返回长表：keys、月份、shap_base、factor_name、shap_value、value_T、value_T_1。
        """
        if gbm is None or curr_rows is None or curr_rows.empty:
            return pd.DataFrame()

        ordered = cls.resolve_feature_names(gbm, feature_names)
        if not ordered:
            return pd.DataFrame()
        missing = [c for c in ordered if c not in curr_rows.columns]
        if missing:
            raise ValueError(f"SHAP 缺少特征列: {missing[:5]}")

        meta_cols = [c for c in (meta_cols or []) if c in curr_rows.columns and c not in KEY_COLS + ['月份']]
        contrib_cols = ordered + ['contrib_bias']

        curr = curr_rows.reset_index(drop=True).copy()
        curr['月份'] = pd.to_datetime(curr['月份'])

        # meta 与贡献严格分列：主键只从 curr 取，不与 SHAP 宽表 concat 同名列
        meta_curr = curr[KEY_COLS + ['月份'] + meta_cols].copy()
        shap_t = cls.absolute_shap(gbm, curr, ordered)
        shap_t.columns = [f'_phi_{c}' for c in contrib_cols]

        # 特征值（用于 value_T）
        feat_t = curr[ordered].copy()
        feat_t.columns = [f'_val_{c}' for c in ordered]

        curr_wide = pd.concat([meta_curr, shap_t, feat_t], axis=1)

        prior = prior_rows.copy() if prior_rows is not None and not prior_rows.empty else pd.DataFrame()
        if not prior.empty:
            prior = prior.reset_index(drop=True).copy()
            prior['月份'] = pd.to_datetime(prior['月份'])
            prior_miss = [c for c in ordered if c not in prior.columns]
            if prior_miss:
                prior = pd.DataFrame()

        if not prior.empty:
            meta_prior = prior[KEY_COLS + ['月份']].copy()
            shap_p = cls.absolute_shap(gbm, prior, ordered)
            shap_p.columns = [f'_phi_{c}' for c in contrib_cols]
            feat_p = prior[ordered].copy()
            feat_p.columns = [f'_val_{c}' for c in ordered]
            prior_wide = pd.concat([meta_prior, shap_p, feat_p], axis=1)
            prior_wide = prior_wide.drop_duplicates(KEY_COLS, keep='last')
            prior_wide = prior_wide.rename(columns={'月份': 'shap_base_month'})
        else:
            prior_wide = pd.DataFrame(columns=KEY_COLS + ['shap_base_month'])

        merged = curr_wide.merge(prior_wide, on=KEY_COLS, how='left', suffixes=('', '_p'))
        has_prior = merged['shap_base_month'].notna() if 'shap_base_month' in merged.columns else pd.Series(False, index=merged.index)
        merged['shap_base'] = np.where(has_prior, 'prior_month', 'no_prior_month')

        # 相对差分：有 prior 用 φ_T - φ_{T-1}；否则用绝对 φ_T
        # 列名加前缀，避免与主键/特征同名导致 melt 失败
        delta_frames = []
        for c in contrib_cols:
            phi_t = merged[f'_phi_{c}']
            phi_p_col = f'_phi_{c}_p'
            if phi_p_col in merged.columns:
                phi_p = merged[phi_p_col]
                delta = np.where(has_prior, phi_t - phi_p.fillna(0), phi_t)
                delta = np.where(has_prior & phi_p.isna(), phi_t, delta)
            else:
                delta = phi_t.to_numpy()
            delta_frames.append(pd.Series(delta, index=merged.index, name=f'_d_{c}'))
        delta_df = pd.concat(delta_frames, axis=1)
        delta_value_cols = [f'_d_{c}' for c in contrib_cols]

        # 校验：sum(相对SHAP) 应 ≈ pred_T - pred_{T-1}（有 prior）或 ≈ pred_T（无 prior）
        sum_delta = delta_df.sum(axis=1)
        pred_t = shap_t.sum(axis=1)  # sum of absolute φ_T == model pred
        phi_p_cols = [f'_phi_{c}_p' for c in contrib_cols if f'_phi_{c}_p' in merged.columns]
        if phi_p_cols:
            pred_p = merged[phi_p_cols].sum(axis=1)
            expected = np.where(has_prior, pred_t.to_numpy() - pred_p.fillna(0).to_numpy(), pred_t.to_numpy())
            expected = np.where(has_prior & pred_p.isna(), pred_t.to_numpy(), expected)
        else:
            expected = pred_t.to_numpy()
        residual = sum_delta.to_numpy() - expected
        abs_exp = np.abs(expected)
        bad = (np.abs(residual) > 1e-3) & (abs_exp > 1e-6) & (np.abs(residual) / np.maximum(abs_exp, 1e-9) > 0.05)
        n_bad = int(np.sum(bad))
        if len(merged):
            mean_abs_res = float(np.mean(np.abs(residual)))
            if n_bad:
                print(f"SHAP校验偏差偏大: rows={len(merged)}, bad={n_bad}, mean|residual|={mean_abs_res:.4f}")
            else:
                print(f"SHAP校验 OK: rows={len(merged)}, mean|residual|={mean_abs_res:.4f}")

        # melt 成长表
        id_cols = KEY_COLS + ['月份', 'shap_base']
        if 'shap_base_month' in merged.columns:
            id_cols.append('shap_base_month')
        id_cols += meta_cols
        # 去重且保证单列
        id_cols = list(dict.fromkeys(id_cols))

        long_phi = pd.concat([merged[id_cols].reset_index(drop=True), delta_df.reset_index(drop=True)], axis=1)
        long = long_phi.melt(
            id_vars=id_cols,
            value_vars=delta_value_cols,
            var_name='_feat',
            value_name='shap_value',
        )
        long['_feat'] = long['_feat'].str.replace(r'^_d_', '', regex=True)

        # value_T / value_T_1（同样加前缀，避免与主键同名）
        val_t_parts = [merged[KEY_COLS].reset_index(drop=True)]
        for c in ordered:
            val_t_parts.append(merged[f'_val_{c}'].rename(f'_vt_{c}'))
        val_t_wide = pd.concat(val_t_parts, axis=1)
        val_t_long = val_t_wide.melt(
            id_vars=KEY_COLS, value_vars=[f'_vt_{c}' for c in ordered],
            var_name='_feat', value_name='value_T',
        )
        val_t_long['_feat'] = val_t_long['_feat'].str.replace(r'^_vt_', '', regex=True)

        val_p_parts = [merged[KEY_COLS].reset_index(drop=True)]
        for c in ordered:
            col_p = f'_val_{c}_p'
            if col_p in merged.columns:
                val_p_parts.append(merged[col_p].rename(f'_vp_{c}'))
            else:
                val_p_parts.append(pd.Series(np.nan, index=merged.index, name=f'_vp_{c}'))
        val_p_wide = pd.concat(val_p_parts, axis=1)
        val_p_long = val_p_wide.melt(
            id_vars=KEY_COLS, value_vars=[f'_vp_{c}' for c in ordered],
            var_name='_feat', value_name='value_T_1',
        )
        val_p_long['_feat'] = val_p_long['_feat'].str.replace(r'^_vp_', '', regex=True)

        long = long.merge(val_t_long, on=KEY_COLS + ['_feat'], how='left')
        long = long.merge(val_p_long, on=KEY_COLS + ['_feat'], how='left')
        long.loc[long['_feat'] == 'contrib_bias', ['value_T', 'value_T_1']] = np.nan

        long['factor_name'] = np.where(long['_feat'] == 'contrib_bias', 'SHAP_bias', long['_feat'])
        long['factor_layer'] = 'shap'
        long = long.drop(columns=['_feat'])
        return long.reset_index(drop=True)


class WhiteboxAttributor:
    """组装白盒归因汇总与因子明细（SHAP + 后处理）。"""

    POST_TERM_COLS = [
        ('term_model', '过程项_模型'),
        ('term_3m_mean', '过程项_近3月均'),
        ('term_lag12', '过程项_去年同期'),
        ('term_bias', '过程项_偏差修正'),
    ]

    def __init__(self, top_k: int = 10):
        self.top_k = top_k

    def build(
        self,
        detailed_results: pd.DataFrame,
        shap_long: pd.DataFrame,
    ) -> tuple[pd.DataFrame, pd.DataFrame]:
        """
        返回 (attribution_summary, attribution_factors)。
        factors 写入 Excel「白盒归因」Sheet。
        """
        if detailed_results is None or detailed_results.empty:
            return pd.DataFrame(), pd.DataFrame()

        detail = detailed_results.copy()
        detail['月份'] = pd.to_datetime(detail['月份'])
        if 'qty_lag1' not in detail.columns:
            detail['qty_lag1'] = 0.0
        detail['qty_lag1'] = pd.to_numeric(detail['qty_lag1'], errors='coerce').fillna(0.0)
        detail['y_pred'] = pd.to_numeric(detail.get('y_pred', 0), errors='coerce').fillna(0.0)
        detail['delta_y'] = detail['y_pred'] - detail['qty_lag1']

        factor_parts = []
        if shap_long is not None and not shap_long.empty:
            sl = shap_long.copy()
            sl['月份'] = pd.to_datetime(sl['月份'])
            factor_parts.append(sl)

        post_factors = self._post_process_factors(detail)
        if not post_factors.empty:
            factor_parts.append(post_factors)

        if not factor_parts:
            return self._summary_only(detail), pd.DataFrame()

        factors = pd.concat(factor_parts, ignore_index=True)
        factors = self._attach_keys_from_detail(factors, detail)
        factors = self._topk_per_prediction(factors)
        factors = annotate_attribution_types(factors)
        summary = self._build_summary(detail, factors)
        return summary, factors

    def _post_process_factors(self, detail: pd.DataFrame) -> pd.DataFrame:
        rows = []
        for _, r in detail.iterrows():
            base = {
                '3级渠道': r['3级渠道'],
                '型号-CRM最新名称': r['型号-CRM最新名称'],
                '月份': r['月份'],
                '品类': r.get('品类'),
                'series': r.get('series'),
                'horizon': r.get('horizon'),
                'horizon_offset': r.get('horizon_offset'),
                'shap_base': 'post',
                'shap_base_month': np.nan,
            }
            # 规则层：最终预测相对策略合成的差额
            if 'strategy_pred' in detail.columns and pd.notna(r.get('strategy_pred')):
                rule_gap = float(r['y_pred']) - float(r['strategy_pred'])
                if abs(rule_gap) > 1e-6:
                    rows.append({
                        **base,
                        'factor_name': str(r.get('post_process_rule', 'rule')),
                        'factor_layer': 'rule',
                        'value_T': r['y_pred'],
                        'value_T_1': r['strategy_pred'],
                        'shap_value': rule_gap,
                    })
            # MA：无树 SHAP，用相对 qty_lag1 说明；LGB 不写，避免冲淡特征归因
            method = str(r.get('baseline_model') or r.get('method') or '')
            if method == 'MA':
                rows.append({
                    **base,
                    'factor_name': 'MA_vs_qty_lag1',
                    'factor_layer': 'ma',
                    'value_T': r['y_pred'],
                    'value_T_1': r['qty_lag1'],
                    'shap_value': float(r['y_pred']) - float(r['qty_lag1']),
                })
        return pd.DataFrame(rows)

    def _attach_keys_from_detail(self, factors: pd.DataFrame, detail: pd.DataFrame) -> pd.DataFrame:
        meta = detail[[
            c for c in [
                '3级渠道', '型号-CRM最新名称', '月份', '品类', 'series', 'status',
                'horizon', 'horizon_offset', 'baseline_model', 'method',
                'y_pred', 'qty_lag1', 'model_pred', 'delta_y',
            ] if c in detail.columns
        ]].drop_duplicates(KEY_COLS + ['月份'])
        out = factors.merge(meta, on=KEY_COLS + ['月份'], how='left', suffixes=('', '_d'))
        for c in ['品类', 'series', 'horizon', 'horizon_offset']:
            if f'{c}_d' in out.columns:
                out[c] = out[c].combine_first(out[f'{c}_d']) if c in out.columns else out[f'{c}_d']
                out.drop(columns=[f'{c}_d'], inplace=True, errors='ignore')
        return out

    def _topk_per_prediction(self, factors: pd.DataFrame) -> pd.DataFrame:
        """每个预测键保留 |shap_value| Top-K（shap 层），post/rule/ma 全保留。"""
        if factors.empty:
            return factors
        parts = []
        group_keys = [c for c in KEY_COLS + ['月份'] if c in factors.columns]
        for _, g in factors.groupby(group_keys, sort=False):
            shap_g = g[g['factor_layer'] == 'shap'].copy()
            other = g[g['factor_layer'] != 'shap'].copy()
            if not shap_g.empty:
                shap_g['_abs'] = shap_g['shap_value'].abs()
                top = shap_g.nlargest(self.top_k, '_abs')
                rest = shap_g.drop(top.index)
                if not rest.empty:
                    other_row = top.iloc[0].copy()
                    other_row['factor_name'] = 'other_shap'
                    other_row['shap_value'] = rest['shap_value'].sum()
                    other_row['value_T'] = np.nan
                    other_row['value_T_1'] = np.nan
                    top = pd.concat([top, pd.DataFrame([other_row])], ignore_index=True)
                top = top.drop(columns=['_abs'], errors='ignore')
                parts.append(top)
            if not other.empty:
                parts.append(other)
        out = pd.concat(parts, ignore_index=True) if parts else factors
        if 'shap_value' in out.columns:
            abs_sum = out.groupby(group_keys)['shap_value'].transform(lambda s: s.abs().sum())
            out['contribution_pct'] = np.where(
                abs_sum > 1e-9,
                out['shap_value'].abs() / abs_sum,
                0.0,
            )
        return out

    def _build_summary(self, detail: pd.DataFrame, factors: pd.DataFrame) -> pd.DataFrame:
        rows = []
        group_keys = KEY_COLS + ['月份']
        shap_sum = (
            factors[factors['factor_layer'] == 'shap']
            .groupby(group_keys, as_index=False)['shap_value']
            .sum()
            .rename(columns={'shap_value': 'sum_shap'})
            if not factors.empty and (factors['factor_layer'] == 'shap').any()
            else pd.DataFrame(columns=group_keys + ['sum_shap'])
        )
        merged = detail.merge(shap_sum, on=group_keys, how='left')
        for _, r in merged.iterrows():
            top = ''
            if not factors.empty:
                mask = (
                    (factors['3级渠道'] == r['3级渠道'])
                    & (factors['型号-CRM最新名称'] == r['型号-CRM最新名称'])
                    & (pd.to_datetime(factors['月份']) == pd.to_datetime(r['月份']))
                    & (factors['factor_layer'] == 'shap')
                )
                sub = factors.loc[mask].copy()
                if not sub.empty:
                    sub['_abs'] = sub['shap_value'].abs()
                    tops = sub.nlargest(min(5, self.top_k), '_abs')
                    top = '; '.join(
                        f"{n}:{v:.1f}" for n, v in zip(tops['factor_name'], tops['shap_value'])
                    )
            model_pred = r.get('model_pred', np.nan)
            sum_shap = r.get('sum_shap', np.nan)
            residual = np.nan
            if pd.notna(model_pred) and pd.notna(sum_shap):
                residual = float(r['delta_y']) - float(sum_shap) if pd.notna(sum_shap) else np.nan
            rows.append({
                '品类': r.get('品类'),
                'series': r.get('series'),
                'status': r.get('status'),
                '3级渠道': r['3级渠道'],
                '型号-CRM最新名称': r['型号-CRM最新名称'],
                '月份': r['月份'],
                'horizon': r.get('horizon'),
                'baseline_model': r.get('baseline_model', r.get('method')),
                'y_pred': r['y_pred'],
                'qty_lag1': r['qty_lag1'],
                'delta_y': r['delta_y'],
                'model_pred': model_pred,
                'sum_shap': sum_shap,
                'residual_vs_delta_y': residual,
                'post_process_rule': r.get('post_process_rule'),
                'top_factors': top,
            })
        return pd.DataFrame(rows)

    def _summary_only(self, detail: pd.DataFrame) -> pd.DataFrame:
        return self._build_summary(detail, pd.DataFrame())


def format_attribution_sheet(factors: pd.DataFrame) -> pd.DataFrame:
    """导出「白盒归因」Sheet 的中文列名。"""
    if factors is None or factors.empty:
        return pd.DataFrame()
    df = factors.copy()
    if 'factor_type' not in df.columns or 'type_impact' not in df.columns:
        df = annotate_attribution_types(df)
    if '月份' in df.columns:
        df['月份'] = pd.to_datetime(df['月份']).dt.strftime('%Y-%m')
    if 'shap_base_month' in df.columns:
        df['shap_base_month'] = pd.to_datetime(df['shap_base_month'], errors='coerce').dt.strftime('%Y-%m')

    rename = {
        'horizon': '预测期',
        'horizon_offset': '预测期序号',
        '月份': '预测月份',
        '品类': '品类',
        'series': '系列',
        'status': '状态',
        '3级渠道': '3级渠道',
        '型号-CRM最新名称': '型号',
        'baseline_model': '基线模型',
        'method': '方法',
        'y_pred': '最终预测值',
        'qty_lag1': '上月实际qty_lag1',
        'delta_y': '相对上月差异',
        'model_pred': '模型原始预测',
        'factor_layer': '因子层',
        'factor_name': '影响因子',
        'factor_type': '归因类型',
        'value_T': '因子当期值',
        'value_T_1': '因子上月值',
        'shap_value': '影响量_台',
        'type_impact': '类型影响量',
        'contribution_pct': '影响占比',
        'shap_base': 'SHAP基准类型',
        'shap_base_month': 'SHAP基准月',
    }
    prefer = [
        'horizon', '月份', '品类', 'series', 'status', '3级渠道', '型号-CRM最新名称',
        'baseline_model', 'y_pred', 'qty_lag1', 'delta_y', 'model_pred',
        'factor_layer', 'factor_name', 'factor_type', 'value_T', 'value_T_1',
        'shap_value', 'type_impact', 'contribution_pct',
        'shap_base', 'shap_base_month',
    ]
    cols = [c for c in prefer if c in df.columns] + [c for c in df.columns if c not in prefer and c not in ('_abs',)]
    out = df.reindex(columns=cols).rename(columns=rename)
    sort_keys = [c for c in ['品类', '3级渠道', '型号', '预测月份', '归因类型', '因子层'] if c in out.columns]
    if sort_keys:
        out = out.sort_values(by=sort_keys).reset_index(drop=True)
    return out
