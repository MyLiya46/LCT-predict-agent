# -*- coding: utf-8 -*-
"""icewash 写 PG 最小改造（feat-icewash §3.1~§3.3，T53）。

纯「写 PG + 读本地 CSV」加法，不改预测逻辑（pipeline.py/predictor.py/post_processor.py/attribution.py 零改动）：

1. `_write_forecast_to_pg` / `_write_attribution_to_pg`：main() 尾部追加调用，把预测结果明细与
   归因因子明细落到 PG 中转表（fcst_forecast_result / fcst_attribution）。
2. `sync_history_csv`：历史 CSV（data/ads_cbg_rt_fcst_retail_stat.csv）离线灌 fcst_history。

命名映射（单一出处）：
  历史：period_id→period, category_name→category, product_mode_name→sku, channel_name_l3→channel_l3, retail_qty→qty, retail_amt→retail_amt
  预测：horizon/月份/品类/series/status/3级渠道/型号-CRM最新名称/y_pred/plan_price →
        horizon/forecast_month/category/series/status/channel_l3/sku/final_value/plan_price
  归因：对齐 attribution.py format_attribution_sheet 的 rename（factor_name/factor_type/shap_value/contribution_pct/value_T 等）。

PG 引擎独立于 MySQL ENGINE_URL：新增 BACKEND_PG_URL（默认 app/app@127.0.0.1:5432/agent_platform），
写失败仅告警不阻断主流程（对齐「落 xlsx 始终成功」现状容错）。
"""
from __future__ import annotations

import os
from typing import Optional

import pandas as pd
from sqlalchemy import create_engine, text

DEFAULT_PG_URL = "postgresql+psycopg2://app:app@127.0.0.1:5432/agent_platform"


def _pg_url() -> str:
    return os.environ.get("BACKEND_PG_URL", DEFAULT_PG_URL)


def _to_sql_append(df: pd.DataFrame, table: str, url: str) -> None:
    """DataFrame append 到 PG（失败仅打印告警，不阻断）。"""
    if df is None or df.empty:
        return
    try:
        engine = create_engine(url)
        df.to_sql(table, con=engine, if_exists="append", index=False, chunksize=1000)
        engine.dispose()
        print(f"[pg_sync] {table} 写入 {len(df)} 行")
    except Exception as e:  # noqa: BLE001 - 写 PG 失败不阻断预测主流程
        print(f"[pg_sync] {table} 写入失败（不阻断主流程）: {e}")


def forecast_to_pg_frame(detailed_results: pd.DataFrame) -> pd.DataFrame:
    """预测明细 → fcst_forecast_result 列（英文短名）。"""
    if detailed_results is None or detailed_results.empty:
        return pd.DataFrame()
    df = detailed_results.copy()
    if "月份" in df.columns:
        df["月份"] = pd.to_datetime(df["月份"]).dt.strftime("%Y-%m")
    out = pd.DataFrame()
    out["horizon"] = df.get("horizon")
    out["forecast_month"] = df.get("月份")
    out["category"] = df.get("品类")
    out["series"] = df.get("series")
    out["status"] = df.get("status")
    out["channel_l3"] = df.get("3级渠道")
    out["sku"] = df.get("型号-CRM最新名称")
    out["final_value"] = pd.to_numeric(df.get("y_pred"), errors="coerce") if "y_pred" in df.columns else None
    out["plan_price"] = pd.to_numeric(df.get("plan_price"), errors="coerce") if "plan_price" in df.columns else None
    return out


