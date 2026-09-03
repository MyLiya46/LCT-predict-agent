"""OA OAuth 网关客户端。"""
from __future__ import annotations

from typing import Any

import httpx

from app.config import get_settings
from app.utils.errors import ValidationError

OA_LOGIN_FAILED_MESSAGE = "OA 登录失败：OAuth 网关未通过验证"


def normalize_oa(oa: str) -> str:
    """Normalize and validate the OA identifier before any upstream call."""
    normalized = oa.strip().lower() if isinstance(oa, str) else ""
    if not normalized:
        raise ValidationError("OA 不能为空")
    if len(normalized) > 128:
        raise ValidationError("OA 最长 128 个字符")
    return normalized


async def fetch_access_token(username: str) -> dict[str, Any]:
    """Exchange an OA username for the short-lived OAuth gateway token.

    Upstream details are deliberately reduced to the three fields used by the
    login flow.  In particular, neither the client secret nor the raw response
    is ever placed in an exception or returned to callers.
    """
    username = normalize_oa(username)
    settings = get_settings()
    form = {
        "grant_type": settings.oauth_grant_type,
        "client_id": settings.oauth_client_id,
        "client_secret": settings.oauth_client_secret,
        "source_type": settings.oauth_source_type,
        "user_type": settings.oauth_user_type,
        "login_field": settings.oauth_login_field,
        "username": username,
        "device_id": settings.oauth_device_id,
    }
    url = f"{settings.oauth_base_url.rstrip('/')}/{settings.oauth_token_path.lstrip('/')}"

    try:
        async with httpx.AsyncClient(timeout=10.0, trust_env=False) as client:
            response = await client.post(url, files=form)
            response.raise_for_status()
            payload = response.json()
            token_payload = payload.get("data", payload) if isinstance(payload, dict) else {}
            token = token_payload.get("access_token") if isinstance(token_payload, dict) else None
            if not isinstance(token, str) or not token.strip():
                raise ValueError("missing access token")
            return {
                "access_token": token,
                "token_type": token_payload.get("token_type") or "Bearer",
                "expires_in": token_payload.get("expires_in") or 0,
            }
    except ValidationError:
        raise
    except (httpx.HTTPError, ValueError, TypeError, AttributeError, KeyError):
        raise ValidationError(OA_LOGIN_FAILED_MESSAGE) from None
