from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]
LIBRARY = ROOT / "novel-rag"
STORY_ID = "overturned-world-fujimaru"
TIMELINE_ID = "main"
SHARED_STORY_ID = "__shared__"
SHARED_TIMELINE_ID = "global"
STORY_DIRS = ("canon", "history", "outline", "character-state", "world-state", "feedback")
SYSTEM_DIRS = ("rules", "judgment", "generator", "audit", "style-audit")


def load_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(value, dict):
        raise ValueError(f"YAML root must be a mapping: {path}")
    return value


def write_yaml(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(value, allow_unicode=True, sort_keys=False, width=120),
        encoding="utf-8",
    )


def move_directory(source: Path, target: Path) -> None:
    if not source.exists():
        target.mkdir(parents=True, exist_ok=True)
        return
    if target.exists():
        raise FileExistsError(f"target already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source), str(target))


def move_file(source: Path, target: Path) -> None:
    if not source.exists():
        raise FileNotFoundError(source)
    if target.exists():
        raise FileExistsError(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source), str(target))


def verify_backup(backup_root: Path) -> dict[str, Any]:
    manifest_path = backup_root / "BACKUP-MANIFEST.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    rows = manifest.get("files", [])
    if not isinstance(rows, list) or len(rows) != manifest.get("file_count"):
        raise RuntimeError("backup manifest file_count does not match its file list")
    total_bytes = 0
    for row in rows:
        path = backup_root / str(row["path"])
        if not path.is_file():
            raise RuntimeError(f"backup file missing: {path}")
        payload = path.read_bytes()
        total_bytes += len(payload)
        if len(payload) != int(row["bytes"]):
            raise RuntimeError(f"backup byte count mismatch: {path}")
        if hashlib.sha256(payload).hexdigest() != str(row["sha256"]):
            raise RuntimeError(f"backup SHA-256 mismatch: {path}")
    if total_bytes != int(manifest.get("total_bytes", -1)):
        raise RuntimeError("backup total_bytes mismatch")
    return manifest


def shared_document_ids() -> set[str]:
    values: set[str] = set()
    for dirname in SYSTEM_DIRS:
        root = LIBRARY / dirname
        if not root.exists():
            continue
        for path in [*root.rglob("*.yaml"), *root.rglob("*.yml")]:
            metadata = load_yaml(path).get("metadata", {})
            document_id = metadata.get("document_id") if isinstance(metadata, dict) else None
            if document_id:
                values.add(str(document_id))
    return values


def rewrite_shared_identity(root: Path) -> int:
    count = 0
    for dirname in SYSTEM_DIRS:
        directory = root / dirname
        for path in [*directory.rglob("*.yaml"), *directory.rglob("*.yml")]:
            text = path.read_text(encoding="utf-8")
            replaced, story_count = re.subn(
                r"(?m)^(\s{2}story_id:)\s*[^\r\n]+$",
                rf"\1 {SHARED_STORY_ID}",
                text,
                count=1,
            )
            replaced, timeline_count = re.subn(
                r"(?m)^(\s{2}timeline_id:)\s*[^\r\n]+$",
                rf"\1 {SHARED_TIMELINE_ID}",
                replaced,
                count=1,
            )
            if story_count != 1 or timeline_count != 1:
                raise RuntimeError(f"cannot rewrite shared identity: {path}")
            path.write_text(replaced, encoding="utf-8")
            count += 1
    return count


