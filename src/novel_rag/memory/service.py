"""组合源回读、状态/事件投影、router；remember 只提交一个规范批次。"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from uuid import uuid4

from ..catalog.aliases import load_story_aliases
from ..generation.store import DraftStore, StoreConflict
from ..generation.types import MemoryCommit
from ..identity import GraphKey, StoryCoordinate
from ..std.serialization import json_text
from ..std.hashing import fingerprint_bytes
from ..retrieval.assembler import estimate_tokens
from ..service import load_story_sources
from .graph import ENDPOINTS, RECORD_FIELDS, RECORD_GROUPS, project_records
from .effects import initial_memory_effect_invalid
from .router import route
from .schema import validate_memory_update, validate_source_refs, validate_state_entry
from .state import reduce_state


class MemoryService:
    """记忆语义owner；Store只持原始批次/来源映射，不解释故事。"""

    def __init__(self, library_root: Path, store: DraftStore):
        """依赖：现有源读取/DraftStore。输入：库根与唯一Store。输出：记忆服务。实现：只保存依赖，无模型或索引创建。"""
        self.root, self.store = Path(library_root), store

    def corpus(self, run: dict, *, full: bool = False):
        """依赖：load_story_sources。输入：固定run/是否读取全lineage供来源核验。输出：同次源快照。实现：公共scope/游标选择，不按旧工具结果放宽权限。"""
        binding = run["binding"]
        coordinate = binding["narrative_cursor"].get("coordinate")
        from ..identity import StoryCoordinate

        return load_story_sources(self.root, GraphKey(**binding["scope"]),
                                  coordinate=StoryCoordinate.from_value(coordinate) if coordinate and not full else None,
                                  endpoint=binding["narrative_cursor"]["endpoint"])

    def read_snapshot(self, run: dict, *, through: dict | None = None, full=None,
                      include_formal: bool = True) -> dict:
        """依赖：SourceCorpus.at_cursor/同一Store/共同回放。输入：run、可选较早检查点及现成源快照。输出：一次读取的来源/有序批次/缺口/签名。实现：同锁固定分支，来源只解析一次，各消费者共用。"""
        with self.store.lock:
            view_run = deepcopy(run)
            if through:
                _, view_run["draft_text"] = self.store.resolve_draft(through)
                view_run["draft_ref"] = through
                view_run["draft_revision"] = through["draft_revision"]
            full = full or self.corpus(view_run, full=True)
            cursor = view_run["binding"]["narrative_cursor"]
            coordinate = StoryCoordinate.from_value(cursor["coordinate"]) if cursor.get("coordinate") else None
            corpus = full.at_cursor(coordinate, cursor["endpoint"])
            batches, gaps, publications = self._read_batches(view_run, corpus, full, include_formal=include_formal)
            gaps.extend(self._coverage_gaps(view_run, batches))
            return {"run": view_run, "full": full, "corpus": corpus, "batches": batches, "gaps": gaps,
                    "publications": publications, "signature": self._effect_signature(view_run, full, batches, publications)}

    def batches(self, run: dict, corpus=None, *, full=None, include_formal: bool = True) -> tuple[list[dict], list[str]]:
        """依赖：共同read_snapshot。输入：run及可选同次源快照。输出：故事序批次/缺口。实现：兼容原入口，正文读取与采用均委托同一排序和来源效力。"""
        snapshot = self.read_snapshot(run, full=full, include_formal=include_formal)
        return snapshot["batches"], snapshot["gaps"]

    def _publication_evidence(self, publication: dict, source: dict, scope: GraphKey) -> tuple[list[dict], dict]:
        """依赖：Store保护版本/共同StoredBatch/原指纹与映射。输入：发布绑定、正式Ref及scope。输出：核验的映射批次/原hash或来源错误。实现：逐批核原内容身份与冻结集合，不把映射差异当原始冲突。"""
        from ..std.hashing import fingerprint_bytes
        from .schema import validate_stored_batch

        raw = self.store.protected_memory(publication.get("raw_snapshot"), scope)
        mapped = self.store.protected_memory(publication.get("mapped_snapshot"), scope).get("batches")
        batches, hashes = raw.get("batches"), raw.get("canonical_hashes")
        if not isinstance(batches, list) or not isinstance(hashes, list) or any(validate_stored_batch(batch) for batch in batches):
            raise StoreConflict("source_invalid: 冻结批次形状错误")
        actual = {batch["batch_id"]: fingerprint_bytes(json_text(batch).encode("utf-8")) for batch in batches}
        if len(actual) != len(batches) or hashes != list(actual.values()) or publication.get("canonical_hashes") != hashes or publication["batch_count"] != len(batches):
            raise StoreConflict("source_invalid: 冻结批次指纹/集合不符")
        expected = self.map_publication(batches, source)
        if mapped != expected or publication.get("adopted_source_ref") != source or publication.get("scope") != scope.as_dict():
            raise StoreConflict("source_invalid: 发布映射与原冻结批次不符")
        return mapped, actual

    def _published_batches(self, run: dict, corpus, full) -> tuple[list[dict], list[str], dict]:
        """依赖：Store采用journal/保护证据/实际投影。输入：同份源与绑定。输出：正式候选、缺口、发布效力。实现：容器消失仍恢复控制目标，保护副本绝不作为有效事实注入。"""
        from .schema import validate_stored_batch

        scopes = [GraphKey(corpus.scope.story_id, timeline) for timeline in
                  corpus.timeline_registry.allowed_timeline_ids(corpus.scope.timeline_id)]
        journals, gaps = self.store.memory_publications(scopes)
        raw, handled, statuses, known_operations, lost = [], set(), {}, set(), []
        cutoffs = corpus.timeline_registry.cutoffs(corpus.scope.timeline_id)
        for journal in journals:
            source = (journal.get("result") or {}).get("source_ref")
            if not isinstance(source, dict):
                continue
            coordinate = source.get("coordinate")
            position = {"kind": "document", "coordinate": coordinate, "endpoint": "after"} if coordinate else None
            timeline = journal["scope"]["timeline_id"]
            cutoff = cutoffs.get(timeline)
            if self._position_future(position, run) or cutoff is not None and (coordinate is None or StoryCoordinate.from_value(coordinate) > cutoff):
                continue
            operation = journal["operation_id"]
            known_operations.add(operation)
            publication = journal.get("memory_publication")
            if isinstance(publication, dict):
                evidence_error = None
                try:
                    mapped, hashes = self._publication_evidence(publication, source, GraphKey(**journal["scope"]))
                except (ValueError, TypeError, KeyError, OSError) as exc:
                    mapped, hashes, evidence_error = [], {}, str(exc)
                projection = publication.get("projection_ref")
                projection_id = publication.get("projection_id")
                document = next((doc for doc in full.documents if doc.document_id == projection_id), None)
                valid = (evidence_error is None and isinstance(projection, dict) and document is not None and
                         full.source_refs[projection_id].as_dict() == projection and
                         document.metadata.get("memory_batches") == mapped and
                         document.metadata.get("memory_kind") == "memory_projection" and
                         document.metadata.get("ownership", "auto") != "user" and
                         self.source_refs_status([source], run, corpus, full) == "valid")
                statuses[operation] = {"source": source, "projection": full.source_refs[projection_id].as_dict() if document else None,
                                       "binding": publication.get("projection_ref"), "valid": bool(valid),
                                       "evidence": {"raw": publication.get("raw_snapshot"), "mapped": publication.get("mapped_snapshot"),
                                                    "hashes": publication.get("canonical_hashes"), "error": evidence_error}}
                if projection_id:
                    handled.add(projection_id)
                if valid:
                    raw.extend(dict(deepcopy(batch), _raw_hash=hashes[batch["batch_id"]]) for batch in mapped)
                elif publication.get("batch_count", 0):
                    controls = self.publication_controls(mapped) if evidence_error is None else []
                    if controls and all(not validate_stored_batch(batch) for batch in controls):
                        raw.extend(dict(deepcopy(batch), visibility="stale", _raw_hash=hashes[batch["batch_id"]]) for batch in controls)
                    else:
                        raw.append({"batch_id": "gap-" + operation, "memory_revision": 0, "source_refs": [source],
                                    "narrative_position": position, "update": {}, "quarantine": True})
                    lost.append((operation, hashes))
                if evidence_error:
                    gaps.append(f"{operation}: 发布完整性缺口 {evidence_error}")
            else:
                available = [doc for doc in corpus.documents if doc.metadata.get("memory_kind") in {"memory_projection", "author_note"} and
                             any(ref.get("document_id") == source["document_id"] for batch in doc.metadata.get("memory_batches", []) for ref in batch.get("source_refs", []))]
                if not available:
                    raw.append({"batch_id": "legacy-gap-" + operation, "memory_revision": 0, "source_refs": [source],
                                "narrative_position": position, "update": {}, "quarantine": True})
                    gaps.append(f"{operation}: 旧发布缺保护证据，来源之后的基线未知")
                statuses[operation] = {"source": source, "legacy_projection": [doc.document_id for doc in available]}
        for document in corpus.documents:
            metadata = document.metadata
            if metadata.get("memory_kind") not in {"memory_projection", "author_note"} or document.document_id in handled:
                continue
            if metadata.get("memory_kind") == "author_note":
                gaps.append(f"{document.document_id}: 作者编辑笔记，旧投影失效")
            statuses["container:" + document.document_id] = full.source_refs[document.document_id].as_dict()
            raw.extend(dict(deepcopy(batch), visibility="stale") if metadata["memory_kind"] == "author_note" else deepcopy(batch)
                       for batch in metadata.get("memory_batches", []))
        for document in corpus.documents:
            if document.metadata.get("memory_publication_expected") and document.metadata.get("adoption_id") not in known_operations:
                source = corpus.source_refs[document.document_id].as_dict()
                position = {"kind": "document", "coordinate": source["coordinate"], "endpoint": "after"}
                raw.append({"batch_id": "missing-journal-" + document.document_id, "memory_revision": 0,
                            "source_refs": [source], "narrative_position": position, "update": {}, "quarantine": True})
                statuses["missing:" + document.document_id] = source
                gaps.append(f"{document.document_id}: 发布清单缺失，基线未知")
        grouped, unverified = {}, []
        for batch in raw:
            if "_raw_hash" in batch:
                grouped.setdefault(batch["batch_id"], []).append(batch)
            else:
                unverified.append(batch)
        selected, active_hashes = list(unverified), {}
        for batch_id, copies in grouped.items():
            if len({batch["_raw_hash"] for batch in copies}) > 1:
                gaps.append(f"{batch_id}: 规范原始内容冲突，不采用任一副本")
                for batch in copies:
                    selected.extend(dict(control, visibility="stale") for control in self.publication_controls([batch]))
            else:
                valid = [batch for batch in copies if batch.get("visibility") != "stale"]
                candidates = valid or copies
                if valid:
                    active_hashes[batch_id] = copies[0]["_raw_hash"]
                selected.append(min(candidates, key=lambda batch: self._order_key(run, batch, 0, gaps)[:4] +
                    (-max((ref.get("source_revision", 0) for ref in batch["source_refs"]), default=0), json_text(batch))))
        for batch in selected:
            batch.pop("_raw_hash", None)
        for operation, hashes in lost:
            if not hashes or any(active_hashes.get(key) != value for key, value in hashes.items()):
                gaps.append(f"{operation}: 已发布投影缺失/失效，旧记录为未知；可读取当前原文")
        return selected, gaps, statuses

    def _order_key(self, run: dict, batch: dict, ordinal: int, gaps: list[str], lineage: dict | None = None) -> tuple:
        """依赖：StoryCoordinate/Store真实前缀。输入：候选批次和稳定批序。输出：可比较故事排序键。实现：正式坐标或同分支前缀长度先排序，未知只报告缺口而不伪造故事位置。"""
        position = batch.get("narrative_position") or {}
        if position.get("kind") == "draft":
            refs = [batch.get("draft_ref")] + batch.get("source_refs", [])
            ref = next((ref for ref in refs if ref and ref.get("kind") == "draft" and ref.get("checkpoint_id") == position.get("checkpoint_id")), None)
            if ref:
                try:
                    source_run, prefix = self.store.resolve_draft(ref)
                    return (1, len(prefix.encode("utf-8")), (lineage or {}).get(source_run["run_id"], 0), ref["draft_revision"], 0, ordinal)
                except (ValueError, OSError):
                    pass
        coordinate = position.get("coordinate")
        if coordinate is None:
            coords = [ref["coordinate"] for ref in batch.get("source_refs", []) if ref.get("kind") == "document" and ref.get("coordinate")]
            if coords:
                coordinate = max(coords, key=StoryCoordinate.from_value)
        if coordinate:
            value = StoryCoordinate.from_value(coordinate)
            revision = max((ref.get("source_revision", 0) for ref in batch.get("source_refs", []) if ref.get("kind") == "document"), default=0)
            return (0, value.volume, value.chapter or 0, value.scene or 0, revision,
                    ordinal + (1000000000 if batch.get("quarantine") or batch.get("visibility") == "stale" else 0))
        if any(ref.get("kind") != "author_input" for ref in batch.get("source_refs", [])):
            gaps.append(f"{batch['batch_id']}: 生效位置未知，不声称覆盖完整")
        return (2, 0, 0, 0, 0, ordinal)

    def _read_batches(self, run: dict, corpus, full, *, include_formal: bool = True) -> tuple[list[dict], list[str], dict]:
        """依赖：共同排序/SourceRef效力/所选父链。输入：同次来源与分支。输出：有序且标效力的批次/缺口/发布签名。实现：未来先过滤，失效控制保留，原始记录不改写。"""
        raw, gaps, publications = self._published_batches(run, corpus, full) if include_formal else ([], [], {})
        gaps = list(corpus.gaps) + gaps
        parents, current, seen = [], run, set()
        while current["run_id"] not in seen:
            seen.add(current["run_id"])
            parents.append(current)
            binding, parent = current["binding"], current["binding"].get("base_ref")
            if binding["output_mode"] != "append_suffix" or not parent or parent["kind"] != "draft":
                break
            current, _ = self.store.resolve_draft(parent)
        for parent in reversed(parents):
            raw.extend(deepcopy(parent["memory_batches"]))
        lineage = {parent["run_id"]: index for index, parent in enumerate(reversed(parents))}
        ordered = sorted(enumerate(raw), key=lambda item: self._order_key(run, item[1], item[0], gaps, lineage))
        batches = []
        for _, batch in ordered:
            forced = batch.get("visibility") == "stale"
            for change in batch.get("update", {}).get("state_changes", []):
                data = change.get("entry", change)
                refs = data.get("source_refs", batch.get("source_refs", []))
                status = self.source_refs_status(refs, run, corpus, full)
                if status == "valid" and self._source_role_error({"record_kind": "state", "source_refs": refs}, full):
                    status = "stale"
                position = data.get("narrative_position", batch.get("narrative_position"))
                change["visibility"] = "future" if self._position_future(position, run) or status == "future" else "stale" if forced else status
            boundary = batch.get("update", {}).get("scene_boundary")
            if boundary:
                refs = [batch["draft_ref"]] if batch.get("draft_ref") else batch["source_refs"]
                status = self.source_refs_status(refs, run, corpus, full)
                if status == "valid" and self._source_role_error({"record_kind": "scene_boundary", "source_refs": refs}, full):
                    status = "stale"
                    gaps.append(f"{batch['batch_id']}: 场景边界来源资格不符")
                batch["boundary_visibility"] = "future" if self._position_future(batch.get("narrative_position"), run) or status == "future" else "stale" if forced else status
            for group in RECORD_GROUPS:
                for write in batch.get("update", {}).get(group, []):
                    data = write.get("record", write)
                    candidate = dict(data, narrative_position=data.get("narrative_position", batch.get("narrative_position")))
                    status = self._record_status(candidate, run, corpus, full)
                    write["visibility"] = "future" if status == "future" else "stale" if forced else status
                    if write["visibility"] == "stale":
                        gaps.append(f"{write['id']}: 记录来源失效，可读取当前原文")
            for entity in batch.get("update", {}).get("unresolved_entities", []):
                status = self._record_status(dict(entity, record_kind="unresolved_entity"), run, corpus, full)
                entity["visibility"] = "future" if status == "future" else "stale" if forced else status
                if entity["visibility"] == "stale":
                    gaps.append(f"{entity['id']}: 未定身份来源失效/来源资格不符")
            batches.append(batch)
        return batches, list(dict.fromkeys(gaps)), publications

    def _effect_signature(self, run: dict, full, batches: list[dict], publications: dict) -> dict:
        """依赖：同次来源/实际前缀效力。输入：run和回放输入。输出：不依赖查询的效力签名。实现：覆盖来源版本、投影存在性与父前缀，不设第二revision。"""
        signature = {"publications": publications}
        refs = list(run["binding"]["baseline_source_refs"])
        base = run["binding"].get("base_ref")
        if base:
            refs.append(base)
        for batch in batches:
            if self._position_future(batch.get("narrative_position"), run):
                continue
            refs.extend(batch.get("source_refs", []))
            for group in RECORD_GROUPS:
                for write in batch.get("update", {}).get(group, []):
                    refs.extend(write.get("record", write).get("source_refs", []))
        for ref in refs:
            if ref["kind"] == "document":
                actual = full.source_refs.get(ref["document_id"])
                signature["document:" + ref["document_id"]] = actual.as_dict() if actual else None
            elif ref["kind"] == "draft":
                try:
                    signature["draft:" + ref["checkpoint_id"]] = self.store.prefix_status(run, ref)
                except (ValueError, OSError):
                    signature["draft:" + ref["checkpoint_id"]] = "stale"
            elif ref["kind"] == "author_input":
                try:
                    self.store.input_text(ref)
                    signature["input:" + ref["run_id"] + ":" + ref["input_slot"]] = ref["snapshot_hash"]
                except (ValueError, OSError):
                    signature["input:" + ref["run_id"] + ":" + ref["input_slot"]] = None
        return signature

    def _position_future(self, position: dict | None, run: dict) -> bool:
        """依赖：正式before/after游标。输入：记录摄取位置/run。输出：是否未来。实现：按记录生效点裁剪，不用事实最早出处或墙钟代替。"""
        from ..identity import StoryCoordinate

        cursor = run["binding"]["narrative_cursor"]
        if not position or position.get("kind") != "document" or not cursor.get("coordinate"):
            return False
        coordinate = StoryCoordinate.from_value(position["coordinate"])
        limit = StoryCoordinate.from_value(cursor["coordinate"])
        return coordinate > limit or cursor["endpoint"] == "before" and coordinate == limit

    def _coverage_gaps(self, run: dict, batches: list[dict]) -> list[str]:
        """依赖：真实正文检查点/逐项效力。输入：当前正文与故事序批次。输出：未记录后缀/未知scene缺口。实现：仅正文变化推进覆盖，不要求周期总结或阻止保存。"""
        covered, gaps = 0, []
        for batch in batches:
            changes = batch.get("update", {}).get("state_changes", [])
            for change in changes:
                entry = change.get("entry", {})
                if change.get("visibility", "valid") == "valid" and entry.get("lifetime") == "scene" and not entry.get("scene_id"):
                    gaps.append(f"{change['entry_id']}: scene生命周期边界未知")
            body = any(change.get("visibility", "valid") == "valid" for change in changes) or any(
                write.get("visibility", "valid") == "valid" and any(ref["kind"] != "author_input" for ref in write.get("record", write).get("source_refs", []))
                for group in RECORD_GROUPS for write in batch.get("update", {}).get(group, [])) or (
                batch.get("update", {}).get("scene_boundary") and batch.get("boundary_visibility") == "valid")
            ref = batch.get("draft_ref")
            if body and ref and ref["kind"] == "draft" and self.store.prefix_status(run, ref) == "valid":
                _, prefix = self.store.resolve_draft(ref, run=run)
                covered = max(covered, len(prefix.encode("utf-8")))
        if len(run["draft_text"].encode("utf-8")) > covered:
            gaps.append("当前草稿存在尚未记录的正文后缀；覆盖没有推进")
        return gaps

    def source_refs_status(self, refs: list[dict], run: dict, corpus, full) -> str:
        """依赖：真实SourceCorpus/检查点/输入版本。输入：逐项引用与当前绑定。输出：valid/future/stale。实现：先核实际字节和范围，再区分游标未来，不把缺失当未发生。"""
        if not refs:
            return "stale"
        statuses = []
        for ref in refs:
            try:
                if ref["kind"] == "document":
                    source = full.source_refs.get(ref["document_id"])
                    if source is None or source.as_dict() != ref:
                        return "stale"
                    statuses.append("valid" if ref["document_id"] in corpus.source_refs else "future")
                elif ref["kind"] == "draft":
                    statuses.append(self.store.prefix_status(run, ref))
                elif ref["kind"] == "author_input":
                    self.store.input_text(ref)
                    statuses.append("valid")
                else:
                    return "stale"
            except (ValueError, KeyError, OSError):
                return "stale"
        return "stale" if "stale" in statuses else "future" if "future" in statuses else "valid"

    def _record_status(self, record: dict, run: dict, corpus, full) -> str:
        """依赖：真实来源/叙事生效点。输入：记录与固定run。输出：valid/future/stale。实现：先排除未来，再核来源资格；未来失效不能撤销过去，较早出处不提前人物摄取。"""
        if self._position_future(record.get("narrative_position"), run):
            return "future"
        status = self.source_refs_status(record.get("source_refs", []), run, corpus, full)
        if status == "valid" and self._source_role_error(record, full):
            return "stale"
        return status

    def _source_role_error(self, record: dict, full) -> str | None:
        """依赖：同次SourceCorpus/记录类型。输入：规范记录与来源快照。输出：来源资格错误或None。实现：新写入与正式回读共用正文/作者输入适用域，Canon仅补充发生记录。"""
        refs, kind, payload = record.get("source_refs", []), record.get("record_kind"), record.get("payload", {})
        if refs and all(ref["kind"] == "author_input" for ref in refs) and kind not in {"note", "link", "hook"}:
            return "作者计划不是已发生事实"
        body_source = any(ref["kind"] == "draft" or ref["kind"] == "document" and
                          full.read(ref["document_id"])[0].metadata["document_type"] == "history" for ref in refs)
        if kind in {"event_line", "experience", "state", "scene_boundary", "unresolved_entity"} or kind == "hook" and payload.get("nature") != "author_plan":
            if not body_source:
                return "已发生记录需要实际正文检查点/History，Canon仅可补充"
        if kind == "hook" and payload.get("nature") == "author_plan" and not any(ref["kind"] == "author_input" for ref in refs):
            return "author_plan必须显式引用真实AuthorInputRef"
        return None

    def _reconcile(self, run: dict, corpus, full, batches: list[dict], *, signature: dict | None = None) -> dict:
        """依赖：纯来源失效策略/Store原子协调。输入：同次快照及签名。输出：当前版本run。实现：领域层判首次失效，Store复核版本/选中稿并原子落盘。"""
        signature = signature if signature is not None else self._effect_signature(run, full, batches, {})
        initially_invalid = initial_memory_effect_invalid(run["binding"]["baseline_source_refs"], full.source_refs,
                                                          signature, run.get("memory_local_invalidations", []))
        return self.store.reconcile_memory_effect(run["run_id"], expected_memory_revision=run["memory_revision"],
                                                  expected_draft_ref=run.get("draft_ref"), signature=signature,
                                                  initially_invalid=initially_invalid)

    def current_snapshot(self, run_id: str) -> dict:
        """依赖：共同read_snapshot/效力CAS。输入：固定run。输出：已协调版本的源快照或冲突。实现：复用原三次内部读取重试，不选择记忆、不新建状态。"""
        for attempt in range(3):
            run = self.store.load(run_id)
            snapshot = self.read_snapshot(run)
            corpus, full = snapshot["corpus"], snapshot["full"]
            batches, gaps = snapshot["batches"], snapshot["gaps"]
            try:
                run = self._reconcile(run, corpus, full, batches, signature=snapshot["signature"])
                break
            except StoreConflict as exc:
                if "memory_snapshot已过期" not in str(exc) or attempt == 2:
                    raise
        snapshot["run"] = run
        return snapshot

    def recall(self, run_id: str, *, focus: list[str] | None = None, query: str = "",
               available_tokens: int | None = None, snapshot: dict | None = None,
               candidate_search: dict | None = None, with_candidate_state: bool = False,
               browse_all: bool = False) -> dict:
        """依赖：共同快照/reducer/graph/router。输入：查询/原进度及作者全可见浏览标志。输出：完整包/冲突及可选内部进度。实现：原来源权限内选择，浏览独立绑定，控制状态不占事实预算。"""
        snapshot = snapshot if snapshot is not None else self.current_snapshot(run_id)
        if snapshot["run"]["run_id"] != run_id:
            raise StoreConflict("scope_denied: 记忆快照不属于本run")
        run, corpus, full = snapshot["run"], snapshot["corpus"], snapshot["full"]
        batches, gaps = snapshot["batches"], snapshot["gaps"]
        source_snapshot_hash = None
        if candidate_search is not None or with_candidate_state or browse_all:
            source_snapshot_hash = fingerprint_bytes(json_text({"refs": {key: ref.as_dict() for key, ref in corpus.source_refs.items()},
                                                                 "gaps": corpus.gaps}).encode("utf-8"))
        if candidate_search is not None and candidate_search.get("source_snapshot_hash") != source_snapshot_hash:
            raise ValueError("snapshot_stale: 候选查询的可见来源已改变，请重新recall")
        state = reduce_state(batches, memory_revision=run["memory_revision"], scope=corpus.scope.as_dict(), gaps=gaps)
        dependency_gaps = {}
        records = project_records(batches, visible=lambda record: self._record_status(record, run, corpus, full),
                                  dependency_gaps=dependency_gaps)
        entities = corpus.entities()
        focus = list(focus or [])
        requested_focus = list(focus)
        allowed = set(corpus.timeline_registry.allowed_timeline_ids(corpus.scope.timeline_id))
        aliases, alias_error = [], None
        try:
            aliases = [alias for alias in load_story_aliases(self.root, corpus.scope.story_id)
                       if alias["timeline_id"] in allowed | {"", "common"}]
            for alias in aliases:
                if alias["alias"] in focus or alias["alias"] in query:
                    focus.append(alias["entity_id"])
        except (OSError, ValueError) as exc:
            alias_error = str(exc)
            state["gaps"].append(f"别名来源无效: {exc}")
        alias_hash = fingerprint_bytes(json_text({"aliases": aliases, "error": alias_error}).encode("utf-8"))
        if candidate_search is not None and candidate_search.get("alias_hash") != alias_hash:
            raise ValueError("snapshot_stale: 候选查询的别名来源已改变，请重新recall")
        for key, entity in entities.items():
            records[key] = {"id": key, "record_kind": "entity", "payload": entity, "source_refs": []}
        for key, row in records.items():
            if row["record_kind"] == "entity" and isinstance(row["payload"].get("name"), str) and (
                    row["payload"]["name"] in focus or row["payload"]["name"] in query):
                focus.append(key)
        from ..graph.builder import normalize_entities

        route_capacity = available_tokens
        while True:
            packet = route(records, state["entries"], focus=focus, query=query, available_tokens=route_capacity,
                           blocked_dependencies=dependency_gaps, ended_entries=state["ended_entries"], candidate_search=candidate_search,
                           browse_all=browse_all)
            navigation_state = packet.pop("candidate_search_state", None)
            if navigation_state is not None:
                navigation_state["source_snapshot_hash"] = source_snapshot_hash
                navigation_state.update(request_focus=requested_focus, alias_hash=alias_hash)
                packet["candidate_search"]["state_hash"] = fingerprint_bytes(json_text(navigation_state).encode("utf-8"))
            selected_state = deepcopy(state)
            selected_state["entries"] = packet.pop("state_entries")
            selected_state["ended_entries"] = packet.pop("state_receipts", [])
            selected_state["claims"] = [row for row in selected_state["entries"]
                                        if row.get("domain") == "CharacterView" and row.get("kind") == "claim"]
            selected_state["source_refs"] = list(packet["source_refs"])
            selected_state.update(draft_branch=run["binding"]["draft_branch"], baseline_ref=run["binding"].get("base_ref"))
            if not batches:
                packet["gaps"].append("尚无事件/状态记忆，可读取正式原文")
            packet.update(memory_revision=run["memory_revision"], state_view=selected_state,
                          references=[{"source_ref": ref.as_dict(), "kind": "original", "document_id": key,
                                       "entity_refs": normalize_entities(corpus.read(key)[0].metadata)}
                                      for key, ref in corpus.source_refs.items() if key in {ref.get("document_id") for ref in packet["source_refs"]}])
            packet["gaps"] = list(dict.fromkeys(packet["gaps"] + selected_state["gaps"]))
            if available_tokens is None:
                break
            excess = estimate_tokens(json_text(packet)) - available_tokens
            if excess <= 0:
                break
            if route_capacity <= 0:
                raise ValueError("context_limit: 记忆来源/覆盖元数据超过显式容量，记录已保留")
            route_capacity = max(0, route_capacity - excess)
        for reference in corpus.search(query, focus=focus, limit=None if available_tokens is None else 8):
            if reference["document_id"] in {item["document_id"] for item in packet["references"]}:
                continue
            if available_tokens is None:
                packet["references"].append(reference)
                continue
            candidate = deepcopy(packet)
            candidate["references"].append(reference)
            if estimate_tokens(json_text(candidate)) > available_tokens:
                reference = dict(reference, text=None)
                candidate["references"][-1] = reference
            if estimate_tokens(json_text(candidate)) <= available_tokens:
                packet = candidate
        if browse_all:
            packet["browse_binding"] = {"run_id": run_id, "draft_ref": run.get("draft_ref"),
                                       "draft_revision": run["draft_revision"], "memory_revision": run["memory_revision"],
                                       "source_snapshot_hash": source_snapshot_hash}
        if with_candidate_state and navigation_state is not None:
            packet["_candidate_search_state"] = navigation_state
        return packet

    @staticmethod
    def remember_arguments(*, draft_ref: dict | None = None, expected_memory_revision: int, update: dict) -> dict:
        """依赖：记忆提交输入合同。输入：可省略稿源、版本、原差分。输出：唯一幂等参数。实现：省略draft_ref与显式None规范为同一值，回执查询和提交共用。"""
        return {"draft_ref": draft_ref, "expected_memory_revision": expected_memory_revision, "update": update}

    def remember(self, run_id: str, call_id: str, *, draft_ref: dict | None,
                 expected_memory_revision: int, update: dict) -> dict:
        """依赖：共同快照/既有源锁/Store原子提交。输入：来源、CAS、整批差分与调用ID。输出：稳定回执。实现：幂等优先，源锁→Store锁内校验版本及来源再整批提交，取消不越过提交点。"""
        from ..mutations.source import build_source_mutation_coordinator
        from ..mutations.types import fingerprint_file

        arguments = self.remember_arguments(draft_ref=draft_ref, expected_memory_revision=expected_memory_revision, update=update)
        previous = self.store.committed_tool(run_id, call_id, arguments)
        if previous is not None:
            return previous
        if draft_ref is not None:
            errors = validate_source_refs([draft_ref])
            if errors or draft_ref.get("kind") != "draft":
                raise ValueError("source_invalid: draft_ref需要合法DraftRef；" + "; ".join(errors))
        with build_source_mutation_coordinator(self.root).lock:
            with self.store.lock:
                run = self.store.load(run_id)
                snapshot = self.read_snapshot(run)
                self._reconcile(run, snapshot["corpus"], snapshot["full"], snapshot["batches"], signature=snapshot["signature"])

                def build(current: dict) -> MemoryCommit:
                    """依赖：固定源快照/规范化器。输入：提交边界当前run。输出：MemoryCommit或来源错误。实现：复核同份源字节，外部不合作编辑不产生混合来源提交。"""
                    commit = self._normalize(current, draft_ref, update, snapshot=snapshot)
                    for document in snapshot["full"].documents:
                        ref = snapshot["full"].source_refs[document.document_id]
                        if fingerprint_file(document.path) != ref.source_hash:
                            raise StoreConflict("source_invalid: 提交前来源快照已改变，请重新读取")
                    return commit

                return self.store.commit_memory(run_id, call_id, arguments, build)

    def _normalize(self, run: dict, draft_ref: dict | None, update: dict, *, snapshot: dict | None = None) -> MemoryCommit:
        """依赖：同run来源/共同Schema/graph字段。输入：完整差分。输出：批次/回执/签名的明确提交值或拒绝。实现：整批校验后分配ID和来源，内部签名不写入业务批次。"""
        errors = validate_memory_update(update)
        if errors:
            raise ValueError("source_invalid: " + "; ".join(errors))
        snapshot = self.read_snapshot(run, full=snapshot["full"] if snapshot else None, through=draft_ref)
        corpus, full = snapshot["corpus"], snapshot["full"]
        if draft_ref and self.source_refs_status([draft_ref], run, corpus, full) != "valid":
            raise StoreConflict("source_invalid: 正文检查点已失效或不在所选分支")
        batches = snapshot["batches"]
        known, slots = {}, {}
        for batch in batches:
            for change in batch.get("update", {}).get("state_changes", []):
                status = change.get("visibility", batch.get("visibility", "valid"))
                if status == "future":
                    continue
                if status == "stale":
                    known.pop(change["entry_id"], None)
                else:
                    known[change["entry_id"]] = "state"
                    if "entry" in change:
                        slots[change["entry_id"]] = change["entry"]
        records = project_records(batches, visible=lambda record: self._record_status(record, run, corpus, full))
        known.update((key, row["record_kind"]) for key, row in records.items())
        known.update((key, "entity") for key in corpus.entities())
        # 临时身份仅由host返回；不把任意同名文字合并为Canon。
        known.update((key, "entity") for key in run.get("unresolved_entities", {}))
        normalized, mapping, accepted = deepcopy(update), {}, []
        groups = RECORD_GROUPS
        if set(update) - set(groups) - {"state_changes", "scene_boundary", "unresolved_entities"}:
            raise ValueError("source_invalid: 未知记忆更新字段")
        for entity in normalized.get("unresolved_entities", []):
            local = entity["local_ref"]
            if not draft_ref or local in mapping:
                raise ValueError("source_invalid: 临时身份需要实际正文来源及唯一local_ref")
            stable = "entity-" + uuid4().hex
            mapping[local], known[stable] = stable, "entity"
            entity.update(id=stable, scope=run["binding"]["scope"], source_refs=[draft_ref],
                          narrative_position={"kind": "draft", "checkpoint_id": draft_ref["checkpoint_id"]})
            accepted.append(stable)
        for index, change in enumerate(normalized.get("state_changes", [])):
            path = f"update.state_changes[{index}]"
            if not draft_ref or change.get("op") not in {"set", "clear"}:
                raise ValueError(f"source_invalid: {path}: 状态变化需要正文来源及set/clear")
            local = change.get("local_ref")
            if local:
                if local in mapping or change.get("entry_id") or change["op"] != "set":
                    raise ValueError(f"source_invalid: {path}.local_ref: 重复/混用ID")
                mapping[local] = "state-" + uuid4().hex
                change["entry_id"] = mapping[local]
                known[change["entry_id"]] = "state"
            elif known.get(change.get("entry_id")) != "state":
                raise ValueError(f"source_invalid: {path}.entry_id: 状态ID未知，请先recall读取真实条目；新建使用local_ref")
            accepted.append(change["entry_id"])
            if change["op"] == "set":
                entry = change["entry"]
                for field in ("holder", "target"):
                    if isinstance(entry.get(field), dict):
                        stable = mapping.get(entry[field]["local_ref"])
                        if not stable or known.get(stable) != "entity":
                            raise ValueError("scope_denied: 未定身份local_ref不存在或不是entity")
                        entry[field] = stable
                errors = validate_state_entry(entry)
                if errors:
                    raise ValueError(f"source_invalid: {path}.entry: " + "; ".join(errors))
                if change["entry_id"] in slots and any(slots[change["entry_id"]].get(field) != entry.get(field)
                                                       for field in ("domain", "kind", "holder", "target")):
                    identity = {field: slots[change["entry_id"]].get(field) for field in ("domain", "kind", "holder", "target")}
                    raise ValueError(f"source_invalid: {path}.entry: 状态身份的领域/kind/holder/target不能改变；原身份=" +
                                     json_text(identity) + "；先recall读取原entry_id，更新保留原身份，新身份须显式新建local_ref")
                entry.update(entry_id=change["entry_id"], source_refs=[draft_ref])
            else:
                change["source_refs"] = [draft_ref]
        for group, kind in groups.items():
            for index, write in enumerate(normalized.get(group, [])):
                path = f"update.{group}[{index}]"
                if write.get("op") not in {"create", "update", "retire"}:
                    raise ValueError(f"source_invalid: {path}.op: 记录操作非法")
                if write["op"] == "create":
                    local = write.get("local_ref")
                    if not local or local in mapping:
                        raise ValueError(f"source_invalid: {path}.local_ref: 新记录需唯一local_ref")
                    mapping[local] = kind + "-" + uuid4().hex
                    write["id"] = mapping[local]
                    known[write["id"]] = kind
                else:
                    ref = write.get("ref", {})
                    if ref.get("kind") != kind or known.get(ref.get("id")) != kind:
                        raise ValueError(f"source_invalid: {path}.ref: 记录类型/ID不能改变；先recall读取原kind/id，未知ID不可用于更新或退役，新建使用local_ref")
                    write["id"] = ref["id"]
                accepted.append(write["id"])
        sources = []
        for group, kind in groups.items():
            for index, write in enumerate(normalized.get(group, [])):
                path = f"update.{group}[{index}]"
                if write["op"] == "retire":
                    if not draft_ref:
                        raise ValueError(f"source_invalid: {path}: 退役需实际正文来源")
                    write["source_refs"] = [draft_ref] if draft_ref else []
                    continue
                record = write.get("record")
                record_path = path + ".record"
                if not isinstance(record, dict):
                    raise ValueError(f"source_invalid: {record_path}需要包含record_kind和payload的对象")
                if record.get("record_kind") != kind:
                    raise ValueError(f"source_invalid: {record_path}.record_kind必须为小写{kind}")
                payload = record.get("payload")
                if not isinstance(payload, dict):
                    raise ValueError(f"source_invalid: {record_path}.payload必须是对象，允许字段{sorted(RECORD_FIELDS[kind])}")
                unexpected = set(payload) - RECORD_FIELDS[kind]
                if unexpected:
                    raise ValueError(f"source_invalid: {record_path}.payload未知字段{sorted(unexpected)}，允许字段{sorted(RECORD_FIELDS[kind])}；拓扑用links记录")
                refs = record.get("source_refs") or ([draft_ref] if draft_ref else [])
                allowed_inputs = run["binding"]["input_snapshot_refs"]
                if any(ref["kind"] == "author_input" and ref not in allowed_inputs for ref in refs):
                    raise ValueError(f"scope_denied: {record_path}.source_refs: 输入引用未经本run提供")
                if self.source_refs_status(refs, run, corpus, full) != "valid":
                    raise ValueError(f"source_invalid: {record_path}.source_refs: 记录来源不可见或过期")
                role_error = self._source_role_error(dict(record, source_refs=refs), full)
                if role_error:
                    raise ValueError(f"source_invalid: {record_path}.source_refs: " + role_error)
                if not draft_ref and (kind in {"event_line", "experience"} or kind == "hook" and payload.get("nature") != "author_plan"):
                    raise ValueError(f"source_invalid: {record_path}.source_refs: 已发生记录需要实际正文检查点/History，Canon仅可补充")
                if kind == "link":
                    for field in ("subject_ref", "object_ref"):
                        ref = payload[field]
                        if "local_ref" in ref:
                            stable = mapping.get(ref["local_ref"])
                            if not stable:
                                raise ValueError(f"source_invalid: {record_path}.payload.{field}: 悬空local_ref")
                            payload[field] = {"id": stable, "kind": known[stable]}
                        elif known.get(ref.get("id")) != ref.get("kind"):
                            raise ValueError(f"scope_denied: {record_path}.payload.{field}: 关联端点未知或越域；先recall读取真实kind/id")
                    ends = ENDPOINTS.get(payload["relation_type"])
                    if not ends or payload["subject_ref"]["kind"] not in ends[0] or payload["object_ref"]["kind"] not in ends[1]:
                        raise ValueError(f"source_invalid: {record_path}.payload: Link方向/端点非法")
                record.update(id=write["id"], scope=run["binding"]["scope"], source_refs=refs)
                sources.extend(ref for ref in refs if ref not in sources)
        if draft_ref and draft_ref not in sources:
            sources.append(draft_ref)
        position = {"kind": "draft", "checkpoint_id": draft_ref["checkpoint_id"]} if draft_ref else None
        boundary = normalized.get("scene_boundary")
        if boundary:
            if not draft_ref or boundary != "begin_scene":
                raise ValueError("source_invalid: 场景边界需要正文和begin_scene")
            normalized["scene_boundary"] = {"kind": "begin_scene", "scene_id": "scene-" + uuid4().hex}
        scene_id = normalized.get("scene_boundary", {}).get("scene_id") if isinstance(normalized.get("scene_boundary"), dict) else None
        for change in normalized.get("state_changes", []):
            if "entry" in change:
                change["entry"].update(narrative_position=position)
                if change["entry"]["lifetime"] == "scene":
                    change["entry"]["scene_id"] = scene_id or self._current_scene(batches)
        for group in groups:
            for write in normalized.get(group, []):
                if "record" in write:
                    write["record"]["narrative_position"] = position
        batch = {"batch_id": "batch-" + uuid4().hex, "memory_revision": 0, "draft_ref": draft_ref,
                 "source_refs": sources, "narrative_position": position, "update": normalized}
        signature = self._effect_signature(run, full, batches + [batch], snapshot["publications"])
        result = {"memory_revision": 0, "accepted_record_ids": accepted, "local_ref_to_stable_id": mapping, "source_errors": []}
        return MemoryCommit(batch, result, signature)

    def _current_scene(self, batches: list[dict]) -> str | None:
        """依赖：已保存显式边界。输入：有序批次。输出：最后可见scene ID/未知。实现：不由run或段落推断场景。"""
        for batch in reversed(batches):
            boundary = batch.get("update", {}).get("scene_boundary")
            if boundary and batch.get("boundary_visibility", "valid") == "valid":
                return boundary["scene_id"]
        return None

    def publication_candidates(self, run: dict, draft_ref: dict, *, full=None) -> list[dict]:
        """依赖：共同读取/故事回放/Store前缀。输入：采用run、确切检查点及源快照。输出：被冻结的原始候选序列。实现：只选所选分支前缀，剥除派生可见标记，不重分配ID。"""
        snapshot = self.read_snapshot(run, through=draft_ref, full=full, include_formal=False)
        candidates = []
        for batch in snapshot["batches"]:
            draft_sources = [ref for ref in batch["source_refs"] if ref["kind"] == "draft"]
            if any(self.store.prefix_status(snapshot["run"], ref) != "valid" for ref in draft_sources):
                continue
            clone = deepcopy(batch)
            clone.pop("visibility", None)
            clone.pop("boundary_visibility", None)
            for group in ["state_changes", "unresolved_entities", *RECORD_GROUPS]:
                for write in clone["update"].get(group, []):
                    write.pop("visibility", None)
            candidates.append(clone)
        return candidates

    def map_publication(self, batches: list[dict], adopted_ref: dict) -> list[dict]:
        """依赖：已核验前缀/分型Ref字段。输入：冻结原批次和正式Ref。输出：有序映射副本。实现：只转换声明来源/位置，原指纹和自由payload不改写。"""
        mapped = deepcopy(batches)
        position = {"kind": "document", "endpoint": "after", "coordinate": adopted_ref["coordinate"]}
        for batch in mapped:
            batch["source_refs"] = [deepcopy(adopted_ref) if ref["kind"] == "draft" else ref for ref in batch["source_refs"]]
            if batch.get("draft_ref") and batch["draft_ref"]["kind"] == "draft":
                batch["draft_ref"] = deepcopy(adopted_ref)
            if batch.get("narrative_position") is not None:
                batch["narrative_position"] = deepcopy(position)
            for group in ["state_changes", "unresolved_entities", *RECORD_GROUPS]:
                for write in batch["update"].get(group, []):
                    data = write.get("entry", write) if group == "state_changes" else write.get("record", write)
                    if "source_refs" in data:
                        data["source_refs"] = [deepcopy(adopted_ref) if ref["kind"] == "draft" else ref for ref in data["source_refs"]]
                    if data.get("narrative_position") is not None:
                        data["narrative_position"] = deepcopy(position)
        return mapped

    def publication_controls(self, batches: list[dict]) -> list[dict]:
        """依赖：映射后的结构记录。输入：确切发布批次。输出：不含状态值/经历文本的失效控制索引。实现：保留影响ID和必要Link义务，失效时不把快照恢复成事实。"""
        controls = []
        for batch in batches:
            control = {key: deepcopy(batch[key]) for key in ("batch_id", "memory_revision", "source_refs", "narrative_position")}
            if batch.get("draft_ref"):
                control["draft_ref"] = deepcopy(batch["draft_ref"])
            update = {}
            for change in batch["update"].get("state_changes", []):
                data = change.get("entry", change)
                update.setdefault("state_changes", []).append({"op": "clear", "entry_id": change["entry_id"],
                    "source_refs": deepcopy(data.get("source_refs", batch["source_refs"]))})
            for group in RECORD_GROUPS:
                for write in batch["update"].get(group, []):
                    data = write.get("record", write)
                    if group == "links" and data.get("payload", {}).get("relation_type") == "required_context":
                        value = {"op": "create", "id": write["id"], "record": deepcopy(data)}
                    else:
                        value = {"op": "retire", "id": write["id"], "source_refs": deepcopy(data.get("source_refs", batch["source_refs"]))}
                    update.setdefault(group, []).append(value)
            if batch["update"].get("scene_boundary"):
                update["scene_boundary"] = deepcopy(batch["update"]["scene_boundary"])
            control["update"] = update
            controls.append(control)
        return controls
