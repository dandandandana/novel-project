"""Atomic temporary-build-and-promote protocol shared by graph builders.

Both the story ``GraphBuilder`` and ``SharedBuilder`` follow the same
contract: build into a sibling temporary SQLite file, run acceptance (reader
validation plus optional retrieval regression) while the staged file is still
in the target directory, then promote with a single ``os.replace``.  Any
failure keeps the previously promoted graph; a failed promotion keeps the
accepted staged file so a coordinator can retry it without rebuilding.
"""

from __future__ import annotations

import os
import sqlite3
import tempfile
from pathlib import Path
from typing import Any, Callable

from .types import GraphBuildError


def build_and_promote_atomically(
    target: Path,
    *,
    label: str,
    populate: Callable[[sqlite3.Connection], Any],
    accept: Callable[[Path], None],
) -> tuple[Any, Path]:
    """Populate a temp database, accept it, then atomically promote it.

    ``populate`` runs inside one transaction on the staged connection and
    returns the caller's payload (typically a manifest).  ``accept`` receives
    the staged path after the connection is closed and must raise on any
    rejection.  Returns ``(payload, final_path)``.
    """

    final_path = Path(target).resolve()
    final_path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{final_path.stem}.", suffix=".tmp", dir=str(final_path.parent)
    )
    os.close(fd)
    temp_path = Path(temp_name)
    promotion_started = False
    try:
        connection = sqlite3.connect(temp_path)
        try:
            with connection:
                payload = populate(connection)
        finally:
            connection.close()
        # Acceptance runs while the staged file is still in the target
        # directory, then the handle is closed before os.replace so Windows
        # readers/builders do not hold the handle.
        accept(temp_path)
        promotion_started = True
        os.replace(temp_path, final_path)
        return payload, final_path
    except Exception as exc:
        if not promotion_started and temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass
        if isinstance(exc, GraphBuildError):
            raise
        raise GraphBuildError(f"{label}构建失败: {exc}") from exc
