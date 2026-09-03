"""确定性看板 spec 生成（helper，零 LLM，【变更自 T43】）。

query_sales_data / predict_sales 执行成功且返回非空数据时，引擎调用
`build_dashboard_spec` 把返回数据自动映射为看板 spec（折线/柱状/表格），
不依赖 AI 判断、不额外调用 LLM。正常聊天（不调这两个工具）走不到此处，
天然「绝不触发」。

映射规则（启发式类型推断，列名 + 值类型双判定）：
- predict_sales：forecast:[{period,value}] → 折线（labels=period[]，单系列「预测值」）。
- query_sales_data：
    1. 空 rows → None（不呈现看板）；
    2. 列推断：日期列（month/date/time/period/…）为 x；数值列（amount/sales/… 或全数值）为 y；其余为维度；
    3. 有日期列 + 数值列 + 无变化维度 → 折线（单/多系列，x 对齐）；
    4. 有日期列 + 数值列 + 有变化维度 → 表格（按首个变化维度透视，gap 置空不丢数据）；
    5. 无日期列但有数值列、且行数少无变化维度 → 柱状；否则 → 表格；
    6. 无自然数值列 → 原始 rows 表格（兜底，不静默丢弃数据）。

返回 None 表示不呈现看板（空数据）。
"""
from __future__ import annotations

from typing import Any

# 会触发看板的工具名（确定性白名单，非 LLM 判断）
DASHBOARD_TOOL_NAMES = {"query_sales_data", "predict_sales"}

_DATE_PATTERNS = ("month", "date", "time", "period", "week", "year", "quarter", "日", "月", "年", "周", "季", "期")
_NUM_PATTERNS = ("amount", "sales", "value", "revenue", "count", "qty", "quantity", "price", "金额", "销售额", "销量", "数量", "价格", "值", "营收")


def build_dashboard_spec(tool_name: str, output: Any) -> dict[str, Any] | None:
    """据工具返回数据自动构 spec；无法映射/空数据 → None。"""
    data = _unwrap_output(output)
    if not isinstance(data, dict):
        return None
    if tool_name == "predict_sales":
        return _predict_spec(data)
    if tool_name == "query_sales_data":
        return _query_spec(data)
    return None


def _unwrap_output(output: Any) -> Any:
    """解包工具输出：沙箱工具 handler 返回 {ok, data:{...}}，daemon 可能原样透传一层
    {ok, data:{...}}（双包）。此处稳健归一：若外层 data 内藏 rows/forecast 则解一层。"""
    if isinstance(output, dict):
        inner = output.get("data")
        if isinstance(inner, dict) and ("rows" in inner or "forecast" in inner):
            return inner
        # 已是 {rows}/{forecast} 直挂 或 {ok,data} 但 data 非行/预测结构 → 原样
    return output


# ------------------------------------------------------------------
# predict_sales
# ------------------------------------------------------------------
def _predict_spec(output: dict[str, Any]) -> dict[str, Any] | None:
    forecast = output.get("forecast") or []
    if not isinstance(forecast, list) or not forecast:
        return None
    labels: list[str] = []
    values: list[float | None] = []
    for i, item in enumerate(forecast):
        if not isinstance(item, dict):
            continue
        labels.append(str(item.get("period", i)))
        v = item.get("value")
        values.append(float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None)
    if not labels or not any(v is not None for v in values):
        return None
    meta = output.get("meta") or {}
    description = ""
    if meta.get("horizon") is not None:
        description = f"未来 {meta['horizon']} 期"
    if meta.get("unit"):
        description = f"{description}（单位：{meta['unit']}）".strip("（）")
    card: dict[str, Any] = {
        "card_type": "line",
        "title": "销售预测",
        "data": {"labels": labels, "series": [{"name": "预测值", "values": values}]},
    }
    if description:
        card["description"] = description
    return {"layout": "single", "cards": [card]}


