import shutil
from pathlib import Path

import yaml

from novel_rag.generation import generate
from novel_rag.retrieval import ContextBundle
from novel_rag.scaffold import create_story
from novel_rag.state_review import approve_state_proposal
from novel_rag.writeback import confirm_runtime


class _StubRetriever:
    def retrieve(self, _request):
        return ContextBundle()


class _StubModel:
    def __call__(self, stage, _payload):
        if stage == "normalize":
            return {"outline": {"required_events": [
                {"event": "甲交信", "actor": "甲", "required_result": "乙收信"},
            ]}}
        if stage == "decide_behavior":
            return {"action": "甲把信递给乙"}
        if stage == "derive_result":
            return {"result": "乙收信", "state_deltas": {
                "乙": {"knowledge": {"has_letter": True}},
            }}
        if stage == "render_prose":
            return {"text": "甲把信递给乙，乙收信。"}
        if stage == "validate":
            return {"status": "pass", "issues": []}
        raise AssertionError(stage)


def _target_library(tmp_path: Path) -> Path:
    library = tmp_path / "novel-rag"
    (library / "registry").mkdir(parents=True)
    (library / "registry" / "layout.yaml").write_text(
        yaml.safe_dump({"layout_version": "2.0"}), encoding="utf-8"
    )
    (library / "registry" / "stories.yaml").write_text(
        yaml.safe_dump({"stories": []}), encoding="utf-8"
    )
    (library / "shared" / "registry").mkdir(parents=True)
    (library / "shared" / "registry" / "module-defaults.yaml").write_text(
        yaml.safe_dump({"modules": []}), encoding="utf-8"
    )
    (library / "shared" / "registry" / "version-map.yaml").write_text(
        yaml.safe_dump({"versions": []}), encoding="utf-8"
    )
    templates = library / "shared" / "templates"
    templates.mkdir(parents=True)
    source = Path(__file__).parents[1] / "novel-rag" / "shared" / "templates"
    for name in ("character-current.yaml", "world-current.yaml"):
        shutil.copy2(source / name, templates / name)
    create_story(library, story_id="demo", title="Demo")
    (library / "stories" / "demo" / "author-preferences.txt").write_text(
        "默认", encoding="utf-8"
    )
    return library


def test_target_scaffold_generate_confirm_and_approve_never_use_old_root(tmp_path: Path):
    library = _target_library(tmp_path)
    index = library / "index"
    output = tmp_path / "outputs"
    story = library / "stories" / "demo"

    result = generate(
        {"story_id": "demo", "timeline_id": "main", "outline": "交信"},
        _StubModel(),
        library_root=library,
        index_root=index,
        output_root=output,
        retriever=_StubRetriever(),
    )
    assert result.status == "pass"
    runtime = Path(result.extensions["runtime_dir"])

    confirmed = confirm_runtime(
        runtime,
        library_root=library,
        index_root=index,
        confirmed=True,
        volume=1,
        chapter=1,
        scene=1,
    )
    assert confirmed.status == "committed"
    assert Path(confirmed.history_path).is_relative_to(
        story / "timelines" / "main"
    )

    promoted = approve_state_proposal(runtime, library_root=library, index_root=index)
    assert promoted.status == "promoted"
    assert list((story / "timelines" / "main" / "history").rglob("*.yaml"))
    assert list((story / "timelines" / "main" / "character-state" / "current").rglob("*.yaml"))
    assert (story / "common" / "registry" / "version-map.yaml").exists()

    # Target stories must not recreate any legacy story-root content or
    # registry files as a side effect of either write transaction.
    for relative in (
        "history",
        "character-state",
        "world-state",
        "registry/timelines.yaml",
        "registry/version-map.yaml",
    ):
        assert not (story / relative).exists(), relative
