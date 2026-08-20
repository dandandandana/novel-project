from pathlib import Path

import yaml

from novel_rag.scaffold import create_story


def write_yaml(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(value, allow_unicode=True), encoding="utf-8")


def test_create_story_builds_isolated_tree_and_inherits_shared_modules(tmp_path):
    write_yaml(tmp_path / "registry" / "stories.yaml", {"stories": []})
    write_yaml(
        tmp_path / "shared" / "registry" / "module-defaults.yaml",
        {"modules": [{"module_type": "rule", "active_versions": ["shared-rule-v1.0"]}]},
    )

    root = create_story(tmp_path, story_id="second-novel", title="第二部小说")

    assert root == tmp_path / "stories" / "second-novel"
    assert (root / "common" / "canon").is_dir()
    assert (root / "common" / "registry").is_dir()
    assert (root / "timelines" / "main" / "history").is_dir()
    assert (root / "timelines" / "main" / "world-state").is_dir()
    assert (root / "timelines" / "main" / "summaries").is_dir()
    assert (root / "timelines" / "main" / "system-overrides" / "style-audit").is_dir()
    module_map = yaml.safe_load(
        (root / "timelines" / "main" / "registry" / "module-map.yaml").read_text(
            encoding="utf-8"
        )
    )
    assert module_map["modules"] == [{
        "module_type": "rule",
        "active_versions": ["shared-rule-v1.0"],
        "story_id": "second-novel",
        "timeline_id": "main",
    }]
    timeline_registry = yaml.safe_load(
        (root / "common" / "registry" / "timelines.yaml").read_text(encoding="utf-8")
    )
    assert timeline_registry["story_id"] == "second-novel"
    assert timeline_registry["timelines"][0]["parent_timeline_id"] is None
    assert timeline_registry["timelines"][0]["divergence_at"] is None
    assert timeline_registry["timelines"][0]["divergence_snapshot"] is None
    catalog = yaml.safe_load((tmp_path / "registry" / "stories.yaml").read_text(encoding="utf-8"))
    assert catalog["stories"][0]["storage_path"] == "stories/second-novel"


def test_create_story_rejects_path_like_story_id(tmp_path):
    write_yaml(tmp_path / "registry" / "stories.yaml", {"stories": []})
    try:
        create_story(tmp_path, story_id="../escape", title="非法")
    except ValueError as exc:
        assert "story_id" in str(exc)
    else:
        raise AssertionError("path-like story_id should be rejected")
