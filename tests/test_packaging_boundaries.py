"""Installed-package data and runtime-root contracts across checkout layouts."""

from __future__ import annotations

from importlib.resources import files
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

import novel_rag
from novel_rag.generation.tools import writing_resources
from novel_rag.state.helpers import _template
from novel_rag.state.types import StateReviewError


def test_installed_defaults_follow_working_directory(tmp_path: Path) -> None:
    """依赖：当前安装包/独立Python进程。输入：仓库外目录及可选CI wheel门。输出：资料根/CLI及真实非editable安装断言。实现：隔离启动，按CI标志核包位置和安装元数据，禁止PYTHONPATH代替安装。"""
    command = """
import json
from importlib.metadata import distribution
import novel_rag
from novel_rag import config
from novel_rag.cli.arguments import build_parser
parser = build_parser()
default = parser.parse_args(["validate"])
explicit = parser.parse_args(["--library", "author-library", "validate"])
print(json.dumps({
    "package": novel_rag.__file__,
    "installed_init": str(distribution("novel-rag").locate_file("novel_rag/__init__.py")),
    "direct_url": json.loads(distribution("novel-rag").read_text("direct_url.json") or "{}"),
    "root": str(config.ROOT), "library": str(config.LIBRARY_ROOT),
    "index": str(config.INDEX_ROOT), "default": default.library,
    "explicit": explicit.library, "explicit_index": explicit.index,
}))
"""
    completed = subprocess.run(
        [sys.executable, "-I", "-c", command], cwd=tmp_path,
        check=False, capture_output=True, text=True, timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    values = json.loads(completed.stdout)
    assert Path(values["package"]).resolve() == Path(novel_rag.__file__).resolve()
    if os.environ.get("NOVEL_RAG_REQUIRE_WHEEL") == "1":
        assert Path(values["package"]).resolve() == Path(values["installed_init"]).resolve()
        assert values["direct_url"].get("dir_info", {}).get("editable") is not True
    assert Path(values["root"]) == tmp_path
    assert Path(values["library"]) == tmp_path / "novel-rag"
    assert Path(values["index"]) == tmp_path / "novel-rag" / "index"
    assert values["default"] == values["library"]
    assert values["explicit"] == "author-library"
    assert values["explicit_index"] is None
    assert not (tmp_path / "novel-rag").exists()


def test_packaged_writer_and_web_resources_are_complete() -> None:
    """依赖：importlib.resources/真实资源加载器。输入：安装包资源。输出：参考和网页素材完整性断言。实现：按manifest遍历全部静态图片并核对生产读取结果。"""
    resource = files("novel_rag.generation").joinpath("resources.json")
    assert json.loads(resource.read_text(encoding="utf-8")) == writing_resources()
    static = files("novel_rag.web").joinpath("static")
    for name in ("index.html", "workspace.js", "launcher.js", "tiles.json"):
        assert static.joinpath(name).read_bytes(), name
    manifest = json.loads(static.joinpath("assets").joinpath("manifest.json").read_text(encoding="utf-8"))
    assert manifest["assets"]
    for asset in manifest["assets"]:
        assert static.joinpath("assets").joinpath(asset["file"]).read_bytes(), asset["file"]


@pytest.mark.parametrize("name", ["character-current.yaml", "world-current.yaml"])
def test_state_template_falls_back_to_read_only_package(tmp_path: Path, name: str) -> None:
    """依赖：现有状态模板入口/包资源。输入：无模板资料根。输出：默认状态模板及无写入断言。实现：读取真实后备资源并核对读取前后字节。"""
    resource = files("novel_rag").joinpath("templates").joinpath(name)
    before = resource.read_bytes()
    value = _template(tmp_path, name)
    assert value["metadata"]["document_type"] in {"character_state", "world_state"}
    assert resource.read_bytes() == before
    assert list(tmp_path.iterdir()) == []


def test_state_template_prefers_user_library_in_existing_order(tmp_path: Path) -> None:
    """依赖：现有状态模板入口。输入：两个用户模板层。输出：用户优先级断言。实现：分别移除shared覆盖和根覆盖以核对包后备。"""
    shared = tmp_path / "shared" / "templates" / "character-current.yaml"
    local = tmp_path / "templates" / "character-current.yaml"
    shared.parent.mkdir(parents=True)
    local.parent.mkdir(parents=True)
    shared.write_text("choice: shared\n", encoding="utf-8")
    local.write_text("choice: local\n", encoding="utf-8")
    assert _template(tmp_path, shared.name) == {"choice": "shared"}
    shared.unlink()
    assert _template(tmp_path, local.name) == {"choice": "local"}
    local.unlink()
    assert _template(tmp_path, local.name)["metadata"]["document_type"] == "character_state"
    with pytest.raises(StateReviewError, match="缺少状态模板"):
        _template(tmp_path, "unknown-template.yaml")


def test_context_identity_fails_when_declared_source_is_missing(monkeypatch) -> None:
    """依赖：运行证据原有源码hash入口。输入：声明缺失文件。输出：明确读取错误。实现：仅替换文件清单，确保证据不会悄悄省略缺失实现。"""
    import test_context_runtime

    monkeypatch.setattr(test_context_runtime, "_SOURCE_FILES", ("novel_rag/missing-implementation.py",))
    with pytest.raises(FileNotFoundError):
        test_context_runtime._source_hashes()
