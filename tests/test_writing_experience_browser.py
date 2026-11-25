"""写作体验R1：真实浏览器、本地HTTP与临时作品；不使用真实模型或正式资料。"""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import expect, sync_playwright

from native_http_fixture import workspace_server
from test_workspace_browser import installed_browser_path
from novel_rag.documents import read_yaml_mapping
from novel_rag.harness import BackendClient
from novel_rag.web.app import create_app
from writer_fixtures import make_library, write_yaml


def accept_exit_dialog(dialog) -> None:
    """依赖：Playwright原生dialog。输入：离开提示。输出：None。实现：显式允许测试刷新，恢复仍由浏览器真实存储完成。"""
    dialog.accept()


@contextmanager
def writing_workspace(tmp_path: Path):
    """依赖：现有建库/HTTP/browser路径夹具。输入：临时目录。输出：页面/浏览器/app/backend/库。实现：真实loopback与已安装浏览器，退出释放自身服务和进程。"""
    root = make_library(tmp_path)
    app = create_app(root, tmp_path / "workspace", tmp_path / "model-config.json")
    with workspace_server(app) as backend, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=str(installed_browser_path(playwright)))
        try:
            context = browser.new_context(viewport={"width": 1366, "height": 768})
            page = context.new_page()
            page.on("dialog", accept_exit_dialog)
            page.goto(backend + "/#write", wait_until="domcontentloaded")
            expect(page.locator("#runStatus")).to_have_text("已连接本地工作区")
            yield page, browser, app, backend, root
        finally:
            browser.close()


def test_unstarted_input_refresh_scope_switch_and_opener_copies_remain_separate(tmp_path: Path) -> None:
    """依赖：真实页面/localStorage/sessionStorage/opener。输入：未提交A/B输入及复制session的新tab。
    输出：刷新/切书恢复且两页互不覆盖、无模型调用。实现：操作实际表单，比较作者可见正文与各writer记录。
    """
    with writing_workspace(tmp_path) as (page, browser, app, backend, root):
        page.locator("#useHarnessButton").click()
        page.locator("#outlineInput").fill("A大纲：雨夜取回钥匙。")
        page.locator("#requestInput").fill("保持人物视角。")
        page.locator("#draftEditor").fill("A未提交正文。")
        page.locator("#chapterInput").fill("7")
        page.reload(wait_until="domcontentloaded")
        expect(page.locator("#draftEditor")).to_have_value("A未提交正文。")
        expect(page.locator("#outlineInput")).to_have_value("A大纲：雨夜取回钥匙。")
        expect(page.locator("#requestInput")).to_have_value("保持人物视角。")
        expect(page.locator("#chapterInput")).to_have_value("7")
        page.locator("#storySelect").select_option("other")
        expect(page.locator("#draftEditor")).to_have_value("")
        page.locator("#outlineInput").fill("B作品大纲。")
        page.locator("#draftEditor").fill("B独立正文。")
        page.locator("#storySelect").select_option("demo")
        expect(page.locator("#draftEditor")).to_have_value("A未提交正文。")
        with page.expect_popup() as popup_info:
            page.evaluate("() => window.open(location.href, '_blank')")
        popup = popup_info.value
        popup.on("dialog", accept_exit_dialog)
        expect(popup.locator("#draftEditor")).to_have_value("A未提交正文。")
        popup.locator("#draftEditor").fill("复制tab自己的正文。")
        page.locator("#draftEditor").fill("原tab后来的修改。")
        popup.reload(wait_until="domcontentloaded")
        page.reload(wait_until="domcontentloaded")
        expect(popup.locator("#draftEditor")).to_have_value("复制tab自己的正文。")
        expect(page.locator("#draftEditor")).to_have_value("原tab后来的修改。")
        records = page.evaluate("() => Object.entries(localStorage).filter(([key]) => key.startsWith('novel-rag.inputs.v1:')).map(([, value]) => JSON.parse(value))")
        assert len({record["writer"] for record in records}) >= 2
        assert all("token" not in record and "api_key" not in record for record in records)
        assert app.state.service._models == {}
        assert not list((root / "stories" / "demo" / "timelines" / "main" / "history").glob("**/*.yaml"))


