"""Shared-system graph projection and read-only reader."""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from ..chunking import chunk_text
from ..layout import SHARED_STORY_ID, SHARED_TIMELINE_ID
from .builder import _document_metadata_and_content
from .corpus import corpus_documents, corpus_module_references, metadata_of
from ..identity import GraphKey
from .corpus import require_validated_corpus
from .fingerprint import corpus_fingerprint, database_fingerprint
from .reader import open_read_only
from .schema import (
    SHARED_SCHEMA_VERSION,
    create_schema,
    probe_trigram,
    verify_integrity,
    verify_schema,
)
from .types import (
    DocumentHit,
    GraphBuildError,
    GraphBuildResult,
    GraphReadError,
    SharedManifest,
    SharedModuleHit,
    ModuleGraphIndex,
)


def shared_path(index_root_or_target: Path) -> Path:
    value = Path(index_root_or_target)
    if value.suffix:
        candidate = value.resolve()
        if candidate.name != "shared.db":
            raise ValueError("shared target 必须是 canonical shared.db 路径")
        return candidate
    return (value / "shared.db").resolve()


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _derived_references(corpus: Any) -> tuple[dict[str, Any], ...]:
    explicit = list(corpus_module_references(corpus))
    if explicit:
        return tuple(explicit)
    result: list[dict[str, Any]] = []
    module_types = {"rule": "ruler", "judgment_spec": "judgment", "generator_spec": "generator", "audit_spec": "audit", "style_audit": "style"}
    for document in corpus_documents(corpus):
        metadata = metadata_of(document)
        document_id, _metadata, _content, source_file = _document_metadata_and_content(document)
        module_type = str(metadata.get("module_type") or module_types.get(str(metadata.get("document_type", "")), ""))
        if module_type:
            result.append(
                {
                    "module_type": module_type,
                    "document_id": document_id,
                    "version": str(metadata.get("version", "")),
                    "source_file": source_file,
                }
            )
    return tuple(
        sorted(result, key=lambda row: (row["module_type"], row["document_id"], row["version"]))
    )


