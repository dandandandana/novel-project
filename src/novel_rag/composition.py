"""Application composition roots for graph-backed retrieval and mutations.

The graph package owns SQLite projection and the retrieval package owns
channel composition.  This module is the application boundary that wires the
two together with the service/catalog layout, so CLI and mutation callers do
not each grow a slightly different reader or staging policy.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, replace
from functools import partial
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

import yaml

from .catalog import (
    TimelineRegistry,
    ValidatedCorpus,
    load_story_aliases,
    load_timeline_registry,
    yaml_source_fingerprint,
)
from .catalog.paths import resolve_module_map_path, timeline_registry_path
from .documents import RagDocument
from .graph import (
    GraphBuildError,
    GraphBuilder,
    GraphKey,
    GraphReadError,
    GraphReader,
    SharedBuilder,
    SharedReader,
    open_read_only,
)
from .graph.fingerprint import graph_corpus_fingerprint
from .layout import (
    SHARED_STORY_ID,
    SHARED_TIMELINE_ID,
    index_root,
    registry_root,
    shared_index_path,
    story_graph_path,
    story_root,
)
from .config import DEFAULT_SEARCH_STATUSES
from .mutations import ChangeSet, GraphBuildArtifact, MutationCoordinator
from .mutations.source import source_projection_ignores
from .retrieval import RetrievalRequest, RetrieverService
from .service import load_valid_documents, load_validated_corpus


def _shared_corpus(corpus: ValidatedCorpus) -> ValidatedCorpus:
    documents = tuple(
        document
        for document in corpus.documents
        if str(document.metadata.get("story_id", "")) == SHARED_STORY_ID
        and str(document.metadata.get("timeline_id", "")) == SHARED_TIMELINE_ID
    )
    return ValidatedCorpus.from_documents(
        documents,
        root=corpus.root,
        strict=True,
    )


class GraphRetriever(RetrieverService):
    """RetrieverService that owns the two read-only graph connections."""

    def close(self) -> None:
        for reader in (self.graph_reader, self.shared_reader):
            close = getattr(reader, "close", None)
            if callable(close):
                close()

    def __enter__(self) -> "GraphRetriever":
        return self

    def __exit__(self, _type: Any, _value: Any, _traceback: Any) -> None:
        self.close()


class _WithoutSharedManifest:
    """Reader proxy for an explicit ``--no-shared`` retrieval request."""

    def __init__(self, reader: Any) -> None:
        self._reader = reader

    def manifest(self) -> Any:
        manifest = self._reader.manifest()
        if getattr(manifest, "shared_manifest_fingerprint", None):
            return replace(manifest, shared_manifest_fingerprint=None)
        return manifest

    def close(self) -> None:
        self._reader.close()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._reader, name)


def build_graph_retriever(
    library_root: str | Path,
    key: GraphKey,
    *,
    index_directory: str | Path | None = None,
    include_shared: bool = True,
) -> GraphRetriever:
    """Build a current-corpus-validated graph-backed RetrieverService.

    Both readers receive their canonical ``GraphKey`` and the current scoped
    corpus fingerprint.  Missing, stale, malformed, or capability-incomplete
    graphs therefore fail at construction and are never silently replaced by
    the legacy YAML adapter.
    """

    if not isinstance(key, GraphKey):
        raise TypeError("build_graph_retriever 需要 canonical GraphKey")
    if key.is_shared:
        raise ValueError("build_graph_retriever 的 key 必须是故事 GraphKey")
    root = Path(library_root).resolve()
    graph_index = (
        Path(index_directory).resolve()
        if index_directory is not None
        else index_root(root).resolve()
    )

    # The service validates every source document before we scope the graph.
    # ``for_graph`` then applies the registry lineage/cutoff contract once.
    try:
        corpus = load_validated_corpus(
            root,
            key.story_id,
            include_shared=True,
        )
    except GraphReadError:
        raise
    except Exception as exc:
        raise GraphReadError(f"当前 corpus 校验失败，无法建立 GraphRetriever: {exc}") from exc
    scoped = corpus.for_graph(key)
    shared = _shared_corpus(corpus)
    graph_fingerprint = graph_corpus_fingerprint(corpus, key)
    shared_fingerprint = shared.fingerprint()

    story_reader = GraphReader(
        key.graph_path(graph_index),
        expected_key=key,
        expected_fingerprint=graph_fingerprint,
        corpus=scoped,
        expected_shared_manifest_fingerprint=(shared_fingerprint if include_shared else None),
    )
    if not include_shared:
        story_reader = _WithoutSharedManifest(story_reader)
        return GraphRetriever(
            story_reader,
            shared_reader=None,
            corpus=scoped,
            expected_source_fingerprint=graph_fingerprint,
        )
    try:
        shared_reader = SharedReader(
            GraphKey.shared().graph_path(graph_index),
            expected_key=GraphKey.shared(),
            expected_fingerprint=shared_fingerprint,
            corpus=shared,
        )
    except Exception:
        story_reader.close()
        raise

    return GraphRetriever(
        story_reader,
        shared_reader=shared_reader,
        corpus=scoped,
        shared_corpus=shared,
        expected_source_fingerprint=graph_fingerprint,
        expected_shared_manifest_fingerprint=shared_fingerprint,
    )


@dataclass(frozen=True)
class IndexBuildResult:
    """Result row returned by canonical graph projection orchestration."""

    scope: str
    path: Path
    document_count: int
    chunk_count: int


@dataclass(frozen=True)
class SearchResult:
    """Stable row shape kept for callers migrating from ``novel_rag.index``."""

    document_id: str
    title: str
    document_type: str
    status: str
    source_file: str
    score: float
    content: str
    metadata: dict[str, Any]


_SEARCH_TOKEN_BUDGET = 262_144


def _search_request(key: GraphKey, query: str) -> RetrievalRequest:
    return RetrievalRequest(
        graph_key=key,
        outline=query,
        token_budget=_SEARCH_TOKEN_BUDGET,
    )


def _metadata(document: Any) -> Mapping[str, Any]:
    value = getattr(document, "metadata", None)
    if isinstance(value, Mapping):
        return value
    if isinstance(document, Mapping):
        value = document.get("metadata", document)
        return value if isinstance(value, Mapping) else {}
    return {}


def _source_root(value: Path | None) -> Path | None:
    return value.resolve() if value is not None else None


def _registry_for_story(
    library_root: Path | None,
    story_id: str,
    supplied: TimelineRegistry | Mapping[str, TimelineRegistry] | None,
) -> TimelineRegistry | None:
    if supplied is not None:
        if isinstance(supplied, Mapping):
            value = supplied.get(story_id)
            if value is not None and not isinstance(value, TimelineRegistry):
                raise TypeError("timeline_registry mapping 的值必须是 TimelineRegistry")
            return value
        if not isinstance(supplied, TimelineRegistry):
            raise TypeError("timeline_registry 必须是 TimelineRegistry")
        return supplied
    if library_root is None:
        return None
    path = timeline_registry_path(library_root, story_id)
    if not path.is_file():
        return None
    try:
        return load_timeline_registry(
            path,
            expected_story_id=story_id,
            snapshot_root=library_root / "stories" / story_id,
        )
    except Exception as exc:
        raise GraphBuildError(f"timeline registry 无法加载: {path}: {exc}") from exc


def _timeline_ids(
    story_id: str,
    documents: Iterable[Any],
    registry: TimelineRegistry | None,
    requested: str | None,
) -> list[str]:
    if requested is not None:
        return [requested]
    if registry is not None:
        return [entry.timeline_id for entry in registry.entries]
    values = {
        str(_metadata(document).get("timeline_id", ""))
        for document in documents
        if str(_metadata(document).get("story_id", "")) == story_id
    }
    values.discard("")
    values.discard("common")
    values.discard(SHARED_TIMELINE_ID)
    return sorted(values) or ["main"]


def _module_references_for_graph(
    root: Path | None,
    story_id: str,
    timeline_id: str,
    documents: tuple[RagDocument, ...],
    registry: TimelineRegistry | None,
) -> tuple[dict[str, str], ...]:
    allowed = set(registry.allowed_timeline_ids(timeline_id)) if registry is not None else {timeline_id}
    by_id = {document.document_id: document for document in documents}
    references: list[dict[str, str]] = []
    if root is not None:
        path = resolve_module_map_path(root, story_id, timeline_id=timeline_id, required=False)
        try:
            value = yaml.safe_load(path.read_text(encoding="utf-8")) if path.is_file() else {}
        except (OSError, UnicodeError, yaml.YAMLError) as exc:
            raise GraphBuildError(f"无法读取 module-map: {path}: {exc}") from exc
        rows = value.get("modules", []) if isinstance(value, Mapping) else []
        for row in rows if isinstance(rows, list) else ():
            if not isinstance(row, Mapping):
                continue
            row_story = str(row.get("story_id") or story_id)
            row_timeline = str(row.get("timeline_id") or timeline_id)
            if row_story not in {"", story_id} or row_timeline not in {*allowed, "", "common"}:
                continue
            module_type = str(row.get("module_type") or "")
            active = row.get("active_versions", row.get("active_version", ()))
            if isinstance(active, str):
                active = (active,)
            for document_id in active if isinstance(active, (list, tuple, set)) else ():
                source = by_id.get(str(document_id))
                metadata = _metadata(source) if source is not None else {}
                references.append(
                    {
                        "module_type": module_type,
                        "document_id": str(document_id),
                        "version": str(metadata.get("version", "")),
                        "source_file": str(getattr(source, "path", "") or ""),
                    }
                )
    for document in documents:
        values = _metadata(document).get("module_references", ())
        if isinstance(values, Mapping):
            values = (values,)
        for value in values if isinstance(values, (list, tuple, set)) else ():
            if isinstance(value, Mapping) and value.get("document_id"):
                references.append(
                    {
                        "module_type": str(value.get("module_type", value.get("type", ""))),
                        "document_id": str(value["document_id"]),
                        "version": str(value.get("version", "")),
                        "source_file": str(value.get("source_file", "")),
                    }
                )
    unique = {
        (item["module_type"], item["document_id"], item["version"]): item
        for item in references
        if item["module_type"] and item["document_id"]
    }
    return tuple(unique[key] for key in sorted(unique))


def _manifest_fingerprint(path: Path, *, shared: bool = False) -> str:
    table = "shared_manifest" if shared else "graph_manifest"
    connection = open_read_only(path)
    try:
        row = connection.execute(
            f"SELECT source_fingerprint FROM {table} WHERE id = 1"
        ).fetchone()
        if row is None or not row[0]:
            raise GraphReadError(f"图缺少有效 {table} source_fingerprint: {path}")
        return str(row[0])
    finally:
        connection.close()


def _chunk_count(path: Path, fingerprint: str, *, shared: bool = False) -> int:
    reader: Any
    if shared:
        reader = SharedReader(path, expected_key=GraphKey.shared(), expected_fingerprint=fingerprint)
    else:
        candidate = path.resolve()
        key = GraphKey(candidate.parent.name, candidate.stem)
        reader = GraphReader(path, expected_key=key, expected_fingerprint=fingerprint)
    try:
        return int(reader.connection.execute("SELECT count(*) FROM chunks_fts").fetchone()[0])
    finally:
        reader.close()


def _prune_old_and_new_indexes(index_directory: Path, expected_keys: set[GraphKey]) -> None:
    graphs_root = index_directory / "graphs"
    if not graphs_root.is_dir():
        return
    for path in graphs_root.glob("*/*.db"):
        try:
            key = GraphKey(path.parent.name, path.stem)
        except ValueError:
            continue
        if key not in expected_keys:
            path.unlink()


def rebuild_graph_projections(
    index_directory: str | Path,
    documents: list[RagDocument],
    story_ids: list[str],
    *,
    story_id: str | None = None,
    timeline_id: str | None = None,
    shared_only: bool = False,
    library_root: str | Path | None = None,
    timeline_registry: Any | None = None,
    prune_stale: bool = True,
    on_partition: Callable[[IndexBuildResult], None] | None = None,
) -> list[Any]:
    """Canonical index orchestration used by CLI/TUI.

    The old ``index.rebuild_isolated_indexes`` name is deliberately only a
    warning-and-conversion shim.  This function owns the canonical projection
    policy so application callers never need to import the legacy index module.
    """
    if shared_only and (story_id is not None or timeline_id is not None):
        raise ValueError("--shared 不能与 story/timeline 同时使用")
    if timeline_id is not None and story_id is None:
        raise ValueError("指定 timeline_id 时必须同时指定 story_id")

    root = _source_root(Path(library_root) if library_root is not None else None)
    target_root = Path(index_directory).resolve()
    source_documents = tuple(documents)
    requested_story_ids = [story_id] if story_id is not None else list(dict.fromkeys(story_ids))
    build_shared = shared_only or (story_id is None and timeline_id is None)
    results: list[IndexBuildResult] = []
    shared_fingerprint: str | None = None

    if build_shared:
        shared_documents = tuple(
            document
            for document in source_documents
            if str(_metadata(document).get("story_id", "")) == SHARED_STORY_ID
        )
        shared_corpus = ValidatedCorpus.from_documents(
            shared_documents,
            root=root,
            strict=False,
        )
        built_shared = SharedBuilder(
            shared_corpus,
            target=shared_index_path(target_root),
        ).build()
        shared_fingerprint = str(built_shared.manifest.source_fingerprint)
        result_row = IndexBuildResult(
            "shared",
            built_shared.path,
            int(built_shared.manifest.document_count),
            _chunk_count(built_shared.path, shared_fingerprint, shared=True),
        )
        results.append(result_row)
        if on_partition is not None:
            on_partition(result_row)
    elif not shared_only and shared_index_path(target_root).is_file():
        shared_fingerprint = _manifest_fingerprint(shared_index_path(target_root), shared=True)
        with SharedReader(
            shared_index_path(target_root),
            expected_key=GraphKey.shared(),
            expected_fingerprint=shared_fingerprint,
        ):
            pass

    expected_keys: set[GraphKey] = set()
    if not shared_only:
        for current_story_id in requested_story_ids:
            registry = _registry_for_story(root, current_story_id, timeline_registry)
            story_documents = tuple(
                document
                for document in source_documents
                if str(_metadata(document).get("story_id", "")) == current_story_id
            )
            for current_timeline_id in _timeline_ids(
                current_story_id,
                story_documents,
                registry,
                timeline_id,
            ):
                key = GraphKey(current_story_id, current_timeline_id)
                expected_keys.add(key)
                corpus = ValidatedCorpus.from_documents(
                    story_documents,
                    root=root,
                    timeline_registry=registry,
                    strict=False,
                ).for_graph(key)
                built = GraphBuilder(
                    key,
                    corpus,
                    target=story_graph_path(target_root, current_story_id, current_timeline_id),
                    shared_manifest_fingerprint=shared_fingerprint,
                    module_references=_module_references_for_graph(
                        root,
                        current_story_id,
                        current_timeline_id,
                        source_documents,
                        registry,
                    ),
                    registry_aliases=(
                        load_story_aliases(root, current_story_id)
                        if root is not None
                        else None
                    ),
                ).build()
                fingerprint = str(built.manifest.source_fingerprint)
                scope = current_story_id if current_timeline_id == "main" else (
                    f"{current_story_id}/{current_timeline_id}"
                )
                result_row = IndexBuildResult(
                    scope,
                    built.path,
                    int(built.manifest.document_count),
                    _chunk_count(built.path, fingerprint),
                )
                results.append(result_row)
                if on_partition is not None:
                    on_partition(result_row)

    if prune_stale and story_id is None and timeline_id is None and not shared_only:
        _prune_old_and_new_indexes(target_root, expected_keys)
    return results


class _RecordingReader:
    """Transparent reader proxy retaining hit metadata for old result rows."""

    def __init__(self, reader: Any, *, omit_shared_manifest: bool = False) -> None:
        self._reader = reader
        self._hits: dict[str, Any] = {}
        self._omit_shared_manifest = omit_shared_manifest

    def manifest(self) -> Any:
        manifest = self._reader.manifest()
        if self._omit_shared_manifest and getattr(manifest, "shared_manifest_fingerprint", None):
            return replace(manifest, shared_manifest_fingerprint=None)
        return manifest

    def search(self, query: str, *, limit: int = 6) -> list[Any]:
        hits = list(self._reader.search(query, limit=limit))
        for hit in hits:
            document_id = str(getattr(hit, "document_id", ""))
            if document_id:
                self._hits[document_id] = hit
        return hits

    def close(self) -> None:
        self._reader.close()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._reader, name)


def _result_from_evidence(evidence: Any, hit: Any, score: float) -> SearchResult:
    metadata = dict(getattr(hit, "metadata", {}) or {})
    return SearchResult(
        document_id=str(getattr(hit, "document_id", evidence.document_id)),
        title=str(getattr(hit, "title", "") or metadata.get("title", "")),
        document_type=str(getattr(hit, "document_type", "") or metadata.get("document_type", "")),
        status=str(getattr(hit, "status", "") or getattr(evidence, "status", "") or metadata.get("status", "")),
        source_file=str(getattr(hit, "source_file", "") or metadata.get("source_file", "")),
        score=float(score),
        content=str(getattr(hit, "content", "") or getattr(evidence, "content", "")),
        metadata=metadata,
    )


def _search_canonical(
    index_directory: Path,
    query: str,
    key: GraphKey,
    *,
    document_types: list[str] | None,
    statuses: list[str] | None,
    limit: int,
    include_shared: bool,
    library_root: Path | None,
) -> list[SearchResult]:
    """依赖：只读图及资料验证入口。输入：查询、图键及可选库根。输出：命中或源证明错误。实现：核真实资料，沿用纯平铺语料的清单兼容读取。"""
    if limit <= 0:
        return []
    if not query.strip():
        raise ValueError("query 不能为空")

    story_path = key.graph_path(index_directory)
    if not story_path.is_file():
        raise GraphReadError(
            f"canonical GraphKey 图不存在: {story_path}；"
            "如需读取旧索引，请显式传入 legacy=True"
        )

    if library_root is None:
        sibling_root = index_directory.parent
        if index_directory == index_root(sibling_root) and (registry_root(sibling_root) / "stories.yaml").is_file():
            library_root = sibling_root

    if library_root is not None:
        service = build_graph_retriever(
            library_root,
            key,
            index_directory=index_directory,
            include_shared=include_shared,
        )
        raw_shared = service.shared_reader
        story_reader = _RecordingReader(
            service.graph_reader,
            omit_shared_manifest=not include_shared,
        )
        shared_reader = _RecordingReader(service.shared_reader) if include_shared else None
        service.graph_reader = story_reader
        service.shared_reader = shared_reader
        try:
            bundle = service.retrieve(_search_request(key, query))
            return _bundle_results(
                bundle,
                story_reader,
                shared_reader,
                document_types=document_types,
                statuses=statuses,
                limit=limit,
            )
        finally:
            story_reader.close()
            if shared_reader is not None:
                shared_reader.close()
            elif raw_shared is not None:
                raw_shared.close()

    story_base = GraphReader(
        story_path, expected_key=key,
        expected_fingerprint=_manifest_fingerprint(story_path),
    )
    shared_base: Any | None = None
    try:
        if include_shared:
            shared_path = shared_index_path(index_directory)
            if not shared_path.is_file():
                raise FileNotFoundError(f"共享系统索引不存在，请先执行 index: {shared_path}")
            shared_base = SharedReader(
                shared_path, expected_key=GraphKey.shared(),
                expected_fingerprint=_manifest_fingerprint(shared_path, shared=True),
            )
        story_reader = _RecordingReader(story_base, omit_shared_manifest=not include_shared)
        shared_reader = _RecordingReader(shared_base) if shared_base is not None else None
        retriever = RetrieverService(
            story_reader,
            shared_reader=shared_reader,
            limit=max(1, limit),
        )
        bundle = retriever.retrieve(_search_request(key, query))
        return _bundle_results(
            bundle,
            story_reader,
            shared_reader,
            document_types=document_types,
            statuses=statuses,
            limit=limit,
        )
    finally:
        if shared_base is not None:
            shared_base.close()
        story_base.close()


def _bundle_results(
    bundle: Any,
    story_reader: _RecordingReader,
    shared_reader: _RecordingReader | None,
    *,
    document_types: list[str] | None,
    statuses: list[str] | None,
    limit: int,
) -> list[SearchResult]:
    accepted_statuses = set(statuses or DEFAULT_SEARCH_STATUSES)
    accepted_types = set(document_types or ())
    results: list[SearchResult] = []
    seen: set[str] = set()
    evidence_rows = tuple(getattr(bundle, "all_evidence", ()))
    for position, evidence in enumerate(evidence_rows):
        hit = story_reader._hits.get(evidence.document_id)
        if hit is None and shared_reader is not None:
            hit = shared_reader._hits.get(evidence.document_id)
        if hit is None:
            continue
        status = str(getattr(hit, "status", "") or getattr(evidence, "status", "") or "")
        document_type = str(getattr(hit, "document_type", ""))
        if status not in accepted_statuses or (accepted_types and document_type not in accepted_types):
            continue
        if evidence.document_id in seen:
            continue
        seen.add(evidence.document_id)
        results.append(
            _result_from_evidence(
                evidence,
                hit,
                float(len(evidence_rows) - position),
            )
        )
        if len(results) >= limit:
            break
    return results


def search_graph(
    index_directory: str | Path,
    query: str,
    key: GraphKey,
    *,
    document_types: list[str] | None = None,
    statuses: list[str] | None = None,
    limit: int = 6,
    include_shared: bool = True,
    library_root: str | Path | None = None,
    legacy: bool = False,
) -> list[Any]:
    """依赖：canonical/legacy 读取入口。输入：图键、查询与检索选项。输出：命中或错误。实现：按路径选择当前资料核验或纯平铺图兼容读取。"""

    if not isinstance(key, GraphKey):
        raise TypeError("search_graph 需要 canonical GraphKey")
    if legacy:
        from .index import _search_legacy

        return _search_legacy(
            Path(index_directory).resolve(),
            query,
            key.story_id,
            key.timeline_id,
            document_types=document_types,
            statuses=statuses,
            limit=limit,
            include_shared=include_shared,
        )
    return _search_canonical(
        Path(index_directory).resolve(),
        query,
        key,
        document_types=document_types,
        statuses=statuses,
        limit=limit,
        include_shared=include_shared,
        library_root=Path(library_root).resolve() if library_root is not None else None,
    )


def timeline_summary_root(library_root: str | Path, key: GraphKey) -> Path:
    """Return the target-layout YAML directory for one timeline's summaries."""

    if not isinstance(key, GraphKey) or key.is_shared:
        raise ValueError("摘要必须绑定故事 GraphKey")
    return story_root(Path(library_root).resolve(), key.story_id) / "timelines" / key.timeline_id / "summaries"


