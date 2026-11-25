"""单文件原子保存；不提供跨文件事务、CAS或凭证权限策略。"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Mapping
import uuid


def atomic_write_bytes(path: Path, value: bytes) -> None:
    """依赖：Path/UUID/os。输入：目标路径和bytes。输出：成功替换或原I/O异常。实现：独占同目录临时文件，flush/fsync/replace后只清理本次文件。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.write")
    owns_temporary = False
    try:
        with temporary.open("xb") as handle:
            owns_temporary = True
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if owns_temporary:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass


def atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    """依赖：json/atomic_write_bytes。输入：路径和映射。输出：UTF-8文件或原异常。实现：保持既有Unicode/排序/两空格缩进/default=str/末尾换行字节。"""
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2, default=str)
    atomic_write_bytes(path, f"{encoded}\n".encode("utf-8"))
