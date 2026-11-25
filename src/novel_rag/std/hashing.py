"""字节指纹；缺失文件、来源身份与有效性由调用者决定。"""
from __future__ import annotations

import hashlib


def fingerprint_bytes(value: bytes) -> str:
    """依赖：hashlib。输入：原始bytes。输出：带sha256前缀的指纹。实现：保持原字节域和十六进制编码。"""
    return f"sha256:{hashlib.sha256(value).hexdigest()}"
