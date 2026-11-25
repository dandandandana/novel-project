"""Generation-facing retrieval composition and legacy adaptation.

The generation pipeline consumes only the stable retrieval contracts.  The
small adapter in this module is deliberately kept at the application edge:
it lets the old CLI continue to work while callers migrate to an injected
``Retriever`` implementation.  It reads validated YAML documents through the
existing document service and does not know about an index connection, row,
or storage-specific result type.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any, Callable, Iterable, Mapping

from ..documents import RagDocument
from ..identity import GraphKey
from ..retrieval import (
    ContextAssembler,
    ContextBundle,
    Evidence,
    EvidenceChannel,
    RetrievalRequest,
    Retriever,
)
from ..service import load_valid_documents
from .types import GenerationError


_AUTHORITY_DOCUMENT_TYPES = {
    "canon",
    "current",
    "character_state",
    "world_state",
    "rule",
    "feedback",
    "judgment_spec",
    "generator_spec",
    "audit_spec",
    "style_audit",
    "style_sample",
}
_SUMMARY_DOCUMENT_TYPES = {
    "summary",
    "scene-summary",
    "scene_summary",
    "chapter-summary",
    "chapter_summary",
    "volume-summary",
    "volume_summary",
}
_DEFAULT_STATUS = {"active", "canon"}
_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{2,}|[\u3400-\u9fff]+", re.UNICODE)


@dataclass(frozen=True, slots=True)
class ContextItem:
    """Compatibility representation used by the existing generation stages.

    This is intentionally a generation value object rather than an index
    result.  Its fields match the historical JSON/context shape so model
    prompts and the public ``retrieve_context`` helper remain stable.
    """

    document_id: str
    title: str
    document_type: str
    status: str
    source_file: str
    score: float
    content: str
    metadata: dict[str, Any]


def _key_part(key: Any, name: str, default: str = "") -> str:
    if isinstance(key, Mapping):
        value = key.get(name, default)
    else:
        value = getattr(key, name, default)
    return str(value or default)


def _document_type(document: RagDocument) -> str:
    return str(document.metadata.get("document_type") or "")


def _document_status(document: RagDocument) -> str:
    return str(document.metadata.get("status") or "")


def _document_is_stale(document: RagDocument) -> bool:
    metadata = document.metadata
    freshness = str(metadata.get("freshness") or "").strip().lower()
    return bool(metadata.get("stale")) or freshness == "stale"


def _query_terms(value: str) -> tuple[str, ...]:
    compact = " ".join(str(value or "").split()).strip()
    if not compact:
        return ()
    terms: list[str] = [compact[:160]]
    terms.extend(token for token in _TOKEN_RE.findall(compact) if token not in terms)
    return tuple(dict.fromkeys(term for term in terms if term))


def _match_score(text: str, queries: Iterable[str]) -> float:
    """Score one document using only local lexical evidence.

    This is a migration fallback, not a replacement for the five-channel
    retriever.  The score is consumed within the compatibility adapter only;
    it is never compared with a score from another channel.
    """

    haystack = text.casefold()
    score = 0.0
    for query in queries:
        needle = query.casefold()
        if not needle:
            continue
        if needle in haystack:
            score += 2.0 + min(len(needle), 80) / 80.0
        else:
            score += sum(1.0 for token in _query_terms(query)[1:] if token.casefold() in haystack)
    return score


def _content(document: RagDocument) -> str:
    return document.searchable_text().strip()


class LegacyRetrieverAdapter:
    """Read the legacy YAML corpus behind the stable Retriever contract.

    The adapter exists only for callers that have not yet assembled graph
    readers.  It retains story/timeline isolation and active/canon filtering,
    and keeps shared documents in the Authority layer.  New callers should
    inject a graph-backed Retriever instead.
    """

    def __init__(self, library_root: Path, index_root: Path | None = None, *, limit: int = 12) -> None:
        self.library_root = Path(library_root).resolve()
        self.index_root = Path(index_root).resolve() if index_root is not None else self.library_root / "index"
        if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
            raise ValueError("legacy retrieval limit 必须是正整数")
        self.limit = limit
        self.assembler = ContextAssembler()

    def retrieve(self, request: RetrievalRequest) -> ContextBundle:
        if not isinstance(request, RetrievalRequest):
            raise TypeError("LegacyRetrieverAdapter.retrieve 需要 RetrievalRequest")
        story_id = _key_part(request.graph_key, "story_id")
        timeline_id = _key_part(request.graph_key, "timeline_id")
        # Preserve the old CLI contract: the compatibility path must not turn
        # a missing index into a silently successful generation.  Both the
        # legacy story path and the new per-GraphKey path are accepted while
        # the application composition root is being migrated.
        legacy_path = self.index_root / "stories" / f"{story_id}.db"
        graph_path = self.index_root / "graphs" / story_id / f"{timeline_id}.db"
        shared_path = self.index_root / "shared.db"
        if not self.index_root.exists() or not (legacy_path.exists() or graph_path.exists()):
            expected = graph_path if graph_path.parent.exists() else legacy_path
            raise GenerationError(f"小说索引不存在，请先执行 novel-rag index: {expected}")
        if not shared_path.exists():
            raise GenerationError(f"共享系统索引不存在，请先执行 novel-rag index: {shared_path}")
        try:
            documents, issues = load_valid_documents(
                self.library_root,
                story_id=story_id,
                include_shared=True,
            )
        except (OSError, ValueError) as exc:
            raise GenerationError(f"读取资料失败: {exc}") from exc
        if issues:
            # A legacy caller used to receive index failures at search time.
            # Keep that failure explicit instead of silently constructing an
            # empty context from invalid YAML.
            raise GenerationError("当前小说资料校验失败: " + "; ".join(issue.message for issue in issues[:3]))

        queries = tuple(dict.fromkeys((request.outline, *request.target_entities)))
        authority: list[Evidence] = []
        temporal: list[Evidence] = []
        lexical: list[Evidence] = []
        for document in documents:
            metadata = document.metadata
            document_story = str(metadata.get("story_id") or "")
            document_timeline = str(metadata.get("timeline_id") or "")
            is_shared = document_story == "__shared__" and document_timeline == "global"
            if not is_shared and (document_story != story_id or document_timeline != timeline_id):
                continue
            if _document_status(document) not in _DEFAULT_STATUS:
                continue
            if _document_is_stale(document):
                # In particular, a user-owned stale summary must not leak into
                # generation while the graph is awaiting a rebuild/merge.
                continue
            body = _content(document)
            score = _match_score(body, queries)
            if score <= 0:
                continue
            document_type = _document_type(document)
            channel = (
                EvidenceChannel.TEMPORAL
                if document_type in _SUMMARY_DOCUMENT_TYPES
                else EvidenceChannel.AUTHORITY
                if is_shared or document_type in _AUTHORITY_DOCUMENT_TYPES
                else EvidenceChannel.LEXICAL
            )
            evidence = Evidence(
                document_id=document.document_id,
                channel=channel,
                # A legacy document type is the best available authority
                # label.  It remains metadata, never a cross-channel score.
                authority=str(metadata.get("authority") or document_type or channel.value),
                fact_type=(str(metadata["fact_type"]) if metadata.get("fact_type") not in (None, "") else None),
                valid_at=(str(metadata["valid_at"]) if metadata.get("valid_at") not in (None, "") else None),
                entity_ids=tuple(str(value) for value in (metadata.get("entity_ids") or ())),
                reason="legacy YAML compatibility adapter：按 story/timeline 隔离后的词面命中",
                source_version=(str(metadata["version"]) if metadata.get("version") not in (None, "") else None),
                source_fingerprint=(str(metadata["source_fingerprint"]) if metadata.get("source_fingerprint") not in (None, "") else None),
                content=body,
                channel_score=score,
                timeline_id="global" if is_shared else timeline_id,
                status=_document_status(document),
            )
            if channel is EvidenceChannel.AUTHORITY:
                authority.append(evidence)
            elif channel is EvidenceChannel.TEMPORAL:
                temporal.append(evidence)
            else:
                lexical.append(evidence)

        # ``ContextAssembler`` owns layer ordering, deduplication, conflict
        # accounting, and budget limits even for the compatibility path.
        return self.assembler.assemble(
            request,
            mandatory=authority,
            temporal_memory=temporal,
            lexical_supplements=lexical,
        )


def build_legacy_retriever(
    library_root: Path,
    index_root: Path | None = None,
    *,
    limit: int = 12,
) -> LegacyRetrieverAdapter:
    """Construct the opt-in legacy retriever for migration callers.

    The CLI owns the ``--legacy`` switch, so it can select this helper
    explicitly without changing generation's graph-backed default.  Keeping
    construction in one named API also prevents callers from accidentally
    using a legacy adapter as an implicit fallback.
    """

    return LegacyRetrieverAdapter(Path(library_root), Path(index_root) if index_root is not None else None,
                                  limit=limit)


RetrieverFactory = Callable[[Path, Path], Retriever]
_default_retriever_factory: RetrieverFactory | None = None


class _CompositionRetriever:
    """Lazily open the graph reader selected by each request's GraphKey."""

    def __init__(self, library_root: Path, index_root: Path, builder: Callable[..., Any]) -> None:
        self.library_root = Path(library_root)
        self.index_root = Path(index_root)
        self.builder = builder

    def retrieve(self, request: RetrievalRequest) -> ContextBundle:
        if not isinstance(request, RetrievalRequest):
            raise TypeError("_CompositionRetriever.retrieve 需要 RetrievalRequest")
        provider = self._build(request)
        try:
            return provider.retrieve(request)
        finally:
            close = getattr(provider, "close", None)
            if callable(close):
                close()

    def _build(self, request: RetrievalRequest) -> Retriever:
        # The production composition root accepts (library_root, GraphKey,
        # index_directory=...).  The keyword/positional fallbacks keep this
        # boundary compatible with small application adapters during rollout.
        attempts = (
            lambda: self.builder(self.library_root, request.graph_key, index_directory=self.index_root),
            lambda: self.builder(
                library_root=self.library_root,
                key=request.graph_key,
                index_directory=self.index_root,
            ),
            lambda: self.builder(self.library_root, request.graph_key, index_root=self.index_root),
            lambda: self.builder(
                library_root=self.library_root,
                index_root=self.index_root,
                graph_key=request.graph_key,
            ),
            lambda: self.builder(library_root=self.library_root, index_root=self.index_root),
        )
        last_error: TypeError | None = None
        for attempt in attempts:
            try:
                provider = attempt()
            except TypeError as exc:
                last_error = exc
                continue
            if not hasattr(provider, "retrieve"):
                raise TypeError("build_graph_retriever 必须返回带 retrieve() 的对象")
            return provider
        assert last_error is not None
        raise last_error


