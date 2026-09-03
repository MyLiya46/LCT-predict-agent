"""T08 数据源单测：AES-256-GCM 加解密、白名单校验、连通性测试（respx mock）。"""

import pytest
import respx
import httpx

from app.datasource.service import create_datasource, decrypt_secret, encrypt_secret, validate_whitelist
from app.utils.errors import ValidationError


def test_aes_roundtrip_and_no_plaintext():
    token = "super-secret-token-12345"
    enc = encrypt_secret(token)
    assert enc != token
    assert token not in enc, "密文不应含明文"
    assert decrypt_secret(enc) == token


def test_whitelist_validation():
    allowed = ["10.0.0.0/8", "192.168.0.0/16"]
    domains = ["corp.com"]
    # 合规
    validate_whitelist(["10.0.1.5", "10.0.0.0/8"], allowed, domains)
    validate_whitelist(["sales.corp.com"], allowed, domains)
    # 越界（公网 / 未知域名）
    with pytest.raises(ValidationError):
        validate_whitelist(["8.8.8.8"], allowed, domains)
    with pytest.raises(ValidationError):
        validate_whitelist(["evil.example.org"], allowed, domains)
    # host:port 形式
    validate_whitelist(["10.0.0.1:8000"], allowed, domains)


@pytest.mark.asyncio
@respx.mock
async def test_connection_test(db_session_factory):
    respx.get("http://internal.test:8000/api/v1/healthz/custom").mock(return_value=httpx.Response(200, json={"ok": True}))

    factory = db_session_factory
    async with factory() as s:
        ds = await create_datasource(
            s, name="mock-ds", base_url="http://internal.test:8000/api/v1",
            credential="tok", whitelist=["10.0.0.0/8"], type="http_api",
        )
        result = await (
            __import__("app.datasource.service", fromlist=["test_connection"]).test_connection(s, str(ds.id))
        )
        assert result["ok"] is True


@pytest.mark.asyncio
async def test_create_datasource_encrypts(db_session_factory):
    factory = db_session_factory
    async with factory() as s:
        ds = await create_datasource(
            s, name="ds2", base_url="http://10.0.0.2", credential="my-token",
            whitelist=["10.0.0.0/8"],
        )
        assert "my-token" not in ds.credential_encrypted
        assert decrypt_secret(ds.credential_encrypted) == "my-token"