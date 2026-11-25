"""作品创建的磁盘故障、并发和真实 HTTP 回归；只使用 pytest 临时库。"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from http.client import HTTPConnection
import json
from pathlib import Path
import re
import threading
from typing import Any
from urllib.parse import urlsplit

import pytest
import yaml

from native_http_fixture import workspace_server
from novel_rag import scaffold
from novel_rag.documents import read_yaml_mapping
from novel_rag.mutations import MutationLockError
from novel_rag.web.app import create_app
from writer_fixtures import make_library, write_yaml


def _http_json(
    base_url: str,
    path: str,
    *,
    method: str = "GET",
    token: str | None = None,
    value: Any = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, Any]:
    """依赖：HTTPConnection/JSON及真实workspace_server。输入：URL/方法/可选token和正文。
    输出：HTTP状态与JSON；网络错误直接失败。实现：不强制提前关闭连接，完整读取响应后释放，不重试请求。
    """
    request_headers = dict(headers or {})
    body = None if value is None else json.dumps(value, ensure_ascii=False).encode("utf-8")
    if token is not None:
        request_headers["X-Workspace-Token"] = token
    if body is not None:
        request_headers["Content-Type"] = "application/json"
    address = urlsplit(base_url)
    connection = HTTPConnection(address.hostname, address.port, timeout=5)
    try:
        connection.request(method, path, body=body, headers=request_headers)
        response = connection.getresponse()
        return response.status, json.loads(response.read().decode("utf-8"))
    finally:
        connection.close()


def test_same_story_intent_recovers_without_registering_or_rewriting_twice(tmp_path: Path) -> None:
    """依赖：create_story/临时v2库。输入：相同ID/标题/继承意图与作者文件。
    输出：显式重试返回原根且字节不变，默认重复拒绝。实现：重读注册表及作者文件。
    """
    library = make_library(tmp_path)
    created = scaffold.create_story(library, story_id="new-book", title="新书", inherit_shared=False)
    author_file = created / "timelines" / "main" / "history" / "author-note.txt"
    author_file.write_text("作者后来写入的正文，不能重建覆盖。", encoding="utf-8")
    catalog = library / "registry" / "stories.yaml"
    committed_bytes = catalog.read_bytes()

    with pytest.raises(FileExistsError):
        scaffold.create_story(library, story_id="new-book", title="新书", inherit_shared=False)
    recovered = scaffold.create_story(
        library, story_id="new-book", title="新书", inherit_shared=False, exist_ok=True,
    )

    assert recovered == created
    assert catalog.read_bytes() == committed_bytes
    assert author_file.read_text(encoding="utf-8") == "作者后来写入的正文，不能重建覆盖。"
    rows = read_yaml_mapping(catalog)["stories"]
    assert [row["story_id"] for row in rows] == ["demo", "other", "new-book"]
    assert rows[-1]["inherit_shared"] is False


@pytest.mark.parametrize("changed_intent", [{"title": "不同书名"}, {"inherit_shared": True}])
def test_existing_story_rejects_changed_creation_intent(
    tmp_path: Path, changed_intent: dict[str, Any],
) -> None:
    """依赖：create_story/真实目录。输入：已注册书和改变的标题或继承意图。
    输出：FileExistsError且原目录/表不变。实现：同ID重试并回读保存字节。
    """
    library = make_library(tmp_path)
    created = scaffold.create_story(library, story_id="new-book", title="新书", inherit_shared=False)
    catalog = library / "registry" / "stories.yaml"
    before = catalog.read_bytes()
    module_map = created / "timelines" / "main" / "registry" / "module-map.yaml"
    modules_before = module_map.read_bytes()
    arguments = {"story_id": "new-book", "title": "新书", "inherit_shared": False, "exist_ok": True}
    arguments.update(changed_intent)

    with pytest.raises(FileExistsError):
        scaffold.create_story(library, **arguments)

    assert catalog.read_bytes() == before
    assert module_map.read_bytes() == modules_before


def test_registration_write_failure_removes_only_this_unregistered_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """依赖：原子保存/monkeypatch/临时库。输入：注册提交前IO故障。
    输出：原表/旧书保留，新树清理后能重试。实现：仅对注册表的原子写注入故障。
    """
    library = make_library(tmp_path)
    catalog = library / "registry" / "stories.yaml"
    before = catalog.read_bytes()
    existing = library / "stories" / "demo" / "common" / "canon" / "author.txt"
    existing.write_bytes(b"existing author content")
    atomic_save = scaffold.atomic_write_bytes

    def fail_before_registration(path: Path, value: bytes) -> None:
        """依赖：原atomic_write_bytes。输入：目标/字节。输出：None或受控IO错误。
        实现：注册表提交前失败，其余建树文件仍走真实原子保存。
        """
        if Path(path) == catalog:
            raise OSError("fixture: registration not committed")
        atomic_save(path, value)

    with monkeypatch.context() as fault:
        fault.setattr(scaffold, "atomic_write_bytes", fail_before_registration)
        with pytest.raises(OSError, match="registration not committed"):
            scaffold.create_story(library, story_id="new-book", title="新书", inherit_shared=False)

    assert catalog.read_bytes() == before
    assert existing.read_bytes() == b"existing author content"
    assert not (library / "stories" / "new-book").exists()
    assert not (library / ".novel-rag" / "mutation.lock").exists()
    assert scaffold.create_story(
        library, story_id="new-book", title="新书", inherit_shared=False, exist_ok=True,
    ).is_dir()


def test_error_after_registration_commit_preserves_registered_tree_and_recovers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """依赖：真实原子保存/故障注入。输入：注册已落盘但回执前抛IO错误。
    输出：注册树保留，同意图重试不重复。实现：先真实写表再抛错并重读磁盘。
    """
    library = make_library(tmp_path)
    catalog = library / "registry" / "stories.yaml"
    atomic_save = scaffold.atomic_write_bytes

    def fail_after_registration(path: Path, value: bytes) -> None:
        """依赖：原atomic_write_bytes。输入：目标/字节。输出：None或受控IO错误。
        实现：注册表真实提交成功后模拟回执错误，其他文件正常写入。
        """
        atomic_save(path, value)
        if Path(path) == catalog:
            raise OSError("fixture: registration committed before response loss")

    with monkeypatch.context() as fault:
        fault.setattr(scaffold, "atomic_write_bytes", fail_after_registration)
        with pytest.raises(OSError, match="registration committed"):
            scaffold.create_story(library, story_id="new-book", title="新书", inherit_shared=False)

    created = library / "stories" / "new-book"
    assert created.is_dir()
    assert (created / "common" / "registry" / "timelines.yaml").is_file()
    assert (created / "timelines" / "main" / "registry" / "module-map.yaml").is_file()
    committed_bytes = catalog.read_bytes()
    assert scaffold.create_story(
        library, story_id="new-book", title="新书", inherit_shared=False, exist_ok=True,
    ) == created
    assert catalog.read_bytes() == committed_bytes
    assert [row["story_id"] for row in read_yaml_mapping(catalog)["stories"]].count("new-book") == 1


@pytest.mark.parametrize("broken_catalog", [
    b"- unexpected-envelope\n",
    b"stories: not-a-list\n",
    b"stories:\n  - not-a-row\n",
    b"stories: [\n",
])
def test_bad_catalog_is_preserved_and_never_replaced_by_new_story(
    tmp_path: Path, broken_catalog: bytes,
) -> None:
    """依赖：create_story/YAML校验。输入：顶层、列表、行或语法损坏的注册表。
    输出：显式失败且原字节保留，无新树。实现：写故障夹具并检查拒绝后的磁盘。
    """
    library = make_library(tmp_path)
    catalog = library / "registry" / "stories.yaml"
    catalog.write_bytes(broken_catalog)

    with pytest.raises((ValueError, yaml.YAMLError)):
        scaffold.create_story(library, story_id="new-book", title="新书", exist_ok=True)

    assert catalog.read_bytes() == broken_catalog
    assert not (library / "stories" / "new-book").exists()
    assert (library / "stories" / "demo").is_dir()
    assert not (library / ".novel-rag" / "mutation.lock").exists()


def test_unregistered_crash_residue_is_kept_for_inspection(tmp_path: Path) -> None:
    """依赖：create_story/临时目录。输入：已有未注册目录和残留正文。
    输出：拒绝新建并保留残留及原表。实现：模拟崩溃后的磁盘形状再显式重试。
    """
    library = make_library(tmp_path)
    residue = library / "stories" / "new-book"
    residue.mkdir()
    recovered_text = residue / "unregistered-draft.txt"
    recovered_text.write_bytes(b"recovery evidence must remain")
    catalog = library / "registry" / "stories.yaml"
    before = catalog.read_bytes()

    with pytest.raises(FileExistsError):
        scaffold.create_story(library, story_id="new-book", title="新书", exist_ok=True)

    assert recovered_text.read_bytes() == b"recovery evidence must remain"
    assert catalog.read_bytes() == before


@pytest.mark.parametrize("linked_part", ["story", "stories", "registry", "lock"])
def test_creation_rejects_paths_linked_outside_library(
    tmp_path: Path, linked_part: str,
) -> None:
    """依赖：Path符号链接/create_story。输入：作品、父目录、注册或锁目录的外链。
    输出：scope_denied且外部文件不变；平台禁止链接时skip。实现：临时外链后执行创建。
    """
    library = make_library(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "foreign.txt"
    sentinel.write_bytes(b"outside content must remain")
    if linked_part == "story":
        linked_path = library / "stories" / "new-book"
    elif linked_part == "lock":
        linked_path = library / ".novel-rag"
    else:
        linked_path = library / linked_part
        linked_path.rename(library / f"{linked_part}-original")
    try:
        linked_path.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError) as error:
        pytest.skip(f"平台不允许目录符号链接: {type(error).__name__}")

    with pytest.raises(ValueError, match="scope_denied"):
        scaffold.create_story(library, story_id="new-book", title="新书", exist_ok=True)

    assert sentinel.read_bytes() == b"outside content must remain"
    assert sorted(path.name for path in outside.iterdir()) == ["foreign.txt"]
    assert linked_path.is_symlink()


def test_library_lock_contention_is_explicit_and_retry_keeps_both_books(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """依赖：线程Event/create_story/真实库锁。输入：首建树持锁时的第二本创建。
    输出：第二次明确锁错误，释放后重试保留两书。实现：受控屏障串联真实注册提交。
    """
    library = make_library(tmp_path)
    first_tree_ready = threading.Event()
    allow_first_commit = threading.Event()
    build_tree = scaffold._build_story_tree

    def hold_first_tree(
        library_root: Path, story_root: Path, story_id: str, timeline_id: str,
        timeline_name: str, inherit_shared: bool,
    ) -> None:
        """依赖：原建树/Event。输入：原建树参数。输出：None或屏障超时。
        实现：真实建立第一树后持锁等待，第二树正常建立。
        """
        build_tree(library_root, story_root, story_id, timeline_id, timeline_name, inherit_shared)
        if story_id == "first-book":
            first_tree_ready.set()
            if not allow_first_commit.wait(5):
                raise TimeoutError("fixture: first registration barrier timed out")

    monkeypatch.setattr(scaffold, "_build_story_tree", hold_first_tree)
    with ThreadPoolExecutor(max_workers=1) as executor:
        first = executor.submit(
            scaffold.create_story, library, story_id="first-book", title="第一本", inherit_shared=False,
        )
        try:
            assert first_tree_ready.wait(5), "第一本应在注册前实际持有库锁"
            with pytest.raises(MutationLockError, match="锁已被占用"):
                scaffold.create_story(library, story_id="second-book", title="第二本", inherit_shared=False)
            assert not (library / "stories" / "second-book").exists()
        finally:
            allow_first_commit.set()
        assert first.result(timeout=5).is_dir()

    assert scaffold.create_story(
        library, story_id="second-book", title="第二本", inherit_shared=False, exist_ok=True,
    ).is_dir()
    assert [row["story_id"] for row in read_yaml_mapping(library / "registry" / "stories.yaml")["stories"]] == [
        "demo", "other", "first-book", "second-book",
    ]
    assert not (library / ".novel-rag" / "mutation.lock").exists()


def test_real_http_create_enforces_local_token_and_builds_profile_free_story(tmp_path: Path) -> None:
    """依赖：真实workspace_server/urllib/scaffold。输入：空目录表、零profile和授权边界。
    输出：未授权不写，授权创建可重试且harness准备可用。实现：真HTTP并回读原库及run。
    """
    library = make_library(tmp_path)
    catalog = write_yaml(library / "registry" / "stories.yaml", {"stories": []})
    write_yaml(library / "shared" / "registry" / "module-defaults.yaml", {
        "modules": [{"module_type": "style-audit", "active_versions": ["legacy-audit"]}],
    })
    config = tmp_path / "model-config.json"
    app = create_app(library, tmp_path / "workspace", config)
    before = catalog.read_bytes()
    intended = {"story_id": "new-book", "title": "新的故事"}

    with workspace_server(app) as base_url:
        status, bootstrap = _http_json(base_url, "/api/v1/bootstrap")
        assert status == 200
        assert bootstrap["stories"] == []
        assert bootstrap["profiles"] == []
        token = bootstrap["token"]
        for request_token, headers in [
            (None, {}),
            ("wrong-token", {}),
            (token, {"Origin": "https://foreign.example"}),
            (token, {"Host": "foreign.example"}),
        ]:
            status, denied = _http_json(
                base_url, "/api/v1/stories", method="POST", token=request_token,
                headers=headers, value=intended,
            )
            assert status == 403
            assert denied["error"]["code"] == "scope_denied"
            assert catalog.read_bytes() == before
            assert not (library / "stories" / "new-book").exists()

        status, created = _http_json(
            base_url, "/api/v1/stories", method="POST", token=token, value=intended,
        )
        assert status == 200
        assert set(created) == {"story_id", "title", "timelines"}
        assert created["story_id"] == "new-book" and created["title"] == "新的故事"
        assert created["timelines"][0]["timeline_id"] == "main"
        public_json = json.dumps(created, ensure_ascii=False)
        assert str(library) not in public_json and str(tmp_path / "workspace") not in public_json
        assert token not in public_json
        assert read_yaml_mapping(
            library / "stories" / "new-book" / "timelines" / "main" / "registry" / "module-map.yaml",
        ) == {"modules": []}
        committed_bytes = catalog.read_bytes()
        status, retried = _http_json(
            base_url, "/api/v1/stories", method="POST", token=token, value=intended,
        )
        assert status == 200 and retried == created
        assert catalog.read_bytes() == committed_bytes
        status, conflict = _http_json(
            base_url, "/api/v1/stories", method="POST", token=token,
            value={"story_id": "new-book", "title": "另一种意图"},
        )
        assert status in {400, 409} and conflict["error"]["message"]
        assert catalog.read_bytes() == committed_bytes
        status, prepared = _http_json(
            base_url, "/api/v1/runs", method="POST", token=token,
            value={"story_id": "new-book", "timeline_id": "main", "driver": "harness",
                   "outline": "开始新故事。", "request": "准备交接。", "request_id": "new-book-first-run"},
        )
        assert status == 200
        run = app.state.service.store.load(prepared["run_id"])
        assert run["status"] == "prepared" and run["driver"] == "harness"
        assert run["profile_name"] is None
        assert run["binding"]["scope"] == {"story_id": "new-book", "timeline_id": "main"}
        assert not config.exists()


@pytest.mark.parametrize("invalid_body", [
    ["new-book", "title"],
    {"story_id": "new-book"},
    {"story_id": "new-book", "title": ""},
    {"story_id": "../outside", "title": "非法路径"},
    {"story_id": "new-book", "title": "新书", "inherit_shared": True},
    {"story_id": "new-book", "title": "新书", "api_key": "fixture-key-never-echo"},
])
def test_http_story_creation_whitelist_rejects_invalid_input_without_writes(
    tmp_path: Path, invalid_body: Any,
) -> None:
    """依赖：真实workspace_server/输入白名单。输入：缺项、额外字段、坏路径或坏类型。
    输出：400且注册表/原目录不变、敏感额外值不回显。实现：真HTTP拒绝后核对磁盘。
    """
    library = make_library(tmp_path)
    catalog = library / "registry" / "stories.yaml"
    before = catalog.read_bytes()
    app = create_app(library, tmp_path / "workspace", tmp_path / "model-config.json")
    with workspace_server(app) as base_url:
        _, bootstrap = _http_json(base_url, "/api/v1/bootstrap")
        status, rejected = _http_json(
            base_url, "/api/v1/stories", method="POST", token=bootstrap["token"], value=invalid_body,
        )
        assert status == 400
        assert rejected["error"]["code"] == "source_invalid"
        assert "fixture-key-never-echo" not in json.dumps(rejected)
        assert catalog.read_bytes() == before
        assert sorted(path.name for path in (library / "stories").iterdir()) == ["demo", "other"]


@pytest.mark.parametrize("parent_swap", [True, False])
def test_cleanup_preserves_foreign_tree_when_created_directory_is_replaced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, parent_swap: bool,
) -> None:
    """依赖：真实建树/Path移动或symlink/原异常清理。输入：创建后父路径或叶目录被替换。
    输出：第三方标记和本次原树保留、原注册不变。实现：仅移动已核对归属的pytest临时目录，模拟换路径后建树失败。
    """
    library = make_library(tmp_path)
    catalog = library / "registry" / "stories.yaml"
    original_catalog = catalog.read_bytes()
    stories = library / "stories"
    owned_copy = library / ("preserved-stories" if parent_swap else "preserved-new-book")
    foreign = (tmp_path / "outside" if parent_swap else library / "foreign") / "new-book"
    foreign.mkdir(parents=True)
    marker = foreign / "foreign-marker.txt"
    marker.write_text("third-party-content", encoding="utf-8")
    for path in (stories, owned_copy, foreign):
        path.resolve().relative_to(tmp_path.resolve())

    def replace_created_path(library_root, root, story_id, timeline_id, timeline_name, inherit_shared) -> None:
        """依赖：测试独占的已解析路径。输入：原建树参数。输出：OSError。实现：先核临时范围，保留本次目录后换成不同目标，触发原清理流程。"""
        root.resolve().relative_to(tmp_path.resolve())
        if parent_swap:
            stories.rename(owned_copy)
            try:
                stories.symlink_to(foreign.parent, target_is_directory=True)
            except OSError as exc:
                pytest.skip(f"当前环境不能创建目录symlink: {exc}")
        else:
            root.rename(owned_copy)
            foreign.rename(root)
        raise OSError("boundary-change-during-build")

    monkeypatch.setattr(scaffold, "_build_story_tree", replace_created_path)
    with pytest.raises(OSError, match="boundary-change-during-build"):
        scaffold.create_story(library, story_id="new-book", title="新作品", inherit_shared=False)
    preserved_marker = marker if parent_swap else stories / "new-book" / marker.name
    assert preserved_marker.read_text(encoding="utf-8") == "third-party-content"
    assert (owned_copy / "new-book" if parent_swap else owned_copy).is_dir()
    assert catalog.read_bytes() == original_catalog


def test_workspace_id_is_opaque_stable_on_restart_and_isolates_library_and_store(tmp_path: Path) -> None:
    """依赖：真实bootstrap/同一组合根。输入：重启、换模型配置路径、换库或工作根。
    输出：同库工作根身份稳定、跨库/根隔离且无路径token。实现：串行启动实际HTTP服务核对。
    """
    library = make_library(tmp_path / "first")
    other_library = make_library(tmp_path / "second")
    workspace = tmp_path / "workspace"
    identities = []
    tokens = []
    for root, store_root, config_path in [
        (library, workspace, tmp_path / "model-config.json"),
        (library, workspace, tmp_path / "another-model-config.json"),
        (library, tmp_path / "other-workspace", tmp_path / "model-config.json"),
        (other_library, workspace, tmp_path / "model-config.json"),
    ]:
        app = create_app(root, store_root, config_path)
        with workspace_server(app) as base_url:
            status, bootstrap = _http_json(base_url, "/api/v1/bootstrap")
            assert status == 200
            identity = bootstrap["workspace_id"]
            assert isinstance(identity, str) and re.fullmatch(r"(?:[A-Za-z0-9_-]+:)?[A-Za-z0-9_-]{16,}", identity)
            assert str(root) not in identity and str(store_root) not in identity
            assert bootstrap["token"] not in identity
            public_json = json.dumps(bootstrap, ensure_ascii=False)
            assert str(root) not in public_json and str(store_root) not in public_json
            identities.append(identity)
            tokens.append(bootstrap["token"])
            assert not config_path.exists()
    assert identities[0] == identities[1]
    assert len(set(identities)) == 3
    assert tokens[0] != tokens[1]
