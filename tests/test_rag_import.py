from pathlib import Path

import yaml

from novel_rag.documents import load_document
from novel_rag.index import SqliteIndex, search_isolated
from novel_rag.rag_import import (
    RagImportError,
    import_outline,
    import_rag_yaml,
    preview_outline,
)


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


def test_upload_text_outline_creates_valid_searchable_document(tmp_path: Path) -> None:
    library, index = make_library(tmp_path)
    source = tmp_path / "outline.txt"
    source.write_text("VAULT-ALPHA-927 必须在本章开启。", encoding="utf-8")

    result = import_outline(
        source, library_root=library, index_root=index, story_id="demo", timeline_id="main",
        title="开启保险库", volume=1, chapter=2,
    )

    document = load_document(result.path)
    assert result.status == "imported"
    assert document.metadata["document_type"] == "outline"
    assert document.body["outline"]["required_events"] == ["VAULT-ALPHA-927 必须在本章开启。"]
    matches = search_isolated(index, "VAULT", "demo", "main", document_types=["outline"])
    assert [item.document_id for item in matches] == [result.document_id]


def test_upload_valid_rag_yaml_preserves_document_and_reindexes(tmp_path: Path) -> None:
    library, index = make_library(tmp_path)
    source = tmp_path / "canon.yaml"
    source.write_text(yaml.safe_dump({
        "metadata": {
            "document_id": "canon-demo-vault-v1.0", "story_id": "demo", "timeline_id": "main",
            "document_type": "canon", "title": "保险库设定", "status": "canon", "version": "1.0",
        },
        "content": "VAULT-CANON-551 只能由持钥人开启。",
    }, allow_unicode=True, sort_keys=False), encoding="utf-8")

    result = import_rag_yaml(
        source, library_root=library, index_root=index, story_id="demo", timeline_id="main"
    )

    assert result.path.parent.name == "imported"
    assert search_isolated(index, "VAULT", "demo", "main", document_types=["canon"])


def test_upload_rejects_cross_story_metadata(tmp_path: Path) -> None:
    library, index = make_library(tmp_path)
    source = tmp_path / "wrong.yaml"
    source.write_text(yaml.safe_dump({
        "metadata": {
            "document_id": "wrong", "story_id": "other", "timeline_id": "main",
            "document_type": "canon", "title": "错误作品", "status": "canon", "version": "1.0",
        },
        "content": "不能越界",
    }, allow_unicode=True), encoding="utf-8")

    try:
        import_rag_yaml(source, library_root=library, index_root=index, story_id="demo", timeline_id="main")
    except RagImportError as exc:
        assert "不一致" in str(exc)
    else:
        raise AssertionError("cross-story upload must be rejected")


def test_outline_preview_reports_version_conflict_without_writing(tmp_path: Path) -> None:
    library, index = make_library(tmp_path)
    source = tmp_path / "outline.txt"
    source.write_text("VAULT-ALPHA-927 must open.", encoding="utf-8")
    first = import_outline(
        source, library_root=library, index_root=index, story_id="demo", timeline_id="main",
        title="Vault", volume=1, chapter=2, version="1.0",
    )

    source.write_text("VAULT-ALPHA-927 must open twice.", encoding="utf-8")
    preview = preview_outline(
        source, library_root=library, index_root=index, story_id="demo", timeline_id="main",
        title="Vault", volume=1, chapter=2, version="2.0",
    )

    assert preview.status == "conflict"
    assert preview.ready is False
    assert first.document_id in " ".join(preview.conflicts)
    assert preview.path.exists() is False


def test_versioned_upload_deprecates_previous_and_is_idempotent(tmp_path: Path) -> None:
    library, index = make_library(tmp_path)
    source = tmp_path / "outline.txt"
    source.write_text("VAULT-ALPHA-927 opens.", encoding="utf-8")
    first = import_outline(
        source, library_root=library, index_root=index, story_id="demo", timeline_id="main",
        title="Vault", volume=1, chapter=2, version="1.0",
    )
    source.write_text("VAULT-ALPHA-927 opens and locks.", encoding="utf-8")
    second = import_outline(
        source, library_root=library, index_root=index, story_id="demo", timeline_id="main",
        title="Vault", volume=1, chapter=2, version="2.0", supersedes=first.document_id,
    )

    assert second.status == "imported"
    assert yaml.safe_load(first.path.read_text(encoding="utf-8"))["metadata"]["status"] == "deprecated"
    version_map = yaml.safe_load(
        (library / "stories" / "demo" / "registry" / "version-map.yaml").read_text(encoding="utf-8")
    )
    row = next(item for item in version_map["versions"] if item["document_family"] == second.document_family)
    assert row["current"] == second.document_id
    assert first.document_id in row["supersedes"]
    assert import_outline(
        source, library_root=library, index_root=index, story_id="demo", timeline_id="main",
        title="Vault", volume=1, chapter=2, version="2.0", supersedes=first.document_id,
    ).status == "noop"


def test_upload_rolls_back_document_and_index_on_rebuild_failure(tmp_path: Path, monkeypatch) -> None:
    library, index = make_library(tmp_path)
    source = tmp_path / "canon.yaml"
    source.write_text(yaml.safe_dump({
        "metadata": {
            "document_id": "canon-demo-vault-v1.0", "story_id": "demo", "timeline_id": "main",
            "document_type": "canon", "title": "Vault", "status": "canon", "version": "1.0",
        },
        "content": "VAULT-CANON-551",
    }, allow_unicode=True, sort_keys=False), encoding="utf-8")
    import novel_rag.importers.helpers as import_helpers

    def fail_rebuild(*args, **kwargs):
        raise RuntimeError("index unavailable")

    monkeypatch.setattr(import_helpers, "rebuild_isolated_indexes", fail_rebuild)
    try:
        import_rag_yaml(source, library_root=library, index_root=index, story_id="demo", timeline_id="main")
    except RagImportError:
        pass
    else:
        raise AssertionError("failed index rebuild must abort upload")
    assert not (library / "stories" / "demo" / "canon" / "imported" / "canon-demo-vault-v1.0.yaml").exists()
    assert not (library / "stories" / "demo" / "registry" / "version-map.yaml").exists()
