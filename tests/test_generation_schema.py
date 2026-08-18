from novel_rag.generation_schema import (
    AuthorPreferenceProfile,
    GenerationContract,
    GenerationRequest,
    LengthPolicy,
    OutlineContract,
)


def test_natural_language_outline_is_a_valid_goal() -> None:
    request = GenerationRequest.from_input({"story": "demo", "outline": "甲找到乙，并把信交给他。"})
    outline = OutlineContract.from_input(request.outline)
    contract = GenerationContract(request=request, outline=outline)
    assert contract.semantic_errors() == []
    assert outline.required_events[0].event.startswith("甲找到乙")
    assert outline.required_events[0].event_id.startswith("event-001-")


def test_natural_outline_lines_get_stable_source_clause_ids() -> None:
    outline = OutlineContract.from_input("- 甲打开保险库\n2. 乙随后烧毁地下室")
    assert [event.event for event in outline.required_events] == ["甲打开保险库", "乙随后烧毁地下室"]
    assert [event.extensions["source_clause_id"] for event in outline.required_events] == [
        event.event_id for event in outline.required_events
    ]


def test_mapping_aliases_and_extensions_are_preserved() -> None:
    outline = OutlineContract.from_input({
        "必须发生": [{"剧情节点": "A揭穿B", "subject": "A", "result": "秘密公开"}],
        "custom_note": "keep me",
    })
    assert outline.required_events[0].actor == "A"
    assert outline.required_events[0].required_result == "秘密公开"
    assert outline.extensions["custom_note"] == "keep me"


def test_length_policy_is_auto_without_numbers_and_author_with_numbers() -> None:
    assert LengthPolicy.from_input(None).mode == "auto"
    policy = LengthPolicy.from_input({"target": "8000", "expansion_points": "争吵部分"})
    assert policy.mode == "author"
    assert policy.target == 8000
    assert policy.expansion_points == ["争吵部分"]
    assert policy.overlong == "warn"


def test_preferences_accept_free_text_and_loose_mapping() -> None:
    free = AuthorPreferenceProfile.from_input("第三人称有限，少解释。", source_path="prefs.txt")
    assert free.raw_text == "第三人称有限，少解释。"
    assert free.source_path == "prefs.txt"
    mapped = AuthorPreferenceProfile.from_input({"视角": "第一人称", "unknown": 3})
    assert mapped.pov == "第一人称"
    assert mapped.extensions["unknown"] == 3


def test_only_core_semantic_absence_fails() -> None:
    contract = GenerationContract(
        request=GenerationRequest.from_input({"story_id": "demo", "outline": ""}),
        outline=OutlineContract.from_input(""),
    )
    assert contract.semantic_errors() == ["缺少核心写作目标或大纲"]


def test_invalid_event_order_falls_back_to_input_order() -> None:
    outline = OutlineContract.from_input({"required_events": [{"event": "发生事件", "order": "稍后"}]})
    assert outline.required_events[0].order == 0


def test_request_accepts_explicit_length_policy() -> None:
    request = GenerationRequest.from_input({"story_id": "demo", "outline": "写一章", "字数": {"min": 3000}})
    assert request.length == {"min": 3000}
