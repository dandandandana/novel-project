from __future__ import annotations

import copy
import shutil
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
from .documents import read_yaml_mapping
from .mutations import FileMutationLock
from .std.atomic_io import atomic_write_bytes


def _write(path: Path, value: dict[str, Any]) -> None:
    """依赖：YAML编码/公共原子写。输入：路径/映射。输出：None或IO错误。实现：编码既有格式后委托原子保存。"""
    atomic_write_bytes(path, yaml.safe_dump(value, allow_unicode=True, sort_keys=False, width=120).encode("utf-8"))


def create_story(
    library_root: Path,
    *,
    story_id: str,
    title: str,
    timeline_id: str = DEFAULT_TIMELINE_ID,
    timeline_name: str = "主世界线",
    language: str = "zh-CN",
    inherit_shared: bool = True,
    exist_ok: bool = False,
) -> Path:
    """依赖：原建树/库锁/YAML与原子保存。输入：书名/ID/时间线及显式同意图重试。输出：作品根或冲突/IO错误。实现：锁内核对归属，最后注册；失败只清本次建树，崩溃残留保留。"""
    validate_story_id(story_id)
    if not isinstance(title, str) or not title.strip():
        raise ValueError("source_invalid: 作品标题不能为空")
    title = title.strip()
    if timeline_id == "common":
        raise ValueError("timeline_id=common 保留给 common 作用域")
    try:
        GraphKey(story_id, timeline_id)
    except ValueError as exc:
        raise ValueError(str(exc)) from exc
    library_root = Path(library_root).resolve()
    root = story_root(library_root, story_id)
    catalog_path = library_root / "registry" / "stories.yaml"
    lock_path = library_root / ".novel-rag" / "mutation.lock"
    for path in (root, catalog_path, lock_path):
        try:
            path.resolve().relative_to(library_root)
        except ValueError as exc:
            raise ValueError("scope_denied: 新作品路径不属于本库") from exc
    with FileMutationLock(lock_path):
        catalog = read_yaml_mapping(catalog_path)
        if catalog_path.exists() and "stories" not in catalog:
            raise ValueError("source_invalid: 作品注册表缺少stories列表，拒绝覆盖")
        rows = catalog.setdefault("stories", [])
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise ValueError("source_invalid: 作品注册表格式损坏")
        registered = [row for row in rows if row.get("story_id") == story_id]
        if root.exists() or root.is_symlink() or registered:
            if exist_ok and len(registered) == 1 and root.is_dir() and not root.is_symlink():
                row = registered[0]
                timelines = read_yaml_mapping(root / "common" / "registry" / "timelines.yaml").get("timelines", [])
                if (row.get("title") == title and row.get("primary_timeline") == timeline_id
                        and row.get("inherit_shared") is inherit_shared
                        and row.get("language") == language and row.get("storage_path") == f"stories/{story_id}"
                        and isinstance(timelines, list) and any(isinstance(item, dict)
                            and item.get("timeline_id") == timeline_id and item.get("name") == timeline_name
                            for item in timelines)
                        and (root / "timelines" / timeline_id / "registry" / "module-map.yaml").is_file()):
                    return root
            raise FileExistsError(f"小说目录或注册已存在，拒绝覆盖；不完整目录请保留核对: {root}")
        root.mkdir(parents=True, exist_ok=False)
        owned_stat = root.stat()
        try:
            _build_story_tree(library_root, root, story_id, timeline_id, timeline_name, inherit_shared)
            rows.append({"story_id": story_id, "title": title, "status": "active", "primary_timeline": timeline_id,
                         "current_volume": 0, "current_chapter": 0, "language": language,
                         "storage_path": f"stories/{story_id}", "inherit_shared": inherit_shared})
            _write(catalog_path, catalog)
        except Exception:
            cleanup_allowed = False
            try:
                catalog_path.resolve().relative_to(library_root)
                current_catalog = read_yaml_mapping(catalog_path)
                committed = current_catalog.get("stories", [])
                registry_known = not catalog_path.exists() or "stories" in current_catalog and isinstance(committed, list)
                registered_now = (any(isinstance(row, dict) and row.get("story_id") == story_id for row in committed)
                                  if isinstance(committed, list) else True)
                resolved_root = root.resolve()
                resolved_root.relative_to(library_root)
                current_stat = root.stat()
                cleanup_allowed = (registry_known and not registered_now and not root.is_symlink()
                    and resolved_root.parent == (library_root / "stories").resolve()
                    and (current_stat.st_dev, current_stat.st_ino) == (owned_stat.st_dev, owned_stat.st_ino))
            except (OSError, ValueError, yaml.YAMLError):
                pass  # 归属或注册事实不明时保留目录；传播原建树错误。
            if cleanup_allowed:
                shutil.rmtree(root)
            raise
    return root


def _build_story_tree(library_root: Path, root: Path, story_id: str, timeline_id: str,
                      timeline_name: str, inherit_shared: bool) -> None:
    """依赖：既有目录常量/原子YAML保存。输入：已独占的新目录/书线/继承选择。输出：None或IO错误。实现：建立原兼容树与模板，注册表提交由create_story负责。"""
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
        defaults = read_yaml_mapping(shared_registry_root(library_root) / "module-defaults.yaml").get("modules", [])
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
