"""一个创作循环；web/CLI共享，不调用v2 normalize/audit/repair管线。"""
from __future__ import annotations

import asyncio
from copy import deepcopy
import json
from dataclasses import asdict
from pathlib import Path
from uuid import uuid4

from ..documents import DocumentError
from ..std.serialization import json_text
from ..identity import GraphKey, StoryCoordinate
from ..model_api import ModelAPIError, ToolCall
from ..std.hashing import fingerprint_bytes
from ..retrieval.assembler import estimate_tokens
from ..service import load_story_sources
from .context import (HARNESS_INSTRUCTIONS, active_recall_selection, build_context, context_binding,
                      describe_text, result_source_refs)
from .store import StoreConflict
from .tools import ToolDispatcher
from .types import DraftRef, NarrativeCursor, RunBinding, parse_source_ref


class RunService:
    """运行调度owner；单创作槽，不把技术session当叙事场景。"""

    def __init__(self, library_root: Path, store, memory, model_config, *, adoption=None):
        """依赖：Store/Memory/原配置与采用owner。输入：装配组件及可选采用实例。输出：会话服务。实现：直接构造仍兼容，同Store仅持一个采用实例，模型密钥不进入run JSON。"""
        from ..writeback.adopt import AdoptionService

        self.root, self.store, self.memory, self.config = Path(library_root), store, memory, model_config
        self._adoption = adoption if adoption is not None else AdoptionService(self.root, store, memory)
        self._models, self._signals, self._slot = {}, {}, None

    def writer_lease(self):
        """依赖：原Store生命周期锁。输入：无。输出：原租约context manager。实现：仅委托，调用方在恢复前取得并在transport清理后释放。"""
        return self.store.writer_lease()

    def recover(self) -> list[str]:
        """依赖：原Store恢复。输入：已持工作区租约的调用方。输出：恢复的run IDs或原错误。实现：只标记遗留运行，不重发请求或另建恢复状态。"""
        return self.store.recover()

    def workspace_bootstrap(self, *, harness: bool = False) -> dict:
        """依赖：原配置owner/根身份。输入：是否外部宿主握手。输出：身份或脱敏profile选择。实现：harness分支不访问配置，工作台损坏配置仍返回能力缺口。"""
        root, workspace = self.root.resolve(), self.store.root.resolve()
        if harness:
            return {"library_root": str(root), "workspace_root": str(self.store.root)}
        error = None
        try:
            profiles = [self.config.get(name) for name in self.config.list_profiles()]
        except (ValueError, RuntimeError, OSError):
            profiles, error = [], {"code": "capability", "message": "模型配置无法读取，可使用自己的写作工具"}
        return {"workspace_id": fingerprint_bytes((str(root) + "\0" + str(workspace)).encode("utf-8")),
                "profiles": [{"name": profile.name, "model": profile.model, "mode": profile.mode} for profile in profiles],
                "model_configuration_error": error}

    def run_info(self, run_id: str) -> dict:
        """依赖：原Store热快照。输入：run ID。输出：身份/驱动/状态及可启动标志。实现：提供调度描述，run执行时仍复核真实状态，不触发记忆召回。"""
        run = self.store.snapshot(run_id, view="live")
        driver = run.get("driver", "builtin")
        return {"run_id": run_id, "session_id": run["session_id"], "status": run["status"], "driver": driver,
                "launchable": run["status"] == "queued" and driver == "builtin"}

    def run_result(self, run_id: str, *, error=None) -> dict:
        """依赖：原Store公开快照。输入：run ID及可选调用异常。输出：CLI原五字段结果。实现：仅投影运行事实，不recall；保留已存错误、稿件和终态，凭证脱敏仍由输出边界负责。"""
        run = self.store.snapshot(run_id)
        status = str(run.get("status") or ("interrupted" if error is not None else "failed"))
        failure = (run.get("error") or error) if error is not None else run.get("error")
        if failure is None and status != "completed":
            failure = {"code": status, "message": f"写作任务状态：{status}"}
        draft_ref = run.get("draft_ref")
        if hasattr(draft_ref, "as_dict"):
            draft_ref = draft_ref.as_dict()
        return {"run_id": run_id, "status": status, "draft_ref": draft_ref,
                "draft_text": run.get("draft_text", ""), "error": failure}

    def workspace_snapshot(self, run_id: str, *, view: str = "full", after: int = 0) -> dict:
        """依赖：运行视图和记忆召回。输入：run、full/live与事件游标。输出：原工作台快照或读取错误。实现：完整视图附当前记忆，热视图只读运行。"""
        result = self._workspace_run_view(run_id, view=view, after=after)
        if view == "full":
            result.update(self._workspace_memory_fields(run_id))
        return result

    def _workspace_memory_fields(self, run_id: str) -> dict:
        """依赖：MemoryService.recall。输入：run ID。输出：同次读取的记忆包和版本或原错误。实现：将包与其实际版本一起投影到工作台。"""
        packet = self.memory.recall(run_id)
        return {"memory_state": packet, "memory_revision": packet["memory_revision"]}

    def _workspace_run_view(self, run_id: str, *, view: str, after: int = 0) -> dict:
        """依赖：Store快照与目标来源。输入：run、视图和事件游标。输出：含采用坐标与来源的运行视图。实现：从绑定和正式目标推算下一场坐标。"""
        result = self.store.snapshot(run_id, view=view, after=after)
        binding = result["binding"]
        target_ref = self.store.target_source_ref(result, metadata_only=view == "live")
        coordinate = binding.get("target_coordinate") or (target_ref.get("coordinate") if target_ref else None)
        if coordinate is None and binding["narrative_cursor"].get("coordinate"):
            coordinate = dict(binding["narrative_cursor"]["coordinate"])
            coordinate["scene"] += 1
        result["suggested_coordinate"] = coordinate or {"volume": 1, "chapter": 1, "scene": 1}
        result["adoption_target_source_hash"] = target_ref["source_hash"] if target_ref else None
        result["adoption_target_coordinate"] = target_ref.get("coordinate") if target_ref else None
        return result

    def observe(self, run_id: str, *, after: int = 0, revision=None) -> dict | None:
        """依赖：原Store观察提示/live快照。输入：run、事件游标与上次提示。输出：变化后的原live/提示/终态或None。实现：未变化只stat，提示不认证来源或提交，SSE编码仍归HTTP。"""
        current = self.store.observation_revision(run_id)
        if current == revision:
            return None
        run = self.store.snapshot(run_id, view="live", after=after)
        return {"revision": current, "snapshot": run,
                "terminal": run["status"] in {"completed", "cancelled", "failed", "interrupted"}}

    def adopt_draft(self, run_id: str, draft_revision: int, expected_source_hash: str | None,
                    coordinates, operation_id: str) -> dict:
        """依赖：同Store采用owner。输入：所选修订/源CAS/坐标/原操作ID。输出：原采用回执或冲突。实现：直接委托原锁与恢复协议，不外加Store锁或把记忆发布失败改为正文失败。"""
        return self._adoption.adopt(run_id, draft_revision, expected_source_hash, coordinates, operation_id)

    def edit_document(self, scope: GraphKey, document_id: str, expected_revision: int,
                      expected_source_hash: str, content: str) -> dict:
        """依赖：原writeback编辑owner。输入：作者文档/作用域/双CAS/内容。输出：保存后实际来源或原错误。实现：共享工作区Store与源提交协议，不复制YAML或锁逻辑。"""
        from ..writeback.adopt import edit_reference

        return edit_reference(self.root, self.store, scope, document_id,
                              expected_revision, expected_source_hash, content)

    def harness_tools(self, run_id: str) -> dict:
        """依赖：唯一ToolDispatcher/宿主说明。输入：固定run ID。输出：原五工具或权限错误。实现：应用层检查harness驱动，不访问模型配置或编译全文上下文。"""
        if self.run_info(run_id)["driver"] != "harness":
            raise StoreConflict("scope_denied: 此任务使用内置模型")
        return {"tools": self.tool_dispatcher(run_id).definitions(), "instructions": HARNESS_INSTRUCTIONS}

    def start(self, scope: GraphKey, task_kind: str, outline: str, request: str,
              base_ref=None, target_coordinate=None, profile_name=None, *,
              session_id=None, parent_run_id=None, request_id=None) -> str:
        """依赖：无模型prepare/原ModelConfigStore。输入：作者任务及profile。输出：内置run ID。实现：共同准备后只为queued构造一个client，harness不经过此驱动。"""
        run_id = self.prepare(scope, task_kind, outline, request, base_ref, target_coordinate, profile_name,
                              driver="builtin", session_id=session_id, parent_run_id=parent_run_id, request_id=request_id)
        with self.store.lock:
            run = self.store.load(run_id)
            if run["status"] != "queued" or run_id in self._models:
                return run_id
            try:
                model = self.config.build_model(profile_name)
                self._models[run_id] = model
                run["model_snapshot"] = {"model": model.model, "mode": model.mode, "timeout": model.timeout,
                                         "max_output_tokens": model.max_output_tokens,
                                         "context_window_tokens": getattr(model, "context_window_tokens", None),
                                         "output_reserve_tokens": getattr(model, "output_reserve_tokens", None),
                                         "max_turns": getattr(model, "max_turns", None)}
                self.store.write(run)
            except (ValueError, RuntimeError) as exc:
                self.store.set_status(run_id, "failed", {"code": "capability", "message": str(exc)})
        return run_id

    def prepare(self, scope: GraphKey, task_kind: str, outline: str, request: str,
                base_ref=None, target_coordinate=None, profile_name=None, *, driver="harness",
                session_id=None, parent_run_id=None, request_id=None) -> str:
        """依赖：Store/共同来源绑定。输入：作者原任务、driver及稳定request ID。输出：唯一run ID或冲突。实现：同锁中固定绑定，原ID补齐未完成的准备步骤。"""
        if driver not in {"builtin", "harness"} or driver == "harness" and profile_name is not None:
            raise ValueError("source_invalid: harness使用宿主模型，driver/profile组合不合法")
        if request_id is not None and (not isinstance(request_id, str) or not 1 <= len(request_id) <= 128):
            raise ValueError("source_invalid: request_id长度不合法")
        coordinate = StoryCoordinate.from_value(target_coordinate) if target_coordinate is not None else None
        arguments = {"scope": scope.as_dict(), "task_kind": task_kind, "outline": outline, "request": request,
                     "base_ref": base_ref.as_dict() if hasattr(base_ref, "as_dict") else base_ref,
                     "target_coordinate": asdict(coordinate) if coordinate else None, "profile_name": profile_name,
                     "session_id": session_id, "parent_run_id": parent_run_id}
        if driver != "builtin":
            arguments["driver"] = driver
        signature = fingerprint_bytes(json_text(arguments).encode("utf-8"))
        with self.store.lock:
            previous = self._requested_run(scope, request_id) if request_id else None
            if previous is not None:
                if previous.get("request_arguments_hash") != signature:
                    raise StoreConflict("revision_conflict: 同请求ID参数不同")
                return self._complete_preparation(scope, previous)
            return self._prepare(scope, task_kind, outline, request, base_ref, coordinate, profile_name, driver=driver,
                               session_id=session_id, parent_run_id=parent_run_id,
                               request_id=request_id, request_arguments_hash=signature)

    def _requested_run(self, scope: GraphKey, request_id: str) -> dict | None:
        """依赖：同作品线原run快照。输入：作用域及稳定ID。输出：原运行元数据或None。实现：调用方持Store锁，查权威快照，无需展开历史产物。"""
        for path in (self.store.root / scope.story_id / scope.timeline_id / "runs").glob("*/run.json"):
            previous = json.loads(path.read_text(encoding="utf-8"))
            if previous.get("request_id") == request_id:
                return previous
        return None

    def _prepare(self, scope: GraphKey, task_kind: str, outline: str, request: str,
               base_ref=None, target_coordinate=None, profile_name=None, *, driver="harness",
               session_id=None, parent_run_id=None, request_id=None, request_arguments_hash=None) -> str:
        """依赖：公共源/RunBinding/Store。输入：原纲、driver、真实基线/坐标。输出：已保存run ID或来源错误。实现：固定scope/游标/父稿后持久化，并完成初稿和索引。"""
        if task_kind not in {"write", "revise", "discuss"} or not isinstance(outline, str) or not isinstance(request, str):
            raise ValueError("source_invalid: 任务类型/原纲/要求不合法")
        corpus = load_story_sources(self.root, scope)
        base = parse_source_ref(base_ref) if isinstance(base_ref, dict) else base_ref
        parent, cursor, mode, initial_revision = None, NarrativeCursor("after"), "full_body", 0
        if base is None:
            history = [doc for doc in corpus.documents if doc.metadata["document_type"] == "history"]
            if history:
                latest = max(history, key=lambda doc: (corpus.source_refs[doc.document_id].coordinate or StoryCoordinate(0), doc.document_id))
                base = corpus.source_refs[latest.document_id]
        if base and base.kind == "document":
            actual = corpus.source_refs.get(base.document_id)
            if actual is None or actual != base:
                raise StoreConflict("source_invalid: 正式基线版本/作用域已改变")
            cursor = NarrativeCursor("before" if task_kind == "revise" else "after", base.coordinate)
            if task_kind == "revise" and target_coordinate is None:
                target_coordinate = base.coordinate
        elif base:
            parent, _ = self.store.resolve_draft(base.as_dict())
            if parent["binding"]["scope"] != scope.as_dict():
                raise StoreConflict("scope_denied: 父稿不属于本作品线")
            cursor = NarrativeCursor(**{**parent["binding"]["narrative_cursor"],
                                        "coordinate": StoryCoordinate.from_value(parent["binding"]["narrative_cursor"]["coordinate"])
                                        if parent["binding"]["narrative_cursor"].get("coordinate") else None})
            if task_kind == "write":
                mode, initial_revision = "append_suffix", parent["memory_revision"]
            target_ref = self.store.target_source_ref(parent)
            if target_coordinate is None:
                target_coordinate = parent["binding"].get("target_coordinate") or (target_ref.get("coordinate") if target_ref else None)
            if task_kind == "revise":
                if target_coordinate is None and cursor.coordinate:
                    target_coordinate = StoryCoordinate(cursor.coordinate.volume, cursor.coordinate.chapter, cursor.coordinate.scene + 1)
                if target_coordinate is not None:
                    target_coordinate = StoryCoordinate.from_value(target_coordinate)
                    cursor = NarrativeCursor("before", target_coordinate)
        target = StoryCoordinate.from_value(target_coordinate) if target_coordinate is not None else None
        visible = corpus.at_cursor(cursor.coordinate, cursor.endpoint)
        binding = RunBinding(scope, task_kind, cursor, base, "branch-" + uuid4().hex, target,
                             base.checkpoint_id if base and base.kind == "draft" and mode == "append_suffix" else None,
                             tuple(visible.source_refs.values()), output_mode=mode, initial_memory_revision=initial_revision)
        run = self.store.create(binding, outline, request, profile_name=profile_name,
                                session_id=session_id, parent_run_id=parent_run_id or (parent["run_id"] if parent else None),
                                request_id=request_id, request_arguments_hash=request_arguments_hash, driver=driver)
        return self._complete_preparation(scope, run)

    def _complete_preparation(self, scope: GraphKey, run: dict) -> str:
        """依赖：已持久绑定/Store保存/会话索引。输入：同锁内新建或重放的run。输出：原run ID或原I/O错误。实现：仅为空且从未保存的续写分支补父稿，幂等登记索引。"""
        run_id = run["run_id"]
        if run["binding"]["output_mode"] == "append_suffix" and run["draft_revision"] == 0 and not run["drafts"]:
            self.store.save(run_id, 0, self.assemble_output(run, ""), origin="base")
        self._save_session(run["session_id"], run_id, scope)
        return run_id

    def _save_session(self, session_id: str, run_id: str, scope: GraphKey) -> None:
        """依赖：原子JSON/安全身份。输入：session/run/scope。输出：None或索引错误。实现：会话只索引run历史，已有登记直接返回。"""
        from ..identity import validate_identifier
        from ..std.atomic_io import atomic_write_json

        validate_identifier(session_id)
        path = self.store.root / scope.story_id / scope.timeline_id / "sessions" / session_id / "session.json"
        with self.store.lock:
            data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"session_id": session_id, "scope": scope.as_dict(), "run_ids": []}
            if data["scope"] != scope.as_dict():
                raise StoreConflict("scope_denied: session跨作用域")
            if run_id in data["run_ids"]:
                return
            data["run_ids"].append(run_id)
            atomic_write_json(path, data)

    def feedback(self, session_id: str, base_run_id: str, task_kind: str, request: str,
                 base_ref=None, selected_parent_checkpoint=None, *, request_id=None, driver=None, profile_name=None) -> str:
        """依赖：共同prepare/start及父稿。输入：反馈、可选父检查点及driver/profile。输出：原run ID或冲突。实现：同锁选择父稿；省略Ref的续写重放沿用原绑定。"""
        with self.store.lock:
            parent = self.store.load(base_run_id)
            if parent["session_id"] != session_id:
                raise StoreConflict("scope_denied: 父run不属于session")
            scope = GraphKey(**parent["binding"]["scope"])
            ref = base_ref or parent.get("draft_ref") or parent["binding"].get("base_ref")
            if not base_ref and isinstance(request_id, str) and request_id and task_kind == "write":
                previous = self._requested_run(scope, request_id)
                if (previous is not None and previous["parent_run_id"] == base_run_id
                        and previous["session_id"] == session_id and previous["binding"]["output_mode"] == "append_suffix"):
                    bound_parent = previous["binding"]["base_ref"]
                    if not selected_parent_checkpoint or bound_parent["checkpoint_id"] == selected_parent_checkpoint:
                        ref = bound_parent
            if selected_parent_checkpoint and (not ref or ref.get("checkpoint_id") != selected_parent_checkpoint):
                raise StoreConflict("source_invalid: 所选父检查点不匹配")
            driver = driver or parent.get("driver", "builtin")
            if driver not in {"builtin", "harness"}:
                raise ValueError("source_invalid: 未知创作驱动")
            starter = self.start if driver == "builtin" else self.prepare
            return starter(scope, task_kind, parent["request_snapshot"]["outline"], request,
                           ref, profile_name=(profile_name or parent["profile_name"]) if driver == "builtin" else None,
                           session_id=session_id, parent_run_id=base_run_id, request_id=request_id)

    def cancel(self, run_id: str) -> dict:
        """依赖：Store/真实transport信号。输入：run ID。输出：停止快照。实现：harness同锁关闭本地工具；内置等待transport清理，不声称停止宿主LLM。"""
        with self.store.lock:
            run = self.store.load(run_id)
            run["cancel_requested"] = True
            self.store.write(run)
            if run["status"] == "queued" or run.get("driver") == "harness" and run["status"] == "prepared":
                self.store.set_status(run_id, "cancelled")
                self._models.pop(run_id, None)
        if run_id in self._signals:
            self._signals[run_id].set()
        return self.store.snapshot(run_id)

    def assemble_output(self, run: dict, text: str) -> str:
        """依赖：固定output_mode/真实父DraftRef。输入：run及本轮完整输出或接收前缀。输出：目标正文全文。实现：唯一拼装点仅append_suffix加父前缀，正式前章不拼进新章。"""
        if run["binding"]["output_mode"] == "append_suffix":
            _, prefix = self.store.resolve_draft(run["binding"]["base_ref"])
            return prefix + text
        return text

    def _commit_author_draft(self, run_id: str, expected_revision: int, text: str) -> tuple[DraftRef, str]:
        """依赖：Store与assemble_output。输入：作者文本与草稿CAS。输出：本次提交的引用及全文或原错误。实现：同锁判定接收前缀、拼装完整正文并保存作者选择。"""
        with self.store.lock:
            run = self.store.load(run_id)
            received = self.store.received(run_id)
            origin = "partial" if isinstance(text, str) and text == received.get("text") and not received.get("complete") else "author"
            body = self.assemble_output(run, text) if origin == "partial" else text
            ref = self.store.save(run_id, expected_revision, body, origin=origin, protect_author=True)
            return ref, body

    def save_author_draft(self, run_id: str, expected_revision: int, text: str) -> DraftRef:
        """依赖：作者草稿提交。输入：run、草稿CAS和文本。输出：本次保存的DraftRef或原错误。实现：沿共同提交路径返回既有引用类型。"""
        ref, _ = self._commit_author_draft(run_id, expected_revision, text)
        return ref

    def save_author_draft_receipt(self, run_id: str, expected_revision: int, text: str, *, view: str = "full") -> dict:
        """依赖：作者草稿提交、运行视图与记忆。输入：run、草稿CAS、文本及full/live。输出：保存引用、确切全文和各项读取状态。实现：先提交一次，再独立读取所选视图；读取异常保留原回执。"""
        if view not in {"full", "live"}:
            raise ValueError("source_invalid: 草稿回执的view需要full或live")
        saved, body = self._commit_author_draft(run_id, expected_revision, text)
        result = {"run_id": run_id, "saved_draft_ref": saved.as_dict(),
                  "saved_draft_revision": saved.draft_revision, "saved_draft_text": body,
                  "memory_read": {"status": "not_requested"}}
        try:
            result.update(self._workspace_run_view(run_id, view=view))
        except (OSError, ValueError, RuntimeError, KeyError, TypeError):
            result["snapshot_read"] = {"status": "unavailable", "message": "草稿已保存，当前运行状态暂时无法读取。"}
        if view == "full":
            try:
                result.update(self._workspace_memory_fields(run_id))
            except (OSError, ValueError, RuntimeError, KeyError, TypeError):
                result["memory_read"] = {"status": "unavailable", "message": "记忆读取失败，可在记忆页重新读取。"}
            else:
                result["memory_read"] = {"status": "available"}
        return result

    def tool_dispatcher(self, run_id: str, *, delivery: str = "full", origin: str = "model") -> ToolDispatcher:
        """依赖：唯一ToolDispatcher/assemble_output。输入：run/交付/调用来源。输出：共同dispatcher。实现：原正文/权限共用，作者只读与模型选择分开。"""
        run = self.store.load(run_id)

        def assemble(text):
            """依赖：assemble_output。输入：完整输出。输出：目标全文。实现：按固定父引用只拼一次。"""
            return self.assemble_output(run, text)

        def select():
            """依赖：Store作者版本。输入：无。输出：是否可移动选中稿。实现：已有作者修改时生成仅另存。"""
            return self.store.load(run_id)["author_revision"] == 0

        return ToolDispatcher(self.memory, self.store, run_id, assemble, select, delivery=delivery, origin=origin)

    def harness_context(self, run_id: str, *, view: str = "full") -> dict:
        """依赖：共同context_binding/build_context/Store。输入：固定harness run及视图。输出：同份材料绑定的交接。实现：锁外编译，不把后台刷新声称为清除外部宿主历史，full导出兼容。"""
        if view not in {"full", "model"}:
            raise ValueError("source_invalid: context view需要full或model")
        run = self.store.load(run_id)
        if run.get("driver") != "harness":
            raise StoreConflict("scope_denied: 此任务使用内置模型")
        definitions = self.tool_dispatcher(run_id).definitions()
        state = context_binding(run, self.memory, self.store, definitions)
        current = state["run"]
        messages = build_context(current, self.memory, self.store, definitions, view=view, context_state=state)
        operations = list(current["tool_commits"])[-32:]
        result = {"run_id": run_id, "driver": "harness", "status": current["status"], "messages": messages,
                  "instructions": HARNESS_INSTRUCTIONS, "tools": definitions, "draft_revision": current["draft_revision"],
                  "memory_revision": current["memory_revision"], "draft_ref": current["draft_ref"],
                  "saved_draft": {"draft_ref": current["draft_ref"], "text": current["draft_text"]},
                  "cancel_requested": current["cancel_requested"], "operation_count": len(current["tool_commits"]),
                  "committed_operations": {key: current["tool_commits"][key] for key in operations},
                  "context_view": view, "context_version": 3 if view == "model" else 2}
        if view == "model":
            result.pop("tools")
            result["tool_names"] = [definition["name"] for definition in definitions]
            result["material_binding"] = state["manifest"]
            result["material_binding_hash"] = state["signature"]
            result["host_history_control"] = "external_host"
            result["refresh_note"] = "这是本次材料快照；外部宿主需重新读取并管理自己的历史，资源刷新不证明旧窗口已清除。"
            result["saved_draft"] = describe_text(current["draft_text"] if current["draft_ref"] else None,
                                                 source_ref=current["draft_ref"], kind="saved_draft",
                                                 read_arguments={"source_ref": current["draft_ref"]} if current["draft_ref"] else {})
            result["saved_draft"]["inline"] = False
            result["committed_operations"] = {key: {"arguments_hash": current["tool_commits"][key]["arguments_hash"]} for key in operations}
        return result

    def execute_tool(self, run_id: str, call: ToolCall, *, delivery: str = "full", attempt_id: str | None = None,
                     provider_call_id: str | None = None, turn_id: str | None = None, origin: str = "model") -> dict:
        """依赖：共同dispatcher/原行与提交表。输入：run/调用/协议绑定及来源。输出：原回执/页。实现：作者仅recall并隔离模型事件和选择，冻结进度仍在原行，原提交身份保持。"""
        if origin not in {"model", "author_browse"} or origin == "author_browse" and call.name != "recall":
            raise ValueError("scope_denied: 作者入口仅提供记忆浏览")
        if attempt_id is not None and call.call_id != self.store.invocation_key(attempt_id, provider_call_id):
            raise StoreConflict("revision_conflict: 内部调用键与原attempt不符")
        with self.store.lock:
            previous = next((row for row in self.store.load(run_id).get("tool_results", [])
                             if row["call_id"] == call.call_id), None)
            if previous is not None and (previous.get("arguments", call.arguments) != call.arguments or previous["name"] != call.name):
                raise StoreConflict("revision_conflict: 同内部调用键参数或工具不同")
            if origin == "model":
                self.store.event(run_id, "tool_started", {"name": call.name, "call_id": call.call_id,
                                                         "provider_call_id": provider_call_id, "attempt_id": attempt_id})
            dispatcher = self.tool_dispatcher(run_id, delivery=delivery, origin=origin)
        result = dispatcher.execute(call)
        if call.name in {"save_draft", "remember"} and result.get("ok") is False:
            error = result.get("error", {}).get("code")
            if error not in {"source_invalid", "revision_conflict", "scope_denied", "cancelled", "snapshot_stale"}:
                committed = dispatcher.committed_result(call)
                if committed is None:
                    raise StoreConflict("outcome_unknown: 原写结果无法确认，保留原调用身份与参数，不重放新意图")
                result = committed
        with self.store.lock:
            current = self.store.load(run_id)
            rows = current.setdefault("tool_results", [])
            row = next((item for item in rows if item["call_id"] == call.call_id), None)
            if row is not None and (row.get("arguments", call.arguments) != call.arguments or row["name"] != call.name):
                raise StoreConflict("revision_conflict: 同内部调用键参数或工具不同")
            record = {"call_id": call.call_id, "invocation_key": call.call_id, "name": call.name,
                      "arguments": deepcopy(call.arguments), "result": result}
            if origin == "author_browse":
                record["origin"] = origin
            if dispatcher.candidate_search_state is not None:
                record["candidate_search_state"] = dispatcher.candidate_search_state
            if attempt_id is not None:
                record.update(attempt_id=attempt_id, provider_call_id=provider_call_id, turn_id=turn_id)
            if row is None:
                rows.append(record)
            else:
                row.update(record)
            self.store.write(current)
            if origin == "model":
                self.store.event(run_id, "tool_finished", {"name": call.name, "call_id": call.call_id, "ok": result.get("ok", True)})
            delivered = dispatcher.deliver_result(call, result)
            current = self.store.load(run_id)
            next(item for item in current["tool_results"] if item["call_id"] == call.call_id)["delivered_result"] = delivered
            self.store.write(current)
            return delivered

    def browse_memory(self, run_id: str, arguments: dict) -> dict:
        """依赖：共同工具执行/作者origin。输入：run及query或原候选参数。输出：带run归属的完整记忆包。实现：冻结原回执供续查，不写模型事件/焦点，不受模型终态停止门。"""
        if not isinstance(arguments, dict) or set(arguments) - {"query", "continuation"}:
            raise ValueError("source_invalid: 作者浏览只接受query或continuation")
        call = ToolCall("browse:" + uuid4().hex, "recall", arguments)
        return {"run_id": run_id, "origin": "author_browse",
                "packet": self.execute_tool(run_id, call, origin="author_browse")}

    def _renewal_reason(self, previous: dict, current: dict) -> str | None:
        """依赖：同次编译材料清单。输入：上次预期绑定与当前实际绑定。输出：重建原因或None。实现：逐字段与原Ref效力比较，新增读材料不冒充旧材料失效。"""
        for key in previous.keys() | current.keys():
            if key != "materials" and previous.get(key) != current.get(key):
                return key
        statuses = {json_text(item["source_ref"]): item["status"] for item in current["materials"]}
        for item in previous["materials"]:
            if statuses.get(json_text(item["source_ref"])) != item["status"]:
                return "material_effect"
        return None

    def _advance_material_binding(self, previous: dict, call: ToolCall, result: dict) -> dict:
        """依赖：真实工具回执/共同选择派生。输入：预期绑定、原调用及完整结果。输出：仅按已知自身效果推进的绑定。实现：不采样作者修改或外部来源，保留旧Ref效力待下轮核验。"""
        expected = deepcopy(previous)
        if result.get("ok") is False:
            return expected
        if call.name == "save_draft" and result.get("kind") == "draft" and previous["author_revision"] == 0:
            if call.arguments["expected_revision"] == previous["draft_revision"]:
                expected.update(draft_ref=result, draft_revision=result["draft_revision"])
        elif call.name == "remember" and call.arguments["expected_memory_revision"] == previous["memory_revision"]:
            expected["memory_revision"] = result["memory_revision"]
        elif call.name == "recall" and "focus" in call.arguments and "continuation" not in call.arguments:
            selection = active_recall_selection({"tool_results": [{"name": "recall", "arguments": call.arguments,
                                                                   "result": result, "invocation_key": call.call_id}]})
            expected.update(selection=selection, focus=selection["focus"] if selection else [],
                            query=selection["query"] if selection else "")
        for ref in result_source_refs(result):
            if not any(item["source_ref"] == ref for item in expected["materials"]):
                expected["materials"].append({"source_ref": ref, "status": "future" if result.get("kind") == "edit_reference" else "valid"})
        return expected

    def _request_manifest(self, model, messages: list[dict], definitions: list[dict]) -> dict:
        """依赖：模型公开计量入口/既有token估算。输入：本次消息与五工具。输出：无正文凭证发送统计。实现：真实codec记录逻辑请求，未知适配器仅标本地视图和能力未知。"""
        if hasattr(model, "request_manifest"):
            return model.request_manifest(messages, definitions, {})
        text = json_text({"messages": messages, "tools": definitions})
        return {"mode": getattr(model, "mode", "unknown"), "logical_json_bytes": None,
                "local_view_bytes": len(text.encode("utf-8")), "estimated_tokens": estimate_tokens(text),
                "context_fits": None, "context_window_tokens": None, "output_reserve_tokens": None,
                "provider_request_observation": "unavailable"}

    def harness_tool(self, run_id: str, name: str, arguments: dict, operation_id: str | None = None, *, delivery: str = "full") -> dict:
        """依赖：dispatcher/原提交表。输入：固定run/工具/操作ID/交付视图。输出：实际回执或页。实现：交付不改变幂等参数，副作用保持原CAS与锁顺序。"""
        if delivery not in {"full", "model"}:
            raise ValueError("source_invalid: delivery需要full或model")
        if not isinstance(name, str) or not isinstance(arguments, dict):
            raise ValueError("source_invalid: 工具名称/参数形状不合法")
        if name in {"save_draft", "remember"} and (not isinstance(operation_id, str) or not 1 <= len(operation_id) <= 128):
            raise ValueError("source_invalid: 写工具需要1–128字符稳定operation_id")
        if operation_id is not None and (not isinstance(operation_id, str) or not 1 <= len(operation_id) <= 128):
            raise ValueError("source_invalid: operation_id类型/长度不合法")
        call_id = "harness:" + name + ":" + (operation_id or uuid4().hex)
        with self.store.lock:
            run = self.store.load(run_id)
            if run.get("driver") != "harness":
                raise StoreConflict("scope_denied: 此任务使用内置模型")
            dispatcher = self.tool_dispatcher(run_id)
            previous = dispatcher.committed_result(ToolCall(call_id, name, arguments))
            if previous is not None:
                return previous
            if run["status"] != "prepared" or run["cancel_requested"]:
                return {"ok": False, "error": {"code": "cancelled", "message": "本地工具已结束；可读取原检查点和提交结果"}}
        return self.execute_tool(run_id, ToolCall(call_id, name, arguments), delivery=delivery)

    def finish_harness(self, run_id: str, status: str = "completed", discussion_text: str | None = None) -> dict:
        """依赖：Store技术生命周期。输入：host结束状态及可选讨论文本。输出：安全快照。实现：同锁结束工具入口，EOF不调用；不审核正文或替宿主保存未提交聊天。"""
        if status not in {"completed", "interrupted", "cancelled"} or discussion_text is not None and not isinstance(discussion_text, str):
            raise ValueError("source_invalid: 外部结束参数不合法")
        with self.store.lock:
            run = self.store.load(run_id)
            if run.get("driver") != "harness":
                raise StoreConflict("scope_denied: 此任务使用内置模型")
            if run["status"] == status:
                if discussion_text is not None and discussion_text != run.get("discussion_text"):
                    raise StoreConflict("revision_conflict: 已完成讨论不可用不同文本重放")
                return self.store.snapshot(run_id)
            if run["status"] != "prepared":
                raise StoreConflict("revision_conflict: 此任务已经结束")
            if run["binding"]["task_kind"] == "discuss":
                if discussion_text is not None:
                    run["discussion_text"] = discussion_text
                    self.store.write(run)
            elif discussion_text is not None:
                raise ValueError("source_invalid: 正文请用save_draft明确保存")
            elif status == "completed" and not any(item["origin"] != "base" for item in run["drafts"].values()):
                raise ValueError("source_invalid: 完成前请明确保存正文检查点")
            self.store.set_status(run_id, status)
            return self.store.snapshot(run_id)

    async def run(self, run_id: str) -> dict:
        """依赖：单槽/共同编译/原ModelClient与Store。输入：内置run。输出：最终安全快照。实现：发送前校验、完整工具边界安全重建，保留原提交及作者保护，无固定16轮限制。"""
        if self.store.load(run_id).get("driver", "builtin") != "builtin":
            raise ValueError("scope_denied: harness任务由宿主模型驱动")
        if self._slot is None:
            self._slot = asyncio.Lock()
        async with self._slot:
            run = self.store.load(run_id)
            if run["status"] != "queued":
                return self.store.snapshot(run_id)
            signal = self._signals[run_id] = asyncio.Event()
            if run["cancel_requested"]:
                signal.set()
            self.store.set_status(run_id, "running")
            def assemble(text):
                """依赖：固定父前缀/output_mode。输入：本run完整输出。输出：目标全文。实现：只有此处拼一次，正式前章只作上下文。"""
                return self.assemble_output(run, text)

            def can_select():
                """依赖：作者revision。输入：无。输出：是否可移动当前稿。实现：作者编辑后旧生成只能另存，不覆盖作者指针。"""
                return self.store.load(run_id)["author_revision"] == 0

            dispatcher = self.tool_dispatcher(run_id)
            definitions = dispatcher.definitions()
            try:
                model = self._models[run_id]
                messages, attempt_results, expected = [], [], None
                attempt_id, turn_count = None, 0
                while True:
                    if signal.is_set() or self.store.load(run_id)["cancel_requested"]:
                        raise asyncio.CancelledError()
                    maximum = getattr(model, "max_turns", None)
                    if maximum is not None and turn_count >= maximum:
                        self.store.set_status(run_id, "interrupted", {"code": "run_limit", "message": "已达显式模型turn限制，原输入与公开产物已保留"})
                        break
                    state = await asyncio.to_thread(context_binding, self.store.load(run_id), self.memory,
                                                    self.store, definitions, delivered_results=attempt_results)
                    reason = "initial" if expected is None else self._renewal_reason(expected, state["manifest"])
                    if reason is not None:
                        if attempt_results:
                            state = await asyncio.to_thread(context_binding, self.store.load(run_id), self.memory,
                                                            self.store, definitions)
                        attempt_id = "attempt-" + uuid4().hex
                        messages = build_context(state["run"], self.memory, self.store, definitions,
                                                 view="model", context_state=state)
                        expected = deepcopy(state["manifest"])
                        attempt_results = [{"source_refs": deepcopy(state["material_refs"])}]
                    request_manifest = self._request_manifest(model, messages, definitions)
                    if request_manifest.get("context_fits") is False:
                        if reason is None:
                            state = await asyncio.to_thread(context_binding, self.store.load(run_id), self.memory,
                                                            self.store, definitions)
                            attempt_id, reason = "attempt-" + uuid4().hex, "window"
                            messages = build_context(state["run"], self.memory, self.store, definitions,
                                                     view="model", context_state=state)
                            expected = deepcopy(state["manifest"])
                            attempt_results = [{"source_refs": deepcopy(state["material_refs"])}]
                            request_manifest = self._request_manifest(model, messages, definitions)
                        if request_manifest.get("context_fits") is False:
                            raise ModelAPIError("context_limit: 安全重建后必要材料仍超过显式窗口与输出预留，原输入已保留")
                    turn_id, buffer = "turn-" + uuid4().hex, ""
                    request_manifest.update(assembly_version=3, attempt_reason=reason or "keep",
                                            material_binding=deepcopy(state["manifest"]),
                                            message_count=len(messages), context_view="model")
                    await asyncio.to_thread(self.store.prepare_turn, run_id, turn_id, attempt_id, request_manifest)

                    async def on_delta(text):
                        """依赖：固定run/turn及Store。输入：公开文本增量。输出：None。实现：受shield保存后才发布事件，取消等待已开始保存结束，不进入其它run。"""
                        nonlocal buffer
                        buffer += text
                        saving = asyncio.create_task(asyncio.to_thread(self.store.receive, run_id, turn_id, buffer))
                        try:
                            await asyncio.shield(saving)
                        except asyncio.CancelledError:
                            await saving
                            raise

                    turn = await model.complete_turn(messages, definitions, {}, signal, on_delta)
                    await asyncio.to_thread(self.store.commit_turn, run_id, turn_id, turn.as_dict())
                    turn_count += 1
                    if signal.is_set():
                        raise asyncio.CancelledError()
                    if turn.finish_reason == "length":
                        self.store.set_status(run_id, "interrupted", {"code": "context_limit", "message": "模型输出截断，公开文本已保留，可明确保存/继续"})
                        break
                    if turn.tool_calls:
                        if len({call.call_id for call in turn.tool_calls}) != len(turn.tool_calls):
                            raise ModelAPIError("model_protocol: 同turn有重复provider调用ID，不执行歧义工具组")
                        results = []
                        for provider_call in turn.tool_calls:
                            if signal.is_set():
                                raise asyncio.CancelledError()
                            call = ToolCall(self.store.invocation_key(attempt_id, provider_call.call_id),
                                            provider_call.name, provider_call.arguments)
                            result = await asyncio.to_thread(self.execute_tool, run_id, call, delivery="model",
                                                             attempt_id=attempt_id, provider_call_id=provider_call.call_id,
                                                             turn_id=turn_id)
                            raw = next(row["result"] for row in self.store.load(run_id)["tool_results"]
                                       if row["call_id"] == call.call_id)
                            expected = self._advance_material_binding(expected, call, raw)
                            attempt_results.extend([raw, result])
                            results.append({"call_id": provider_call.call_id, "result": result})
                        messages = model.followup_messages(messages, turn, results)
                        continue
                    if not turn.text:
                        raise ModelAPIError("model_protocol: 响应没有可保存的公开正文或讨论，原继续项不当正文")
                    with self.store.lock:
                        current = self.store.load(run_id)
                        if run["binding"]["task_kind"] == "discuss":
                            current["discussion_text"] = turn.text
                            self.store.write(current)
                        else:
                            self.store.save(run_id, current["draft_revision"], assemble(turn.text), origin="model", select=can_select())
                    self.store.set_status(run_id, "completed")
                    break
            except asyncio.CancelledError:
                self.store.set_status(run_id, "cancelled")
            except (ModelAPIError, DocumentError, StoreConflict, ValueError, OSError, KeyError) as exc:
                text = str(exc)
                code = "save_failed" if isinstance(exc, OSError) else text.split(":", 1)[0]
                if code not in {"capability", "scope_denied", "revision_conflict", "model_network", "model_protocol", "context_limit", "source_invalid", "save_failed", "outcome_unknown"}:
                    code = "source_invalid"
                self.store.set_status(run_id, "interrupted" if code in {"context_limit", "outcome_unknown"} else "failed",
                                      {"code": code, "message": text})
            finally:
                self._models.pop(run_id, None)
                self._signals.pop(run_id, None)
            return self.store.snapshot(run_id)