# ------------------------------------------------------------------
# query_sales_data
# ------------------------------------------------------------------
def _query_spec(output: dict[str, Any]) -> dict[str, Any] | None:
    rows = output.get("rows") or []
    if not isinstance(rows, list) or not rows:
        return None
    columns = output.get("columns") or _infer_columns(rows)
    if not isinstance(columns, list) or not columns:
        columns = _infer_columns(rows)

    date_col = _find_date_col(columns)
    num_cols = [c for c in columns if c != date_col and _is_numeric_col(c, rows)]
    dim_cols = [c for c in columns if c != date_col and c not in num_cols]

    if not num_cols:
        # 兜底：无数值列 → 原始 rows 表格（绝不丢数据）
        return _raw_table(rows, columns)

    varying_dims = [c for c in dim_cols if _distinct(rows, c) > 1]

    # 有日期列 → 时序
    if date_col is not None:
        if not varying_dims:
            return _time_series(rows, date_col, num_cols, card_type="line")
        # 有变化维度 → 透视表格（gap 置空，保留全量）
        return _pivot_table(rows, date_col, num_cols, varying_dims[0])

    # 无日期列
    if len(varying_dims) == 1 and len(rows) <= 24:
        # 单一分类维度 + 数值列 → 柱状（x=该维去重值，每数值列一条 series）
        dim = varying_dims[0]
        labels = [str(r.get(dim)) for r in rows if isinstance(r, dict) and r.get(dim) is not None]
        series = [{"name": c, "values": [_num(r.get(c)) for r in rows if isinstance(r, dict) and r.get(dim) is not None]} for c in num_cols]
        return _single(card_type="bar", labels=labels, series=series)
    if varying_dims:
        # 多分类维度交织 → 透视表格
        return _pivot_table(rows, varying_dims[0], num_cols, varying_dims[0])
    # 无维度分组（如仅数值列）→ 表格
    labels = _labels_nodate(rows, dim_cols)
    series = [{"name": c, "values": [_num(r.get(c)) for r in rows]} for c in num_cols]
    return _single(card_type="table", labels=labels, series=series)


# ------------------------------------------------------------------
# 列/值推断
# ------------------------------------------------------------------
def _infer_columns(rows: list[Any]) -> list[str]:
    for r in rows:
        if isinstance(r, dict):
            return list(r.keys())
    return []


def _find_date_col(columns: list[str]) -> str | None:
    for c in columns:
        if _match(c, _DATE_PATTERNS):
            return c
    return None


def _match(name: str, patterns: tuple[str, ...]) -> bool:
    low = str(name).lower()
    return any(p in low for p in patterns)


def _numeric_value(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _is_numeric_col(name: str, rows: list[Any]) -> bool:
    if _match(name, _NUM_PATTERNS):
        return True
    vals = [r.get(name) for r in rows if isinstance(r, dict) and r.get(name) is not None]
    return bool(vals) and all(_numeric_value(v) for v in vals)


def _distinct(rows: list[Any], col: str) -> int:
    return len({str(r.get(col)) for r in rows if isinstance(r, dict) and r.get(col) is not None})


def _num(v: Any) -> float | None:
    return float(v) if _numeric_value(v) else None


# ------------------------------------------------------------------
# card 构造
# ------------------------------------------------------------------
def _single(card_type: str, labels: list[str], series: list[dict[str, Any]]) -> dict[str, Any]:
    return {"layout": "single", "cards": [{"card_type": card_type, "title": "", "data": {"labels": labels, "series": series}}]}


def _time_series(rows: list[Any], x_col: str, num_cols: list[str], card_type: str = "line") -> dict[str, Any]:
    labels = [str(r.get(x_col)) for r in rows if isinstance(r, dict)]
    series = [{"name": c, "values": [_num(r.get(c)) for r in rows if isinstance(r, dict)]} for c in num_cols]
    return _single(card_type=card_type, labels=labels, series=series)


def _pivot_table(rows: list[Any], x_col: str, num_cols: list[str], dim_col: str) -> dict[str, Any]:
    """按 dim 透视：labels=去重后的 x 值；每个 (dim 值 × num 列) 一个 series，gap 置 None。"""
    x_values = _unique(*[str(r.get(x_col)) for r in rows if isinstance(r, dict)])
    dim_values = _unique(*[str(r.get(dim_col)) for r in rows if isinstance(r, dict) and r.get(dim_col) is not None])
    series: list[dict[str, Any]] = []
    for dv in dim_values:
        for nc in num_cols:
            vals: list[float | None] = []
            for xv in x_values:
                row = next((r for r in rows if isinstance(r, dict) and str(r.get(x_col)) == xv and str(r.get(dim_col)) == dv), None)
                vals.append(_num(row.get(nc)) if row else None)
            name = dv if len(num_cols) == 1 else f"{dv}·{nc}"
            series.append({"name": name, "values": vals})
    return _single(card_type="table", labels=x_values, series=series)


def _labels_nodate(rows: list[Any], dim_cols: list[str]) -> list[str]:
    if dim_cols:
        return [str(r.get(dim_cols[0])) for r in rows if isinstance(r, dict)]
    return [str(i) for i in range(len(rows))]


def _raw_table(rows: list[Any], columns: list[str]) -> dict[str, Any]:
    """无数值列兜底：原始 rows 表格（card.table 附加字段，前端直接渲染）。"""
    return {
        "layout": "single",
        "cards": [{
            "card_type": "table",
            "title": "",
            "table": {"columns": list(columns), "rows": rows},
        }],
    }


def _unique(*items: str) -> list[str]:
    seen: list[str] = []
    for it in items:
        if it not in seen:
            seen.append(it)
    return seen
