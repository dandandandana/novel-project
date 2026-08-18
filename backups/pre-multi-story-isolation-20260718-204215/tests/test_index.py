from pathlib import Path

from novel_rag.documents import RagDocument
from novel_rag.index import SqliteIndex


def doc(path: Path, story: str, timeline: str, status: str, title: str, text: str) -> RagDocument:
    return RagDocument(path, {
        "story_id": story, "timeline_id": timeline, "document_type": "history",
        "title": title, "status": status, "version": "1.0",
    }, {"content": text})


def test_search_enforces_story_timeline_and_default_status(tmp_path):
    index = SqliteIndex(tmp_path / "rag.db")
    index.rebuild([
        doc(tmp_path / "a.yaml", "s1", "main", "canon", "主线", "圣杯 战斗结束"),
        doc(tmp_path / "b.yaml", "s1", "school-if", "canon", "IF线", "圣杯 校园出现"),
        doc(tmp_path / "c.yaml", "s1", "main", "draft", "草稿", "圣杯 草稿秘密"),
        doc(tmp_path / "d.yaml", "s2", "main", "canon", "别的作品", "圣杯 另一个故事"),
    ])
    results = index.search("圣杯", "s1", "main")
    assert [result.title for result in results] == ["主线"]


def test_draft_requires_explicit_status(tmp_path):
    index = SqliteIndex(tmp_path / "rag.db")
    index.rebuild([doc(tmp_path / "draft.yaml", "s", "main", "draft", "草稿", "未确认事件")])
    assert index.search("未确认事件", "s", "main") == []
    assert [r.title for r in index.search("未确认事件", "s", "main", statuses=["draft"])] == ["草稿"]

