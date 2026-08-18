from pathlib import Path
import json

import yaml
import pytest

from novel_rag.generation import GenerationError, generate
from novel_rag.index import SqliteIndex
from novel_rag.resume import ResumeError, continue_generation


def make_library(tmp_path: Path) -> tuple[Path, Path]:
    library = tmp_path / "novel-rag"
    story = library / "stories" / "demo"
    (library / "registry").mkdir(parents=True)
    (library / "registry" / "layout.yaml").write_text(yaml.safe_dump({"layout_version": "2.0"}), encoding="utf-8")
    (library / "registry" / "stories.yaml").write_text(
        yaml.safe_dump({"stories": [{"story_id": "demo"}]}), encoding="utf-8")
    (story / "registry").mkdir(parents=True)
    (story / "registry" / "timelines.yaml").write_text(
        yaml.safe_dump({"timelines": [{"story_id": "demo", "timeline_id": "main"}]}), encoding="utf-8")
    (story / "author-preferences.txt").write_text("默认", encoding="utf-8")
    index = library / "index"
    (index / "stories").mkdir(parents=True)
    SqliteIndex(index / "stories" / "demo.db").rebuild([])
    SqliteIndex(index / "shared.db").rebuild([])
    return library, index


class GuidanceModel:
    def __init__(self) -> None:
        self.current_requests: list[str] = []
        self.calls: list[str] = []

    def __call__(self, stage: str, payload: dict):
        self.calls.append(stage)
        if stage == "normalize":
            self.current_requests.append(payload.get("current_request", ""))
            return {"outline": {"required_events": [{"event": "甲打开门", "actor": "甲"}]}}
        if stage == "decide_behavior":
            return "甲打开门"
        if stage == "derive_result":
            return {"result": "门已打开"}
        if stage == "render_prose":
            return {"text": "甲打开门，门已打开。"}
        if stage == "validate":
            return {"issues": [{"check": "continuity", "message": "需要作者判断", "severity": "blocked"}]}
        raise AssertionError(stage)


def test_continue_generation_creates_child_and_preserves_parent(tmp_path: Path) -> None:
    library, index = make_library(tmp_path)
    output = tmp_path / "outputs"
    model = GuidanceModel()
    parent = generate({"story_id": "demo", "outline": "甲打开门"}, model,
                      library_root=library, index_root=index, output_root=output, task_id="parent")
    parent_dir = Path(parent.extensions["runtime_dir"])
    child = continue_generation(parent_dir, "让甲先确认门外没有人", model,
                                library_root=library, index_root=index, output_root=output,
                                task_id="parent-guidance")
    child_dir = Path(child.extensions["runtime_dir"])
    assert child_dir != parent_dir
    assert parent_dir.exists()
    metadata = yaml.safe_load((child_dir / "resume.json").read_text(encoding="utf-8"))
    assert Path(metadata["parent_runtime"]).resolve() == parent_dir.resolve()
    assert metadata["supersedes_runtime"] == metadata["parent_runtime"]
    assert "作者续作指导：让甲先确认门外没有人" in model.current_requests[-1]
    result = yaml.safe_load((child_dir / "result.json").read_text(encoding="utf-8"))
    assert result["extensions"]["parent_runtime"] == str(parent_dir)


def test_continue_requires_guidance_status_and_does_not_touch_parent(tmp_path: Path) -> None:
    library, index = make_library(tmp_path)
    output = tmp_path / "outputs"
    model = GuidanceModel()
    parent = generate({"story_id": "demo", "outline": "甲打开门"}, model,
                      library_root=library, index_root=index, output_root=output,
                      task_id="parent")
    parent_dir = Path(parent.extensions["runtime_dir"])
    parent_result = (parent_dir / "result.json").read_bytes()
    result = json.loads(parent_result.decode("utf-8"))
    result["status"] = "pass"
    (parent_dir / "result.json").write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ResumeError, match="user_guidance_required"):
        continue_generation(parent_dir, "继续", model, library_root=library, index_root=index,
                            output_root=output, task_id="child")
    assert json.loads((parent_dir / "result.json").read_text(encoding="utf-8"))["status"] == "pass"


def test_generate_conflict_rejected_and_confirmed_never_overwritten(tmp_path: Path) -> None:
    library, index = make_library(tmp_path)
    output = tmp_path / "outputs"
    model = GuidanceModel()
    first = generate({"story_id": "demo", "outline": "甲打开门"}, model,
                     library_root=library, index_root=index, output_root=output, task_id="same")
    with pytest.raises(GenerationError, match="使用新的 task_id"):
        generate({"story_id": "demo", "outline": "甲打开门"}, model,
                 library_root=library, index_root=index, output_root=output, task_id="same")
    runtime = Path(first.extensions["runtime_dir"])
    result_path = runtime / "result.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    result.setdefault("extensions", {})["confirmed"] = True
    result_path.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(GenerationError, match="已经确认"):
        generate({"story_id": "demo", "outline": "甲打开门"}, model,
                 library_root=library, index_root=index, output_root=output,
                 task_id="same", overwrite_runtime=True)
