from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from novel_rag.documents import (
    DocumentError,
    DocumentRef,
    load_document,
    read_yaml_mapping,
    read_yaml_snapshot,
)
from novel_rag.generation.types import (
    AuthorInputRef,
    DraftRef,
    NarrativeCursor,
    RunBinding,
    parse_source_ref,
)
from novel_rag.identity import GraphKey, StoryCoordinate
from novel_rag.mutations.types import fingerprint_bytes


def test_source_contract_modules_import_in_isolated_processes() -> None:
    """依赖：Python 子进程。输入：源读取相关模块名。输出：独立导入结果。实现：逐模块启动新解释器捕捉循环依赖。"""

    for module in (
        "novel_rag.service",
        "novel_rag.documents",
        "novel_rag.catalog",
        "novel_rag.generation.types",
    ):
        result = subprocess.run(
            [sys.executable, "-c", f"import {module}"],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, f"{module}: {result.stderr}"


def test_yaml_snapshot_parses_and_hashes_the_same_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """依赖：真实临时 YAML 与 fingerprint_bytes。输入：临时文件及后续外部修改。输出：稳定旧快照。实现：校验解析内容和原始字节指纹一致。"""

    path = tmp_path / "chapter.yaml"
    original = b"metadata:\n  title: First\n  document_id: chapter-1\nbody: first text\n"
    replacement = b"metadata:\n  title: Second\nbody: changed\n"
    path.write_bytes(original)
    read_bytes = Path.read_bytes
    read_count = 0

    def read_then_replace(candidate: Path) -> bytes:
        """依赖：Path.read_bytes。输入：快照文件路径。输出：原始读取字节。实现：读取后模拟并发源文件替换。"""

        nonlocal read_count
        content = read_bytes(candidate)
        if candidate == path and read_count == 0:
            path.write_bytes(replacement)
        read_count += 1
        return content

    monkeypatch.setattr(Path, "read_bytes", read_then_replace)

    snapshot = read_yaml_snapshot(path)

    assert snapshot.path == path
    assert snapshot.raw_bytes == original
    assert snapshot.data["metadata"]["title"] == "First"
    assert snapshot.source_hash == fingerprint_bytes(original)
    assert read_count == 1
    assert read_bytes(path) == replacement
    assert snapshot.source_hash == fingerprint_bytes(original)
    assert snapshot.source_hash != fingerprint_bytes(replacement)
    assert load_document(path, snapshot=snapshot).metadata["title"] == "First"
    assert read_count == 1


def test_load_document_rejects_a_snapshot_for_another_path(tmp_path: Path) -> None:
    """依赖：YamlSnapshot 路径核验。输入：不同路径的快照。输出：DocumentError。实现：确认快照不能替另一来源背书。"""

    source = tmp_path / "source.yaml"
    other = tmp_path / "other.yaml"
    source.write_text("metadata:\n  title: Source\n", encoding="utf-8")
    snapshot = read_yaml_snapshot(source)

    with pytest.raises(DocumentError, match="快照路径与文档路径不一致"):
        load_document(other, snapshot=snapshot)


def test_snapshot_alias_path_keeps_original_bytes_after_source_changes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """依赖：真实文件/快照公共读取。输入：同一文件的相对与绝对路径及后续改源。输出：旧快照值保持、另文件拒绝。实现：验证不同路径表示仍核物理身份，同路径也不偷换新字节。"""
    source = tmp_path / "source.yaml"
    source.write_text("metadata:\n  title: Original\n", encoding="utf-8")
    snapshot = read_yaml_snapshot(source)
    source.write_text("metadata:\n  title: Changed\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    assert load_document(Path("source.yaml"), snapshot=snapshot).metadata["title"] == "Original"
    assert load_document(source, snapshot=snapshot).metadata["title"] == "Original"
    other = tmp_path / "other.yaml"
    other.write_bytes(source.read_bytes())
    with pytest.raises(DocumentError, match="快照路径与文档路径不一致"):
        load_document(other, snapshot=snapshot)


def test_bad_yaml_raises_document_error_and_mapping_compatibility_remains(tmp_path: Path) -> None:
    """依赖：DocumentError 与 read_yaml_mapping。输入：损坏、缺失和非映射 YAML。输出：原错误及兼容空映射。实现：验证两种读取合同边界。"""

    bad = tmp_path / "bad.yaml"
    bad.write_text("metadata: [\n", encoding="utf-8")
    with pytest.raises(DocumentError, match="无法读取 YAML"):
        read_yaml_snapshot(bad)

    assert read_yaml_mapping(tmp_path / "missing.yaml") == {}
    bad.write_text("- item\n", encoding="utf-8")
    assert read_yaml_mapping(bad) == {}
    bad.write_text("null\n", encoding="utf-8")
    assert read_yaml_mapping(bad) == {}


@pytest.mark.parametrize("accelerated", [False, True], ids=["python-fallback", "safe-c-loader"])
def test_yaml_snapshot_safe_loader_preserves_merge_scalars_and_rejects_python_tags(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, accelerated: bool,
) -> None:
    """依赖：两种安全PyYAML后端/真实文件。输入：Unicode、merge/布尔/块正文及Python标签。输出：相同手定值/原hash和危险标签拒绝。实现：禁用可选C后端验证回退，读取仍绑定同次字节。"""
    if accelerated and not hasattr(yaml, "CSafeLoader"):
        pytest.skip("可选LibYAML后端未安装")
    if not accelerated:
        monkeypatch.delattr(yaml, "CSafeLoader", raising=False)
    path = tmp_path / "safe.yaml"
    raw = "defaults: &base\n  count: 3\n  enabled: on\nmetadata:\n  <<: *base\n  title: 原文\nbody:\n  content: |\n    第一行\n    第二行\n".encode("utf-8")
    path.write_bytes(raw)
    snapshot = read_yaml_snapshot(path)
    assert snapshot.data == {"defaults": {"count": 3, "enabled": True}, "metadata": {"count": 3, "enabled": True, "title": "原文"}, "body": {"content": "第一行\n第二行\n"}}
    assert snapshot.raw_bytes == raw and snapshot.source_hash == fingerprint_bytes(raw)
    path.write_text("metadata: {}\nbody: !!python/name:builtins.str ''\n", encoding="utf-8")
    with pytest.raises(DocumentError, match="无法读取 YAML"):
        read_yaml_snapshot(path)


def test_source_references_and_run_binding_round_trip_as_json_values() -> None:
    """依赖：documents 与 generation 纯合同。输入：三类来源和运行绑定。输出：等价往返对象。实现：序列化、重建并区分不同草稿检查点。"""

    document_ref = DocumentRef(
        document_id="chapter-1",
        source_revision=4,
        source_hash="sha256:source",
        scope=GraphKey("story-a", "main"),
        coordinate=StoryCoordinate(1, 2, 3),
    )
    draft_ref = DraftRef(
        draft_document_id="draft-a",
        draft_revision=7,
        content_hash="sha256:draft",
        checkpoint_id="checkpoint-a",
    )
    input_ref = AuthorInputRef(
        run_id="run-a",
        input_slot="outline",
        snapshot_hash="sha256:outline",
    )

    for source_ref in (document_ref, draft_ref, input_ref):
        encoded = source_ref.as_dict()
        decoded = json.loads(json.dumps(encoded))
        assert parse_source_ref(decoded) == source_ref

    assert draft_ref != DraftRef(
        draft_document_id="draft-a",
        draft_revision=7,
        content_hash="sha256:draft",
        checkpoint_id="checkpoint-b",
    )

    binding = RunBinding(
        scope=GraphKey("story-a", "main"),
        task_kind="write",
        narrative_cursor=NarrativeCursor(
            endpoint="after",
            coordinate=StoryCoordinate(1, 2, 2),
        ),
        base_ref=draft_ref,
        draft_branch="branch-a",
        target_coordinate=StoryCoordinate(1, 3, 1),
        selected_parent_checkpoint="checkpoint-a",
        baseline_source_refs=(document_ref,),
        input_snapshot_refs=(input_ref,),
        output_mode="append_suffix",
        initial_memory_revision=9,
    )

    encoded_binding = binding.as_dict()
    decoded_binding = json.loads(json.dumps(encoded_binding))
    assert RunBinding.from_dict(decoded_binding) == binding


def test_source_contract_compatibility_exports_share_one_owner() -> None:
    """依赖：contracts与旧导入入口。输入：三类Ref、解析器、位置校验和指纹格式。输出：旧新接口对象相同。实现：身份比较保证重导出没有第二份类型或校验实现。"""

    from novel_rag import config
    from novel_rag.contracts import references
    from novel_rag.generation import types
    from novel_rag.memory import schema

    assert DocumentRef is references.DocumentRef is types.DocumentRef
    assert DraftRef is references.DraftRef
    assert AuthorInputRef is references.AuthorInputRef
    assert parse_source_ref is references.parse_source_ref
    assert types.MemorySourceRef is references.MemorySourceRef
    assert schema.validate_source_refs is references.validate_source_refs
    assert schema.validate_position is references.validate_position
    assert config.SOURCE_FINGERPRINT_PATTERN is references.SOURCE_FINGERPRINT_PATTERN


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({}, []),
        ({"source_revision": 0}, []),
        ({"source_hash": "sha256:" + "A" * 64}, []),
        ({"coordinate": None}, []),
        ({"coordinate": {"volume": 1}}, []),
        ({"kind": "unknown"}, ["source_refs[0]: 分型Ref对象错误"]),
        ({"extra": "field"}, ["source_refs[0]: 必需字段缺失或存在未知字段"]),
        ({"source_revision": True}, ["source_refs[0].source_revision: 修订需要合法整数"]),
        ({"source_revision": -1}, ["source_refs[0].source_revision: 修订需要合法整数"]),
        ({"source_hash": "sha256:invalid"}, ["source_refs[0]: 实际hash格式无效"]),
        ({"coordinate": {"volume": "1"}}, ["source_refs[0]: narrative_position.coordinate需要显式整数坐标"]),
        ({"coordinate": {"volume": -1}}, ["source_refs[0]: narrative_position.coordinate错误"]),
    ],
)
def test_document_ref_structure_preserves_validation_errors(changes: dict, expected: list[str]) -> None:
    """依赖：纯来源结构校验。输入：正式引用及单字段边界。输出：既有错误文本或通过。实现：以手定有效Ref变异检查严格形状，保持解析与效力判断分离。"""

    from novel_rag.contracts.references import validate_source_refs

    reference = {
        "kind": "document", "document_id": "chapter-1", "source_revision": 1,
        "source_hash": "sha256:" + "a" * 64,
        "scope": {"story_id": "story-a", "timeline_id": "main"},
        "coordinate": {"volume": 1, "chapter": 2, "scene": 3},
    }
    assert validate_source_refs([reference | changes]) == expected


