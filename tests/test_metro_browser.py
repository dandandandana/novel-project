from __future__ import annotations

import asyncio
import json
import re
import socket as stdlib_socket
import threading
from pathlib import Path
from importlib.resources import files
from types import SimpleNamespace
from urllib.request import urlopen

import pytest

import native_http_fixture as fixture_module
from native_http_fixture import workspace_server
from novel_rag.documents import read_yaml_mapping
from novel_rag.web.app import create_app
from writer_fixtures import make_library, put_document, write_yaml
from test_workspace_browser import installed_browser_path


_ACTIONS = {
    "workbench": "#write",
    "overview": "#about",
    "resources": "#resources",
    "memory": "#memory",
    "harness": "#write",
    "activity": "#activity",
    "settings": "#settings",
    "about": "#about",
    "placeholder": "#placeholder",
    "outline": "#write",
    "preferences": "#resources",
}


def test_resource_requests_follow_panel_and_scope_without_losing_edits(tmp_path: Path) -> None:
    """依赖：本机Chrome、真实资料API和暂扣响应。输入：首页、前进后退及两本书。
    输出：进入面板才读取，迟到响应不串作品或资料，恢复原编辑及保存版本。实现：控制实际请求回执到达顺序，再用外部编辑触发保存冲突。
    """
    runtime = pytest.importorskip("playwright.sync_api")
    root = make_library(tmp_path)
    put_document(root, "before", "前一章。")
    canon_path = put_document(root, "keep", "钥匙归还要求。", category="canon")
    canon = read_yaml_mapping(canon_path)
    canon["content"] = canon.pop("text")
    write_yaml(canon_path, canon)
    put_document(root, "other-only", "另一部作品。", story="other")
    app = create_app(root, tmp_path / "workspace", tmp_path / "model-config.json")
    with workspace_server(app) as base_url, runtime.sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=str(installed_browser_path(playwright)))
        try:
            page = browser.new_page(viewport={"width": 1366, "height": 768})
            requests = []

            def track_resources(request) -> None:
                """依赖：浏览器事件。输入：实际HTTP请求。输出：资源请求记录。实现：只匹配偏好及资料API。"""
                if "/api/v1/preferences/" in request.url or "/api/v1/documents" in request.url:
                    requests.append(request.url)

            page.on("request", track_resources)
            page.goto(base_url + "/", wait_until="domcontentloaded")
            runtime.expect(page.locator("#runStatus")).to_have_text("已连接本地工作区")
            runtime.expect(page.locator('.tile[data-tile="resources"]')).to_be_visible()
            assert requests == []

            page.locator('.tile[data-tile="resources"]').click()
            runtime.expect(page.locator("#preferencesEditor")).to_be_enabled()
            runtime.expect(page.locator("#reloadDocumentsButton")).to_be_enabled()
            assert len(requests) == 3
            page.go_back()
            runtime.expect(page.locator("#launcherView")).to_be_visible()
            page.go_forward()
            runtime.expect(page.locator("#documentSelect")).to_be_enabled()
            assert len(requests) == 3

            page.locator("#documentSelect").select_option("keep")
            runtime.expect(page.locator("#documentEditor")).to_have_value("钥匙归还要求。")
            page.locator("#documentEditor").fill("尚未保存的钥匙资料。")
            page.locator("#preferencesEditor").fill("尚未保存的作者偏好。")
            held = []

            def hold_old_list(route) -> None:
                """依赖：真实资料API。输入：原书列表请求。输出：暂扣真实响应。实现：切书后交付原始字节。"""
                held.append((route, route.fetch()))

            old_list = "**/api/v1/documents?story_id=demo&timeline_id=main"
            page.route(old_list, hold_old_list)
            with page.expect_request(old_list):
                page.locator("#reloadDocumentsButton").click()
            runtime.expect(page.locator("#documentStatus")).to_contain_text("正在读取")
            runtime.expect(page.locator("#reloadDocumentsButton")).to_be_disabled()
            page.locator("#homeButton").click()
            page.locator('.tile[data-tile="workbench"]').click()
            page.locator("#storySelect").select_option("other")
            runtime.expect(page.locator("#storySelect")).to_have_value("other")
            assert not any("story_id=other" in url or "/preferences/other?" in url for url in requests)
            page.locator("#homeButton").click()
            page.locator('.tile[data-tile="resources"]').click()
            runtime.expect(page.locator("#documentSelect")).to_have_value("other-only")
            runtime.expect(page.locator("#documentPreview")).to_contain_text("另一部作品。")
            assert len(held) == 1
            with page.expect_response(old_list):
                held[0][0].fulfill(response=held[0][1])
            page.unroute(old_list, hold_old_list)
            runtime.expect(page.locator("#documentSelect")).to_have_value("other-only")

            page.locator("#resourcesPanel summary").click()
            page.locator("#homeButton").click()
            page.locator('.tile[data-tile="workbench"]').click()
            page.locator("#storySelect").select_option("demo")
            before_reentry = len(requests)
            page.locator("#homeButton").click()
            page.locator('.tile[data-tile="resources"]').click()
            runtime.expect(page.locator("#preferencesEditor")).not_to_be_visible()
            assert len(requests) == before_reentry
            page.locator("#homeButton").click()
            page.locator('.tile[data-tile="preferences"]').click()
            runtime.expect(page.locator("#preferencesStatus")).to_contain_text("未保存偏好已保留")
            runtime.expect(page.locator("#preferencesEditor")).to_have_value("尚未保存的作者偏好。")
            runtime.expect(page.locator("#documentSelect")).to_have_value("keep")
            runtime.expect(page.locator("#documentEditor")).to_have_value("尚未保存的钥匙资料。")
            runtime.expect(page.locator("#reloadDocumentsButton")).to_be_enabled()
            assert len(requests) == before_reentry + 3

            detail_url = "**/api/v1/documents/keep?story_id=demo&timeline_id=main"
            late_detail = []

            def hold_first_detail(route) -> None:
                """依赖：Playwright请求路由。输入：同一资料详情的GET。输出：暂扣首个请求。实现：让稍后的同资料详情先完成。"""
                if late_detail:
                    route.continue_()
                else:
                    late_detail.append(route)

            page.route(detail_url, hold_first_detail)
            page.locator("#documentSelect").select_option("before")
            runtime.expect(page.locator("#documentPreview")).to_contain_text("前一章。")
            with page.expect_request(detail_url):
                page.locator("#documentSelect").select_option("keep")
            runtime.expect(page.locator("#documentEditor")).to_be_disabled()
            page.locator("#documentSelect").select_option("before")
            page.locator("#documentSelect").select_option("keep")
            runtime.expect(page.locator("#documentStatus")).to_have_text("此资料的未保存修改已恢复。")
            with page.expect_response(lambda response: "/documents/keep?" in response.url and response.status == 503):
                late_detail[0].fulfill(status=503, json={"detail": "旧详情读取失败。"})
            page.unroute(detail_url, hold_first_detail)
            page.evaluate("() => new Promise(resolve => requestAnimationFrame(resolve))")
            runtime.expect(page.locator("#documentStatus")).to_have_text("此资料的未保存修改已恢复。")
            runtime.expect(page.locator("#documentEditor")).to_have_value("尚未保存的钥匙资料。")

            canon["content"] = "别处已更新钥匙资料。"
            write_yaml(canon_path, canon)
            with page.expect_response("**/api/v1/documents/keep") as conflict:
                page.locator("#saveDocumentButton").click()
            assert conflict.value.status == 409
            runtime.expect(page.locator("#documentStatus")).to_contain_text("资料版本已改变")
            runtime.expect(page.locator("#documentEditor")).to_have_value("尚未保存的钥匙资料。")
            assert read_yaml_mapping(canon_path)["content"] == "别处已更新钥匙资料。"

            direct = browser.new_page()
            direct.on("request", track_resources)
            before_direct = len(requests)
            direct.goto(base_url + "/#resources", wait_until="domcontentloaded")
            runtime.expect(direct.locator("#reloadDocumentsButton")).to_be_enabled()
            runtime.expect(direct.locator("#preferencesEditor")).to_be_visible()
            assert len(requests) == before_direct + 3
        finally:
            browser.close()


