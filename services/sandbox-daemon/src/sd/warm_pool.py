"""预热池（T11 / tech_design T2 与 §3.7）。

每个 enabled 工具镜像保留 warm 实例；spawn 后空闲 60s 复用。
预热 = 拉取镜像（容器预热实例由 runner 的 warm_pool 调度）。
"""
from __future__ import annotations

import logging
import time
from typing import Optional

logger = logging.getLogger("sd.warm")

_LAST_WARM: dict[str, float] = {}
WARM_TTL_S = 60.0


def warm_image(image: str) -> tuple[bool, str]:
    """预热单个镜像（幂等，TTL 内不重复）。"""
    now = time.monotonic()
    last = _LAST_WARM.get(image)
    if last and now - last < WARM_TTL_S:
        return True, "already warm"
    ok = _try_pull(image)
    _LAST_WARM[image] = now
    return ok, "pulled" if ok else "pull-failed"


def _try_pull(image: str) -> bool:
    try:
        import docker

        client = docker.from_env()
        client.images.pull(image)
        return True
    except Exception:  # noqa: BLE001
        return False


def recycled(image: str) -> bool:
    """判断 warm 实例是否可复用。"""
    return True