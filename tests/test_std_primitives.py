"""基础库独立性、原持久化字节和旧公开入口兼容。"""
from __future__ import annotations

import ast
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from novel_rag.std import atomic_io
from novel_rag.std.hashing import fingerprint_bytes
from novel_rag.std.serialization import json_text


def test_std_imports_only_standard_library_in_fresh_process() -> None:
    """依赖：AST/独立Python进程。输入：实际std源码。输出：无业务或第三方依赖断言。实现：静态核依赖根，并逐模块导入核真实加载范围。"""
    import novel_rag.std as std

    root = Path(std.__file__).parent
    modules = []
    for path in root.glob("*.py"):
        modules.append("novel_rag.std" + ("." + path.stem if path.stem != "__init__" else ""))
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                assert all(name.name.split(".")[0] in sys.stdlib_module_names for name in node.names)
            elif isinstance(node, ast.ImportFrom):
                assert node.level <= 1
                if not node.level:
                    assert node.module.split(".")[0] in sys.stdlib_module_names
    script = (
        "import importlib,json,sys; "
        f"[importlib.import_module(name) for name in {modules!r}]; "
        "print(json.dumps([name for name in sys.modules if name.startswith('novel_rag')]))"
    )
    result = subprocess.run([sys.executable, "-B", "-c", script], check=True,
                            text=True, encoding="utf-8", capture_output=True)
    assert all(name == "novel_rag" or name == "novel_rag.std" or name.startswith("novel_rag.std.")
               for name in json.loads(result.stdout))


def test_old_public_primitives_reexport_the_same_implementations() -> None:
    """依赖：旧公开导出与std。输入：既有函数路径。输出：对象身份一致。实现：核兼容导出委托同一实现而非复制算法。"""
    from novel_rag import timeutil
    from novel_rag.graph import corpus
    from novel_rag.mutations import coordinator, types
    from novel_rag.std.time import utc_now_iso

    assert timeutil.utc_now_iso is utc_now_iso
    assert types.fingerprint_bytes is fingerprint_bytes
    assert coordinator.atomic_write_bytes is atomic_io.atomic_write_bytes
    assert coordinator.atomic_write_json is atomic_io.atomic_write_json
    assert corpus.json_text is json_text


def test_serialization_keeps_distinct_persisted_byte_contracts(tmp_path: Path) -> None:
    """依赖：std编码/真实临时文件。输入：Unicode映射与空字节。输出：历史紧凑/缩进格式及固定SHA。实现：与既有字面量核对，不将幂等格式统一。"""
    value = {"z": "雪", "a": [1, True]}
    assert json_text(value) == '{"a":[1,true],"z":"雪"}'
    path = tmp_path / "manifest.json"
    atomic_io.atomic_write_json(path, value)
    assert path.read_bytes() == '{\n  "a": [\n    1,\n    true\n  ],\n  "z": "雪"\n}\n'.encode("utf-8")
    assert fingerprint_bytes(b"") == "sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


def test_atomic_write_does_not_remove_a_preexisting_temporary(tmp_path: Path, monkeypatch) -> None:
    """依赖：真实文件/可控UUID。输入：已有临时文件与旧目标。输出：独占创建拒绝且两者不变。实现：制造名称碰撞检验只清理自己创建的文件。"""
    target = tmp_path / "draft.txt"
    target.write_bytes(b"old")
    temporary = tmp_path / ".draft.txt.occupied.write"
    temporary.write_bytes(b"another owner")
    monkeypatch.setattr(atomic_io.uuid, "uuid4", lambda: SimpleNamespace(hex="occupied"))
    with pytest.raises(FileExistsError):
        atomic_io.atomic_write_bytes(target, b"new")
    assert target.read_bytes() == b"old"
    assert temporary.read_bytes() == b"another owner"


def test_old_tool_commit_replays_without_reencoding_identity(tmp_path: Path) -> None:
    """依赖：原DraftStore/测试绑定。输入：采用旧带空格JSON指纹的回执。输出：重启后原参数恢复成功。实现：写入历史提交形状并核同ID换参仍拒绝。"""
    from novel_rag.generation.store import DraftStore, StoreConflict
    from test_run_store import _binding

    store = DraftStore(tmp_path)
    run = store.create(_binding(), "", "")
    old_bytes = '{"text": "雪", "value": 1}'.encode("utf-8")
    run["tool_commits"]["old-operation"] = {
        "arguments_hash": fingerprint_bytes(old_bytes), "result": {"saved": "old-result"}}
    store.write(run)
    restored = DraftStore(tmp_path)
    assert restored.committed_tool(run["run_id"], "old-operation", {"value": 1, "text": "雪"}) == {"saved": "old-result"}
    with pytest.raises(StoreConflict):
        restored.committed_tool(run["run_id"], "old-operation", {"value": 2, "text": "雪"})