def _assert_no_horizontal_overflow(page) -> None:
    """依赖：真实浏览器的文档和视口尺寸。
    输入：已设置目标视口的Playwright页面。
    输出：无水平溢出时返回，否则给出尺寸诊断并失败。
    实现：比较document与body的scrollWidth和innerWidth。
    """
    dimensions = page.evaluate("""() => ({
      viewport: window.innerWidth,
      document: document.documentElement.scrollWidth,
      body: document.body.scrollWidth
    })""")
    assert dimensions["document"] <= dimensions["viewport"], dimensions
    assert dimensions["body"] <= dimensions["viewport"], dimensions


def test_metro_navigation_layout_and_recovery_over_real_workspace(tmp_path: Path) -> None:
    """验证真实工作区Metro首页、导航、草稿保留和配置失败入口。

    依赖：本机Chrome/Edge、Playwright、workspace_server、真实FastAPI/RunService与writer_fixtures。
    输入：无profile的临时作品库、真实损坏配置文件及一章History和Canon资料。
    输出：首页布局/键盘/路由/回退、未保存输入保留、无导航写请求、损坏配置仍可进入工作台。
    实现：延迟真实bootstrap响应后先选harness，准备真实run，再跨面板浏览并核对DOM、URL和HTTP行为。
    """
    browser_path = installed_browser_path()
    playwright_module = pytest.importorskip("playwright.sync_api")
    expect = playwright_module.expect

    root = make_library(tmp_path)
    history_id = "metro-history"
    canon_id = "metro-canon"
    put_document(root, history_id, "上一章正文：甲把铜钥匙交还给乙。", category="history")
    canon_path = put_document(root, canon_id, "已保存资料：铜钥匙只能打开旧屋的侧门。", category="canon")
    canon_document = read_yaml_mapping(canon_path)
    canon_document.pop("text", None)
    canon_document["content"] = "已保存资料：铜钥匙只能打开旧屋的侧门。"
    write_yaml(canon_path, canon_document)
    workspace = tmp_path / "workspace"
    config_path = tmp_path / "model-config.json"
    app = create_app(root, workspace, config_path)
    assert app.state.service.config.list_profiles() == []

    bootstrap_started = threading.Event()
    release_bootstrap = threading.Event()

    async def delay_real_bootstrap(request, call_next):
        """依赖：FastAPI middleware和线程事件。
        输入：真实HTTP request及原始ASGI handler。
        输出：原始handler生成的响应。
        实现：只延迟真实bootstrap请求以暴露早选driver竞态，其余请求原样通过。
        """
        if request.url.path == "/api/v1/bootstrap":
            bootstrap_started.set()
            await asyncio.to_thread(release_bootstrap.wait, 5)
        return await call_next(request)

    app.middleware("http")(delay_real_bootstrap)
    mutation_requests: list[str] = []
    static_responses: list[tuple[str, int, str]] = []
    page_errors: list[str] = []

    with workspace_server(app) as base_url:
        with playwright_module.sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, executable_path=str(browser_path))
            try:
                page = browser.new_page(viewport={"width": 1920, "height": 1080}, device_scale_factor=1)

                def track_request(request) -> None:
                    """依赖：Playwright Request events and captured route lists.
                    输入：one browser request.
                    输出：matching write paths and image URLs appended for assertions.
                    实现：records actual outgoing requests without changing their transport.
                    """
                    path = request.url.split("?", 1)[0]
                    if request.method == "POST" and (
                        path.endswith("/api/v1/runs") or path.endswith("/cancel")
                    ):
                        mutation_requests.append(f"{request.method} {path}")

                def track_response(response) -> None:
                    """依赖：Playwright Response events and static-response capture.
                    输入：one completed browser response.
                    输出：local static path, status, and content type captured for checks.
                    实现：records actual /static responses without reading or replacing their bodies.
                    """
                    if response.url.startswith(base_url + "/static/"):
                        static_responses.append((
                            response.url,
                            response.status,
                            response.headers.get("content-type", ""),
                        ))

                def record_page_error(error) -> None:
                    """依赖：Playwright pageerror event.
                    输入：an uncaught browser exception.
                    输出：exception text captured for the final assertion.
                    实现：appends the real page error without suppressing it.
                    """
                    page_errors.append(str(error))

                page.on("request", track_request)
                page.on("response", track_response)
                page.on("pageerror", record_page_error)
                page.goto(base_url + "/", wait_until="domcontentloaded")
                expect(page.locator("#launcherView")).to_be_visible()
                assert bootstrap_started.wait(2), "真实bootstrap未进入延迟middleware"
                expect(page.locator("#workspaceView")).to_be_hidden()
                assert page.locator("#tileGrid .tile").count() >= 10
                first_tile = page.locator("#tileGrid .tile").first
                page.keyboard.press("Tab")
                expect(first_tile).to_be_focused()
                first_action = first_tile.get_attribute("data-action")
                page.keyboard.press("ArrowRight")
                focused_action = page.evaluate("document.activeElement?.dataset?.action || null")
                assert focused_action and focused_action != first_action
                page.keyboard.press("Enter")
                expect(page.locator("#workspaceView")).to_be_visible()
                assert page.evaluate("window.location.hash") == _ACTIONS[focused_action]
                page.keyboard.press("Escape")
                expect(page.locator("#launcherView")).to_be_visible()
                expect(page.locator(f'.tile[data-action="{focused_action}"]')).to_be_focused()
                page.locator('.tile[data-action="workbench"]').click()
                expect(page.locator("#writeSurface")).to_be_visible()
                page.locator("#driverSelect").select_option("harness")
                release_bootstrap.set()
                expect(page.locator("#runStatus")).to_have_text("已连接本地工作区", timeout=10_000)
                expect(page.locator("#driverSelect")).to_have_value("harness")
                page.locator("#homeButton").click()
                expect(page.locator("#launcherView")).to_be_visible()
                expect(page.locator('.tile[data-action="workbench"]')).to_be_focused()

                required_actions = set(_ACTIONS)
                actual_actions = set(page.locator("#tileGrid .tile").evaluate_all(
                    "tiles => tiles.map(tile => tile.dataset.action)"
                ))
                assert required_actions.issubset(actual_actions), actual_actions
                tile_details = page.locator("#tileGrid .tile").evaluate_all("""tiles => tiles.map(tile => {
                  const rect = tile.getBoundingClientRect();
                  return {
                    action: tile.dataset.action,
                    title: tile.innerText.trim(),
                    kind: tile.dataset.kind || "",
                    area: Math.round(rect.width * rect.height),
                    left: rect.left,
                    width: rect.width
                  };
                })""")
                assert all(tile["title"] for tile in tile_details), tile_details
                assert len({tile["area"] for tile in tile_details}) >= 4, tile_details
                assert len([tile for tile in tile_details if tile["action"] in required_actions]) >= 10
                assert static_responses and all(status == 200 for _, status, _ in static_responses), static_responses

                for width, height in ((1920, 1080), (1366, 768)):
                    page.set_viewport_size({"width": width, "height": height})
                    _assert_no_horizontal_overflow(page)
                    metrics = page.locator("#tileGrid").evaluate("""grid => {
                      const rect = element => {
                        const box = element.getBoundingClientRect();
                        return {left: box.left, width: box.width, height: box.height,
                                area: box.width * box.height};
                      };
                      const style = getComputedStyle(grid);
                      return {
                        grid: rect(grid), columnGap: style.columnGap, rowGap: style.rowGap,
                        hero: rect(grid.querySelector('.tile[data-kind="hero"]')),
                        primary: rect(grid.querySelector('.tile[data-kind="primary"]')),
                        tiles: [...grid.querySelectorAll('.tile')].map(rect)
                      };
                    }""")
                    assert metrics["hero"] is not None and metrics["primary"] is not None, metrics
                    assert metrics["columnGap"] == "14px" and metrics["rowGap"] == "14px", metrics
                    assert 0.25 <= metrics["hero"]["width"] / metrics["grid"]["width"] <= 0.40, metrics
                    assert metrics["hero"]["left"] == min(tile["left"] for tile in metrics["tiles"]), metrics
                    other_areas = sorted(tile["area"] for tile in metrics["tiles"] if tile["area"] > 0)
                    assert metrics["primary"]["area"] > other_areas[len(other_areas) // 2] * 1.25, metrics

                page.set_viewport_size({"width": 1366, "height": 768})
                clock = page.locator("#launcherView .hero-clock[data-clock]")
                expect(clock).to_be_visible()
                initial_clock = clock.inner_text().strip()
                assert re.fullmatch(r"\d{2}:\d{2}", initial_clock), initial_clock
                browser_clock = page.evaluate("new Intl.DateTimeFormat([], {hour: '2-digit', minute: '2-digit', hourCycle: 'h23'}).format(new Date())")
                assert initial_clock == browser_clock, {"display": initial_clock, "browser": browser_clock}

                placeholder_tile = page.locator('.tile[data-action="placeholder"]').first
                placeholder_tile.evaluate("tile => { tile.dataset.action = 'unconfigured-action'; }")
                unknown_tile = page.locator('.tile[data-action="unconfigured-action"]')
                unknown_tile.click()
                expect(page.locator("#workspaceView")).to_be_visible()
                assert page.evaluate("window.location.hash") == "#placeholder"
                assert page.locator("#surfaceTitle").inner_text().strip()
                page.keyboard.press("Escape")
                expect(page.locator("#launcherView")).to_be_visible()
                expect(unknown_tile).to_be_focused()
                unknown_tile.evaluate("tile => { tile.dataset.action = 'placeholder'; }")

                for tile_index in range(page.locator("#tileGrid .tile").count()):
                    tile = page.locator("#tileGrid .tile").nth(tile_index)
                    action = tile.get_attribute("data-action")
                    expected_hash = _ACTIONS.get(action, "#placeholder")
                    expect(tile).to_be_visible()
                    tile.click()
                    expect(page.locator("#workspaceView")).to_be_visible()
                    assert page.evaluate("window.location.hash") == expected_hash, action
                    expect(page.locator("#surfaceTitle")).to_be_visible()
                    assert page.locator("#surfaceTitle").inner_text().strip(), action
                    if action in {"workbench", "outline", "harness"}:
                        expect(page.locator("#writeSurface")).to_be_visible()
                    elif action in {"resources", "preferences"}:
                        expect(page.locator("#resourcesSurface")).to_be_visible()
                        expect(page.locator("#resourcesPanel")).to_be_visible()
                        assert page.locator("#resourcesPanel").evaluate("panel => panel.open") is True
                    page.locator("#homeButton").click()
                    expect(page.locator("#launcherView")).to_be_visible()

                page.locator('.tile[data-action="workbench"]').click()
                expect(page.locator("#workspaceView")).to_be_visible()
                expect(page.locator("#driverSelect")).to_have_value("harness")
                expect(page.locator("#storySelect")).to_have_value("demo")
                expect(page.locator("#timelineSelect")).to_have_value("main")
                prepared_outline = "真实run大纲：甲先归还铜钥匙，再决定是否进入旧屋。"
                prepared_request = "真实交接要求：写出雨停前甲和乙的简短对话。"
                page.locator("#outlineInput").fill(prepared_outline)
                page.locator("#requestInput").fill(prepared_request)
                page.locator("#startButton").click()
                expect(page.locator("#runStatus")).to_have_text("已准备，等待外部写作工具", timeout=10_000)
                run_id = page.evaluate("new URL(window.location.href).searchParams.get('run')")
                assert isinstance(run_id, str) and run_id
                run_snapshot = app.state.service.store.load(run_id)
                assert run_snapshot["driver"] == "harness"
                assert run_snapshot["profile_name"] is None
                assert run_snapshot["status"] == "prepared"
                assert run_snapshot["request_snapshot"]["outline"] == prepared_outline
                assert run_snapshot["request_snapshot"]["request"] == prepared_request
                assert app.state.service._models == {}

                outline_text = "未保存大纲：甲要先归还铜钥匙，再决定是否进入旧屋。"
                request_text = "未保存要求：沿用上一章的迟疑，先写雨停前的动作。"
                draft_text = "未保存正文：甲把钥匙放在门槛边，仍没有敲门。"
                page.locator("#outlineInput").fill(outline_text)
                page.locator("#requestInput").fill(request_text)
                page.locator("#draftEditor").fill(draft_text)
                posts_before_navigation = len(mutation_requests)
                assert any(path.endswith("/api/v1/runs") for path in mutation_requests)

                page.locator("#homeButton").click()
                expect(page.locator("#launcherView")).to_be_visible()
                assert page.evaluate("new URL(window.location.href).searchParams.get('run')") == run_id
                page.locator('.tile[data-action="memory"]').click()
                expect(page.locator("#workspaceView")).to_be_visible()
                assert page.evaluate("window.location.hash") == "#memory"
                assert page.evaluate("new URL(window.location.href).searchParams.get('run')") == run_id
                page.go_back()
                expect(page.locator("#launcherView")).to_be_visible()
                assert page.evaluate("new URL(window.location.href).searchParams.get('run')") == run_id
                page.go_forward()
                expect(page.locator("#workspaceView")).to_be_visible()
                assert page.evaluate("window.location.hash") == "#memory"
                page.locator("#homeButton").click()
                page.locator('.tile[data-action="workbench"]').click()
                expect(page.locator("#outlineInput")).to_have_value(outline_text)
                expect(page.locator("#requestInput")).to_have_value(request_text)
                expect(page.locator("#draftEditor")).to_have_value(draft_text)

                page.locator("#homeButton").click()
                page.locator('.tile[data-tile="resources"]').click()
                expect(page.locator("#resourcesSurface")).to_be_visible()
                expect(page.locator("#preferencesEditor")).to_be_enabled()
                preference_text = "未保存偏好：保留安靜的叙述节奏。"
                document_text = "未保存设定：侧门的锁已经生锈，铜钥匙暂时转不动。"
                page.locator("#preferencesEditor").fill(preference_text)
                page.locator("#documentSelect").select_option(canon_id)
                expect(page.locator("#documentEditor")).to_be_visible()
                expect(page.locator("#documentEditor")).to_have_value("已保存资料：铜钥匙只能打开旧屋的侧门。")
                page.locator("#documentEditor").fill(document_text)
                page.locator("#homeButton").click()
                page.locator('.tile[data-action="about"]').click()
                expect(page.locator("#workspaceView")).to_be_visible()
                page.locator("#homeButton").click()
                page.locator('.tile[data-tile="resources"]').click()
                expect(page.locator("#preferencesEditor")).to_have_value(preference_text)
                expect(page.locator("#documentSelect")).to_have_value(canon_id)
                expect(page.locator("#documentEditor")).to_have_value(document_text)

                page.locator("#documentSelect").select_option(history_id)
                expect(page.locator("#reviseDocumentButton")).to_be_visible()
                page.locator("#reviseDocumentButton").click()
                expect(page.locator("#writeSurface")).to_be_visible()
                expect(page.locator("#requestInput")).to_be_focused()
                expect(page.locator("#requestInput")).to_have_value(request_text)
                expect(page.locator("#outlineInput")).to_have_value(outline_text)
                expect(page.locator("#draftEditor")).to_have_value(draft_text)
                assert page.evaluate("new URL(window.location.href).searchParams.get('run')") == run_id
                assert len(mutation_requests) == posts_before_navigation, mutation_requests
                assert app.state.service._models == {}
                assert page_errors == []

                page.locator("#homeButton").click()
                expect(clock).to_be_visible()
                page.wait_for_function("""before => {
                  const clock = document.querySelector('#launcherView .hero-clock[data-clock]');
                return clock && clock.textContent.trim() !== before;
                }""", arg=initial_clock, timeout=65_000)
                updated_clock = clock.inner_text().strip()
                assert re.fullmatch(r"\d{2}:\d{2}", updated_clock), updated_clock
                assert updated_clock != initial_clock

            finally:
                release_bootstrap.set()
                browser.close()

    broken_config = tmp_path / "broken-model-config.json"
    broken_config.write_text('{"profiles":', encoding="utf-8")
    broken_app = create_app(root, tmp_path / "workspace-broken-config", broken_config)
    with workspace_server(broken_app) as broken_url:
        with playwright_module.sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, executable_path=str(browser_path))
            try:
                page = browser.new_page(viewport={"width": 1366, "height": 768})
                page.goto(broken_url + "/", wait_until="domcontentloaded")
                expect(page.locator("#launcherView")).to_be_visible()
                expect(page.locator('.tile[data-action="workbench"]')).to_be_visible()
                page.locator('.tile[data-action="workbench"]').click()
                expect(page.locator("#workspaceView")).to_be_visible()
                expect(page.locator("#writeSurface")).to_be_visible()
            finally:
                browser.close()