def test_dirty_original_revision_conflicts_then_refresh_offers_local_copy(tmp_path: Path) -> None:
    """依赖：真实两tab/唯一DraftStore CAS。输入：基于R1的编辑与另一页保存R2。
    输出：旧编辑保存冲突，刷新保留候选，明确选择后保存R3。实现：从真实工具初始化草稿，再由两个网页写者产生版本竞争。
    """
    with writing_workspace(tmp_path) as (page, browser, app, backend, root):
        page.locator("#useHarnessButton").click()
        page.locator("#outlineInput").fill("两个版本的正文。")
        page.locator("#startButton").click()
        expect(page.locator("#runStatus")).to_have_text("已准备，等待外部写作工具")
        run_id = parse_qs(urlparse(page.url).query)["run"][0]
        client = BackendClient(backend)
        client.request(client.run_path(run_id, "/harness-tool"), {
            "name": "save_draft", "arguments": {"text": "服务器R1。", "expected_revision": 0}, "operation_id": "seed-r1",
        })
        expect(page.locator("#draftEditor")).to_have_value("服务器R1。")
        page.locator("#draftEditor").fill("作者基于R1的修改。")
        second = page.context.new_page()
        second.goto(backend + f"/?run={run_id}", wait_until="domcontentloaded")
        expect(second.locator("#draftRevision")).to_have_text("草稿修订 1")
        second.locator("#draftEditor").fill("第二页保存的R2。")
        second.locator("#saveDraftButton").click()
        expect(second.locator("#draftRevision")).to_have_text("草稿修订 2")
        expect(page.locator("#draftRevision")).to_have_text("草稿修订 2")
        with page.expect_response("**/api/v1/runs/*/draft?view=live") as rejected:
            page.locator("#saveDraftButton").click()
        assert rejected.value.status == 409
        expect(page.locator("#errorBanner")).to_be_visible()
        expect(page.locator("#draftEditor")).to_have_value("作者基于R1的修改。")
        assert app.state.service.store.snapshot(run_id)["draft_text"] == "第二页保存的R2。"
        page.reload(wait_until="domcontentloaded")
        expect(page.locator("#draftEditor")).to_have_value("第二页保存的R2。")
        expect(page.locator("#localRecoveryPanel")).to_be_visible()
        expect(page.locator("#localRecoveryText")).to_have_value("作者基于R1的修改。")
        page.locator("#restoreLocalDraftButton").click()
        page.locator("#saveDraftButton").click()
        expect(page.locator("#draftRevision")).to_have_text("草稿修订 3")
        assert app.state.service.store.snapshot(run_id)["draft_text"] == "作者基于R1的修改。"


