"""作者按需记忆浏览的真实HTTP/浏览器验收；不配置或调用外部模型。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from native_http_fixture import workspace_server
from novel_rag.harness import BackendClient
from novel_rag.web.app import create_app
from writer_fixtures import make_library, put_document
from test_workspace_browser import installed_browser_path, _assert_no_horizontal_overflow


def _prepare_memory_run(client: BackendClient, *, count: int, extra: bool = False) -> tuple[str, dict]:
    """依赖：真实BackendClient/五工具。输入：线索数及孤立记录选项。输出：run和稳定ID映射。实现：HTTP准备、save及remember建夹具，不直接改Store。"""
    run = client.request("/api/v1/runs", {"story_id": "demo", "timeline_id": "main", "driver": "harness",
        "outline": "按原始来源浏览旧事。", "request": "保留原文、性质、来源和位置。"})
    run_id = run["run_id"]
    draft = client.request(client.run_path(run_id, "/harness-tool"), {"name": "save_draft",
        "arguments": {"text": "\n".join(f"第{i:03}块铜牌原文。" for i in range(count)) + "\n独立经过：门已打开。独立笔记：记下雨声。状态：灯亮。",
                      "expected_revision": 0}, "operation_id": "browser-seed-save"})
    update = {"hooks": [{"op": "create", "local_ref": f"clue-{i}", "record": {
        "record_kind": "hook", "payload": {"nature": "unexplained" if i % 2 else "unresolved",
        "text": f"第{i:03}块铜牌原文。", "explanation_candidates": []}}} for i in range(count)]}
    if extra:
        update.update(notes=[{"op": "create", "local_ref": "lonely-note", "record": {
            "record_kind": "note", "payload": {"text": "独立笔记：记下雨声。"}}}],
            experiences=[{"op": "create", "local_ref": "lonely-experience", "record": {
                "record_kind": "experience", "payload": {"text": "独立经过：门已打开。"}}}],
            state_changes=[{"op": "set", "local_ref": "lit", "entry": {
                "domain": "World", "kind": "condition", "value": "状态：灯亮。", "lifetime": "carry"}},
                {"op": "set", "local_ref": "ended", "entry": {
                "domain": "World", "kind": "condition", "value": "稍后解除的状态。", "lifetime": "carry"}}])
    remembered = client.request(client.run_path(run_id, "/harness-tool"), {"name": "remember", "operation_id": "browser-seed-memory",
        "arguments": {"draft_ref": draft, "expected_memory_revision": 0, "update": update}})
    assert remembered.get("ok") is not False, remembered
    mapping = remembered["local_ref_to_stable_id"]
    if extra:
        cleared = client.request(client.run_path(run_id, "/harness-tool"), {"name": "remember", "operation_id": "browser-clear",
            "arguments": {"draft_ref": draft, "expected_memory_revision": remembered["memory_revision"],
                          "update": {"state_changes": [{"op": "clear", "entry_id": mapping["ended"]}]}}})
        assert cleared.get("ok") is not False, cleared
    return run_id, mapping


def test_memory_browser_reads_130_candidates_after_cancel_without_idle_recall(tmp_path: Path) -> None:
    """依赖：真实Uvicorn/HTTP/已安装浏览器。输入：130线索和取消run。输出：64/64/2、本批16后可见、无闲置召回。实现：观察真实请求和页面卡片，核来源/性质/位置及终页。"""
    playwright = pytest.importorskip("playwright.sync_api")
    root = make_library(tmp_path)
    app = create_app(root, tmp_path / "workspace", tmp_path / "no-model.json")
    assert app.state.service.config.list_profiles() == []
    with workspace_server(app) as backend, playwright.sync_playwright() as runtime:
        client = BackendClient(backend)
        run_id, mapping = _prepare_memory_run(client, count=130)
        client.request(client.run_path(run_id, "/cancel"), {})
        browser = runtime.chromium.launch(headless=True, executable_path=str(installed_browser_path(runtime)))
        try:
            page = browser.new_page(viewport={"width": 1360, "height": 980})
            paths, errors, memory_responses = [], [], []
            page.on("request", lambda request: paths.append(request.url))
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on("response", lambda response: memory_responses.append(response) if response.url.endswith("/memory") else None)
            page.goto(f"{backend}/?run={run_id}#write", wait_until="domcontentloaded")
            playwright.expect(page.locator("#runStatus")).to_contain_text("已停止", timeout=15000)
            assert not any(path.endswith("/memory") for path in paths)
            run_reads = [path for path in paths if f"/runs/{run_id}?" in path]
            assert run_reads and all("view=live" in path for path in run_reads)
            page.locator("#homeButton").click()
            page.locator('.tile[data-action="memory"]').first.click()
            playwright.expect(page.locator("#memoryStatus")).to_contain_text("已查 64 个节点", timeout=15000)
            playwright.expect(page.locator(".memory-card")).to_have_count(64)
            playwright.expect(page.locator(".memory-card").nth(16)).to_be_visible()
            playwright.expect(page.locator(".memory-card").first).to_contain_text("叙事位置：")
            playwright.expect(page.locator(".memory-card").first).to_contain_text("来源：")
            playwright.expect(page.locator(".memory-card").first).to_contain_text("性质：")
            playwright.expect(page.locator(".memory-card").first).to_contain_text("选择说明：")
            page.locator("#moreMemoryButton").click()
            playwright.expect(page.locator("#memoryStatus")).to_contain_text("已查 128 个节点", timeout=15000)
            playwright.expect(page.locator(".memory-card")).to_have_count(128)
            page.locator("#moreMemoryButton").click()
            playwright.expect(page.locator("#memoryStatus")).to_contain_text("已查 130 个节点", timeout=15000)
            playwright.expect(page.locator(".memory-card")).to_have_count(130)
            playwright.expect(page.locator("#moreMemoryButton")).to_be_hidden()
            actual_ids = page.locator(".memory-card").evaluate_all("cards => cards.map(card => card.dataset.recordId)")
            assert set(actual_ids) == set(mapping.values())
            assert len([path for path in paths if path.endswith("/memory")]) == 3
            assert errors == []
            page.locator("#memoryStatus").scroll_into_view_if_needed()
            artifacts = Path(__file__).resolve().parents[1] / "output/workspace-observation-20261021/C-ui"
            artifacts.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(artifacts / "memory-130.png"))
            page.set_viewport_size({"width": 390, "height": 844})
            _assert_no_horizontal_overflow(page)
            page.locator("#memoryStatus").scroll_into_view_if_needed()
            page.screenshot(path=str(artifacts / "memory-mobile.png"))
        finally:
            if "memory_responses" in locals():
                artifacts = Path(__file__).resolve().parents[1] / "output/workspace-observation-20261021/C-ui"
                artifacts.mkdir(parents=True, exist_ok=True)
                (artifacts / "memory-page-timings.json").write_text(json.dumps([
                    {"status": response.status, "timing": response.request.timing}
                    for response in memory_responses], indent=2), encoding="utf-8")
            browser.close()


def test_memory_browser_keeps_isolated_records_and_rejects_changed_source_cursor(tmp_path: Path) -> None:
    """依赖：真实HTTP/来源字节/浏览器。输入：70线索及孤立笔记经历和Set/Clear。输出：旧cursor拒绝不混包，重查后所有记录可见。实现：首批后改未选来源，再重新完整浏览并核稳定身份。"""
    playwright = pytest.importorskip("playwright.sync_api")
    root = make_library(tmp_path)
    source = put_document(root, "background", "原始背景", category="canon")
    app = create_app(root, tmp_path / "workspace", tmp_path / "no-model.json")
    with workspace_server(app) as backend, playwright.sync_playwright() as runtime:
        client = BackendClient(backend)
        run_id, mapping = _prepare_memory_run(client, count=70, extra=True)
        browser = runtime.chromium.launch(headless=True, executable_path=str(installed_browser_path(runtime)))
        try:
            page = browser.new_page()
            page.goto(f"{backend}/?run={run_id}#memory", wait_until="domcontentloaded")
            playwright.expect(page.locator("#memoryStatus")).to_contain_text("已查 64 个节点", timeout=15000)
            source.write_text(source.read_text(encoding="utf-8").replace("原始背景", "已修改背景"), encoding="utf-8")
            page.locator("#moreMemoryButton").click()
            playwright.expect(page.locator("#memoryStatus")).to_contain_text("读取失败", timeout=15000)
            playwright.expect(page.locator(".memory-card")).to_have_count(0)
            playwright.expect(page.locator("#moreMemoryButton")).to_be_hidden()
            page.locator("#refreshMemoryButton").click()
            playwright.expect(page.locator("#memoryStatus")).to_contain_text("已查 64 个节点", timeout=15000)
            page.locator("#moreMemoryButton").click()
            playwright.expect(page.locator("#memoryStatus")).to_contain_text("本次查询范围已查完", timeout=15000)
            for name in ("lonely-note", "lonely-experience", "lit", "ended"):
                playwright.expect(page.locator(f'.memory-card[data-record-id="{mapping[name]}"]')).to_have_count(1)
            playwright.expect(page.locator(f'.memory-card[data-record-id="{mapping["ended"]}"]')).to_contain_text("cleared")
            playwright.expect(page.locator("#memoryCards")).to_contain_text("独立笔记：记下雨声。")
            playwright.expect(page.locator("#memoryCards")).to_contain_text("独立经过：门已打开。")
        finally:
            browser.close()


def test_memory_browser_ignores_delayed_previous_run_response_and_coalesces_live_reads(tmp_path: Path) -> None:
    """依赖：真实HTTP/Playwright路由延迟。输入：原run记忆响应延迟和新run切换。输出：不串页，同run并发刷新只有一请求。实现：fetch真实后端后暂扣响应，切到新run后释放旧包。"""
    playwright = pytest.importorskip("playwright.sync_api")
    root = make_library(tmp_path)
    app = create_app(root, tmp_path / "workspace", tmp_path / "no-model.json")
    with workspace_server(app) as backend, playwright.sync_playwright() as runtime:
        client = BackendClient(backend)
        first, _ = _prepare_memory_run(client, count=3)
        second, _ = _prepare_memory_run(client, count=1, extra=True)
        browser = runtime.chromium.launch(headless=True, executable_path=str(installed_browser_path(runtime)))
        try:
            page = browser.new_page()
            held = []
            def hold_memory(route) -> None:
                """依赖：Playwright真实route.fetch。输入：旧run记忆请求。输出：暂扣真实响应。实现：不改响应内容，供切换后手动交付。"""
                held.append((route, route.fetch()))
            page.route(f"**/runs/{first}/memory", hold_memory)
            page.goto(f"{backend}/?run={first}#memory", wait_until="domcontentloaded")
            playwright.expect(page.locator("#memoryStatus")).to_contain_text("正在读取记忆", timeout=15000)
            page.wait_for_function("() => document.querySelector('#runStatus').textContent.includes('已准备')")
            page.evaluate("runId => activateRun(runId, '', false)", second)
            playwright.expect(page.locator("#memoryCards")).to_contain_text("独立笔记：记下雨声。", timeout=15000)
            assert len(held) == 1
            held[0][0].fulfill(response=held[0][1])
            playwright.expect(page.locator(".memory-card")).to_have_count(5)
            assert page.evaluate("workspace.memoryBrowse.runId") == second
            reads = []
            def track_read(route) -> None:
                """依赖：真实HTTP读取。输入：新run的live请求。输出：原响应。实现：记录次数后原样转发，检验同时调用刷新单飞。"""
                reads.append(route.request.url)
                route.continue_()
            page.route(f"**/runs/{second}?*", track_read)
            page.evaluate("() => Promise.all([refreshRunSnapshot(workspace.runId), refreshRunSnapshot(workspace.runId), refreshRunSnapshot(workspace.runId)])")
            assert len(reads) == 1
            before = page.locator("#memoryCards").inner_text()
            page.evaluate("() => applySnapshot({...workspace.snapshot, event_seq: workspace.lastEventSeq - 1, draft_text: 'LATE_WRONG_TEXT'}, workspace.runId)")
            assert page.locator("#memoryCards").inner_text() == before
            assert page.locator("#draftEditor").input_value() != "LATE_WRONG_TEXT"
        finally:
            browser.close()
