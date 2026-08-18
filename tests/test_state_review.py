import json
import shutil
from pathlib import Path

import yaml

from novel_rag.state_review import (
    StateReviewError,
    approve_state_proposal,
    inspect_state_proposal,
    reject_state_proposal,
)


def _library(tmp_path: Path) -> tuple[Path, Path]:
    library = tmp_path / "novel-rag"
    story = library / "stories" / "demo"
    (library / "registry").mkdir(parents=True)
    (library / "registry" / "layout.yaml").write_text(yaml.safe_dump({"layout_version": "2.0"}), encoding="utf-8")
    (library / "registry" / "stories.yaml").write_text(
        yaml.safe_dump({"stories": [{"story_id": "demo"}]}), encoding="utf-8"
    )
    (story / "registry").mkdir(parents=True)
    (story / "registry" / "timelines.yaml").write_text(
        yaml.safe_dump({"timelines": [{"story_id": "demo", "timeline_id": "main"}]}), encoding="utf-8"
    )
    (story / "registry" / "character-variants.yaml").write_text(
        yaml.safe_dump({"character_variants": []}), encoding="utf-8"
    )
    (story / "registry" / "module-map.yaml").write_text(
        yaml.safe_dump({"modules": []}), encoding="utf-8"
    )
    (story / "registry" / "version-map.yaml").write_text(
        yaml.safe_dump({"versions": []}), encoding="utf-8"
    )
    for directory in (
        "history",
        "character-state/current",
        "character-state/snapshots",
        "character-state/change-logs",
        "world-state/current",
        "world-state/snapshots",
        "world-state/change-logs",
    ):
        (story / directory).mkdir(parents=True, exist_ok=True)
    (library / "shared" / "templates").mkdir(parents=True)
    source = Path(__file__).parents[1] / "novel-rag" / "shared" / "templates"
    for name in ("character-current.yaml", "world-current.yaml"):
        shutil.copy2(source / name, library / "shared" / "templates" / name)
    index = library / "index"
    (index / "stories").mkdir(parents=True)
    return library, index