def test_live_save_keeps_subsequent_edits_and_reports_real_memory_failure_on_entry(tmp_path: Path) -> None:
    """依赖：真实浏览器、草稿HTTP和作品注册。输入：已准备run、被清空的时间线注册、延迟回执。
    输出：草稿保存与故障各自可见，后续编辑保留，修复注册后可重读。实现：暂扣真实提交响应并实际进入记忆页。
    """
    with writing_workspace(tmp_path) as (page, browser, app, backend, root):
        page.locator("#useHarnessButton").click()
        page.locator("#outlineInput").fill("把旧钥匙藏在雨棚下面。")
        page.locator("#startButton").click()
        expect(page.locator("#runStatus")).to_have_text("已准备，等待外部写作工具")
        run_id = parse_qs(urlparse(page.url).query)["run"][0]
        timeline = root / "stories" / "demo" / "common" / "registry" / "timelines.yaml"
        original = timeline.read_bytes()
        memory_path = f"**/api/v1/runs/{run_id}/memory"
        live_save_path = f"**/api/v1/runs/{run_id}/draft?view=live"
        held = []
        memory_requests = []

        def hold_save(route) -> None:
            """依赖：真实草稿API。输入：作者保存请求。输出：暂扣的route。实现：由测试控制原请求的提交和回执交付。"""
            held.append(route)

        def track_memory(request) -> None:
            """依赖：Playwright请求事件。输入：浏览器真实请求。输出：当前run记忆请求记录。实现：只匹配作者浏览端点。"""
            if request.url.endswith(f"/api/v1/runs/{run_id}/memory"):
                memory_requests.append(request)

        page.route(live_save_path, hold_save)
        page.on("request", track_memory)
        try:
            write_yaml(timeline, {"timelines": []})
            page.locator("#draftEditor").fill("本次提交的正文。")
            with page.expect_request(live_save_path):
                page.locator("#saveDraftButton").click()
            expect(page.locator("#saveDraftButton")).to_be_disabled()
            assert len(held) == 1
            route = held[0]
            response = route.fetch()
            assert response.status == 200
            receipt = response.json()
            assert receipt["saved_draft_revision"] == 1
            assert receipt["memory_read"]["status"] == "not_requested"
            page.locator("#draftEditor").fill("等待回执时输入的下一版。")
            route.fulfill(response=response)
            page.unroute(live_save_path, hold_save)
            expect(page.locator("#draftRevision")).to_have_text("草稿修订 1")
            expect(page.locator("#draftEditState")).to_contain_text("草稿已保存 · 修订 1，编辑器仍有未保存的修改")
            expect(page.locator("#draftEditor")).to_have_value("等待回执时输入的下一版。")
            assert app.state.service.store.snapshot(run_id)["draft_text"] == "本次提交的正文。"
            assert memory_requests == []

            page.locator("#homeButton").click()
            with page.expect_response(memory_path):
                page.locator('.tile[data-tile="memory"]').click()
            expect(page.locator("#memoryStatus")).to_contain_text("读取失败")
            assert len(memory_requests) == 1
        finally:
            timeline.write_bytes(original)
        with page.expect_response(memory_path):
            page.locator("#refreshMemoryButton").click()
        expect(page.locator("#memoryStatus")).to_contain_text("本次查询范围已查完")
        assert len(memory_requests) == 2
        page.locator("#homeButton").click()
        page.locator('.tile[data-tile="workbench"]').click()
        expect(page.locator("#draftEditState")).to_contain_text("草稿已保存 · 修订 1")
        expect(page.locator("#draftEditor")).to_have_value("等待回执时输入的下一版。")
        page.locator("#saveDraftButton").click()
        expect(page.locator("#draftEditState")).to_contain_text("草稿已保存 · 修订 2")
        assert app.state.service.store.snapshot(run_id)["draft_text"] == "等待回执时输入的下一版。"
        assert len(memory_requests) == 2


