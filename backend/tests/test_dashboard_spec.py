"""确定性看板 spec 生成单测（【变更自 T43】零 LLM、复用工具数据）。

覆盖 build_dashboard_spec 的映射规则：
- predict_sales：forecast → 折线（labels=period、series 单「预测值」）；
- query_sales_data：日期列+数值列+无变化维度 → 折线；
  有变化维度 → 透视表格（gap 置 None）；无数值列 → 原始 rows 兜底表；
  空数据 → None；
- 非 dashboard 工具名 / 非 dict 输出 → None。
"""


from app.tools.dashboard_spec import build_dashboard_spec


# ------------------------------------------------------------------
# predict_sales
# ------------------------------------------------------------------
def test_predict_forecast_line():
    output = {
        "forecast": [
            {"period": "2026-08", "value": 260000},
            {"period": "2026-09", "value": 273000},
            {"period": "2026-10", "value": 286650},
        ],
        "meta": {"model": "default", "horizon": 3, "unit": "元"},
    }
    spec = build_dashboard_spec("predict_sales", output)
    assert spec is not None
    assert spec["layout"] == "single"
    card = spec["cards"][0]
    assert card["card_type"] == "line"
    assert card["data"]["labels"] == ["2026-08", "2026-09", "2026-10"]
    assert card["data"]["series"][0]["name"] == "预测值"
    assert card["data"]["series"][0]["values"] == [260000, 273000, 286650]
    assert "未来 3 期" in card.get("description", "")


def test_predict_empty_forecast_none():
    assert build_dashboard_spec("predict_sales", {"forecast": [], "meta": {}}) is None
    assert build_dashboard_spec("predict_sales", {"meta": {}}) is None


# ------------------------------------------------------------------
# query_sales_data
# ------------------------------------------------------------------
QUERY_ROWS = [
    {"region": "华东", "product": "A", "amount": 123400, "month": "2026-02"},
    {"region": "华东", "product": "B", "amount": 156700, "month": "2026-03"},
    {"region": "华东", "product": "A", "amount": 198300, "month": "2026-04"},
    {"region": "华东", "product": "B", "amount": 221000, "month": "2026-05"},
]


def test_query_time_series_line():
    output = {"rows": QUERY_ROWS, "columns": ["region", "product", "amount", "month"], "query_time": ""}
    spec = build_dashboard_spec("query_sales_data", output)
    assert spec is not None
    card = spec["cards"][0]
    # 有日期列 month、有变化维度 product → 透视表（非 line）
    assert card["card_type"] == "table"
    # labels = 去重后的 month 序列
    assert card["data"]["labels"] == ["2026-02", "2026-03", "2026-04", "2026-05"]
    # series 名 = product 值（单数值列）
    names = [s["name"] for s in card["data"]["series"]]
    assert names == ["A", "B"]
    # gap 置 None（A 无 2026-03、2026-05）
    a_series = next(s for s in card["data"]["series"] if s["name"] == "A")
    assert a_series["values"][1] is None
    assert a_series["values"][0] == 123400


def test_query_no_dim_series_line():
    # 无变化维度（去除 product）→ 折线
    rows = [
        {"month": "2026-02", "amount": 100},
        {"month": "2026-03", "amount": 120},
        {"month": "2026-04", "amount": 90},
    ]
    spec = build_dashboard_spec("query_sales_data", {"rows": rows, "columns": ["month", "amount"]})
    card = spec["cards"][0]
    assert card["card_type"] == "line"
    assert card["data"]["labels"] == ["2026-02", "2026-03", "2026-04"]
    assert card["data"]["series"][0]["values"] == [100, 120, 90]


def test_query_no_date_bar():
    rows = [
        {"region": "华东", "amount": 1000},
        {"region": "华南", "amount": 800},
    ]
    spec = build_dashboard_spec("query_sales_data", {"rows": rows, "columns": ["region", "amount"]})
    card = spec["cards"][0]
    # 无日期列、少行、无变化维度 → 柱状
    assert card["card_type"] == "bar"
    assert card["data"]["labels"] == ["华东", "华南"]


def test_query_no_numeric_raw_table():
    rows = [{"name": "a", "desc": "x"}, {"name": "b", "desc": "y"}]
    spec = build_dashboard_spec("query_sales_data", {"rows": rows, "columns": ["name", "desc"]})
    card = spec["cards"][0]
    assert card["card_type"] == "table"
    # 兜底走 card.table（原始 rows 直挂）
    assert card.get("table") is not None
    assert card["table"]["columns"] == ["name", "desc"]
    assert len(card["table"]["rows"]) == 2


def test_query_empty_rows_none():
    assert build_dashboard_spec("query_sales_data", {"rows": [], "columns": []}) is None
    assert build_dashboard_spec("query_sales_data", {"rows": None}) is None


# ------------------------------------------------------------------
# 非 dashboard 工具 / 非 dict
# ------------------------------------------------------------------
def test_non_dashboard_tool_none():
    assert build_dashboard_spec("some_other_tool", {"rows": [1]}) is None


def test_non_dict_output_none():
    assert build_dashboard_spec("query_sales_data", [1, 2, 3]) is None
    assert build_dashboard_spec("predict_sales", "not-a-dict") is None
