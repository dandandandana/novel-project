from pathlib import Path

import yaml

from novel_rag.generation import PreferenceRequired, build_contract, generate
from novel_rag.generation import execute_scene
from novel_rag.generation_schema import (
    AuthorPreferenceProfile, DynamicCharacterState, GenerationContract, GenerationRequest,
    OutlineContract, SceneState,
)


def make_library(tmp_path: Path, *, preferences: str | None = "默认") -> tuple[Path, Path]:
    library = tmp_path / "novel-rag"
    story = library / "stories" / "demo"
    (library / "registry").mkdir(parents=True)
    (library / "registry" / "layout.yaml").write_text(yaml.safe_dump({"layout_version": "2.0"}), encoding="utf-8")
    (library / "registry" / "stories.yaml").write_text(yaml.safe_dump({"stories": [{"story_id": "demo"}]}), encoding="utf-8")
    (story / "registry").mkdir(parents=True)
    (story / "registry" / "timelines.yaml").write_text(
        yaml.safe_dump({"timelines": [{"story_id": "demo", "timeline_id": "main"}]}), encoding="utf-8")
    if preferences is not None:
        (story / "author-preferences.txt").write_text(preferences, encoding="utf-8")
    index = library / "index"
    (index / "stories").mkdir(parents=True)
    # Empty valid indexes are sufficient for the no-hit test path.
    from novel_rag.index import SqliteIndex
    SqliteIndex(index / "stories" / "demo.db").rebuild([])
    SqliteIndex(index / "shared.db").rebuild([])
    return library, index


class FakeModel:
    def __init__(self, repair_until: int = 0):
        self.calls: list[str] = []
        self.repair_until = repair_until

    def __call__(self, stage: str, payload: dict):
        self.calls.append(stage)
        if stage == "normalize":
            return {"outline": {"required_events": [{"event": "甲交出信", "actor": "甲", "required_result": "乙拿到信"}]}}
        if stage == "decide_behavior":
            assert "references" not in payload
            return {"action": "甲把信递给乙"}
        if stage == "derive_result":
            return {"result": "乙拿到信", "state_deltas": {"乙": {"knowledge": {"has_letter": True}}}}
        if stage == "render_prose":
            return {"text": "甲把信递给乙，乙拿到信。"}
        if stage == "validate":
            repairs = self.calls.count("repair")
            if repairs < self.repair_until:
                return {"issues": [{"check": "outline", "message": "缺少指定细节", "severity": "repairable"}]}
            return {"status": "pass", "issues": []}
        if stage == "repair":
            text = payload["text"] + " 他确认对方已经拿稳。"
            return {"text": text, "preserved_event_ids": payload["required_response"]["preserved_event_ids"],
                    "event_evidence": {event_id: {"excerpt": "甲把信递给乙，乙拿到信。", "actor": "甲", "result": "乙拿到信"}
                                       for event_id in payload["required_response"]["preserved_event_ids"]}}
        if stage == "reference_profile":
            return {"capabilities": ["自然对白"], "forbidden_surface_copy": ["原句"]}
        if stage == "polish":
            return {"text": payload["text"], "preserved_event_ids": payload["required_response"]["preserved_event_ids"],
                    "event_evidence": {event_id: {"excerpt": "甲把信递给乙，乙拿到信。", "actor": "甲", "result": "乙拿到信"}
                                       for event_id in payload["required_response"]["preserved_event_ids"]}}
        raise AssertionError(stage)


def test_generate_full_pipeline_without_writeback(tmp_path: Path) -> None:
    library, index = make_library(tmp_path)
    model = FakeModel()
    result = generate({"story_id": "demo", "outline": "甲把信交给乙。"}, model,
                      library_root=library, index_root=index, output_root=tmp_path / "outputs")
    assert result.status == "pass"
    assert result.text.startswith("甲把信")
    assert model.calls == ["normalize", "decide_behavior", "derive_result", "render_prose", "validate"]
    assert not (library / "stories" / "demo" / "history" / "generated.yaml").exists()
    assert Path(result.extensions["runtime_dir"], "final.txt").exists()


def test_missing_preferences_requests_bootstrap(tmp_path: Path) -> None:
    library, index = make_library(tmp_path, preferences=None)
    try:
        generate({"story_id": "demo", "outline": "写一章"}, FakeModel(), library_root=library, index_root=index)
    except PreferenceRequired as exc:
        assert exc.path.name == "author-preferences.txt"
    else:
        raise AssertionError("missing preferences must stop once")


