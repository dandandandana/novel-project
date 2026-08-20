from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from novel_rag.cli import build_parser
from novel_rag.cli import commands as cli_commands
from novel_rag.documents import RagDocument
from novel_rag.generation import LegacyRetrieverAdapter
from novel_rag.index import SqliteIndex, rebuild_isolated_indexes


def _document(path: Path, content: str) -> RagDocument:
    path.write_text("source bytes", encoding="utf-8")
    return RagDocument(
        path,
        {
            "document_id": f"{content}-v1.0",
            "story_id": "demo",
            "timeline_id": "main",
            "document_type": "history",
            "title": content,
            "status": "canon",
            "version": "1.0",
        },
        {"content": content},
    )


def _library(tmp_path: Path) -> tuple[Path, Path]:
    library = tmp_path / "library"
    (library / "registry").mkdir(parents=True)
    (library / "registry" / "stories.yaml").write_text(
        yaml.safe_dump({"stories": [{"story_id": "demo"}]}),
        encoding="utf-8",
    )
    story_registry = library / "stories" / "demo" / "registry"
    story_registry.mkdir(parents=True)
    (story_registry / "timelines.yaml").write_text(
        yaml.safe_dump(
            {"timelines": [{"story_id": "demo", "timeline_id": "main"}]}
        ),
        encoding="utf-8",
    )
    return library, library / "index"


def test_cli_search_legacy_forces_old_db_when_both_indexes_exist(
    tmp_path: Path, capsys
) -> None:
    library, index = _library(tmp_path)
    legacy_document = _document(tmp_path / "legacy.yaml", "legacy-cli-token")
    SqliteIndex(index / "stories" / "demo.db", _compat=True).rebuild(
        [legacy_document]
    )
    canonical_document = _document(tmp_path / "canonical.yaml", "canonical-cli-token")
    with pytest.warns(DeprecationWarning):
        rebuild_isolated_indexes(index, [canonical_document], ["demo"])

    args = Namespace(
        library=str(library),
        index=str(index),
        story="demo",
        timeline="main",
        query="legacy-cli-token",
        type=None,
        status=None,
        limit=6,
        no_shared=True,
        legacy=True,
    )
    assert cli_commands.command_search(args) == 0
    payload = json.loads(capsys.readouterr().out)

    assert [item["document_id"] for item in payload] == [legacy_document.document_id]


def test_cli_generate_legacy_injects_generation_legacy_adapter(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    library, index = _library(tmp_path)
    args = build_parser().parse_args(
        [
            "--library",
            str(library),
            "--index",
            str(index),
            "generate",
            "--story",
            "demo",
            "--timeline",
            "main",
            "--outline",
            "测试大纲",
            "--model-command",
            "unused-model-command",
            "--legacy",
        ]
    )
    captured: dict[str, object] = {}

    monkeypatch.setattr(cli_commands, "_model_from_args", lambda _args: object())

    def fake_generate(request, model, **kwargs):
        captured["request"] = request
        captured["model"] = model
        captured["retriever"] = kwargs["retriever"]
        return SimpleNamespace(text="legacy generated", warnings=(), status="pass")

    monkeypatch.setattr(cli_commands, "generate", fake_generate)

    assert cli_commands.command_generate(args) == 0
    capsys.readouterr()
    assert isinstance(captured["retriever"], LegacyRetrieverAdapter)