def _yaml_source_fingerprint(root: Path) -> str:
    return yaml_source_fingerprint(root)


def _projected_library(staged: Any, root: Path) -> Path:
    """依赖：原源投影/共享锁guard过滤。输入：暂存ChangeSet和库根。输出：只读资料投影路径。实现：只跳过源锁guard，复制原资料并覆盖本批源；越界保留GraphBuildError。"""
    projected = Path(staged.root) / "source"
    if not projected.exists():
        shutil.copytree(
            root,
            projected,
            dirs_exist_ok=True,
            ignore=partial(source_projection_ignores, root),
        )
    for original, staged_path in staged.staged_files.items():
        source = Path(original).resolve()
        try:
            relative = source.relative_to(root)
        except ValueError as exc:
            raise GraphBuildError(f"ChangeSet 路径越出 library_root: {source}") from exc
        target = projected / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(Path(staged_path), target)
    return projected


def _load_projected_documents(
    staged: Any,
    root: Path,
) -> tuple[Path, tuple[RagDocument, ...]]:
    projected = _projected_library(staged, root)
    documents, issues = load_valid_documents(projected, include_shared=True)
    if issues:
        detail = "；".join(f"{issue.path}: {issue.message}" for issue in issues[:12])
        raise GraphBuildError(f"staged YAML 校验失败: {detail}")
    return projected, tuple(documents)


