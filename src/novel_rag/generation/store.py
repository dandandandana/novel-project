"""v3 工作产物的唯一保存点；快照含提交事实，派生回执不决定成功。"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import json
import re
from pathlib import Path
from threading import RLock
from typing import Callable
from uuid import uuid4

from ..identity import GraphKey, validate_identifier
from ..contracts.references import SOURCE_FINGERPRINT_PATTERN
from ..std.atomic_io import atomic_write_bytes, atomic_write_json
from ..std.hashing import fingerprint_bytes
from ..memory.effects import draft_selection_effect
from ..mutations.types import fingerprint_file
from ..std.time import utc_now_iso
from .types import AuthorInputRef, DraftRef, MemoryCommit, RunBinding


def public_tool_row(row: dict) -> dict:
    """依赖：原tool_results行合同。输入：持久工具行。输出：公开浅副本。实现：仅移除候选控制状态，原参数/结果/交付及Store原行保持。"""
    return {key: value for key, value in row.items() if key != "candidate_search_state"}


class StoreConflict(ValueError):
    """版本/参数/来源冲突；保存之前拒绝，正文不做语义合并。"""


class DraftStore:
    """单后端工作区；互斥+单run权威快照，跨文件只承诺先产物后引用。"""

    def __init__(self, workspace_root: Path):
        """依赖：Path/RLock。输入：工作产物根。输出：Store实例。实现：仅保存配置，首次操作创建目录，不读密钥。"""
        self.root, self.lock = Path(workspace_root).resolve(), RLock()

    def writer_lease(self):
        """依赖：已有FileMutationLock。输入：本工作区。输出：生命周期锁context manager。实现：生产写入口在恢复前独占，确认死亡的旧进程可恢复，不复制锁协议。"""
        from ..mutations.locks import FileMutationLock
        return FileMutationLock(self.root / ".writer.lock", stale_after=0)

    def _run_path(self, run_id: str) -> Path:
        """依赖：validate_identifier。输入：host run_id。输出：权威快照路径。实现：安全键校验+受控工作区映射。"""
        validate_identifier(run_id)
        candidates = list(self.root.glob(f"*/*/runs/{run_id}/run.json"))
        if len(candidates) != 1:
            raise StoreConflict("scope_denied: 运行不存在或身份歧义")
        return candidates[0]

    def load(self, run_id: str) -> dict:
        """依赖：原始run与同run hash产物。输入：run_id。输出：兼容旧形状的独立JSON。实现：核验并还原冷字段，缺失/损坏拒绝，不用缓存判提交。"""
        with self.lock:
            run = self._read_run(run_id)
            storage = run.pop("payload_storage", None)
            references = storage["refs"] if storage else {}
            loaded, seen = {}, set()
            payload_root = self._run_path(run_id).parent
            for location, parent, key in self._payload_slots(run):
                if location not in references:
                    continue
                if parent[key] is not None:
                    raise StoreConflict("source_invalid: 物理产物引用含内联值")
                digest = references[location]
                if digest not in loaded:
                    loaded[digest] = self._read_payload(payload_root, digest)
                parent[key] = deepcopy(loaded[digest])
                seen.add(location)
            if seen != set(references):
                raise StoreConflict("source_invalid: 运行产物引用位置不合法")
            return run

    def _read_run(self, run_id: str) -> dict:
        """依赖：权威run文件。输入：run ID。输出：未展开物理快照。实现：只接受已知布局，冷引用仅由load解释，热读不解析产物。"""
        run = json.loads(self._run_path(run_id).read_text(encoding="utf-8"))
        self._payload_references(run)
        return run

    @staticmethod
    def _payload_references(run: dict) -> dict:
        """依赖：物理布局合同。输入：run。输出：已验证的引用映射或冲突。实现：新旧读取/内部写回共用版本验证，不擅自降级未知布局。"""
        storage = run.get("payload_storage")
        if storage is not None and (not isinstance(storage, dict) or set(storage) != {"version", "refs"}
                                   or type(storage["version"]) is not int or storage["version"] != 1
                                   or not isinstance(storage["refs"], dict)):
            raise StoreConflict("source_invalid: 不支持的运行产物布局")
        return storage["refs"] if storage else {}

    def _read_payload(self, parent: Path, digest: str):
        """依赖：受控hash路径/真实字节。输入：run目录/hash。输出：原JSON值或冲突。实现：先核hash再解析，不用mtime或缺失兜底替代内容。"""
        path = self._payload_path(parent, digest)
        try:
            raw = path.read_bytes()
            if fingerprint_bytes(raw) != digest:
                raise ValueError("payload hash不匹配")
            return json.loads(raw)
        except (OSError, ValueError) as exc:
            raise StoreConflict(f"source_invalid: 运行产物缺失或损坏 {digest}") from exc

    @staticmethod
    def _payload_slots(run: dict):
        """依赖：原run字段形状。输入：物理或逻辑run。输出：允许外置的位置/父容器/键。实现：仅工具大字段及不可变turn/批次/稿版本，用户字典不作引用解释。"""
        for group in ("tool_results", "turns", "memory_batches"):
            for index, row in enumerate(run.get(group, [])):
                if group != "tool_results":
                    yield f"{group}/{index}", run[group], index
                else:
                    for field in ("arguments", "result", "delivered_result", "candidate_search_state"):
                        if field in row:
                            yield f"{group}/{index}/{field}", row, field
        for key in run.get("drafts", {}):
            yield "drafts/" + key, run["drafts"], key

    @staticmethod
    def _payload_path(parent: Path, digest: str) -> Path:
        """依赖：公共hash格式。输入：run目录与内容指纹。输出：受控本run产物路径或冲突。实现：只接受完整sha256，用hex文件名避免路径/Windows冒号。"""
        if not isinstance(digest, str) or re.fullmatch(SOURCE_FINGERPRINT_PATTERN, digest) is None:
            raise StoreConflict("source_invalid: 运行产物hash格式错误")
        return parent / "payloads" / (digest[7:] + ".json")

    def observation_revision(self, run_id: str) -> tuple:
        """依赖：原子替换run的stat。输入：run ID。输出：观察变化提示。实现：只用于减少SSE解析，不判断来源效力或提交成功。"""
        with self.lock:
            stat = self._run_path(run_id).stat()
            return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns

    def write(self, run: dict) -> None:
        """依赖：公共原子保存/指纹/同run产物。输入：逻辑或内部物理快照。输出：None/异常。实现：大字段先按内容保存再提升引用，原逻辑内容不裁剪，调用者持互斥。"""
        scope = run["binding"]["scope"]
        key = GraphKey(**scope)
        validate_identifier(run["run_id"])
        path = self.root / key.story_id / key.timeline_id / "runs" / run["run_id"] / "run.json"
        stored = deepcopy(run)
        references = dict(self._payload_references(stored))
        stored.pop("payload_storage", None)
        from ..std.serialization import json_text

        locations = set()
        for location, parent, field in self._payload_slots(stored):
            locations.add(location)
            if location in references:
                self._payload_path(path.parent, references[location])
                if parent[field] is not None:
                    raise StoreConflict("source_invalid: 物理产物引用含内联值")
                continue
            raw = json_text(parent[field]).encode("utf-8")
            if len(raw) < 8192:
                continue
            digest = fingerprint_bytes(raw)
            payload = self._payload_path(path.parent, digest)
            if payload.exists():
                if fingerprint_bytes(payload.read_bytes()) != digest:
                    raise StoreConflict("source_invalid: 运行产物hash不匹配")
            else:
                atomic_write_bytes(payload, raw)
            parent[field], references[location] = None, digest
        if set(references) - locations:
            raise StoreConflict("source_invalid: 运行产物引用位置不合法")
        if references:
            stored["payload_storage"] = {"version": 1, "refs": references}
        atomic_write_json(path, stored)

    def create(self, binding: RunBinding, outline: str, request: str, *,
               profile_name: str | None = None, session_id: str | None = None,
               parent_run_id: str | None = None, request_id: str | None = None,
               request_arguments_hash: str | None = None, driver: str = "builtin") -> dict:
        """依赖：RunBinding/指纹/原子快照。输入：固定绑定、原输入和driver。输出：持久化run。实现：harness准备态不代表内置请求，安全输入槽不含凭证。"""
        with self.lock:
            run_id = "run-" + uuid4().hex
            session_id = session_id or "session-" + uuid4().hex
            refs = tuple(AuthorInputRef(run_id, slot, fingerprint_bytes(text.encode("utf-8")))
                         for slot, text in (("outline", outline), ("request", request)))
            binding = replace(binding, input_snapshot_refs=refs)
            run = {"schema_version": 3, "writer_version": "v3", "run_id": run_id,
                   "session_id": session_id, "binding": binding.as_dict(),
                   "request_snapshot": {"outline": outline, "request": request},
                   "profile_name": profile_name, "parent_run_id": parent_run_id,
                   "request_id": request_id, "request_arguments_hash": request_arguments_hash,
                   "driver": driver, "status": "prepared" if driver == "harness" else "queued",
                   "cancel_requested": False, "created_at": utc_now_iso(),
                   "draft_revision": 0, "draft_ref": None, "draft_text": "", "drafts": {},
                   "author_revision": 0, "memory_revision": binding.initial_memory_revision,
                   "memory_batches": [], "tool_commits": {}, "turns": [], "events": [],
                   "source_signature": {ref.document_id: ref.source_hash for ref in binding.baseline_source_refs},
                   "error": None, "adoption": None}
            self.write(run)
            return deepcopy(run)

    @staticmethod
    def _append_event(run: dict, event_type: str, payload: dict) -> dict:
        """依赖：原事件形状。输入：待提交的run、类型和payload。输出：新事件。实现：在同个快照中按现有长度分配连续seq。"""
        event = {"run_id": run["run_id"], "seq": len(run["events"]) + 1, "type": event_type, "payload": payload}
        run["events"].append(event)
        return event

    def event(self, run_id: str, event_type: str, payload: dict) -> dict:
        """依赖：run.json/原子保存。输入：事件类型与安全payload。输出：单调seq事件。实现：先保存完整事件再交观察者，SSE非事实源。"""
        with self.lock:
            run = self._read_run(run_id)
            event = self._append_event(run, event_type, payload)
            self.write(run)
            return event

    def set_status(self, run_id: str, status: str, error: dict | None = None) -> dict:
        """依赖：权威快照/event。输入：状态和可恢复错误。输出：新快照。实现：持久状态之后发布状态事件，不清空稿件。"""
        with self.lock:
            run = self.load(run_id)
            run.update(status=status, error=error)
            self.write(run)
            self.event(run_id, "status", {"status": status, "error": error})
            return self.load(run_id)

    @staticmethod
    def _read_received_turn(parent: Path, turn_id: str) -> tuple[Path, dict]:
        """依赖：安全turn标识与JSON。输入：run目录/turn ID。输出：接收路径与快照或空值。实现：读取真实UTF-8文件，只在缺失时返回空值。"""
        validate_identifier(turn_id)
        path = parent / "turns" / turn_id / "received.json"
        try:
            return path, json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return path, {}

    @staticmethod
    def _published_text_chars(run: dict, turn_id: str, text: str, previous_text: str) -> int:
        """依赖：原run事件与内部发布位置。输入：run/turn及当前与已接收文本。输出：已发布字符数或冲突。实现：同turn用原子提交位置，旧run或换turn时从持久事件核前缀。"""
        position = run.get("received_published_chars") if run.get("received_turn_id") == turn_id else None
        if position is not None:
            if type(position) is not int or not 0 <= position <= len(previous_text):
                raise StoreConflict("source_invalid: 已发布位置不一致")
            return position
        prefix = "".join(event["payload"]["text"] for event in run["events"]
                         if event["type"] == "text_delta" and event["payload"].get("turn_id") == turn_id)
        if not text.startswith(prefix):
            raise StoreConflict("model_protocol: 已发布的增量前缀不一致")
        return len(prefix)

    def receive(self, run_id: str, turn_id: str, text: str, *, complete: bool = False) -> None:
        """依赖：原子JSON/热run。输入：turn累计公开文本及完成标记。输出：None或保存/协议错误。实现：先写接收，再一次提交指针与未发布文本，不推进草稿修订。"""
        with self.lock:
            run = self._read_run(run_id)
            path, previous = self._read_received_turn(self._run_path(run_id).parent, turn_id)
            previous_text = previous.get("text", "")
            if not text.startswith(previous_text):
                raise StoreConflict("model_protocol: 增量前缀不一致")
            was_complete = previous.get("complete", False)
            if was_complete and text != previous_text:
                raise StoreConflict("model_protocol: 完整turn不能追加增量")
            published_chars = self._published_text_chars(run, turn_id, text, previous_text)
            snapshot = {"turn_id": turn_id, "text": text, "complete": complete or was_complete,
                        "persisted_bytes": len(text.encode("utf-8"))}
            if snapshot != previous:
                atomic_write_json(path, snapshot)
            delta = text[published_chars:]
            if delta or run.get("received_turn_id") != turn_id:
                run.update(received_turn_id=turn_id, received_published_chars=len(text))
                if delta:
                    self._append_event(run, "text_delta", {"text": delta, "turn_id": turn_id})
                self.write(run)

    def _latest_received(self, parent: Path, run: dict) -> dict:
        """依赖：原turn顺序、接收指针与received文件。输入：run目录及已读快照。输出：最新持久前缀或空值。实现：优先恢复末轮文件，无文件回已发布轮；无转录才用旧接收文件兜底。"""
        published_turn = run.get("received_turn_id")
        last_turn = run.get("last_turn_id")
        if not last_turn and run["turns"]:
            last_index = len(run["turns"]) - 1
            row = run["turns"][last_index]
            if row is None:
                digest = self._payload_references(run).get(f"turns/{last_index}")
                if digest is not None:
                    row = self._read_payload(parent, digest)
            last_turn = row.get("turn_id") if isinstance(row, dict) else None
        if last_turn and last_turn != published_turn:
            _, received = self._read_received_turn(parent, last_turn)
            if received:
                return received
        if published_turn:
            return self._read_received_turn(parent, published_turn)[1]
        if last_turn:
            return {}
        files = sorted(parent.glob("turns/*/received.json"), key=lambda path: path.stat().st_mtime_ns)
        return json.loads(files[-1].read_text(encoding="utf-8")) if files else {}

    def received(self, run_id: str, turn_id: str | None = None) -> dict:
        """依赖：独立received文件/原run。输入：run及可选turn。输出：持久前缀或空值。实现：明确指定轮次时读原文件，否则沿原转录与指针选择，未发布前缀仍可读取。"""
        with self.lock:
            run = self._read_run(run_id)
            parent = self._run_path(run_id).parent
            if turn_id:
                return self._read_received_turn(parent, turn_id)[1]
            return self._latest_received(parent, run)

    def prepare_turn(self, run_id: str, turn_id: str, attempt_id: str, manifest: dict) -> None:
        """依赖：原run快照/安全身份。输入：turn、attempt及无凭证发送清单。输出：None/身份冲突。实现：网络前同次保存准备行和末轮标识，不持锁跨请求。"""
        validate_identifier(turn_id)
        validate_identifier(attempt_id)
        with self.lock:
            run = self.load(run_id)
            prepared = {"turn_id": turn_id, "attempt_id": attempt_id, "request_manifest": deepcopy(manifest),
                        "request_status": "prepared"}
            previous = next((row for row in run["turns"] if row["turn_id"] == turn_id), None)
            if previous is not None:
                if any(previous.get(key) != value for key, value in prepared.items() if key != "request_status"):
                    raise StoreConflict("revision_conflict: 同turn发送绑定不同")
                return
            run["turns"].append(prepared)
            run["last_turn_id"] = turn_id
            self.write(run)

    def invocation_key(self, attempt_id: str, provider_call_id: str) -> str:
        """依赖：既有字节指纹/安全身份。输入：真实attempt与协议call ID。输出：内部提交键。实现：指纹命名空间隔离attempt，provider ID不改写、不作路径。"""
        validate_identifier(attempt_id)
        if not isinstance(provider_call_id, str) or not provider_call_id:
            raise StoreConflict("model_protocol: 工具调用缺少provider ID")
        return "invocation-" + fingerprint_bytes(json.dumps(
            [attempt_id, provider_call_id], ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")).split(":", 1)[-1]

    def commit_turn(self, run_id: str, turn_id: str, turn: dict) -> None:
        """依赖：原run准备行/received。输入：完整规范turn/continuation。输出：None/重复响应冲突。实现：更新同一准备行保留发送绑定，旧入口追加时记录末轮，先固化公开序列。"""
        with self.lock:
            run = self.load(run_id)
            previous = next((row for row in run["turns"] if row["turn_id"] == turn_id), None)
            if previous is None:
                previous = {"turn_id": turn_id}
                run["turns"].append(previous)
                run["last_turn_id"] = turn_id
            elif previous.get("request_status") == "completed" and any(previous.get(key) != value for key, value in turn.items()):
                raise StoreConflict("revision_conflict: 同turn完整响应不同")
            previous.update(turn, request_status="completed")
            self.write(run)
            self.receive(run_id, turn_id, turn["text"], complete=True)

    def public_turn_text(self, run_id: str, turn_id: str) -> str:
        """依赖：本run原turn/received快照。输入：已记录turn ID。输出：公开原文本或范围错误。实现：只读本run公开text，不泄露reasoning、不创建正文引用。"""
        validate_identifier(turn_id)
        with self.lock:
            run = self.load(run_id)
            turn = next((row for row in run["turns"] if row["turn_id"] == turn_id), None)
            received = self.received(run_id, turn_id)
            if turn is None and not received:
                raise StoreConflict("scope_denied: 本run没有该公开turn")
            return turn["text"] if turn is not None and isinstance(turn.get("text"), str) else received.get("text", "")

    def save(self, run_id: str, expected_revision: int, text: str, *, origin: str = "author",
             call_id: str | None = None, arguments: dict | None = None,
             select: bool = True, protect_author: bool = False) -> DraftRef:
        """依赖：原子正文/纯记忆失效策略。输入：CAS/完整正文/调用身份。输出：唯一DraftRef或冲突。实现：先幂等再CAS，正文先落盘，快照一次提交引用、失效、结果与事件。"""
        with self.lock:
            if isinstance(expected_revision, bool) or not isinstance(expected_revision, int) or not isinstance(text, str):
                raise ValueError("source_invalid: 草稿需要整数修订与正文文本")
            run = self.load(run_id)
            result = self._previous_commit(run, call_id, arguments)
            if result is not None:
                return DraftRef(**{key: value for key, value in result.items() if key != "kind"})
            if run["draft_revision"] != expected_revision:
                raise StoreConflict("revision_conflict: 草稿已改变")
            revision = max((item["ref"]["draft_revision"] for item in run["drafts"].values()), default=0) + 1
            ref = DraftRef("draft-" + run_id, revision, fingerprint_bytes(text.encode("utf-8")), "checkpoint-" + uuid4().hex)
            path = self._run_path(run_id).parent / "drafts" / f"{revision}.txt"
            atomic_write_bytes(path, text.encode("utf-8"))
            run["drafts"][ref.checkpoint_id] = {"ref": ref.as_dict(), "origin": origin, "text": text}
            if select:
                effect = draft_selection_effect(run["draft_text"], text, run["drafts"],
                                                run["memory_batches"], run.get("memory_effect_signature"))
                if effect.invalidated_checkpoints:
                    run["memory_revision"] += 1
                    if effect.effect_signature is not None:
                        run["memory_effect_signature"] = effect.effect_signature
                    run["memory_local_invalidations"] = list(effect.invalidated_checkpoints)
                run.update(draft_revision=revision, draft_ref=ref.as_dict(), draft_text=text)
            else:
                run.update(generated_draft_ref=ref.as_dict(), generated_draft_text=text)
            if origin == "author" or protect_author:
                run["author_revision"] = revision
            self._record_commit(run, call_id, arguments, ref.as_dict())
            self._append_event(run, "draft_saved", {"draft_ref": run["draft_ref"], "draft_revision": run["draft_revision"],
                                                    "draft_text": run["draft_text"]})
            self.write(run)
            return ref

    def _previous_commit(self, run: dict, call_id: str | None, arguments: dict | None) -> dict | None:
        """依赖：同run工具提交表。输入：真实call_id/原参数。输出：原结果或None。实现：参数指纹匹配先于CAS；同ID换参数拒绝。"""
        if not call_id or call_id not in run["tool_commits"]:
            return None
        record = run["tool_commits"][call_id]
        if record["arguments_hash"] != self._arguments_hash(arguments):
            raise StoreConflict("revision_conflict: 同调用ID参数不同")
        return deepcopy(record["result"])

    def committed_tool(self, run_id: str, call_id: str, arguments: dict) -> dict | None:
        """依赖：唯一提交表/_previous_commit。输入：run、稳定工具ID及原参数。输出：原提交结果/None或冲突。实现：同锁查已提交结果，允许取消后恢复，不新建回执日志。"""
        with self.lock:
            return self._previous_commit(self.load(run_id), call_id, arguments)

    def _arguments_hash(self, arguments: dict | None) -> str:
        """依赖：fingerprint_bytes/标准JSON。输入：工具参数。输出：稳定字节指纹。实现：排序序列化，不用call_id拼路径。"""
        return fingerprint_bytes(json.dumps(arguments or {}, sort_keys=True, ensure_ascii=False).encode("utf-8"))

    def _record_commit(self, run: dict, call_id: str | None, arguments: dict | None, result: dict) -> None:
        """依赖：权威run数据。输入：调用与结果。输出：原地更新提交表。实现：与批次/revision一次保存，外部回执可重建。"""
        if call_id:
            run["tool_commits"][call_id] = {"arguments_hash": self._arguments_hash(arguments), "result": deepcopy(result)}

    def commit_memory(self, run_id: str, call_id: str, arguments: dict,
                      build: Callable[[dict], MemoryCommit | tuple[dict, dict]]) -> dict:
        """依赖：MemoryCommit/整批验证回调。输入：真实调用、原参数、纯builder。输出：稳定结果。实现：幂等→终态/CAS→规范结果原子提交；旧二元组仅在入口复制并提取内部签名。"""
        with self.lock:
            run = self.load(run_id)
            previous = self._previous_commit(run, call_id, arguments)
            if previous is not None:
                return previous
            if run["cancel_requested"] or run["status"] in {"completed", "cancelled", "failed", "interrupted"}:
                raise StoreConflict("cancelled: 已停止，不提交新的记忆副作用")
            if arguments["expected_memory_revision"] != run["memory_revision"]:
                raise StoreConflict("revision_conflict: 记忆版本已变化")
            commit = build(deepcopy(run))
            if not isinstance(commit, MemoryCommit):
                legacy_batch, legacy_result = commit
                legacy_batch = deepcopy(legacy_batch)
                commit = MemoryCommit(legacy_batch, legacy_result, legacy_batch.pop("_effect_signature", None))
            batch, result = deepcopy(commit.batch), deepcopy(commit.result)
            if commit.effect_signature is not None:
                run["memory_effect_signature"] = deepcopy(commit.effect_signature)
            run["memory_revision"] += 1
            batch["memory_revision"] = result["memory_revision"] = run["memory_revision"]
            run["memory_batches"].append(batch)
            self._record_commit(run, call_id, arguments, result)
            self.write(run)
            return deepcopy(result)

    def reconcile_memory_effect(self, run_id: str, *, expected_memory_revision: int,
                                expected_draft_ref: dict | None, signature: dict,
                                initially_invalid: bool) -> dict:
        """依赖：原Store锁/来源效力决策。输入：读取版本、选中稿、签名及首次失效。输出：当前run或快照冲突。实现：同锁复核双CAS，相等不写，首次有效初始化不增版本。"""
        with self.lock:
            current = self.load(run_id)
            if current["memory_revision"] != expected_memory_revision or current.get("draft_ref") != expected_draft_ref:
                raise StoreConflict("revision_conflict: memory_snapshot已过期，请重新读取")
            previous = current.get("memory_effect_signature")
            if previous == signature:
                return current
            current["memory_effect_signature"] = deepcopy(signature)
            if previous is not None or initially_invalid:
                current["memory_revision"] += 1
            self.write(current)
            return current

    def record_adoption_receipt(self, run_id: str, result: dict) -> None:
        """依赖：原Store锁/权威run。输入：run身份与已确认采用回执。输出：None或写入错误。实现：同锁重读后只更新回执，不覆盖并发草稿或把镜像当正文提交点。"""
        with self.lock:
            current = self.load(run_id)
            current["adoption"] = deepcopy(result)
            self.write(current)

    def resolve_draft(self, ref: dict, *, run: dict | None = None, metadata_only: bool = False) -> tuple[dict, str]:
        """依赖：host检查点/原payload读取。输入：Ref、可选同次run及轻读标志。输出：来源元数据/原文。实现：默认完整兼容，轻读只展开指定检查点，正文始终核真实字节/hash。"""
        document_id = ref.get("draft_document_id", "")
        if not document_id.startswith("draft-run-"):
            raise StoreConflict("source_invalid: 草稿身份不合法")
        source_id = document_id[len("draft-"):]
        run = run if run is not None and run["run_id"] == source_id else (self._read_run(source_id) if metadata_only else self.load(source_id))
        checkpoint = run["drafts"].get(ref.get("checkpoint_id"))
        location = "drafts/" + str(ref.get("checkpoint_id"))
        references = self._payload_references(run)
        if location in references:
            if checkpoint is not None:
                raise StoreConflict("source_invalid: 物理产物引用含内联值")
            checkpoint = self._read_payload(self._run_path(source_id).parent, references[location])
        if checkpoint is None or checkpoint["ref"] != ref:
            raise StoreConflict("source_invalid: 检查点不存在或引用不匹配")
        path = self._run_path(run["run_id"]).parent / "drafts" / f"{ref['draft_revision']}.txt"
        text = path.read_bytes().decode("utf-8")
        if fingerprint_bytes(text.encode("utf-8")) != ref["content_hash"]:
            raise StoreConflict("source_invalid: 草稿字节已改变")
        return run, text

    def accepts_prefix(self, run: dict, ref: dict, *, selected_text: str | None = None) -> bool:
        """依赖：resolve_draft/父绑定。输入：run/引用/可选采用正文。输出：是否覆盖同起点前缀。实现：复用同次run元数据，仍核真实正文并沿所选父链，不做substring重定位。"""
        source_run, prefix = self.resolve_draft(ref, run=run)
        current, seen = run, set()
        while current["run_id"] not in seen:
            seen.add(current["run_id"])
            if current["run_id"] == source_run["run_id"]:
                text = selected_text if selected_text is not None else run["draft_text"]
                return text.encode("utf-8").startswith(prefix.encode("utf-8"))
            parent = current["binding"].get("base_ref")
            if not parent or parent["kind"] != "draft":
                break
            current, parent_text = self.resolve_draft(parent)
            if not parent_text.encode("utf-8").startswith(prefix.encode("utf-8")):
                break
        return False

    def prefix_status(self, run: dict, ref: dict) -> str:
        """依赖：真实父前缀/检查点。输入：同次run/草稿引用。输出：valid/future/stale。实现：复用同run元数据且核真实字节，未来先裁，祖先改写失效/纯追加有效。"""
        source, prefix = self.resolve_draft(ref, run=run)
        accepted = self.accepts_prefix(run, ref)
        if source["run_id"] == run["run_id"] and ref["draft_revision"] > run["draft_revision"]:
            return "future"
        current, seen = run, set()
        broken = False
        while current["run_id"] not in seen:
            seen.add(current["run_id"])
            parent = current["binding"].get("base_ref")
            if current["binding"]["output_mode"] != "append_suffix" or not parent or parent["kind"] != "draft":
                break
            current, parent_text = self.resolve_draft(parent)
            if current["run_id"] == source["run_id"] and ref["draft_revision"] > parent["draft_revision"]:
                return "future"
            broken = broken or not current["draft_text"].startswith(parent_text)
        return "valid" if accepted and not broken else "stale"

    def adoption_path(self, scope: GraphKey, operation_id: str) -> Path:
        """依赖：既有adoptions目录/公共指纹。输入：scope与采用操作ID。输出：唯一journal路径。实现：安全hash键，不将任意ID拼入文件名。"""
        key = fingerprint_bytes(operation_id.encode("utf-8")).split(":", 1)[1]
        return self.root / scope.story_id / scope.timeline_id / "adoptions" / (key + ".json")

    def protect_memory(self, scope: GraphKey, payload: dict) -> dict:
        """依赖：json_text/原子字节/既有source-versions。输入：冻结的记忆证据。输出：逻辑键与hash。实现：按不可变内容地址保护，副本不作为当前事实库。"""
        from ..std.serialization import json_text

        raw = json_text(payload).encode("utf-8")
        content_hash = fingerprint_bytes(raw)
        target = self.root / scope.story_id / scope.timeline_id / "source-versions" / "memory" / (content_hash[7:] + ".json")
        if not target.exists():
            atomic_write_bytes(target, raw)
        if fingerprint_file(target) != content_hash:
            raise StoreConflict("save_failed: 冻结记忆保护版本hash不符")
        return {"key": target.relative_to(self.root).as_posix(), "hash": content_hash}

    def protected_memory(self, ref: dict, scope: GraphKey) -> dict:
        """依赖：保护版本/实际hash。输入：内部逻辑引用与scope。输出：冻结证据或来源错误。实现：核验根目录/作品归属及字节，不依赖原绝对路径。"""
        from ..contracts.references import SOURCE_FINGERPRINT_PATTERN

        if not isinstance(ref, dict) or set(ref) != {"key", "hash"} or not isinstance(ref.get("key"), str) or not ref["key"] or not isinstance(ref.get("hash"), str) or not SOURCE_FINGERPRINT_PATTERN.fullmatch(ref["hash"]):
            raise StoreConflict("source_invalid: 冻结记忆保护引用形状错误")
        logical = Path(ref["key"])
        if logical.is_absolute() or ".." in logical.parts:
            raise StoreConflict("source_invalid: 冻结记忆保护引用越根")
        target = (self.root / logical).resolve()
        try:
            target.relative_to((self.root / scope.story_id / scope.timeline_id / "source-versions" / "memory").resolve())
        except ValueError as exc:
            raise StoreConflict("source_invalid: 冻结记忆保护引用越域") from exc
        if fingerprint_file(target) != ref["hash"]:
            raise StoreConflict("source_invalid: 冻结记忆保护版本缺失或损坏")
        value = json.loads(target.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise StoreConflict("source_invalid: 冻结记忆保护版本形状错误")
        return value

    def memory_publications(self, scopes: list[GraphKey]) -> tuple[list[dict], list[str]]:
        """依赖：既有adoption journal。输入：可访问scope列表。输出：发布记录与损坏缺口。实现：读取持久绑定，不扫描其他作品、不恢复或重提正文。"""
        publications, gaps = [], []
        for scope in scopes:
            directory = self.root / scope.story_id / scope.timeline_id / "adoptions"
            for path in sorted(directory.glob("*.json")):
                try:
                    value = json.loads(path.read_text(encoding="utf-8"))
                    if not isinstance(value, dict) or value.get("scope") != scope.as_dict() or not isinstance(value.get("operation_id"), str):
                        raise ValueError("采用journal身份错误")
                    from ..memory.schema import validate_source_refs

                    result = value.get("result")
                    if result is not None and not isinstance(result, dict):
                        raise ValueError("采用journal.result错误")
                    references = [("result.source_ref", (result or {}).get("source_ref"))]
                    publication = value.get("memory_publication")
                    if publication is not None:
                        if not isinstance(publication, dict) or not isinstance(publication.get("projection_id"), str) or type(publication.get("batch_count")) is not int or publication["batch_count"] < 0:
                            raise ValueError("采用journal.memory_publication字段错误")
                        references.extend(("memory_publication." + name, publication.get(name)) for name in ("projection_ref", "adopted_source_ref"))
                    for name, reference in references:
                        if reference is not None and (not isinstance(reference, dict) or reference.get("kind") != "document" or
                                validate_source_refs([reference]) or reference.get("scope") != scope.as_dict()):
                            raise ValueError("采用journal." + name + "需要本scope的DocumentRef")
                    publications.append(value)
                except (ValueError, OSError) as exc:
                    gaps.append(f"{path.name}: 发布证据不可读 {exc}")
        return publications, gaps

    def target_source_ref(self, run: dict, *, metadata_only: bool = False) -> dict | None:
        """依赖：父DraftRef/采用事实。输入：run及可选轻读。输出：真正History目标或None。实现：沿所选父链核正文和检查点，轻读不加载无关冷历史，前章不当采用目标。"""
        current, seen = run, set()
        while current["run_id"] not in seen:
            seen.add(current["run_id"])
            adopted = current.get("adoption")
            if adopted and adopted.get("source_ref"):
                return deepcopy(adopted["source_ref"])
            binding = current["binding"]
            base = binding.get("base_ref")
            if base and base["kind"] == "document":
                return deepcopy(base) if binding["task_kind"] == "revise" else None
            if not base or base["kind"] != "draft":
                break
            current, _ = self.resolve_draft(base, metadata_only=metadata_only)
        return None

    def input_text(self, ref: dict) -> str:
        """依赖：固定请求槽或protected input-versions。输入：AuthorInputRef。输出：原UTF-8文本。实现：逐字节hash校验，runtime清理后仍可回读保护版本。"""
        run_id, slot = ref["run_id"], ref["input_slot"]
        snapshot_hash = ref.get("snapshot_hash", "")
        if not isinstance(snapshot_hash, str) or not snapshot_hash.startswith("sha256:") or len(snapshot_hash) != 71 or any(char not in "0123456789abcdef" for char in snapshot_hash[7:]):
            raise StoreConflict("source_invalid: 输入版本hash不合法")
        validate_identifier(run_id)
        if slot not in {"outline", "request"}:
            raise StoreConflict("source_invalid: 输入槽不合法")
        try:
            text = self.load(run_id)["request_snapshot"][slot]
        except (StoreConflict, OSError):
            key = fingerprint_bytes((run_id + slot).encode("utf-8")).split(":", 1)[1]
            paths = list(self.root.glob(f"*/*/input-versions/{key}/{ref['snapshot_hash'].split(':', 1)[1]}.txt"))
            if len(paths) != 1:
                raise StoreConflict("source_invalid: 输入版本不存在")
            text = paths[0].read_bytes().decode("utf-8")
        if fingerprint_bytes(text.encode("utf-8")) != ref["snapshot_hash"]:
            raise StoreConflict("source_invalid: 输入版本hash不符")
        return text

    def protect_input(self, run: dict, ref: dict) -> None:
        """依赖：input_text/atomic_write_bytes。输入：采用run及输入引用。输出：None。实现：发布前将确切输入按安全key/hash保存并核验，不改事实库。"""
        text = self.input_text(ref)
        scope = run["binding"]["scope"]
        key = fingerprint_bytes((ref["run_id"] + ref["input_slot"]).encode("utf-8")).split(":", 1)[1]
        target = self.root / scope["story_id"] / scope["timeline_id"] / "input-versions" / key / (ref["snapshot_hash"].split(":", 1)[1] + ".txt")
        atomic_write_bytes(target, text.encode("utf-8"))
        if fingerprint_bytes(target.read_bytes()) != ref["snapshot_hash"]:
            raise StoreConflict("save_failed: 输入版本核验失败")

    def protect_source(self, library_root: Path, scope: GraphKey, path: Path, snapshot) -> Path:
        """依赖：同次YamlSnapshot/原子字节与指纹。输入：库、作用域、原文件及读取快照。输出：保护版本路径。实现：相对源路径哈希作键，完整旧YAML先保存核验，备份不进默认corpus。"""
        path.resolve().relative_to((Path(library_root) / "stories" / scope.story_id).resolve())
        key = fingerprint_bytes(str(path.relative_to(library_root)).encode("utf-8")).split(":", 1)[1]
        target = self.root / scope.story_id / scope.timeline_id / "source-versions" / key / (snapshot.source_hash.split(":", 1)[1] + ".yaml")
        atomic_write_bytes(target, snapshot.raw_bytes)
        if fingerprint_file(target) != snapshot.source_hash:
            raise OSError("save_failed: 源版本备份核验失败")
        return target

    def recover(self) -> list[str]:
        """依赖：磁盘run枚举。输入：本工作区。输出：被标interrupted的run IDs。实现：启动时标遗留running，不重发任何请求。"""
        recovered = []
        with self.lock:
            for path in self.root.glob("*/*/runs/*/run.json"):
                run = self._read_run(path.parent.name)
                if run["status"] in {"running", "queued"}:
                    run["status"] = "interrupted"
                    self.write(run)
                    recovered.append(run["run_id"])
        return recovered

    def snapshot(self, run_id: str, *, view: str = "full", after: int = 0) -> dict:
        """依赖：run/received/公开投影。输入：run、full/live及事件游标。输出：兼容全快照或热观察。实现：同次读取投影接收前缀与事件增量，旧布局仅按需读取末轮；full保留公开原行与用量。"""
        from ..model_api import provider_usage_totals

        if view not in {"full", "live"} or type(after) is not int or after < 0:
            raise ValueError("source_invalid: 快照view或事件游标不合法")
        with self.lock:
            if view == "live":
                raw = self._read_run(run_id)
                fields = ("run_id", "session_id", "binding", "request_snapshot", "profile_name", "parent_run_id", "driver",
                          "status", "cancel_requested", "created_at", "draft_revision", "draft_ref", "draft_text",
                          "author_revision", "memory_revision", "error", "adoption", "generated_draft_ref", "generated_draft_text")
                result = {key: raw[key] for key in fields if key in raw}
                received = self._latest_received(self._run_path(run_id).parent, raw)
                high = len(raw["events"])
                result.update(snapshot_view="live", event_seq=high, events_reset=after > high,
                              events=raw["events"][0 if after > high else after:],
                              received_text=received.get("text", ""), received_turn_id=received.get("turn_id"))
                return result
            run = self.load(run_id)
            received = self._latest_received(self._run_path(run_id).parent, run)
        run.pop("received_published_chars", None)
        run.pop("last_turn_id", None)
        run["tool_results"] = [public_tool_row(row) for row in run.get("tool_results", [])]
        # Provider continuation只供运行恢复；隐藏reasoning/原生继续项不进入浏览器快照。
        run["turns"] = [{key: turn.get(key) for key in ("turn_id", "attempt_id", "request_status", "request_manifest",
                                                     "text", "tool_calls", "finish_reason", "usage")} for turn in run["turns"]]
        run.update(received_text=received.get("text", ""), received_turn_id=received.get("turn_id"))
        run["provider_usage"] = (provider_usage_totals([row.get("usage") or {} for row in run["turns"]
                                                       if row.get("request_status") == "completed" or row.get("finish_reason")])
                                 if run.get("driver", "builtin") == "builtin" else None)
        return run
