from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from novel_rag.documents import load_document, validate_document
from novel_rag.mutations import (
    MutationConflictError,
    MutationCoordinator,
    SummaryDocument,
    SummaryEditor,
    SummaryUpdate,
    SummaryWriter,
    ThreadMutationLock,
    fingerprint_file,
)
from novel_rag.service import load_story_sources
from novel_rag.identity import GraphKey
from writer_fixtures import make_library, put_document


def _summary_path(root: Path, name: str = "scene.yaml") -> Path:
    """依赖：Path。输入：临时库根与文件名。输出：规范 summary 路径。实现：固定 stories/timelines/summaries 目录结构。"""

    return root / "stories" / "demo" / "timelines" / "main" / "summaries" / name


def _payload(
    *,
    content: str,
    ownership: str = "auto",
    revision: int = 1,
    memory_kind: str = "memory_projection",
    memory_batches: list[dict[str, Any]] | None = None,
    source_refs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """依赖：YAML summary schema与正式来源引用。输入：文本、所有权、revision、批次及来源。输出：可验证的summary映射。实现：补齐文档元数据并原样保留批次和来源。"""

    return {
        "metadata": {
            "document_id": "scene-summary-v1",
            "story_id": "demo",
            "timeline_id": "main",
            "document_type": "chapter-summary",
            "title": "Scene summary",
            "status": "active",
            "version": "1.0",
            "ownership": ownership,
            "revision": revision,
            "memory_schema_version": 3,
            "memory_kind": memory_kind,
            "source_refs": list(source_refs or []),
            "coverage": {"kind": "author_input"},
            "memory_batches": list(memory_batches or []),
            "custom_metadata": {"keep": True},
        },
        "content": content,
    }


def _source_env(tmp_path: Path) -> tuple[Path, dict[str, Any]]:
    """依赖：writer_fixtures与真实SourceCorpus。输入：pytest临时目录。输出：规范库根与实际History DocumentRef。实现：写真实History YAML并从同一SourceLoader读取其source_hash和范围。"""

    root = make_library(tmp_path)
    put_document(root, "summary-source", "实际正文来源：场景仍在继续。", chapter=1, scene=1)
    source_ref = load_story_sources(root, GraphKey("demo", "main")).source_refs["summary-source"].as_dict()
    return root, source_ref


def _clear_batch(source_ref: dict[str, Any], entry_id: str) -> dict[str, Any]:
    """依赖：StoredMemoryBatch及v3 summary validator。输入：真实来源DocumentRef和稳定状态ID。输出：规范Clear批次。实现：将批次/变化来源、生效位置及Clear身份写入update.state_changes。"""

    return {
        "batch_id": f"clear-{entry_id}",
        "memory_revision": 4,
        "source_refs": [source_ref],
        "narrative_position": {"kind": "document", "coordinate": source_ref["coordinate"]},
        "update": {
            "state_changes": [{
                "op": "clear",
                "entry_id": entry_id,
                "source_refs": [source_ref],
            }],
        },
    }


def _save(path: Path, value: dict[str, Any]) -> None:
    """依赖：PyYAML 与文件系统。输入：目标路径和 summary 映射。输出：真实 YAML 文件。实现：UTF-8 写入兼容格式的安全序列化结果。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(value, allow_unicode=True, sort_keys=False, default_flow_style=False),
        encoding="utf-8",
    )


def _coordinator(root: Path, *, lock: Any | None = None) -> MutationCoordinator:
    """依赖：真实 MutationCoordinator 与 documents validator。输入：库根和可选锁。输出：source-only coordinator。实现：对 staged YAML 调用既有 load_document/validate_document 后返回空图变更协调器。"""

    def validate_staged(staged: Any) -> bool:
        """依赖：既有 document loader/validator。输入：staged changes。输出：校验通过标志。实现：逐文件验证规范 YAML summary schema。"""

        for path in staged.changeset.files:
            errors = validate_document(load_document(staged.staged_path(path)))
            if errors:
                raise AssertionError("; ".join(errors))
        return True

    return MutationCoordinator(
        library_root=root,
        validate_staged=validate_staged,
        lock=lock,
    )


def test_from_yaml_keeps_single_read_fingerprint_out_of_payload(tmp_path: Path) -> None:
    """依赖：SummaryDocument 与文件指纹函数。输入：带扩展 metadata 的实际 YAML。输出：快照与往返断言。实现：验证解析值和字节指纹来自同一读入且指纹不持久化。"""

    target = _summary_path(tmp_path)
    _save(target, _payload(content="计划", memory_batches=[{"batch_id": "clear-1", "changes": [{"op": "clear"}]}]))

    document = SummaryDocument.from_yaml(target)
    payload = document.to_payload()

    assert document.file_fingerprint == fingerprint_file(target)
    assert document.metadata["custom_metadata"] == {"keep": True}
    assert document.metadata["memory_batches"] == [
        {"batch_id": "clear-1", "changes": [{"op": "clear"}]}
    ]
    assert "file_fingerprint" not in payload["metadata"]
    assert "file_fingerprint" not in repr(document)
    assert document == SummaryDocument(
        path=document.path,
        document_id=document.document_id,
        content=document.content,
        ownership=document.ownership,
        source_fingerprint=document.source_fingerprint,
        revision=document.revision,
        stale=document.stale,
        metadata=document.metadata,
        file_fingerprint="sha256:different",
    )


def test_source_only_default_uses_source_owner_without_graph_builder(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """依赖：mutations.source唯一工厂与summary constructors。输入：默认 coordinator 配置。输出：使用的 coordinator 与库根。实现：替换工厂入口并提供无 graph_builder 的真实 coordinator。"""

    coordinator = _coordinator(tmp_path)
    seen: list[Path] = []

    def build_source_mutation_coordinator(*, library_root: Path) -> MutationCoordinator:
        """依赖：临时 coordinator。输入：library_root。输出：可提交 YAML 的协调器。实现：记录根路径并返回真实 MutationCoordinator。"""

        seen.append(library_root)
        return coordinator

    import novel_rag.mutations.source as source_module

    monkeypatch.setattr(
        source_module,
        "build_source_mutation_coordinator",
        build_source_mutation_coordinator,
        raising=False,
    )
    root = tmp_path / "stories" / "demo" / "timelines" / "main" / "summaries"

    writer = SummaryWriter(root, library_root=tmp_path, source_only=True)
    editor = SummaryEditor(root, library_root=tmp_path, source_only=True)

    assert writer.coordinator is coordinator
    assert editor.coordinator is coordinator
    assert seen == [tmp_path.resolve(), tmp_path.resolve()]


def test_source_only_writer_round_trips_metadata_without_graph_keys(tmp_path: Path) -> None:
    """依赖：真实History DocumentRef、MutationCoordinator与原文档validator。输入：旧summary及自动更新。输出：落盘文档与空图键断言。实现：提交规范StoredMemoryBatch并核对来源、Clear和完整metadata往返。"""

    library_root, source_ref = _source_env(tmp_path)
    target = _summary_path(library_root)
    batches = [_clear_batch(source_ref, "e1")]
    _save(target, _payload(content="旧投影", memory_batches=batches, source_refs=[source_ref]))
    observed_keys: list[tuple[Any, ...]] = []

    def validate(staged: Any) -> bool:
        """依赖：真实 staged changes 与原文档 validator。输入：staged changes。输出：schema 校验通过标志。实现：记录图键并验证每份暂存 YAML。"""

        observed_keys.append(staged.changeset.affected_graph_keys)
        for path in staged.changeset.files:
            assert validate_document(load_document(staged.staged_path(path))) == []
        return True

    coordinator = MutationCoordinator(library_root=library_root, validate_staged=validate)
    writer = SummaryWriter(
        target.parent,
        coordinator=coordinator,
        source_only=True,
        affected_graph_keys=(GraphKey("demo", "main"),),
    )
    written = writer.write_ai(
        target,
        "新投影",
        affected_graph_keys=(GraphKey("demo", "main"),),
    )
    loaded = SummaryDocument.from_yaml(target)

    assert written.revision == 2
    assert written.ownership == "auto"
    assert loaded.content == "新投影"
    assert loaded.metadata["memory_kind"] == "memory_projection"
    assert loaded.metadata["memory_batches"] == batches
    assert loaded.metadata["source_refs"] == [source_ref]
    assert loaded.metadata["custom_metadata"] == {"keep": True}
    assert observed_keys == [()]
    assert writer._keys_for(written) == ()


def test_source_only_editor_marks_projection_as_author_note_and_keeps_clear_batch(tmp_path: Path) -> None:
    """依赖：真实History DocumentRef、SummaryEditor与MutationCoordinator。输入：含规范Clear批次的memory projection。输出：author_note与新revision。实现：保存后验证来源、原始Clear批次和扩展metadata均未丢失。"""

    library_root, source_ref = _source_env(tmp_path)
    target = _summary_path(library_root)
    batches = [_clear_batch(source_ref, "old-set")]
    _save(target, _payload(content="模型展示文字", revision=4, memory_batches=batches, source_refs=[source_ref]))
    editor = SummaryEditor(target.parent, coordinator=_coordinator(library_root), source_only=True)

    updated = editor.update(SummaryUpdate("scene-summary-v1", 4, "作者整理后的参考笔记"))
    persisted = SummaryDocument.from_yaml(target)

    assert updated.ownership == "user"
    assert updated.revision == 5
    assert persisted.content == "作者整理后的参考笔记"
    assert persisted.metadata["memory_kind"] == "author_note"
    assert persisted.metadata["memory_batches"] == batches
    assert persisted.metadata["source_refs"] == [source_ref]
    assert persisted.metadata["custom_metadata"] == {"keep": True}
    assert editor._keys_for(persisted) == ()


def test_editor_rejects_save_after_current_snapshot_was_read(tmp_path: Path) -> None:
    """依赖：SummaryStore lookup 与真实 MutationCoordinator。输入：读取后并发保存的新 YAML。输出：CAS 冲突且并发版本保留。实现：在 find 返回实际快照后写入竞争版本，再执行真实 commit。"""

    target = _summary_path(tmp_path)
    _save(target, _payload(content="原投影"))
    editor = SummaryEditor(target.parent, coordinator=_coordinator(tmp_path), source_only=True)
    original_find = editor.store.find

    def find_then_save(document_id: str) -> SummaryDocument:
        """依赖：原始 find 与 _save。输入：摘要 ID。输出：原快照。实现：先实际读取，再模拟作者提交竞争版本。"""

        current = original_find(document_id)
        _save(target, _payload(content="作者刚保存", ownership="user", revision=2, memory_kind="author_note"))
        return current

    editor.store.find = find_then_save  # type: ignore[method-assign]

    with pytest.raises(MutationConflictError, match="fingerprint 不匹配"):
        editor.update(SummaryUpdate("scene-summary-v1", 1, "过期编辑"))

    persisted = SummaryDocument.from_yaml(target)
    assert persisted.content == "作者刚保存"
    assert persisted.ownership == "user"


def test_writer_rejects_user_takeover_after_existing_snapshot_was_read(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """依赖：SummaryDocument snapshot 与真实 MutationCoordinator。输入：读取后接管 ownership 的 YAML。输出：CAS 冲突且用户内容保留。实现：from_yaml 返回旧快照前保存真实用户版本，再运行真实 commit。"""

    target = _summary_path(tmp_path)
    _save(target, _payload(content="原投影"))
    coordinator = _coordinator(tmp_path)
    writer = SummaryWriter(target.parent, coordinator=coordinator, source_only=True)
    original_from_yaml = SummaryDocument.from_yaml
    did_save = False

    def read_then_save(cls: type[SummaryDocument], path: str | Path) -> SummaryDocument:
        """依赖：原始 from_yaml 与 _save。输入：目标路径。输出：旧快照。实现：首次读后保存实际 ownership=user 竞争版本。"""

        nonlocal did_save
        current = original_from_yaml(path)
        if Path(path) == target and not did_save:
            did_save = True
            _save(target, _payload(content="用户接管", ownership="user", revision=2, memory_kind="author_note"))
        return current

    monkeypatch.setattr(SummaryDocument, "from_yaml", classmethod(read_then_save))

    with pytest.raises(MutationConflictError, match="fingerprint 不匹配"):
        writer.write_ai(target, "过期自动结果")

    persisted = original_from_yaml(target)
    assert persisted.content == "用户接管"
    assert persisted.ownership == "user"


def test_writer_missing_fingerprint_protects_a_concurrent_first_create(tmp_path: Path) -> None:
    """依赖：MutationCoordinator lock boundary 与真实文件 CAS。输入：首次写入前并发创建的用户 YAML。输出：missing-fingerprint 冲突且用户文件保留。实现：锁获取处执行真实创建后交给 coordinator 完成校验。"""

    target = _summary_path(tmp_path)

    class CreateBeforeLock(ThreadMutationLock):
        created = False

        def acquire(self) -> None:
            """依赖：ThreadMutationLock 与 _save。输入：无。输出：获取测试锁。实现：首次获取前实际创建竞争文件，再委托加锁。"""

            if not self.created:
                self.created = True
                _save(target, _payload(content="先到的用户文件", ownership="user"))
            super().acquire()

    coordinator = _coordinator(tmp_path, lock=CreateBeforeLock())
    writer = SummaryWriter(target.parent, coordinator=coordinator, source_only=True)

    with pytest.raises(MutationConflictError, match="fingerprint 不匹配"):
        writer.write_ai(target, "首次自动结果")

    persisted = SummaryDocument.from_yaml(target)
    assert persisted.content == "先到的用户文件"
    assert persisted.ownership == "user"
