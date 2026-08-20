from __future__ import annotations

from pathlib import Path

import yaml

from novel_rag.feedback import create_feedback
from novel_rag.identity import GraphKey
from novel_rag.importers import import_outline
from novel_rag.scaffold import create_story


def _target_library(tmp_path: Path) -> Path:
    root = tmp_path / "library"
    (root / "registry").mkdir(parents=True)
    (root / "registry" / "layout.yaml").write_text(
        yaml.safe_dump({"layout_version": "2.0"}), encoding="utf-8"
    )
    (root / "registry" / "stories.yaml").write_text(
        yaml.safe_dump({"stories": []}), encoding="utf-8"
    )
    create_story(root, story_id="demo", title="Demo", inherit_shared=False)
    return root


def test_target_only_import_and_feedback_promote_canonical_graphs(tmp_path: Path) -> None:
    library = _target_library(tmp_path)
    source = tmp_path / "outline.txt"
    source.write_text("TARGET-ONLY-OUTLINE 必须保留。", encoding="utf-8")

    imported = import_outline(
        source,
        library_root=library,
        index_root=library / "index",
        story_id="demo",
        timeline_id="main",
        title="Target outline",
        volume=1,
        chapter=1,
    )
    feedback = create_feedback(
        library_root=library,
        index_root=library / "index",
        story_id="demo",
        timeline_id="main",
        target_type="runtime",
        target_id="run-target-only",
        issue="TARGET-ONLY-FEEDBACK",
    )

    assert imported.status in {"imported", "pending"}
    assert feedback.status in {"imported", "pending"}
    assert imported.path.parts[-4:-1] == ("main", "outline", "chapters")
    assert feedback.path.parts[-3:-1] == ("feedback", "imported")
    assert (library / "stories" / "demo" / "common" / "registry" / "version-map.yaml").is_file()
    assert not (library / "stories" / "demo" / "registry").exists()
    assert (library / "index" / "shared.db").is_file()
    assert GraphKey("demo", "main").graph_path(library / "index").is_file()