def test_metro_local_image_failure_keeps_workbench_clickable(tmp_path: Path) -> None:
    """验证首页真实本地图片成功加载，且图片失败不影响工作台入口。

    依赖：本机Chrome/Edge、Playwright、workspace_server和真实静态资源服务。
    输入：由应用静态目录实际返回的图片URL。
    输出：图片资源先以HTTP 200加载；同一真实图片请求失败后工作台按钮仍可用。
    实现：先观察本地图片Response，再在新浏览器context仅中止该图片URL并执行真实按钮导航。
    """
    browser_path = installed_browser_path()
    playwright_module = pytest.importorskip("playwright.sync_api")
    expect = playwright_module.expect
    root = make_library(tmp_path)
    app = create_app(root, tmp_path / "workspace", tmp_path / "model-config.json")

    with workspace_server(app) as base_url:
        with playwright_module.sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, executable_path=str(browser_path))
            try:
                source_page = browser.new_page(viewport={"width": 1366, "height": 768})
                image_responses: list[tuple[str, int, str]] = []

                def capture_image_response(response) -> None:
                    """依赖：Playwright Response event和本地图片响应列表。
                    输入：浏览器已完成的HTTP Response。
                    输出：真实图片URL、状态码及content type。
                    实现：只记录image/*响应，不修改请求或响应。
                    """
                    content_type = response.headers.get("content-type", "").lower()
                    if content_type.startswith("image/"):
                        image_responses.append((response.url, response.status, content_type))

                source_page.on("response", capture_image_response)
                source_page.goto(base_url + "/", wait_until="domcontentloaded")
                expect(source_page.locator("#launcherView")).to_be_visible()
                source_page.wait_for_function("""() => performance.getEntriesByType('resource').some(item =>
                  item.name.startsWith(location.origin + '/static/') && /\\.(avif|gif|jpe?g|png|svg|webp)(?:$|\\?)/i.test(item.name)
                )""", timeout=10_000)
                assert image_responses, "首页没有请求任何图片资源"
                assert all(url.startswith(base_url + "/static/") and status == 200 for url, status, _ in image_responses), image_responses
                image_url = image_responses[0][0]

                image_failure_page = browser.new_page(viewport={"width": 1366, "height": 768})
                failed_images: list[str] = []

                def fail_image(route) -> None:
                    """依赖：Playwright route API与已证实HTTP 200的本地资源URL。
                    输入：所选静态图片的匹配Route。
                    输出：页面收到图片加载失败。
                    实现：仅中止这一图片请求，保留真实应用服务和其他网络行为。
                    """
                    failed_images.append(route.request.url)
                    route.abort()

                image_failure_page.route(image_url, fail_image)
                image_failure_page.goto(base_url + "/", wait_until="domcontentloaded")
                expect(image_failure_page.locator("#launcherView")).to_be_visible()
                image_failure_page.locator('.tile[data-action="workbench"]').click()
                expect(image_failure_page.locator("#workspaceView")).to_be_visible()
                assert image_url in failed_images, failed_images
                source_page.close()
                image_failure_page.close()
            finally:
                browser.close()