def test_partial_save_receipt_keeps_canonical_parent_prefix_when_snapshot_fails(tmp_path: Path, monkeypatch) -> None:
    """依赖：真实HTTP和子run、持久正文及故障投影。输入：父前缀、子轮部分文本和另有编辑的作者。
    输出：提交修订、完整独立预览和正确后续CAS。实现：仅故障提交后的状态读取，两个草稿写入照常走同一服务。
    """
    with writing_workspace(tmp_path) as (page, browser, app, backend, root):
        client = BackendClient(backend)
        parent = client.request("/api/v1/runs", {
            "story_id": "demo", "timeline_id": "main", "driver": "harness",
            "outline": "第一章接续父稿。", "request": "父文本。",
        })
        prefix, suffix = "父稿正文。", "已收到的追加开头。"
        parent_ref = client.request(client.run_path(parent["run_id"], "/harness-tool"), {
            "name": "save_draft", "arguments": {"text": prefix, "expected_revision": 0},
            "operation_id": "parent-draft",
        })
        child = client.request(f"/api/v1/sessions/{parent['session_id']}/feedback", {
            "base_run_id": parent["run_id"], "base_ref": parent_ref,
            "selected_parent_checkpoint": parent_ref["checkpoint_id"], "request": "从父稿继续。",
        })
        run_id = child["run_id"]
        service = app.state.service
        service.store.receive(run_id, "partial-turn", suffix, complete=False)
        client.request(client.run_path(run_id, "/cancel"), {})
        partial_revision = service.store.snapshot(run_id)["draft_revision"] + 1
        page.goto(backend + f"/?run={run_id}#write", wait_until="domcontentloaded")
        expect(page.locator("#saveReceivedButton")).to_be_enabled()
        expect(page.locator("#livePreview")).to_contain_text(suffix)
        page.locator("#draftEditor").fill("仍需保留的独立作者编辑。")
        live_save_path = f"**/api/v1/runs/{run_id}/draft?view=live"

        def fail_run_view(run_id, *, view, after=0):
            """依赖：作者保存后的运行视图。输入：run、view和游标。输出：读盘故障。实现：阻断状态投影，草稿存储保持真实。"""
            raise OSError("temporary run projection failure")

        with monkeypatch.context() as fault:
            fault.setattr(service, "_workspace_run_view", fail_run_view)
            with page.expect_response(live_save_path) as saved:
                page.locator("#saveReceivedButton").click()
            receipt = saved.value.json()
            assert saved.value.status == 200
            assert receipt["snapshot_read"]["status"] == "unavailable"
            assert receipt["saved_draft_text"] == prefix + suffix
            assert receipt["saved_draft_revision"] == partial_revision
            assert "snapshot_view" not in receipt
            expect(page.locator("#draftRevision")).to_have_text(f"草稿修订 {partial_revision}")
            expect(page.locator("#draftEditState")).to_contain_text(f"部分草稿已保存 · 修订 {partial_revision}")
            expect(page.locator("#draftEditState")).to_contain_text("运行状态暂时无法读取")
            expect(page.locator("#savedPartialPreview")).to_have_text(prefix + suffix)
            expect(page.locator("#draftEditor")).to_have_value("仍需保留的独立作者编辑。")
            expect(page.locator("#saveReceivedButton")).not_to_be_visible()
        assert service.store.snapshot(run_id)["draft_text"] == prefix + suffix
        with page.expect_request(live_save_path) as request:
            page.locator("#saveDraftButton").click()
        assert request.value.post_data_json["expected_revision"] == partial_revision
        expect(page.locator("#draftEditState")).to_contain_text(f"草稿已保存 · 修订 {partial_revision + 1}")
        assert service.store.snapshot(run_id)["draft_text"] == "仍需保留的独立作者编辑。"


def test_committed_start_without_response_retries_original_identity_after_refresh(tmp_path: Path) -> None:
    """依赖：Playwright网络故障/真实幂等prepare。输入：服务器已提交但浏览器回执断开。
    输出：刷新不自动POST，显式重试复用原参数/ID，只有原run。实现：route.fetch真实提交后abort客户端回执，再重读页面。
    """
    with writing_workspace(tmp_path) as (page, browser, app, backend, root):
        attempts = []

        def drop_receipt(route) -> None:
            """依赖：真实HTTP route。输入：开始请求。输出：客户端网络失败。实现：保存原参数与已提交run，再只丢回执。"""
            response = route.fetch()
            attempts.append((route.request.post_data_json, response.json()["run_id"]))
            route.abort()

        page.locator("#useHarnessButton").click()
        page.locator("#outlineInput").fill("原始待确认输入。")
        page.route("**/api/v1/runs", drop_receipt)
        page.locator("#startButton").click()
        expect(page.locator("#runStatus")).to_have_text("请求结果待确认")
        page.unroute("**/api/v1/runs", drop_receipt)
        page.reload(wait_until="domcontentloaded")
        expect(page.locator("#errorBanner")).to_contain_text("上次待确认")
        assert len(attempts) == 1
        page.locator("#outlineInput").fill("回执丢失后新改的输入。")
        with page.expect_request("**/api/v1/runs") as retried:
            page.locator("#startButton").click()
        assert retried.value.post_data_json == attempts[0][0]
        expect(page.locator("#runStatus")).to_have_text("已准备，等待外部写作工具")
        assert parse_qs(urlparse(page.url).query)["run"][0] == attempts[0][1]
        assert app.state.service.store.snapshot(attempts[0][1])["request_snapshot"]["outline"] == "原始待确认输入。"
        expect(page.locator("#outlineInput")).to_have_value("回执丢失后新改的输入。")


