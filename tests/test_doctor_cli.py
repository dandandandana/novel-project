"""Tests for the installation preflight and its local CLI route."""

from __future__ import annotations

import json
import subprocess
import sys
from argparse import Namespace
from pathlib import Path

import novel_rag.doctor as doctor_module
from novel_rag.cli.arguments import build_parser
from novel_rag.cli.commands import command_doctor


OLD_COMMANDS = {
    "validate",
    "index",
    "search",
    "list-stories",
    "create-story",
    "generate",
    "continue",
    "init-preferences",
    "confirm",
    "state-review",
    "state-approve",
    "state-reject",
    "import-rag",
    "import-outline",
    "feedback-create",
    "feedback-list",
    "feedback-resolve",
    "api-config",
    "tui",
    "summary",
    "pending",
}


def test_doctor_is_additive_to_the_existing_cli_commands() -> None:
    """依赖：真实CLI parser。输入：既有命令集合。输出：兼容入口及v3增量断言。实现：保留全部旧命令，增加doctor/write/workspace/harness。"""
    parser = build_parser()
    commands = set(parser._subparsers._group_actions[0].choices)

    assert OLD_COMMANDS <= commands
    assert commands == OLD_COMMANDS | {"doctor", "write", "workspace", "harness"}
    assert parser.parse_args(["doctor"]).func is command_doctor


def test_doctor_report_matches_the_local_runtime() -> None:
    report = doctor_module.run_doctor()

    assert report.python_version
    assert report.sqlite_version == doctor_module.sqlite3.sqlite_version
    assert report.ok == (report.fts5 and report.trigram)
    assert report.as_dict()["capabilities"] == {
        "fts5": report.fts5,
        "trigram": report.trigram,
    }


def test_doctor_returns_nonzero_and_explains_missing_fts5(
    monkeypatch, capsys
) -> None:
    monkeypatch.setattr(doctor_module, "_probe_fts5", lambda: False)

    exit_code = command_doctor(Namespace())
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 1
    assert payload["ok"] is False
    assert payload["fts5"] is False
    assert payload["trigram"] is False
    assert any("FTS5" in message for message in payload["diagnostics"])
    assert any("未执行 trigram" in message for message in payload["diagnostics"])


def test_doctor_returns_nonzero_and_explains_missing_trigram(
    monkeypatch, capsys
) -> None:
    monkeypatch.setattr(doctor_module, "_probe_fts5", lambda: True)
    monkeypatch.setattr(doctor_module, "_probe_trigram", lambda: False)

    exit_code = command_doctor(Namespace())
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 1
    assert payload["ok"] is False
    assert payload["fts5"] is True
    assert payload["trigram"] is False
    assert any("trigram" in message for message in payload["diagnostics"])


def test_python_module_route_reports_without_using_global_console_script() -> None:
    project_root = Path(__file__).resolve().parents[1]
    completed = subprocess.run(
        [sys.executable, "-m", "novel_rag.cli", "doctor"],
        cwd=project_root,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )

    payload = json.loads(completed.stdout)
    assert completed.returncode in {0, 1}
    assert completed.returncode == (0 if payload["ok"] else 1)
    assert payload["python_version"]
    assert payload["sqlite_version"]
    assert "capabilities" in payload