def _load_story_corpus(
    projected: Path,
    documents: tuple[RagDocument, ...],
    key: GraphKey,
) -> tuple[ValidatedCorpus, Any]:
    registry_path = timeline_registry_path(projected, key.story_id)
    try:
        registry = load_timeline_registry(
            registry_path,
            expected_story_id=key.story_id,
            snapshot_root=story_root(projected, key.story_id),
        )
        corpus = ValidatedCorpus.from_documents(
            documents,
            root=projected,
            timeline_registry=registry,
            strict=True,
        )
        return corpus.for_graph(key), registry
    except Exception as exc:
        raise GraphBuildError(
            f"无法加载 GraphKey {key.story_id}/{key.timeline_id} 的 staged corpus: {exc}"
        ) from exc


def _module_references(
    root: Path,
    story_id: str,
    timeline_id: str,
    documents: tuple[RagDocument, ...],
    registry: Any,
) -> tuple[dict[str, str], ...]:
    allowed = (
        set(registry.allowed_timeline_ids(timeline_id))
        if registry is not None
        else {timeline_id}
    )
    by_id = {document.document_id: document for document in documents}
    references: list[dict[str, str]] = []
    # Resolve one authoritative map in target-first order.  If a target map
    # and a legacy map coexist, the legacy file must not add a second set of
    # module references to the same graph.
    path = resolve_module_map_path(
        root,
        story_id,
        timeline_id=timeline_id,
        required=False,
    )
    if path.is_file():
        try:
            value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except (OSError, UnicodeError, yaml.YAMLError) as exc:
            raise GraphBuildError(f"无法读取 module-map: {path}: {exc}") from exc
        rows = value.get("modules", []) if isinstance(value, Mapping) else []
        if not isinstance(rows, list):
            rows = []
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            row_story = str(row.get("story_id") or story_id)
            row_timeline = str(row.get("timeline_id") or timeline_id)
            if row_story not in {"", story_id} or row_timeline not in {
                *allowed,
                "",
                "common",
            }:
                continue
            module_type = str(row.get("module_type") or "")
            active = row.get("active_versions", row.get("active_version", ()))
            if isinstance(active, str):
                active = (active,)
            for document_id in active if isinstance(active, (list, tuple, set)) else ():
                document_id = str(document_id)
                source = by_id.get(document_id)
                metadata = source.metadata if source is not None else {}
                references.append(
                    {
                        "module_type": module_type,
                        "document_id": document_id,
                        "version": str(metadata.get("version") or ""),
                        "source_file": str(source.path) if source is not None else "",
                    }
                )
    for document in documents:
        values = document.metadata.get("module_references", ())
        if isinstance(values, Mapping):
            values = (values,)
        for value in values if isinstance(values, (list, tuple, set)) else ():
            if isinstance(value, Mapping) and value.get("document_id"):
                references.append(
                    {
                        "module_type": str(value.get("module_type", value.get("type", ""))),
                        "document_id": str(value["document_id"]),
                        "version": str(value.get("version", "")),
                        "source_file": str(value.get("source_file", "")),
                    }
                )
    unique = {
        (row["module_type"], row["document_id"], row["version"]): row
        for row in references
        if row["module_type"] and row["document_id"]
    }
    return tuple(unique[key] for key in sorted(unique))


