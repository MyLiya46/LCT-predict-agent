from __future__ import annotations

from collections import defaultdict
from typing import Any

from sqlalchemy import select

from app.models import AttributionAnalysisRow
from app.services.forecast_model_client import normalize_category
from app.tools.internal._capability import call_hook, context_session, need_input, number, tool_error


async def handle(input_data: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
    missing = [key for key in ("system_forecast_number", "category", "sku", "period") if input_data.get(key) in (None, "")]
    if missing:
        return need_input(*missing)
    payload = await call_hook(context, "get_attribution", input_data)
    if payload is None:
        session = context_session(context)
        if session is None:
            return tool_error("缺少 PG session，无法查询归因结果")
        clauses = [
            AttributionAnalysisRow.version == str(input_data["system_forecast_number"]),
            AttributionAnalysisRow.category == normalize_category(input_data["category"]),
            AttributionAnalysisRow.sku == str(input_data["sku"]),
        ]
        period = str(input_data["period"]).strip()
        if period.upper().startswith("N+"):
            clauses.append(AttributionAnalysisRow.horizon == period)
        else:
            clauses.append(AttributionAnalysisRow.period == period[:7])
        result = await session.execute(select(AttributionAnalysisRow).where(*clauses).order_by(AttributionAnalysisRow.id))
        source_rows = list(result.scalars().all())
        if not source_rows:
            return tool_error("未找到匹配的归因结果")
        impacts: dict[str, float] = defaultdict(float)
        for row in source_rows:
            name = str(row.attr_type or (row.payload or {}).get("影响因子") or "其他")
            impacts[name] += number(row.impact)
        factors = [
            {"name": name, "impact": round(value, 1), "direction": "正向" if value >= 0 else "负向"}
            for name, value in sorted(impacts.items(), key=lambda item: abs(item[1]), reverse=True)
        ]
        table = {
            "columns": [
                {"key": "name", "title": "因子"},
                {"key": "impact", "title": "影响量", "align": "right"},
                {"key": "direction", "title": "方向"},
            ],
            "rows": factors,
        }
        payload = {
            "response_type": "attribution",
            "factors": factors,
            "rows": factors,
            "envelope": {
                "text": {"title": "预测归因分析", "markdown": f"型号 **{input_data['sku']}** 的主要预测影响因子已整理如下。"},
                "table": table,
            },
        }
        return payload
    return {"response_type": "attribution", "factors": payload.get("factors", payload.get("rows", [])), "envelope": payload}
