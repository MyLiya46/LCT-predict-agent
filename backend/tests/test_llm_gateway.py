"""T08 gateway, parser, and optional analysis acceptance tests."""

import json

import httpx
import pytest
import respx

from app.config import Settings
from app.llm.gateway.analysis_agent import enrich_envelope
from app.llm.gateway.ml_api_client import MLApiClient, build_inputs
from app.llm.gateway.response_parser import envelope_from_chat_answer


def _settings(**values):
    defaults = {
        "database_url": "postgresql+asyncpg://u:p@localhost/db",
        "jwt_secret": "x" * 40,
        "api_internal_token": "internal",
        "agent_api_url": "http://agent.test/agi/v1/chat-messages",
        "agent_api_key": "agent-secret",
        "agent_response_mode": "blocking",
        "turing_api_key": "",
    }
    defaults.update(values)
    return Settings(_env_file=None, **defaults)


@pytest.mark.asyncio
@respx.mock
async def test_gateway_blocking_payload_and_secret_boundary():
    route = respx.post("http://agent.test/agi/v1/chat-messages").mock(
        return_value=httpx.Response(200, json={"answer": "ok", "conversation_id": "c1"})
    )
    settings = _settings()
    result = await MLApiClient(settings).chat(
        "query", {"new_token": "oauth-token"}, "forecast-agent-ui", "c1", []
    )
    assert result.answer == "ok"
    assert route.calls[0].request.headers["Authorization"] == "Bearer agent-secret"
    body = json.loads(route.calls[0].request.content)
    assert body["response_mode"] == "blocking"
    assert body["conversation_id"] == "c1"
    assert body["inputs"]["new_token"] == "oauth-token"
    assert "agent-secret" not in result.answer


@pytest.mark.asyncio
@respx.mock
async def test_gateway_stream_maps_events_and_requires_answer():
    sse = "\n".join(
        [
            "data: {\"event\":\"ping\"}",
            "data: {\"event\":\"node_started\",\"data\":{\"title\":\"查询\"}}",
            "data: {\"event\":\"agent_message\",\"answer\":\"你好\"}",
            "data: {\"event\":\"message_end\"}",
            "data: [DONE]",
        ]
    )
    respx.post("http://agent.test/agi/v1/chat-messages").mock(
        return_value=httpx.Response(200, text=sse, headers={"content-type": "text/event-stream"})
    )
    events = [item async for item in MLApiClient(_settings()).stream_chat("q", {}, "u")]
    assert [item["type"] for item in events] == ["status", "status", "status", "result"]
    assert events[-1]["result"].answer == "你好"


@pytest.mark.asyncio
@respx.mock
async def test_gateway_upstream_errors_are_redacted():
    respx.post("http://agent.test/agi/v1/chat-messages").mock(
        return_value=httpx.Response(401, text="secret-upstream-body")
    )
    with pytest.raises(RuntimeError, match="HTTP 401") as error:
        await MLApiClient(_settings()).chat("q", {}, "u")
    assert "secret-upstream-body" not in str(error.value)


@pytest.mark.asyncio
@respx.mock
async def test_gateway_timeout_and_invalid_json_are_explicit():
    respx.post("http://agent.test/agi/v1/chat-messages").mock(side_effect=httpx.ReadTimeout("slow"))
    with pytest.raises(RuntimeError, match="timed out"):
        await MLApiClient(_settings()).chat("q", {}, "u")

    respx.reset()
    respx.post("http://agent.test/agi/v1/chat-messages").mock(return_value=httpx.Response(200, text="not-json"))
    with pytest.raises(RuntimeError, match="invalid JSON"):
        await MLApiClient(_settings()).chat("q", {}, "u")


def test_build_inputs_only_forwards_oauth_token(monkeypatch):
    from app.config import reset_settings

    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/db")
    monkeypatch.setenv("JWT_SECRET", "x" * 40)
    monkeypatch.setenv("API_INTERNAL_TOKEN", "internal")
    monkeypatch.setenv("AGENT_EXTRA_INPUTS_JSON", '{"jwt_token":"backend-jwt","region":"华东"}')
    reset_settings()
    inputs = build_inputs(access_token="oauth-token")
    assert inputs["new_token"] == "oauth-token"
    assert inputs["region"] == "华东"
    assert "jwt_token" not in inputs
    assert "backend-jwt" not in inputs.values()
    reset_settings()


def test_response_parser_handles_fenced_json():
    envelope = envelope_from_chat_answer(
        answer='```json\n{"summary":"结论","factors":[{"name":"价格"}]}\n```',
        intent="history",
    )
    assert envelope.intent == "attribution"
    assert envelope.text.markdown == "结论"


@pytest.mark.asyncio
async def test_analysis_fallback_and_valid_json(monkeypatch):
    from app.llm.gateway import turing

    base = envelope_from_chat_answer(answer="原始结论", intent="forecast")
    monkeypatch.setattr(turing, "turing_configured", lambda: True)
    monkeypatch.setattr(turing, "chat_completion", lambda **_: _raise())
    result = await enrich_envelope(
        user_query="q", core_answer="原始结论", intent="forecast", structured=None, base_envelope=base
    )
    assert result == base

    async def valid(**_):
        return '{"text":{"title":"分析","markdown":"增强结论\\n\\n## 联想追问\\n- 忽略"}}'

    monkeypatch.setattr(turing, "chat_completion", valid)
    monkeypatch.setattr(turing, "turing_configured", lambda: True)
    result = await enrich_envelope(
        user_query="q", core_answer="原始结论", intent="forecast", structured=None, base_envelope=base
    )
    assert result.text.markdown == "增强结论"


@pytest.mark.asyncio
async def test_analysis_missing_key_and_invalid_json_fall_back(monkeypatch):
    from types import SimpleNamespace

    import app.llm.gateway.analysis_agent as module
    from app.llm.gateway import turing

    base = envelope_from_chat_answer(answer="原始结论", intent="forecast")
    monkeypatch.setattr(module, "get_settings", lambda: SimpleNamespace(analysis_agent_enabled=True))
    monkeypatch.setattr(turing, "turing_configured", lambda: False)
    assert await enrich_envelope(
        user_query="q", core_answer="原始结论", intent="forecast", structured=None, base_envelope=base
    ) == base

    monkeypatch.setattr(turing, "turing_configured", lambda: True)

    async def invalid(**_):
        return "not-json"

    monkeypatch.setattr(turing, "chat_completion", invalid)
    assert await enrich_envelope(
        user_query="q", core_answer="原始结论", intent="forecast", structured=None, base_envelope=base
    ) == base


def _raise():
    raise RuntimeError("turing failure")
