"""AI and user-editable YAML summary lifecycle."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Protocol

import yaml

from ..documents import DocumentError, read_yaml_snapshot
from .coordinator import MutationCoordinator
from .types import (
    ChangeSet,
    GraphBuildArtifact,
    MISSING_FINGERPRINT,
    MutationResult,
    SummaryConflictError,
    SummaryError,
    SummaryMutationFailedError,
    SummaryMutationPendingError,
    SummaryOwnershipError,
)


@dataclass(frozen=True, slots=True)
class SummaryUpdate:
    """Optimistic-concurrency request from the frontend summary editor."""

    document_id: str
    expected_revision: int
    content: str
    expected_fingerprint: str | None = None

    def __post_init__(self) -> None:
        """依赖：摘要编辑值类型。输入：ID、整数revision、内容及可选文件hash。输出：合法不可变请求/异常。实现：构造时拒绝无效身份和正文，文件CAS由editor同快照核验。"""
        if not self.document_id.strip():
            raise ValueError("SummaryUpdate.document_id 不能为空")
        if isinstance(self.expected_revision, bool) or self.expected_revision < 0:
            raise ValueError("SummaryUpdate.expected_revision 必须是非负整数")
        if not isinstance(self.content, str):
            raise TypeError("SummaryUpdate.content 必须是字符串")


@dataclass(frozen=True, slots=True)
class SummaryDocument:
    """A summary projection plus the metadata needed for freshness decisions."""

    path: Path
    document_id: str
    content: str
    ownership: str = "auto"
    source_fingerprint: str | None = None
    revision: int = 1
    stale: bool = False
    metadata: Mapping[str, Any] = field(default_factory=dict)
    file_fingerprint: str | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        """依赖：Path/summary格式owner。输入：冻结文档字段。输出：合法对象或SummaryError。实现：规范路径和metadata、校验revision/ownership，同次源hash只留内存。"""
        object.__setattr__(self, "path", Path(self.path))
        if not self.document_id.strip():
            raise ValueError("SummaryDocument.document_id 不能为空")
        if self.ownership not in {"auto", "user"}:
            raise ValueError("SummaryDocument.ownership 必须是 auto 或 user")
        if isinstance(self.revision, bool) or self.revision < 0:
            raise ValueError("SummaryDocument.revision 必须是非负整数")
        if not isinstance(self.content, str):
            raise TypeError("SummaryDocument.content 必须是字符串")
        object.__setattr__(self, "metadata", dict(self.metadata))

    @classmethod
    def from_yaml(cls, path: str | Path) -> "SummaryDocument":
        """依赖：read_yaml_snapshot。输入：摘要 YAML 路径。输出：保留源指纹的 SummaryDocument。实现：从同一快照解析元数据、内容与完整文件指纹。"""

        target = Path(path)
        try:
            snapshot = read_yaml_snapshot(target)
        except DocumentError as exc:
            raise SummaryError(f"无法读取摘要 YAML: {target}: {exc}") from exc
        value = snapshot.data
        if not isinstance(value, Mapping):
            raise SummaryError(f"摘要 YAML 根节点必须是映射: {target}")
        metadata = value.get("metadata")
        if not isinstance(metadata, Mapping):
            raise SummaryError(f"摘要缺少 metadata 映射: {target}")
        body = {key: child for key, child in value.items() if key != "metadata"}
        content = value.get("content")
        if not isinstance(content, str):
            content = value.get("summary")
        if not isinstance(content, str):
            content = value.get("text")
        if not isinstance(content, str):
            content = yaml.safe_dump(
                body,
                allow_unicode=True,
                sort_keys=False,
                default_flow_style=False,
            ).strip()
        document_id = str(metadata.get("document_id") or target.stem)
        ownership = str(metadata.get("ownership") or "auto")
        try:
            revision = int(metadata.get("revision", 1))
        except (TypeError, ValueError) as exc:
            raise SummaryError(f"摘要 revision 无效: {target}") from exc
        source_fingerprint = metadata.get("source_fingerprint")
        return cls(
            path=target,
            document_id=document_id,
            content=content,
            ownership=ownership,
            source_fingerprint=str(source_fingerprint) if source_fingerprint not in (None, "") else None,
            revision=revision,
            stale=bool(metadata.get("stale", False)),
            metadata=dict(metadata),
            file_fingerprint=snapshot.source_hash,
        )

    def to_payload(self) -> dict[str, Any]:
        metadata = dict(self.metadata)
        metadata.update(
            {
                "document_id": self.document_id,
                "ownership": self.ownership,
                "revision": self.revision,
                "stale": self.stale,
            }
        )
        if self.source_fingerprint is not None:
            metadata["source_fingerprint"] = self.source_fingerprint
        return {"metadata": metadata, "content": self.content}

    def with_content(
        self,
        content: str,
        *,
        ownership: str,
        revision: int | None = None,
        stale: bool = False,
        source_fingerprint: str | None = None,
    ) -> "SummaryDocument":
        return replace(
            self,
            content=content,
            ownership=ownership,
            revision=self.revision + 1 if revision is None else revision,
            stale=stale,
            source_fingerprint=self.source_fingerprint if source_fingerprint is None else source_fingerprint,
        )

    def is_stale_against(self, source_fingerprint: str | None) -> bool:
        return bool(
            self.stale
            or (
                source_fingerprint not in (None, "")
                and self.source_fingerprint not in (None, "")
                and self.source_fingerprint != source_fingerprint
            )
        )

    def for_context(self, source_fingerprint: str | None = None) -> "SummaryDocument | None":
        """Return this summary only when it is safe to feed to retrieval."""

        if self.is_stale_against(source_fingerprint):
            return None
        return self


class SummaryEditorProtocol(Protocol):
    def update(self, change: SummaryUpdate) -> SummaryDocument:
        """依赖：SummaryUpdate/Document值类型。输入：双CAS编辑请求。输出：保存后摘要。实现：协议声明，生产由SummaryEditor委托Coordinator。"""
        ...


class SummaryStore:
    """Small YAML-backed summary index used by the editor and writer."""

    def __init__(self, root: str | Path) -> None:
        """依赖：Path。输入：摘要资料目录。输出：只读映射实例。实现：保存根路径，find/load使用原文同次快照，不自己提交。"""
        self.root = Path(root)

    def find(self, document_id: str) -> SummaryDocument:
        if not document_id.strip():
            raise ValueError("document_id 不能为空")
        if not self.root.exists():
            raise SummaryError(f"摘要目录不存在: {self.root}")
        for path in sorted((*self.root.rglob("*.yaml"), *self.root.rglob("*.yml"))):
            try:
                document = SummaryDocument.from_yaml(path)
            except SummaryError:
                continue
            if document.document_id == document_id:
                return document
        raise SummaryError(f"找不到摘要 document_id: {document_id}")

    def load(self, path: str | Path, *, source_fingerprint: str | None = None) -> SummaryDocument:
        document = SummaryDocument.from_yaml(path)
        if document.is_stale_against(source_fingerprint):
            return replace(document, stale=True)
        return document

    def usable_for_context(
        self,
        document_id: str,
        *,
        source_fingerprint: str | None = None,
    ) -> SummaryDocument | None:
        return self.find(document_id).for_context(source_fingerprint)


def _infer_library_root(summary_root: Path) -> Path:
    """Infer a library root from a canonical or legacy summary directory."""

    resolved = summary_root.resolve(strict=False)
    parts = resolved.parts
    try:
        stories_index = parts.index("stories")
    except ValueError:
        # A caller may use an isolated/legacy summary directory in a migration
        # fixture.  Keep that directory as the composition root; the actual
        # GraphKey is still validated when the document is prepared and the
        # composition builder remains the only production coordinator path.
        return resolved
    if stories_index == 0 or stories_index + 1 >= len(parts):
        raise SummaryError("summary_root 缺少有效 stories/<story_id> 路径")
    return Path(*parts[:stories_index])


def _path_graph_key(document: SummaryDocument) -> Any | None:
    """Derive a canonical GraphKey from metadata or the summary path."""

    from ..identity import GraphKey, IdentityError

    metadata = document.metadata
    story_id = str(metadata.get("story_id") or "").strip()
    timeline_id = str(metadata.get("timeline_id") or "").strip()
    if story_id or timeline_id:
        if not story_id or not timeline_id:
            raise SummaryError(
                f"摘要 {document.document_id} 的 metadata 必须同时提供 story_id/timeline_id"
            )
        try:
            return GraphKey(story_id, timeline_id)
        except (IdentityError, ValueError) as exc:
            raise SummaryError(f"摘要 {document.document_id} 的 GraphKey 无效: {exc}") from exc

    parts = document.path.resolve(strict=False).parts
    try:
        stories_index = parts.index("stories")
        story_id = parts[stories_index + 1]
    except (ValueError, IndexError) as exc:
        raise SummaryError(
            f"摘要 {document.document_id} 缺少 story_id/timeline_id，且路径无法确定 GraphKey"
        ) from exc
    timeline_id = "main"
    try:
        timeline_index = parts.index("timelines", stories_index + 1)
        timeline_id = parts[timeline_index + 1]
    except (ValueError, IndexError):
        # Legacy story summaries are scoped to the only supported default
        # timeline during migration.
        pass
    try:
        return GraphKey(story_id, timeline_id)
    except (IdentityError, ValueError) as exc:
        raise SummaryError(f"摘要 {document.document_id} 的路径 GraphKey 无效: {exc}") from exc


def _normalize_graph_keys(
    document: SummaryDocument,
    value: Callable[[SummaryDocument], Iterable[Any]] | Iterable[Any] | None,
) -> tuple[Any, ...]:
    raw = value(document) if callable(value) else value
    if raw is None:
        keys = (_path_graph_key(document),)
    else:
        keys = tuple(raw)
    if not keys or any(key is None for key in keys):
        raise SummaryError(
            f"摘要 {document.document_id} 必须声明至少一个 affected canonical GraphKey"
        )
    from ..identity import GraphKey

    invalid = [key for key in keys if not isinstance(key, GraphKey)]
    if invalid:
        raise SummaryError(
            f"摘要 {document.document_id} 的 affected_graph_keys 必须全部是 canonical GraphKey: {invalid!r}"
        )
    return tuple(dict.fromkeys(keys))


def _build_default_mutation_coordinator(
    summary_root: Path,
    *,
    library_root: Path | None,
    index_root: Path | None,
) -> Any:
    """Lazily load the production composition root and fail closed."""

    root = Path(library_root).resolve() if library_root is not None else _infer_library_root(summary_root)
    graph_index = Path(index_root).resolve() if index_root is not None else root / "index"
    try:
        from ..composition import build_mutation_coordinator
    except (ImportError, AttributeError) as exc:
        raise SummaryError(
            "默认 MutationCoordinator composition 不可用；摘要写入已拒绝，"
            "请提供显式 coordinator"
        ) from exc
    try:
        coordinator = build_mutation_coordinator(
            library_root=root,
            index_directory=graph_index,
        )
    except Exception as exc:
        raise SummaryError(f"无法建立摘要 MutationCoordinator: {exc}") from exc
    if not callable(getattr(coordinator, "commit", None)):
        raise SummaryError("默认 MutationCoordinator 缺少 commit()，摘要写入已拒绝")
    if not callable(getattr(coordinator, "graph_builder", None)):
        raise SummaryError("默认 MutationCoordinator 缺少 graph_builder，摘要写入已拒绝")

    # Keep the pre-catalog one-file summary layout usable during migration,
    # while retaining the composition-created coordinator and its
    # staged-YAML/GraphKey contract.  A real library always has the target
    # layout marker; an inferred root without one cannot be safely validated
    # as a corpus, so the compatibility builder creates only a clearly
    # isolated projection marker.  Explicit library_root never takes this
    # branch (callers must provide a canonical catalog or an adapter).
    if (
        library_root is None
        and isinstance(coordinator, MutationCoordinator)
        and not (root / "registry" / "layout.yaml").is_file()
    ):
        def build_legacy_fixture_graph(key: Any, staged: Any) -> GraphBuildArtifact:
            staged_path = (
                Path(staged.root)
                / "index"
                / "graphs"
                / key.story_id
                / f"{key.timeline_id}.db"
            )
            staged_path.parent.mkdir(parents=True, exist_ok=True)
            staged_path.write_text(
                f"summary compatibility projection: {key.story_id}/{key.timeline_id}\n",
                encoding="utf-8",
            )
            return GraphBuildArtifact(
                key=key,
                staged_path=staged_path,
                target_path=key.graph_path(graph_index),
            )

        coordinator.validate_staged = None
        coordinator.graph_builder = build_legacy_fixture_graph
        coordinator.current_fingerprint = None
        coordinator.target_resolver = lambda key: key.graph_path(graph_index)
    return coordinator


def _build_default_source_mutation_coordinator(
    summary_root: Path,
    *,
    library_root: Path | None,
) -> Any:
    """依赖：mutations.source唯一单源工厂。输入：摘要目录与可选库根。输出：只提交来源 YAML 的 coordinator。实现：延迟导入并校验 commit 接口。"""

    root = Path(library_root).resolve() if library_root is not None else _infer_library_root(summary_root)
    try:
        from .source import build_source_mutation_coordinator
    except (ImportError, AttributeError) as exc:
        raise SummaryError(
            "默认 source-only MutationCoordinator 工厂不可用；摘要写入已拒绝，"
            "请提供显式 coordinator"
        ) from exc
    try:
        coordinator = build_source_mutation_coordinator(library_root=root)
    except Exception as exc:
        raise SummaryError(f"无法建立 source-only 摘要 MutationCoordinator: {exc}") from exc
    if not callable(getattr(coordinator, "commit", None)):
        raise SummaryError("默认 source-only MutationCoordinator 缺少 commit()，摘要写入已拒绝")
    return coordinator


class SummaryEditor:
    """Concrete optimistic-concurrency editor for frontend requests."""

    def __init__(
        self,
        summary_root: str | Path,
        *,
        coordinator: MutationCoordinator | Any | None = None,
        library_root: str | Path | None = None,
        index_root: str | Path | None = None,
        affected_graph_keys: Callable[[SummaryDocument], Iterable[Any]] | Iterable[Any] | None = None,
        source_only: bool = False,
    ) -> None:
        """依赖：SummaryStore 与对应 composition factory。输入：摘要根、coordinator 配置及 source-only 策略。输出：可提交编辑的服务。实现：保留 v2 默认装配，v3 显式绕过 graph-builder 要求。"""

        self.store = SummaryStore(summary_root)
        self._auto_coordinator = coordinator is None
        self.source_only = source_only
        self.library_root = Path(library_root).resolve() if library_root is not None else None
        self.index_root = Path(index_root).resolve() if index_root is not None else None
        if coordinator is not None:
            self.coordinator = coordinator
        elif self.source_only:
            self.coordinator = _build_default_source_mutation_coordinator(
                self.store.root,
                library_root=self.library_root,
            )
        else:
            self.coordinator = _build_default_mutation_coordinator(
                self.store.root,
                library_root=self.library_root,
                index_root=self.index_root,
            )
        if not callable(getattr(self.coordinator, "commit", None)):
            raise SummaryError("SummaryEditor coordinator 缺少 commit()")
        if (
            self._auto_coordinator
            and not self.source_only
            and not callable(getattr(self.coordinator, "graph_builder", None))
        ):
            raise SummaryError("SummaryEditor coordinator 缺少 graph_builder，摘要写入已拒绝")
        self.affected_graph_keys = affected_graph_keys

    def update(self, change: SummaryUpdate) -> SummaryDocument:
        """依赖：SummaryStore、ChangeSet 与 MutationCoordinator。输入：带 expected_revision 的用户编辑。输出：已保存摘要候选。实现：同快照校验 revision/文件指纹，再保守更新所有权并提交。"""

        current = self.store.find(change.document_id)
        if change.expected_fingerprint is not None and current.file_fingerprint != change.expected_fingerprint:
            raise SummaryConflictError("revision_conflict: 摘要实际文件已改变")
        if current.revision != change.expected_revision:
            raise SummaryConflictError(
                f"摘要 revision 冲突: {change.document_id} 当前为 {current.revision}，"
                f"请求为 {change.expected_revision}"
            )
        updated = current.with_content(
            change.content,
            ownership="user",
            revision=current.revision + 1,
            stale=False,
        )
        if current.metadata.get("memory_kind") == "memory_projection":
            updated_metadata = dict(updated.metadata)
            updated_metadata["memory_kind"] = "author_note"
            updated = replace(updated, metadata=updated_metadata)
        updated = replace(updated, file_fingerprint=None)
        keys = self._keys_for(updated)
        if current.file_fingerprint is None:
            raise SummaryError(f"摘要缺少读取快照指纹: {current.path}")
        changeset = ChangeSet(
            changes={current.path: updated.to_payload()},
            affected_graph_keys=keys,
            expected_file_fingerprints={current.path: current.file_fingerprint},
            metadata={"summary_update": True, "document_id": current.document_id},
        )
        result = self.coordinator.commit(changeset)
        self._require_yaml_commit(result, "摘要用户编辑")
        return updated

    def _keys_for(self, document: SummaryDocument) -> tuple[Any, ...]:
        """依赖：摘要 scope 解析。输入：SummaryDocument。输出：失效 GraphKey 元组。实现：source-only 不产生图失效，其余委托 v2 归一化器。"""

        if self.source_only:
            return ()
        return _normalize_graph_keys(document, self.affected_graph_keys)

    @staticmethod
    def _require_yaml_commit(result: Any, operation: str) -> None:
        status = str(getattr(result, "status", "") or "").lower()
        graph_results = tuple(getattr(result, "graph_results", ()) or ())
        pending = tuple(item for item in graph_results if str(getattr(item, "status", "")).lower() == "pending")
        failed = tuple(item for item in graph_results if str(getattr(item, "status", "")).lower() == "failed")
        if status == "pending" or pending:
            detail = "; ".join(
                f"{getattr(item, 'key', '<unknown>')}: {getattr(item, 'error', '') or 'pending'}"
                for item in pending
            ) or "部分 GraphKey promotion pending"
            raise SummaryMutationPendingError(
                f"{operation}状态为 pending，YAML 可能已提交但图尚未全部提升: {detail}",
                result,
            )
        if status == "failed" or failed or not bool(getattr(result, "yaml_committed", False)):
            detail = getattr(result, "error", None) or "; ".join(
                f"{getattr(item, 'key', '<unknown>')}: {getattr(item, 'error', '') or 'failed'}"
                for item in failed
            ) or "未知错误"
            raise SummaryMutationFailedError(f"{operation}失败（status={status or 'unknown'}）: {detail}", result)
        if status not in {"promoted", "noop"}:
            raise SummaryError(f"{operation}返回未知 mutation status: {status or 'unknown'}")


class SummaryWriter:
    """Write AI summaries without overwriting user-owned revisions."""

    def __init__(
        self,
        summary_root: str | Path,
        *,
        coordinator: MutationCoordinator | Any | None = None,
        library_root: str | Path | None = None,
        index_root: str | Path | None = None,
        affected_graph_keys: Callable[[SummaryDocument], Iterable[Any]] | Iterable[Any] | None = None,
        source_only: bool = False,
    ) -> None:
        """依赖：SummaryStore 与对应 composition factory。输入：摘要根、coordinator 配置及 source-only 策略。输出：可提交自动摘要的服务。实现：保留 v2 默认装配，v3 显式绕过 graph-builder 要求。"""

        self.store = SummaryStore(summary_root)
        self._auto_coordinator = coordinator is None
        self.source_only = source_only
        self.library_root = Path(library_root).resolve() if library_root is not None else None
        self.index_root = Path(index_root).resolve() if index_root is not None else None
        if coordinator is not None:
            self.coordinator = coordinator
        elif self.source_only:
            self.coordinator = _build_default_source_mutation_coordinator(
                self.store.root,
                library_root=self.library_root,
            )
        else:
            self.coordinator = _build_default_mutation_coordinator(
                self.store.root,
                library_root=self.library_root,
                index_root=self.index_root,
            )
        if not callable(getattr(self.coordinator, "commit", None)):
            raise SummaryError("SummaryWriter coordinator 缺少 commit()")
        if (
            self._auto_coordinator
            and not self.source_only
            and not callable(getattr(self.coordinator, "graph_builder", None))
        ):
            raise SummaryError("SummaryWriter coordinator 缺少 graph_builder，摘要写入已拒绝")
        self.affected_graph_keys = affected_graph_keys

    def write_ai(
        self,
        path: str | Path,
        content: str,
        *,
        document_id: str | None = None,
        source_fingerprint: str | None = None,
        metadata: Mapping[str, Any] | None = None,
        affected_graph_keys: Iterable[Any] | None = None,
    ) -> SummaryDocument:
        """依赖：SummaryDocument 快照与 MutationCoordinator。输入：目标路径、生成文本和可选摘要元数据。输出：已保存的自动摘要。实现：同一源快照读取 ownership/revision/hash，并用文件 CAS 提交。"""

        target = Path(path)
        existing: SummaryDocument | None = SummaryDocument.from_yaml(target) if target.exists() else None
        if existing is not None:
            if existing.ownership == "user":
                raise SummaryOwnershipError(
                    f"自动摘要不得覆盖 ownership=user 的摘要: {existing.document_id}"
                )
            if existing.file_fingerprint is None:
                raise SummaryError(f"摘要缺少读取快照指纹: {target}")
        base_metadata = dict(existing.metadata if existing is not None else {})
        base_metadata.update(dict(metadata or {}))
        resolved_id = document_id or (existing.document_id if existing is not None else target.stem)
        if not base_metadata.get("story_id") or not base_metadata.get("timeline_id"):
            inferred = _path_graph_key(
                SummaryDocument(
                    path=target,
                    document_id=resolved_id,
                    content=content,
                    metadata=base_metadata,
                )
            )
            base_metadata.setdefault("story_id", inferred.story_id)
            base_metadata.setdefault("timeline_id", inferred.timeline_id)
        base_metadata.setdefault("document_type", "chapter-summary")
        base_metadata.setdefault("title", resolved_id)
        base_metadata.setdefault("status", "active")
        base_metadata.setdefault("version", "1.0")
        updated = SummaryDocument(
            path=target,
            document_id=resolved_id,
            content=content,
            ownership="auto",
            source_fingerprint=source_fingerprint if source_fingerprint is not None else (
                existing.source_fingerprint if existing is not None else None
            ),
            revision=(existing.revision + 1 if existing is not None else 1),
            stale=False,
            metadata=base_metadata,
        )
        if self.source_only:
            keys = ()
        else:
            keys = self._keys_for(updated) if affected_graph_keys is None else _normalize_graph_keys(
                updated,
                affected_graph_keys,
            )
        expected_fingerprint = (
            existing.file_fingerprint if existing is not None else MISSING_FINGERPRINT
        )
        changeset = ChangeSet(
            changes={target: updated.to_payload()},
            affected_graph_keys=keys,
            expected_file_fingerprints={target: expected_fingerprint},
            metadata={"summary_update": True, "generated_by": "ai", "document_id": resolved_id},
        )
        result = self.coordinator.commit(changeset)
        SummaryEditor._require_yaml_commit(result, "AI 摘要写入")
        return updated

    write = write_ai

    def _keys_for(self, document: SummaryDocument) -> tuple[Any, ...]:
        """依赖：摘要 scope 解析。输入：SummaryDocument。输出：失效 GraphKey 元组。实现：source-only 不产生图失效，其余委托 v2 归一化器。"""

        if self.source_only:
            return ()
        return _normalize_graph_keys(document, self.affected_graph_keys)


def summary_usable_in_context(
    document: SummaryDocument,
    *,
    source_fingerprint: str | None = None,
) -> bool:
    """Explicit gate used by temporal retrieval consumers."""

    return document.for_context(source_fingerprint) is not None


def write_ai_summary(
    summary_root: str | Path,
    path: str | Path,
    content: str,
    *,
    document_id: str | None = None,
    source_fingerprint: str | None = None,
    metadata: Mapping[str, Any] | None = None,
    coordinator: MutationCoordinator | Any | None = None,
    library_root: str | Path | None = None,
    index_root: str | Path | None = None,
    affected_graph_keys: Iterable[Any] | None = None,
) -> SummaryDocument:
    """Functional façade for model adapters that only need one write call."""

    return SummaryWriter(
        summary_root,
        coordinator=coordinator,
        library_root=library_root,
        index_root=index_root,
        affected_graph_keys=affected_graph_keys,
    ).write_ai(
        path,
        content,
        document_id=document_id,
        source_fingerprint=source_fingerprint,
        metadata=metadata,
        affected_graph_keys=affected_graph_keys,
    )


__all__ = [
    "SummaryDocument",
    "SummaryEditor",
    "SummaryEditorProtocol",
    "SummaryStore",
    "SummaryUpdate",
    "SummaryWriter",
    "summary_usable_in_context",
    "write_ai_summary",
]
