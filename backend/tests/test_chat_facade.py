from app.api.chat_facade import ChatRequest, SessionPatch


def test_facade_requests_accept_frontend_shapes():
    body = ChatRequest(
        message="查询冰箱历史销量",
        session_id=None,
        params={"category": "冰箱"},
        oa="user@example.com",
        access_token="oauth-token",
    )
    assert body.message.startswith("查询")
    assert body.params["category"] == "冰箱"


def test_session_patch_requires_a_change():
    assert SessionPatch(title="新标题").title == "新标题"
    assert SessionPatch(pinned=True).pinned is True
