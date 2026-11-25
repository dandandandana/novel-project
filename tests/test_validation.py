from pathlib import Path

import yaml

from novel_rag.documents import iter_documents, load_document, validate_document
from novel_rag.service import load_valid_documents, validate_registries


def write_yaml(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(value, allow_unicode=True), encoding="utf-8")


def initialize_library(tmp_path: Path, story_ids: tuple[str, ...] = ("s",)) -> None:
    write_yaml(tmp_path / "registry" / "layout.yaml", {"layout_version": "2.0"})
    write_yaml(
        tmp_path / "registry" / "stories.yaml",
        {"stories": [{"story_id": story_id} for story_id in story_ids]},
    )
    write_yaml(tmp_path / "shared" / "registry" / "module-defaults.yaml", {"modules": []})
    write_yaml(tmp_path / "shared" / "registry" / "version-map.yaml", {"versions": []})
    for story_id in story_ids:
        registry = tmp_path / "stories" / story_id / "registry"
        write_yaml(
            registry / "timelines.yaml",
            {"timelines": [{"story_id": story_id, "timeline_id": "main"}]},
        )
        write_yaml(registry / "character-variants.yaml", {"character_variants": []})
        write_yaml(registry / "aliases.yaml", {"aliases": []})
        write_yaml(registry / "version-map.yaml", {"versions": []})
        write_yaml(registry / "module-map.yaml", {"modules": []})


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
    initialize_library(tmp_path)
    for dirname in ("rules", "judgment"):
        path = tmp_path / "shared" / dirname / "active" / "doc.yaml"
        path.parent.mkdir(parents=True)
        path.write_text("metadata: {}\n", encoding="utf-8")
    assert {path.parents[1].name for path in iter_documents(tmp_path)} == {"rules", "judgment"}


def test_duplicate_story_registration_is_rejected(tmp_path):
    initialize_library(tmp_path, ("same",))
    write_yaml(
        tmp_path / "registry" / "stories.yaml",
        {"stories": [{"story_id": "same"}, {"story_id": "same"}]},
    )
    issues = validate_registries(tmp_path)
    assert any("重复注册: same" in issue.message for issue in issues)


def test_module_map_must_reference_matching_active_document(tmp_path):
    initialize_library(tmp_path)
    registry = tmp_path / "stories" / "s" / "registry"
    write_yaml(registry / "module-map.yaml", {"modules": [{
        "story_id": "s", "timeline_id": "main", "module_type": "rule", "active_versions": ["missing-v1.0"],
    }]})
    documents, issues = load_valid_documents(tmp_path)
    assert documents == []
    assert any("active_versions 未指向有效文档: missing-v1.0" in issue.message for issue in issues)


def test_story_metadata_cannot_cross_physical_boundary(tmp_path):
    initialize_library(tmp_path, ("s1", "s2"))
    write_yaml(
        tmp_path / "stories" / "s1" / "canon" / "wrong.yaml",
        {
            "metadata": {
                "document_id": "wrong-v1.0",
                "story_id": "s2",
                "timeline_id": "main",
                "document_type": "canon",
                "title": "串库资料",
                "status": "canon",
                "version": "1.0",
            },
            "content": "不应跨小说加载",
        },
    )
    documents, issues = load_valid_documents(tmp_path)
    assert documents == []
    assert any("物理小说目录与 metadata.story_id 不一致" in issue.message for issue in issues)


def test_target_story_documents_win_over_copy_only_legacy_tree(tmp_path):
    """A migrated target copy is authoritative while legacy sources remain."""

    initialize_library(tmp_path)
    value = {
        "metadata": {
            "document_id": "target-wins-v1.0",
            "story_id": "s",
            "timeline_id": "main",
            "document_type": "history",
            "title": "目标布局",
            "status": "canon",
            "version": "1.0",
        },
        "content": "target",
    }
    legacy = tmp_path / "stories" / "s" / "history" / "scene.yaml"
    target = tmp_path / "stories" / "s" / "timelines" / "main" / "history" / "scene.yaml"
    write_yaml(legacy, {**value, "content": "legacy"})
    write_yaml(target, value)

    documents, issues = load_valid_documents(tmp_path)

    assert issues == []
    assert [document.path.resolve() for document in documents] == [target.resolve()]


def test_shared_system_document_can_be_inherited_by_story(tmp_path):
    initialize_library(tmp_path)
    write_yaml(
        tmp_path / "shared" / "rules" / "active" / "rule.yaml",
        {
            "metadata": {
                "document_id": "shared-rule-v1.0",
                "story_id": "__shared__",
                "timeline_id": "global",
                "document_type": "rule",
                "module_type": "ruler",
                "priority": "global",
                "enforcement": "mandatory",
                "title": "共享规则",
                "status": "active",
                "version": "1.0",
            },
            "rule": {"content": "共享审计规则"},
        },
    )
    write_yaml(
        tmp_path / "stories" / "s" / "registry" / "module-map.yaml",
        {"modules": [{
            "story_id": "s",
            "timeline_id": "main",
            "module_type": "rule",
            "active_versions": ["shared-rule-v1.0"],
        }]},
    )
    documents, issues = load_valid_documents(tmp_path)
    assert issues == []
    assert [document.document_id for document in documents] == ["shared-rule-v1.0"]


def test_valid_relations_pass_validation(tmp_path):
    path = tmp_path / "rel.yaml"
    write_yaml(path, {"metadata": {
        "story_id": "s", "timeline_id": "main", "document_type": "canon",
        "title": "关系", "status": "draft", "version": "1.0",
        "relations": [{
            "subject_id": "gilgamesh", "relation_type": "master_servant",
            "object_id": "shenqi-hui",
        }],
    }, "content": "x"})
    assert validate_document(load_document(path)) == []


def test_relations_entry_missing_object_id_is_rejected(tmp_path):
    path = tmp_path / "rel-bad.yaml"
    write_yaml(path, {"metadata": {
        "story_id": "s", "timeline_id": "main", "document_type": "canon",
        "title": "关系", "status": "draft", "version": "1.0",
        "relations": [{"subject_id": "gilgamesh", "relation_type": "master_servant"}],
    }, "content": "x"})
    errors = validate_document(load_document(path))
    assert "metadata.relations[0].object_id 必须为非空字符串" in errors


def test_relations_must_be_list(tmp_path):
    path = tmp_path / "rel-not-list.yaml"
    write_yaml(path, {"metadata": {
        "story_id": "s", "timeline_id": "main", "document_type": "canon",
        "title": "关系", "status": "draft", "version": "1.0",
        "relations": {"subject_id": "gilgamesh"},
    }, "content": "x"})
    errors = validate_document(load_document(path))
    assert any(error.startswith("无效 relations: 必须为列表") for error in errors)


def test_document_without_relations_key_is_unaffected(tmp_path):
    path = tmp_path / "plain.yaml"
    write_yaml(path, {"metadata": {
        "story_id": "s", "timeline_id": "main", "document_type": "canon",
        "title": "普通文档", "status": "canon", "version": "1.0",
    }, "content": "没有 relations 键"})
    assert validate_document(load_document(path)) == []


def test_shared_module_defaults_must_reference_shared_document(tmp_path):
    initialize_library(tmp_path)
    write_yaml(
        tmp_path / "shared" / "registry" / "module-defaults.yaml",
        {"modules": [{"module_type": "rule", "active_versions": ["missing-shared-rule"]}]},
    )
    _, issues = load_valid_documents(tmp_path)
    assert any("active_versions 未指向有效文档: missing-shared-rule" in issue.message for issue in issues)
