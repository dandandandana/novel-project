"""作品单源提交策略；复用既有事务协调器与共享源锁，不装配生成或图业务。"""
from __future__ import annotations

from pathlib import Path
import shutil

from ..catalog.layout import LegacyLayoutMapper, NormalizedPath
from ..identity import GraphKey


_COMMON_EDIT_TYPES = frozenset({"canon", "summary", "scene-summary", "chapter-summary", "volume-summary"})


def source_projection_ignores(library_root: Path, directory: str, names: list[str]) -> set[str]:
    """依赖：标准库copytree过滤协议。输入：库根、当前目录和条目名。输出：本层排除名集合。实现：保留原index/暂存排除，跳过根源锁guard及任意位置的运行时保留名.writer.lock.guard，其余资料和guard后缀不受影响。"""
    ignored = shutil.ignore_patterns("index", ".mutation-*", ".writer.lock.guard")(directory, names)
    if Path(directory).resolve() == (Path(library_root) / ".novel-rag").resolve():
        ignored.add("mutation.lock.guard")
    return ignored


def require_source_write_scope(identity: NormalizedPath, scope: GraphKey, *, allow_common: bool = False) -> None:
    """依赖：目录映射器已核验的来源身份。输入：来源、请求作品线及是否允许共同资料。输出：None 或 scope_denied。实现：时间线必须精确匹配，共同资料仅限同作品的显式入口。"""
    if identity.scope == "timeline" and identity.graph_key == scope:
        return
    if allow_common and identity.scope == "common" and identity.story_id == scope.story_id:
        return
    target = identity.timeline_id or identity.scope
    raise ValueError(f"scope_denied: {scope.story_id}/{scope.timeline_id} 无权修改 {identity.story_id}/{target} 的正式资料")


def build_source_mutation_coordinator(library_root: Path, *, pre_commit=None, after_source_commit=None,
                                      write_scope: GraphKey | None = None, allow_common: bool = False):
    """依赖：既有Coordinator/源锁及目录映射器。输入：库根、锁内hook与可选写作用域。输出：v3单源提交器。实现：核验实际目标与待写YAML的身份、结构及写权限，不建图。"""
    from ..documents import load_document, read_yaml_snapshot, registered_story_ids, validate_document
    from ..catalog.timelines import load_timeline_registry
    from ..catalog.paths import timeline_registry_path
    from .coordinator import MutationCoordinator
    from .types import MISSING_FINGERPRINT, MutationConflictError

    root = Path(library_root).resolve()
    mapper = LegacyLayoutMapper(root)

    def validate_source(staged):
        """依赖：目录映射器、版本字节和注册表。输入：StagedChanges。输出：None 或校验异常。实现：锁内核验待写身份，scoped写入同时核对实际原件的归属及指纹。"""
        if len(staged.staged_files) != 1 or staged.changeset.affected_graph_keys:
            raise ValueError("source-only需要单源文件及空graph keys")
        for original, temporary in staged.staged_files.items():
            document = load_document(temporary)
            metadata = document.metadata
            identity = mapper.normalize_path(original, metadata=metadata)
            if identity.scope not in {"common", "timeline"}:
                raise ValueError("scope_denied: 正式目标不是作品资料")
            story_id = identity.story_id
            if story_id not in registered_story_ids(root):
                raise ValueError("scope_denied: 未注册作品")
            errors = validate_document(document)
            if errors or metadata.get("story_id") != story_id:
                raise ValueError("source_invalid: " + "；".join(errors or ["目标作品身份不符"]))
            kind = metadata["document_type"]
            if kind != "history" and kind not in _COMMON_EDIT_TYPES:
                raise ValueError("source_invalid: source-only仅作品源/参考容器")
            registry = load_timeline_registry(timeline_registry_path(root, story_id),
                                               expected_story_id=story_id,
                                               snapshot_root=root / "stories" / story_id)
            if identity.scope == "timeline":
                registry.get(identity.timeline_id)
            if write_scope is not None:
                edit_common = allow_common and kind in _COMMON_EDIT_TYPES
                require_source_write_scope(identity, write_scope, allow_common=edit_common)
                original_hash = staged.original_fingerprints[original]
                if original_hash != MISSING_FINGERPRINT:
                    snapshot = read_yaml_snapshot(original)
                    if snapshot.source_hash != original_hash:
                        raise MutationConflictError("revision_conflict: 验证写权限时正式源版本已改变")
                    current = load_document(original, snapshot=snapshot)
                    current_identity = mapper.normalize_path(original, metadata=current.metadata)
                    edit_current_common = edit_common and current.metadata.get("document_type") in _COMMON_EDIT_TYPES
                    require_source_write_scope(current_identity, write_scope, allow_common=edit_current_common)
                    if (current_identity.scope, current_identity.graph_key) != (identity.scope, identity.graph_key):
                        raise ValueError("scope_denied: 不能通过替换同一来源改变它的归属")

    return MutationCoordinator(library_root=root, staging_root=root / ".novel-rag" / "staging",
                               lock_path=root / ".novel-rag" / "mutation.lock",
                               validate_staged=validate_source, pre_commit=pre_commit,
                               after_source_commit=after_source_commit)