def _runtime(tmp_path: Path, library: Path, *, character: bool = True, world: bool = False) -> Path:
    story = library / "stories" / "demo"
    history = story / "history" / "volume-01" / "chapter-001" / "scene-001.yaml"
    history.parent.mkdir(parents=True)
    history.write_text(
        yaml.safe_dump(
            {
                "metadata": {
                    "document_id": "history-demo-v01-c001-s001",
                    "story_id": "demo",
                    "timeline_id": "main",
                    "document_type": "history",
                    "title": "第一场",
                    "volume": 1,
                    "chapter": 1,
                    "scene": 1,
                    "status": "canon",
                    "version": "1.0",
                },
                "content": "甲把信交给乙，乙确认收下。",
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    if character:
        current = story / "character-state" / "current" / "jia.yaml"
        current.write_text(
            yaml.safe_dump(
                {
                    "metadata": {
                        "document_id": "state-current-jia-v1.0",
                        "story_id": "demo",
                        "timeline_id": "main",
                        "document_type": "character_state",
                        "title": "甲当前状态",
                        "character_id": "jia",
                        "variant_id": "jia-main",
                        "snapshot_type": "current",
                        "effective_at": "volume-01-chapter-001",
                        "last_updated": "2026-01-01",
                        "version": "1.0",
                        "status": "active",
                        "supersedes": None,
                    },
                    "character_state": {
                        "current_position": {"location": "门口", "companions": [], "faction": ""},
                        "knowledge": {"known": ["旧消息"], "unknown": [], "mistaken_beliefs": [], "suspicions": [], "secrets_held": []},
                    },
                },
                allow_unicode=True,
                sort_keys=False,
            ),
            encoding="utf-8",
        )
    runtime = tmp_path / "outputs" / ".workflow" / "demo" / "task-1"
    runtime.mkdir(parents=True)
    (runtime / "contract.json").write_text(
        json.dumps({"request": {"story_id": "demo", "timeline_id": "main"}}), encoding="utf-8"
    )
    result = {"status": "pass", "extensions": {"confirmed": True, "runtime_dir": str(runtime)}}
    (runtime / "result.json").write_text(json.dumps(result), encoding="utf-8")
    proposal = {
        "status": "needs_review",
        "writeback_id": "wb-001",
        "history_document_id": "history-demo-v01-c001-s001",
        "candidate_state": {
            "characters": {
                "jia": {"knowledge": {"known": ["新消息"]}, "constraints": {"position": "ignore-me"}}
            }
        },
        "event_state_deltas": [{"event_id": "event-1", "state_deltas": {"jia": {"knowledge": {"known": ["新消息"]}}}}],
    }
    if world:
        proposal["world_state"] = {"global_events": ["甲乙交换信件"]}
    (runtime / "state-writeback-proposal.json").write_text(json.dumps(proposal, ensure_ascii=False), encoding="utf-8")
    return runtime


def _checks(*_args):
    return []


def test_inspect_requires_no_mutation_and_exposes_evidence(tmp_path: Path):
    library, _ = _library(tmp_path)
    runtime = _runtime(tmp_path, library)
    summary = inspect_state_proposal(runtime, library_root=library)
    assert summary["status"] == "needs_review"
    assert summary["character_ids"] == ["jia"]
    assert summary["evidence"]["history_document_id"] == "history-demo-v01-c001-s001"
    assert json.loads((runtime / "state-writeback-proposal.json").read_text(encoding="utf-8"))["status"] == "needs_review"


def test_approve_promotes_template_state_with_snapshot_log_and_version_map(tmp_path: Path):
    library, index = _library(tmp_path)
    runtime = _runtime(tmp_path, library)
    result = approve_state_proposal(
        runtime,
        library_root=library,
        index_root=index,
        validator=_checks,
        indexer=_checks,
        retrieval=lambda *_args: 2,
    )
    assert result.status == "promoted"
    assert result.retrieval_cases == 2
    current = yaml.safe_load((library / "stories/demo/character-state/current/jia.yaml").read_text(encoding="utf-8"))
    assert current["metadata"]["document_id"] == "state-current-jia-v1.1"
    assert current["character_state"]["knowledge"]["known"] == ["新消息"]
    snapshots = list((library / "stories/demo/character-state/snapshots").rglob("*.yaml"))
    logs = list((library / "stories/demo/character-state/change-logs").rglob("*.yaml"))
    assert snapshots and logs
    version_map = yaml.safe_load((library / "stories/demo/registry/version-map.yaml").read_text(encoding="utf-8"))
    assert version_map["versions"][0]["current"] == "state-current-jia-v1.1"
    saved = json.loads((runtime / "state-writeback-proposal.json").read_text(encoding="utf-8"))
    assert saved["status"] == "promoted"
    assert approve_state_proposal(runtime, library_root=library, index_root=index, validator=_checks, indexer=_checks, retrieval=lambda *_args: 2).status == "noop"


def test_reject_does_not_touch_formal_state(tmp_path: Path):
    library, _ = _library(tmp_path)
    runtime = _runtime(tmp_path, library)
    result = reject_state_proposal(runtime, reason="作者暂不采用", library_root=library)
    assert result.status == "rejected"
    assert (library / "stories/demo/character-state/current/jia.yaml").exists()
    saved = json.loads((runtime / "state-writeback-proposal.json").read_text(encoding="utf-8"))
    assert saved["decision"] == "reject"


def test_failed_validation_rolls_back_everything(tmp_path: Path):
    library, index = _library(tmp_path)
    runtime = _runtime(tmp_path, library)
    before = (library / "stories/demo/character-state/current/jia.yaml").read_bytes()
    try:
        approve_state_proposal(
            runtime,
            library_root=library,
            index_root=index,
            validator=lambda *_args: ["simulated failure"],
            indexer=_checks,
            retrieval=_checks,
        )
    except StateReviewError as exc:
        assert "validate" in str(exc)
    else:
        raise AssertionError("validation failure must abort promotion")
    assert (library / "stories/demo/character-state/current/jia.yaml").read_bytes() == before
    assert not list((library / "stories/demo/character-state/snapshots").rglob("*.yaml"))
    proposal = json.loads((runtime / "state-writeback-proposal.json").read_text(encoding="utf-8"))
    assert proposal["status"] == "needs_review"
