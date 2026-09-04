"""T08 local agent health endpoint tests."""

from types import SimpleNamespace

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


@pytest.mark.asyncio
async def test_agent_health_reports_pg_provider_when_gateway_key_is_missing(monkeypatch):
    import app.api.health as health_module
    import app.llm.service as llm_service

    class Factory:
        def __call__(self):
            return self

        async def __aenter__(self):
            return object()

        async def __aexit__(self, *_args):
            return False

    monkeypatch.delenv("AGENT_API_KEY", raising=False)
    monkeypatch.setattr(health_module, "get_session_factory", lambda: Factory())
    monkeypatch.setattr(
        llm_service,
        "get_default_provider",
        lambda _session: _healthy_provider(),
    )
    reset_settings()
    response = await health_module.agent_health()
    assert response == {
        "ok": True,
        "mode": "provider",
        "configured_mode": "blocking",
        "url": "https://provider.test/v1",
        "provider": "llm-provider",
    }


async def _healthy_provider():
    return SimpleNamespace(status="healthy", base_url="https://provider.test/v1")


def json_text(value):
    import json

    return json.dumps(value)
