from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
RAG = ROOT / "novel-rag" / "shared"
STYLE = RAG / "style-audit"
MANIFEST = STYLE / "active" / "manifest.yaml"
VERSION_MAP = RAG / "registry" / "version-map.yaml"

ACTION_SOURCE = Path(
    r"C:\Users\dandandandana\.codex\attachments\30f8df7c-9d84-450f-96c6-e9031a46507a\pasted-text.txt"
)
SOUND_SOURCE = Path(
    r"C:\Users\dandandandana\.codex\attachments\d167a673-4af0-4652-8119-aec01c92c2fb\pasted-text.txt"
)


def load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def write_yaml(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=120),
        encoding="utf-8",
        newline="\n",
    )


def style_document(
    *,
    document_id: str,
    title: str,
    audit_scope: str,
    module_id: str,
    priority: str,
    source: Path,
    scene_type: str | None,
) -> dict:
    return {
        "metadata": {
            "document_id": document_id,
            "story_id": "__shared__",
            "timeline_id": "global",
            "document_type": "style_audit",
            "title": title,
            "audit_scope": audit_scope,
            "scene_type": scene_type,
            "module_id": module_id,
            "priority": priority,
            "version": "1.0",
            "status": "active",
            "created_at": "2026-07-14",
            "updated_at": "2026-07-14",
            "supersedes": None,
            "source_file": source.as_posix(),
        },
        "style_rules": {
            "activation": "active",
            "priority": priority,
            "scope": "battle" if scene_type == "battle" else "global",
            "content": source.read_text(encoding="utf-8").strip(),
        },
    }


def upsert_version(entries: list[dict], new_entry: dict) -> None:
    family = new_entry["document_family"]
    entries[:] = [item for item in entries if item.get("document_family") != family]
    entries.append(new_entry)


def main() -> None:
    for source in (ACTION_SOURCE, SOUND_SOURCE):
        if not source.exists():
            raise FileNotFoundError(source)

    manifest = load_yaml(MANIFEST)
    if manifest["metadata"]["document_id"] not in {
        "style-global-manifest-v1.1",
        "style-global-manifest-v1.2",
    }:
        raise ValueError(f"unexpected manifest version: {manifest['metadata']['document_id']}")

    if manifest["metadata"]["document_id"] == "style-global-manifest-v1.1":
        archived = deepcopy(manifest)
        archived["metadata"]["status"] = "deprecated"
        archived["metadata"]["updated_at"] = "2026-07-14"
        write_yaml(STYLE / "deprecated" / "manifest-v1.1.yaml", archived)

    write_yaml(
        STYLE / "active" / "action-continuity.yaml",
        style_document(
            document_id="style-action-continuity-v1.0",
            title="动作连贯性与文字血肉化修正规范",
            audit_scope="global_module",
            module_id="action-continuity",
            priority="high",
            source=ACTION_SOURCE,
            scene_type=None,
        ),
    )
    write_yaml(
        STYLE / "scene-specific" / "battle-syntax-sound.yaml",
        style_document(
            document_id="style-battle-syntax-sound-v1.0",
            title="句法黏合、连接词与战斗声场补强模块",
            audit_scope="scene_specific",
            module_id="battle-syntax-sound",
            priority="high",
            source=SOUND_SOURCE,
            scene_type="battle",
        ),
    )

    modules = manifest["audit"]["active_modules"]
    modules[:] = [
        item
        for item in modules
        if item.get("module_id") not in {"action-continuity", "battle-syntax-sound"}
    ]
    modules.extend(
        [
            {
                "module_id": "action-continuity",
                "title": "动作连贯性与文字血肉化修正规范",
                "scope": "global",
                "priority": "high",
            },
            {
                "module_id": "battle-syntax-sound",
                "title": "句法黏合、连接词与战斗声场补强模块",
                "scope": "battle",
                "priority": "high",
            },
        ]
    )
    manifest["metadata"].update(
        {
            "document_id": "style-global-manifest-v1.2",
            "version": "1.2",
            "status": "active",
            "updated_at": "2026-07-14",
            "supersedes": "style-global-manifest-v1.1",
            "source_file": f"{ACTION_SOURCE.as_posix()} + {SOUND_SOURCE.as_posix()}",
        }
    )
    write_yaml(MANIFEST, manifest)

    version_map = load_yaml(VERSION_MAP)
    versions = version_map.setdefault("versions", [])
    upsert_version(
        versions,
        {
            "document_family": "style-global-manifest",
            "current": "style-global-manifest-v1.2",
            "supersedes": ["style-global-manifest-v1.1", "style-global-manifest-v1.0"],
            "reason": "启用动作连贯性、文字血肉化、句法黏合与战斗声场补强模块",
        },
    )
    upsert_version(
        versions,
        {
            "document_family": "style-action-continuity",
            "current": "style-action-continuity-v1.0",
            "supersedes": [],
            "reason": "导入用户确认的全局动作连贯性与文字血肉化规范",
        },
    )
    upsert_version(
        versions,
        {
            "document_family": "style-battle-syntax-sound",
            "current": "style-battle-syntax-sound-v1.0",
            "supersedes": [],
            "reason": "导入用户确认的战斗句法黏合、连接词与声场补强规范",
        },
    )
    write_yaml(VERSION_MAP, version_map)

    print("style_modules_imported=2")
    print("manifest=style-global-manifest-v1.2")


if __name__ == "__main__":
    main()
