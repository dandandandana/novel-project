from __future__ import annotations

from contextlib import contextmanager
import json
import os
import re
import socket
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Iterator
from urllib.request import urlopen

import pytest
import uvicorn
from playwright.sync_api import Browser, Page, expect, sync_playwright

from native_http_fixture import NativeEndpoint, workspace_server
from novel_rag.documents import read_yaml_mapping
from novel_rag.identity import GraphKey
from novel_rag.model_config.store import ModelConfigStore
from novel_rag.service import load_story_sources
from novel_rag.web.app import create_app
from writer_fixtures import make_library, put_document, write_yaml

from test_writer_session import _text_response, _tool_response


def installed_browser_path(runtime=None) -> Path:
    """依赖：已安装Chrome/Edge或Playwright Chromium。
    输入：可选的已开启Playwright runtime。
    输出：浏览器路径；本地缺失跳过，CI缺失失败。
    实现：先查本机位置，再复用runtime或临时开启驱动查bundle；不下载浏览器。
    """
    candidates = (
        Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
        Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
    )
    for path in candidates:
        if path.is_file():
            return path
    if runtime is None:
        with sync_playwright() as started:
            browser_path = Path(started.chromium.executable_path)
    else:
        browser_path = Path(runtime.chromium.executable_path)
    if browser_path.is_file():
        return browser_path
    message = "缺少浏览器；请先安装Chrome/Edge或执行 python -m playwright install chromium。"
    if os.environ.get("CI", "").lower() in {"1", "true"}:
        pytest.fail(message)
    pytest.skip(message)


def test_browser_finder_reuses_active_runtime_without_nested_driver(tmp_path: Path, monkeypatch) -> None:
    """依赖：共同finder/已有runtime形状。输入：无系统浏览器但已安装bundle。输出：复用路径且不启动嵌套driver。实现：禁止sync_playwright入口，模拟Linux路径发现并核对返回。"""
    bundle = tmp_path / "chromium"
    runtime = SimpleNamespace(chromium=SimpleNamespace(executable_path=str(bundle)))
    monkeypatch.setattr(Path, "is_file", lambda path: path == bundle)

    def forbidden_start():
        """依赖：负例哨兵。输入：无。输出：断言失败。实现：已有runtime时任何新driver启动均失败。"""
        raise AssertionError("must reuse the active Playwright runtime")

    monkeypatch.setattr(sys.modules[__name__], "sync_playwright", forbidden_start)
    assert installed_browser_path(runtime) == bundle


def test_browser_finder_discovers_bundle_with_one_owned_driver(tmp_path: Path, monkeypatch) -> None:
    """依赖：共同finder/上下文夹具。输入：无系统浏览器的bundle路径。输出：返回路径且driver关闭。实现：记录临时driver进入退出，不下载或启动浏览器。"""
    bundle = tmp_path / "chromium"
    lifecycle = []
    monkeypatch.setattr(Path, "is_file", lambda path: path == bundle)

    @contextmanager
    def driver():
        """依赖：上下文协议。输入：无。输出：仅含bundle路径的runtime。实现：记录enter/exit检验finder释放自己开启的driver。"""
        lifecycle.append("enter")
        try:
            yield SimpleNamespace(chromium=SimpleNamespace(executable_path=str(bundle)))
        finally:
            lifecycle.append("exit")

    monkeypatch.setattr(sys.modules[__name__], "sync_playwright", driver)
    assert installed_browser_path() == bundle
    assert lifecycle == ["enter", "exit"]


@pytest.mark.parametrize("ci", ["true", ""])
def test_browser_finder_missing_browser_fails_ci_and_skips_locally(monkeypatch, ci: str) -> None:
    """依赖：共同finder/pytest结果类型。输入：无浏览器及CI标志。输出：CI失败、本地跳过。实现：隔离文件探测，防止CI因浏览器前置缺失报告伪绿。"""
    monkeypatch.setenv("CI", ci)
    monkeypatch.setattr(Path, "is_file", lambda path: False)
    runtime = SimpleNamespace(chromium=SimpleNamespace(executable_path="missing-browser"))
    expected = pytest.fail.Exception if ci else pytest.skip.Exception
    with pytest.raises(expected, match="缺少浏览器"):
        installed_browser_path(runtime)


