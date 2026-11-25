"""Staged YAML and per-GraphKey mutation coordination."""

from __future__ import annotations

import os
import hashlib
import json
import re
import shutil
import tempfile
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

import yaml

from ..std.atomic_io import atomic_write_bytes, atomic_write_json
from .locks import MutationLock, ThreadMutationLock
from .types import (
    ChangeSet,
    GraphBuildArtifact,
    GraphMutationResult,
    MutationBuildError,
    MutationConflictError,
    MutationError,
    MutationLockError,
    MutationResult,
    MISSING_FINGERPRINT,
    StagedChanges,
    fingerprint_file,
)


class MutationCoordinator:
    """Coordinate staged YAML changes and independent graph promotions.

    Callbacks are deliberately storage-neutral:

    ``validate_staged(staged)`` validates the staged corpus;
    ``graph_builder(key, staged)`` returns a :class:`GraphBuildArtifact`; and
    ``retrieval_regression(key, artifact, staged)`` raises or returns false on
    a failed retrieval regression.  This lets the existing graph/catalog
    owners adapt their own builders without importing mutation internals.
    """

    def __init__(
        self,
        *,
        library_root: str | Path | None = None,
        staging_root: str | Path | None = None,
        validate_staged: Callable[[StagedChanges], Any] | None = None,
        validator: Callable[[StagedChanges], Any] | None = None,
        graph_builder: Callable[[Any, StagedChanges], Any] | None = None,
        build_graph: Callable[[Any, StagedChanges], Any] | None = None,
        retrieval_regression: Callable[[Any, GraphBuildArtifact, StagedChanges], Any] | None = None,
        regression: Callable[[Any, GraphBuildArtifact, StagedChanges], Any] | None = None,
        target_resolver: Callable[[Any], str | Path] | None = None,
        promote_graph: Callable[[Any, GraphBuildArtifact], Any] | None = None,
        current_fingerprint: Callable[[], str] | None = None,
        lock: MutationLock | None = None,
        lock_path: str | Path | None = None,
        pre_commit: Callable[[ChangeSet], ChangeSet | MutationResult | None] | None = None,
        after_source_commit: Callable[[StagedChanges], None] | None = None,
    ) -> None:
        """依赖：源锁/现有校验建图callbacks。输入：存储路径、策略及可选pre_commit。输出：Coordinator实例。实现：保留默认图链，hook在同一次源锁内执行。"""
        if validate_staged is not None and validator is not None:
            raise ValueError("validate_staged 与 validator 只能提供一个")
        if graph_builder is not None and build_graph is not None:
            raise ValueError("graph_builder 与 build_graph 只能提供一个")
        if retrieval_regression is not None and regression is not None:
            raise ValueError("retrieval_regression 与 regression 只能提供一个")
        if lock is not None and lock_path is not None:
            raise ValueError("lock 与 lock_path 只能提供一个")
        self.library_root = Path(library_root).resolve() if library_root is not None else None
        self.staging_root = Path(staging_root).resolve() if staging_root is not None else None
        self.validate_staged = validate_staged or validator
        self.graph_builder = graph_builder or build_graph
        self.retrieval_regression = retrieval_regression or regression
        self.target_resolver = target_resolver
        self.promote_graph = promote_graph
        self.current_fingerprint = current_fingerprint
        self.pre_commit = pre_commit
        self.after_source_commit = after_source_commit
        if lock_path is not None:
            from .locks import FileMutationLock

            self.lock = FileMutationLock(lock_path)
        else:
            self.lock = lock or ThreadMutationLock()
        self._pending_artifacts: dict[str, GraphBuildArtifact] = {}
        self._pending_roots: dict[str, Path] = {}
        self.pending_root = (
            (self.library_root / ".novel-rag" / "pending")
            if self.library_root is not None
            else None
        )

    def commit(self, changes: ChangeSet) -> MutationResult:
        """依赖：源锁/staging/校验/建图。输入：ChangeSet。输出：真实MutationResult。实现：一次锁域内可选预提交准备→指纹CAS→源提交→图提升，旧默认不变。"""

        if not isinstance(changes, ChangeSet):
            raise TypeError("MutationCoordinator.commit 需要 ChangeSet")
        # A caller may omit the id for a one-shot mutation.  Pending manifests
        # must still have a durable, collision-resistant identity.
        if not changes.change_id:
            from dataclasses import replace

            changes = replace(changes, change_id=uuid.uuid4().hex)
        with self._locked():
            if self.pre_commit is not None:
                prepared = self.pre_commit(changes)
                if isinstance(prepared, MutationResult):
                    return prepared
                if prepared is not None:
                    if not isinstance(prepared, ChangeSet):
                        raise TypeError("pre_commit需要返回ChangeSet/MutationResult/None")
                    changes = prepared
            baseline_global = self._check_initial_fingerprint(changes)
            original_paths = {self._target_path(path): path for path in changes.files}
            original_fingerprints = {
                target: fingerprint_file(target) for target in original_paths
            }
            self._check_expected_files(changes, original_fingerprints)
            stage_root = self._new_stage_root()
            try:
                staged = self._stage_changes(changes, stage_root, original_fingerprints)
                try:
                    self._run_validator(staged)
                except Exception as exc:
                    self._remove_stage_root(stage_root)
                    error = f"staged YAML 校验失败: {exc}"
                    return self._failed_result(
                        changes,
                        error,
                        tuple(
                            GraphMutationResult(key, "failed", error=error)
                            for key in changes.affected_graph_keys
                        ),
                    )
                artifacts, build_failure = self._build_all(changes, staged)
                if build_failure is not None:
                    self._cleanup_artifacts(artifacts.values())
                    self._remove_stage_root(stage_root)
                    return self._failed_result(
                        changes,
                        build_failure,
                        tuple(
                            GraphMutationResult(key, "failed", error=build_failure)
                            for key in changes.affected_graph_keys
                        ),
                    )
                self._assert_unchanged(changes, original_fingerprints, baseline_global)
                try:
                    self._commit_yaml(staged, original_fingerprints, baseline_global)
                except MutationConflictError:
                    self._cleanup_artifacts(artifacts.values())
                    self._remove_stage_root(stage_root)
                    raise
                except Exception as exc:
                    self._cleanup_artifacts(artifacts.values())
                    self._remove_stage_root(stage_root)
                    error = f"YAML 提交失败: {exc}"
                    return self._failed_result(
                        changes,
                        error,
                        tuple(
                            GraphMutationResult(key, "failed", error=error)
                            for key in changes.affected_graph_keys
                        ),
                    )
                if self.after_source_commit is not None:
                    self.after_source_commit(staged)
                return self._promote_all(changes, artifacts, stage_root)
            except MutationConflictError:
                self._remove_stage_root(stage_root)
                raise
            except MutationLockError:
                self._remove_stage_root(stage_root)
                raise
            except Exception:
                self._remove_stage_root(stage_root)
                raise

    def retry_pending(self, result: MutationResult | None = None) -> MutationResult | tuple[MutationResult, ...]:
        """Retry pending artifacts, optionally restoring them from disk.

        The original API accepted the in-memory ``MutationResult`` returned by
        :meth:`commit`.  Keeping that form preserves callers which still hold
        callback artifacts.  Omitting it is the durable recovery entry point;
        each pending manifest is loaded and retried independently.
        """

        if result is None:
            return self.retry_persisted_pending()
        if not isinstance(result, MutationResult):
            raise TypeError("retry_pending 需要 MutationResult")
        if not result.pending:
            return result
        with self._locked():
            refreshed: list[GraphMutationResult] = []
            still_pending = False
            has_failed = False
            for previous in result.graph_results:
                if not previous.pending:
                    refreshed.append(previous)
                    continue
                identity = self._key_id(previous.key)
                artifact = self._pending_artifacts.get(identity)
                if artifact is None:
                    has_failed = True
                    refreshed.append(
                        GraphMutationResult(
                            previous.key,
                            "failed",
                            previous.target_path,
                            previous.staged_path,
                            "pending artifact 不在当前 coordinator 中，且无法从 manifest 恢复",
                        )
                    )
                    continue
                try:
                    self._promote_artifact(artifact)
                    refreshed.append(
                        GraphMutationResult(
                            previous.key,
                            "promoted",
                            artifact.target_path,
                            artifact.staged_path,
                        )
                    )
                    self._cleanup_artifacts((artifact,))
                    self._pending_artifacts.pop(identity, None)
                except Exception as exc:
                    still_pending = True
                    refreshed.append(
                        GraphMutationResult(
                            previous.key,
                            "pending",
                            artifact.target_path,
                            artifact.staged_path,
                            str(exc),
                        )
                    )
            updated = MutationResult(
                status="pending" if still_pending else ("failed" if has_failed else "promoted"),
                graph_results=tuple(refreshed),
                yaml_committed=result.yaml_committed,
                change_id=result.change_id,
                staging_root=result.staging_root,
                error=("一个或多个 pending artifact 无法恢复" if has_failed else None),
            )
            manifest = self._manifest_path(result.change_id)
            if still_pending or has_failed:
                self._persist_result_manifest(manifest, updated)
                return updated
            root = result.staging_root
            if root is not None:
                self._remove_stage_root(root)
            self._pending_roots.pop(result.change_id, None)
            self._remove_pending_manifest(manifest)
            return updated

    def retry_persisted_pending(self) -> tuple[MutationResult, ...]:
        """Retry all recoverable pending manifests found in the library."""

        results: list[MutationResult] = []
        for payload in self.list_pending():
            change_id = str(payload.get("change_id") or "")
            if not change_id:
                continue
            payload = self._restore_pending_artifacts(payload)
            result = self._result_from_manifest(payload)
            if not result.pending:
                if result.status == "promoted":
                    self._remove_pending_manifest(self._manifest_path(change_id))
                results.append(result)
                continue
            retried = self.retry_pending(result)
            if isinstance(retried, tuple):
                # This branch is defensive; a single manifest always uses the
                # result-taking form above.
                results.extend(retried)
            else:
                results.append(retried)
        return tuple(results)

    def list_pending(self) -> list[dict[str, Any]]:
        """Return durable pending manifests for CLI/TUI observability."""

        if self.pending_root is None or not self.pending_root.is_dir():
            return []
        rows: list[dict[str, Any]] = []
        for path in sorted(self.pending_root.glob("*.json")):
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(value, dict):
                    raise ValueError("manifest 须为 mapping")
                value.setdefault("manifest_path", str(path))
                rows.append(value)
            except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
                rows.append({
                    "manifest_path": str(path),
                    "status": "invalid",
                    "error": f"无法读取 pending manifest: {exc}",
                })
        return rows

    # Friendly aliases for embedders that used the noun-oriented name.
    pending_manifests = list_pending

    @contextmanager
    def _locked(self):
        lock = self.lock
        if hasattr(lock, "__enter__"):
            with lock:
                yield
            return
        lock.acquire()
        try:
            yield
        finally:
            lock.release()

    def _target_path(self, raw_path: str | Path) -> Path:
        path = Path(raw_path)
        if not path.is_absolute() and self.library_root is not None:
            path = self.library_root / path
        path = path.resolve()
        if self.library_root is not None:
            try:
                path.relative_to(self.library_root)
            except ValueError as exc:
                raise MutationError(f"变更路径越过 library_root: {path}") from exc
        return path

    def _new_stage_root(self) -> Path:
        if self.staging_root is not None:
            self.staging_root.mkdir(parents=True, exist_ok=True)
            return Path(tempfile.mkdtemp(prefix=".mutation-", dir=str(self.staging_root)))
        parent = self.library_root or Path.cwd()
        parent.mkdir(parents=True, exist_ok=True)
        return Path(tempfile.mkdtemp(prefix=".mutation-", dir=str(parent)))

    def _stage_changes(
        self,
        changes: ChangeSet,
        stage_root: Path,
        original_fingerprints: Mapping[Path, str],
    ) -> StagedChanges:
        """序列化并原子写入变更暂存文件。

        依赖：目标路径解析、现有 YAML 序列化器与 atomic_write_bytes。
        输入：变更集、暂存根目录和原始指纹映射。
        输出：记录目标与暂存路径的 StagedChanges。
        实现：保持现有序列化结果，将字节落盘委托给共享原语。
        """
        staged_files: dict[Path, Path] = {}
        for raw_path, value in changes.changes.items():
            target = self._target_path(raw_path)
            if self.library_root is not None:
                relative = target.relative_to(self.library_root)
            else:
                relative = Path(target.name)
            staged_path = stage_root / relative
            staged_path.parent.mkdir(parents=True, exist_ok=True)
            payload = self._serialize_change(value)
            atomic_write_bytes(staged_path, payload)
            staged_files[target] = staged_path
        return StagedChanges(changes, stage_root, staged_files, original_fingerprints)

    @staticmethod
    def _serialize_change(value: Any) -> bytes:
        if isinstance(value, bytes):
            return value
        if isinstance(value, str):
            return value.encode("utf-8")
        return yaml.safe_dump(
            value,
            allow_unicode=True,
            sort_keys=False,
            default_flow_style=False,
        ).encode("utf-8")

    def _run_validator(self, staged: StagedChanges) -> None:
        if self.validate_staged is None:
            return
        result = self.validate_staged(staged)
        if result is False:
            raise MutationBuildError("staged YAML 校验失败")

    def _build_all(
        self,
        changes: ChangeSet,
        staged: StagedChanges,
    ) -> tuple[dict[str, GraphBuildArtifact], str | None]:
        if not changes.affected_graph_keys:
            return {}, None
        if self.graph_builder is None:
            return {}, "未配置 graph_builder"
        artifacts: dict[str, GraphBuildArtifact] = {}
        for key in changes.affected_graph_keys:
            try:
                built = self.graph_builder(key, staged)
                artifact = self._coerce_artifact(key, built)
                if not artifact.regression_passed:
                    raise MutationBuildError(f"GraphKey {key!r} retrieval regression 失败")
                if self.retrieval_regression is not None:
                    result = self.retrieval_regression(key, artifact, staged)
                    if result is False:
                        raise MutationBuildError(f"GraphKey {key!r} retrieval regression 失败")
                artifacts[self._key_id(key)] = artifact
            except Exception as exc:
                self._cleanup_artifacts(artifacts.values())
                return artifacts, f"GraphKey {key!r} 构建失败: {exc}"
        return artifacts, None

    def _coerce_artifact(self, key: Any, value: Any) -> GraphBuildArtifact:
        if isinstance(value, GraphBuildArtifact):
            if self._key_id(value.key) != self._key_id(key):
                raise MutationBuildError("GraphBuildArtifact.key 与请求 GraphKey 不一致")
            if value.target_path is None and self.target_resolver is not None:
                return GraphBuildArtifact(
                    key=value.key,
                    staged_path=value.staged_path,
                    target_path=Path(self.target_resolver(key)),
                    promote_callback=value.promote_callback,
                    cleanup_callback=value.cleanup_callback,
                    regression_passed=value.regression_passed,
                    metadata=value.metadata,
                )
            return value
        if isinstance(value, (str, Path)):
            target = Path(self.target_resolver(key)) if self.target_resolver is not None else None
            return GraphBuildArtifact(key, Path(value), target)
        if isinstance(value, Mapping):
            staged = value.get("staged_path", value.get("temporary_path"))
            target = value.get("target_path", value.get("path"))
            if staged is None and value.get("promoted"):
                raise MutationBuildError("graph_builder 返回了已提升图，必须返回 temporary/staged graph")
            return GraphBuildArtifact(
                key=key,
                staged_path=Path(staged) if staged is not None else None,
                target_path=Path(target) if target is not None else (
                    Path(self.target_resolver(key)) if self.target_resolver is not None else None
                ),
                promote_callback=value.get("promote_callback"),
                cleanup_callback=value.get("cleanup_callback"),
                regression_passed=bool(value.get("regression_passed", True)),
                metadata=value,
            )
        staged = getattr(value, "staged_path", None) or getattr(value, "temporary_path", None)
        target = getattr(value, "target_path", None)
        if staged is None and getattr(value, "promoted", False):
            raise MutationBuildError("graph_builder 返回了已提升图，必须返回 temporary/staged graph")
        if staged is None:
            raise MutationBuildError("graph_builder 必须返回 GraphBuildArtifact 或 staged path")
        return GraphBuildArtifact(
            key=key,
            staged_path=Path(staged),
            target_path=Path(target) if target is not None else (
                Path(self.target_resolver(key)) if self.target_resolver is not None else None
            ),
            promote_callback=getattr(value, "promote_callback", None),
            cleanup_callback=getattr(value, "cleanup_callback", None),
            regression_passed=bool(getattr(value, "regression_passed", True)),
        )

    def _assert_unchanged(
        self,
        changes: ChangeSet,
        original_fingerprints: Mapping[Path, str],
        baseline_global: str | None,
    ) -> None:
        if self.current_fingerprint is not None and baseline_global is not None:
            current = str(self.current_fingerprint())
            if current != baseline_global:
                raise MutationConflictError(
                    f"YAML source fingerprint 在建图期间变化: {baseline_global} -> {current}"
                )
        for target, original in original_fingerprints.items():
            current = fingerprint_file(target)
            if current != original:
                raise MutationConflictError(
                    f"YAML 在建图期间被外部修改: {target} ({original} -> {current})"
                )

    def _check_initial_fingerprint(self, changes: ChangeSet) -> str | None:
        if changes.expected_fingerprint is not None:
            if self.current_fingerprint is None:
                raise MutationConflictError("ChangeSet 要求 expected_fingerprint，但未配置 current_fingerprint")
            current = str(self.current_fingerprint())
            if current != str(changes.expected_fingerprint):
                raise MutationConflictError(
                    f"YAML source fingerprint 不匹配: {current} != {changes.expected_fingerprint}"
                )
            return current
        return str(self.current_fingerprint()) if self.current_fingerprint is not None else None

    def _check_expected_files(self, changes: ChangeSet, actual: Mapping[Path, str]) -> None:
        for raw_path, expected in changes.expected_file_fingerprints.items():
            path = self._target_path(raw_path)
            current = actual.get(path, fingerprint_file(path))
            if current != str(expected):
                raise MutationConflictError(
                    f"YAML 文件 fingerprint 不匹配: {path} ({current} != {expected})"
                )

    def _commit_yaml(
        self,
        staged: StagedChanges,
        original_fingerprints: Mapping[Path, str],
        baseline_global: str | None,
    ) -> None:
        # Check all files immediately before the first replace and each target
        # again immediately before its own replace.  The protocol deliberately
        # does not claim a multi-file global atomic commit.
        self._assert_unchanged(staged.changeset, original_fingerprints, baseline_global)
        for target, staged_path in staged.staged_files.items():
            if fingerprint_file(target) != original_fingerprints[target]:
                raise MutationConflictError(f"YAML 在提交前被外部修改: {target}")
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(staged_path, target)

    def _promote_all(
        self,
        changes: ChangeSet,
        artifacts: Mapping[str, GraphBuildArtifact],
        stage_root: Path,
    ) -> MutationResult:
        results: list[GraphMutationResult] = []
        manifest = self._manifest_path(changes.change_id)
        manifest_error: str | None = None
        if artifacts:
            try:
                self._write_pending_manifest(changes, artifacts, stage_root)
            except Exception as exc:
                # YAML has already committed.  Preserve every staged artifact
                # in memory and report pending rather than deleting accepted
                # work merely because observability storage was unavailable.
                manifest_error = f"无法持久化 pending manifest: {exc}"
        for key in changes.affected_graph_keys:
            artifact = artifacts[self._key_id(key)]
            if manifest_error is not None:
                identity = self._key_id(key)
                self._pending_artifacts[identity] = artifact
                self._pending_roots[changes.change_id] = stage_root
                results.append(
                    GraphMutationResult(
                        key,
                        "pending",
                        artifact.target_path,
                        artifact.staged_path,
                        manifest_error,
                    )
                )
                continue
            try:
                self._promote_artifact(artifact)
                results.append(GraphMutationResult(key, "promoted", artifact.target_path, artifact.staged_path))
                self._update_pending_manifest_entry(
                    manifest,
                    self._key_id(key),
                    status="promoted",
                    error=None,
                )
            except Exception as exc:
                identity = self._key_id(key)
                self._pending_artifacts[identity] = artifact
                self._pending_roots[changes.change_id] = stage_root
                results.append(
                    GraphMutationResult(
                        key,
                        "pending",
                        artifact.target_path,
                        artifact.staged_path,
                        str(exc),
                    )
                )
                self._update_pending_manifest_entry(
                    manifest,
                    identity,
                    status="pending",
                    error=str(exc),
                )
        if any(item.pending for item in results):
            if manifest_error is not None:
                # Best effort only: the primary result still contains the
                # precise diagnostic when a filesystem prevented persistence.
                try:
                    self._write_pending_manifest(
                        changes,
                        artifacts,
                        stage_root,
                        results=results,
                    )
                except Exception:
                    pass
            return MutationResult(
                status="pending",
                graph_results=tuple(results),
                yaml_committed=True,
                change_id=changes.change_id,
                staging_root=stage_root,
            )
        self._cleanup_artifacts(artifacts.values())
        self._remove_stage_root(stage_root)
        self._remove_pending_manifest(manifest)
        return MutationResult(
            status="promoted",
            graph_results=tuple(results),
            yaml_committed=True,
            change_id=changes.change_id,
        )

    def _manifest_path(self, change_id: str) -> Path | None:
        if self.pending_root is None or not change_id:
            return None
        safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(change_id))
        if safe != str(change_id) or not safe:
            safe = f"{safe or 'change'}-{hashlib.sha256(str(change_id).encode('utf-8')).hexdigest()[:12]}"
        return self.pending_root / f"{safe}.json"

    def _manifest_path_allowed(self, value: str | Path | None) -> bool:
        if value is None or self.library_root is None:
            return False
        try:
            Path(value).resolve().relative_to(self.library_root.resolve())
        except ValueError:
            return False
        return True

    @staticmethod
    def _key_payload(key: Any) -> dict[str, str] | None:
        story = getattr(key, "story_id", None)
        timeline = getattr(key, "timeline_id", None)
        if story is None or timeline is None:
            if isinstance(key, Mapping):
                story = key.get("story_id")
                timeline = key.get("timeline_id")
        if story is None or timeline is None:
            return None
        return {"story_id": str(story), "timeline_id": str(timeline)}

    @staticmethod
    def _manifest_now() -> tuple[str, float]:
        now = datetime.now(timezone.utc)
        return now.isoformat(), time.time()

    def _artifact_manifest_entry(
        self,
        key: Any,
        artifact: GraphBuildArtifact,
        *,
        status: str = "pending",
        error: str | None = None,
    ) -> dict[str, Any]:
        staged = str(artifact.staged_path) if artifact.staged_path is not None else None
        target = str(artifact.target_path) if artifact.target_path is not None else None
        mode = "callback" if artifact.promote_callback is not None or self.promote_graph is not None else "path"
        recoverable = (
            mode == "path"
            and staged is not None
            and target is not None
            and self._manifest_path_allowed(staged)
            and self._manifest_path_allowed(target)
        )
        return {
            "identity": self._key_id(key),
            "key": self._key_payload(key),
            "status": status,
            "staged_path": staged,
            "target_path": target,
            "staged_fingerprint": fingerprint_file(artifact.staged_path) if artifact.staged_path is not None else None,
            "promotion_mode": mode,
            "recoverable": recoverable,
            "error": error,
            "metadata": dict(artifact.metadata),
        }

    def _write_pending_manifest(
        self,
        changes: ChangeSet,
        artifacts: Mapping[str, GraphBuildArtifact],
        stage_root: Path,
        *,
        results: Iterable[GraphMutationResult] | None = None,
    ) -> Path | None:
        path = self._manifest_path(changes.change_id)
        if path is None:
            return None
        result_map = {self._key_id(item.key): item for item in (results or ())}
        entries = []
        for key in changes.affected_graph_keys:
            identity = self._key_id(key)
            result = result_map.get(identity)
            entries.append(
                self._artifact_manifest_entry(
                    key,
                    artifacts[identity],
                    status=result.status if result is not None else "pending",
                    error=result.error if result is not None else None,
                )
            )
        created_at, created_epoch = self._manifest_now()
        payload = {
            "schema_version": 1,
            "kind": "novel-rag-pending-mutation",
            "change_id": changes.change_id,
            "created_at": created_at,
            "created_at_epoch": created_epoch,
            "updated_at": created_at,
            "yaml_committed": True,
            "staging_root": str(stage_root),
            "status": "pending",
            "entries": entries,
            "metadata": dict(changes.metadata),
        }
        self._atomic_write_json(path, payload)
        return path

    @staticmethod
    def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
        """兼容旧调用并委托共享 JSON 写入口。

        依赖：模块级 atomic_write_json。
        输入：目标 Path 和 JSON 映射。
        输出：成功写入后返回 None。
        实现：保留旧静态方法签名，不复制序列化或临时文件逻辑。
        """
        atomic_write_json(path, payload)

    def _update_pending_manifest_entry(
        self,
        manifest: Path | None,
        identity: str,
        *,
        status: str,
        error: str | None,
    ) -> None:
        if manifest is None or not manifest.exists():
            return
        try:
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                return
            entries = payload.get("entries")
            if not isinstance(entries, list):
                return
            for entry in entries:
                if isinstance(entry, dict) and entry.get("identity") == identity:
                    entry["status"] = status
                    entry["error"] = error
                    break
            statuses = [entry.get("status") for entry in entries if isinstance(entry, dict)]
            payload["status"] = (
                "pending" if "pending" in statuses
                else "failed" if "failed" in statuses
                else "promoted"
            )
            payload["updated_at"], _ = self._manifest_now()
            self._atomic_write_json(manifest, payload)
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
            # Promotion has already happened; a later durable retry/list can
            # still expose the original manifest.  Never turn a successful
            # graph promotion into a destructive cleanup because observability
            # itself was temporarily unavailable.
            return

    def _persist_result_manifest(self, manifest: Path | None, result: MutationResult) -> None:
        if manifest is None:
            return
        try:
            if manifest.exists():
                payload = json.loads(manifest.read_text(encoding="utf-8"))
            else:
                payload = {
                    "schema_version": 1,
                    "kind": "novel-rag-pending-mutation",
                    "change_id": result.change_id,
                    "created_at": self._manifest_now()[0],
                    "yaml_committed": result.yaml_committed,
                    "staging_root": str(result.staging_root) if result.staging_root else None,
                    "entries": [],
                }
            if not isinstance(payload, dict):
                raise ValueError("manifest 须为 mapping")
            existing = {
                str(item.get("identity")): item
                for item in payload.get("entries", ())
                if isinstance(item, dict) and item.get("identity") is not None
            }
            entries = []
            for item in result.graph_results:
                entry = existing.get(self._key_id(item.key), {
                    "identity": self._key_id(item.key),
                    "key": self._key_payload(item.key),
                    "promotion_mode": "path",
                    "recoverable": self._manifest_path_allowed(item.staged_path)
                    and self._manifest_path_allowed(item.target_path),
                })
                entry.update({
                    "status": item.status,
                    "staged_path": str(item.staged_path) if item.staged_path is not None else entry.get("staged_path"),
                    "target_path": str(item.target_path) if item.target_path is not None else entry.get("target_path"),
                    "error": item.error,
                })
                entries.append(entry)
            payload.update({
                "change_id": result.change_id,
                "yaml_committed": result.yaml_committed,
                "staging_root": str(result.staging_root) if result.staging_root else payload.get("staging_root"),
                "status": result.status,
                "updated_at": self._manifest_now()[0],
                "entries": entries,
                "error": result.error,
            })
            self._atomic_write_json(manifest, payload)
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
            return

    @staticmethod
    def _graph_key_from_payload(value: Any) -> Any:
        if not isinstance(value, Mapping):
            raise ValueError("pending manifest 缺少 GraphKey identity")
        from ..identity import GraphKey

        return GraphKey(str(value["story_id"]), str(value["timeline_id"]))

    def _result_from_manifest(self, payload: Mapping[str, Any]) -> MutationResult:
        rows: list[GraphMutationResult] = []
        for entry in payload.get("entries", ()):
            if not isinstance(entry, Mapping):
                continue
            try:
                key = self._graph_key_from_payload(entry.get("key"))
            except (KeyError, TypeError, ValueError):
                continue
            rows.append(
                GraphMutationResult(
                    key,
                    str(entry.get("status") or "failed"),
                    Path(entry["target_path"]) if entry.get("target_path") else None,
                    Path(entry["staged_path"]) if entry.get("staged_path") else None,
                    str(entry["error"]) if entry.get("error") else None,
                )
            )
        status = str(payload.get("status") or "pending")
        return MutationResult(
            status=status,
            graph_results=tuple(rows),
            yaml_committed=bool(payload.get("yaml_committed", True)),
            change_id=str(payload.get("change_id") or ""),
            staging_root=Path(payload["staging_root"]) if payload.get("staging_root") else None,
            error=str(payload["error"]) if payload.get("error") else None,
        )

    def _restore_pending_artifacts(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Restore path-based artifacts and reconcile idempotent promotions."""

        restored = dict(payload)
        entries = [dict(entry) for entry in payload.get("entries", ()) if isinstance(entry, Mapping)]
        changed = False
        change_id = str(payload.get("change_id") or "")
        for entry in entries:
            if entry.get("status") != "pending":
                continue
            if entry.get("promotion_mode") != "path" or not entry.get("recoverable", False):
                continue
            staged_raw = entry.get("staged_path")
            target_raw = entry.get("target_path")
            if not self._manifest_path_allowed(staged_raw) or not self._manifest_path_allowed(target_raw):
                continue
            staged = Path(str(staged_raw)).resolve()
            target = Path(str(target_raw)).resolve()
            expected = entry.get("staged_fingerprint")
            if not staged.exists() and target.exists() and expected and fingerprint_file(target) == expected:
                entry["status"] = "promoted"
                entry["error"] = None
                changed = True
                continue
            if not staged.exists():
                continue
            key = self._graph_key_from_payload(entry.get("key"))
            self._pending_artifacts[self._key_id(key)] = GraphBuildArtifact(
                key=key,
                staged_path=staged,
                target_path=target,
                metadata=entry.get("metadata") if isinstance(entry.get("metadata"), Mapping) else {},
            )
            if change_id and payload.get("staging_root"):
                self._pending_roots[change_id] = Path(str(payload["staging_root"]))
        if changed:
            statuses = [entry.get("status") for entry in entries]
            restored["entries"] = entries
            restored["status"] = (
                "pending" if "pending" in statuses
                else "failed" if "failed" in statuses
                else "promoted"
            )
            restored["updated_at"] = self._manifest_now()[0]
            manifest = self._manifest_path(change_id)
            if manifest is not None:
                try:
                    self._atomic_write_json(manifest, restored)
                except OSError:
                    pass
        return restored

    def _remove_pending_manifest(self, manifest: Path | None) -> None:
        if manifest is None:
            return
        try:
            manifest.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            # A completed promotion remains safe; leave the manifest for
            # ``pending list`` to surface rather than masking the result.
            pass

    def _promote_artifact(self, artifact: GraphBuildArtifact) -> None:
        if artifact.promote_callback is not None:
            result = artifact.promote_callback()
            if result is False:
                raise MutationError("graph promote callback 返回失败")
            return
        if self.promote_graph is not None:
            result = self.promote_graph(artifact.key, artifact)
            if result is False:
                raise MutationError("promote_graph callback 返回失败")
            return
        if artifact.staged_path is None or artifact.target_path is None:
            raise MutationError("GraphBuildArtifact 缺少 staged_path/target_path 或 promote callback")
        if not artifact.staged_path.exists():
            raise MutationError(f"staged graph 不存在: {artifact.staged_path}")
        artifact.target_path.parent.mkdir(parents=True, exist_ok=True)
        if artifact.staged_path.resolve() != artifact.target_path.resolve():
            os.replace(artifact.staged_path, artifact.target_path)

    @staticmethod
    def _cleanup_artifacts(artifacts: Iterable[GraphBuildArtifact]) -> None:
        for artifact in artifacts:
            if artifact.cleanup_callback is not None:
                try:
                    artifact.cleanup_callback()
                except Exception:
                    pass
            if artifact.staged_path is not None:
                try:
                    artifact.staged_path.unlink()
                except (FileNotFoundError, OSError):
                    pass

    @staticmethod
    def _remove_stage_root(root: Path) -> None:
        try:
            shutil.rmtree(root)
        except (FileNotFoundError, OSError):
            pass

    @staticmethod
    def _key_id(key: Any) -> str:
        story = getattr(key, "story_id", None)
        timeline = getattr(key, "timeline_id", None)
        if story is not None or timeline is not None:
            return f"{story}/{timeline}"
        if isinstance(key, Mapping):
            return f"{key.get('story_id')}/{key.get('timeline_id')}"
        return repr(key)

    @staticmethod
    def _failed_result(
        changes: ChangeSet,
        error: str,
        graph_results: tuple[GraphMutationResult, ...],
    ) -> MutationResult:
        return MutationResult(
            status="failed",
            graph_results=graph_results,
            yaml_committed=False,
            change_id=changes.change_id,
            error=error,
        )


__all__ = ["MutationCoordinator"]