def test_metro_mobile_workbench_scroll_focus_and_driver_click(tmp_path: Path) -> None:
    """验证窄屏从滚动入口进入工作台后标题和driver可操作，返回焦点仍可见。

    依赖：本机Chrome/Edge、Playwright、workspace_server、真实FastAPI页面和writer_fixtures。
    输入：320×568视口、无profile的临时作品库及首页workbench tile。
    输出：滚动后的tile可点击、工作台标题/driver处于可视范围、返回后原tile获焦且可见。
    实现：真实浏览器滚到tile、点击进入、将driver滚入视口并实际点击，再通过home按钮检查焦点和几何位置。
    """
    browser_path = installed_browser_path()
    playwright_module = pytest.importorskip("playwright.sync_api")
    expect = playwright_module.expect
    root = make_library(tmp_path)
    app = create_app(root, tmp_path / "workspace", tmp_path / "model-config.json")

    with workspace_server(app) as base_url:
        with playwright_module.sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, executable_path=str(browser_path))
            try:
                page = browser.new_page(viewport={"width": 320, "height": 568}, device_scale_factor=1)
                page.goto(base_url + "/", wait_until="domcontentloaded")
                expect(page.locator("#launcherView")).to_be_visible()
                workbench_tile = page.locator('.tile[data-action="workbench"]').first
                page.evaluate("window.scrollTo(0, document.documentElement.scrollHeight)")
                workbench_tile.scroll_into_view_if_needed()
                assert page.evaluate("window.scrollY") > 0, "首页场景应实际滚动后到达工作台入口"
                workbench_tile.click()

                expect(page.locator("#workspaceView")).to_be_visible()
                surface_title = page.locator("#surfaceTitle")
                expect(surface_title).to_be_visible()
                assert surface_title.inner_text().strip()
                title_box = surface_title.bounding_box()
                assert title_box is not None
                assert 0 <= title_box["y"] and title_box["y"] + title_box["height"] <= 568, title_box

                driver_select = page.locator("#driverSelect")
                driver_select.scroll_into_view_if_needed()
                driver_box = driver_select.bounding_box()
                assert driver_box is not None
                assert 0 <= driver_box["y"] and driver_box["y"] + driver_box["height"] <= 568, driver_box
                driver_select.click()
                expect(driver_select).to_be_focused()
                driver_select.select_option("harness")
                expect(driver_select).to_have_value("harness")

                page.locator("#homeButton").click()
                expect(page.locator("#launcherView")).to_be_visible()
                expect(workbench_tile).to_be_focused()
                tile_box = workbench_tile.bounding_box()
                assert tile_box is not None
                assert 0 <= tile_box["y"] and tile_box["y"] + tile_box["height"] <= 568, tile_box
            finally:
                browser.close()


