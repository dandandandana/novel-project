"""Filesystem and retrieval-regression helpers for the writeback step."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from ..documents import read_yaml_mapping
from ..identity import GraphKey
from ..retrieval import ContextBundle, RetrievalRequest, Retriever
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


def _retrieval_tests(
    library_root: Path,
    index_root: Path,
    *,
    retriever: Retriever | None = None,
    regression: Callable[..., Any] | None = None,
) -> int:
    """Run retrieval cases through the application-level Retriever.

    The old helper searched an SQLite index directly.  That path is no longer
    owned by writeback; callers can inject a graph-backed ``Retriever`` or a
    legacy-compatible regression callback while migrating the CLI.
    """

    cases: list[dict[str, Any]] = []
    for path in sorted((library_root / "stories").glob("*/retrieval-tests.yaml")):
        cases.extend((read_yaml_mapping(path).get("tests") or []))
    if not cases:
        return 0
    if regression is not None:
        try:
            result = regression(library_root, index_root)
        except TypeError:
            result = regression()
        if isinstance(result, int) and not isinstance(result, bool):
            return result
        if result is False:
            raise WritebackError("检索回归失败")
        return len(cases)
    if retriever is None:
        raise WritebackError("存在检索回归用例，但未注入 Retriever")
    failures = []
    for case in cases:
        try:
            request = RetrievalRequest(
                graph_key=GraphKey(str(case["story_id"]), str(case["timeline_id"])),
                outline=str(case.get("query") or ""),
                token_budget=None,
            )
            bundle = retriever.retrieve(request)
        except Exception as exc:
            failures.append(f"{case.get('id', 'unnamed')}: {exc}")
            continue
        if not isinstance(bundle, ContextBundle):
            failures.append(f"{case.get('id', 'unnamed')}: Retriever 未返回 ContextBundle")
            continue
        results = bundle.all_evidence
        ids = {item.document_id for item in results}
        statuses = {str(item.status or "") for item in results}
        missing = set(case.get("expected_document_ids", [])) - ids
        forbidden = set(case.get("forbidden_document_ids", [])) & ids
        bad_statuses = set(case.get("forbidden_statuses", [])) & statuses
        if missing or forbidden or bad_statuses:
            failures.append(str(case.get("id", "unnamed")))
    if failures:
        raise WritebackError(f"检索回归失败: {', '.join(failures)}")
    return len(cases)