def _open_tile(page: Page, action: str) -> None:
    """依赖：Metro首页的tile action、workspaceView和Playwright expect。
    输入：真实浏览器页面及配置中至少出现一次的tile action。
    输出：对应功能面板可见；找不到入口或面板时断言失败。
    实现：点击首个匹配配置按钮，兼容同一功能的多个tile入口，并等待工作区显示。
    """
    page.locator(f'.tile[data-action="{action}"]').first.click()
    expect(page.locator("#workspaceView")).to_be_visible()


def _return_home(page: Page) -> None:
    """依赖：Metro工作区的#homeButton和Playwright expect。
    输入：当前处于功能面板的浏览器页面。
    输出：首页重新可见。
    实现：点击真实返回按钮并等待launcherView显示。
    """
    page.locator("#homeButton").click()
    expect(page.locator("#launcherView")).to_be_visible()


def _assert_no_horizontal_overflow(page: Page) -> None:
    """依赖：真实浏览器布局尺寸。
    输入：已渲染的 Playwright 页面。
    输出：无横向溢出时返回，否则断言失败并显示页面与视口宽度。
    实现：比较 document/body scrollWidth 与当前 innerWidth。
    """
    dimensions = page.evaluate("""() => ({
      viewport: window.innerWidth,
      document: document.documentElement.scrollWidth,
      body: document.body.scrollWidth
    })""")
    assert dimensions["document"] <= dimensions["viewport"], dimensions
    assert dimensions["body"] <= dimensions["viewport"], dimensions


def _collect_page_error(errors: list[str]):
    """依赖：Playwright Page 的 pageerror 事件。
    输入：保存错误文本的列表。
    输出：可注册到页面的具名回调。
    实现：将浏览器未捕获异常转成字符串，供端到端测试最终断言。
    """
    def record(error) -> None:
        """依赖：Playwright 的页面异常对象和外层错误列表。
        输入：一个 pageerror。
        输出：无。
        实现：记录异常文本，不吞掉测试自身断言。
        """
        errors.append(str(error))

    return record


