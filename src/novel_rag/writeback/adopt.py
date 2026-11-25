"""v3作者采用：单History权威提交，笔记发布可恢复但不决定正文成功。"""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from threading import RLock

from ..catalog.corpus import document_coordinate
from ..mutations.source import build_source_mutation_coordinator
from ..documents import DocumentRef, load_document, read_yaml_snapshot
from ..identity import GraphKey, StoryCoordinate
from ..std.serialization import json_text
from ..mutations import ChangeSet, MutationResult, SummaryWriter
from ..std.atomic_io import atomic_write_bytes, atomic_write_json
from ..std.hashing import fingerprint_bytes
from ..mutations.types import MISSING_FINGERPRINT, fingerprint_file
from ..service import load_story_sources
from ..std.time import utc_now_iso
from ..generation.store import StoreConflict


class AdoptionService:
    """源锁内准备/恢复；进程内互斥覆盖提交后回执与派生发布。"""

    def __init__(self, library_root: Path, store, memory):
        """依赖：现有mutation owner/Store/Memory。输入：库及组件。输出：采用服务。实现：使用同一源锁域和单进程互斥，不另建事务引擎。"""
        self.root, self.store, self.memory, self.lock = Path(library_root).resolve(), store, memory, RLock()

    def adopt(self, run_id: str, draft_revision: int, expected_source_hash: str | None,
              coordinates, operation_id: str) -> dict:
        """依赖：真实DraftRef/源锁/intent。输入：所选修订、源CAS、坐标、幂等操作ID。输出：adopted结果/冲突。实现：锁内备份+intent+单源replace，源成功后单独发布记忆，失败不撤正文。"""
        with self.lock:
            if not isinstance(operation_id, str) or not 1 <= len(operation_id) <= 128:
                raise ValueError("source_invalid: operation_id长度不合法")
            run = self.store.load(run_id)
            matches = [value["ref"] for value in run["drafts"].values() if value["ref"]["draft_revision"] == draft_revision]
            if len(matches) != 1:
                raise StoreConflict("source_invalid: 所选草稿修订不存在")
            draft_ref = matches[0]
            _, text = self.store.resolve_draft(draft_ref)
            scope = GraphKey(**run["binding"]["scope"])
            coordinate = StoryCoordinate.from_value(coordinates or run["binding"].get("target_coordinate"))
            if not coordinate.is_complete:
                raise ValueError("source_invalid: 采用需要明确卷/章/场景")
            journal_root = self.store.root / scope.story_id / scope.timeline_id / "adoptions"
            path = self.store.adoption_path(scope, operation_id)
            arguments = {"run_id": run_id, "draft_ref": draft_ref, "expected_source_hash": expected_source_hash,
                         "coordinates": {"volume": coordinate.volume, "chapter": coordinate.chapter, "scene": coordinate.scene}}
            argument_hash = fingerprint_bytes(json.dumps(arguments, sort_keys=True).encode("utf-8"))
            result_box = {}

            def prepare(changes):
                """依赖：Coordinator已持源锁/完整字节快照。输入：占位ChangeSet。输出：真实单源ChangeSet或已提交noop。实现：先恢复旧intent，再核目标CAS/备份/持久intent，随后才stage。"""
                import json

                full = load_story_sources(self.root, scope)
                base = run["binding"].get("base_ref")
                target_ref = self.store.target_source_ref(run)
                target = None
                revising_target = bool(target_ref and target_ref.get("coordinate") and coordinate == StoryCoordinate.from_value(target_ref["coordinate"]))
                if revising_target:
                    original, _ = full.read(target_ref["document_id"])
                    if original.metadata["document_type"] != "history":
                        raise ValueError("source_invalid: 采用修订只改History，不自动改Canon")
                    target = original.path
                if target is None:
                    target = self.root / "stories" / scope.story_id / "timelines" / scope.timeline_id / "history" / f"volume-{coordinate.volume:02d}" / f"chapter-{coordinate.chapter:02d}" / f"scene-{coordinate.scene:02d}.yaml"
                target.resolve().relative_to((self.root / "stories" / scope.story_id).resolve())
                # 所有旧提交事实在新adoption_id写入前固化，避免A→B→重试A覆盖B。
                for pending_path in sorted(journal_root.glob("*.json")):
                    pending = json.loads(pending_path.read_text(encoding="utf-8"))
                    if self._intent_target(pending) == target.resolve() and pending.get("state") == "prepared":
                        self._recover_intent(pending_path, pending)
                if path.exists():
                    pending = json.loads(path.read_text(encoding="utf-8"))
                    if pending["arguments_hash"] != argument_hash:
                        raise StoreConflict("revision_conflict: 同采用ID参数不同")
                    self._recover_intent(path, pending)
                    if pending.get("state") == "adopted":
                        result_box.update(intent=pending)
                        return MutationResult("noop", yaml_committed=True, change_id=operation_id)
                    if pending.get("state") == "conflict":
                        raise StoreConflict("revision_conflict: 采用结果无法恢复，保留intent")
                snapshot = read_yaml_snapshot(target) if target.exists() else None
                actual_hash = snapshot.source_hash if snapshot else MISSING_FINGERPRINT
                expected = expected_source_hash if expected_source_hash is not None else MISSING_FINGERPRINT
                if actual_hash != expected:
                    raise StoreConflict("revision_conflict: 正式源已改变，草稿保留")
                # CAS参数不能迁移已固定的运行基线；幂等恢复已在此检查之前返回。
                if base and base["kind"] == "document":
                    actual_base = full.source_refs.get(base["document_id"])
                    if actual_base is None or actual_base.as_dict() != base:
                        raise StoreConflict("revision_conflict: 运行正文基线已改变，请从新版本重新发起")
                elif base and base["kind"] == "draft":
                    self.store.resolve_draft(base)
                if revising_target and full.source_refs[target_ref["document_id"]].as_dict() != target_ref:
                    raise StoreConflict("revision_conflict: 已有正文目标基线改变，草稿保留")
                if snapshot is None:
                    if any(doc.metadata["document_type"] == "history" and document_coordinate(doc) == coordinate for doc in full.documents):
                        raise StoreConflict("revision_conflict: 该坐标已有正式History，请选新场景或明确修订")
                    metadata = {"document_id": "history-" + operation_id, "story_id": scope.story_id,
                                "timeline_id": scope.timeline_id, "document_type": "history", "status": "canon",
                                "title": f"第{coordinate.volume}卷 第{coordinate.chapter}章 第{coordinate.scene}场"}
                    revision, backup = 1, None
                else:
                    original = load_document(target, snapshot=snapshot)
                    metadata = dict(original.metadata)
                    metadata["document_id"] = original.document_id
                    revision = int(metadata.get("source_revision", 1)) + 1
                    backup = self.store.protect_source(self.root, scope, target, snapshot)
                candidates = self.memory.publication_candidates(self.store.load(run_id), draft_ref, full=full)
                frozen = self.store.protect_memory(scope, {"batches": candidates,
                    "canonical_hashes": [fingerprint_bytes(json_text(batch).encode("utf-8")) for batch in candidates]})
                metadata.update(version=str(revision), source_revision=revision, adoption_id=operation_id,
                                memory_publication_expected=True,
                                source_sha256=draft_ref["content_hash"].split(":", 1)[1],
                                volume=coordinate.volume, chapter=coordinate.chapter, scene=coordinate.scene)
                intent = {"operation_id": operation_id, "arguments_hash": argument_hash, "arguments": arguments,
                          "run_id": run_id, "scope": scope.as_dict(), "target": str(target), "expected_source_hash": expected,
                          "draft_ref": draft_ref, "document_id": metadata["document_id"], "source_revision": revision,
                          "content_hash": draft_ref["content_hash"], "backup": str(backup) if backup else None,
                          "target_key": target.resolve().relative_to(self.root).as_posix(),
                          "backup_key": backup.relative_to(self.store.root).as_posix() if backup else None,
                          "memory_frozen": frozen,
                          "state": "prepared", "created_at": utc_now_iso(), "result": None}
                atomic_write_json(path, intent)
                result_box.update(intent=intent)
                return ChangeSet(changes={target: {"metadata": metadata, "content": text}}, affected_graph_keys=(),
                                 expected_file_fingerprints={target: expected}, change_id=operation_id)

            def confirm_source(staged):
                """依赖：仍持有的同一源锁/刚提交文件。输入：staged结果。输出：durable提交事实。实现：新采用可以覆盖之前必须先固化旧结果，之后只补派生回执。"""
                self._recover_intent(path, result_box["intent"])

            coordinator = build_source_mutation_coordinator(self.root, pre_commit=prepare,
                                                            after_source_commit=confirm_source)
            try:
                mutation = coordinator.commit(ChangeSet(changes={}, change_id=operation_id))
                if not mutation.yaml_committed:
                    raise StoreConflict("source_invalid: " + (mutation.error or "正文未提交"))
            except Exception:
                if "intent" not in result_box:
                    raise
                self._recover_intent(path, result_box["intent"])
                if result_box["intent"]["state"] != "adopted":
                    raise
            intent = result_box["intent"]
            self._recover_intent(path, intent)
            result = intent["result"]
            try:
                result["memory_state"] = self._publish(run, intent, text)
            except (ValueError, OSError, RuntimeError):
                result["memory_state"] = "memory_pending"
            intent["result"] = result
            try:
                atomic_write_json(path, intent)
                self.store.record_adoption_receipt(run_id, result)
            except OSError:
                result["receipt_state"] = "pending"
                # 源已提交，回执故障只需同ID恢复；尽可能保留这个说明。
                try:
                    atomic_write_json(path, intent)
                except OSError:
                    pass
            return deepcopy(result)

    def _recover_intent(self, path: Path, intent: dict) -> None:
        """依赖：实际正式文件/原hash/同文件adoption_id。输入：durable intent。输出：原地状态+持久回执。实现：匹配已提交/原源未变/其它冲突三分，不重放未知结果。"""
        if intent.get("state") == "adopted":
            return
        target = self._intent_target(intent)
        try:
            snapshot = read_yaml_snapshot(target)
            metadata, content = snapshot.data.get("metadata", {}), snapshot.data.get("content")
            matched = metadata.get("document_id") == intent["document_id"] and metadata.get("adoption_id") == intent["operation_id"] and isinstance(content, str) and fingerprint_bytes(content.encode("utf-8")) == intent["content_hash"]
        except (ValueError, OSError):
            snapshot, matched = None, False
        if matched:
            intent["state"] = "adopted"
            intent["result"] = {"adopted": True, "document_id": intent["document_id"],
                                "source_revision": intent["source_revision"], "source_hash": snapshot.source_hash,
                                "draft_ref": intent["draft_ref"],
                                "source_ref": DocumentRef(intent["document_id"], intent["source_revision"], snapshot.source_hash,
                                                          GraphKey(**intent["scope"]), StoryCoordinate.from_value(intent["arguments"]["coordinates"])).as_dict(),
                                "memory_state": "memory_pending"}
        elif fingerprint_file(target) == intent["expected_source_hash"]:
            intent["state"] = "uncommitted"
        else:
            intent["state"] = "conflict"
        atomic_write_json(path, intent)

    def _intent_target(self, intent: dict) -> Path:
        """依赖：当前库根/scope。输入：新逻辑键或兼容旧target。输出：可核验的实际目标路径。实现：限定本书内部，搬迁后不向旧绝对位置写入。"""
        target = (self.root / intent["target_key"]).resolve() if intent.get("target_key") else Path(intent["target"]).resolve()
        target.relative_to((self.root / "stories" / intent["scope"]["story_id"]).resolve())
        return target

    def _publish(self, run: dict, intent: dict, text: str) -> str:
        """依赖：冻结候选/保护证据/既有SummaryWriter。输入：已采用intent。输出：complete/skipped/memory_pending。实现：从原冻结集合映射和发布，回执故障不重采样或重提正文。"""
        if intent.get("result", {}).get("memory_state") in {"complete", "skipped"}:
            return intent["result"]["memory_state"]
        target_source = self._intent_target(intent)
        if fingerprint_file(target_source) != intent["result"]["source_hash"]:
            return "skipped"
        coordinate = StoryCoordinate.from_value(intent["arguments"]["coordinates"])
        binding = run["binding"]
        if binding.get("target_coordinate") and coordinate != StoryCoordinate.from_value(binding["target_coordinate"]):
            return "skipped"
        target_ref = self.store.target_source_ref(run)
        if target_ref and target_ref.get("coordinate") and coordinate != StoryCoordinate.from_value(target_ref["coordinate"]):
            return "skipped"
        baseline = binding["narrative_cursor"].get("coordinate")
        if binding["task_kind"] != "revise" and baseline and coordinate <= StoryCoordinate.from_value(baseline):
            return "skipped"
        scope = GraphKey(**intent["scope"])
        if not intent.get("memory_frozen"):
            # Legacy journal lacks a historical freeze; only a still-existing original projection is safe evidence.
            return "skipped"
        original = self.store.protected_memory(intent["memory_frozen"], scope)
        batches = original["batches"]
        adopted_ref = deepcopy(intent["result"]["source_ref"])
        mapped = self.memory.map_publication(batches, adopted_ref)
        for batch in batches:
            for ref in batch["source_refs"]:
                if ref["kind"] == "author_input":
                    self.store.protect_input(run, ref)
        summary_root = self.root / "stories" / scope.story_id / "timelines" / scope.timeline_id / "summaries"
        target = summary_root / ("memory-" + fingerprint_bytes(intent["operation_id"].encode("utf-8")).split(":", 1)[1] + ".yaml")
        publication = intent.get("memory_publication") or {
            "publication_id": intent["operation_id"], "scope": scope.as_dict(), "adopted_source_ref": adopted_ref,
            "raw_snapshot": intent["memory_frozen"], "canonical_hashes": original["canonical_hashes"],
            "mapped_snapshot": self.store.protect_memory(scope, {"batches": mapped}),
            "projection_id": "memory-" + intent["operation_id"],
            "projection_key": target.relative_to(self.root).as_posix(), "projection_ref": None,
            "controls": self.memory.publication_controls(mapped), "batch_count": len(mapped), "state": "prepared"}
        intent["memory_publication"] = publication
        path = self.store.adoption_path(scope, intent["operation_id"])
        atomic_write_json(path, intent)
        if mapped:
            existing = read_yaml_snapshot(target) if target.exists() else None
            metadata = existing.data.get("metadata", {}) if existing else {}
            matching = (metadata.get("document_id") == publication["projection_id"] and
                        metadata.get("memory_kind") == "memory_projection" and metadata.get("ownership", "auto") == "auto" and
                        metadata.get("memory_batches") == mapped)
            if not matching:
                SummaryWriter(summary_root, library_root=self.root, source_only=True).write_ai(
                    target, "创作时记录的经过与仍有效参考。", document_id=publication["projection_id"],
                    metadata={"story_id": scope.story_id, "timeline_id": scope.timeline_id, "document_type": "chapter-summary",
                              "title": "章节参考", "status": "active", "version": "3", "memory_schema_version": 3,
                              "memory_kind": "memory_projection", "memory_batches": mapped, "source_refs": [adopted_ref],
                              "coverage": "bound", **intent["arguments"]["coordinates"]})
            snapshot = read_yaml_snapshot(target)
            self.store.protect_source(self.root, scope, target, snapshot)
            document = load_document(target, snapshot=snapshot)
            publication["projection_ref"] = DocumentRef(document.document_id,
                int(document.metadata.get("source_revision", 1)), snapshot.source_hash, scope, coordinate).as_dict()
            publication["projection_revision"] = int(document.metadata.get("revision", 1))
        publication["state"] = "complete"
        atomic_write_json(path, intent)
        return "complete"


