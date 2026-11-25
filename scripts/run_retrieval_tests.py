from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]

from novel_rag.index import search_isolated


LIBRARY = ROOT / "novel-rag"
INDEX = LIBRARY / "index"


def main() -> None:
    tests = []
    for cases_path in sorted((LIBRARY / "stories").glob("*/retrieval-tests.yaml")):
        cases = yaml.safe_load(cases_path.read_text(encoding="utf-8")) or {}
        tests.extend(cases.get("tests", []))
    if not tests:
        raise AssertionError("没有发现任何小说检索回归用例")
    failures: list[str] = []
    for case in tests:
        results = search_isolated(
            INDEX,
            case["query"],
            case["story_id"],
            case["timeline_id"],
            document_types=case.get("document_types"),
            limit=20,
        )
        ids = {item.document_id for item in results}
        statuses = {item.status for item in results}
        missing = set(case.get("expected_document_ids", [])) - ids
        forbidden_ids = set(case.get("forbidden_document_ids", [])) & ids
        forbidden_statuses = set(case.get("forbidden_statuses", [])) & statuses
        if missing or forbidden_ids or forbidden_statuses:
            failures.append(
                f"{case['id']}: missing={sorted(missing)} "
                f"forbidden_ids={sorted(forbidden_ids)} "
                f"forbidden_statuses={sorted(forbidden_statuses)} returned={sorted(ids)}"
            )
    if failures:
        raise AssertionError("\n".join(failures))
    print(f"retrieval_cases={len(tests)} failures=0")


if __name__ == "__main__":
    main()
