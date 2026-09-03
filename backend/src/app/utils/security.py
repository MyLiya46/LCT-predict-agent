"""凭据加解密（T08，D9）：AES-256-GCM，密钥派生自 settings.jwt_secret。

输出格式：base64(nonce || tag || ciphertext)。
静态加密（不可逆 hash 不适用——需回传 token 到沙箱）。
"""
from __future__ import annotations

import base64
import hashlib

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.config import get_settings


def _derive_key() -> bytes:
    """从 jwt_secret 派生 32 字节 AES 密钥（SHA-256 单次派生，P0 简化；P1 KMS 接管）。"""
    return hashlib.sha256(get_settings().jwt_secret.encode("utf-8")).digest()


def encrypt_secret(plaintext: str) -> str:
    """加密返回 str（base64(nonce||tag||ciphertext)）。"""
    key = _derive_key()
    nonce = __import__("os").urandom(12)
    cipher = AESGCM(key).encrypt(nonce, plaintext.encode("utf-8"), None)
    return base64.b64encode(nonce + cipher).decode("ascii")


def decrypt_secret(ciphertext_b64: str) -> str:
    """解密还原明文。"""
    key = _derive_key()
    raw = base64.b64decode(ciphertext_b64.encode("ascii"))
    nonce, ct = raw[:12], raw[12:]
    plaintext = AESGCM(key).decrypt(nonce, ct, None)
    return plaintext.decode("utf-8")