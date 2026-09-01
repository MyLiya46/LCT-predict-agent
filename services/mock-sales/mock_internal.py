"""mock 内部业务服务（T12 验收用）：销售数据 API + 预测服务。

用法：uvicorn mock_internal:app --port 8001
端点：
  POST /api/v1/query    销售数据查询 → {rows, columns, meta:{query_time}}
  POST /api/v1/predict  销售预测     → {forecast:[{period,value}], meta:{model,horizon}}
  GET  /api/v1/healthz/custom 连通性检查
"""
from __future__ import annotations

from datetime import datetime

from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="mock-sales-internal")


class QueryIn(BaseModel):
    dimensions: list[str] = ["region"]
    time_range: dict = {}
    filters: dict = {}


class PredictIn(BaseModel):
    model: str = "default"
    horizon: int = 3
    data: dict = {}


ROW_COLS = ["region", "product", "amount", "month"]


@app.post("/api/v1/query")
async def query(body: QueryIn):
    region = body.filters.get("region", "华东区")
    return {
        "rows": [
            {"region": region, "product": "A", "amount": 123400, "month": "2026-02"},
            {"region": region, "product": "B", "amount": 156700, "month": "2026-03"},
            {"region": region, "product": "A", "amount": 198300, "month": "2026-04"},
            {"region": region, "product": "B", "amount": 221000, "month": "2026-05"},
            {"region": region, "product": "A", "amount": 245800, "month": "2026-06"},
            {"region": region, "product": "B", "amount": 267900, "month": "2026-07"},
        ],
        "columns": ROW_COLS,
        "meta": {"query_time": datetime.now().isoformat(timespec="seconds")},
    }


@app.post("/api/v1/predict")
async def predict(body: PredictIn):
    h = body.horizon
    base_value = 260000
    forecast = [
        {"period": f"2026-{i + 8}", "value": round(base_value * (1 + 0.05 * i))}
        for i in range(h)
    ]
    return {
        "forecast": forecast,
        "meta": {"model": body.model, "horizon": h, "unit": "元"},
    }


@app.get("/api/v1/healthz/custom")
async def healthz_custom():
    return {"ok": True, "service": "mock-sales-internal"}