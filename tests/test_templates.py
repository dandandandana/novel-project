from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import re
from typing import Any

import pytest
import yaml

from novel_rag.documents import load_document, validate_document


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_ROOT = ROOT / "novel-rag" / "shared" / "templates"


def _load_template(name: str) -> dict[str, Any]:
    path = TEMPLATE_ROOT / name
    assert path.is_file(), f"missing canonical template: {path}"
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict), f"template root must be a mapping: {path}"
    return value


def _filled_template(name: str) -> dict[str, Any]:
    value = deepcopy(_load_template(name))
    metadata = value["metadata"]
    metadata.update(
        {
            "document_id": f"template-test-{Path(name).stem}",
            "story_id": "template-test-story",
            "timeline_id": "main",
            "title": f"Template test: {Path(name).stem}",
            "version": "1.0",
            "status": "active",
        }
    )

    if name == "chapter-outline.yaml":
        metadata.update({"outline_level": "chapter", "volume": 1, "chapter": 1})
        value["outline"].update(
            {
                "opening_state": "上一场景已结束",
                "required_events": ["主角作出选择"],
                "required_order": ["选择", "结果"],
                "required_result": "冲突进入下一阶段",
                "ending_state": "新的目标明确",
            }
        )
    elif name == "character-current.yaml":
        metadata.update(
            {
                "character_id": "template-test-character",
                "variant_id": "template-test-character-main",
                "snapshot_type": "current",
                "effective_at": "chapter-1-scene-1",
                "last_updated": "2026-01-01",
            }
        )
        value["character_state"]["current_position"].update(
            {"location": "测试地点", "companions": [], "faction": "中立"}
        )
    elif name == "world-current.yaml":
        metadata["effective_at"] = "chapter-1-scene-1"
        value["world_state"].update({"timeline_position": "chapter-1-scene-1"})
    elif name == "style-audit.yaml":
        metadata["audit_scope"] = "global"
        value["rules"].update(
            {
                "narrative_perspective": "限知视角",
                "required": ["动作结果清晰"],
                "forbidden": ["无依据的设定扩写"],
                "scene_rules": ["让对白推动场景"],
            }
        )
    elif name == "feedback.yaml":
        metadata.update({"target_type": "chapter", "target_id": "chapter-1"})
        value["feedback"].update(
            {
                "issue": "节奏过快",
                "user_comment": "保留关键反应",
                "affected_scope": "scene-1",
                "correction_rule": ["补足因果反应"],
                "examples": ["示例片段"],
            }
        )
    else:  # Keep the parameter list honest if a template is added later.
        raise AssertionError(f"unhandled canonical template: {name}")
    return value


@pytest.mark.parametrize(
    "name",
    [
        "chapter-outline.yaml",
        "character-current.yaml",
        "world-current.yaml",
        "style-audit.yaml",
        "feedback.yaml",
    ],
)
def test_canonical_templates_validate(name: str, tmp_path: Path) -> None:
    path = tmp_path / name
    path.write_text(
        yaml.safe_dump(_filled_template(name), allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    document = load_document(path)
    assert document.metadata["document_type"] in {
        "outline",
        "character_state",
        "world_state",
        "style_audit",
        "feedback",
    }
    assert validate_document(document) == []


def _yaml_mappings_in_markdown(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8")
    mappings: list[dict[str, Any]] = []
    for match in re.finditer(r"```yaml\s*\n(.*?)\n```", text, flags=re.DOTALL):
        value = yaml.safe_load(match.group(1))
        if isinstance(value, dict):
            mappings.append(value)
    return mappings


def _mapping_keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        return {str(key) for key in value} | {
            child_key for child in value.values() for child_key in _mapping_keys(child)
        }
    if isinstance(value, list):
        return {child_key for child in value for child_key in _mapping_keys(child)}
    return set()


def test_skill_references_do_not_define_legacy_character_state_fields() -> None:
    forbidden = {
        "physical_state",
        "mental_state",
        "knowledge_state",
        "goal_state",
        "relationship_state",
        "ability_state",
    }
    reference_root = ROOT / "skills" / "rag-outline-to-novel" / "references"
    for path in sorted(reference_root.glob("*.md")):
        for mapping in _yaml_mappings_in_markdown(path):
            assert forbidden.isdisjoint(_mapping_keys(mapping)), path
