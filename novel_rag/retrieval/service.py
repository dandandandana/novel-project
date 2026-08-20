"""Hybrid retrieval service built on the read-only graph adapters.

This module is the composition root for the five retrieval channels.  It does
not open SQLite itself and does not know about the legacy ``index`` module:
the graph and shared readers own storage, manifest validation, and trigram
capability checks.  The service only converts their hit value objects into
the stable :mod:`novel_rag.retrieval.types` contract.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Any, Callable, Iterable, Mapping, Sequence

from ..graph.types import GraphReadError
from .assembler import ContextAssembler
from .types import (
    ContextBundle,
    Evidence,
    EvidenceChannel,
    RetrievalRequest,
)


class RetrievalError(RuntimeError):
    """Base error for retrieval composition failures."""


class RetrievalAmbiguityError(RetrievalError):
    """An alias or entity could not be resolved to one deterministic entity."""


class RetrievalConfigurationError(RetrievalError):
    """A requested channel or reader capability is not configured."""


_AUTHORITY_TYPES = {
    "canon",
    "character_state",
    "world_state",
    "current",
    "feedback",
    "rule",
    "judgment_spec",
    "generator_spec",
    "audit_spec",
    "style_audit",
    "style_sample",
}
_SUMMARY_TYPES = {
    "summary",
    "scene-summary",
    "scene_summary",
    "chapter-summary",
    "chapter_summary",
    "volume-summary",
    "volume_summary",
}
_CJK_OR_WORD_RE = re.compile(r"[\u3400-\u9fff]+|[A-Za-z0-9][A-Za-z0-9_.:-]*", re.UNICODE)
_CJK_RE = re.compile(r"^[\u3400-\u9fff]+$", re.UNICODE)


def _safe_query_terms(value: str) -> tuple[str, ...]:
    """Split user text into FTS-safe, independently searchable terms.

    ``GraphReader.search`` quotes each whitespace-delimited term, which is
    safe but makes a multi-word outline an implicit ``AND`` query.  That is
    particularly harmful for feedback IDs: an active feedback document may
    contain the ID while the scene outline contains unrelated event wording.
    Keep each extracted term as its own query.  For a contiguous CJK run,
    retain the full phrase and add trigram windows so punctuation or wording
    differences do not turn the whole run into one brittle phrase query.

    Only ASCII letters/digits and CJK codepoints are emitted.  Raw user
    punctuation and FTS operators never cross this boundary.
    """

    compact = " ".join(str(value or "").split()).strip()
    if not compact:
        return ()
    terms: list[str] = []
    for token in _CJK_OR_WORD_RE.findall(compact):
        if _CJK_RE.fullmatch(token):
            # SQLite's trigram tokenizer cannot match one- or two-codepoint
            # terms, but keeping them is harmless and lets a narrow reader
            # adapter decide whether it supports exact short aliases.
            terms.append(token)
            if len(token) >= 3:
                terms.extend(
                    token[index : index + 3]
                    for index in range(len(token) - 2)
                )
        else:
            terms.append(token)
    return tuple(dict.fromkeys(term for term in terms if term))


@dataclass(frozen=True, slots=True)
class _QueryHit:
    """One hit with query provenance and a channel-local merge position."""

    value: Any
    query: str
    ordinal: int

    @property
    def channel_score(self) -> float:
        # Reader results are already BM25 ordered within each query.  Across
        # independent queries there is no common score scale, so use only a
        # deterministic merge position.  This score is consumed by the same
        # channel's assembler sorting and is never compared across channels.
        return -float(self.ordinal)


def _as_mapping(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    metadata = getattr(value, "metadata", None)
    return metadata if isinstance(metadata, Mapping) else {}


def _value(value: Any, *keys: str, default: Any = None) -> Any:
    mapping = _as_mapping(value)
    for key in keys:
        item = mapping.get(key)
        if item not in (None, ""):
            return item
        item = getattr(value, key, None)
        if item not in (None, ""):
            return item
    return default


def _field(value: Any, name: str, default: Any = None) -> Any:
    """Read a field from either a manifest object or a mapping adapter."""

    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _as_ids(value: Any) -> tuple[str, ...]:
    if value in (None, ""):
        return ()
    if isinstance(value, (list, tuple, set, frozenset)):
        return tuple(dict.fromkeys(str(item) for item in value if str(item)))
    return (str(value),)


class EvidenceNormalizer:
    """Convert graph/shared hit objects into explainable ``Evidence``."""

    def normalize(
        self,
        value: Any,
        channel: EvidenceChannel | str,
        *,
        timeline_id: str | None = None,
        source_fingerprint: str | None = None,
        reason: str = "",
        authority: str | None = None,
    ) -> Evidence:
        channel_value = EvidenceChannel(channel)
        if isinstance(value, Evidence):
            # A provider cannot smuggle a sixth channel into a service result.
            return replace(
                value,
                channel=channel_value,
                timeline_id=value.timeline_id or timeline_id,
                source_fingerprint=value.source_fingerprint or source_fingerprint,
                reason=value.reason or reason,
            )

        document_id = str(getattr(value, "document_id", "") or _value(value, "document_id", default=""))
        if not document_id:
            document_id = str(getattr(value, "relation_id", "") or _value(value, "relation_id", default=""))
        if not document_id:
            document_id = str(_value(value, "module_type", default="module"))

        metadata = dict(_as_mapping(value))
        content = str(getattr(value, "content", "") or _value(value, "content", default=""))
        title = str(getattr(value, "title", "") or _value(value, "title", default=""))
        document_type = str(
            getattr(value, "document_type", "")
            or _value(value, "document_type", default="")
        )
        status = str(getattr(value, "status", "") or _value(value, "status", default="")) or None
        relation_type = str(getattr(value, "relation_type", "") or _value(value, "relation_type", default=""))
        module_type = str(getattr(value, "module_type", "") or _value(value, "module_type", default=""))
        if not content:
            if relation_type:
                subject_id = str(getattr(value, "subject_id", "") or _value(value, "subject_id", default=""))
                object_id = str(getattr(value, "object_id", "") or _value(value, "object_id", default=""))
                content = f"{subject_id} -[{relation_type}]-> {object_id}".strip()
            elif module_type:
                version = str(getattr(value, "version", "") or _value(value, "version", default=""))
                source_file = str(getattr(value, "source_file", "") or _value(value, "source_file", default=""))
                content = " ".join(part for part in (module_type, document_id, version, source_file) if part)
            elif title:
                content = title

        entity_ids = _as_ids(
            _value(
                value,
                "entity_ids",
                "entity_id",
                "character_id",
                "location_id",
                "faction_id",
                "ability_id",
            )
        )
        subject_id = str(getattr(value, "subject_id", "") or _value(value, "subject_id", default=""))
        object_id = str(getattr(value, "object_id", "") or _value(value, "object_id", default=""))
        relation_path = tuple(part for part in (subject_id, relation_type, object_id) if part)
        effective_timeline = str(
            _value(value, "timeline_id", default=timeline_id) or timeline_id or ""
        ) or None
        effective_authority = str(
            _value(value, "authority", default=authority or channel_value.value)
            or authority
            or channel_value.value
        )
        fact_type = _value(value, "fact_type", default=None)
        if fact_type in (None, ""):
            fact_type = relation_type or module_type or document_type or None
        valid_at = _value(
            value,
            "valid_at",
            "covers_through",
            "chapter",
            "scene",
            default=None,
        )
        if valid_at is not None:
            valid_at = str(valid_at)
        version = _value(value, "source_version", "version", default=None)
        fingerprint = _value(value, "source_fingerprint", default=source_fingerprint)
        if fingerprint is not None:
            fingerprint = str(fingerprint)
        return Evidence(
            document_id=document_id,
            channel=channel_value,
            authority=effective_authority,
            fact_type=str(fact_type) if fact_type not in (None, "") else None,
            valid_at=valid_at,
            entity_ids=entity_ids,
            relation_path=relation_path,
            reason=reason,
            source_version=str(version) if version not in (None, "") else None,
            source_fingerprint=fingerprint,
            content=content,
            channel_score=None,
            timeline_id=effective_timeline,
            status=status,
        )


def _manifest(reader: Any) -> Any:
    method = getattr(reader, "manifest", None)
    if not callable(method):
        raise RetrievalConfigurationError("reader 缺少 manifest()")
    return method()


def _manifest_fingerprint(manifest: Any) -> str | None:
    value = _field(manifest, "source_fingerprint")
    return str(value) if value not in (None, "") else None


def _reader_search(reader: Any, query: str, limit: int) -> list[Any]:
    if not query.strip():
        return []
    method = getattr(reader, "search", None)
    if not callable(method):
        raise RetrievalConfigurationError("reader 缺少 search(query, limit=...)")
    return list(method(query, limit=limit))


def _unique_hits(hits: Iterable[Any]) -> tuple[Any, ...]:
    result: list[Any] = []
    seen: set[str] = set()
    for hit in hits:
        identity = str(
            getattr(hit, "document_id", "")
            or getattr(hit, "relation_id", "")
            or _value(hit, "document_id", "relation_id", default="")
        )
        if not identity:
            identity = repr(hit)
        if identity in seen:
            continue
        seen.add(identity)
        result.append(hit)
    return tuple(result)


class RetrieverService:
    """Compose the five retrieval channels over validated graph readers."""

    def __init__(
        self,
        graph_reader: Any,
        *,
        shared_reader: Any | None = None,
        corpus: Any | Callable[[RetrievalRequest], Any] | None = None,
        shared_corpus: Any | Callable[[RetrievalRequest], Any] | None = None,
        expected_source_fingerprint: str | None = None,
        expected_shared_manifest_fingerprint: str | None = None,
        assembler: ContextAssembler | None = None,
        normalizer: EvidenceNormalizer | None = None,
        relation_types: set[str] | None = None,
        max_hops: int = 1,
        limit: int = 12,
        semantic_enabled: bool = False,
        semantic_provider: Callable[[RetrievalRequest], Iterable[Any]] | None = None,
    ) -> None:
        if graph_reader is None:
            raise RetrievalConfigurationError("graph_reader 不能为空")
        if isinstance(max_hops, bool) or not isinstance(max_hops, int) or max_hops <= 0:
            raise ValueError("max_hops 必须是正整数")
        if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
            raise ValueError("limit 必须是正整数")
        if semantic_enabled and semantic_provider is None:
            raise RetrievalConfigurationError("Semantic 通道启用时必须提供 semantic_provider")
        self.graph_reader = graph_reader
        self.shared_reader = shared_reader
        self.corpus = corpus
        self.shared_corpus = shared_corpus
        self.expected_source_fingerprint = expected_source_fingerprint
        self.expected_shared_manifest_fingerprint = expected_shared_manifest_fingerprint
        self.assembler = assembler or ContextAssembler()
        self.normalizer = normalizer or EvidenceNormalizer()
        self.relation_types = set(relation_types or ())
        self.max_hops = max_hops
        self.limit = limit
        self.semantic_enabled = semantic_enabled
        self.semantic_provider = semantic_provider

    def retrieve(self, request: RetrievalRequest) -> ContextBundle:
        if not isinstance(request, RetrievalRequest):
            raise TypeError("RetrieverService.retrieve 需要 RetrievalRequest")
        graph_manifest = self._validate_graph(request)
        shared_manifest = self._validate_shared(request, graph_manifest)
        story_fingerprint = _manifest_fingerprint(graph_manifest)
        shared_fingerprint = _manifest_fingerprint(shared_manifest)

        mandatory = self._authority(
            request,
            graph_fingerprint=story_fingerprint,
            shared_fingerprint=shared_fingerprint,
        )
        graph = self._graph(request, story_fingerprint)
        temporal = self._temporal(request, story_fingerprint)
        lexical = self._lexical(request, story_fingerprint)
        semantic = self._semantic(request, story_fingerprint)
        return self.assembler.assemble(
            request,
            mandatory=mandatory,
            graph_context=graph,
            temporal_memory=temporal,
            lexical_supplements=lexical,
            semantic_supplements=semantic,
        )

    def _validate_graph(self, request: RetrievalRequest) -> Any:
        manifest = _manifest(self.graph_reader)
        expected_story = str(_field(request.graph_key, "story_id", ""))
        expected_timeline = str(_field(request.graph_key, "timeline_id", ""))
        actual = (str(_field(manifest, "story_id", "")), str(_field(manifest, "timeline_id", "")))
        if actual != (expected_story, expected_timeline):
            raise GraphReadError(
                "图身份与 RetrievalRequest.graph_key 不一致: "
                f"{actual[0]}/{actual[1]} != {expected_story}/{expected_timeline}"
            )
        actual_fingerprint = _manifest_fingerprint(manifest)
        if self.expected_source_fingerprint is not None and actual_fingerprint != self.expected_source_fingerprint:
            raise GraphReadError("图 source_fingerprint 与期望值不一致，图已 stale")
        corpus = self._resolve_corpus(self.corpus, request)
        self._assert_reader_fresh(self.graph_reader, corpus, "图")
        return manifest

    def _validate_shared(self, request: RetrievalRequest, graph_manifest: Any) -> Any | None:
        graph_shared_fingerprint = _field(graph_manifest, "shared_manifest_fingerprint")
        if self.shared_reader is None:
            if graph_shared_fingerprint not in (None, ""):
                raise RetrievalConfigurationError(
                    "目标图依赖 shared manifest，但未提供 shared_reader；"
                    "不能静默省略 Authority shared/module-map"
                )
            return None
        manifest = _manifest(self.shared_reader)
        actual = (
            str(_field(manifest, "story_id", "")),
            str(_field(manifest, "timeline_id", "")),
        )
        if actual != ("__shared__", "global"):
            raise GraphReadError("shared manifest 身份不正确")
        actual_fingerprint = _manifest_fingerprint(manifest)
        expected = self.expected_shared_manifest_fingerprint or graph_shared_fingerprint
        if expected not in (None, "") and actual_fingerprint != str(expected):
            raise GraphReadError("shared_manifest_fingerprint 不匹配，图已 stale")
        corpus = self._resolve_corpus(self.shared_corpus, request)
        self._assert_reader_fresh(self.shared_reader, corpus, "shared 图")
        return manifest

    @staticmethod
    def _resolve_corpus(
        value: Any | Callable[[RetrievalRequest], Any] | None,
        request: RetrievalRequest,
    ) -> Any | None:
        if value is None:
            return None
        if callable(value) and not hasattr(value, "documents"):
            return value(request)
        return value

    @staticmethod
    def _assert_reader_fresh(reader: Any, corpus: Any | None, label: str) -> None:
        if corpus is None:
            return
        assert_fresh = getattr(reader, "assert_fresh", None)
        if callable(assert_fresh):
            # GraphReader/SharedReader raise GraphReadError directly.  Do not
            # catch or downgrade that error: stale must reach the caller.
            assert_fresh(corpus)
            return
        is_fresh = getattr(reader, "is_fresh", None)
        if callable(is_fresh) and not is_fresh(corpus):
            raise GraphReadError(f"{label} source_fingerprint 不匹配，图已 stale")
        raise RetrievalConfigurationError(f"{label} reader 缺少 freshness 校验接口")

    def _queries(self, request: RetrievalRequest) -> tuple[str, ...]:
        """Build independently searchable, explainable query terms.

        The old implementation passed the complete outline to FTS.  Since
        ``GraphReader.search`` quotes every whitespace-delimited term, that
        made a multi-word outline an implicit AND expression.  Querying the
        safe terms separately preserves recall while the merge below records
        which term produced each hit.
        """

        values: list[str] = []
        values.extend(_safe_query_terms(request.outline))
        for value in request.target_entities:
            values.extend(_safe_query_terms(str(value)))
        return tuple(dict.fromkeys(value for value in values if value))

    def _query_hits(
        self,
        reader: Any,
        queries: Sequence[str],
        *,
        extra: Iterable[Any] = (),
        extra_query: str = "entity-id",
    ) -> tuple[_QueryHit, ...]:
        """Merge per-query reader results without combining score scales.

        Each reader call retains its BM25 order.  The flattened order is the
        explicit query-plan order followed by each query's local rank; the
        ``_QueryHit`` keeps that provenance for evidence explanations and a
        channel-local score.  Entity-bound fallbacks are appended after FTS
        terms and labelled separately.
        """

        result: list[_QueryHit] = []
        seen: set[str] = set()
        for query in queries:
            for hit in _reader_search(reader, query, self.limit):
                identity = self._hit_id(hit) or repr(hit)
                if identity in seen:
                    continue
                seen.add(identity)
                result.append(_QueryHit(hit, query, len(result)))
        for hit in extra:
            identity = self._hit_id(hit) or repr(hit)
            if identity in seen:
                continue
            seen.add(identity)
            result.append(_QueryHit(hit, extra_query, len(result)))
        return tuple(result)

    @staticmethod
    def _query_reason(base: str, match: _QueryHit) -> str:
        return f"{base}；查询词={match.query!r}"

    def _authority(
        self,
        request: RetrievalRequest,
        *,
        graph_fingerprint: str | None,
        shared_fingerprint: str | None,
    ) -> tuple[Evidence, ...]:
        result: list[Evidence] = []
        queries = self._queries(request)
        authority_hits = self._query_hits(
            self.graph_reader,
            queries,
            extra=self._documents_for_target_entities(request),
        )
        for match in authority_hits:
            hit = match.value
            document_type = str(getattr(hit, "document_type", "") or _value(hit, "document_type", default=""))
            if document_type not in _AUTHORITY_TYPES:
                continue
            status = str(_value(hit, "status", default="")).strip().lower()
            if status and status not in {"active", "canon"}:
                continue
            result.append(
                replace(self.normalizer.normalize(
                    hit,
                    EvidenceChannel.AUTHORITY,
                    timeline_id=request.graph_key.timeline_id,
                    source_fingerprint=graph_fingerprint,
                    reason=self._query_reason(
                        "Authority：按 story/timeline 身份加载 Canon、current 或 active feedback",
                        match,
                    ),
                    authority=self._authority_name(hit, document_type),
                ), channel_score=match.channel_score)
            )

        if self.shared_reader is not None:
            shared_hits = self._query_hits(
                self.shared_reader,
                queries,
            )
            refs = self._module_references()
            refs_by_document = {self._hit_id(item): item for item in refs}
            for match in shared_hits:
                hit = match.value
                result.append(
                    replace(self.normalizer.normalize(
                        hit,
                        EvidenceChannel.AUTHORITY,
                        timeline_id="global",
                        source_fingerprint=shared_fingerprint,
                        reason=self._query_reason(
                            "Authority：shared/module-map 命中共享系统规则",
                            match,
                        ),
                        authority="shared-module",
                    ), channel_score=match.channel_score)
                )
                refs_by_document.pop(self._hit_id(hit), None)
            # module-map itself is authoritative even if the free-text outline
            # does not happen to contain a rule's wording.
            for reference in refs_by_document.values():
                result.append(
                    self.normalizer.normalize(
                        reference,
                        EvidenceChannel.AUTHORITY,
                        timeline_id="global",
                        source_fingerprint=shared_fingerprint,
                        reason="Authority：shared/module-map 注册引用",
                        authority="shared-module",
                    )
                )
        return tuple(result)

    def _module_references(self) -> tuple[Any, ...]:
        method = getattr(self.shared_reader, "module_references", None)
        if not callable(method):
            raise RetrievalConfigurationError("shared_reader 缺少 module_references()")
        return tuple(method())

    @staticmethod
    def _hit_id(value: Any) -> str:
        return str(
            getattr(value, "document_id", "")
            or getattr(value, "relation_id", "")
            or _value(value, "document_id", "relation_id", default="")
        )

    @staticmethod
    def _authority_name(hit: Any, document_type: str) -> str:
        explicit = _value(hit, "authority", default=None)
        if explicit:
            return str(explicit)
        if document_type in {"character_state", "world_state", "current"}:
            return "current"
        if document_type == "feedback":
            return "feedback"
        return "canon"

    def _resolve_entity_ids(self, request: RetrievalRequest) -> tuple[str, ...]:
        resolver = getattr(self.graph_reader, "resolve_aliases", None)
        if not callable(resolver):
            # A narrow reader adapter may expose stable entity IDs but no
            # alias table.  Preserve explicit target IDs; free-text alias
            # expansion remains unavailable rather than inventing entities.
            return tuple(dict.fromkeys(str(value) for value in request.target_entities if str(value)))
        terms = list(request.target_entities)
        for token in _CJK_OR_WORD_RE.findall(request.outline):
            # GraphReader resolves exact aliases.  Free-text outlines must
            # therefore contribute their extracted terms before resolution.
            # The old implementation placed ``terms.append`` inside a CJK
            # branch after its one-character ``continue``; English tokens
            # were therefore never added to the resolver at all.  Exact alias
            # resolution is authoritative, so a registered one-character
            # Chinese alias is safe to attempt as well.
            if _CJK_RE.fullmatch(token):
                terms.append(token)
                if len(token) <= 32:
                    terms.extend(token[index : index + size] for size in range(1, min(8, len(token)) + 1) for index in range(len(token) - size + 1))
            else:
                terms.append(token)
        candidates: list[tuple[str, str, int]] = []
        for term in dict.fromkeys(str(value).strip() for value in terms if str(value).strip()):
            resolution = resolver(term)
            matches = tuple(getattr(resolution, "matches", ()) or ())
            if matches:
                longest = max(len(str(_value(match, "alias", default=""))) for match in matches)
                ids = tuple(
                    dict.fromkeys(
                        str(_value(match, "entity_id", default=""))
                        for match in matches
                        if len(str(_value(match, "alias", default=""))) == longest
                        and _value(match, "entity_id", default="") not in (None, "")
                    )
                )
            else:
                ids = tuple(dict.fromkeys(str(item) for item in getattr(resolution, "entity_ids", ()) if str(item)))
            if len(ids) > 1:
                raise RetrievalAmbiguityError(f"别名无法唯一解析: {term!r} -> {ids}")
            if ids:
                candidates.append((term, ids[0], len(term)))
            elif term in request.target_entities:
                # Target entities may already be stable IDs and need not have
                # a human-facing alias row.
                candidates.append((term, term, 0))
        # If both a short and a longer alias match the same text span, only
        # retain the longest match.  This mirrors the Graph channel contract
        # and prevents ``甲`` from expanding alongside a more specific ``甲乙``.
        entity_ids: list[str] = []
        for term, entity_id, length in candidates:
            shadowed = any(
                other_length > length and term and term in other_term
                for other_term, _other_id, other_length in candidates
            )
            if not shadowed:
                entity_ids.append(entity_id)
        return tuple(dict.fromkeys(entity_ids))

    def _graph(self, request: RetrievalRequest, fingerprint: str | None) -> tuple[Evidence, ...]:
        entity_ids = set(self._resolve_entity_ids(request))
        result: list[Evidence] = []
        neighbors = getattr(self.graph_reader, "neighbors", None)
        if not callable(neighbors):
            raise RetrievalConfigurationError("graph_reader 缺少 neighbors()")
        for relation in neighbors(entity_ids, self.relation_types, self.max_hops):
            metadata = _as_mapping(relation)
            result.append(
                self.normalizer.normalize(
                    relation,
                    EvidenceChannel.GRAPH,
                    timeline_id=request.graph_key.timeline_id,
                    source_fingerprint=fingerprint,
                    reason="Graph：显式关系白名单邻接扩展",
                    authority=str(_value(relation, "authority", default="graph")),
                )
            )
        documents_for_entities = getattr(self.graph_reader, "documents_for_entities", None)
        if not callable(documents_for_entities):
            raise RetrievalConfigurationError("graph_reader 缺少 documents_for_entities()")
        for hit in documents_for_entities(entity_ids, None):
            document_type = str(
                getattr(hit, "document_type", "")
                or _value(hit, "document_type", default="")
            )
            if document_type in _SUMMARY_TYPES:
                # Summaries belong to Temporal; keeping them out of Graph
                # prevents cross-channel de-duplication from hiding the
                # temporal provenance.
                continue
            result.append(
                self.normalizer.normalize(
                    hit,
                    EvidenceChannel.GRAPH,
                    timeline_id=request.graph_key.timeline_id,
                    source_fingerprint=fingerprint,
                    reason="Graph：实体关联文档",
                    authority="graph",
                )
            )
        return _unique_evidence(result)

    def _temporal(self, request: RetrievalRequest, fingerprint: str | None) -> tuple[Evidence, ...]:
        result: list[Evidence] = []
        temporal_hits = self._query_hits(
            self.graph_reader,
            self._queries(request),
            extra=self._documents_for_target_entities(request),
        )
        for match in temporal_hits:
            hit = match.value
            document_type = str(getattr(hit, "document_type", "") or _value(hit, "document_type", default=""))
            metadata = _as_mapping(hit)
            if document_type not in _SUMMARY_TYPES and not bool(_value(hit, "is_summary", default=False)):
                continue
            if bool(_value(hit, "stale", default=False)) or str(_value(hit, "freshness", default="")).lower() == "stale":
                continue
            ownership = str(_value(hit, "ownership", default="auto"))
            result.append(
                replace(self.normalizer.normalize(
                    hit,
                    EvidenceChannel.TEMPORAL,
                    timeline_id=request.graph_key.timeline_id,
                    source_fingerprint=fingerprint,
                    reason=self._query_reason(
                        f"Temporal：{ownership} summary 覆盖历史内容",
                        match,
                    ),
                    authority="temporal-summary",
                ), channel_score=match.channel_score)
            )
        return tuple(result)

    def _documents_for_target_entities(self, request: RetrievalRequest) -> list[Any]:
        """Load entity-bound documents without reaching through to SQLite.

        This supplements free-text search for summaries and authority records
        whose wording does not contain the complete outline string.
        """

        entity_ids = set(self._resolve_entity_ids(request))
        if not entity_ids:
            return []
        method = getattr(self.graph_reader, "documents_for_entities", None)
        if not callable(method):
            raise RetrievalConfigurationError("graph_reader 缺少 documents_for_entities()")
        return list(method(entity_ids, None))

    def _lexical(self, request: RetrievalRequest, fingerprint: str | None) -> tuple[Evidence, ...]:
        result: list[Evidence] = []
        for match in self._query_hits(self.graph_reader, self._queries(request)):
            result.append(
                replace(self.normalizer.normalize(
                    match.value,
                    EvidenceChannel.LEXICAL,
                    timeline_id=request.graph_key.timeline_id,
                    source_fingerprint=fingerprint,
                    reason=self._query_reason(
                        "Lexical：SQLite FTS5 trigram 词面召回",
                        match,
                    ),
                    authority="lexical",
                ), channel_score=match.channel_score)
            )
        return tuple(result)

    def _semantic(self, request: RetrievalRequest, fingerprint: str | None) -> tuple[Evidence, ...]:
        if not self.semantic_enabled:
            return ()
        assert self.semantic_provider is not None
        return tuple(
            self.normalizer.normalize(
                value,
                EvidenceChannel.SEMANTIC,
                timeline_id=request.graph_key.timeline_id,
                source_fingerprint=fingerprint,
                reason="Semantic：可选实验通道",
                authority="semantic",
            )
            for value in self.semantic_provider(request)
        )


def _unique_evidence(items: Iterable[Evidence]) -> tuple[Evidence, ...]:
    result: list[Evidence] = []
    seen: set[tuple[Any, ...]] = set()
    for item in items:
        key = (
            item.document_id,
            item.fact_type,
            item.timeline_id,
            item.valid_at,
            item.source_version,
            item.content,
        )
        if key not in seen:
            seen.add(key)
            result.append(item)
    return tuple(result)


# Names used by different callers during the migration all point at the same
# service; no separate behavior is hidden behind the aliases.
HybridRetriever = RetrieverService
ServiceRetriever = RetrieverService
RetrievalService = RetrieverService


__all__ = [
    "EvidenceNormalizer",
    "HybridRetriever",
    "RetrievalAmbiguityError",
    "RetrievalConfigurationError",
    "RetrievalError",
    "RetrievalService",
    "RetrieverService",
    "ServiceRetriever",
]
