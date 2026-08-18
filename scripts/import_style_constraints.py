from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]
LIBRARY = ROOT / "novel-rag" / "shared"
SOURCE_ROOT = Path("D:/project")
STORY_ID = "__shared__"
TIMELINE_ID = "global"
TODAY = date(2026, 7, 12).isoformat()

MODULES = {
    "比喻.txt": ("metaphor", "比喻模块", "global", "normal"),
    "标点.txt": ("punctuation", "标点符号规范", "global", "normal"),
    "存在性废话.txt": ("information-filter", "存在性废话与心理状态约束", "global", "normal"),
    "动作.txt": ("action", "动作描写模块", "global", "normal"),
    "对话.txt": ("dialogue", "对话协议", "global", "normal"),
    "旁白.txt": ("narration-voice", "旁白描写模块", "global", "normal"),
    "叙事.txt": ("narrative-organization", "叙事组织模块", "global", "normal"),
    "长段描写.txt": ("long-description", "长段描写限制与描写解构", "global", "normal"),
    "总纲补丁.txt": ("master-patch", "正常叙事、活人感与角色私有性总纲补丁", "global", "highest"),
    "场景类型判定协议.txt": ("scene-classifier", "场景类型判定协议", "scene_dispatcher", "high"),
    "主人物场景.txt": ("character-scene", "主人物与场景描写法则", "character_focused", "high"),
}


def dump(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=120), encoding="utf-8")


def extract_version(text: str) -> str:
    match = re.search(r"V(\d+(?:\.\d+)*)", text[:300], re.IGNORECASE)
    return match.group(1) if match else "1.0"


def import_module(filename: str, module_id: str, title: str, scope: str, priority: str) -> Path:
    source = SOURCE_ROOT / filename
    content = source.read_text(encoding="utf-8-sig").strip()
    version = extract_version(content)
    scene_specific = scope != "global"
    destination = LIBRARY / "style-audit" / ("scene-specific" if scene_specific else "active") / f"{module_id}.yaml"
    data = {
        "metadata": {
            "document_id": f"style-{module_id}-v{version}",
            "story_id": STORY_ID,
            "timeline_id": TIMELINE_ID,
            "document_type": "style_audit",
            "title": title,
            "audit_scope": "scene_specific" if scene_specific else "global_module",
            "scene_type": scope if scene_specific else None,
            "module_id": module_id,
            "priority": priority,
            "version": version,
            "status": "active",
            "created_at": TODAY,
            "updated_at": TODAY,
            "supersedes": None,
            "source_file": str(source),
        },
        "style_rules": {
            "activation": "active",
            "priority": priority,
            "scope": scope,
            "content": content,
        },
    }
    dump(destination, data)
    return destination


def import_manifest(module_documents: list[tuple[str, str, str, str]]) -> None:
    data = {
        "metadata": {
            "document_id": "style-global-manifest-v1.0",
            "story_id": STORY_ID,
            "timeline_id": TIMELINE_ID,
            "document_type": "style_audit",
            "title": "当前生效文风审计总表",
            "audit_scope": "global",
            "version": "1.0",
            "status": "active",
            "created_at": TODAY,
            "updated_at": TODAY,
            "supersedes": None,
            "source_file": "D:/project/总纲补丁.txt",
        },
        "audit": {
            "resolution_order": [
                "正常叙事与可读性",
                "总纲补丁（highest）",
                "当前段落场景类型专项规则",
                "角色私有性与关系真实性",
                "其他全局模块规则",
            ],
            "active_modules": [
                {"module_id": module_id, "title": title, "scope": scope, "priority": priority}
                for module_id, title, scope, priority in module_documents
            ],
            "conflict_rule": "发生冲突时，以总纲补丁及更具体的当前场景规则为准；不得为机械合规破坏正常叙事。",
        },
    }
    dump(LIBRARY / "style-audit" / "active" / "manifest.yaml", data)


def main() -> None:
    active = LIBRARY / "style-audit" / "active"
    scene = LIBRARY / "style-audit" / "scene-specific"
    for directory in (active, scene):
        for old in directory.glob("*.yaml"):
            old.unlink()
    module_documents: list[tuple[str, str, str, str]] = []
    for filename, (module_id, title, scope, priority) in MODULES.items():
        import_module(filename, module_id, title, scope, priority)
        module_documents.append((module_id, title, scope, priority))
    import_manifest(module_documents)
    print(f"style_modules={len(MODULES)} manifest=1")


if __name__ == "__main__":
    main()