def _insert_shared_documents(connection: sqlite3.Connection, documents: tuple[Any, ...]) -> int:
    document_count = 0
    for document in documents:
        document_id, metadata, content, source_file = _document_metadata_and_content(document)
        story_id = str(metadata.get("story_id", ""))
        timeline_id = str(metadata.get("timeline_id", ""))
        if (story_id, timeline_id) != (SHARED_STORY_ID, SHARED_TIMELINE_ID):
            raise GraphBuildError(
                "shared 图只能包含 __shared__/global 文档: "
                f"{story_id}/{timeline_id}"
            )
        connection.execute(
            """INSERT INTO documents(
                document_id, source_file, story_id, timeline_id, document_type,
                status, version, title, metadata_json, content
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                document_id,
                source_file,
                story_id,
                timeline_id,
                str(metadata.get("document_type", "")),
                str(metadata.get("status", "")),
                str(metadata.get("version", "")),
                str(metadata.get("title", "")),
                json.dumps(metadata, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                content,
            ),
        )
        for chunk in chunk_text(content):
            connection.execute(
                "INSERT INTO chunks_fts(chunk_id, document_id, content) VALUES (?, ?, ?)",
                (f"{document_id}:{chunk.ordinal}", document_id, chunk.text),
            )
        document_count += 1
    return document_count


class SharedBuilder:
    """Build and atomically promote the independent shared-system index."""

    def __init__(
        self,
        corpus: Any,
        target: Path | None = None,
        *,
        index_root: Path | None = None,
        module_references: Any = None,
        retrieval_regression: Callable[["SharedReader"], Any] | None = None,
        regression_gate: Callable[["SharedReader"], Any] | None = None,
        regression: Callable[["SharedReader"], Any] | None = None,
    ) -> None:
        self.corpus = require_validated_corpus(corpus)
        if target is None and index_root is None:
            raise ValueError("必须提供 target 或 index_root")
        self.target = shared_path(Path(target if target is not None else index_root))
        if module_references is None:
            self._module_references = _derived_references(corpus)
        else:
            self._module_references = tuple(
                corpus_module_references({"module_references": module_references})
            )
        self.retrieval_regression = retrieval_regression or regression_gate or regression

    def build(self) -> GraphBuildResult:
        final_path = self.target.resolve()
        final_path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(
            prefix=f".{final_path.stem}.", suffix=".tmp", dir=str(final_path.parent)
        )
        os.close(fd)
        temp_path = Path(temp_name)
        promotion_started = False
        try:
            connection = sqlite3.connect(temp_path)
            try:
                with connection:
                    create_schema(connection, shared=True)
                    documents = corpus_documents(self.corpus)
                    document_count = _insert_shared_documents(connection, documents)
                    for reference in self._module_references:
                        connection.execute(
                            """INSERT INTO module_references(
                                module_type, document_id, version, source_file, metadata_json
                            ) VALUES (?, ?, ?, ?, ?)""",
                            (
                                str(reference.get("module_type", "")),
                                str(reference.get("document_id", "")),
                                str(reference.get("version", "")),
                                str(reference.get("source_file", "")),
                                json.dumps(reference, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                            ),
                        )
                    manifest = SharedManifest(
                        schema_version=SHARED_SCHEMA_VERSION,
                        story_id=SHARED_STORY_ID,
                        timeline_id=SHARED_TIMELINE_ID,
                        source_fingerprint=corpus_fingerprint(self.corpus),
                        built_at=_now(),
                        document_count=document_count,
                        module_reference_count=len(self._module_references),
                        source_root=(str(self.corpus.root) if self.corpus.root is not None else None),
                    )
                    connection.execute(
                        """INSERT INTO shared_manifest(
                            id, schema_version, story_id, timeline_id, source_fingerprint,
                            built_at, document_count, module_reference_count, source_root
                        ) VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            manifest.schema_version,
                            manifest.story_id,
                            manifest.timeline_id,
                            manifest.source_fingerprint,
                            manifest.built_at,
                            manifest.document_count,
                            manifest.module_reference_count,
                            manifest.source_root or "",
                        ),
                    )
            finally:
                connection.close()
            with SharedReader(
                temp_path,
                expected_fingerprint=manifest.source_fingerprint,
            ) as reader:
                verify_integrity(reader.connection)
                if self.retrieval_regression is not None:
                    self.retrieval_regression(reader)
            promotion_started = True
            os.replace(temp_path, final_path)
            return GraphBuildResult(path=final_path, manifest=manifest, promoted=True)
        except Exception as exc:
            if not promotion_started and temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    pass
            if isinstance(exc, GraphBuildError):
                raise
            raise GraphBuildError(f"shared 图构建失败: {exc}") from exc

    build_shared = build


