"""模型只见五个工具；定义/handler 唯一登记，不开放采用、凭证或任意文件。"""
from __future__ import annotations

import json
from pathlib import Path

from ..documents import DocumentError
from ..std.serialization import json_text
from ..memory.schema import draft_reference_schema, memory_update_guidance, remember_update_schema, validate_source_refs
from ..mutations.types import MutationLockError
from ..std.hashing import fingerprint_bytes
from ..onboarding import read_author_preferences_text
from .store import StoreConflict


_CONTEXT_SLOT_KEYS = {"turn_text": "turn_id", "tool_receipt": "invocation_key"}


def _document_page(text: str, arguments: dict, selector: dict, default_window: int | None) -> dict:
    """依赖：text_page 和文本指纹。输入：已授权原文、段落/字符范围、确切来源和默认窗口。输出：文本页及下一页参数或版本/范围错误。实现：校验全文指纹，按段落取范围后沿同一来源分页。"""
    from .context import text_page

    content_hash = fingerprint_bytes(text.encode("utf-8"))
    if "expected_content_hash" in arguments and arguments["expected_content_hash"] != content_hash:
        raise ValueError("revision_conflict: 读取文本已改变，不能拼接旧页")
    paragraphs = text.split("\n\n")
    first = arguments.get("start_paragraph", 1)
    last = arguments.get("end_paragraph", len(paragraphs))
    if type(first) is not int or type(last) is not int or not 1 <= first <= last <= len(paragraphs):
        raise ValueError("source_invalid: 段落范围不合法")
    maximum = arguments.get("max_characters", default_window)
    page = text_page("\n\n".join(paragraphs[first - 1:last]),
                     start_character=arguments.get("start_character", 0), max_characters=maximum)
    next_start = page.pop("next_start_character")
    next_arguments = None
    if next_start is not None:
        next_arguments = {**selector, "expected_content_hash": content_hash, "start_character": next_start,
                          "max_characters": maximum, "start_paragraph": first, "end_paragraph": last}
    return {**page, "content_hash": content_hash, "source_total_characters": len(text),
            "paragraph_range": [first, last], "next_arguments": next_arguments}


def writing_resources() -> dict:
    """依赖：包内写法及独立来源记录。输入：无。输出：资源ID映射。实现：只读实际片段/核实的结构摘要，各自保留来源，不载完整runtime或原书。"""
    return json.loads(Path(__file__).with_name("resources.json").read_text(encoding="utf-8"))


