"""数据源服务（T08）：创建/校验/加密/测试/prepare_env。"""
from __future__ import annotations

import ipaddress
import re
from typing import Any, Optional

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.config_service import get_sys_config
from app.models import DataSource
from app.utils.errors import ConflictError, NotFoundError, ValidationError
from app.utils.security import decrypt_secret, encrypt_secret


def validate_whitelist(declared: list[str], allowed: list[str], allowed_domains: Optional[list[str]] = None) -> None:
    """出网白名单声明校验：必须在沙箱允许集中（tech_design §3.6 / T08）。

    声明项可为 CIDR，也可是域名后缀；域名必须匹配 allowed 中的域名后缀或解析后落在 CIDR。
    """
    allowed_domains = allowed_domains or []
    for item in declared:
        item = item.strip()
        if not item:
            continue
        # 兼容 host:port 形式（如 10.0.0.1:8000 / sales.internal:443）
        host = item
        if ":" in item and not item.count(":") > 1:
            host = item.split(":")[0]
        try:
            net = ipaddress.ip_network(host, strict=False)
            ok = any(net.subnet_of(ipaddress.ip_network(a, strict=False)) for a in allowed if _is_cidr(a))
        except ValueError:
            # 视为域名后缀
            ok = any(host == d or host.endswith("." + d.lstrip(".")) for d in allowed_domains)
        if not ok:
            raise ValidationError(f"出网声明 {item} 不在沙箱白名单允许集内")


def _is_cidr(text: str) -> bool:
    try:
        ipaddress.ip_network(text, strict=False)
        return True
    except ValueError:
        return False


async def _allowed_set(session: AsyncSession) -> tuple[list[str], list[str]]:
    """沙箱允许出网集（system_config.sandbox.whitelist 或 settings.whitelist_list 兜底）。"""
    settings = get_settings()
    whitelist_cfg = await get_sys_config(session, "sandbox.whitelist", None)
    if whitelist_cfg:
        raw: list[str] = whitelist_cfg if isinstance(whitelist_cfg, list) else [whitelist_cfg]
    else:
        raw = settings.whitelist_list
    cidrs = [x for x in raw if _is_cidr(x)]
    domains = [x for x in raw if not _is_cidr(x)]
    return cidrs, domains


async def create_datasource(
    session: AsyncSession,
    *,
    name: str,
    base_url: str,
    credential: str,
    whitelist: list[str],
    type: str = "http_api",
) -> DataSource:
    """注册数据源：名称唯一、credential 加密落库、白名单校验。"""
    exists = await session.execute(select(DataSource).where(DataSource.name == name))
    if exists.scalars().first() is not None:
        raise ConflictError("数据源名称已存在")
    cidrs, domains = await _allowed_set(session)
    validate_whitelist(whitelist, cidrs, domains)

    ds = DataSource(
        name=name,
        type=type,
        base_url=base_url,
        credential_encrypted=encrypt_secret(credential),
        whitelist=whitelist,
        enabled=True,
    )
    session.add(ds)
    await session.commit()
    await session.refresh(ds)
    return ds


async def get_datasource(session: AsyncSession, ds_id: str) -> DataSource:
    ds = await session.get(DataSource, ds_id)
    if ds is None:
        raise NotFoundError("数据源不存在")
    return ds


async def test_connection(session: AsyncSession, ds_id: str) -> dict:
    """连通性测试（TD-A2：api 直连数据源 /healthz/custom，超时 5s，失败不改状态）。"""
    ds = await get_datasource(session, ds_id)
    token = decrypt_secret(ds.credential_encrypted)
    url = f"{ds.base_url.rstrip('/')}/healthz/custom"
    headers = {"Authorization": f"Bearer {token}"}
    try:
        async with httpx.AsyncClient(timeout=5.0, trust_env=False) as client:
            resp = await client.get(url, headers=headers)
        if resp.status_code == 200:
            return {"ok": True, "detail": "连接成功"}
        return {"ok": False, "detail": f"连接失败: HTTP {resp.status_code}"}
    except httpx.TimeoutException:
        return {"ok": False, "detail": "连接失败: 超时(>5s)"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "detail": f"连接失败: {exc}"}


def prepare_env(ds: DataSource) -> dict[str, str]:
    """产出沙箱环境变量注入清单：DS_TOKEN_<NAME> 与 DS_BASE_URL_<NAME>（不落日志）。

    工具 handler 经 DS_TOKEN_<NAME> 取服务账号 token、DS_BASE_URL_<NAME> 取 base_url。
    """
    stem = re.sub(r"[^A-Z0-9_]", "_", ds.name.upper())
    token_key = (stem if stem.startswith("DS_TOKEN_") else "DS_TOKEN_" + stem)
    base_key = (stem if stem.startswith("DS_BASE_URL_") else "DS_BASE_URL_" + stem)
    return {
        token_key: decrypt_secret(ds.credential_encrypted),
        base_key: ds.base_url,
    }


def list_from_db(rows: list[DataSource]) -> list[dict[str, Any]]:
    """脱敏列表：credential 显示 ***。"""
    out = []
    for ds in rows:
        out.append(
            {
                "id": str(ds.id),
                "name": ds.name,
                "type": ds.type,
                "base_url": ds.base_url,
                "credential_encrypted": "***",
                "whitelist": list(ds.whitelist or []),
                "enabled": ds.enabled,
                "created_at": ds.created_at.isoformat() if ds.created_at else None,
            }
        )
    return out