class SharedReader:
    """Read-only reader for ``index/shared.db``."""

    @classmethod
    def from_corpus(cls, path: Path, corpus: Any, **kwargs: Any) -> "SharedReader":
        """Open shared.db with an explicit canonical corpus freshness proof."""

        return cls(path, expected_key=GraphKey.shared(), corpus=corpus, **kwargs)

    open = from_corpus

    def __init__(
        self,
        path: Path,
        *,
        expected_key: Any | None = None,
        expected_fingerprint: str | None = None,
        expected_source_fingerprint: str | None = None,
        corpus: Any | None = None,
    ) -> None:
        self.path = Path(path)
        if self.path.suffix and self.path.name != "shared.db" and self.path.suffix != ".tmp":
            raise GraphReadError("SharedReader 必须打开 canonical shared.db 路径")
        if expected_source_fingerprint is not None:
            if expected_fingerprint is not None and expected_fingerprint != expected_source_fingerprint:
                raise GraphReadError("expected_fingerprint 与 expected_source_fingerprint 冲突")
            expected_fingerprint = expected_source_fingerprint
        self._expected_key = GraphKey.shared()
        if expected_key is not None:
            try:
                candidate = expected_key if isinstance(expected_key, GraphKey) else GraphKey(
                    str(expected_key.story_id), str(expected_key.timeline_id)
                )
            except (AttributeError, ValueError) as exc:
                raise GraphReadError(f"shared expected_key 无效: {exc}") from exc
            if candidate != self._expected_key:
                raise GraphReadError("shared reader 必须使用 GraphKey.shared()")
        if corpus is not None:
            try:
                corpus_fingerprint_value = corpus_fingerprint(corpus)
            except Exception as exc:
                raise GraphReadError(f"无法计算 scoped shared corpus fingerprint: {exc}") from exc
            if expected_fingerprint is not None and expected_fingerprint != corpus_fingerprint_value:
                raise GraphReadError("expected_fingerprint 与 scoped shared corpus 不一致")
            expected_fingerprint = corpus_fingerprint_value
        self._expected_fingerprint = expected_fingerprint
        self._connection = open_read_only(self.path)
        try:
            verify_schema(self._connection, shared=True)
            verify_integrity(self._connection)
            if not probe_trigram():
                raise GraphReadError("当前 SQLite 缺少可用的 FTS5 trigram")
            self._manifest = self._load_manifest()
            if self._manifest.schema_version != SHARED_SCHEMA_VERSION:
                raise GraphReadError(
                    f"shared schema_version 不受支持: {self._manifest.schema_version!r}"
                )
            if not self._manifest.source_fingerprint.startswith("sha256:"):
                raise GraphReadError("shared_manifest source_fingerprint 必须是 sha256")
            if (self._manifest.story_id, self._manifest.timeline_id) != (
                SHARED_STORY_ID,
                SHARED_TIMELINE_ID,
            ):
                raise GraphReadError("shared_manifest 身份不正确")
            try:
                if GraphKey(self._manifest.story_id, self._manifest.timeline_id) != self._expected_key:
                    raise GraphReadError("shared_manifest 身份与 GraphKey.shared() 不一致")
            except ValueError as exc:
                raise GraphReadError(f"shared_manifest 身份无效: {exc}") from exc
            if self._expected_fingerprint is not None and self._manifest.source_fingerprint != self._expected_fingerprint:
                raise GraphReadError("shared source_fingerprint 不匹配，图已过期")
            current = database_fingerprint(
                self._connection,
                source_root=Path(self._manifest.source_root) if self._manifest.source_root else None,
            )
            if current is None and self._expected_fingerprint is None:
                raise GraphReadError(
                    "无法从 shared 图重新计算当前 source_fingerprint；"
                    "必须提供 expected_fingerprint 或 canonical scoped corpus"
                )
            if current is not None and current != self._manifest.source_fingerprint:
                raise GraphReadError("shared source_fingerprint 与当前 YAML 不一致，图已 stale")
        except Exception:
            self.close()
            raise

    def _load_manifest(self) -> SharedManifest:
        row = self._connection.execute("SELECT * FROM shared_manifest WHERE id = 1").fetchone()
        if row is None:
            raise GraphReadError("shared 图缺少唯一 shared_manifest")
        try:
            return SharedManifest(
                schema_version=str(row["schema_version"]),
                story_id=str(row["story_id"]),
                timeline_id=str(row["timeline_id"]),
                source_fingerprint=str(row["source_fingerprint"]),
                built_at=str(row["built_at"]),
                document_count=int(row["document_count"]),
                module_reference_count=int(row["module_reference_count"]),
                source_root=(
                    str(row["source_root"])
                    if "source_root" in row.keys() and row["source_root"]
                    else None
                ),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise GraphReadError(f"shared_manifest 内容无效: {exc}") from exc

    def manifest(self) -> SharedManifest:
        self._ensure_fresh()
        return self._manifest

    def _ensure_fresh(self) -> None:
        if self._connection is None:
            raise GraphReadError("SharedReader 已关闭")
        current = database_fingerprint(
            self._connection,
            source_root=Path(self._manifest.source_root) if self._manifest.source_root else None,
        )
        if current is None:
            if self._expected_fingerprint is None:
                raise GraphReadError(
                    "无法证明 shared 图的新鲜度；必须提供 expected_fingerprint 或 scoped corpus"
                )
            return
        if current != self._manifest.source_fingerprint:
            raise GraphReadError("shared source_fingerprint 与当前 YAML 不一致，图已 stale")

    @property
    def connection(self) -> sqlite3.Connection:
        if self._connection is None:
            raise GraphReadError("SharedReader 已关闭")
        self._ensure_fresh()
        return self._connection

    def is_fresh(self, corpus: Any) -> bool:
        try:
            return self._manifest.source_fingerprint == corpus_fingerprint(corpus)
        except (GraphReadError, ValueError):
            return False

    def assert_fresh(self, corpus: Any) -> None:
        self._ensure_fresh()
        if not self.is_fresh(corpus):
            raise GraphReadError("shared source_fingerprint 与当前 YAML 不一致，shared 图已 stale")

    def module_references(self, module_type: str | None = None) -> list[SharedModuleHit]:
        self._ensure_fresh()
        if module_type:
            rows = self._connection.execute(
                "SELECT * FROM module_references WHERE module_type = ? ORDER BY document_id",
                (module_type,),
            ).fetchall()
        else:
            rows = self._connection.execute(
                "SELECT * FROM module_references ORDER BY module_type, document_id"
            ).fetchall()
        return [
            SharedModuleHit(
                module_type=str(row["module_type"]),
                document_id=str(row["document_id"]),
                version=str(row["version"]),
                source_file=str(row["source_file"]),
            )
            for row in rows
        ]

    def dependent_graph_keys(self, manifests: Any) -> tuple[GraphKey, ...]:
        """Return every GraphKey whose manifest references a shared module."""

        self._ensure_fresh()
        index = ModuleGraphIndex.from_manifests(manifests)
        keys: set[GraphKey] = set()
        for reference in self.module_references():
            keys.update(
                index.graph_keys_for_module(reference.module_type, reference.document_id)
            )
        return tuple(sorted(keys))

    affected_graph_keys = dependent_graph_keys

    def search(self, query: str, *, limit: int = 6) -> list[DocumentHit]:
        self._ensure_fresh()
        value = str(query or "").strip()
        if not value:
            raise ValueError("query 不能为空")
        fts_query = " ".join(f'"{term.replace(chr(34), chr(34) * 2)}"' for term in value.split())
        rows = self._connection.execute(
            """SELECT d.* FROM chunks_fts f
               JOIN documents d ON d.document_id = f.document_id
               WHERE chunks_fts MATCH ? ORDER BY bm25(chunks_fts) LIMIT ?""",
            (fts_query, int(limit)),
        ).fetchall()
        return [_document_hit(row) for row in rows]

    def close(self) -> None:
        connection = getattr(self, "_connection", None)
        if connection is not None:
            self._connection = None
            connection.close()

    def __enter__(self) -> "SharedReader":
        return self

    def __exit__(self, _type: Any, _value: Any, _traceback: Any) -> None:
        self.close()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass


def _document_hit(row: sqlite3.Row) -> DocumentHit:
    try:
        metadata = json.loads(str(row["metadata_json"] or "{}"))
    except json.JSONDecodeError:
        metadata = {}
    return DocumentHit(
        document_id=str(row["document_id"]),
        title=str(row["title"]),
        document_type=str(row["document_type"]),
        status=str(row["status"]),
        source_file=str(row["source_file"]),
        content=str(row["content"]),
        metadata=metadata if isinstance(metadata, dict) else {},
    )


def build_shared(corpus: Any, target: Path, **builder_options: Any) -> GraphBuildResult:
    return SharedBuilder(corpus, target, **builder_options).build()