class ToolDispatcher:
    """所有权限来自run绑定；模型参数不能改scope。"""

    def __init__(self, memory, store, run_id: str, assemble, select, *, delivery: str = "full", origin: str = "model"):
        """依赖：MemoryService/Store/唯一schema。输入：run/回调/交付与来源。输出：dispatcher。实现：作者路径仅recall，复用冻结验证，模型五工具及停止门保持。"""
        if delivery not in {"full", "model"}:
            raise ValueError("source_invalid: delivery需要full或model")
        self.memory, self.store, self.run_id, self.assemble, self.select = memory, store, run_id, assemble, select
        self.delivery = delivery
        if origin not in {"model", "author_browse"}:
            raise ValueError("scope_denied: 工具调用来源不合法")
        self.origin = origin
        self.candidate_search_state = None
        self.registry = {
            "recall": ("读取完整记录/必要依赖语义包。无focus可发现线索候选，selection_reasons标明未确认对应，保持原性质/来源；非空focus替换持续焦点，省略query清旧话题，focus=[]清空；省略focus临时检索。next_arguments只续读同一冻结语义/JSON包；candidate_search.next_arguments继续查未访问候选，每次至多64个，不改变持续focus/Q。原样复制对应入口，来源或记忆变化后重查；不把候选当唯一匹配或全图已穷尽。",
                       {"focus": {"type": "array", "items": {"type": "string"}}, "query": {"type": "string"},
                        "page_characters": {"type": "integer", "minimum": 1},
                        "continuation": {"type": "object", "description": "原样复制next_arguments.continuation或candidate_search.next_arguments.continuation；前者读原包，后者查新候选，不猜调用ID/hash/起点。"}}, [], self._recall),
            "read_document": ("读实际原文/当前作者输入/选中稿或合法父稿。document_id/source_ref/context_slot三选一；模型默认字符分页，沿next_arguments读同一Ref。旧document_id可用段落范围。edit_reference不是章前人物知识。",
                              {"document_id": {"type": "string"}, "source_ref": {"type": "object", "description": "原样复制当前上下文/已返回的完整DocumentRef、DraftRef或本run AuthorInputRef。"},
                               "context_slot": {"type": "string", "enum": ["author_preferences", *_CONTEXT_SLOT_KEYS]},
                               "turn_id": {"type": "string", "description": "context_slot=turn_text时原样使用技术过程turn_id；不读取隐藏推理。"},
                               "invocation_key": {"type": "string", "description": "context_slot=tool_receipt时原样使用原内部键；技术回执不是剧情事实。"},
                               "expected_content_hash": {"type": "string"}, "start_character": {"type": "integer", "minimum": 0},
                               "max_characters": {"type": "integer", "minimum": 1},
                               "start_paragraph": {"type": "integer", "minimum": 1}, "end_paragraph": {"type": "integer", "minimum": 1}}, [], self._read_document),
            "read_writing_reference": ("按写作困难读有出处的写法/范例；不是本书剧情事实。",
                                       {"resource_id": {"type": "string", "enum": list(writing_resources())}}, ["resource_id"], self._read_reference),
            "save_draft": ("保存本run截至此时完整输出：full_body完整稿，append_suffix完整新后缀；取得真实DraftRef后可记忆。",
                           {"text": {"type": "string"}, "expected_revision": {"type": "integer", "minimum": 0}}, ["text", "expected_revision"], self._save),
            "remember": ("可选记录有来源的一批变化。state_changes用set/clear；CharacterView信息可带channel/source/certainty/basis，内容与获知检查点分开，群体/在场不自动知情。event_lines/experiences/hooks/notes/links新建create用local_ref，update/retire用实际ref。无正文仅可记作者计划/笔记；连续操作示例、可写字段与重试规则见update声明。",
                         {"draft_ref": draft_reference_schema(), "expected_memory_revision": {"type": "integer", "minimum": 0}, "update": remember_update_schema()}, ["expected_memory_revision", "update"], self._remember),
        }

    def definitions(self) -> list[dict]:
        """依赖：唯一registry。输入：无。输出：公共原生工具定义。实现：schema和handler同源，host校验结构/来源/范围，人物摄取等正文语义仍由创作LLM声明。"""
        return [{"name": name, "description": entry[0], "strict": False,
                 "parameters": {"type": "object", "properties": entry[1], "required": entry[2], "additionalProperties": False}}
                for name, entry in self.registry.items()]

    def execute(self, call) -> dict:
        """依赖：registry/Store及记忆源锁。输入：完整ToolCall。输出：结果/结构错误。实现：remember由MemoryService按源→Store锁提交，其余副作用保持Store同锁停止判定。"""
        if call.name == "remember":
            return self._execute_locked(call)
        with self.store.lock:
            return self._execute_locked(call)

    def committed_result(self, call) -> dict | None:
        """依赖：MemoryService唯一参数/Store提交表。输入：ToolCall。输出：已提交结果或None/冲突。实现：查询使用真正提交时的默认值，不把省略稿源误判改参。"""
        arguments = self.memory.remember_arguments(**call.arguments) if call.name == "remember" else call.arguments
        return self.store.committed_tool(self.run_id, call.call_id, arguments)

    def _execute_locked(self, call) -> dict:
        """依赖：registry/提交锁/共同错误指引。输入：ToolCall。输出：回执或拒绝。实现：作者仅可读recall且不受模型停止门；原模型CAS/停止/幂等保持。"""
        try:
            if self.origin == "author_browse" and (call.name != "recall" or set(call.arguments) - {"query", "continuation"}):
                raise ValueError("scope_denied: 作者浏览仅接受recall查询或原候选入口")
            if call.name not in self.registry:
                raise ValueError("scope_denied: 未提供的工具")
            spec = self.registry[call.name]
            if not isinstance(call.arguments, dict) or set(call.arguments) - set(spec[1]) or any(key not in call.arguments for key in spec[2]):
                raise ValueError("source_invalid: 工具参数缺失或超出合同")
            types = {"string": str, "integer": int, "array": list, "object": dict, "null": type(None)}
            for key, value in call.arguments.items():
                schema = spec[1][key]
                allowed = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
                if type(value) not in [types[item] for item in allowed]:
                    raise ValueError(f"source_invalid: {key}类型不合法")
                if "minimum" in schema and value < schema["minimum"] or "enum" in schema and value not in schema["enum"]:
                    raise ValueError(f"source_invalid: {key}超出允许范围")
                if schema.get("items", {}).get("type") == "string" and any(not isinstance(item, str) for item in value):
                    raise ValueError(f"source_invalid: {key}需要字符串列表")
            previous = self.committed_result(call)
            if previous is not None:
                return previous
            run = self.store.load(self.run_id)
            if self.origin != "author_browse" and (run["cancel_requested"] or call.name in {"save_draft", "remember"} and run["status"] in {"completed", "cancelled", "failed", "interrupted"}):
                raise ValueError("cancelled: 已请求停止，不开始新工具副作用")
            return spec[3](call.arguments, call.call_id)
        except (DocumentError, StoreConflict, MutationLockError, ValueError, KeyError, TypeError, OSError) as exc:
            message = ("source_invalid: 缺少结构字段 " + str(exc.args[0]) + "，请按工具声明的嵌套结构传入"
                       if isinstance(exc, KeyError) else "source_invalid: " + str(exc) if isinstance(exc, MutationLockError) else str(exc))
            error = {"code": message.split(":", 1)[0], "message": message}
            if call.name == "remember" and error["code"] == "source_invalid":
                details = memory_update_guidance(call.arguments.get("update") if isinstance(call.arguments, dict) else None, message)
                if details["issues"] or details["operations"]:
                    error["details"] = details
            return {"ok": False, "error": error,
                    "memory_revision": self.store.load(self.run_id)["memory_revision"]}

    def _recall(self, arguments: dict, call_id: str) -> dict:
        """依赖：MemoryService/原工具行/共同交付。输入：查询或原cursor。输出：新包/冻结页或拒绝。实现：同origin原行/hash/来源校验，作者全可见浏览与模型选择隔离。"""
        if "continuation" in arguments:
            from .context import MODEL_PAGE_CHARACTERS, json_result_page, semantic_result_page

            cursor = arguments["continuation"]
            semantic = cursor.get("kind") == "semantic"
            candidates = cursor.get("kind") == "candidates"
            expected = ({"kind", "call_id", "content_hash"} if candidates else
                        {"kind", "call_id", "content_hash", "projection_version", "index"} if semantic else {"call_id", "content_hash", "start_character"})
            if set(arguments) - {"continuation", "page_characters"} or set(cursor) != expected:
                raise ValueError("source_invalid: recall续读参数不合法")
            if (type(cursor["call_id"]) is not str or type(cursor["content_hash"]) is not str or
                    not candidates and type(cursor["index" if semantic else "start_character"]) is not int):
                raise ValueError("source_invalid: recall续读字段类型错误")
            if semantic and (type(cursor["projection_version"]) is not int or cursor["projection_version"] != 1):
                raise ValueError("source_invalid: continuation.projection_version不支持；使用原JSON入口或重新查询")
            snapshot = self.memory.current_snapshot(self.run_id)
            run = snapshot["run"]
            matches = [row for row in run.get("tool_results", []) if row.get("invocation_key", row.get("call_id")) == cursor["call_id"] and row["name"] == "recall"
                       and row.get("origin", "model") == self.origin]
            if len(matches) != 1 or matches[0]["result"].get("delivery") or matches[0]["result"].get("ok") is False:
                raise ValueError("scope_denied: 本run没有该完整recall结果")
            result = matches[0]["result"]
            if fingerprint_bytes(json_text(result).encode("utf-8")) != cursor["content_hash"]:
                raise ValueError("source_invalid: recall冻结结果hash不匹配")
            if result["memory_revision"] != run["memory_revision"]:
                raise ValueError("snapshot_stale: 原recall来源效力或记忆已改变，请发起新查询")
            from .context import result_source_refs

            references = result_source_refs(result)
            if references and self.memory.source_refs_status(references, run, snapshot["corpus"], snapshot["full"]) != "valid":
                raise ValueError("snapshot_stale: 原recall查询来源已改变或不可见，请发起新查询")
            if candidates:
                state = matches[0].get("candidate_search_state")
                progress = result.get("candidate_search", {})
                if not isinstance(state, dict) or progress.get("state_hash") != fingerprint_bytes(json_text(state).encode("utf-8")):
                    raise ValueError("source_invalid: 原候选进度缺失或hash不符，请重新recall")
                if progress.get("complete"):
                    raise ValueError("source_invalid: 本次候选frontier已读完，没有下一批")
                packet = self.memory.recall(self.run_id, focus=state["request_focus"], query=state["query"], snapshot=snapshot,
                                            candidate_search=state, with_candidate_state=True, browse_all=self.origin == "author_browse")
                self.candidate_search_state = packet.pop("_candidate_search_state", None)
                return packet
            if semantic:
                return semantic_result_page(result, cursor["call_id"], index=cursor["index"],
                                            page_characters=arguments.get("page_characters", MODEL_PAGE_CHARACTERS))
            return json_result_page(result, cursor["call_id"], start_character=cursor["start_character"],
                                    page_characters=arguments.get("page_characters", MODEL_PAGE_CHARACTERS))
        packet = self.memory.recall(self.run_id, focus=arguments.get("focus", []), query=arguments.get("query", ""),
                                    with_candidate_state=True, browse_all=self.origin == "author_browse")
        self.candidate_search_state = packet.pop("_candidate_search_state", None)
        return packet

    def deliver_result(self, call, result: dict) -> dict:
        """依赖：原结果/共同语义、JSON与候选导航。输入：调用/完整结果。输出：交付页或full包。实现：候选入口与交付页入口分开，内部frontier不交付，原包保持冻结。"""
        from .context import MODEL_PAGE_CHARACTERS, candidate_search_navigation, json_result_page, semantic_result_page

        if call.name != "recall" or result.get("delivery") or result.get("ok") is False:
            return result
        page_chars = call.arguments.get("page_characters")
        if page_chars is None and self.delivery == "model":
            return semantic_result_page(result, call.call_id)
        if page_chars is None:
            return dict(result, candidate_search=candidate_search_navigation(result, call.call_id)) if "candidate_search" in result else result
        return json_result_page(result, call.call_id, page_characters=page_chars or MODEL_PAGE_CHARACTERS)

    def _read_document(self, arguments: dict, call_id: str) -> dict:
        """依赖：来源合同、Store、作品资料和文本分页。输入：三选一的来源与范围。输出：含用途、引用及续页入口的正文或错误。实现：按来源检查权限，确切读取身份直接沿用于续页。"""
        from .context import MODEL_PAGE_CHARACTERS, technical_tool_receipt
        from ..graph.builder import normalize_entities

        if sum(key in arguments for key in ("document_id", "source_ref", "context_slot")) != 1:
            raise ValueError("source_invalid: document_id/source_ref/context_slot需要三选一")
        slot = arguments.get("context_slot")
        selector = {"context_slot": slot} if slot is not None else {}
        for context_slot, key in _CONTEXT_SLOT_KEYS.items():
            if key in arguments:
                if slot != context_slot:
                    raise ValueError(f"source_invalid: {key}仅用于context_slot={context_slot}")
                selector[key] = arguments[key]
        run = self.store.load(self.run_id)
        reference = arguments.get("source_ref")
        if reference is not None and validate_source_refs([reference]):
            raise ValueError("source_invalid: 读取引用不合法")
        kind, entity_refs = "original", []
        if slot is not None:
            key = _CONTEXT_SLOT_KEYS.get(slot)
            if key and not selector.get(key):
                raise ValueError(f"source_invalid: context_slot={slot}需要{key}")
            if slot == "tool_receipt":
                text = json_text(technical_tool_receipt(run, arguments["invocation_key"], store=self.store))
                kind = "technical_receipt"
            elif slot == "turn_text":
                text = self.store.public_turn_text(self.run_id, arguments["turn_id"])
                kind = "technical_turn"
            else:
                text = read_author_preferences_text(self.memory.root, run["binding"]["scope"]["story_id"])
                kind = "author_preferences"
        elif reference and reference["kind"] == "author_input":
            if reference not in run["binding"]["input_snapshot_refs"]:
                raise ValueError("scope_denied: 仅能读取本run已提供的作者输入")
            text, kind = self.store.input_text(reference), "author_input"
        elif reference and reference["kind"] == "draft":
            text, kind = self._read_draft(run, reference)
        else:
            corpus = self.memory.corpus(run)
            document_id = reference["document_id"] if reference else arguments["document_id"]
            base = run["binding"].get("base_ref")
            if document_id not in corpus.source_refs and run["binding"]["task_kind"] == "revise" and base and base.get("document_id") == document_id:
                corpus, kind = self.memory.corpus(run, full=True), "edit_reference"
            document, ref = corpus.read(document_id)
            actual = ref.as_dict()
            if reference is not None and actual != reference:
                raise ValueError("revision_conflict: 原文引用版本已改变，请显式读取新来源")
            reference = actual
            text = document.body.get("content") if isinstance(document.body, dict) else None
            text = text if isinstance(text, str) else document.searchable_text()
            entity_refs = normalize_entities(document.metadata)
        if reference is not None:
            selector = {"source_ref": reference}
        window = MODEL_PAGE_CHARACTERS if self.delivery == "model" else None
        return {"source_ref": reference, "entity_refs": entity_refs, "kind": kind,
                **_document_page(text, arguments, selector, window)}

    def _read_draft(self, run: dict, reference: dict) -> tuple[str, str]:
        """依赖：Store 的父稿快照、检查点及前缀校验。输入：当前 run 和草稿引用。输出：原文和用途或范围错误。实现：沿所选父链核修订上界，再从已定位的运行校验并读取正文。"""
        current, ceiling, seen = run, run["draft_revision"], set()
        scope = run["binding"]["scope"]
        while current["run_id"] not in seen and current["binding"]["scope"] == scope:
            if "draft-" + current["run_id"] == reference["draft_document_id"]:
                if reference["draft_revision"] > ceiling:
                    break
                owner, text = self.store.resolve_draft(reference, run=current)
                if owner["binding"]["scope"] != scope:
                    raise ValueError("scope_denied: 草稿不属于本作品线")
                if run["binding"]["task_kind"] == "revise" and reference == run["binding"].get("base_ref"):
                    return text, "edit_reference"
                if reference == run.get("draft_ref"):
                    return text, "saved_draft"
                if self.store.prefix_status(run, reference) == "valid":
                    return text, "body_context"
                raise ValueError("scope_denied: 草稿不是当前选中稿或有效父前缀")
            seen.add(current["run_id"])
            parent = current["binding"].get("base_ref")
            if not parent or parent["kind"] != "draft":
                break
            current = self.store.load(parent["draft_document_id"][len("draft-"):])
            ceiling = parent["draft_revision"]
        raise ValueError("scope_denied: 草稿不在本run选定的可读链")

    def _read_reference(self, arguments: dict, call_id: str) -> dict:
        """依赖：writing_resources。输入：host已提供资源ID。输出：写法片段或结构摘要/独立来源。实现：只从包内白名单读，参考不变成本书事实引用。"""
        return writing_resources()[arguments["resource_id"]]

    def _save(self, arguments: dict, call_id: str) -> dict:
        """依赖：唯一session组装/Store。输入：本run累计输出及CAS。输出：DraftRef。实现：父前缀由host仅拼一次，幂等保存，迟到只留独立稿。"""
        with self.store.lock:
            return self.store.save(self.run_id, arguments["expected_revision"], self.assemble(arguments["text"]),
                                   origin="model", call_id=call_id, arguments=arguments, select=self.select()).as_dict()

    def _remember(self, arguments: dict, call_id: str) -> dict:
        """依赖：MemoryService统一批次。输入：完整差分/来源/CAS。输出：ID映射/版本。实现：整批写一次，不安排observer/审批或另一份状态日志。"""
        return self.memory.remember(self.run_id, call_id, draft_ref=arguments.get("draft_ref"),
                                    expected_memory_revision=arguments["expected_memory_revision"], update=arguments["update"])
