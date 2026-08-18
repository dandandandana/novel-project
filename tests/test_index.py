from pathlib import Path

from novel_rag.documents import RagDocument
from novel_rag.index import SqliteIndex, rebuild_isolated_indexes, search_isolated


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


def test_isolated_indexes_do_not_leak_story_content_but_share_system_rules(tmp_path):
    documents = [
        doc(tmp_path / "s1.yaml", "s1", "main", "canon", "第一部人物", "隔离哨兵 苍蓝人物"),
        doc(tmp_path / "s2.yaml", "s2", "main", "canon", "第二部人物", "隔离哨兵 赤红人物"),
        RagDocument(
            tmp_path / "shared.yaml",
            {
                "document_id": "shared-rule-v1.0",
                "story_id": "__shared__",
                "timeline_id": "global",
                "document_type": "rule",
                "title": "共享文风规则",
                "status": "active",
                "version": "1.0",
            },
            {"content": "隔离哨兵 共享审计"},
        ),
    ]
    index_root = tmp_path / "index"
    rebuild_isolated_indexes(index_root, documents, ["s1", "s2"])

    s1 = search_isolated(index_root, "隔离哨兵", "s1", "main", limit=10)
    s2 = search_isolated(index_root, "隔离哨兵", "s2", "main", limit=10)
    assert {item.title for item in s1} == {"第一部人物", "共享文风规则"}
    assert {item.title for item in s2} == {"第二部人物", "共享文风规则"}
    assert {item.title for item in search_isolated(
        index_root, "隔离哨兵", "s1", "main", limit=10, include_shared=False
    )} == {"第一部人物"}


def test_rebuild_removes_unregistered_story_index(tmp_path):
    index_root = tmp_path / "index"
    rebuild_isolated_indexes(index_root, [doc(
        tmp_path / "old.yaml", "old-story", "main", "canon", "旧作品", "旧索引"
    )], ["old-story"])
    stale = index_root / "stories" / "old-story.db"
    assert stale.exists()

    rebuild_isolated_indexes(index_root, [], [])
    assert not stale.exists()