def edit_reference(library_root: Path, store, scope: GraphKey, document_id: str,
                   expected_revision: int, expected_source_hash: str, content) -> dict:
    """依赖：SourceCorpus/原SummaryEditor/源提交工厂/Store备份。输入：作者scope、ID、双CAS与新内容。输出：实际新源。实现：显式编辑Canon或笔记，摘要归属交原owner；无模型调用或任意路径。"""
    from ..mutations.summary import SummaryEditor, SummaryUpdate

    if isinstance(expected_revision, bool) or not isinstance(expected_revision, int) or not isinstance(expected_source_hash, str):
        raise ValueError("source_invalid: 编辑资料需要整数revision与实际文件hash")
    root = Path(library_root).resolve()
    corpus = load_story_sources(root, scope)
    document, ref = corpus.read(document_id)
    if ref.source_hash != expected_source_hash:
        raise StoreConflict("revision_conflict: 资料文件已改变")
    kind = document.metadata["document_type"]
    if "summary" in kind:
        SummaryEditor(document.path.parent, library_root=root, source_only=True).update(
            SummaryUpdate(document_id, expected_revision, content, expected_source_hash))
    elif kind == "canon":
        def prepare(changes):
            """依赖：已持源锁的当前SourceCorpus。输入：占位ChangeSet。输出：单Canon更改。实现：同次字节核双CAS，先保存旧源，稳定身份/坐标只前进revision。"""
            current = load_story_sources(root, scope)
            doc, actual = current.read(document_id)
            if actual.source_hash != expected_source_hash or actual.source_revision != expected_revision:
                raise StoreConflict("revision_conflict: 设定版本已改变")
            snapshot = current.snapshots[document_id]
            store.protect_source(root, scope, doc.path, snapshot)
            body = {"content": content} if isinstance(content, str) and isinstance(doc.body.get("content"), str) else content
            if not isinstance(body, dict) or "metadata" in body:
                raise ValueError("source_invalid: 结构化设定须保持原字段形状")
            metadata = dict(doc.metadata, document_id=doc.document_id,
                            source_revision=actual.source_revision + 1, version=str(actual.source_revision + 1))
            return ChangeSet(changes={doc.path: {"metadata": metadata, **body}}, affected_graph_keys=(),
                             expected_file_fingerprints={doc.path: expected_source_hash})

        result = build_source_mutation_coordinator(root, pre_commit=prepare).commit(ChangeSet(changes={}))
        if not result.yaml_committed:
            raise ValueError("source_invalid: " + (result.error or "设定未提交"))
    else:
        raise ValueError("scope_denied: 此入口只编辑设定或参考笔记，正文请采用草稿")
    updated, actual = load_story_sources(root, scope).read(document_id)
    return {"document_id": document_id, "source_ref": actual.as_dict(), "metadata": updated.metadata,
            "content": updated.body, "document_revision": updated.metadata.get("revision", actual.source_revision)}
