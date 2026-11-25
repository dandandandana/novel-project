from __future__ import annotations

import inspect
from pathlib import Path

import yaml

from novel_rag.composition import IndexBuildResult, rebuild_graph_projections
from novel_rag.documents import RagDocument
from novel_rag.generation import LegacyRetrieverAdapter, generate


def _doc(path: Path, story: str, timeline: str, status: str, title: str, text: str) -> RagDocument:
    return RagDocument(path, {
        "story_id": story, "timeline_id": timeline, "document_type": "history",
        "title": title, "status": status, "version": "1.0",
    }, {"content": text})


def _make_library(tmp_path: Path, *, preferences: str | None = "默认") -> tuple[Path, Path]:
    library = tmp_path / "novel-rag"
    story = library / "stories" / "demo"
    (library / "registry").mkdir(parents=True)
    (library / "registry" / "layout.yaml").write_text(yaml.safe_dump({"layout_version": "2.0"}), encoding="utf-8")
    (library / "registry" / "stories.yaml").write_text(yaml.safe_dump({"stories": [{"story_id": "demo"}]}), encoding="utf-8")
    (story / "registry").mkdir(parents=True)
    (story / "registry" / "timelines.yaml").write_text(
        yaml.safe_dump({"timelines": [{"story_id": "demo", "timeline_id": "main"}]}), encoding="utf-8")
    if preferences is not None:
        (story / "author-preferences.txt").write_text(preferences, encoding="utf-8")
    index = library / "index"
    (index / "stories").mkdir(parents=True)
    from novel_rag.index import SqliteIndex
    SqliteIndex(index / "stories" / "demo.db").rebuild([])
    SqliteIndex(index / "shared.db").rebuild([])
    return library, index


class FakeModel:
    def __init__(self, repair_until: int = 0):
        self.calls: list[str] = []
        self.repair_until = repair_until

    def __call__(self, stage: str, payload: dict):
        self.calls.append(stage)
        if stage == "normalize":
            return {"outline": {"required_events": [{"event": "甲交出信", "actor": "甲", "required_result": "乙拿到信"}]}}
        if stage == "decide_behavior":
            return {"action": "甲把信递给乙"}
        if stage == "derive_result":
            return {"result": "乙拿到信", "state_deltas": {"乙": {"knowledge": {"has_letter": True}}}}
        if stage == "render_prose":
            return {"text": "甲把信递给乙，乙拿到信。"}
        if stage == "validate":
            repairs = self.calls.count("repair")
            if repairs < self.repair_until:
                return {"issues": [{"check": "outline", "message": "缺少指定细节", "severity": "repairable"}]}
            return {"status": "pass", "issues": []}
        if stage == "repair":
            text = payload["text"] + " 他确认对方已经拿稳。"
            return {"text": text, "preserved_event_ids": payload["required_response"]["preserved_event_ids"],
                    "event_evidence": {event_id: {"excerpt": "甲把信递给乙，乙拿到信。", "actor": "甲", "result": "乙拿到信"}
                                       for event_id in payload["required_response"]["preserved_event_ids"]}}
        raise AssertionError(stage)


def test_rebuild_reports_each_partition_in_deterministic_order(tmp_path: Path) -> None:
    documents = [
        _doc(tmp_path / "s1.yaml", "s1", "main", "canon", "主线人物", "进度回调 苍蓝事件"),
        RagDocument(
            tmp_path / "shared.yaml",
            {
                "document_id": "shared-rule-v1.0",
                "story_id": "__shared__",
                "timeline_id": "global",
                "document_type": "rule",
                "title": "共享规则",
                "status": "active",
                "version": "1.0",
            },
            {"content": "进度回调 共享审计"},
        ),
    ]
    index_dir = tmp_path / "index"
    collector: list[IndexBuildResult] = []
    results = rebuild_graph_projections(
        index_dir,
        documents,
        ["s1"],
        library_root=tmp_path,
        on_partition=collector.append,
    )
    assert [row.scope for row in collector] == ["shared", "s1"]
    assert results == collector
    assert all(isinstance(row, IndexBuildResult) for row in collector)

    again: list[IndexBuildResult] = []
    rebuild_graph_projections(index_dir, documents, ["s1"], library_root=tmp_path,
                              on_partition=again.append)
    assert [row.scope for row in again] == [row.scope for row in collector]


def test_generate_emits_progress_milestones_in_order(tmp_path: Path) -> None:
    library, index = _make_library(tmp_path)
    messages: list[str] = []
    result = generate({"story_id": "demo", "outline": "交信"}, FakeModel(),
                      library_root=library, index_root=index, output_root=tmp_path / "outputs",
                      retriever=LegacyRetrieverAdapter(library, index),
                      progress=messages.append)
    assert result.status == "pass"
    joined = "\n".join(messages)
    assert "检索上下文已加载" in joined
    assert "初稿完成，正在润色……" in joined
    assert "润色完成，进入审计……" in joined
    assert messages.index("检索上下文已加载") < messages.index("初稿完成，正在润色……") < messages.index("润色完成，进入审计……")


def test_generate_reports_each_audit_repair_round(tmp_path: Path) -> None:
    library, index = _make_library(tmp_path)
    messages: list[str] = []
    result = generate({"story_id": "demo", "outline": "交信"}, FakeModel(repair_until=2),
                      library_root=library, index_root=index, output_root=tmp_path / "outputs",
                      retriever=LegacyRetrieverAdapter(library, index),
                      progress=messages.append)
    assert result.attempts == 2
    rounds = [message for message in messages if message.startswith("审计定向修复")]
    assert rounds == ["审计定向修复 第 1 轮……", "审计定向修复 第 2 轮……"]
    assert messages.index("润色完成，进入审计……") < messages.index(rounds[0])


def test_callbacks_default_to_previous_behavior(tmp_path: Path) -> None:
    from novel_rag.generation.pipeline import generate as pipeline_generate

    parameters = inspect.signature(pipeline_generate).parameters
    assert parameters["progress"].default is None
    assert parameters["progress"].kind is inspect.Parameter.KEYWORD_ONLY
    rebuild_parameters = inspect.signature(rebuild_graph_projections).parameters
    assert rebuild_parameters["on_partition"].default is None
    assert rebuild_parameters["on_partition"].kind is inspect.Parameter.KEYWORD_ONLY

    documents = [_doc(tmp_path / "s1.yaml", "s1", "main", "canon", "主线人物", "默认行为 事件")]
    index_dir = tmp_path / "index"
    results = rebuild_graph_projections(index_dir, documents, ["s1"], library_root=tmp_path)
    assert [row.scope for row in results] == ["shared", "s1"]

    library, index = _make_library(tmp_path)
    result = generate({"story_id": "demo", "outline": "交信"}, FakeModel(),
                      library_root=library, index_root=index, output_root=tmp_path / "outputs",
                      retriever=LegacyRetrieverAdapter(library, index))
    assert result.status == "pass"