def test_browser_writes_edits_and_adopts_plain_text_over_real_uvicorn(tmp_path: Path) -> None:
    """验证真实浏览器编辑偏好和Canon，再从原文工具写稿并正式采用。

    依赖：实际 Chrome/Edge、Playwright、Uvicorn loopback、真实 Web/Run/Store 和资料编辑组件。
    输入：临时 YAML 作品、作者偏好、Canon、带 key 的 profile、原文读取工具和终稿。
    输出：偏好进入原生请求、Canon 原文可读、草稿修订和正式 History 文件。
    实现：浏览器展开本轮选项并操作资料，以公开URL定位HTTP/SSE持久草稿，完成创作与采用。
    """
    root = make_library(tmp_path)
    initial_text = "旧屋门口的石阶常年留着潮气。"
    put_document(root, "old-scene", initial_text, chapter=1, scene=1)
    preferences_path = root / "stories" / "demo" / "author-preferences.txt"
    preferences_path.write_text("【叙述】贴近主角感官，不替配角猜心。\n", encoding="utf-8")
    canon_original = "山路尽头有一座闲置的旧屋。"
    canon_updated = "山路尽头有一座闲置的旧屋，门内常年备着一盏油灯。"
    canon_path = put_document(root, "canon-lore", canon_original, category="canon")
    canon_doc = read_yaml_mapping(canon_path)
    canon_doc.pop("text", None)
    canon_doc["content"] = canon_original
    write_yaml(canon_path, canon_doc)
    saved_preferences = "【叙述】贴近主角感官，不替配角猜心。\n【对白】留出停顿和潜台词。\n"
    workspace, config_path = tmp_path / "workspace", tmp_path / "model-config.json"
    private_key = "browser-local-provider-secret"
    unsafe_text = ('第二章：门缝里透出一点暖光。 '
                   '<img src=x onerror="window.__novelExecuted=true">'
                   '<script>window.__novelExecuted=true</script>')
    calls = [
        {"call_id": "call-browser-read-original", "name": "read_document",
         "arguments": {"document_id": "old-scene"}},
        {"call_id": "call-browser-read-canon", "name": "read_document",
         "arguments": {"document_id": "canon-lore"}},
    ]

    with NativeEndpoint([
        {"mode": "chat", **_tool_response("chat", calls)},
        {"mode": "chat", **_text_response("chat", unsafe_text)},
    ]) as endpoint:
        assert endpoint.base_url is not None
        config = ModelConfigStore(config_path)
        config.set_profile("browser-fixture", {
            "base_url": endpoint.base_url, "model": "browser-fixture-model", "mode": "chat",
            "api_key": private_key, "no_auth": False, "timeout": 5, "retries": 0,
        })
        app = create_app(root, workspace, config_path)
        browser_path = installed_browser_path()
        page_errors: list[str] = []
        with workspace_server(app) as base_url, sync_playwright() as playwright:
            with urlopen(base_url + "/api/v1/bootstrap", timeout=2) as response:
                bootstrap = json.loads(response.read().decode("utf-8"))
            assert bootstrap["profiles"] == [{
                "name": "browser-fixture", "model": "browser-fixture-model", "mode": "chat",
            }]
            assert private_key not in json.dumps(bootstrap, ensure_ascii=False)
            browser: Browser | None = None
            try:
                browser = playwright.chromium.launch(headless=True, executable_path=str(browser_path))
                page = browser.new_page(viewport={"width": 1360, "height": 980}, device_scale_factor=1)
                page.on("pageerror", _collect_page_error(page_errors))
                page.goto(base_url + "/", wait_until="domcontentloaded")
                expect(page.locator("#runStatus")).to_have_text("已连接本地工作区")
                _open_tile(page, "workbench")
                expect(page.get_by_role("heading", name="写下这一段")).to_be_visible()
                expect(page.locator("#runStatus")).to_have_text("已连接本地工作区")
                expect(page.locator("#startButton")).to_be_enabled()

                page.locator("#writingOptions > summary").click()
                page.get_by_role("radio", name="创作").focus()
                page.keyboard.press("ArrowRight")
                expect(page.get_by_role("radio", name="修改")).to_be_checked()
                page.keyboard.press("ArrowRight")
                expect(page.get_by_role("radio", name="讨论")).to_be_checked()
                page.keyboard.press("ArrowLeft")
                expect(page.get_by_role("radio", name="修改")).to_be_checked()
                page.keyboard.press("ArrowLeft")
                expect(page.get_by_role("radio", name="创作")).to_be_checked()

                _return_home(page)
                _open_tile(page, "resources")
                expect(page.locator("#resourcesPanel")).to_be_visible()
                assert page.locator("#resourcesPanel").evaluate("element => element.open") is True
                expect(page.locator("#preferencesEditor")).to_have_value("【叙述】贴近主角感官，不替配角猜心。\n")
                page.locator("#preferencesEditor").fill(saved_preferences)
                page.get_by_role("button", name="保存偏好").click()
                expect(page.locator("#preferencesStatus")).to_have_text("偏好已保存。")
                assert preferences_path.read_text(encoding="utf-8") == saved_preferences

                page.locator("#documentSelect").select_option("canon-lore")
                expect(page.locator("#documentEditor")).to_be_visible()
                expect(page.locator("#documentEditor")).to_have_value(canon_original)
                page.locator("#documentEditor").fill(canon_updated)
                page.get_by_role("button", name="保存资料修改").click()
                expect(page.locator("#documentStatus")).to_have_text("资料已保存 · 修订 2")
                assert read_yaml_mapping(canon_path)["content"] == canon_updated
                canon_sources = load_story_sources(root, GraphKey("demo", "main"))
                edited_canon, edited_canon_ref = canon_sources.read("canon-lore")
                assert edited_canon.body["content"] == canon_updated
                assert edited_canon_ref.source_hash

                _return_home(page)
                _open_tile(page, "workbench")
                page.locator("#outlineInput").fill("第二章：沿山路找到旧屋，原文是参考。")
                page.get_by_label("本轮要求 / 修改反馈").fill("读取第一章原文后写出门缝里的灯光。")
                page.get_by_role("button", name="开始创作").click()
                expect(page.locator("#runStatus")).to_have_text("本轮已完成", timeout=15_000)
                expect(page.locator("#draftRevision")).to_have_text("草稿修订 1")
                expect(page.locator("#draftEditor")).to_have_value(unsafe_text)
                expect(page.locator("#toolLog")).to_contain_text("read_document · 开始")
                expect(page.locator("#toolLog")).to_contain_text("read_document · 完成")
                expect(page.locator("#livePreview")).to_contain_text("第二章：门缝里透出一点暖光。")
                assert page.evaluate("() => window.__novelExecuted") is None
                assert page.locator("#draftEditor img, #draftEditor script").count() == 0
                assert page.locator("#livePreview img, #livePreview script").count() == 0

                author_text = unsafe_text + "\n甲把地图折起来，决定先等雨停。"
                page.locator("#draftEditor").fill(author_text)
                page.get_by_role("button", name="保存草稿").click()
                expect(page.locator("#draftRevision")).to_have_text("草稿修订 2")
                expect(page.locator("#draftEditor")).to_have_value(author_text)

                page.get_by_label("卷").fill("1")
                page.get_by_label("章").fill("2")
                page.get_by_label("场").fill("1")
                page.get_by_role("button", name="采用正文").click()
                expect(page.locator("#runStatus")).to_have_text(
                    re.compile("^采用(请求已返回|结果待确认)$"), timeout=10_000,
                )
                adopted_run_id = page.evaluate("() => new URLSearchParams(window.location.search).get('run')")
                snapshot = app.state.service.store.load(adopted_run_id)
                if snapshot["adoption"] is None:
                    diagnostic = {
                        "run_status": page.locator("#runStatus").inner_text(),
                        "error_banner": page.locator("#errorBanner").inner_text(),
                        "draft_edit_state": page.locator("#draftEditState").inner_text(),
                        "draft_revision": snapshot["draft_revision"],
                        "adoption": snapshot["adoption"],
                    }
                    page.screenshot(path=str(tmp_path / "adoption-failure.png"), full_page=True)
                    (tmp_path / "adoption-failure.json").write_text(
                        json.dumps(diagnostic, ensure_ascii=False, indent=2), encoding="utf-8",
                    )
                    pytest.fail(f"草稿采用没有持久化结果；现场：{diagnostic}")
                assert snapshot["adoption"]["adopted"] is True
                expect(page.locator("#draftEditState")).to_have_text("正式作品已返回采用结果。")
                assert snapshot["draft_text"] == author_text
                adopted_path = (root / "stories" / "demo" / "timelines" / "main" / "history"
                                / "volume-01" / "chapter-02" / "scene-01.yaml")
                adopted_doc = read_yaml_mapping(adopted_path)
                assert adopted_doc["content"] == author_text
                assert adopted_doc["metadata"]["document_type"] == "history"
                adopted_id = adopted_doc["metadata"]["document_id"]
                reloaded_sources = load_story_sources(root, GraphKey("demo", "main"))
                assert adopted_id in reloaded_sources.source_refs
                assert reloaded_sources.source_refs[adopted_id].source_hash
                assert private_key not in page.locator("body").inner_text()
                assert page_errors == []

                page.set_viewport_size({"width": 1360, "height": 980})
                _assert_no_horizontal_overflow(page)
                page.set_viewport_size({"width": 390, "height": 844})
                _assert_no_horizontal_overflow(page)
                expect(page.locator("#draftEditor")).to_be_visible()
                page.set_viewport_size({"width": 1360, "height": 980})
                screenshot = Path(__file__).resolve().parents[1] / "output" / "playwright" / "v3-workspace.png"
                screenshot.parent.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(screenshot), full_page=True)
                assert screenshot.is_file() and screenshot.stat().st_size > 0
                assert endpoint.requests[0]["path"] == "/v1/chat/completions"
                assert private_key not in json.dumps(endpoint.requests[0]["body"], ensure_ascii=False)
                second_body = endpoint.requests[1]["body"]
                second_request = json.dumps(second_body, ensure_ascii=False)
                user_message = next(message for message in second_body["messages"] if message["role"] == "user")
                assembled_context = json.loads(user_message["content"])
                assert assembled_context["author_preferences"] == saved_preferences
                first_body = endpoint.requests[0]["body"]
                first_user_message = next(
                    message for message in first_body["messages"] if message["role"] == "user"
                )
                initial_context = json.loads(first_user_message["content"])
                selected_canon = [
                    reference for reference in initial_context.get("references", [])
                    if reference.get("document_id") == "canon-lore"
                ]
                for reference in selected_canon:
                    assert reference["source_ref"] == edited_canon_ref.as_dict()
                    if reference.get("text") is not None:
                        assert reference["text"] == canon_updated
                canon_tool_message = next(
                    message for message in second_body["messages"]
                    if message.get("role") == "tool"
                    and message.get("tool_call_id") == calls[1]["call_id"]
                )
                canon_tool_result = json.loads(canon_tool_message["content"])
                assert canon_tool_result["kind"] == "original"
                assert canon_tool_result["text"] == canon_updated
                assert canon_tool_result["source_ref"] == edited_canon_ref.as_dict()
                assert calls[0]["call_id"] in second_request
                assert calls[1]["call_id"] in second_request
                assert canon_updated in second_request
                assert initial_text in second_request
                assert endpoint.callback_errors == []
            finally:
                if browser is not None:
                    browser.close()


