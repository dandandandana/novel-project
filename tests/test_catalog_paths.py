from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from novel_rag.catalog import (
    LayoutMappingError,
    StoryCatalogPaths,
    TimelineRegistry,
    load_timeline_registry,
    module_map_paths,
    resolve_module_map_path,
    resolve_timeline_registry_path,
    resolve_version_map_path,
    timeline_registry_path,
    version_map_path,
)
from novel_rag.identity import StoryCoordinate
from novel_rag.layout import (
    module_map_paths as layout_module_map_paths,
    timeline_registry_path as layout_timeline_registry_path,
)
from novel_rag.scaffold import create_story


def _library_root(tmp_path: Path) -> Path:
    root = tmp_path / "novel-rag"
    (root / "registry").mkdir(parents=True)
    return root


def test_target_scaffold_registry_and_branch_lineage_load(tmp_path: Path) -> None:
    library = _library_root(tmp_path)
    story_root = create_story(library, story_id="demo", title="Demo")
    common_registry = story_root / "common" / "registry"
    timeline_path = common_registry / "timelines.yaml"

    registry_value = yaml.safe_load(timeline_path.read_text(encoding="utf-8"))
    registry_value["timelines"].append(
        {
            "story_id": "demo",
            "timeline_id": "branch",
            "parent_timeline_id": "main",
            "divergence_at": "volume-01/chapter-02/scene-03",
            "divergence_snapshot": "snapshots/branch.yaml",
        }
    )
    timeline_path.write_text(
        yaml.safe_dump(registry_value, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    snapshot = story_root / "snapshots" / "branch.yaml"
    snapshot.parent.mkdir(parents=True)
    snapshot.write_text("state: {}\n", encoding="utf-8")

    paths = StoryCatalogPaths(library, "demo")
    assert resolve_timeline_registry_path(library, "demo", required=True) == timeline_path
    assert timeline_registry_path(library, "demo", required=True) == timeline_path
    assert paths.resolve_module_map_path(required=True) == (
        story_root / "timelines" / "main" / "registry" / "module-map.yaml"
    )
    assert resolve_module_map_path(library, "demo", required=True) == (
        story_root / "timelines" / "main" / "registry" / "module-map.yaml"
    )
    assert resolve_version_map_path(library, "demo", required=True) == (
        common_registry / "version-map.yaml"
    )
    assert version_map_path(library, "demo", required=True) == (
        common_registry / "version-map.yaml"
    )

    registry = load_timeline_registry(
        timeline_path,
        expected_story_id="demo",
        snapshot_root=story_root,
    )
    assert registry.allowed_timeline_ids("main") == ("main",)
    assert registry.allowed_timeline_ids("branch") == ("main", "branch")
    assert registry.cutoffs("branch")["main"] == StoryCoordinate(1, 2, 3)
    assert registry.get("branch").snapshot_path(story_root) == snapshot


def test_catalog_paths_choose_target_and_fall_back_to_legacy(tmp_path: Path) -> None:
    library = _library_root(tmp_path)
    story_root = create_story(library, story_id="demo", title="Demo")
    paths = StoryCatalogPaths(library, "demo")
    legacy_registry = story_root / "registry"
    legacy_registry.mkdir()
    legacy_timeline = legacy_registry / "timelines.yaml"
    legacy_module = legacy_registry / "module-map.yaml"
    legacy_version = legacy_registry / "version-map.yaml"
    for path, value in (
        (legacy_timeline, {"timelines": []}),
        (legacy_module, {"modules": []}),
        (legacy_version, {"versions": []}),
    ):
        path.write_text(yaml.safe_dump(value), encoding="utf-8")

    # The target scaffold remains authoritative when both layouts exist.
    assert paths.resolve_timeline_registry_path(required=True) == (
        story_root / "common" / "registry" / "timelines.yaml"
    )
    assert layout_timeline_registry_path(library, "demo") == (
        story_root / "common" / "registry" / "timelines.yaml"
    )
    assert paths.resolve_module_map_path(required=True) == (
        story_root / "timelines" / "main" / "registry" / "module-map.yaml"
    )
    assert layout_module_map_paths(library, "demo")[0] == (
        story_root / "timelines" / "main" / "registry" / "module-map.yaml"
    )
    assert paths.resolve_version_map_path(required=True) == (
        story_root / "common" / "registry" / "version-map.yaml"
    )
    assert legacy_timeline in paths.existing_registry_files("timelines.yaml")
    assert legacy_module in module_map_paths(library, "demo")
    assert legacy_version in paths.existing_registry_files("version-map.yaml")

    # A legacy-only story remains readable and has deterministic write paths.
    legacy_only = _library_root(tmp_path / "legacy")
    legacy_story = legacy_only / "stories" / "old-story"
    (legacy_story / "registry").mkdir(parents=True)
    for name, value in (
        ("timelines.yaml", {"timelines": []}),
        ("module-map.yaml", {"modules": []}),
        ("version-map.yaml", {"versions": []}),
    ):
        (legacy_story / "registry" / name).write_text(
            yaml.safe_dump(value), encoding="utf-8"
        )
    legacy_paths = StoryCatalogPaths(legacy_only, "old-story")
    assert legacy_paths.resolve_timeline_registry_path(required=True) == (
        legacy_story / "registry" / "timelines.yaml"
    )
    assert legacy_paths.resolve_module_map_path(required=True) == (
        legacy_story / "registry" / "module-map.yaml"
    )
    assert legacy_paths.resolve_version_map_path(required=True) == (
        legacy_story / "registry" / "version-map.yaml"
    )


def test_catalog_paths_reject_unsafe_registry_filenames(tmp_path: Path) -> None:
    paths = StoryCatalogPaths(_library_root(tmp_path), "demo")
    with pytest.raises(LayoutMappingError, match="单一文件名"):
        paths.resolve_registry_file("../timelines.yaml")
