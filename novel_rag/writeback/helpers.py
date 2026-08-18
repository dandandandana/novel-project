"""Filesystem and retrieval-regression helpers for the writeback step."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..documents import read_yaml_mapping
from ..index import search_isolated
from .types import WritebackError


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise WritebackError(f"无法读取运行时文件 {path.name}: {exc}") from exc
    if not isinstance(value, dict):
        raise WritebackError(f"运行时文件不是对象: {path.name}")
    return value


def _atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def _retrieval_tests(library_root: Path, index_root: Path) -> int:
    cases: list[dict[str, Any]] = []
    for path in sorted((library_root / "stories").glob("*/retrieval-tests.yaml")):
        cases.extend((read_yaml_mapping(path).get("tests") or []))
    failures = []
    for case in cases:
        results = search_isolated(index_root, str(case["query"]), str(case["story_id"]),
                                  str(case["timeline_id"]), document_types=case.get("document_types"), limit=20)
        ids = {item.document_id for item in results}
        statuses = {item.status for item in results}
        missing = set(case.get("expected_document_ids", [])) - ids
        forbidden = set(case.get("forbidden_document_ids", [])) & ids
        bad_statuses = set(case.get("forbidden_statuses", [])) & statuses
        if missing or forbidden or bad_statuses:
            failures.append(str(case.get("id", "unnamed")))
    if failures:
        raise WritebackError(f"检索回归失败: {', '.join(failures)}")
    return len(cases)