@pytest.mark.parametrize("response_order", ["natural", "late-cancel", "stale-live"])
def test_browser_recovers_partial_after_stop_and_continues_from_explicit_save(tmp_path: Path, response_order: str) -> None:
    """验证运行中停止后的真实部分输出恢复、显式保存及反馈续写。

    依赖：实际 Chrome/Edge、Playwright、Uvicorn loopback、RunService、DraftStore 与本地原生 endpoint。
    输入：首请求被 barrier 截断的 UTF-8 文本、HTTP回执到达顺序和后续完整终稿。
    输出：cancelled 父稿保留接收前缀，作者显式保存后新 run 只追加一次后缀。
    实现：浏览器真实启动和停止，安排延迟回执后核对终态，再刷新、保存部分稿并用同会话反馈续写。
    """
    root = make_library(tmp_path)
    workspace, config_path = tmp_path / "workspace", tmp_path / "model-config.json"
    partial_text = "门缝里透出一线灯光，"
    suffix = "雨声盖过脚步，甲把地图收进怀里。"
    release_stream, first_frame_sent = threading.Event(), threading.Event()
    first_response = {
        "mode": "chat",
        "frames": [{"choices": [{"index": 0, "delta": {"content": partial_text}}]}],
        "after_first": release_stream,
        "first_frame_sent": first_frame_sent,
    }
    page_errors: list[str] = []

    with NativeEndpoint([
        first_response,
        {"mode": "chat", **_text_response("chat", suffix)},
    ], barrier_timeout=6) as endpoint:
        assert endpoint.base_url is not None
        config = ModelConfigStore(config_path)
        config.set_profile("browser-fixture", {
            "base_url": endpoint.base_url, "model": "browser-fixture-model", "mode": "chat",
            "no_auth": True, "timeout": 5, "retries": 0,
        })
        app = create_app(root, workspace, config_path)
        browser_path = installed_browser_path()
        with workspace_server(app) as base_url, sync_playwright() as playwright:
            browser: Browser | None = None
            try:
                browser = playwright.chromium.launch(headless=True, executable_path=str(browser_path))
                page = browser.new_page(viewport={"width": 1360, "height": 980}, device_scale_factor=1)
                page.on("pageerror", _collect_page_error(page_errors))
                page.goto(base_url + "/", wait_until="domcontentloaded")
                _open_tile(page, "workbench")
                expect(page.locator("#runStatus")).to_have_text("已连接本地工作区")
                page.locator("#outlineInput").fill("第二章：门后的灯光引出一场短暂相遇。")
                page.get_by_label("本轮要求 / 修改反馈").fill("先写一段可继续的正文。")
                page.get_by_role("button", name="开始创作").click()

                assert first_frame_sent.wait(5), "本地 provider 没有发送首个文本帧"
                expect(page.locator("#livePreview")).to_contain_text(partial_text, timeout=5_000)
                first_run_id = page.evaluate("() => new URLSearchParams(window.location.search).get('run')")
                assert first_run_id
                expect(page.locator("#runStatus")).to_have_text("运行中")
                stop_button = page.get_by_role("button", name="停止本轮")
                if response_order == "natural":
                    stop_button.click()
                else:
                    cancel_url = f"**/api/v1/runs/{first_run_id}/cancel"
                    live_url = f"**/api/v1/runs/{first_run_id}?view=live&after=*"
                    held_cancel, held_live = [], []

                    def hold_cancel(route) -> None:
                        """依赖：Playwright真实route。输入：停止POST。输出：暂扣的请求。实现：测试控制真实提交后回执的到达次序。"""
                        held_cancel.append(route)
                        page.evaluate("() => { window.cancelRouteHeld = true; }")

                    def hold_live(route) -> None:
                        """依赖：Playwright真实route。输入：首个热观察GET。输出：暂扣的请求。实现：读取运行中状态后延迟交付。"""
                        if held_live:
                            route.continue_()
                            return
                        held_live.append(route)
                        page.evaluate("() => { window.liveRouteHeld = true; }")

                    if response_order == "stale-live":
                        page.route(live_url, hold_live)
                        page.evaluate("() => { void refreshRunSnapshot(workspace.runId); }")
                        page.wait_for_function("() => window.liveRouteHeld")
                        stale_live = held_live[0].fetch()
                        running = stale_live.json()
                    else:
                        running = page.evaluate("id => apiFetch(`/runs/${id}?view=live`)", first_run_id)
                    assert running["status"] == "running"
                    page.route(cancel_url, hold_cancel)
                    with page.expect_request(cancel_url):
                        stop_button.click()
                    page.wait_for_function("() => window.cancelRouteHeld")
                    cancel_response = held_cancel[0].fetch()
                    assert cancel_response.ok
                    if response_order == "stale-live":
                        page.wait_for_function("seq => workspace.lastEventSeq > seq", arg=running["event_seq"])
                        expect(page.locator("#runStatus")).to_have_text("本轮已停止", timeout=10_000)
                        held_live[0].fulfill(response=stale_live)
                        held_cancel[0].fulfill(response=cancel_response)
                        page.unroute(live_url, hold_live)
                    else:
                        expect(page.locator("#runStatus")).to_have_text("本轮已停止", timeout=10_000)
                        page.evaluate("""() => {
                            const original = applySnapshot;
                            applySnapshot = (snapshot, runId) => {
                                const result = original(snapshot, runId);
                                if (snapshot.status === "running" && snapshot.cancel_requested) window.staleCancelDelivered = true;
                                return result;
                            };
                        }""")
                        held_cancel[0].fulfill(response=cancel_response, json={**running, "cancel_requested": True})
                        page.wait_for_function("() => window.staleCancelDelivered")
                    page.unroute(cancel_url, hold_cancel)
                expect(page.locator("#runStatus")).to_have_text("本轮已停止", timeout=10_000)
                release_stream.set()

                cancelled = app.state.service.store.snapshot(first_run_id)
                assert cancelled["status"] == "cancelled"
                assert cancelled["draft_revision"] == 0
                assert cancelled["draft_text"] == ""
                assert cancelled["received_text"] == partial_text
                assert endpoint.wait_for_requests(1, timeout=1)

                page.reload(wait_until="domcontentloaded")
                expect(page.locator("#runStatus")).to_have_text("本轮已停止", timeout=10_000)
                expect(page.locator("#livePreview")).to_contain_text(partial_text)
                expect(page.locator("#draftRevision")).to_have_text("草稿修订 0")
                expect(page.locator("#draftEditor")).to_have_value("")
                expect(page.locator("#saveReceivedButton")).to_be_visible()
                expect(page.locator("#saveReceivedButton")).to_be_enabled()
                page.get_by_role("button", name="保存已接收的部分文本").click()
                expect(page.locator("#draftRevision")).to_have_text("草稿修订 1")
                if page.locator("#draftEditor").input_value() != partial_text:
                    partial_snapshot = app.state.service.store.load(first_run_id)
                    diagnostic = {
                        "run_status": page.locator("#runStatus").inner_text(),
                        "draft_edit_state": page.locator("#draftEditState").inner_text(),
                        "editor_text": page.locator("#draftEditor").input_value(),
                        "draft_revision": partial_snapshot["draft_revision"],
                        "draft_text": partial_snapshot["draft_text"],
                        "author_revision": partial_snapshot["author_revision"],
                    }
                    page.screenshot(path=str(tmp_path / "partial-save-failure.png"), full_page=True)
                    (tmp_path / "partial-save-failure.json").write_text(
                        json.dumps(diagnostic, ensure_ascii=False, indent=2), encoding="utf-8",
                    )
                    pytest.fail(f"显式保存后编辑器没有显示所选partial；现场：{diagnostic}")
                expect(page.locator("#draftEditor")).to_have_value(partial_text)

                saved_parent = app.state.service.store.load(first_run_id)
                assert saved_parent["draft_text"] == partial_text
                partial_checkpoint = next(
                    item for item in saved_parent["drafts"].values()
                    if item["ref"]["draft_revision"] == 1
                )
                assert partial_checkpoint["origin"] == "partial"
                assert saved_parent["author_revision"] == 1
                page.get_by_label("本轮要求 / 修改反馈").fill("从已选定的部分正文继续，不要重写前缀。")
                page.get_by_role("button", name="继续父稿 / 提交反馈").click()
                expect(page.locator("#runStatus")).to_have_text("本轮已完成", timeout=15_000)

                child_run_id = page.evaluate("() => new URLSearchParams(window.location.search).get('run')")
                assert child_run_id and child_run_id != first_run_id
                child = app.state.service.store.load(child_run_id)
                assert child["binding"]["output_mode"] == "append_suffix"
                assert child["draft_text"] == partial_text + suffix
                assert child["draft_text"].count(partial_text) == 1
                assert app.state.service.store.load(first_run_id)["status"] == "cancelled"
                assert partial_text in json.dumps(endpoint.requests[1]["body"], ensure_ascii=False)
                assert len(endpoint.requests) == 2
                assert endpoint.callback_errors == []
                assert page_errors == []
            finally:
                release_stream.set()
                if browser is not None:
                    browser.close()


