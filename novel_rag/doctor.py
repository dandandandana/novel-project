"""Installation-time capability checks for :mod:`novel_rag`.

The graph projection requires SQLite FTS5 with the trigram tokenizer.  This
module deliberately probes an in-memory database only: it never installs,
replaces, upgrades, or downgrades the SQLite runtime.  A failed probe is an
installation diagnostic, rather than a reason to silently switch to a weaker
tokenizer.
"""

from __future__ import annotations

import platform
import sqlite3
from dataclasses import dataclass
from typing import Any

from .graph.schema import probe_trigram


@dataclass(frozen=True)
class DoctorReport:
    """The stable, serialisable result of the installation preflight."""

    python_version: str
    sqlite_version: str
    fts5: bool
    trigram: bool
    diagnostics: tuple[str, ...] = ()
    compile_options: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        """Whether all SQLite capabilities required by the graph are present."""

        return self.fts5 and self.trigram

    @property
    def success(self) -> bool:
        """Alias useful to callers that model a preflight as a success flag."""

        return self.ok

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible report for CLI and integration callers."""

        return {
            "ok": self.ok,
            "status": "ok" if self.ok else "error",
            "message": "安装预检通过" if self.ok else "安装预检未通过",
            "python_version": self.python_version,
            "sqlite_version": self.sqlite_version,
            "capabilities": {
                "fts5": self.fts5,
                "trigram": self.trigram,
            },
            # Keep the flat fields as well as the grouped fields so scripts
            # can consume the report without depending on a nested shape.
            "fts5": self.fts5,
            "trigram": self.trigram,
            "compile_options": list(self.compile_options),
            "diagnostics": list(self.diagnostics),
        }

    def to_dict(self) -> dict[str, Any]:
        """Compatibility spelling for callers that use ``to_dict``."""

        return self.as_dict()


def _probe_fts5() -> bool:
    """Probe creation of a real FTS5 virtual table in memory."""

    connection = sqlite3.connect(":memory:")
    try:
        connection.execute(
            "CREATE VIRTUAL TABLE __novel_rag_doctor_fts5 USING fts5(content)"
        )
        return True
    finally:
        connection.close()


def _probe_compile_options() -> tuple[str, ...]:
    """Read optional SQLite compile flags for human diagnostics."""

    connection = sqlite3.connect(":memory:")
    try:
        rows = connection.execute("PRAGMA compile_options").fetchall()
    finally:
        connection.close()
    return tuple(sorted(str(row[0]) for row in rows if row and row[0]))


def _probe_trigram() -> bool:
    """Probe an actual CJK trigram match, not just the SQLite version."""

    return bool(probe_trigram())


def run_doctor() -> DoctorReport:
    """Run the local installation preflight without changing system state."""

    diagnostics: list[str] = []
    python_version = platform.python_version()
    sqlite_version = sqlite3.sqlite_version

    try:
        fts5 = _probe_fts5()
    except Exception as exc:  # a diagnostic command must explain probe errors
        fts5 = False
        diagnostics.append(
            "SQLite FTS5 probe 失败："
            f"{type(exc).__name__}: {exc}. 请在安装阶段提供启用 FTS5 的 SQLite。"
        )

    if not fts5 and not diagnostics:
        diagnostics.append(
            "当前 SQLite 未启用 FTS5；请在安装阶段提供启用 FTS5 的 SQLite。"
        )

    trigram = False
    if fts5:
        try:
            trigram = _probe_trigram()
        except Exception as exc:  # see the FTS5 note above
            diagnostics.append(
                "SQLite FTS5 trigram probe 失败："
                f"{type(exc).__name__}: {exc}. 请在安装阶段提供支持 trigram 的 SQLite。"
            )
        if not trigram and not diagnostics:
            diagnostics.append(
                "当前 SQLite 的 FTS5 不支持可用的 trigram tokenizer；"
                "请在安装阶段提供支持 trigram 的 SQLite。"
            )
    else:
        diagnostics.append("由于 FTS5 不可用，未执行 trigram 检查。")

    try:
        compile_options = _probe_compile_options()
    except Exception:
        # Compile flags are helpful context, but they are not a second
        # capability gate and should not hide the primary FTS diagnosis.
        compile_options = ()

    return DoctorReport(
        python_version=python_version,
        sqlite_version=sqlite_version,
        fts5=bool(fts5),
        trigram=bool(trigram),
        diagnostics=tuple(diagnostics),
        compile_options=compile_options,
    )


def doctor() -> DoctorReport:
    """Short alias for applications embedding the CLI preflight."""

    return run_doctor()


__all__ = ["DoctorReport", "doctor", "run_doctor"]
