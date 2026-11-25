from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from textwrap import dedent

import pytest


LEGACY_WRITER_MODULES = (
    "novel_rag.generation.helpers", "novel_rag.generation.pipeline", "novel_rag.generation.retrieval",
    "novel_rag.resume", "novel_rag.state", "novel_rag.writeback.confirm", "novel_rag.writeback.helpers",
)


def _import_probe(statement: str, forbidden: tuple[str, ...]) -> list[str]:
    """依赖：独立Python/标准库import hook。输入：实际入口脚本及禁止模块。输出：已加载项目模块或失败。实现：新进程阻断禁止导入并核真实sys.modules，捕获业务输出避免混入证据。"""
    code = dedent('''
        import contextlib, importlib.abc, io, json, sys
        forbidden = FORBIDDEN
        class ImportBoundary(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                """依赖：原import系统。输入：待导入模块。输出：放行或断言失败。实现：按完整模块边界拒绝禁止实现。"""
                if any(fullname == prefix or fullname.startswith(prefix + ".") for prefix in forbidden):
                    raise AssertionError("forbidden import: " + fullname)
        sys.meta_path.insert(0, ImportBoundary())
        with contextlib.redirect_stdout(io.StringIO()):
            exec(STATEMENT)
        print(json.dumps(sorted(name for name in sys.modules if name.startswith("novel_rag"))))
    ''').replace("FORBIDDEN", repr(forbidden)).replace("STATEMENT", repr(dedent(statement)))
    result = subprocess.run(
        [sys.executable, "-B", "-X", "utf8", "-c", code],
        cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True,
        encoding="utf-8", check=False, timeout=45,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    loaded = json.loads(result.stdout)
    assert not [name for name in loaded if any(name == prefix or name.startswith(prefix + ".") for prefix in forbidden)]
    return loaded


@pytest.mark.parametrize(
    ("statement", "forbidden"),
    [
        (
            "import novel_rag.contracts.references",
            ("novel_rag.config", "novel_rag.documents", "novel_rag.generation", "novel_rag.memory", "yaml", "httpx"),
        ),
        (
            "import novel_rag.generation.types",
            ("novel_rag.documents", "novel_rag.config", "novel_rag.generation.helpers", "novel_rag.generation.pipeline"),
        ),
        (
            "import novel_rag.generation.store",
            ("novel_rag.generation.helpers", "novel_rag.generation.pipeline"),
        ),
        (
            "from novel_rag.memory.schema import validate_source_refs; validate_source_refs([{'kind': 'author_input', 'run_id': 'run-1', 'input_slot': 'outline', 'snapshot_hash': 'sha256:' + 'a' * 64}])",
            ("novel_rag.config", "novel_rag.documents", "novel_rag.generation"),
        ),
        ("import novel_rag.cli", (*LEGACY_WRITER_MODULES, "novel_rag.cli.commands", "fastapi", "uvicorn")),
        ("from novel_rag.cli import build_parser; build_parser().parse_args(['doctor'])",
         (*LEGACY_WRITER_MODULES, "novel_rag.composition", "fastapi", "uvicorn")),
        ("import novel_rag.generation.session", (*LEGACY_WRITER_MODULES, "novel_rag.retrieval.service")),
        ("import novel_rag.writeback.adopt", (*LEGACY_WRITER_MODULES, "novel_rag.retrieval.service")),
        ("import novel_rag.retrieval.assembler", ("novel_rag.retrieval.service",)),
    ],
)
def test_contract_imports_do_not_load_implementation_layers(statement: str, forbidden: tuple[str, ...]) -> None:
    """依赖：独立Python进程。输入：合同/Store模块与禁止实现层。输出：无逆向导入。实现：新进程读取真实sys.modules，避免已有pytest导入遮蔽依赖。"""

    _import_probe(statement, forbidden)


@pytest.mark.parametrize("argv", [["--help"], ["write", "--help"], ["harness", "--help"], ["doctor"]])
def test_cli_help_and_doctor_run_with_legacy_imports_blocked(argv: list[str]) -> None:
    """依赖：真实CLI main/独立阻断进程。输入：帮助或doctor参数。输出：正常退出且未加载旧链。实现：实际解析执行原入口，不能只以模块导入成功替代。"""
    _import_probe(f'''
        import sys
        from novel_rag.cli import main
        sys.argv = ["novel-rag", *{argv!r}]
        try:
            assert main() == 0
        except SystemExit as exc:
            assert exc.code == 0
    ''', (*LEGACY_WRITER_MODULES, "novel_rag.composition", "fastapi", "uvicorn"))


@pytest.mark.parametrize("action", ["write", "harness"])
def test_actual_v3_entrypoints_run_with_legacy_imports_blocked(tmp_path: Path, action: str) -> None:
    """依赖：原CLI/Web与现有本地HTTP夹具。输入：临时库和write/harness路径。输出：真实内置完成或外部prepared及无旧链。实现：新进程先阻断旧模块，再执行原命令、服务和持久结果。"""
    setup = f'''
from pathlib import Path
import contextlib, io, json, sys
sys.path.insert(0, str(Path.cwd() / "tests"))
from writer_fixtures import make_library
from novel_rag.cli import build_parser
base = Path({str(tmp_path)!r})
root = make_library(base)
outline = base / "outline.txt"
outline.write_text("写一段雨夜交接。", encoding="utf-8")
config_path = base / "model.json"
'''
    if action == "write":
        script = '''
from http.server import ThreadingHTTPServer
from threading import Thread
from test_writer_cli import _LocalChatHandler
from novel_rag.model_config import ModelConfigStore
server = ThreadingHTTPServer(("127.0.0.1", 0), _LocalChatHandler)
thread = Thread(target=server.serve_forever, daemon=True)
thread.start()
try:
    config = ModelConfigStore(config_path)
    config.set_profile("fixture", base_url=f"http://127.0.0.1:{server.server_port}/v1",
                       model="fixture-writer", mode="chat", no_auth=True, timeout=10, retries=0)
    config.set_active("fixture")
    args = build_parser().parse_args(["--library", str(root), "--model-config", str(config_path),
        "write", "--story", "demo", "--outline-file", str(outline), "--workspace", str(base / "workspace")])
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        result = args.func(args)
    assert result == 0, output.getvalue()
    run = json.loads(output.getvalue())
    assert run["status"] == "completed" and run["draft_ref"] and run["draft_text"]
    assert _LocalChatHandler.requests
finally:
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)
    assert not thread.is_alive()
'''
    else:
        script = '''
from native_http_fixture import workspace_server
from novel_rag.web.app import create_app
config_path.write_text("{broken model config", encoding="utf-8")
app = create_app(root, base / "workspace", config_path)
with workspace_server(app) as backend:
    args = build_parser().parse_args(["harness", "prepare", "--backend", backend,
        "--story", "demo", "--outline-file", str(outline), "--request-id", "lazy-harness-prepare"])
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        result = args.func(args)
    assert result == 0, output.getvalue()
    prepared = json.loads(output.getvalue())
    assert prepared["context"]["status"] == "prepared"
    assert app.state.service.run_info(prepared["run_id"])["driver"] == "harness"
'''
    loaded = _import_probe(setup + script, LEGACY_WRITER_MODULES)
    assert "novel_rag.composition" in loaded
    # GraphRetriever remains the canonical graph service class at its existing owner.
    assert "novel_rag.retrieval.service" in loaded


@pytest.mark.parametrize(("package_name", "owners"), [
    ("novel_rag.cli", {
        ".arguments": ("build_parser",),
        ".helpers": ("_model_from_args", "_paths", "_add_model_arguments"),
        ".commands": ("command_validate", "command_index", "command_search", "command_list_stories",
            "command_create_story", "command_generate", "command_continue", "command_init_preferences",
            "command_confirm", "command_state_review", "command_state_approve", "command_state_reject",
            "command_import_rag", "command_import_outline", "command_feedback_create", "command_feedback_list",
            "command_feedback_resolve", "command_api_config", "command_tui", "command_doctor", "command_summary", "command_pending"),
    }),
    ("novel_rag.writeback", {
        ".types": ("WritebackError", "WritebackResult"),
        ".helpers": ("_atomic_text", "_read_json", "_retrieval_tests"),
        ".confirm": ("confirm_runtime",),
    }),
    ("novel_rag.retrieval", {
        ".assembler": ("BudgetExceeded", "ContextAssembler", "DEFAULT_CHANNEL_QUOTAS", "DEFAULT_TOKEN_BUDGET", "estimate_tokens"),
        ".conflicts": ("ConflictGuard", "detect_conflicts"), ".protocols": ("GraphReader", "Retriever"),
        ".service": ("EvidenceNormalizer", "HybridRetriever", "RetrievalAmbiguityError", "RetrievalConfigurationError",
            "RetrievalError", "RetrievalService", "RetrieverService", "ServiceRetriever"),
        ".types": ("ChannelStats", "ContextBundle", "ContextConflict", "Evidence", "EvidenceChannel", "RetrievalReceipt", "RetrievalRequest"),
    }),
])
def test_lazy_package_exports_keep_original_identity_and_discovery(package_name: str, owners: dict) -> None:
    """依赖：原公开/私有导出与实际owner。输入：历史导出清单。输出：相同对象、star/dir兼容及未知名错误。实现：显式核完整旧契约，不用生产登记表生成预期。"""
    import importlib

    package = importlib.import_module(package_name)
    expected = {name for names in owners.values() for name in names}
    if package_name == "novel_rag.cli":
        expected.add("main")
    assert set(package.__all__) == expected
    for owner, names in owners.items():
        implementation = importlib.import_module(owner, package_name)
        for name in names:
            assert name in dir(package)
            assert getattr(package, name) is getattr(implementation, name)
    namespace = {}
    exec(f"from {package_name} import *", namespace)
    assert set(namespace) - {"__builtins__"} == expected
    assert all(namespace[name] is getattr(package, name) for name in expected)
    with pytest.raises(AttributeError, match="no_such_export"):
        getattr(package, "no_such_export")


def test_generation_legacy_exports_still_resolve_to_original_implementations() -> None:
    """依赖：generation兼容导出与原v2模块。输入：原公开及私有导出。输出：同一对象和原调用结果。实现：核对惰性解析、star导入、错误类型及私有函数调用。"""

    import importlib

    import novel_rag.generation as generation

    owners = {
        "..generation_schema": ("GenerationResult",),
        ".types": ("DocumentRef", "DraftRef", "AuthorInputRef", "NarrativeCursor", "RunBinding", "GenerationError", "PreferenceRequired", "Model", "STAGE_INSTRUCTIONS"),
        ".helpers": ("author_preferences_path", "read_author_preferences", "build_contract", "retrieve_context_bundle", "retrieve_context", "build_reference_profiles", "load_scene_state", "execute_scene", "validate_draft", "_payload", "_safe_task_id"),
        ".retrieval": ("ContextItem", "LegacyRetrieverAdapter", "build_default_retriever", "build_legacy_retriever", "build_retrieval_request", "set_default_retriever_factory"),
        ".pipeline": ("generate",),
    }
    for owner, names in owners.items():
        implementation = importlib.import_module(owner, generation.__name__)
        for name in names:
            assert getattr(generation, name) is getattr(implementation, name)
            assert name in dir(generation)
    namespace: dict[str, object] = {}
    exec("from novel_rag.generation import *", namespace)
    assert set(namespace) - {"__builtins__"} == set(generation.__all__)
    assert namespace["generate"] is generation.generate
    from novel_rag.generation import _payload, _safe_task_id

    assert _payload({"text": "原文"}) == {"text": "原文"}
    assert _safe_task_id("chapter-1") == "chapter-1"
    with pytest.raises(AttributeError, match="no_such_export"):
        getattr(generation, "no_such_export")
