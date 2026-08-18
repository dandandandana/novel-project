from pathlib import Path

import yaml

from novel_rag.documents import iter_documents, load_document, validate_document
from novel_rag.service import load_valid_documents, validate_registries


def write_yaml(path: Path, value: dict) -> None:
    path.write_text(yaml.safe_dump(value, allow_unicode=True), encoding="utf-8")


def test_required_metadata_is_checked(tmp_path):
    path = tmp_path / "bad.yaml"
    write_yaml(path, {"metadata": {"document_type": "canon", "status": "canon"}, "content": "x"})
    errors = validate_document(load_document(path))
    assert "metadata.story_id 为必填字段" in errors
    assert "metadata.timeline_id 为必填字段" in errors


def test_character_state_requires_variant(tmp_path):
    path = tmp_path / "state.yaml"
    write_yaml(path, {"metadata": {
        "story_id": "s", "timeline_id": "main", "document_type": "character_state",
        "title": "状态", "status": "active", "version": "1.0", "character_id": "hero",
    }, "character_state": {}})
    assert "character_state 必须包含 metadata.variant_id" in validate_document(load_document(path))


def test_module_documents_require_module_metadata(tmp_path):
    path = tmp_path / "rule.yaml"
    write_yaml(path, {"metadata": {
        "story_id": "s", "timeline_id": "main", "document_type": "rule",
        "title": "规则", "status": "active", "version": "1.0",
    }, "rule": {}})
    errors = validate_document(load_document(path))
    assert "rule 必须包含 metadata.module_type" in errors
    assert "rule 必须包含 metadata.priority" in errors
    assert "rule 必须包含 metadata.enforcement" in errors


def test_module_type_must_match_document_type(tmp_path):
    path = tmp_path / "judgment.yaml"
    write_yaml(path, {"metadata": {
        "story_id": "s", "timeline_id": "main", "document_type": "judgment_spec",
        "module_type": "ruler", "priority": "global", "enforcement": "mandatory",
        "title": "判断", "status": "active", "version": "1.0",
    }, "judgment": {}})
    assert "judgment_spec 的 module_type 必须为 'judgment'" in validate_document(load_document(path))


def test_iter_documents_includes_ruler_and_judgment_directories(tmp_path):
    for dirname in ("rules", "judgment"):
        path = tmp_path / dirname / "active" / "doc.yaml"
        path.parent.mkdir(parents=True)
        path.write_text("metadata: {}\n", encoding="utf-8")
    assert {path.parent.parent.name for path in iter_documents(tmp_path)} == {"rules", "judgment"}


def test_duplicate_story_registration_is_rejected(tmp_path):
    registry = tmp_path / "registry"
    registry.mkdir()
    write_yaml(registry / "stories.yaml", {"stories": [{"story_id": "same"}, {"story_id": "same"}]})
    write_yaml(registry / "timelines.yaml", {"timelines": []})
    write_yaml(registry / "character-variants.yaml", {"character_variants": []})
    issues = validate_registries(tmp_path)
    assert any("重复注册: same" in issue.message for issue in issues)


def test_module_map_must_reference_matching_active_document(tmp_path):
    registry = tmp_path / "registry"
    registry.mkdir()
    write_yaml(registry / "stories.yaml", {"stories": [{"story_id": "s"}]})
    write_yaml(registry / "timelines.yaml", {"timelines": [{"story_id": "s", "timeline_id": "main"}]})
    write_yaml(registry / "character-variants.yaml", {"character_variants": []})
    write_yaml(registry / "module-map.yaml", {"modules": [{
        "story_id": "s", "timeline_id": "main", "module_type": "rule", "active_version": "missing-v1.0",
    }]})
    documents, issues = load_valid_documents(tmp_path)
    assert documents == []
    assert any("active_version 未指向有效文档: missing-v1.0" in issue.message for issue in issues)
