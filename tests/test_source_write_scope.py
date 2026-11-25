from pathlib import Path

import pytest

from novel_rag.documents import read_yaml_snapshot
from novel_rag.identity import GraphKey
from novel_rag.mutations.source import build_source_mutation_coordinator
from novel_rag.mutations.types import ChangeSet
from writer_fixtures import write_yaml


@pytest.fixture
def legacy_library(tmp_path: Path) -> Path:
    """依赖：共用 YAML 夹具。输入：临时目录。输出：父子线共用旧物理目录的资料库。实现：只建立两条线的旧式注册和分歧快照。"""
    root = tmp_path / "library"
    book = root / "stories" / "demo"
    write_yaml(root / "registry" / "stories.yaml", {"stories": [{"story_id": "demo", "title": "Demo"}]})
    write_yaml(book / "snapshots" / "child.yaml", {"state": "divergence"})
    write_yaml(book / "registry" / "timelines.yaml", {"timelines": [
        {"story_id": "demo", "timeline_id": "main", "parent_timeline_id": None},
        {"story_id": "demo", "timeline_id": "child", "parent_timeline_id": "main",
         "divergence_at": "volume-01/chapter-01/scene-01", "divergence_snapshot": "snapshots/child.yaml"},
    ]})
    return root


@pytest.mark.parametrize("kind", ["history", "canon"])
def test_scoped_source_coordinator_cannot_reassign_a_legacy_slot(legacy_library: Path, kind: str) -> None:
    """依赖：scope 单源协调器和实际快照。输入：父线 History 或共同 Canon 的正确旧 hash 及子线替换。输出：权限拒绝、原件逐字保留。实现：待写归属都可映射到子线，同时检查已存在版本。"""
    target = legacy_library / "stories" / "demo" / kind / "existing.yaml"
    metadata = {"document_id": "existing", "story_id": "demo", "timeline_id": "main",
                "document_type": kind, "status": "canon", "title": "Existing", "version": "1",
                "volume": 1, "chapter": 1, "scene": 1}
    write_yaml(target, {"metadata": metadata, "content": "original"})
    previous = read_yaml_snapshot(target)
    replacement = {"metadata": dict(metadata, timeline_id="child"), "content": "unapproved replacement"}
    coordinator = build_source_mutation_coordinator(legacy_library, write_scope=GraphKey("demo", "child"),
                                                     allow_common=kind == "canon")
    rejected = coordinator.commit(ChangeSet(changes={target: replacement},
                                              expected_file_fingerprints={target: previous.source_hash}))

    assert rejected.status == "failed" and not rejected.yaml_committed
    assert "scope_denied" in rejected.error
    assert target.read_bytes() == previous.raw_bytes

    owner = GraphKey("demo", "main" if kind == "history" else "child")
    coordinator = build_source_mutation_coordinator(legacy_library, write_scope=owner, allow_common=kind == "canon")
    updated = coordinator.commit(ChangeSet(changes={target: {"metadata": metadata, "content": "owner edit"}},
                                             expected_file_fingerprints={target: previous.source_hash}))

    assert updated.yaml_committed
    assert read_yaml_snapshot(target).data == {"metadata": metadata, "content": "owner edit"}


def test_scoped_common_reference_permission_does_not_allow_writing_history(legacy_library: Path) -> None:
    """依赖：scope 单源协调器及旧式共同资料范围。输入：物理 common 下的 History 和正确 hash。输出：拒绝、原件保持。实现：显式允许共同参考资料也不会授予共同正文写权限。"""
    root = legacy_library
    metadata = {"document_id": "common-history", "story_id": "demo", "timeline_id": "main",
                "document_type": "history", "status": "canon", "title": "Common history", "version": "1",
                "volume": 1, "chapter": 1, "scene": 1}
    path = write_yaml(root / "stories" / "demo" / "common" / "history" / "existing.yaml",
                      {"metadata": metadata, "content": "original"})
    previous = read_yaml_snapshot(path)
    coordinator = build_source_mutation_coordinator(root, write_scope=GraphKey("demo", "child"), allow_common=True)
    result = coordinator.commit(ChangeSet(changes={path: {"metadata": metadata, "content": "unapproved"}},
                                            expected_file_fingerprints={path: previous.source_hash}))

    assert result.status == "failed" and not result.yaml_committed
    assert "scope_denied" in result.error
    assert path.read_bytes() == previous.raw_bytes
