import json
from pathlib import Path

from novel_rag.documents import load_document
from novel_rag.writeback import WritebackError, confirm_runtime

from test_generation import make_library


def make_runtime(tmp_path: Path, *, status: str = "pass") -> Path:
    runtime = tmp_path / "outputs" / ".workflow" / "demo" / "chapter-1"
    runtime.mkdir(parents=True)
    text = "甲把信交给乙。"
    (runtime / "final.txt").write_text(text, encoding="utf-8")
    (runtime / "draft-00.txt").write_text(text, encoding="utf-8")
    (runtime / "polished-00.txt").write_text(text, encoding="utf-8")
    (runtime / "audit-00.json").write_text("{}", encoding="utf-8")
    (runtime / "context.json").write_text("{}", encoding="utf-8")
    (runtime / "references.json").write_text("[]", encoding="utf-8")
    (runtime / "contract.json").write_text(json.dumps({
        "request": {"story_id": "demo", "timeline_id": "main"},
        "outline": {"opening_state": "甲持有信", "ending_state": "乙持有信"},
    }, ensure_ascii=False), encoding="utf-8")
    (runtime / "result.json").write_text(json.dumps({
        "text": text, "status": status,
        "events": [{"event_id": "letter", "actor": "甲", "targets": ["乙"],
                    "result": "乙持有信", "state_deltas": {"乙": {"knowledge": {"has_letter": True}}}}],
        "state": {"version": 1, "characters": {"乙": {"knowledge": {"has_letter": True}}}},
        "extensions": {"confirmed": False, "runtime_dir": str(runtime)},
    }, ensure_ascii=False), encoding="utf-8")
    return runtime


def test_confirm_writes_history_and_review_proposal_only(tmp_path: Path) -> None:
    library, index = make_library(tmp_path)
    runtime = make_runtime(tmp_path)
    result = confirm_runtime(runtime, library_root=library, index_root=index, confirmed=True,
                             volume=1, chapter=2, scene=1, title="交信")
    assert result.status == "committed"
    history = load_document(Path(result.history_path))
    assert history.body["content"] == "甲把信交给乙。"
    assert history.metadata["character_ids"] == ["甲", "乙"]
    assert (runtime / "state-writeback-proposal.json").exists()
    saved_result = json.loads((runtime / "result.json").read_text(encoding="utf-8"))
    assert saved_result["extensions"]["confirmed"] is True
    assert saved_result["text"] == ""
    assert saved_result["extensions"]["final_sha256"]
    assert not list(runtime.glob("*.txt"))
    assert not (runtime / "context.json").exists()
    assert not (runtime / "references.json").exists()
    assert not list(runtime.glob("audit-*.json"))
    assert {path.name for path in runtime.iterdir()} == {
        "contract.json", "result.json", "confirmation.json", "state-writeback-proposal.json"
    }
    assert not any((library / "stories" / "demo" / "character-state" / "current").glob("*.yaml"))
    assert confirm_runtime(runtime, library_root=library, index_root=index, confirmed=True,
                           volume=1, chapter=2, scene=1).status == "noop"


def test_confirm_requires_explicit_approval_and_accepted_runtime(tmp_path: Path) -> None:
    library, index = make_library(tmp_path)
    runtime = make_runtime(tmp_path, status="user_guidance_required")
    try:
        confirm_runtime(runtime, library_root=library, index_root=index, confirmed=True,
                        volume=1, chapter=2, scene=1)
    except WritebackError as exc:
        assert "不可确认" in str(exc)
    else:
        raise AssertionError("unaccepted runtime must not enter history")


def test_confirmed_marker_cannot_be_reused_for_another_scene(tmp_path: Path) -> None:
    library, index = make_library(tmp_path)
    runtime = make_runtime(tmp_path)
    confirm_runtime(runtime, library_root=library, index_root=index, confirmed=True,
                    volume=1, chapter=2, scene=1)
    (runtime / "confirmation.json").unlink()
    try:
        confirm_runtime(runtime, library_root=library, index_root=index, confirmed=True,
                        volume=1, chapter=2, scene=2)
    except WritebackError as exc:
        assert "标记确认" in str(exc)
    else:
        raise AssertionError("confirmed runtime must not be committed twice")


def test_runtime_story_directory_must_match_contract(tmp_path: Path) -> None:
    library, index = make_library(tmp_path)
    runtime = make_runtime(tmp_path)
    wrong = runtime.parent.parent / "other" / runtime.name
    wrong.parent.mkdir(parents=True)
    runtime.rename(wrong)
    try:
        confirm_runtime(wrong, library_root=library, index_root=index, confirmed=True,
                        volume=1, chapter=2, scene=1)
    except WritebackError as exc:
        assert "story_id" in str(exc)
    else:
        raise AssertionError("runtime path identity must be bound to contract")


def test_failure_after_history_write_rolls_back(tmp_path: Path, monkeypatch) -> None:
    import novel_rag.writeback as writeback
    library, index = make_library(tmp_path)
    runtime = make_runtime(tmp_path)
    original = writeback._atomic_text

    def fail_proposal(path: Path, text: str) -> None:
        if path.name == "state-writeback-proposal.json":
            raise OSError("simulated proposal failure")
        original(path, text)

    monkeypatch.setattr(writeback, "_atomic_text", fail_proposal)
    try:
        confirm_runtime(runtime, library_root=library, index_root=index, confirmed=True,
                        volume=1, chapter=2, scene=1)
    except WritebackError as exc:
        assert "已回滚" in str(exc)
    else:
        raise AssertionError("partial failure must not commit history")
    target = library / "stories" / "demo" / "history" / "volume-01" / "chapter-002" / "scene-001.yaml"
    assert not target.exists()
    assert json.loads((runtime / "result.json").read_text(encoding="utf-8"))["extensions"]["confirmed"] is False
    assert (runtime / "final.txt").exists()


def test_staging_symlink_cannot_escape_runtime(tmp_path: Path) -> None:
    library, index = make_library(tmp_path)
    runtime = make_runtime(tmp_path)
    outside = tmp_path / "outside-staging"
    outside.mkdir()
    try:
        (runtime / "staging").symlink_to(outside, target_is_directory=True)
    except OSError:
        return  # Windows may deny symlink creation without developer mode.
    try:
        confirm_runtime(runtime, library_root=library, index_root=index, confirmed=True,
                        volume=1, chapter=2, scene=1)
    except WritebackError as exc:
        assert "staging" in str(exc)
    else:
        raise AssertionError("staging symlink must not escape runtime")
    assert not any(outside.iterdir())


def test_missing_confirmed_marker_is_rejected(tmp_path: Path) -> None:
    library, index = make_library(tmp_path)
    runtime = make_runtime(tmp_path)
    value = json.loads((runtime / "result.json").read_text(encoding="utf-8"))
    del value["extensions"]["confirmed"]
    (runtime / "result.json").write_text(json.dumps(value), encoding="utf-8")
    try:
        confirm_runtime(runtime, library_root=library, index_root=index, confirmed=True,
                        volume=1, chapter=2, scene=1)
    except WritebackError as exc:
        assert "confirmed" in str(exc)
    else:
        raise AssertionError("untrusted runtime marker must be rejected")