def test_draft_and_author_refs_keep_validation_and_parser_boundaries() -> None:
    """依赖：三类来源合同及原解析器。输入：草稿修订、作者输入槽和未知kind。输出：原结构拒绝及解析异常。实现：检查严格校验仍与不验证效力的纯解析分开。"""

    from novel_rag.contracts.references import validate_source_refs

    draft = DraftRef("draft-1", 1, "sha256:" + "a" * 64, "checkpoint-1").as_dict()
    author = AuthorInputRef("run-1", "request", "sha256:" + "b" * 64).as_dict()
    assert validate_source_refs([draft, author]) == []
    assert validate_source_refs([draft | {"draft_revision": 0}]) == ["source_refs[0].draft_revision: 修订需要合法整数"]
    assert validate_source_refs([author | {"input_slot": "draft"}]) == ["source_refs[0]: 输入槽非法"]
    assert validate_source_refs([]) == ["source_refs需要非空列表"]
    assert validate_source_refs([None]) == ["source_refs[0]: 分型Ref对象错误"]
    assert parse_source_ref(draft | {"content_hash": "unverified"}).content_hash == "unverified"
    with pytest.raises(ValueError, match="未知来源引用 kind"):
        parse_source_ref({"kind": "unknown"})
    with pytest.raises(KeyError, match="draft_document_id"):
        parse_source_ref({"kind": "draft"})