def test_workspace_server_retries_fetch_bad_port_and_closes_listener(tmp_path: Path, monkeypatch) -> None:
    """验证workspace_server拒绝真实随机分配的Fetch禁用端口并释放listener。

    依赖：fixture模块socket引用、标准库真实socket、workspace_server及writer_fixtures。
    输入：make_library/create_app生成的临时应用和可追踪的真实socket子类。
    输出：首个禁用socket被关闭，后续真实HTTP服务使用保留socket，with退出释放该socket。
    实现：只替换fixture模块的socket工厂，在首个真实bind后将其端口加入禁用集合并核验重试生命周期。
    """
    root = make_library(tmp_path)
    app = create_app(root, tmp_path / "workspace", tmp_path / "model-config.json")
    created_sockets: list[stdlib_socket.socket] = []
    bound_ports: list[int] = []

    class TrackingSocket(stdlib_socket.socket):
        """跟踪fixture创建的真实socket及其bind结果。

        依赖：标准库socket.socket、外层端口记录和pytest monkeypatch。
        输入：socket构造参数或一个真实bind地址。
        输出：原生socket行为，并记录创建、绑定端口及关闭状态。
        实现：子类委托真实socket；首个bind成功后仅更新fixture模块的禁用端口集合。
        """

        def __init__(self, *args, **kwargs):
            """依赖：真实socket构造器和外层created_sockets列表。

            输入：标准库socket构造参数。
            输出：已创建并登记的真实socket实例。
            实现：先初始化底层socket，再将自身追加到测试追踪列表。
            """
            super().__init__(*args, **kwargs)
            created_sockets.append(self)

        def bind(self, address):
            """依赖：原生bind、端口记录和fixture模块的Fetch禁用集合。

            输入：loopback地址及端口0。
            输出：真实bind结果，并在首个成功bind后将端口加入本fixture集合。
            实现：先调用真实bind再读取实际分配端口，只patch fixture模块变量。
            """
            super().bind(address)
            bound_ports.append(self.getsockname()[1])
            if len(bound_ports) == 1:
                monkeypatch.setattr(
                    fixture_module,
                    "FETCH_BAD_PORTS",
                    fixture_module.FETCH_BAD_PORTS | {bound_ports[0]},
                )

    monkeypatch.setattr(
        fixture_module,
        "socket",
        SimpleNamespace(
            AF_INET=stdlib_socket.AF_INET,
            SOCK_STREAM=stdlib_socket.SOCK_STREAM,
            socket=TrackingSocket,
        ),
    )

    with workspace_server(app) as base_url:
        assert len(created_sockets) >= 2
        assert bound_ports[0] in fixture_module.FETCH_BAD_PORTS
        assert created_sockets[0].fileno() == -1
        retained_listener = created_sockets[-1]
        retained_port = retained_listener.getsockname()[1]
        assert retained_port == bound_ports[-1]
        assert int(base_url.rsplit(":", 1)[1]) == retained_port
        assert retained_listener.fileno() >= 0
        with urlopen(base_url + "/api/v1/harness/bootstrap", timeout=2) as response:
            assert response.status == 200

    assert retained_listener.fileno() == -1