def test_storage_failure_keeps_editor_and_blocks_clearing_actions(tmp_path: Path) -> None:
    """依赖：真实浏览器存储错误/范围切换。输入：临时保存抛QuotaExceededError。
    输出：失败状态可见，切书/开run不清旧正文。实现：只故障作者副本保存，不模拟UI逻辑或后端结果。
    """
    with writing_workspace(tmp_path) as (page, browser, app, backend, root):
        page.locator("#useHarnessButton").click()
        page.evaluate("""() => {
          const original = Storage.prototype.setItem;
          Storage.prototype.setItem = function(key, value) {
            if (key.startsWith('novel-rag.inputs.v1:')) throw new DOMException('full', 'QuotaExceededError');
            return original.call(this, key, value);
          };
        }""")
        page.locator("#outlineInput").fill("本机未能保存的大纲。")
        page.locator("#draftEditor").fill("仍留在编辑器的正文。")
        expect(page.locator("#localSaveStatus")).to_contain_text("保存失败")
        page.locator("#storySelect").select_option("other")
        expect(page.locator("#storySelect")).to_have_value("demo")
        expect(page.locator("#draftEditor")).to_have_value("仍留在编辑器的正文。")
        page.locator("#startButton").click()
        expect(page.locator("#errorBanner")).to_contain_text("临时保存不可用")
        assert "run=" not in page.url
        assert app.state.service._models == {}


def test_committed_adoption_without_receipt_keeps_original_target_and_parameters(tmp_path: Path) -> None:
    """依赖：真实采用/HTTP回执故障/浏览器恢复。输入：已采用但未确认的R1与随后改动。
    输出：原operation/坐标/修订原样重试，没有第二正式章节，较新编辑保留。实现：真实提交后丢回执，刷新并修改当前表单后确认旧操作。
    """
    with writing_workspace(tmp_path) as (page, browser, app, backend, root):
        page.locator("#useHarnessButton").click()
        page.locator("#outlineInput").fill("采用只发生一次。")
        page.locator("#startButton").click()
        expect(page.locator("#runStatus")).to_have_text("已准备，等待外部写作工具")
        page.locator("#draftEditor").fill("采用的原正文。")
        page.locator("#saveDraftButton").click()
        expect(page.locator("#draftRevision")).to_have_text("草稿修订 1")
        for selector, value in (("#volumeInput", "1"), ("#chapterInput", "3"), ("#sceneInput", "1")):
            page.locator(selector).fill(value)
        committed = []

        def drop_adoption_receipt(route) -> None:
            """依赖：真实采用route。输入：冻结envelope。输出：网络失败。实现：先真实提交，再记录参数并中断回执。"""
            response = route.fetch()
            assert response.status == 200
            committed.append(route.request.post_data_json)
            route.abort()

        page.route("**/api/v1/runs/*/adopt", drop_adoption_receipt)
        page.locator("#adoptButton").click()
        expect(page.locator("#runStatus")).to_have_text("采用结果待确认")
        page.unroute("**/api/v1/runs/*/adopt", drop_adoption_receipt)
        page.reload(wait_until="domcontentloaded")
        expect(page.locator("#errorBanner")).to_contain_text("待确认的采用")
        page.locator("#chapterInput").fill("4")
        page.locator("#draftEditor").fill("采用回执后另外改的正文。")
        with page.expect_request("**/api/v1/runs/*/adopt") as retried:
            page.locator("#adoptButton").click()
        assert retried.value.post_data_json == committed[0]
        expect(page.locator("#runStatus")).to_have_text("采用请求已返回")
        expect(page.locator("#draftEditor")).to_have_value("采用回执后另外改的正文。")
        history = [read_yaml_mapping(path) for path in (root / "stories" / "demo" / "timelines" / "main" / "history").rglob("*.yaml")]
        assert len(history) == 1 and history[0]["metadata"]["chapter"] == 3