def test_reference_profile_and_polish_are_after_scene_semantics(tmp_path: Path) -> None:
    library, index = make_library(tmp_path)
    model = FakeModel()
    generate({"story_id": "demo", "outline": "交信", "references": ["范文"]}, model,
             library_root=library, index_root=index, output_root=tmp_path / "outputs")
    assert model.calls.index("reference_profile") < model.calls.index("decide_behavior")
    assert model.calls.index("render_prose") < model.calls.index("polish")


def test_preferences_sections_are_parsed(tmp_path: Path) -> None:
    library, _ = make_library(tmp_path, preferences="【POV】\n第三人称有限\n【对白】\n自然承接")
    from novel_rag.generation import read_author_preferences
    profile = read_author_preferences(library, "demo")
    assert profile.pov == "第三人称有限"
    assert profile.dialogue == "自然承接"


def test_repairs_at_most_three_then_requests_guidance(tmp_path: Path) -> None:
    library, index = make_library(tmp_path)
    model = FakeModel(repair_until=99)
    result = generate({"story_id": "demo", "outline": "交信"}, model, library_root=library,
                      index_root=index, output_root=tmp_path / "outputs")
    assert result.status == "user_guidance_required"
    assert result.attempts == 3
    assert model.calls.count("repair") == 3


def test_scene_state_is_chained_with_deep_merge() -> None:
    request = GenerationRequest.from_input({"story_id": "demo", "outline": {
        "required_events": [{"event": "第一步"}, {"event": "第二步"}]
    }})
    contract = GenerationContract(request=request, outline=OutlineContract.from_input(request.outline),
                                  preferences=AuthorPreferenceProfile.from_input("默认"))
    initial = SceneState(characters={"甲": DynamicCharacterState(
        character_id="甲", knowledge={"old": True}, constraints={"inventory": {"letter": True}}
    )})
    seen = []
    def model(stage, payload):
        if stage == "decide_behavior":
            seen.append(payload["scene_state"])
            return "行动"
        if stage == "derive_result":
            return {"result": "完成", "state_deltas": {"甲": {"knowledge": {"new": True}}}}
        if stage == "render_prose":
            return {"text": "事情发生了。"}
        raise AssertionError(stage)
    _, _, state = execute_scene(contract, model, [], initial, {})
    assert seen[1]["characters"]["甲"]["knowledge"] == {"old": True, "new": True}
    assert state.characters["甲"].constraints["inventory"]["letter"] is True


def test_active_feedback_reaches_rendering_but_not_cpm(tmp_path: Path) -> None:
    from novel_rag.feedback import create_feedback

    library, index = make_library(tmp_path)
    create_feedback(
        library_root=library, index_root=index, story_id="demo", timeline_id="main",
        target_type="runtime", target_id="run-1", issue="LETTER-FEEDBACK-921",
        correction_rule=["交信后留出接住信件的动作"], version="1.0",
    )

    class FeedbackModel(FakeModel):
        def __init__(self):
            super().__init__()
            self.payloads = {}

        def __call__(self, stage, payload):
            self.payloads.setdefault(stage, []).append(payload)
            if stage == "normalize":
                self.calls.append(stage)
                return {"outline": {"required_events": [{"event": "LETTER-FEEDBACK-921",
                                                           "actor": "甲",
                                                           "required_result": "乙拿到信"}]}}
            return super().__call__(stage, payload)

    model = FeedbackModel()
    generate({"story_id": "demo", "outline": "LETTER-FEEDBACK-921 甲交出信"}, model,
             library_root=library, index_root=index, output_root=tmp_path / "outputs")
    assert "writing_feedback" not in model.payloads["decide_behavior"][0]
    assert model.payloads["render_prose"][0]["writing_feedback"]


def test_structured_author_events_survive_bad_normalizer(tmp_path: Path) -> None:
    library, index = make_library(tmp_path)
    class BadNormalizer(FakeModel):
        def __call__(self, stage, payload):
            if stage == "normalize":
                return {"outline": {"required_events": [{"event": "第二件事"}]}}
            return super().__call__(stage, payload)
    request = {"story_id": "demo", "outline": {"required_events": [
        {"event": "第一件事", "event_id": "one"}, {"event": "第二件事", "event_id": "two"}
    ]}}
    model = BadNormalizer()
    result = generate(request, model, library_root=library, index_root=index, output_root=tmp_path / "outputs")
    assert [item.event_id for item in result.events] == ["one", "two"]


def test_natural_author_clauses_survive_bad_normalizer() -> None:
    class ReplacingNormalizer(FakeModel):
        def __call__(self, stage, payload):
            if stage == "normalize":
                assert len(payload["source_clauses"]) == 2
                return {"outline": {"required_events": [{"event": "丙离开城市"}]}}
            return super().__call__(stage, payload)

    request = GenerationRequest.from_input({"story_id": "demo", "outline": "甲打开保险库\n乙随后烧毁地下室"})
    contract = build_contract(request, AuthorPreferenceProfile.from_input("默认"), ReplacingNormalizer())
    assert [event.event for event in contract.outline.required_events] == ["甲打开保险库", "乙随后烧毁地下室"]
    assert contract.outline.required_order == [event.event_id for event in contract.outline.required_events]