def attribution_to_pg_frame(attribution_factors: pd.DataFrame) -> pd.DataFrame:
    """归因因子明细 → fcst_attribution 列（英文短名，对齐 attribution.py rename）。"""
    if attribution_factors is None or attribution_factors.empty:
        return pd.DataFrame()
    df = attribution_factors.copy()
    if "月份" in df.columns:
        df["月份"] = pd.to_datetime(df["月份"]).dt.strftime("%Y-%m")

    # 确保 factor_type/type_impact 已标注（annotate_attribution_types）
    if "factor_type" not in df.columns or "type_impact" not in df.columns:
        from attribution import annotate_attribution_types
        df = annotate_attribution_types(df)

    out = pd.DataFrame()
    out["horizon"] = df.get("horizon")
    out["forecast_month"] = df.get("月份")
    out["category"] = df.get("品类")
    out["series"] = df.get("series")
    out["status"] = df.get("status")
    out["channel_l3"] = df.get("3级渠道")
    out["sku"] = df.get("型号-CRM最新名称")
    out["baseline_model"] = df.get("baseline_model")
    out["y_pred"] = pd.to_numeric(df.get("y_pred"), errors="coerce") if "y_pred" in df.columns else None
    out["delta_y"] = pd.to_numeric(df.get("delta_y"), errors="coerce") if "delta_y" in df.columns else None
    out["factor_layer"] = df.get("factor_layer")
    out["factor_name"] = df.get("factor_name")
    out["factor_type"] = df.get("factor_type")
    out["value_T"] = pd.to_numeric(df.get("value_T"), errors="coerce") if "value_T" in df.columns else None
    out["value_T_1"] = pd.to_numeric(df.get("value_T_1"), errors="coerce") if "value_T_1" in df.columns else None
    out["shap_value"] = pd.to_numeric(df.get("shap_value"), errors="coerce") if "shap_value" in df.columns else None
    out["type_impact"] = pd.to_numeric(df.get("type_impact"), errors="coerce") if "type_impact" in df.columns else None
    out["contribution_pct"] = pd.to_numeric(df.get("contribution_pct"), errors="coerce") if "contribution_pct" in df.columns else None
    out["shap_base"] = df.get("shap_base")
    out["shap_base_month"] = df.get("shap_base_month")
    return out


def write_forecast_and_attribution(
    system_forecast_number: str,
    detailed_results: pd.DataFrame,
    attribution_factors: pd.DataFrame,
    pg_url: Optional[str] = None,
) -> dict:
    """预测 + 归因落 PG（main() 尾部追加）。返回 {forecast_rows, attribution_rows}。"""
    url = pg_url or _pg_url()
    fcast = forecast_to_pg_frame(detailed_results)
    if not fcast.empty:
        fcast = fcast.copy()
        fcast.insert(0, "system_forecast_number", system_forecast_number)
        _to_sql_append(fcast, "fcst_forecast_result", url)

    attr = attribution_to_pg_frame(attribution_factors)
    if not attr.empty:
        attr = attr.copy()
        attr.insert(0, "system_forecast_number", system_forecast_number)
        _to_sql_append(attr, "fcst_attribution", url)

    return {"forecast_rows": len(fcast), "attribution_rows": len(attr)}


def history_to_pg_frame(csv_path: str) -> pd.DataFrame:
    """历史 CSV → fcst_history 列（英文短名）。"""
    raw = pd.read_csv(csv_path, dtype={"product_mode_name": str, "channel_name_l3": str})
    out = pd.DataFrame()
    out["period"] = raw["period_id"].astype(str)
    out["category"] = raw["category_name"].astype(str)
    out["channel_l3"] = raw["channel_name_l3"].astype(str)
    out["sku"] = raw["product_mode_name"].astype(str)
    out["qty"] = pd.to_numeric(raw["retail_qty"], errors="coerce")
    out["retail_amt"] = pd.to_numeric(raw["retail_amt"], errors="coerce")
    return out


def sync_history_csv(csv_path: str, pg_url: Optional[str] = None) -> int:
    """历史 CSV 灌 fcst_history（事务内清空后 append，保留 identity 与索引）。"""
    url = pg_url or _pg_url()
    frame = history_to_pg_frame(csv_path)
    if frame.empty:
        print("[pg_sync] 历史 CSV 为空，跳过")
        return 0
    try:
        engine = create_engine(url)
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM fcst_history"))
            frame.to_sql("fcst_history", con=conn, if_exists="append", index=False, chunksize=1000)
        engine.dispose()
        print(f"[pg_sync] fcst_history 灌入 {len(frame)} 行（delete + append）")
        return len(frame)
    except Exception as e:  # noqa: BLE001
        print(f"[pg_sync] fcst_history 灌入失败: {e}")
        return 0


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="历史 CSV 灌 fcst_history")
    parser.add_argument("--csv", default="data/ads_cbg_rt_fcst_retail_stat.csv",
                        help="历史 CSV 路径（相对 cbg_fcst_month 或绝对路径）")
    parser.add_argument("--pg-url", default=None, help="PG 连接串，默认 BACKEND_PG_URL")
    args = parser.parse_args()

    csv_path = args.csv
    import os as _os
    if not _os.path.isabs(csv_path):
        csv_path = str(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", csv_path))
    n = sync_history_csv(csv_path, args.pg_url)
    print(f"完成：灌入 {n} 行")
