"""工具链路完整验收（P0-B5/B6 引擎级）：发送中文查询 → 引擎工具调用 → 追溯链完整。"""
from __future__ import annotations

import time

import httpx

BASE = "http://127.0.0.1:8000"


def main() -> None:
    c = httpx.Client(base_url=BASE, trust_env=False, timeout=15)
    # 幂等：已存在则 409，继续登录
    c.post("/api/v1/auth/register", json={"email": "smoke@corp.com", "password": "Smoke12345", "nickname": "冒烟用户"})
    r = c.post("/api/v1/auth/login", json={"email": "smoke@corp.com", "password": "Smoke12345"})
    assert r.json().get("code") == "0", r.text
    tok = r.json()["data"]["access_token"]
    h = {"Authorization": f"Bearer {tok}"}

    conv = c.post("/api/v1/chat/conversations", headers=h, json={"title": "工具链路验收"}).json()["data"]["id"]
    content = "查询华东区最近 6 月销量"
    r = c.post(f"/api/v1/chat/conversations/{conv}/messages", headers=h, json={"content": content})
    assert r.json()["code"] == "0", r.text
    mid = r.json()["data"]["message_id"]
    print("sent:", content, "-> mid:", mid)

    # 轮询最终状态
    final = None
    for _ in range(20):
        time.sleep(2)
        msgs = c.get(f"/api/v1/chat/conversations/{conv}/messages", headers=h).json()["data"]["items"]
        am = [m for m in msgs if m["role"] == "assistant" and m["id"] == mid]
        if am and am[0]["status"] in ("completed", "failed", "interrupted"):
            final = am[0]
            break
    assert final, "引擎 40s 未完成"
    print("assistant final:", final["status"])

    # 追溯链断言
    trace = c.get(f"/api/v1/chat/conversations/{conv}/messages/{mid}/trace", headers=h).json()["data"]
    evt_types = [e["type"] for e in trace["events"]]
    joined = "->".join(evt_types)
    print("event chain:", joined)
    # 断言工具调用被触发（对内网 daemon 不可达环境，tool_call 必然出现 + tool_error(SANDBOX)→ 继续 planning/done）
    assert "tool_call" in evt_types, "未触发工具调用"
    assert evt_types[-1] in ("done", "agent_process"), "缺少结束事件"
    print("tool_call input:", next(e["payload"].get("input") for e in trace["events"] if e["type"] == "tool_call"))
    print("tool_error:", [e["payload"] for e in trace["events"] if e["type"] == "tool_error"])

    # 导出
    md = c.get(f"/api/v1/chat/conversations/{conv}/messages/{mid}/trace/export", headers=h)
    print("export ok:", "追溯" in md.text or "message" in md.text)

    print("=== TOOL CHAIN VERIFY PASS ===")


if __name__ == "__main__":
    main()