def _retrieval_regression(
    reader: Any,
    key: GraphKey,
    root: Path,
    *,
    shared_db: Path | None = None,
) -> None:
    """Run the story's retrieval cases with official acceptance semantics.

    The gate must exercise the same five-channel retriever as
    ``scripts/run_retrieval_tests.py``; judging the staged graph by raw FTS
    alone would reject alias/entity-dependent cases that production accepts.
    ``shared_db`` is the production shared index; when it is missing or its
    fingerprint diverges, the gate degrades to story-only evidence via
    ``_WithoutSharedManifest`` instead of failing every case.
    """

    from .graph import SharedReader

    failures: list[str] = []
    seen_cases: set[tuple[str, str, Path]] = set()
    shared_reader: Any = None
    expected_shared = getattr(
        getattr(reader, "manifest", lambda: None)(),
        "shared_manifest_fingerprint",
        None,
    )
    if shared_db is not None and Path(shared_db).is_file():
        try:
            shared_reader = SharedReader(
                Path(shared_db),
                expected_key=GraphKey.shared(),
                expected_fingerprint=expected_shared or None,
            )
        except Exception:
            shared_reader = None

    try:
        for path in sorted((root / "stories").rglob("retrieval-tests.yaml")):
            try:
                value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            except (OSError, UnicodeError, yaml.YAMLError) as exc:
                raise GraphBuildError(f"无法读取 retrieval-tests: {path}: {exc}") from exc
            cases = value.get("tests", []) if isinstance(value, Mapping) else []
            if not isinstance(cases, list):
                continue
            for case in cases:
                if not isinstance(case, Mapping):
                    continue
                if (str(case.get("story_id")), str(case.get("timeline_id"))) != (
                    key.story_id,
                    key.timeline_id,
                ):
                    continue
                dedupe_key = (str(case.get("id") or ""), str(case.get("query") or ""), path.parent)
                if dedupe_key in seen_cases:
                    continue
                seen_cases.add(dedupe_key)
                query = str(case.get("query") or "")
                if shared_reader is not None:
                    story_recorder: Any = _RecordingReader(reader)
                    shared_recorder: Any = _RecordingReader(shared_reader)
                else:
                    story_recorder = _WithoutSharedManifest(_RecordingReader(reader))
                    shared_recorder = None
                service = RetrieverService(
                    story_recorder,
                    shared_reader=shared_recorder,
                    limit=20,
                )
                bundle = service.retrieve(_search_request(key, query))
                results = _bundle_results(
                    bundle,
                    story_recorder,
                    shared_recorder,
                    document_types=case.get("document_types"),
                    statuses=None,
                    limit=20,
                )
                ids = {result.document_id for result in results}
                statuses = {result.status for result in results}
                missing = set(str(item) for item in case.get("expected_document_ids", ())) - ids
                forbidden = set(str(item) for item in case.get("forbidden_document_ids", ())) & ids
                bad_statuses = set(str(item) for item in case.get("forbidden_statuses", ())) & statuses
                if missing or forbidden or bad_statuses:
                    failures.append(str(case.get("id") or path.name))
        if failures:
            raise GraphBuildError("检索回归失败: " + ", ".join(failures))
    finally:
        closer = getattr(shared_reader, "close", None)
        if callable(closer):
            closer()


