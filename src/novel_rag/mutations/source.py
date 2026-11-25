"""作品单源提交策略；复用既有事务协调器与共享源锁，不装配生成或图业务。"""
from __future__ import annotations

from pathlib import Path
import shutil


def source_projection_ignores(library_root: Path, directory: str, names: list[str]) -> set[str]:
    """依赖：标准库copytree过滤协议。输入：库根、当前目录和条目名。输出：本层排除名集合。实现：保留原index/暂存排除，跳过根源锁guard及任意位置的运行时保留名.writer.lock.guard，其余资料和guard后缀不受影响。"""
    ignored = shutil.ignore_patterns("index", ".mutation-*", ".writer.lock.guard")(directory, names)
    if Path(directory).resolve() == (Path(library_root) / ".novel-rag").resolve():
        ignored.add("mutation.lock.guard")
    return ignored


def build_source_mutation_coordinator(library_root: Path, *, pre_commit=None, after_source_commit=None):
    """依赖：既有Coordinator/源锁/documents。输入：库根及锁内hook。输出：v3单源提交器。实现：只验目标身份/schema/lineage，不建图；v2工厂保持原语义。"""
    from ..documents import load_document, registered_story_ids, validate_document
    from ..catalog.timelines import load_timeline_registry
    from ..catalog.paths import timeline_registry_path
    from .coordinator import MutationCoordinator

    root = Path(library_root).resolve()

    def validate_source(staged):
        """依赖：实际staged YAML/注册路径。输入：StagedChanges。输出：None/校验异常。实现：一次单文件权威提交并核物理scope/metadata/游标，不采用整库图门。"""
        if len(staged.staged_files) != 1 or staged.changeset.affected_graph_keys:
            raise ValueError("source-only需要单源文件及空graph keys")
        for original, temporary in staged.staged_files.items():
            relative = Path(original).resolve().relative_to(root)
            if len(relative.parts) < 4 or relative.parts[0] != "stories":
                raise ValueError("scope_denied: 正式目标不是作品资料")
            story_id = relative.parts[1]
            if story_id not in registered_story_ids(root):
                raise ValueError("scope_denied: 未注册作品")
            document = load_document(temporary)
            errors = validate_document(document)
            if errors or document.metadata.get("story_id") != story_id:
                raise ValueError("source_invalid: " + "；".join(errors or ["目标作品身份不符"]))
            metadata = document.metadata
            if metadata["document_type"] not in {"history", "canon", "summary", "scene-summary", "chapter-summary", "volume-summary"}:
                raise ValueError("source_invalid: source-only仅作品源/参考容器")
            registry = load_timeline_registry(timeline_registry_path(root, story_id),
                                               expected_story_id=story_id,
                                               snapshot_root=root / "stories" / story_id)
            if relative.parts[2] == "timelines":
                timeline_id = relative.parts[3]
                registry.get(timeline_id)
                if metadata["timeline_id"] != timeline_id:
                    raise ValueError("scope_denied: 物理时间线与metadata不符")
            elif relative.parts[2] != "common":
                # 兼容既有legacy main目标；不创建第二种布局。
                registry.get(str(metadata["timeline_id"]))

    return MutationCoordinator(library_root=root, staging_root=root / ".novel-rag" / "staging",
                               lock_path=root / ".novel-rag" / "mutation.lock",
                               validate_staged=validate_source, pre_commit=pre_commit,
                               after_source_commit=after_source_commit)