def set_default_retriever_factory(factory: RetrieverFactory | None) -> None:
    """Configure the application composition root used by ``generate``.

    Passing ``None`` restores the application graph-retriever factory.  The
    legacy YAML adapter is intentionally not selected implicitly; callers
    that still need it must pass ``LegacyRetrieverAdapter`` explicitly (or
    inject a factory returning one).
    """

    global _default_retriever_factory
    if factory is not None and not callable(factory):
        raise TypeError("retriever factory 必须可调用或 None")
    _default_retriever_factory = factory


def build_default_retriever(library_root: Path, index_root: Path) -> Retriever:
    """Build the application Retriever without silently falling back to YAML.

    Importing the composition root lazily keeps the generation package usable
    by tooling that only needs contracts, while ensuring the normal runtime
    path uses graph readers and their missing/stale checks.
    """

    if _default_retriever_factory is not None:
        retriever = _default_retriever_factory(Path(library_root), Path(index_root))
        if not hasattr(retriever, "retrieve"):
            raise TypeError("retriever factory 必须返回带 retrieve() 的对象")
        return retriever
    try:
        from ..composition import build_graph_retriever
    except (ImportError, AttributeError) as exc:
        raise GenerationError(
            "默认图 Retriever composition 不可用；请配置 build_graph_retriever，"
            "或显式注入 LegacyRetrieverAdapter"
        ) from exc
    return _CompositionRetriever(Path(library_root), Path(index_root), build_graph_retriever)