def test_polish_without_semantic_envelope_is_rejected(tmp_path: Path) -> None:
    library, index = make_library(tmp_path)
    class BadPolisher(FakeModel):
        def __call__(self, stage, payload):
            if stage == "polish":
                return {"text": "硬事件被删掉了。"}
            return super().__call__(stage, payload)
    result = generate({"story_id": "demo", "outline": "交信", "references": ["范文"]}, BadPolisher(),
                      library_root=library, index_root=index, output_root=tmp_path / "outputs")
    assert result.text == "甲把信递给乙，乙拿到信。"
    assert result.state is not None


def test_forged_polish_evidence_is_rejected(tmp_path: Path) -> None:
    library, index = make_library(tmp_path)
    class ForgedPolisher(FakeModel):
        def __call__(self, stage, payload):
            if stage == "polish":
                event_id = payload["required_response"]["preserved_event_ids"][0]
                return {"text": "硬事件已被删除。", "preserved_event_ids": [event_id],
                        "event_evidence": {event_id: {"excerpt": "硬事件已被删除。", "actor": "甲", "result": "乙拿到信"}}}
            return super().__call__(stage, payload)
    result = generate({"story_id": "demo", "outline": "交信", "references": ["范文"]}, ForgedPolisher(),
                      library_root=library, index_root=index, output_root=tmp_path / "outputs")
    assert result.text == "甲把信递给乙，乙拿到信。"


def test_negated_polish_cannot_replace_committed_event_text(tmp_path: Path) -> None:
    library, index = make_library(tmp_path)

    class NegatingPolisher(FakeModel):
        def __call__(self, stage, payload):
            if stage == "polish":
                event_id = payload["required_response"]["preserved_event_ids"][0]
                negated = "甲没有把信交出去；乙拿到信只是传闻。"
                return {"text": negated, "preserved_event_ids": [event_id],
                        "event_evidence": {event_id: {"excerpt": negated, "actor": "甲", "result": "乙拿到信"}}}
            return super().__call__(stage, payload)

    result = generate({"story_id": "demo", "outline": "交信", "references": ["范文"]}, NegatingPolisher(),
                      library_root=library, index_root=index, output_root=tmp_path / "outputs")
    assert result.text == "甲把信递给乙，乙拿到信。"


def test_author_length_reaches_render_without_expansion_point(tmp_path: Path) -> None:
    library, index = make_library(tmp_path)

    class LengthAwareModel(FakeModel):
        def __call__(self, stage, payload):
            if stage == "render_prose":
                assert payload["length_policy"]["mode"] == "author"
                assert payload["length_policy"]["target"] == 1200
                assert payload["event_progress"] == {"index": 1, "total": 1}
            return super().__call__(stage, payload)

    generate({"story_id": "demo", "outline": "交信", "length": {"target": 1200}}, LengthAwareModel(),
             library_root=library, index_root=index, output_root=tmp_path / "outputs")


def test_polish_cannot_negate_anchor_or_copy_reference_surface(tmp_path: Path) -> None:
    library, index = make_library(tmp_path)
    secret = "这是一段绝不能复现的参考原句"

    class UnsafePolisher(FakeModel):
        def __init__(self, suffix: str):
            super().__init__()
            self.suffix = suffix

        def __call__(self, stage, payload):
            if stage == "polish":
                event_id = payload["required_response"]["preserved_event_ids"][0]
                anchor = "甲把信递给乙，乙拿到信。"
                return {"text": anchor + self.suffix, "preserved_event_ids": [event_id],
                        "event_evidence": {event_id: {"excerpt": anchor, "actor": "甲", "result": "乙拿到信"}}}
            if stage == "reference_profile":
                return {"capabilities": ["自然对白"], "forbidden_surface_copy": [secret]}
            return super().__call__(stage, payload)

    for suffix in ("但这一切根本没有发生，只是传闻。", secret):
        result = generate({"story_id": "demo", "outline": "交信", "references": [secret]}, UnsafePolisher(suffix),
                          library_root=library, index_root=index, output_root=tmp_path / "outputs",
                          task_id=suffix[:3])
        assert result.text == "甲把信递给乙，乙拿到信。"
        saved = Path(result.extensions["runtime_dir"], "references.json").read_text(encoding="utf-8")
        assert secret not in saved
