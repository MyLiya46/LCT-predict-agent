# -*- coding: utf-8 -*-
"""统计口径模块（feat-icewash §9）。

口径归类（已核实，源方案 §9）：
  A 已有    —— 直接从 detailed_results 既有特征列导出（不新增计算）。
  B 可派生  —— 由历史 rows / 既有列组合统计（零值率·非零期·SKU 构成分类）。
  C 真正新计算（仅 1 项）—— WAPE：预测 vs 实际成对回测；
               现仅训练期 pred_bias，以「训练期回测近似」【假设】，真回测待模型侧确认后升级。

产出：每项「字段名 + 层级（批次 / SKU / 型号×渠道）」，供 report 卡指标行与 LLM 报告正文消费。
纯导出模块：不落 PG、不改 backend、不触碰 pipeline 计算段。
"""
from __future__ import annotations

from typing import List, Dict

import numpy as np
import pandas as pd


# SKU 构成分类阈值（默认值【假设】，配置化可调；待模型侧拍板后升级）
DEFAULT_CLASS_THRESHOLDS: Dict[str, float] = {
    "sparse_max_cv": 1.5,      # 稀疏：CV 高于该值
    "intermittent_max_nz": 3,  # 间歇：非零期 <= 该值
    "trend_min_delta_ratio": 0.15,   # 趋势：|相对变化率| 高于该值
    "decline_min_eol_ratio": 0.5,    # 衰退：eol_ratio 不低于该值
}

CLASS_ORDER = ["稳定", "趋势", "间歇", "稀疏", "衰退", "新品"]


def _as_float(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="coerce")


def _build_sku_hist_stats(history: pd.DataFrame) -> pd.DataFrame:
    """B 类可派生：按 SKU（3级渠道×型号）统计零值率 / 非零期 / 月均 / CV。

    历史 rows 列：月份 / 3级渠道 / 型号-CRM最新名称 / 数量。
    """
    if history is None or history.empty:
        return pd.DataFrame()
    h = history.copy()
    h["数量"] = _as_float(h.get("数量", 0)).fillna(0.0)
    keys = ["3级渠道", "型号-CRM最新名称"]
    if not set(keys).issubset(h.columns):
        return pd.DataFrame()

    rows = []
    for key, g in h.groupby(keys):
        qty = g["数量"]
        n = len(qty)
        zero_rate = (qty == 0).mean() if n else np.nan
        nz_periods = int((qty > 0).sum())
        mean = qty.mean() if n else np.nan
        std = qty.std(ddof=0) if n else np.nan
        cv = (std / mean) if mean and mean > 0 else np.nan
        rows.append({
            "3级渠道": key[0],
            "型号-CRM最新名称": key[1],
            "历史月份数": n,
            "零值率": zero_rate,
            "非零期": nz_periods,
            "月均销量": mean,
            "销量CV": cv,
        })
    return pd.DataFrame(rows)


def _classify_sku(row: pd.Series, th: Dict[str, float]) -> str:
    """SKU 构成分类（稳定/趋势/间歇/稀疏/衰退/新品）。

    判据（组合，源方案 §9 B）：status / eol_ratio + CV + 非零期 + 近期趋势。
    阈值走默认值【假设】，配置化可调。
    """
    status = str(row.get("status", "") or "")
    eol = _as_float(pd.Series([row.get("eol_ratio", np.nan)])).iloc[0]
    cv = row.get("销量CV", np.nan)
    nz = row.get("非零期", np.nan)
    delta = row.get("delta_y", np.nan)
    base = row.get("月均销量", np.nan)

    # 新品：无历史或非零期极低 + 状态含「新品」
    if "新品" in status or (np.isfinite(nz) and nz <= 1):
        return "新品"
    # 衰退：状态含「衰退」或 eol_ratio 高（近下市）
    if "衰退" in status or (np.isfinite(eol) and eol >= th["decline_min_eol_ratio"]):
        return "衰退"
    # 间隙：非零期很少
    if np.isfinite(nz) and nz <= th["intermittent_max_nz"]:
        return "间歇"
    # 稀疏：高 CV
    if np.isfinite(cv) and cv > th["sparse_max_cv"]:
        return "稀疏"
    # 趋势：相对变化率显著（delta/月均），有方向性
    if np.isfinite(delta) and np.isfinite(base) and base > 0 \
            and abs(delta / base) > th["trend_min_delta_ratio"]:
        return "趋势"
    return "稳定"