def migrate(backup_root: Path) -> None:
    backup_manifest = backup_root / "BACKUP-MANIFEST.json"
    if not backup_manifest.is_file():
        raise FileNotFoundError(f"verified backup manifest missing: {backup_manifest}")
    verified_backup = verify_backup(backup_root)
    if (LIBRARY / "registry" / "layout.yaml").exists():
        raise RuntimeError("layout v2 migration already appears to be complete")
    for required in ("canon", "history", "registry", "rules", "judgment", "style-audit"):
        if not (LIBRARY / required).exists():
            raise FileNotFoundError(f"legacy source missing: {LIBRARY / required}")

    shared_ids = shared_document_ids()
    legacy_version_map = load_yaml(LIBRARY / "registry" / "version-map.yaml")
    version_rows = legacy_version_map.get("versions", [])
    if not isinstance(version_rows, list):
        raise ValueError("registry/version-map.yaml versions must be a list")
    shared_versions = [row for row in version_rows if isinstance(row, dict) and str(row.get("current")) in shared_ids]
    story_versions = [row for row in version_rows if row not in shared_versions]

    story = LIBRARY / "stories" / STORY_ID
    shared = LIBRARY / "shared"
    for dirname in STORY_DIRS:
        move_directory(LIBRARY / dirname, story / dirname)
    for dirname in SYSTEM_DIRS:
        move_directory(LIBRARY / dirname, shared / dirname)
    move_directory(LIBRARY / "templates", shared / "templates")
    move_file(LIBRARY / "retrieval-tests.yaml", story / "retrieval-tests.yaml")

    story_registry = story / "registry"
    story_registry.mkdir(parents=True)
    for filename in ("timelines.yaml", "character-variants.yaml", "aliases.yaml"):
        move_file(LIBRARY / "registry" / filename, story_registry / filename)
    write_yaml(story_registry / "version-map.yaml", {"versions": story_versions})
    (LIBRARY / "registry" / "version-map.yaml").unlink()

    module_defaults = {
        "modules": [
            {
                "module_type": "rule",
                "active_versions": [
                    "ruler-global-v1.0",
                    "ruler-narrative-information-disclosure-v1.0",
                ],
            },
            {
                "module_type": "judgment_spec",
                "active_versions": ["judgment-global-v1.1"],
            },
            {
                "module_type": "style_audit",
                "active_versions": ["style-global-manifest-v1.3"],
            },
        ]
    }
    story_modules = []
    for row in module_defaults["modules"]:
        story_modules.append(
            {
                "story_id": STORY_ID,
                "timeline_id": TIMELINE_ID,
                "module_type": row["module_type"],
                "active_versions": list(row["active_versions"]),
            }
        )
    write_yaml(story_registry / "module-map.yaml", {"modules": story_modules})
    (LIBRARY / "registry" / "module-map.yaml").unlink()

    shared_registry = shared / "registry"
    write_yaml(shared_registry / "version-map.yaml", {"versions": shared_versions})
    write_yaml(shared_registry / "module-defaults.yaml", module_defaults)

    shared_document_count = rewrite_shared_identity(shared)

    catalog_path = LIBRARY / "registry" / "stories.yaml"
    catalog = load_yaml(catalog_path)
    for row in catalog.get("stories", []):
        if isinstance(row, dict) and row.get("story_id") == STORY_ID:
            row["current_volume"] = 4
            row["current_chapter"] = 17
            row["storage_path"] = f"stories/{STORY_ID}"
    write_yaml(catalog_path, catalog)
    write_yaml(
        LIBRARY / "registry" / "layout.yaml",
        {
            "layout_version": "2.0",
            "architecture": "shared-system-plus-isolated-stories",
            "shared_identity": {
                "story_id": SHARED_STORY_ID,
                "timeline_id": SHARED_TIMELINE_ID,
            },
            "story_root": "stories/<story_id>",
            "shared_root": "shared",
            "index_layout": {
                "shared": "index/shared.db",
                "story": "index/stories/<story_id>.db",
            },
        },
    )

    for dirname in SYSTEM_DIRS:
        override = story / "system-overrides" / dirname
        override.mkdir(parents=True, exist_ok=True)
        (override / ".gitkeep").write_text("\n", encoding="utf-8")

    legacy_index = LIBRARY / "index" / "rag.db"
    if legacy_index.exists():
        archive = LIBRARY / "archive" / "legacy-index"
        archive.mkdir(parents=True, exist_ok=True)
        shutil.move(str(legacy_index), str(archive / "rag.db"))
        (archive / "README.md").write_text(
            "# Legacy combined index\n\nThis database predates physical multi-story isolation and is not used.\n",
            encoding="utf-8",
        )

    write_yaml(
        LIBRARY / "registry" / "migration-v2.yaml",
        {
            "migration": {
                "version": "2.0",
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "source_layout": "flat-single-story",
                "target_layout": "shared-system-plus-isolated-stories",
                "story_id": STORY_ID,
                "shared_documents_reidentified": shared_document_count,
                "backup_root": str(backup_root),
                "backup_manifest": str(backup_manifest),
                "backup_file_count": verified_backup["file_count"],
                "backup_total_bytes": verified_backup["total_bytes"],
            }
        },
    )

    forbidden_legacy_paths = [
        *(LIBRARY / dirname for dirname in (*STORY_DIRS, *SYSTEM_DIRS)),
        *(LIBRARY / "registry" / filename for filename in (
            "timelines.yaml",
            "character-variants.yaml",
            "aliases.yaml",
            "version-map.yaml",
            "module-map.yaml",
        )),
    ]
    remaining = [str(path) for path in forbidden_legacy_paths if path.exists()]
    if remaining:
        raise RuntimeError(f"legacy paths remain after migration: {remaining}")
    print(
        f"migration=PASS story={story} shared={shared} "
        f"shared_docs={shared_document_count} backup={backup_root}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate the legacy flat RAG into isolated multi-story layout v2")
    parser.add_argument("--backup", required=True, type=Path)
    args = parser.parse_args()
    migrate(args.backup.resolve())


if __name__ == "__main__":
    main()