def test_setup_creation_layout_and_broken_local_copy_are_actionable(tmp_path: Path) -> None:
    """依赖：真实设置/新作品/布局/localStorage。输入：无profile、标题和损坏记录。
    输出：新书可进入零配置写作，首屏大纲与按钮可见，坏记录保留提示；手机无溢出。实现：实际dialog/键盘及HTTP磁盘结果取证。
    """
    with writing_workspace(tmp_path) as (page, browser, app, backend, root):
        expect(page.locator("#setupHint")).to_be_visible()
        page.locator("#setupButton").click()
        page.locator("#refreshProfilesButton").click()
        expect(page.locator("#setupStatus")).to_contain_text("尚未找到配置")
        page.locator("#closeSetupButton").click()
        page.locator("#newStoryButton").click()
        page.locator("#newStoryTitleInput").fill("新的独立小说")
        page.locator("#createStoryButton").click()
        expect(page.locator("#newStoryDialog")).not_to_be_visible()
        expect(page.locator("#storySelect option:checked")).to_have_text("新的独立小说")
        expect(page.locator("#draftEditor")).to_have_value("")
        page.locator("#useHarnessButton").click()
        expect(page.locator("#startButton")).to_be_enabled()
        for selector in ("#outlineInput", "#startButton"):
            box = page.locator(selector).bounding_box()
            assert box and box["y"] >= 0 and box["y"] + box["height"] <= 768, (selector, box)
        page.locator("#outlineInput").fill("用于建立本机副本。")
        corrupted_key = page.evaluate("""() => {
          const story = document.getElementById('storySelect').value;
          const key = Object.keys(localStorage).find(key => key.startsWith('novel-rag.inputs.v1:') && JSON.parse(localStorage.getItem(key)).scope.story_id === story);
          localStorage.setItem(key + '-broken', '{bad-json'); return key + '-broken';
        }""")
        page.reload(wait_until="domcontentloaded")
        expect(page.locator("#localSaveStatus")).to_contain_text("损坏")
        assert page.evaluate("key => localStorage.getItem(key)", corrupted_key) == "{bad-json"
        page.set_viewport_size({"width": 390, "height": 844})
        assert page.evaluate("() => document.documentElement.scrollWidth <= innerWidth")
        assert len(read_yaml_mapping(root / "registry" / "stories.yaml")["stories"]) == 3


def test_initial_unconfigured_layout_and_native_dialog_escape_keep_writer_focus(tmp_path: Path) -> None:
    """依赖：原生dialog/Metro键盘/初始1366页面。输入：无profile首屏及两个弹窗Escape。
    输出：大纲/开始按钮在祖先可视区、modal关闭后仍写作并返回入口焦点。实现：不切harness或滚动，逐层求裁切交集，再实际按Escape。
    """
    with writing_workspace(tmp_path) as (page, browser, app, backend, root):
        expect(page.locator("#setupHint")).to_be_visible()
        for selector in ("#outlineInput", "#startButton"):
            visibility = page.locator(selector).evaluate("""element => {
                const bounds = element.getBoundingClientRect();
                let top = 0, bottom = innerHeight;
                for (let parent = element.parentElement; parent; parent = parent.parentElement) {
                    const style = getComputedStyle(parent);
                    if (/^(auto|scroll|hidden|clip)$/.test(style.overflowY)) {
                        const rect = parent.getBoundingClientRect();
                        top = Math.max(top, rect.top + parent.clientTop);
                        bottom = Math.min(bottom, rect.top + parent.clientTop + parent.clientHeight);
                    }
                }
                return {top: bounds.top, bottom: bounds.bottom, clipTop: top, clipBottom: bottom};
            }""")
            assert visibility["top"] >= visibility["clipTop"] and visibility["bottom"] <= visibility["clipBottom"], (selector, visibility)
        page.locator("#setupButton").click()
        expect(page.locator("#refreshProfilesButton")).to_be_focused()
        page.keyboard.press("Escape")
        expect(page.locator("#setupDialog")).not_to_be_visible()
        expect(page.locator("#setupButton")).to_be_focused()
        assert page.url.endswith("#write")
        page.locator("#newStoryButton").click()
        page.keyboard.press("Escape")
        expect(page.locator("#newStoryDialog")).not_to_be_visible()
        expect(page.locator("#newStoryButton")).to_be_focused()
        assert page.url.endswith("#write")
