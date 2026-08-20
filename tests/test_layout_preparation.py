from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from novel_rag.documents import RagDocument, validate_document
from novel_rag.migration import (
    MigrationConflictError,
    execute_migration,
    plan_legacy_migration,
)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _metadata_document(path: Path, *, timeline_id: str = "main", **extra) -> None:
    payload = {
        "metadata": {
            "document_id": path.stem,
            "story_id": "demo",
            "timeline_id": timeline_id,
            "document_type": "history",
            "title": path.stem,
            "status": "active",
            "version": "1.0",
            **extra,
        },
        "content": path.stem,
    }
    _write(path, yaml.safe_dump(payload, allow_unicode=True, sort_keys=False))


def test_summary_types_and_lifecycle_metadata_are_validated(tmp_path: Path):
    valid = RagDocument(
        tmp_path / "summary.yaml",
        {
            "document_id": "summary-1",
            "story_id": "demo",
            "timeline_id": "main",
            "document_type": "chapter-summary",
            "title": "第一章摘要",
            "status": "active",
            "version": "1.0",
            "ownership": "auto",
            "covers_documents": ["scene-1"],
            "covers_through": "chapter-1",
            "source_fingerprint": "sha256:" + "a" * 64,
            "revision": 1,
            "generated_by": "test-model",
        },
        {"summary": "内容"},
    )
    assert validate_document(valid) == []

    invalid = RagDocument(
        valid.path,
        {
            **valid.metadata,
            "ownership": "robot",
            "covers_documents": [""],
            "covers_through": "not-a-coordinate",
            "source_fingerprint": "stale",
            "revision": 0,
        },
        valid.body,
    )
    errors = validate_document(invalid)
    assert any("ownership" in error for error in errors)
    assert any("covers_documents" in error for error in errors)
    assert any("covers_through" in error for error in errors)
    assert any("source_fingerprint" in error for error in errors)
    assert any("revision" in error for error in errors)


def test_legacy_migration_plan_is_read_only_and_honors_metadata_scope(tmp_path: Path):
    story = tmp_path / "stories" / "demo"
    _metadata_document(story / "canon" / "rule.yaml")
    _metadata_document(story / "history" / "scene.yaml", timeline_id="branch-a")
    _metadata_document(
        story / "canon" / "branch-rule.yaml",
        timeline_id="branch-a",
    )
    _metadata_document(
        story / "history" / "common-history.yaml",
        timeline_id="main",
        scope="common",
    )
    _write(story / "registry" / "timelines.yaml", "timelines: []\n")
    _write(story / "retrieval-tests.yaml", "tests: []\n")
    _write(story / "author-preferences.txt", "keep at story-meta\n")

    plan = plan_legacy_migration(tmp_path)
    assert plan.is_safe
    assert not (story / "common").exists()
    destinations = {operation.destination for operation in plan.copy_operations}
    assert story / "common" / "canon" / "rule.yaml" in destinations
    assert story / "common" / "registry" / "timelines.yaml" in destinations
    assert story / "common" / "history" / "common-history.yaml" in destinations
    assert story / "timelines" / "branch-a" / "history" / "scene.yaml" in destinations
    assert story / "timelines" / "branch-a" / "canon" / "branch-rule.yaml" in destinations
    assert story / "timelines" / "main" / "retrieval-tests.yaml" in destinations
    assert any("author-preferences" in warning for warning in plan.warnings)

    dry_run = execute_migration(plan, dry_run=True)
    assert dry_run.dry_run is True
    assert not (story / "common").exists()


def test_legacy_migration_is_copy_only_repeatable_and_never_overwrites(tmp_path: Path):
    story = tmp_path / "stories" / "demo"
    source = story / "history" / "scene.yaml"
    _metadata_document(source)

    plan = plan_legacy_migration(tmp_path)
    result = execute_migration(plan, dry_run=False)
    destination = story / "timelines" / "main" / "history" / "scene.yaml"
    assert result.copied_count == 1
    assert source.is_file()
    assert destination.read_bytes() == source.read_bytes()

    repeat = plan_legacy_migration(tmp_path)
    assert repeat.is_safe
    assert repeat.operations[0].status == "unchanged"
    repeat_result = execute_migration(repeat, dry_run=False)
    assert repeat_result.copied_count == 0
    assert repeat_result.skipped_count == 1

    destination.write_text("different", encoding="utf-8")
    conflict_plan = plan_legacy_migration(tmp_path)
    assert not conflict_plan.is_safe
    with pytest.raises(MigrationConflictError):
        execute_migration(conflict_plan, dry_run=False)
    assert source.is_file()
    assert destination.read_text(encoding="utf-8") == "different"


def test_legacy_migration_rejects_metadata_boundary_conflict_before_copy(tmp_path: Path):
    source = tmp_path / "stories" / "demo" / "history" / "bad.yaml"
    _metadata_document(source, story_id="other")

    plan = plan_legacy_migration(tmp_path)
    assert not plan.is_safe
    assert plan.copy_operations == ()
    with pytest.raises(MigrationConflictError):
        execute_migration(plan, dry_run=False)
    assert source.is_file()