def test_browser_preserves_author_edit_when_late_generation_finishes_once(tmp_path: Path) -> None:
    """验证模型迟到终稿只保留为独立生成稿，且快速重复提交只创建一次运行。

    依赖：实际 Chrome/Edge、Playwright、Uvicorn loopback、真实 Web/Run/Store 与本地原生 endpoint。
    输入：重复点击启动、先到的文本帧、作者编辑及 barrier 后到达的完整模型正文。
    输出：作者正文保持选中，晚到生成稿独立可读，session 只登记一个 run。
    实现：浏览器并发提交并在生成中保存作者版本，以公开URL定位run，再放行终稿核对双稿状态与只读面板。
    """
    root = make_library(tmp_path)
    workspace, config_path = tmp_path / "workspace", tmp_path / "model-config.json"
    author_text = "作者先保存的正文：门没有打开，灯光却留在门槛上。"
    generated_text = "模型迟到的完整稿：门缝里透出灯火。<script>window.__lateScript=true</script>"
    release_stream, first_frame_sent = threading.Event(), threading.Event()
    response = {
        "mode": "chat",
        "frames": [
            {"choices": [{"index": 0, "delta": {"content": "模型先收到的片段。"}}]},
            {"choices": [{"index": 0, "delta": {"content": generated_text}}]},
            {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
            "[DONE]",
        ],
        "after_first": release_stream,
        "first_frame_sent": first_frame_sent,
    }
    page_errors: list[str] = []

    with NativeEndpoint([response], barrier_timeout=6) as endpoint:
        assert endpoint.base_url is not None
        config = ModelConfigStore(config_path)
        config.set_profile("browser-fixture", {
            "base_url": endpoint.base_url, "model": "browser-fixture-model", "mode": "chat",
            "no_auth": True, "timeout": 5, "retries": 0,
        })
        app = create_app(root, workspace, config_path)
        browser_path = installed_browser_path()
        with workspace_server(app) as base_url, sync_playwright() as playwright:
            browser: Browser | None = None
            try:
                browser = playwright.chromium.launch(headless=True, executable_path=str(browser_path))
                page = browser.new_page(viewport={"width": 1360, "height": 980}, device_scale_factor=1)
                page.on("pageerror", _collect_page_error(page_errors))
                page.goto(base_url + "/", wait_until="domcontentloaded")
                _open_tile(page, "workbench")
                expect(page.locator("#runStatus")).to_have_text("已连接本地工作区")
                page.locator("#outlineInput").fill("第三章：门外的人决定等到雨停。")
                page.get_by_label("本轮要求 / 修改反馈").fill("继续写出门内外的迟疑。")
                page.get_by_role("button", name="开始创作").dblclick(delay=0)

                assert first_frame_sent.wait(5), "本地 provider 没有发送首个文本帧"
                expect(page.locator("#livePreview")).to_contain_text("模型先收到的片段。", timeout=5_000)
                page.locator("#draftEditor").fill(author_text)
                page.get_by_role("button", name="保存草稿").click()
                expect(page.locator("#draftRevision")).to_have_text("草稿修订 1")
                assert app.state.service.store.load(
                    page.evaluate("() => new URLSearchParams(window.location.search).get('run')")
                )["draft_text"] == author_text

                release_stream.set()
                expect(page.locator("#runStatus")).to_have_text("本轮已完成", timeout=15_000)
                run_id = page.evaluate("() => new URLSearchParams(window.location.search).get('run')")
                saved = app.state.service.store.load(run_id)
                assert saved["draft_text"] == author_text
                assert saved["author_revision"] == 1
                assert saved["generated_draft_text"] == "模型先收到的片段。" + generated_text
                assert saved["generated_draft_ref"]["draft_revision"] == 2
                assert endpoint.wait_for_requests(1, timeout=1)
                session_path = workspace / "demo" / "main" / "sessions" / saved["session_id"] / "session.json"
                session = json.loads(session_path.read_text(encoding="utf-8"))
                assert session["run_ids"] == [run_id]

                expect(page.locator("#generatedDraftButton")).to_be_visible()
                page.get_by_role("button", name="查看保留的生成稿").click()
                expect(page.locator("#generatedDraftPanel")).to_be_visible()
                expect(page.locator("#generatedDraftPreview")).to_have_text(saved["generated_draft_text"])
                expect(page.locator("#draftEditor")).to_have_value(author_text)
                assert page.locator("#generatedDraftPreview script").count() == 0
                assert page.evaluate("() => window.__lateScript") is None
                page.set_viewport_size({"width": 1360, "height": 980})
                _assert_no_horizontal_overflow(page)
                page.set_viewport_size({"width": 390, "height": 844})
                _assert_no_horizontal_overflow(page)
                expect(page.locator("#draftEditor")).to_be_visible()
                assert len(endpoint.requests) == 1
                assert endpoint.callback_errors == []
                assert page_errors == []
            finally:
                release_stream.set()
                if browser is not None:
                    browser.close()