def test_metro_public_art_pools_rotate_and_obey_motion_preferences(tmp_path: Path) -> None:
    """依赖：已安装浏览器/Playwright Clock、真实workspace_server和静态图片。
    输入：当前15张公开素材、4组图片磁贴、展示偏好与reduced-motion。
    输出：全部素材可加载并实际轮换，合法每图焦点生效，静态偏好暂停轮图但时钟继续。
    实现：用真实HTTP页面推进所有timer，遍历完整轮换周期，再实际操作开关和系统偏好；不触发作品写入。
    """
    browser_path = installed_browser_path()
    playwright_module = pytest.importorskip("playwright.sync_api")
    expect = playwright_module.expect
    root = make_library(tmp_path)
    app = create_app(root, tmp_path / "workspace", tmp_path / "model-config.json")
    static = files("novel_rag.web").joinpath("static")
    assets = json.loads((static / "assets/manifest.json").read_text(encoding="utf-8"))["assets"]
    assert len(assets) == 15
    expected_files = {asset["file"] for asset in assets}

    with workspace_server(app) as base_url, playwright_module.sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=str(browser_path))
        try:
            page = browser.new_page(viewport={"width": 1366, "height": 768}, reduced_motion="no-preference")
            page.clock.install()
            page.goto(base_url + "/", wait_until="domcontentloaded")
            expect(page.locator("#tileGrid .tile")).to_have_count(13)
            expect(page.locator("#launcherFallback")).to_be_hidden()
            page.wait_for_function("[...document.querySelectorAll('.tile img')].every(image=>image.complete&&image.naturalWidth>0)")
            assert page.locator(".tile-image img").count() == 16
            for asset in assets:
                if asset.get("imagePosition"):
                    image = page.locator(f'.tile-image img[src$="/{asset["file"]}"]').first
                    assert image.evaluate("image=>image.style.objectPosition") == asset["imagePosition"]

            def active_files():
                """依赖：真实图片磁贴DOM；输入：当前page；输出：tile→当前图片文件；实现：仅读取active帧，验证timer产生的可见选择而不调用应用私有函数。"""
                return page.locator(".tile-image img.active").evaluate_all("images=>Object.fromEntries(images.map(image=>[image.closest('.tile').dataset.tile,new URL(image.src).pathname.split('/').pop()]))")

            seen = set(active_files().values())
            for _ in range(4):
                previous = active_files()
                page.clock.run_for(45_000)
                current = active_files()
                assert len(current) == 4 and all(current[tile] != previous[tile] for tile in current)
                seen.update(current.values())
            assert seen == expected_files

            page.locator('.tile[data-action="settings"]').click()
            page.locator("#motionPreference").uncheck()
            page.locator("#homeButton").click()
            paused = active_files()
            page.clock.run_for(90_000)
            assert active_files() == paused
            page.locator('.tile[data-action="settings"]').click()
            page.locator("#motionPreference").check()
            page.locator("#homeButton").click()
            resumed = active_files()
            page.clock.run_for(45_000)
            assert active_files() != resumed

            page.emulate_media(reduced_motion="reduce")
            still = active_files()
            clock = page.locator(".hero-clock").inner_text()
            page.clock.run_for(90_000)
            assert active_files() == still
            assert page.locator(".hero-clock").inner_text() != clock
        finally:
            browser.close()


