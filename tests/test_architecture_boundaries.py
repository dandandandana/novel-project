"""Focused source checks for the existing std, contract and application owners."""
from __future__ import annotations

import ast
from importlib.util import resolve_name
from pathlib import Path
import sys

import pytest

import novel_rag


def _import_targets(tree: ast.AST, relative_path: str) -> list[tuple[int, str]]:
    """依赖：AST/标准相对名解析。输入：源码树与包内路径。输出：行号和绝对导入名。实现：遍历所有作用域，展开from的模块及成员，不导入目标。"""
    parts = Path(relative_path).with_suffix("").parts
    package = ".".join(("novel_rag", *parts[:-1]))
    targets = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            targets.extend((node.lineno, name.name) for name in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = resolve_name("." * node.level + (node.module or ""), package) if node.level else node.module
            targets.extend((node.lineno, module if name.name == "*" else module + "." + name.name) for name in node.names)
    return targets


def _architecture_violations(relative_path: str, source: str) -> list[str]:
    """依赖：AST/已确认owner边界。输入：包内路径与源码。输出：带规则和行号的违规列表。实现：检查导入及直接/字面getattr访问，不推断任意动态代码或业务类型。"""
    tree = ast.parse(source, filename=relative_path)
    violations = []
    for line, target in _import_targets(tree, relative_path):
        if relative_path.startswith("std/"):
            allowed = target.split(".")[0] in sys.stdlib_module_names or target == "novel_rag.std" or target.startswith("novel_rag.std.")
            if not allowed:
                violations.append(f"std-dependency:{line}:{target}")
        if relative_path.startswith("contracts/"):
            allowed = target.split(".")[0] in sys.stdlib_module_names or any(
                target == owner or target.startswith(owner + ".")
                for owner in ("novel_rag.contracts", "novel_rag.identity")
            )
            if not allowed:
                violations.append(f"contract-dependency:{line}:{target}")
        if relative_path in {"memory/service.py", "writeback/adopt.py", "mutations/source.py"}:
            if target == "novel_rag.composition" or target.startswith("novel_rag.composition."):
                violations.append(f"reverse-composition:{line}:{target}")
    adapter = relative_path.startswith("cli/") or relative_path == "web/app.py"
    commit_owner = relative_path in {"memory/service.py", "writeback/adopt.py"}
    for node in ast.walk(tree):
        name = node.attr if isinstance(node, ast.Attribute) else None
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "getattr"
                and len(node.args) >= 2 and isinstance(node.args[1], ast.Constant)):
            name = node.args[1].value
        if adapter and name in {"store", "memory", "config"}:
            violations.append(f"adapter-internal:{node.lineno}:{name}")
        # These owners delegate persistence to Store operations or atomic writers;
        # binding a raw .write method for a later call also violates that boundary.
        if commit_owner and name == "write":
            violations.append(f"raw-run-write:{node.lineno}:write")
    return violations


def test_architecture_owners_keep_their_declared_source_boundaries() -> None:
    """依赖：实际安装包源码/聚焦AST规则。输入：现有std、合同和适配owner。输出：无越界断言。实现：递归发现基础包及CLI，显式包含应用/提交owner，不扫描有意保留的v2组合链。"""
    root = Path(novel_rag.__file__).resolve().parent
    paths = {root / name for name in ("web/app.py", "memory/service.py", "writeback/adopt.py", "mutations/source.py")}
    for directory in ("std", "contracts", "cli"):
        discovered = set((root / directory).rglob("*.py"))
        assert discovered, directory
        paths.update(discovered)
    violations = []
    for path in sorted(paths):
        relative = path.relative_to(root).as_posix()
        violations.extend(f"{relative}:{issue}" for issue in _architecture_violations(relative, path.read_text(encoding="utf-8")))
    assert not violations, "\n".join(violations)


@pytest.mark.parametrize(("path", "source", "rule"), [
    ("std/example.py", "import yaml", "std-dependency"),
    ("std/nested/example.py", "from ...memory import service", "std-dependency"),
    ("contracts/example.py", "from .. import documents", "contract-dependency"),
    ("contracts/example.py", "def deferred():\n    from novel_rag.generation import store", "contract-dependency"),
    ("memory/service.py", "from ..composition import build_writer_service", "reverse-composition"),
    ("writeback/adopt.py", "import novel_rag.composition as wiring", "reverse-composition"),
    ("web/app.py", "return_value = app.state.service.store.load(run_id)", "adapter-internal"),
    ("cli/commands.py", "result = getattr(service, 'memory').recall(run_id)", "adapter-internal"),
    ("cli/new_command.py", "profiles = service.config.list_profiles()", "adapter-internal"),
    ("memory/service.py", "self.store.write(run)", "raw-run-write"),
    ("writeback/adopt.py", "persist = getattr(self.store, 'write')", "raw-run-write"),
])
def test_architecture_checks_reject_representative_violations(path: str, source: str, rule: str) -> None:
    """依赖：同一源码检查器/隔离字符串反例。输入：每个约束的违规。输出：预期规则失败。实现：不改真实文件，验证拒绝来自边界规则而非语法或依赖错误。"""
    issues = _architecture_violations(path, source)
    assert any(issue.startswith(rule + ":") for issue in issues), issues


@pytest.mark.parametrize(("path", "source"), [
    ("std/nested/example.py", "import json\nfrom ..hashing import fingerprint_bytes"),
    ("contracts/example.py", "from dataclasses import dataclass\nfrom .. import identity\nfrom ..identity import GraphKey\nfrom .references import DocumentRef"),
    ("cli/commands.py", "from ..composition import build_writer_service\nresult = service.run_result(run_id)"),
    ("web/app.py", "from ..generation.store import StoreConflict\nresult = service.workspace_snapshot(run_id)"),
    ("memory/service.py", "result = self.store.commit_memory(run_id, key, arguments, build)"),
    ("writeback/adopt.py", "atomic_write_json(path, receipt)\nself.store.record_adoption_receipt(run_id, receipt)"),
])
def test_architecture_checks_preserve_legal_delegation(path: str, source: str) -> None:
    """依赖：同一源码检查器/合法owner样例。输入：纯依赖与公共用例委托。输出：零违规。实现：保护组合根装配、异常类型及原提交接口，不把v2兼容误禁。"""
    assert _architecture_violations(path, source) == []