def build_mutation_coordinator(
    library_root: str | Path,
    *,
    index_directory: str | Path | None = None,
) -> MutationCoordinator:
    """Build the production staged-YAML plus graph mutation coordinator."""

    root = Path(library_root).resolve()
    graph_index = (
        Path(index_directory).resolve()
        if index_directory is not None
        else index_root(root).resolve()
    )
    cache: dict[str, tuple[Path, tuple[RagDocument, ...]]] = {}

    def load_staged(staged: Any) -> tuple[Path, tuple[RagDocument, ...]]:
        cache_key = str(Path(staged.root).resolve())
        if cache_key not in cache:
            cache[cache_key] = _load_projected_documents(staged, root)
        return cache[cache_key]

    def validate_staged(staged: Any) -> bool:
        keys = tuple(staged.changeset.affected_graph_keys)
        if not keys:
            raise GraphBuildError("正式 YAML 变更必须声明 affected_graph_keys，禁止 YAML-only 提交")
        if any(not isinstance(key, GraphKey) for key in keys):
            raise GraphBuildError("affected_graph_keys 必须全部是 canonical GraphKey")
        load_staged(staged)
        return True

    def build_graph(key: GraphKey, staged: Any) -> GraphBuildArtifact:
        projected, documents = load_staged(staged)
        staged_index = Path(staged.root) / "index"
        target = key.graph_path(graph_index)
        staged_target = key.graph_path(staged_index)
        try:
            if key.is_shared:
                shared = ValidatedCorpus.from_documents(
                    tuple(
                        document
                        for document in documents
                        if str(document.metadata.get("story_id", "")) == SHARED_STORY_ID
                        and str(document.metadata.get("timeline_id", "")) == SHARED_TIMELINE_ID
                    ),
                    root=projected,
                    strict=True,
                )
                built = SharedBuilder(
                    shared,
                    target=staged_target,
                    retrieval_regression=lambda reader: _retrieval_regression(
                        reader,
                        GraphKey.shared(),
                        projected,
                    ),
                ).build()
            else:
                corpus, registry = _load_story_corpus(projected, documents, key)
                shared = _shared_corpus(
                    ValidatedCorpus.from_documents(documents, root=projected, strict=True)
                )
                built = GraphBuilder(
                    key,
                    corpus,
                    target=staged_target,
                    shared_manifest_fingerprint=shared.fingerprint(),
                    module_references=_module_references(
                        projected,
                        key.story_id,
                        key.timeline_id,
                        documents,
                        registry,
                    ),
                    registry_aliases=load_story_aliases(projected, key.story_id),
                    retrieval_regression=lambda reader: _retrieval_regression(
                        reader,
                        key,
                        projected,
                        shared_db=graph_index / "shared.db",
                    ),
                ).build()
        except GraphBuildError:
            raise
        except Exception as exc:
            raise GraphBuildError(
                f"GraphKey {key.story_id}/{key.timeline_id} 构建失败: {exc}"
            ) from exc
        return GraphBuildArtifact(
            key=key,
            staged_path=built.path,
            target_path=target,
            regression_passed=True,
            metadata={"manifest": built.manifest.as_dict()},
        )

    return MutationCoordinator(
        library_root=root,
        staging_root=root / ".novel-rag" / "staging",
        lock_path=root / ".novel-rag" / "mutation.lock",
        validate_staged=validate_staged,
        graph_builder=build_graph,
        target_resolver=lambda key: key.graph_path(graph_index),
        current_fingerprint=lambda: _yaml_source_fingerprint(root),
    )


