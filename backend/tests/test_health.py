"""T08 local agent health endpoint tests."""

import pytest

from app.api.health import agent_health
from app.config import reset_settings


@pytest.mark.asyncio
async def test_agent_health_without_key_is_disabled(monkeypatch):
    monkeypatch.delenv("AGENT_API_KEY", raising=False)
    reset_settings()
    response = await agent_health()
    assert response["ok"] is False
    assert response["mode"] == "disabled"
    assert response["configured_mode"] == "blocking"
    assert "AGENT_API_KEY" in response["error"]
    assert "token" not in json_text(response).lower()


def json_text(value):
    import json

    return json.dumps(value)
