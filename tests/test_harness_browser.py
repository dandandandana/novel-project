from __future__ import annotations

import json
from pathlib import Path

import pytest

from native_http_fixture import workspace_server
from novel_rag.harness import BackendClient
from novel_rag.web.app import create_app
from writer_fixtures import make_library
from test_workspace_browser import installed_browser_path


def test_harness_writer_handoff_runs_end_to_end_in_real_browser(tmp_path: Path) -> None:
    """依赖：已安装浏览器、共同finder、Playwright、workspace_server、临时作品库、BackendClient和真实Web/RunService。
    输入：无profile的临时workspace、原纲、外部保存稿、作者修改和反馈。
    输出：真实浏览器完成prepared/上下文/保存/停止/反馈/恢复，且临时History未写入。
    实现：真实loopback经BackendClient提交外部工具，再用bootstrap实际namespace注入冲突选择并按公开URL恢复子run。
    """
    playwright_module = pytest.importorskip("playwright.sync_api")
    browser_path = installed_browser_path()

    root = make_library(tmp_path)
    workspace = tmp_path / "workspace"
    app = create_app(root, workspace, tmp_path / "model-config.json")
    assert app.state.service.config.list_profiles() == []
    outline = "原始大纲：甲把唯一的铜钥匙交还给乙，随后独自离开。"
    external_text = "外部检查点：甲接过铜钥匙，屋檐的雨水落在门槛上。"
    author_text = "作者定稿：甲接过铜钥匙，听见屋檐雨水落在门槛上。"
    feedback_text = "沿用这段正文，只写甲离开后的动作。"
    suffix = "后缀正文：甲把钥匙放进口袋，独自走进雨里。"
    history_dir = root / "stories" / "demo" / "timelines" / "main" / "history"
    page_errors: list[str] = []

    with workspace_server(app) as backend:
        client = BackendClient(backend)
        with playwright_module.sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, executable_path=str(browser_path))
            try:
                page = browser.new_page(viewport={"width": 1360, "height": 980}, device_scale_factor=1)
                page.on("pageerror", lambda error: page_errors.append(str(error)))
                page.goto(backend + "/", wait_until="domcontentloaded")
                expect = playwright_module.expect
                page.locator('.tile[data-action="workbench"]').click()
                expect(page.locator("#workspaceView")).to_be_visible()
                expect(page.locator("#runStatus")).to_have_text("已连接本地工作区")
                expect(page.locator("#startButton")).to_be_disabled()
                expect(page.locator("#profileSelect")).to_have_attribute("required", "")
                expect(page.locator("#storySelect")).to_have_value("demo")
                expect(page.locator("#timelineSelect")).to_have_value("main")

                page.locator("#driverSelect").select_option("harness")
                expect(page.locator("#profileSelect")).to_be_disabled()
                expect(page.locator("#profileSelect")).not_to_have_attribute("required", "")
                expect(page.locator("#startButton")).to_be_enabled()
                expect(page.locator("#startButton")).to_have_text("准备交接")
                page.locator("#outlineInput").fill(outline)
                page.locator("#requestInput").fill("写出这场交接，保存后续动作时父稿只保留一次。")
                page.locator("#startButton").click()

                expect(page.locator("#runStatus")).to_have_text("已准备，等待外部写作工具", timeout=15000)
                expect(page.locator("#cancelButton")).to_be_enabled()
                parent_id = page.evaluate("new URL(window.location.href).searchParams.get('run')")
                assert isinstance(parent_id, str) and parent_id
                parent = app.state.service.store.load(parent_id)
                assert parent["driver"] == "harness"
                assert parent["profile_name"] is None
                assert parent["status"] == "prepared"
                assert parent["request_snapshot"]["outline"] == outline
                assert app.state.service._models == {}

                command = f"python -m novel_rag.cli harness mcp --backend {backend} --run-id {parent_id}"
                expect(page.locator("#harnessCommand")).to_have_text(command)
                assert app.state.token not in command
                assert app.state.token not in page.locator("body").inner_text()
                page.locator("#harnessPanel > summary").click()
                page.locator("#harnessContextButton").click()
                expect(page.locator("#harnessContextStatus")).to_have_text(
                    "交接上下文已载入；可在只读文本框中选中并复制。", timeout=10000
                )
                first_context = json.loads(page.locator("#harnessContextOutput").input_value())
                assert first_context["run_id"] == parent_id
                assert first_context["driver"] == "harness"
                assert first_context["instructions"]
                assert first_context["messages"]
                assert first_context["context_view"] == "model"
                assert first_context["tool_names"] == [definition["name"] for definition in app.state.service.tool_dispatcher(parent_id).definitions()]
                assert app.state.token not in json.dumps(first_context, ensure_ascii=False)

                external_result = client.request(
                    client.run_path(parent_id, "/harness-tool"),
                    {
                        "name": "save_draft",
                        "arguments": {"text": external_text, "expected_revision": 0},
                        "operation_id": "browser-parent-save",
                    },
                )
                assert external_result["kind"] == "draft"
                expect(page.locator("#draftEditor")).to_have_value(external_text, timeout=15000)
                expect(page.locator("#saveDraftButton")).to_be_enabled()
                page.locator("#harnessContextButton").click()
                expect(page.locator("#harnessContextStatus")).to_have_text(
                    "交接上下文已载入；可在只读文本框中选中并复制。", timeout=10000
                )
                refreshed_context = json.loads(page.locator("#harnessContextOutput").input_value())
                assert refreshed_context["saved_draft"]["source_ref"] == external_result
                read_saved = client.request(client.run_path(parent_id, "/harness-tool"),
                    {"name": "read_document", "arguments": refreshed_context["saved_draft"]["read_arguments"]})
                assert read_saved["text"] == external_text
                assert client.request(client.run_path(parent_id, "/harness-context"))["saved_draft"]["text"] == external_text
                assert external_result == refreshed_context["draft_ref"]

                page.locator("#draftEditor").fill(author_text)
                page.locator("#saveDraftButton").click()
                expect(page.locator("#draftEditor")).to_have_value(author_text)
                expect(page.locator("#draftRevision")).to_have_text("草稿修订 2", timeout=10000)
                authored_parent = app.state.service.store.load(parent_id)
                assert authored_parent["author_revision"] == authored_parent["draft_revision"] == 2
                assert authored_parent["draft_text"] == author_text
                assert not list(history_dir.rglob("*.yaml"))

                for selector in ("#volumeInput", "#chapterInput", "#sceneInput"):
                    page.locator(selector).fill("1")
                expect(page.locator("#adoptButton")).to_be_enabled()
                page.locator("#adoptButton").click()
                expect(page.locator("#draftEditState")).to_have_text("正式作品已返回采用结果。", timeout=15000)
                adopted_history = list(history_dir.rglob("*.yaml"))
                assert len(adopted_history) == 1
                assert author_text in adopted_history[0].read_text(encoding="utf-8")

                page.locator("#homeButton").click()
                expect(page.locator("#launcherView")).to_be_visible()
                assert page.evaluate("new URL(window.location.href).searchParams.get('run')") == parent_id
                page.locator('.tile[data-action="workbench"]').click()
                expect(page.locator("#workspaceView")).to_be_visible()
                expect(page.locator("#draftEditor")).to_have_value(author_text)
                expect(page.locator("#draftEditState")).to_have_text("正式作品已返回采用结果。")
                assert page.evaluate("new URL(window.location.href).searchParams.get('run')") == parent_id

                page.locator("#driverSelect").select_option("builtin")
                expect(page.locator("#driverSelect")).to_have_value("builtin")
                page.wait_for_timeout(2800)
                expect(page.locator("#driverSelect")).to_have_value("builtin")
                page.locator("#driverSelect").select_option("harness")

                expect(page.locator("#cancelButton")).to_have_text("停止本地工具")
                page.locator("#cancelButton").click()
                expect(page.locator("#runStatus")).to_have_text(
                    "已停止本地工具，外部模型请在其宿主停止", timeout=10000
                )
                cancelled_parent = app.state.service.store.load(parent_id)
                assert cancelled_parent["status"] == "cancelled"
                assert cancelled_parent["cancel_requested"] is True
                rejected = client.request(
                    client.run_path(parent_id, "/harness-tool"),
                    {
                        "name": "save_draft",
                        "arguments": {"text": "停止后不应接受的新正文。", "expected_revision": 2},
                        "operation_id": "browser-parent-after-cancel",
                    },
                )
                assert rejected["ok"] is False
                assert rejected["error"]["code"] == "cancelled"
                assert app.state.service.store.load(parent_id)["draft_text"] == author_text

                page.locator("#requestInput").fill(feedback_text)
                page.locator("#feedbackButton").click()
                expect(page.locator("#runStatus")).to_have_text("已准备，等待外部写作工具", timeout=15000)
                child_id = page.evaluate("new URL(window.location.href).searchParams.get('run')")
                assert isinstance(child_id, str) and child_id and child_id != parent_id
                child = app.state.service.store.load(child_id)
                assert child["driver"] == "harness"
                assert child["profile_name"] is None
                assert child["status"] == "prepared"
                assert child["parent_run_id"] == parent_id
                assert child["request_snapshot"]["outline"] == outline
                assert child["request_snapshot"]["request"] == feedback_text
                assert child["binding"]["base_ref"] == authored_parent["draft_ref"]
                assert child["binding"]["output_mode"] == "append_suffix"
                assert child["draft_text"] == author_text

                child_result = client.request(
                    client.run_path(child_id, "/harness-tool"),
                    {
                        "name": "save_draft",
                        "arguments": {"text": suffix, "expected_revision": child["draft_revision"]},
                        "operation_id": "browser-child-save",
                    },
                )
                assert child_result["kind"] == "draft"
                assembled = app.state.service.store.resolve_draft(child_result)[1]
                assert assembled == author_text + suffix
                assert assembled.count(author_text) == 1
                assert len(list(history_dir.rglob("*.yaml"))) == 1

                restored_context = browser.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=1)
                restored_page = restored_context.new_page()
                restored_page.on("pageerror", lambda error: page_errors.append(str(error)))
                restored_page.goto(backend + "/", wait_until="domcontentloaded")
                expect(restored_page.locator("#runStatus")).to_have_text("已连接本地工作区")
                restored_bootstrap = restored_page.request.get(backend + "/api/v1/bootstrap").json()
                selection_key = f"novel-rag.workspace.{restored_bootstrap['workspace_id']}"
                restored_page.evaluate(
                    "([key, value]) => localStorage.setItem(key, JSON.stringify(value))",
                    [selection_key, {
                        "run_id": "run-from-old-local-storage",
                        "story_id": "other",
                        "timeline_id": "main",
                        "driver": "builtin",
                        "profile_name": "",
                    }],
                )
                restored_page.goto(backend + f"/?run={child_id}", wait_until="domcontentloaded")
                expect(restored_page.locator("#workspaceView")).to_be_visible()
                expect(restored_page.locator("#writeSurface")).to_be_visible()
                expect(restored_page.locator("#runStatus")).to_have_text("已准备，等待外部写作工具", timeout=15000)
                expect(restored_page.locator("#storySelect")).to_have_value("demo")
                expect(restored_page.locator("#timelineSelect")).to_have_value("main")
                expect(restored_page.locator("#driverSelect")).to_have_value("harness")
                expect(restored_page.locator("#draftEditor")).to_have_value(assembled)
                stored = json.loads(restored_page.evaluate("key => localStorage.getItem(key)", selection_key))
                assert stored["run_id"] == child_id
                assert stored["story_id"] == "demo"
                assert stored["driver"] == "harness"
                restored_command = f"python -m novel_rag.cli harness mcp --backend {backend} --run-id {child_id}"
                expect(restored_page.locator("#harnessCommand")).to_have_text(restored_command)
                assert app.state.token not in restored_page.locator("body").inner_text()

                restored_page.keyboard.press("Tab")
                restored_page.locator("#driverSelect").focus()
                restored_page.keyboard.press("Home")
                expect(restored_page.locator("#driverSelect")).to_have_value("builtin")
                restored_page.wait_for_timeout(2800)
                expect(restored_page.locator("#driverSelect")).to_have_value("builtin")
                restored_page.keyboard.press("End")
                expect(restored_page.locator("#driverSelect")).to_have_value("harness")
                restored_page.locator("#harnessPanel > summary").click()
                restored_page.locator("#harnessContextButton").click()
                expect(restored_page.locator("#harnessContextStatus")).to_have_text(
                    "交接上下文已载入；可在只读文本框中选中并复制。", timeout=10000
                )
                restored_payload = json.loads(restored_page.locator("#harnessContextOutput").input_value())
                assert restored_payload["saved_draft"]["total_characters"] == len(assembled)
                assert restored_payload["saved_draft"]["source_ref"] == restored_payload["draft_ref"]
                assert client.request(client.run_path(child_id, "/harness-context"))["saved_draft"]["text"] == assembled
                dimensions = restored_page.evaluate("""() => ({
                  viewport: window.innerWidth,
                  document: document.documentElement.scrollWidth,
                  body: document.body.scrollWidth
                })""")
                assert dimensions["viewport"] == 390
                assert dimensions["document"] <= dimensions["viewport"], dimensions
                assert dimensions["body"] <= dimensions["viewport"], dimensions
                assert app.state.token not in restored_page.locator("#harnessContextOutput").input_value()
                assert not page_errors
                restored_context.close()
            finally:
                browser.close()

    assert len(list(history_dir.rglob("*.yaml"))) == 1
