from app.main import app


def test_probe_routes_match_frontend_declarations_and_are_safe():
    paths = app.openapi()["paths"]
    assert "/api/agent/probe/template" in paths
    assert "get" in paths["/api/agent/probe/template"]
    assert "/api/agent/probe" in paths
    assert "post" in paths["/api/agent/probe"]
    assert "/api/chat" in paths
    assert "/api/chat/stream" in paths
    for path in ("/api/agent/probe", "/api/agent/probe/template"):
        assert "AGENT_API_KEY" not in str(paths[path])
        assert "oauth_access_token" not in str(paths[path])