def test_metro_visible_tile_copy_stays_inside_cards_at_breakpoints(tmp_path: Path) -> None:
    """验证窄视口及1000px断点附近全部磁贴的可见文字留在卡片内。

    依赖：本机Chrome/Edge、Playwright、workspace_server和真实Metro静态页面。
    输入：无profile的临时应用及六组窄屏/断点视口。
    输出：13个tile中可见标题、副标题、眉题、序号及辅助文字均不越出所属tile矩形。
    实现：在真实浏览器逐视口读取tile和可见文本DOMRect，并按卡片边界逐项断言，不以页面总宽度代替文字检查。
    """
    browser_path = installed_browser_path()
    playwright_module = pytest.importorskip("playwright.sync_api")
    expect = playwright_module.expect
    root = make_library(tmp_path)
    app = create_app(root, tmp_path / "workspace", tmp_path / "model-config.json")
    viewports = ((844, 390), (768, 1024), (900, 700), (999, 700), (1000, 700), (1001, 700))

    with workspace_server(app) as base_url:
        with playwright_module.sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, executable_path=str(browser_path))
            try:
                page = browser.new_page(viewport={"width": 844, "height": 390}, device_scale_factor=1)
                page.goto(base_url + "/", wait_until="domcontentloaded")
                expect(page.locator("#launcherView")).to_be_visible()
                for width, height in viewports:
                    page.set_viewport_size({"width": width, "height": height})
                    tile_geometry = page.locator("#tileGrid .tile").evaluate_all("""tiles => {
                      const selectors = [
                        [".tile-title", "title"], [".tile-description", "subtitle"],
                        [".tile-eyebrow", "eyebrow"], [".tile-index", "index"],
                        [".hero-caption", "subtitle"], [".tile-meta", "meta"],
                        [".hero-date", "date"], [".hero-clock", "clock"]
                      ];
                      const visible = element => {
                        const style = getComputedStyle(element);
                        const box = element.getBoundingClientRect();
                        return style.display !== "none" && style.visibility !== "hidden" &&
                          Number(style.opacity) > 0 && box.width > 0 && box.height > 0;
                      };
                      return tiles.map(tile => {
                        const tileBox = tile.getBoundingClientRect();
                        const text = [...tile.querySelectorAll(selectors.map(([selector]) => selector).join(","))]
                          .filter(visible).map(element => {
                            const [selector, role] = selectors.find(([candidate]) => element.matches(candidate));
                            const box = element.getBoundingClientRect();
                            return {
                              role, text: element.textContent.trim(), selector,
                              left: box.left, top: box.top, right: box.right, bottom: box.bottom
                            };
                          });
                        return {
                          id: tile.dataset.tile, kind: tile.dataset.kind,
                          box: {left: tileBox.left, top: tileBox.top, right: tileBox.right, bottom: tileBox.bottom},
                          text
                        };
                      });
                    }""")
                    assert len(tile_geometry) == 13, {"viewport": (width, height), "tiles": tile_geometry}
                    for tile in tile_geometry:
                        roles = {item["role"] for item in tile["text"]}
                        expected_roles = {"eyebrow", "index", "subtitle" if tile["kind"] == "hero" else "title"}
                        if tile["kind"] != "compact" or width > 1000:
                            expected_roles.add("subtitle")
                        assert expected_roles <= roles, {
                            "viewport": (width, height), "tile": tile, "expected_roles": expected_roles,
                        }
                        for item in tile["text"]:
                            bounds = tile["box"]
                            assert (
                                item["left"] >= bounds["left"] - 1
                                and item["top"] >= bounds["top"] - 1
                                and item["right"] <= bounds["right"] + 1
                                and item["bottom"] <= bounds["bottom"] + 1
                            ), {"viewport": (width, height), "tile": tile["id"], "text": item, "tile_box": bounds}
            finally:
                browser.close()
