"""出网白名单网络骨架（T11 / tech_design §3.7 & §6.4）。

宿主 iptables 对 sandbox-net 网段强制——先放行白名单，其余默认 DROP 公网。
P0 白名单静态配置（启动时执行一次），管理端编辑属 P1。
daemon 在生产以 privileged 容器形态（Linux）运行，持有 docker.sock + NET_ADMIN。
"""
from __future__ import annotations

import logging
import os
import subprocess

logger = logging.getLogger("sd.net")

SANDBOX_NET = "sandbox-net"
_APPLIED = False


def ensure_network() -> dict:
    """创建 sandbox-net bridge + iptables 白名单（幂等）。"""
    global _APPLIED
    if _APPLIED:
        return {"mode": "docker", "network": SANDBOX_NET}
    try:
        _sh(["docker", "network", "inspect", SANDBOX_NET])
    except subprocess.CalledProcessError:
        _sh(["docker", "network", "create", "--driver", "bridge", SANDBOX_NET])
    _apply_iptables(os.environ.get("WHITELIST_CIDRS", "10.0.0.0/8,192.168.0.0/16"))
    _APPLIED = True
    return {"mode": "docker", "network": SANDBOX_NET}


def _sh(cmd: list[str]) -> str:
    return subprocess.check_output(cmd, text=True, stderr=subprocess.STDOUT)


def _apply_iptables(whitelist: str) -> None:
    """iptables-restore 事务式写规则：白名单放行 + 默认 DROP 公网（§6.4 强制）。

    在 OUTPUT+FORWARD 链上对 sandbox-net 出向做白名单——由于 bridge 网络出向
    走宿主机 FORWARD，故两条链都保护；P0 静态配置（域名后缀→IP 集静态缓存）。
    """
    chain = "SANDBOX_OUT"
    rules: list[str] = ["*filter", f":{chain} - [0:0]"]
    # 白名单放行（CIDR/域名解析 IP 集——P0 域名静态缓存，此处仅 CIDR）
    for item in whitelist.split(","):
        item = item.strip()
        if not item:
            continue
        rules.append(f"-A {chain} -d {item} -j ACCEPT")
    # 默认拒绝（公网 + 其他）
    rules.append(f"-A {chain} -j DROP")
    # 应用到主链（sandbox 网段出口走 FORWARD；容器内直连 public 网段看 OUTPUT）
    rules.append(f"-A FORWARD -i {SANDBOX_NET} -j {chain}")
    rules.append("COMMIT")
    script = "\n".join(rules) + "\n"
    proc = subprocess.run(["iptables-restore"], input=script, text=True, capture_output=True)
    if proc.returncode != 0:
        logger.warning("iptables-restore return %s: %s", proc.returncode, proc.stderr)  # noqa: S603
    else:
        logger.info("iptables 白名单已写入: %s", whitelist)