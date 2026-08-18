from pathlib import Path

import yaml

from novel_rag.feedback import create_feedback, list_feedback, resolve_feedback
from novel_rag.index import SqliteIndex


def make_library(tmp_path: Path) -> tuple[Path, Path]:
    library = tmp_path / "novel-rag"
    story = library / "stories" / "demo"
    (library / "registry").mkdir(parents=True)
    (library / "registry" / "layout.yaml").write_text(
        yaml.safe_dump({"layout_version": "2.0"}), encoding="utf-8"
    )
    (library / "registry" / "stories.yaml").write_text(
        yaml.safe_dump({"stories": [{"story_id": "demo"}]}), encoding="utf-8"
    )
    (story / "registry").mkdir(parents=True)
    (story / "registry" / "timelines.yaml").write_text(
        yaml.safe_dump({"timelines": [{"story_id": "demo", "timeline_id": "main"}]}), encoding="utf-8"
    )
    index = library / "index"
    SqliteIndex(index / "stories" / "demo.db").rebuild([])
    SqliteIndex(index / "shared.db").rebuild([])
    return library, index


def test_feedback_create_list_and_resolve_are_versioned(tmp_path: Path) -> None:
    library, index = make_library(tmp_path)
    created = create_feedback(
        library_root=library, index_root=index, story_id="demo", timeline_id="main",
        target_type="runtime", target_id="run-1", runtime_id="run-1",
        issue="角色状态未同步", user_comment="请修正", version="1.0",
    )
    assert created.status == "imported"
    assert list_feedback(
        library_root=library, index_root=index, story_id="demo", timeline_id="main", status="active"
    )[0].document_id == created.document_id

    resolved = resolve_feedback(
        library_root=library, index_root=index, story_id="demo", timeline_id="main",
        feedback_id=created.document_id, resolution="已在事件提交阶段同步", version="2.0",
        supersedes=created.document_id,
    )
    assert resolved.status == "resolved"
    assert resolved.resolved_at
    again = resolve_feedback(
        library_root=library, index_root=index, story_id="demo", timeline_id="main",
        feedback_id=created.document_id, resolution="已在事件提交阶段同步", version="2.0",
        supersedes=created.document_id,
    )
    assert again.status == "noop"
    assert again.resolved_at == resolved.resolved_at
    assert list_feedback(
        library_root=library, index_root=index, story_id="demo", timeline_id="main", status="active"
    ) == []
    current = list_feedback(
        library_root=library, index_root=index, story_id="demo", timeline_id="main", status="resolved"
    )
    assert [item.document_id for item in current] == [resolved.document_id]
    assert current[0].resolved_at == resolved.resolved_at

    version_map = yaml.safe_load(
        (library / "stories" / "demo" / "registry" / "version-map.yaml").read_text(encoding="utf-8")
    )
    row = next(item for item in version_map["versions"] if item["document_family"] == created.document_family)
    assert row["current"] == resolved.document_id
    assert created.document_id in row["supersedes"]


def test_feedback_rejects_unbound_history_and_state_versions(tmp_path: Path) -> None:
    library, index = make_library(tmp_path)
    try:
        create_feedback(
            library_root=library, index_root=index, story_id="demo", timeline_id="main",
            target_type="runtime", target_id="run-1", issue="bad", history_id="missing",
        )
    except Exception as exc:
        assert "history" in str(exc)
    else:
        raise AssertionError("feedback must reject an unknown history binding")
