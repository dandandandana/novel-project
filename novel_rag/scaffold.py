from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import yaml

from .config import (
    DEFAULT_TIMELINE_ID,
    TARGET_COMMON_DIRS,
    TARGET_TIMELINE_DIRS,
)
from .identity import GraphKey
from .layout import shared_registry_root, story_root, validate_story_id


def _load(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return value if isinstance(value, dict) else {}


def _write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(value, allow_unicode=True, sort_keys=False, width=120),
        encoding="utf-8",
    )


def create_story(
    library_root: Path,
    *,
    story_id: str,
    title: str,
    timeline_id: str = DEFAULT_TIMELINE_ID,
    timeline_name: str = "主世界线",
    language: str = "zh-CN",
    inherit_shared: bool = True,
) -> Path:
    validate_story_id(story_id)
    if timeline_id == "common":
        raise ValueError("timeline_id=common 保留给 common 作用域")
    try:
        GraphKey(story_id, timeline_id)
    except ValueError as exc:
        raise ValueError(str(exc)) from exc
    root = story_root(library_root, story_id)
    if root.exists():
        raise FileExistsError(f"小说目录已存在: {root}")

    catalog_path = library_root / "registry" / "stories.yaml"
    catalog = _load(catalog_path)
    rows = catalog.setdefault("stories", [])
    if any(str(item.get("story_id")) == story_id for item in rows if isinstance(item, dict)):
        raise ValueError(f"story_id 已注册: {story_id}")

    common_root = root / "common"
    timeline_root = root / "timelines" / timeline_id
    for dirname in TARGET_COMMON_DIRS:
        directory = common_root / dirname
        directory.mkdir(parents=True, exist_ok=False)
        (directory / ".gitkeep").write_text("\n", encoding="utf-8")
    for dirname in TARGET_TIMELINE_DIRS:
        directory = timeline_root / dirname
        directory.mkdir(parents=True, exist_ok=True)
        (directory / ".gitkeep").write_text("\n", encoding="utf-8")
    for dirname in ("rules", "judgment", "generator", "audit", "style-audit"):
        directory = timeline_root / "system-overrides" / dirname
        directory.mkdir(parents=True, exist_ok=True)
        (directory / ".gitkeep").write_text("\n", encoding="utf-8")

    common_registry = common_root / "registry"
    timeline_registry = timeline_root / "registry"
    _write(
        common_registry / "timelines.yaml",
        {
            "story_id": story_id,
            "timelines": [
                {
                    "story_id": story_id,
                    "timeline_id": timeline_id,
                    "parent_timeline_id": None,
                    "divergence_at": None,
                    "divergence_snapshot": None,
                    "name": timeline_name,
                    "status": "active",
                }
            ]
        },
    )
    _write(common_registry / "character-variants.yaml", {"character_variants": []})
    _write(common_registry / "aliases.yaml", {"aliases": []})
    _write(common_registry / "version-map.yaml", {"versions": []})

    modules: list[dict[str, Any]] = []
    if inherit_shared:
        defaults = _load(shared_registry_root(library_root) / "module-defaults.yaml").get("modules", [])
        for default in defaults if isinstance(defaults, list) else []:
            if not isinstance(default, dict):
                continue
            item = copy.deepcopy(default)
            item["story_id"] = story_id
            item["timeline_id"] = timeline_id
            modules.append(item)
    _write(timeline_registry / "module-map.yaml", {"modules": modules})
    _write(timeline_root / "retrieval-tests.yaml", {"tests": []})

    preferences_template = library_root / "templates" / "author-preferences.txt"
    if preferences_template.exists():
        (root / "author-preferences.txt.example").write_text(
            preferences_template.read_text(encoding="utf-8"), encoding="utf-8"
        )

    rows.append(
        {
            "story_id": story_id,
            "title": title,
            "status": "active",
            "primary_timeline": timeline_id,
            "current_volume": 0,
            "current_chapter": 0,
            "language": language,
            "storage_path": f"stories/{story_id}",
        }
    )
    _write(catalog_path, catalog)
    return root
