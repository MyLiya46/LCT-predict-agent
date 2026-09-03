"""端到端 HTTP 冒烟（Python 直接调用，保证 UTF-8）：注册→登录→建会话→发消息→追溯。

用法：uv run python tests/smoke_e2e.py [base_url]
后端需已启动（uvicorn app.main:app --port 8000）。
"""
from __future__ import annotations

import sys
import time

import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"


def main() -> None:
    c = httpx.Client(base_url=BASE, timeout=30, trust_env=False)
    # 1) 注册（幂等容错：已存在则忽略别名邮箱）
    email = "smoke@corp.com"
    r = c.post("/api/v1/auth/register", json={"email": email, "password": "Smoke12345", "nickname": "冒烟用户"})
    print("register:", r.status_code, r.json().get("code"))

    # 2) 登录
    r = c.post("/api/v1/auth/login", json={"email": email, "password": "Smoke12345"})
    assert r.status_code == 200 and r.json()["code"] == "0", r.text
    access = r.json()["data"]["access_token"]
    headers = {"Authorization": f"Bearer {access}"}
    print("login ok")

    # 3) me
    r = c.get("/api/v1/auth/me", headers=headers)
    print("me:", r.json()["data"]["email"], r.json()["data"]["roles"])

    # 4) 建会话
    r = c.post("/api/v1/chat/conversations", headers=headers, json={"title": "销售预测会话"})
    assert r.status_code == 200, r.text
    cid = r.json()["data"]["id"]
    print("conversation:", cid)

    # 5) 发消息（中文内容，触发 Agent 引擎→工具链）
    r = c.post(
        f"/api/v1/chat/conversations/{cid}/messages",
        headers={**headers, "Idempotency-Key": "smoke-k1"},
        json={"content": "查询华东区最近 6 月销量"},
    )
    print("send:", r.status_code, r.json().get("code"), r.json().get("data") or r.json().get("message"))
    if r.json().get("code") != "0":
        print("message send failed")
        return
    mid = r.json()["data"]["message_id"]
    trace_id = r.json()["data"]["trace_id"]

    # 6) 幂等重放（命中既有 user 消息，返回其 message_id，且不新建 assistant）
    r2 = c.post(
        f"/api/v1/chat/conversations/{cid}/messages",
        headers={**headers, "Idempotency-Key": "smoke-k1"},
        json={"content": "查询华东区最近 6 月销量"},
    )
    r2_data = r2.json()["data"]
    # 幂等命中返回的应是与首次 user 消息同 id（user 消息的 id 从消息列表反查）
    r_msg = c.get(f"/api/v1/chat/conversations/{cid}/messages", headers=headers)
    user_msgs = [m for m in r_msg.json()["data"]["items"] if m["role"] == "user"]
    print("idempotent replay:", r2_data.get("message_id"), "user count:", len(user_msgs))
    assert r2_data.get("idempotent") is True or len(user_msgs) == 1, "幂等未命中或重复创建 user 消息"
    assert len([m for m in user_msgs if m["content"].startswith("查询华东")]) == 1, "幂等应只产生一条 user 消息"

    # 7) 轮询消息状态（引擎后台执行）
    for _ in range(10):
        time.sleep(2)
        r = c.get(f"/api/v1/chat/conversations/{cid}/messages", headers=headers)
        items = r.json()["data"]["items"]
        assistant = [m for m in items if m["role"] == "assistant" and m["id"] == mid]
        if assistant and assistant[0]["status"] in ("completed", "failed", "interrupted"):
            print("assistant final:", assistant[0]["status"], "| content:", assistant[0]["content"][:120])
            break
    else:
        print("assistant still running after 20s")

    # 8) 追溯
    r = c.get(f"/api/v1/chat/conversations/{cid}/messages/{mid}/trace", headers=headers)
    if r.status_code == 200 and r.json().get("data"):
        evts = r.json()["data"].get("events", [])
        print("trace events:", len(evts))
        for e in evts[:6]:
            print("  ", e["seq"], e["type"], str(e["payload"])[:90])
    else:
        print("trace:", r.status_code, r.text[:200])

    # 9) 追溯导出
    r = c.get(f"/api/v1/chat/conversations/{cid}/messages/{mid}/trace/export", headers=headers)
    print("export md:", "追溯" in r.text or "Trace" in r.text)

    print("\n=== SMOKE E2E DONE ===")


if __name__ == "__main__":
    main()