def build_source_mutation_coordinator(library_root: Path, *, pre_commit=None, after_source_commit=None):
    """依赖：mutations.source唯一工厂。输入：库根及锁内hook。输出：v3单源提交器。实现：保留组合根公共入口并完整委托，源校验和锁路径只在业务owner定义。"""
    from .mutations.source import build_source_mutation_coordinator as build_source

    return build_source(library_root, pre_commit=pre_commit, after_source_commit=after_source_commit)


def build_writer_service(library_root: Path, workspace_root: Path | None = None,
                         model_config_path: Path | None = None):
    """依赖：v3服务/Store/原配置与采用owner。输入：库、工作根、配置路径。输出：唯一RunService。实现：延迟装配同Store/Memory/采用实例，无web extra也可导入旧composition。"""
    from .generation.session import RunService
    from .generation.store import DraftStore
    from .memory.service import MemoryService
    from .model_config import ModelConfigStore
    from .writeback.adopt import AdoptionService

    root = Path(library_root).resolve()
    store = DraftStore(Path(workspace_root) if workspace_root else root.parent / "outputs" / ".workspace")
    memory = MemoryService(root, store)
    adoption = AdoptionService(root, store, memory)
    return RunService(root, store, memory, ModelConfigStore(model_config_path), adoption=adoption)


__all__ = [
    "GraphRetriever",
    "IndexBuildResult",
    "SearchResult",
    "build_graph_retriever",
    "build_mutation_coordinator",
    "build_source_mutation_coordinator",
    "build_writer_service",
    "rebuild_graph_projections",
    "search_graph",
    "timeline_summary_root",
]
