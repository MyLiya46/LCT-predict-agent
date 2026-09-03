"""T20 管理端验证：admin 登录→用户 CRUD→防锁死→系统参数→审计检索留痕。"""
from __future__ import annotations

import httpx

BASE = "http://127.0.0.1:8000"


def main() -> None:
    c = httpx.Client(base_url=BASE, trust_env=False, timeout=15)

    # === 管理员登录（seed 账号） ===
    r = c.post("/api/v1/auth/login", json={"email": "admin@corp.com", "password": "LctDevAdmin_2026!"})
    assert r.json().get("code") == "0", r.text
    ah = {"Authorization": f"Bearer {r.json()['data']['access_token']}"}
    print("admin login ok")

    # === 用户管理：创建 → 列表 → 编辑（角色） ===
    import uuid

    email = f"op-{uuid.uuid4().hex[:6]}@corp.com"
    r = c.post("/api/v1/admin/users", headers=ah, json={"email": email, "initial_password": "OpPass12345", "role": "user", "nickname": "运营号"})
    assert r.json().get("code") == "0", r.text
    uid = r.json()["data"]["id"]
    print("create user ok:", uid[:8])

    r = c.get("/api/v1/admin/users", headers=ah, params={"q": email})
    assert any(u["email"] == email for u in r.json()["data"]["items"]), "用户列表未命中新用户"
    print("list/search ok")

    # === 防锁死：admin 改自身 status=disabled → 409 ===
    me = c.get("/api/v1/auth/me", headers=ah).json()["data"]
    r = c.patch(f"/api/v1/admin/users/{me['id']}", headers=ah, json={"status": "disabled"})
    assert r.status_code == 409, f"应 409 拒绝自禁用，实际 {r.status_code}"
    print("self-disable blocked ok (409)")

    # === 新用户登录验证 ===
    r = c.post("/api/v1/auth/login", json={"email": email, "password": "OpPass12345"})
    assert r.json().get("code") == "0", "新用户应能登录"
    uh = {"Authorization": f"Bearer {r.json()['data']['access_token']}"}
    print("new user login ok")

    # === user 访问 /admin/* → 403 ===
    r = c.get("/api/v1/admin/config", headers=uh)
    assert r.status_code == 403, f"user 访问 admin 应 403，实际 {r.status_code}"
    print("user->admin 403 ok")

    # === 系统参数 PATCH 生效 ===
    r = c.patch("/api/v1/admin/config", headers=ah, json={"key": "retention.conversation_days", "value": 60})
    assert r.json().get("code") == "0", r.text
    r = c.get("/api/v1/admin/config", headers=ah)
    assert r.json()["data"]["retention.conversation_days"] == 60, "系统参数 PATCH 未生效"
    print("config patch ok (60)")

    # === 审计检索留痕（audit.view） ===
    before = c.get("/api/v1/admin/audits", headers=ah).json()["data"]["items"]
    before_ids = {i["id"] for i in before}
    r = c.get("/api/v1/admin/audits", headers=ah)
    assert r.json().get("code") == "0"
    after_ids = {i["id"] for i in r.json()["data"]["items"]}
    new_view = [i for i in r.json()["data"]["items"] if i["action"] == "audit.view"]
    print("audit.view rows:", len(new_view))
    assert any(i["action"] == "audit.view" for i in new_view), "检索未写 audit.view"
    print("audit self-marking ok")

    # === 重置密码 ===
    r = c.post(f"/api/v1/admin/users/{uid}/reset-password", headers=ah, json={"new_password": "NewOpPass67890"})
    assert r.json().get("code") == "0", r.text
    r = c.post("/api/v1/auth/login", json={"email": email, "password": "NewOpPass67890"})
    assert r.json().get("code") == "0", "重置后新密码应可登录"
    print("reset password ok")

    # === 工具/数据源/LLM 列表（已注册对象） ===
    r = c.get("/api/v1/admin/datasources", headers=ah)
    assert r.json().get("code") == "0"
    ds = r.json()["data"]
    assert all("***" in str(d.get("credential_encrypted", "")) or d.get("credential_encrypted") == "***" for d in ds)
    print("datasource list masked ok (", len(ds), "ds )")

    print("\n=== ADMIN VERIFY PASS ===")


if __name__ == "__main__":
    main()
