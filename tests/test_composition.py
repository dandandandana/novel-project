from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from novel_rag.catalog import fingerprint_paths
from novel_rag.composition import build_graph_retriever, build_mutation_coordinator
from novel_rag.graph import GraphKey, GraphReadError
from novel_rag.mutations import ChangeSet, MutationResult, fingerprint_file
from novel_rag.service import load_valid_documents


def _write(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(value, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def _library(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "library"
    _write(root / "registry" / "layout.yaml", {"layout_version": "2.0"})
    _write(root / "registry" / "stories.yaml", {"stories": [{"story_id": "demo"}]})
    _write(root / "shared" / "registry" / "module-defaults.yaml", {"modules": []})
    _write(root / "shared" / "registry" / "version-map.yaml", {"versions": []})
    _write(
        root / "shared" / "rules" / "rule.yaml",
        {
            "metadata": {
                "document_id": "rule-v1.0",
                "story_id": "__shared__",
                "timeline_id": "global",
                "document_type": "rule",
                "title": "共享规则",
                "status": "active",
                "version": "1.0",
                "module_type": "ruler",
                "priority": 1,
                "enforcement": "must",
            },
            "content": "共享检索规则",
        },
    )
    common = root / "stories" / "demo" / "common" / "registry"
    _write(
        common / "timelines.yaml",
        {
            "timelines": [
                {
                    "story_id": "demo",
                    "timeline_id": "main",
                    "parent_timeline_id": None,
                    "divergence_at": None,
                    "divergence_snapshot": None,
                }
            ]
        },
    )
    _write(common / "version-map.yaml", {"versions": []})
    _write(common / "character-variants.yaml", {"character_variants": []})
    _write(common / "aliases.yaml", {"aliases": []})
    _write(root / "stories" / "demo" / "timelines" / "main" / "registry" / "module-map.yaml", {"modules": []})
    _write(
        root / "stories" / "demo" / "timelines" / "main" / "history" / "scene.yaml",
        {
            "metadata": {
                "document_id": "scene-v1.0",
                "story_id": "demo",
                "timeline_id": "main",
                "document_type": "history",
                "title": "主线事件",
                "status": "canon",
                "version": "1.0",
            },
            "content": "三叉戟在港口出现",
        },
    )
    index = root / "index"
    return root, index


def test_graph_retriever_uses_current_corpus_and_canonical_readers(tmp_path: Path) -> None:
    root, index = _library(tmp_path)
    documents, issues = load_valid_documents(root)
    assert not issues

    from novel_rag.index import rebuild_isolated_indexes
    from novel_rag.retrieval import RetrievalRequest

    rebuild_isolated_indexes(index, documents, ["demo"], library_root=root)
    with build_graph_retriever(root, GraphKey("demo", "main")) as retriever:
        bundle = retriever.retrieve(
            RetrievalRequest(graph_key=GraphKey("demo", "main"), outline="三叉戟")
        )
        assert any(item.document_id == "scene-v1.0" for item in bundle.all_evidence)

    (root / "stories" / "demo" / "timelines" / "main" / "history" / "scene.yaml").write_text(
        "changed", encoding="utf-8"
    )
    with pytest.raises(GraphReadError, match="stale|不匹配|校验"):
        build_graph_retriever(root, GraphKey("demo", "main"))


def test_mutation_composition_builds_graphs_from_real_staging(tmp_path: Path) -> None:
    root, index = _library(tmp_path)
    documents, issues = load_valid_documents(root)
    assert not issues
    from novel_rag.index import rebuild_isolated_indexes

    rebuild_isolated_indexes(index, documents, ["demo"], library_root=root)
    target = root / "stories" / "demo" / "timelines" / "main" / "history" / "new.yaml"
    text = yaml.safe_dump(
        {
            "metadata": {
                "document_id": "new-v1.0",
                "story_id": "demo",
                "timeline_id": "main",
                "document_type": "history",
                "title": "新增事件",
                "status": "canon",
                "version": "1.0",
            },
            "content": "新增事件通过 staged graph",
        },
        allow_unicode=True,
        sort_keys=False,
    )
    changes = ChangeSet(
        changes={target: text},
        affected_graph_keys=(GraphKey.shared(), GraphKey("demo", "main")),
        expected_fingerprint=fingerprint_paths(
            [path for path in root.rglob("*.yaml") if "index" not in path.parts],
            root=root,
        ),
        expected_file_fingerprints={target: fingerprint_file(target)},
        change_id="test-composition",
    )
    result = build_mutation_coordinator(root).commit(changes)
    assert isinstance(result, MutationResult)
    assert result.status == "promoted"
    assert target.is_file()
    assert (index / "shared.db").is_file()
    assert (index / "graphs" / "demo" / "main.db").is_file()


def test_mutation_composition_rejects_yaml_only_changes(tmp_path: Path) -> None:
    root, _index = _library(tmp_path)
    target = root / "registry" / "layout.yaml"
    original = target.read_text(encoding="utf-8")
    changes = ChangeSet(
        changes={target: "layout_version: '2.0'\n"},
        expected_file_fingerprints={target: fingerprint_file(target)},
        change_id="yaml-only",
    )
    result = build_mutation_coordinator(root).commit(changes)
    assert result.status == "failed"
    assert target.read_text(encoding="utf-8") == original