def compute_stats(detailed_results: pd.DataFrame, history_results: pd.DataFrame,
                  thresholds: Dict[str, float] | None = None) -> pd.DataFrame:
    """统计口径出口：返回「字段名 + 层级」宽表（一批次策略字段复用 per-SKU 统计）。

    返回 DataFrame，列为字段名；含 '_层级' 辅助列（batch/sku/channel×sku）。
    """
    th = {**DEFAULT_CLASS_THRESHOLDS, **(thresholds or {})}
    detail = pd.DataFrame() if detailed_results is None else detailed_results.copy()
    sku_hist = _build_sku_hist_stats(history_results)

    if detail.empty:
        return pd.DataFrame()

    # ---- A 类：已有特征列直接导出（每明细行一层级）----
    out = pd.DataFrame()
    id_cols = [c for c in ["大类", "品类", "series", "3级渠道", "型号-CRM最新名称", "horizon"] if c in detail.columns]
    id_cols = id_cols or ["3级渠道", "型号-CRM最新名称"]
    out[id_cols] = detail[id_cols]

    for src_name, dst_name in [
        ("method", "方法_MA依据"),
        ("baseline_model", "基线模型"),
        ("term_3m_mean", "近3月均"),
        ("term_lag12", "去年同期"),
        ("avg_price", "均价"),
    ]:
        if src_name in detail.columns:
            out[dst_name] = detail[src_name]

    # 近期趋势 delta_y（派生自 y_pred - qty_lag1，qty_lag1 为既有特征列）
    if "y_pred" in detail.columns and "qty_lag1" in detail.columns:
        out["近期趋势_delta_y"] = _as_float(detail["y_pred"]) - _as_float(detail["qty_lag1"])

    # 波动/CV/月均特征列透出（qty_lag{3,6,12}m_{mean,cv,std,skew,kurt}）
    wave_cols = [c for c in detail.columns
                 if any(c.startswith(p) for p in ("qty_lag1_3m_", "qty_lag1_6m_", "qty_lag1_12m_"))]
    for c in wave_cols:
        out[c] = detail[c]

    # ---- B 类：合并 SKU 历史统计 + 分类 ----
    if not sku_hist.empty:
        out = out.merge(sku_hist, on=["3级渠道", "型号-CRM最新名称"], how="left")
        class_input = out[["status", "eol_ratio", "销量CV", "非零期", "delta_y"]].copy() \
            if "status" in out.columns else sku_hist.copy()
        # 分类输入补 eol_ratio/delta_y（从 detail 一次取，降低复杂度）
    if not sku_hist.empty:
        merge_extra = detail[["3级渠道", "型号-CRM最新名称"] + [c for c in ["status", "eol_ratio"] if c in detail.columns]] \
            .drop_duplicates(["3级渠道", "型号-CRM最新名称"])
        out = out.merge(merge_extra, on=["3级渠道", "型号-CRM最新名称"], how="left", suffixes=("", "_cls"))
        for c in ["status", "eol_ratio"]:
            if f"{c}_cls" in out.columns:
                out[c] = out[c].fillna(out[f"{c}_cls"])
                out.drop(columns=[f"{c}_cls"], inplace=True)
        out["delta_y"] = out["近期趋势_delta_y"] if "近期趋势_delta_y" in out.columns else np.nan
        out["SKU构成分类"] = out.apply(lambda r: _classify_sku(r, th), axis=1)

    # ---- C 类：WAPE（训练期回测近似【假设】）----
    if "pred_bias" in out.columns or "pred_bias" in detail.columns:
        bias = detail["pred_bias"] if "pred_bias" in detail.columns else out["pred_bias"]
        # 训练期回测近似：|pred_bias| / max(|y_pred|,1) 作为 WAPE 近似；真回测待模型侧
        denom = _as_float(detail["y_pred"]).abs().clip(lower=1.0) if "y_pred" in detail.columns else pd.Series([1.0] * len(detail))
        wape_approx = (_as_float(bias).abs() / denom).where(denom.notna())
        out["WAPE_训练期回测近似"] = wape_approx.values if isinstance(wape_approx, pd.Series) else wape_approx

    # ---- 层级标注（批次 / SKU / 型号×渠道）----
    out["_层级"] = out["型号-CRM最新名称"].apply(
        lambda x: "型号×渠道" if pd.notna(x) else "批次"
    ) if "型号-CRM最新名称" in out.columns else "批次"

    return out