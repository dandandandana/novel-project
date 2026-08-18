from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from novel_rag.index import rebuild_isolated_indexes, search_isolated
from novel_rag.scaffold import create_story
from novel_rag.service import load_valid_documents


def write_yaml(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(value, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def story_document(story_id: str, marker: str) -> dict:
    return {
        "metadata": {
            "document_id": f"{story_id}-sentinel-v1.0",
            "story_id": story_id,
            "timeline_id": "main",
            "document_type": "canon",
            "title": f"{story_id} 独立人物",
            "status": "canon",
            "version": "1.0",
        },
        "content": f"isolation_probe {marker}",
    }


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="novel-rag-isolation-") as temp_name:
        library = Path(temp_name) / "novel-rag"
        write_yaml(library / "registry" / "layout.yaml", {"layout_version": "2.0"})
        write_yaml(library / "registry" / "stories.yaml", {"stories": []})
        write_yaml(
            library / "shared" / "registry" / "module-defaults.yaml",
            {"modules": [{"module_type": "rule", "active_versions": ["shared-sentinel-v1.0"]}]},
        )
        write_yaml(
            library / "shared" / "registry" / "version-map.yaml",
            {"versions": [{"document_family": "shared-sentinel", "current": "shared-sentinel-v1.0"}]},
        )
        write_yaml(
            library / "shared" / "rules" / "active" / "sentinel.yaml",
            {
                "metadata": {
                    "document_id": "shared-sentinel-v1.0",
                    "story_id": "__shared__",
                    "timeline_id": "global",
                    "document_type": "rule",
                    "module_type": "ruler",
                    "priority": "global",
                    "enforcement": "mandatory",
                    "title": "共享系统哨兵",
                    "status": "active",
                    "version": "1.0",
                },
                "rule": {"content": "isolation_probe shared_system"},
            },
        )

        for story_id, title, marker in (
            ("blue-novel", "蓝色小说", "blue_character"),
            ("red-novel", "红色小说", "red_character"),
        ):
            story = create_story(library, story_id=story_id, title=title)
            write_yaml(story / "canon" / "sentinel.yaml", story_document(story_id, marker))

        documents, issues = load_valid_documents(library)
        if issues:
            raise AssertionError("\n".join(f"{issue.path}: {issue.message}" for issue in issues))
        index_root = library / "index"
        rebuild_isolated_indexes(index_root, documents, ["blue-novel", "red-novel"])

        blue = search_isolated(index_root, "isolation_probe", "blue-novel", "main", limit=10)
        red = search_isolated(index_root, "isolation_probe", "red-novel", "main", limit=10)
        blue_ids = {item.document_id for item in blue}
        red_ids = {item.document_id for item in red}
        if blue_ids != {"blue-novel-sentinel-v1.0", "shared-sentinel-v1.0"}:
            raise AssertionError(f"blue isolation failed: {sorted(blue_ids)}")
        if red_ids != {"red-novel-sentinel-v1.0", "shared-sentinel-v1.0"}:
            raise AssertionError(f"red isolation failed: {sorted(red_ids)}")
        blue_without_shared = search_isolated(
            index_root,
            "isolation_probe",
            "blue-novel",
            "main",
            limit=10,
            include_shared=False,
        )
        if {item.document_id for item in blue_without_shared} != {"blue-novel-sentinel-v1.0"}:
            raise AssertionError("--no-shared boundary failed")

        print(
            "multi_story_isolation=PASS "
            "blue=blue-novel-sentinel-v1.0+shared-sentinel-v1.0 "
            "red=red-novel-sentinel-v1.0+shared-sentinel-v1.0 "
            "cross_story_leaks=0"
        )


if __name__ == "__main__":
    main()