def build_retrieval_request(contract: Any) -> RetrievalRequest:
    """Translate a generation contract into the stable retrieval request."""

    request = contract.request
    try:
        graph_key = GraphKey(request.story_id, request.timeline_id)
    except (TypeError, ValueError) as exc:
        raise GenerationError(f"生成请求身份无效，无法构造 GraphKey: {exc}") from exc
    events = getattr(contract.outline, "required_events", ())
    target_entities = tuple(
        dict.fromkeys(
            str(value).strip()
            for event in events
            for value in (getattr(event, "actor", ""), getattr(event, "target", ""))
            if str(value).strip()
        )
    )
    outline_parts = [
        str(getattr(event, "event", "")).strip()
        for event in events
        if str(getattr(event, "event", "")).strip()
    ]
    required_result = str(getattr(contract.outline, "required_result", "")).strip()
    if required_result:
        outline_parts.append(required_result)
    if not outline_parts:
        outline_parts.append(str(getattr(contract.outline, "raw_input", "")).strip())
    extensions = getattr(request, "extensions", {}) or {}
    target_stage = extensions.get("target_stage") if isinstance(extensions, Mapping) else None
    raw_budget = extensions.get("token_budget") if isinstance(extensions, Mapping) else None
    if raw_budget in (None, ""):
        token_budget = None
    else:
        try:
            token_budget = int(raw_budget)
        except (TypeError, ValueError) as exc:
            raise GenerationError(f"token_budget 无效: {raw_budget!r}") from exc
    try:
        return RetrievalRequest(
            graph_key=graph_key,
            outline="\n".join(part for part in outline_parts if part),
            target_entities=target_entities,
            target_stage=str(target_stage) if target_stage not in (None, "") else None,
            token_budget=token_budget,
        )
    except (TypeError, ValueError) as exc:
        raise GenerationError(f"检索请求无效: {exc}") from exc


