"""演示数据：注册销售数据源 + 绑定 query_sales_data/predict_sales 工具到默认场景。

用法：uv run python -X utf8 tests/setup_tools_demo.py
前提：服务已启动；admin 账号可用（ADMIN_INITIAL_EMAIL/PASSWORD 种子）。
"""
from __future__ import annotations

import httpx

BASE = "http://127.0.0.1:8000"


def main() -> None:
    c = httpx.Client(base_url=BASE, trust_env=False, timeout=15)
    # admin 登录
    r = c.post("/api/v1/auth/login", json={"email": "admin@corp.com", "password": "LctDevAdmin_2026!"})
    assert r.status_code == 200, r.text
    tok = r.json()["data"]["access_token"]
    h = {"Authorization": f"Bearer {tok}"}

    # 默认场景 id
    scens = c.get("/api/v1/admin/scenarios", headers=h).json()["data"]
    def_scn = next((s for s in scens if s["code"] == "sales_query_predict"), None)
    assert def_scn, "默认场景未找到"
    scn_id = def_scn["id"]
    print("scenario:", scn_id, def_scn["name"])

    # 数据源（mock sales-data，白名单 10.0.0.0/8 内）
    ds_list = c.get("/api/v1/admin/datasources", headers=h).json()["data"]
    if not any(d["name"] == "sales-data" for d in ds_list):
        r = c.post(
            "/api/v1/admin/datasources", headers=h,
            json={
                "name": "sales-data", "type": "http_api",
                "base_url": "http://10.0.0.1:8000/api/v1",
                "credential": "mock_sales_token", "whitelist": ["10.0.0.0/8"],
            },
        )
        print("datasource create:", r.status_code, r.json().get("code"))
    else:
        print("datasource exists")

    # 工具（idempotent：已存在则跳过）
    tools = c.get("/api/v1/admin/tools", headers=h).json()["data"]
    tool_by_name = {t["name"]: t for t in tools}
    for tool_name, descr, inp, outp, handler, image in [
        (
            "query_sales_data", "查询历史销售数据（支持 region/product/channel 维度）",
            {
                "type": "object",
                "properties": {
                    "dimensions": {"type": "array", "items": {"type": "string"}},
                    "time_range": {"type": "object", "properties": {"start": {"type": "string"}, "end": {"type": "string"}}},
                    "filters": {"type": "object", "additionalProperties": True},
                },
                "required": ["dimensions", "time_range"],
            },
            {"type": "object", "properties": {"rows": {"type": "array"}, "columns": {"type": "array"}, "query_time": {"type": "string"}}},
            "query_sales_data",
            "registry/agent-tools/query-sales-data:v1",
        ),
        (
            "predict_sales", "销售预测（基于历史数据发起预测）",
            {
                "type": "object",
                "properties": {
                    "model": {"type": "string"}, "horizon": {"type": "integer"},
                    "base": {"type": "object"},
                },
                "required": ["horizon"],
            },
            {"type": "object", "properties": {"forecast": {"type": "array"}, "meta": {"type": "object"}}},
            "predict_sales",
            "registry/agent-tools/predict-sales:v1",
        ),
    ]:
        if tool_name in tool_by_name:
            print("tool exists:", tool_name)
            continue
        r = c.post(
            "/api/v1/admin/tools", headers=h,
            json={
                "name": tool_name,
                "description": descr,
                "input_schema": inp,
                "output_schema": outp,
                "execution": {
                    "kind": "sandbox", "image": image, "handler": handler,
                    "timeout_s": 30, "warm_pool": 1, "env_from_datasource": ["sales-data"],
                },
                "scenario_id": scn_id,
            },
        )
        print("tool create:", tool_name, r.status_code, r.json().get("code"), r.json().get("message"))
        if r.json().get("code") != "0":
            print("  ->", r.text[:200])

    # T43：render_dashboard 内置工具（internal 执行，进程内，不进容器）
    if "render_dashboard" not in tool_by_name:
        r = c.post(
            "/api/v1/admin/tools", headers=h,
            json={
                "name": "render_dashboard",
                "description": "销售数据看板渲染（折线/柱状/表格，AI 据上下文生成图表 spec）",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "layout": {"type": "string", "enum": ["single", "grid"]},
                        "cards": {"type": "array"},
                    },
                    "required": ["cards"],
                },
                "output_schema": {"type": "object", "properties": {"layout": {"type": "string"}, "cards": {"type": "array"}}},
                "execution": {"kind": "internal", "handler": "render_dashboard", "timeout_s": 5},
                "scenario_id": scn_id,
            },
        )
        print("tool create: render_dashboard", r.status_code, r.json().get("code"), r.json().get("message"))
        if r.json().get("code") != "0":
            print("  ->", r.text[:200])
    else:
        print("tool exists: render_dashboard")

    print("=== SETUP TOOLS DONE ===")


if __name__ == "__main__":
    main()
