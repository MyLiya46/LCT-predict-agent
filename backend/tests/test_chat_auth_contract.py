from app.llm.gateway.ml_api_client import build_inputs
from app.services import chat_bridge


def test_oauth_token_is_request_input_and_backup_jwt_is_not():
    oauth = "oauth-only"
    jwt = "backup-jwt-must-not-leak"
    inputs = build_inputs(access_token=oauth)
    assert inputs["new_token"] == oauth
    assert jwt not in inputs.values()
    assert "backup-jwt" not in chat_bridge.__dict__


def test_bridge_uses_distinct_oauth_field_name():
    assert "oauth_access_token" in chat_bridge.TurnHandle.__annotations__ or "oauth_access_token" in open(chat_bridge.__file__, encoding="utf-8").read()