def retrieve_bundle(
    contract: Any,
    index_root: Path,
    *,
    library_root: Path | None = None,
    retriever: Retriever | None = None,
) -> tuple[RetrievalRequest, ContextBundle]:
    """Retrieve one context bundle, rejecting conflicts and stale evidence."""

    request = build_retrieval_request(contract)
    try:
        provider = retriever or build_default_retriever(
            library_root or Path(index_root).parent,
            index_root,
        )
    except GenerationError:
        raise
    except Exception as exc:
        raise GenerationError(
            f"默认图 Retriever 构建失败（图可能缺失、身份不符或已 stale）: {exc}"
        ) from exc
    if not hasattr(provider, "retrieve"):
        raise TypeError("retriever 必须提供 retrieve(request) 方法")
    try:
        bundle = provider.retrieve(request)
    except GenerationError:
        raise
    except Exception as exc:
        # Graph readers surface identity/schema/fingerprint failures here.  A
        # generation caller must see an actionable failure, never an empty
        # context or an implicit rebuild.
        raise GenerationError(f"检索失败（图可能缺失、身份不符或已 stale）: {exc}") from exc
    if not isinstance(bundle, ContextBundle):
        raise GenerationError("Retriever 必须返回 ContextBundle")
    if bundle.conflicts:
        reasons = "；".join(conflict.reason for conflict in bundle.conflicts[:2])
        raise GenerationError(f"检索上下文存在未解决冲突，生成已停止: {reasons}")
    stale = [
        item.document_id
        for item in bundle.all_evidence
        if str(item.status or "").strip().lower() == "stale"
    ]
    if stale:
        raise GenerationError("检索上下文包含 stale 证据，生成已停止: " + ", ".join(stale[:5]))
    stale_notes = [
        str(note)
        for note in bundle.receipt.notes
        if "stale" in str(note).casefold() or "过期" in str(note)
    ]
    if stale_notes:
        raise GenerationError("检索回执标记图已 stale，生成已停止: " + "；".join(stale_notes[:2]))
    return request, bundle


def _context_item(evidence: Evidence, request: RetrievalRequest) -> ContextItem:
    document_type = evidence.fact_type or evidence.authority
    known_types = _AUTHORITY_DOCUMENT_TYPES | _SUMMARY_DOCUMENT_TYPES | {"outline", "history"}
    if document_type not in known_types:
        document_type = "context"
    metadata: dict[str, Any] = {
        "story_id": _key_part(request.graph_key, "story_id"),
        "timeline_id": evidence.timeline_id or _key_part(request.graph_key, "timeline_id"),
        "document_type": document_type,
        "status": evidence.status or "active",
        "authority": evidence.authority,
        "channel": evidence.channel_name,
        "reason": evidence.reason,
    }
    if evidence.source_version is not None:
        metadata["version"] = evidence.source_version
    if evidence.source_fingerprint is not None:
        metadata["source_fingerprint"] = evidence.source_fingerprint
    if evidence.valid_at is not None:
        metadata["valid_at"] = evidence.valid_at
    return ContextItem(
        document_id=evidence.document_id,
        title=evidence.content.splitlines()[0][:120] if evidence.content else evidence.document_id,
        document_type=document_type,
        status=evidence.status or "active",
        source_file="",
        score=float(evidence.channel_score or 0.0),
        content=evidence.content,
        metadata=metadata,
    )


def bundle_to_context_items(
    bundle: ContextBundle,
    request: RetrievalRequest,
    *,
    limit: int = 12,
) -> list[ContextItem]:
    """Convert layered evidence to the historical generation context shape."""

    if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
        raise ValueError("context limit 必须是正整数")
    layers = (
        bundle.mandatory,
        bundle.graph_context,
        bundle.temporal_memory,
        bundle.lexical_supplements,
        bundle.semantic_supplements,
    )
    result: list[ContextItem] = []
    seen: set[str] = set()
    for layer in layers:
        for evidence in layer:
            if evidence.document_id in seen:
                continue
            seen.add(evidence.document_id)
            result.append(_context_item(evidence, request))
            if len(result) >= limit:
                return result
    return result


__all__ = [
    "ContextItem",
    "LegacyRetrieverAdapter",
    "RetrieverFactory",
    "build_legacy_retriever",
    "build_default_retriever",
    "build_retrieval_request",
    "bundle_to_context_items",
    "retrieve_bundle",
    "set_default_retriever_factory",
]
