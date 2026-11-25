from __future__ import annotations

import asyncio
from pathlib import Path

from novel_rag.documents import read_yaml_mapping
from novel_rag.identity import GraphKey, StoryCoordinate
from novel_rag.service import load_story_sources
from novel_rag.web.app import create_app
from test_memory_service_v3 import _create_run, _document_position, _formal_batch, _write_projection
from test_web_workspace import _asgi_client, _token_headers
from writer_fixtures import make_library, put_document, write_yaml


def test_preference_reads_and_writes_check_registration_without_listing_sources(tmp_path: Path, monkeypatch) -> None:
    """依赖：ASGI、注册表和偏好CAS。输入：已注册、未注册及错误时间线。输出：正常读写或作用域拒绝。实现：禁止枚举正文，核对返回版本与拒绝写入后的文件。"""
    from novel_rag import service as source_service

    def forbid_sources(*args, **kwargs):
        """依赖：断言。输入：正文枚举参数。输出：测试失败。实现：标记偏好请求越过注册表读取了正文目录。"""
        raise AssertionError("偏好请求枚举了作品正文")

    async def scenario():
        """依赖：真实HTTP路由。输入：临时库与偏好版本。输出：保存及作用域断言。实现：在同一服务先写有效偏好，再尝试错误作品线。"""
        root = make_library(tmp_path)
        put_document(root, "first", "这份正文与偏好无关。")
        app = create_app(root, tmp_path / "workspace", tmp_path / "unused.json")
        monkeypatch.setattr(source_service, "_paths_for_scope", forbid_sources)
        async with _asgi_client(app) as client:
            headers = _token_headers(app.state.token)
            url = "/api/v1/preferences/demo"
            first = await client.get(url, headers=headers)
            assert first.status_code == 200
            data = {"content": "保留叙述节奏。", "expected_revision": first.json()["expected_revision"]}
            saved = await client.put(url, headers=headers, json=data)
            assert saved.status_code == 200 and saved.json()["content"] == data["content"]
            assert (await client.get("/api/v1/preferences/unknown", headers=headers)).status_code == 400
            wrong = await client.put(url + "?timeline_id=missing", headers=headers,
                                     json={"content": "错误分支", "expected_revision": saved.json()["expected_revision"]})
            assert wrong.status_code == 400
            assert (await client.get(url, headers=headers)).json() == saved.json()

    asyncio.run(scenario())


def test_draft_http_receipt_separates_saved_revision_from_memory_registry_error(tmp_path: Path) -> None:
    """依赖：真实HTTP保存、临时时间线注册表和Store。输入：失效及恢复后的注册表、草稿CAS。输出：提交回执、独立记忆状态及真实冲突。实现：经full/live保存再核对每个实际版本。"""
    async def scenario():
        """依赖：ASGI和隔离库。输入：一个harness任务与作者修改。输出：各次响应及持久稿一致。实现：准备后令时间线暂时无效，再恢复注册核读。"""
        root = make_library(tmp_path)
        app = create_app(root, tmp_path / "workspace", tmp_path / "unused.json")
        registry = root / "stories/demo/common/registry/timelines.yaml"
        original = registry.read_bytes()
        async with _asgi_client(app) as client:
            headers = _token_headers(app.state.token)
            created = await client.post("/api/v1/runs", headers=headers,
                                        json={"driver": "harness", "story_id": "demo", "outline": "大纲"})
            run_url = "/api/v1/runs/" + created.json()["run_id"]
            save_url = run_url + "/draft"
            data = {"expected_revision": 0, "text": "第一稿。"}
            assert (await client.put(save_url + "?view=typo", headers=headers, json=data)).status_code == 400
            write_yaml(registry, {"timelines": []})
            first = await client.put(save_url, headers=headers, json=data)
            assert first.status_code == 200, first.text
            receipt = first.json()
            assert receipt["saved_draft_ref"] == receipt["draft_ref"]
            assert receipt["saved_draft_revision"] == receipt["draft_revision"] == 1
            assert receipt["saved_draft_text"] == receipt["draft_text"] == data["text"]
            assert receipt["memory_read"]["status"] == "unavailable" and "memory_state" not in receipt
            assert (await client.get(run_url, headers=headers)).status_code == 400
            assert (await client.put(save_url, headers=headers, json=data)).status_code == 409
            light = await client.put(save_url + "?view=live", headers=headers,
                                     json={"expected_revision": 1, "text": "第二稿。"})
            assert light.status_code == 200, light.text
            assert light.json()["memory_read"] == {"status": "not_requested"}
            assert light.json()["saved_draft_revision"] == 2 and "tool_results" not in light.json()
            registry.write_bytes(original)
            final = await client.put(save_url, headers=headers, json={"expected_revision": 2, "text": "第三稿。"})
            assert final.status_code == 200, final.text
            assert final.json()["memory_read"] == {"status": "available"}
            assert final.json()["memory_state"]["memory_revision"] == final.json()["memory_revision"]
            assert final.json()["saved_draft_revision"] == 3 and len(final.json()["drafts"]) == 3

    asyncio.run(scenario())


def test_preferences_and_canon_api_enforce_hash_revision_and_scope_cas(tmp_path: Path) -> None:
    """验证真实偏好与Canon API的双边界、旧CAS拒绝和源字节保护。

    依赖：create_app真实lifespan、临时YAML库、HTTPX ASGI client及原偏好/源编辑owner。
    输入：demo偏好文件、common Canon YAML和有效/过期/跨scope编辑请求。
    输出：成功编辑的新版本、冲突响应、旧字节备份及未经授权scope下的原文保护。
    实现：所有读写经带token的真实Web路由，再回读YAML和source-versions逐字节核验。
    """
    async def scenario() -> None:
        """依赖：真实FastAPI lifespan、偏好和资料路由及临时作品库。
        输入：初始偏好、Canon文档与一组有效/失效CAS参数。
        输出：偏好hash CAS、Canon revision/hash CAS、路径隔离的HTTP断言。
        实现：先写入已知旧版本，再经API逐步编辑并比较源文件与保护备份原始字节。
        """
        root = make_library(tmp_path)
        workspace = tmp_path / "workspace"
        config_path = tmp_path / "model-config.json"
        preferences_path = root / "stories" / "demo" / "author-preferences.txt"
        old_preferences = "【POV】贴近主角观察，不替其他人物猜心。\n".encode("utf-8")
        preferences_path.write_bytes(old_preferences)
        canon_path = root / "stories" / "demo" / "common" / "canon" / "canon-lore.yaml"
        write_yaml(canon_path, {
            "metadata": {
                "document_id": "canon-lore", "story_id": "demo", "timeline_id": "main",
                "document_type": "canon", "title": "山城设定", "status": "canon",
                "version": "1", "source_revision": 1,
            },
            "content": "山城建在两条河流交汇处。",
        })
        initial_canon_bytes = canon_path.read_bytes()
        app = create_app(root, workspace, config_path)

        async with _asgi_client(app) as client:
            bootstrap = (await client.get("/api/v1/bootstrap")).json()
            headers = _token_headers(bootstrap["token"])
            preference_url = "/api/v1/preferences/demo?timeline_id=main"
            preference_get = await client.get(preference_url, headers=headers)
            assert preference_get.status_code == 200, preference_get.text
            old_preference_revision = preference_get.json()["expected_revision"]
            assert preference_get.json()["content"] == old_preferences.decode("utf-8")

            new_preferences = "【POV】贴近主角观察，不替其他人物猜心。\n【对白】保留停顿和潜台词。\n"
            preference_put = await client.put(preference_url, headers=headers, json={
                "content": new_preferences, "expected_revision": old_preference_revision,
            })
            assert preference_put.status_code == 200, preference_put.text
            assert preference_put.json()["content"] == new_preferences
            assert preference_put.json()["expected_revision"] != old_preference_revision
            expected_preference_bytes = new_preferences.encode("utf-8")
            assert preferences_path.read_bytes() == expected_preference_bytes
            preference_backup = preferences_path.with_suffix(".txt.bak")
            assert preference_backup.read_bytes() == old_preferences

            stale_preference = await client.put(preference_url, headers=headers, json={
                "content": "过期偏好不得覆盖。\n", "expected_revision": old_preference_revision,
            })
            assert stale_preference.status_code == 409, stale_preference.text
            assert stale_preference.json()["error"]["code"] == "revision_conflict"
            assert preferences_path.read_bytes() == expected_preference_bytes

            wrong_preference_scope = await client.get(
                "/api/v1/preferences/demo?timeline_id=other", headers=headers,
            )
            assert wrong_preference_scope.status_code == 400, wrong_preference_scope.text
            assert wrong_preference_scope.json()["error"]["code"] == "source_invalid"
            assert preferences_path.read_bytes() == expected_preference_bytes

            documents_response = await client.get(
                "/api/v1/documents?story_id=demo&timeline_id=main", headers=headers,
            )
            assert documents_response.status_code == 200, documents_response.text
            listed = {row["document_id"]: row for row in documents_response.json()}
            assert listed["canon-lore"]["document_type"] == "canon"
            assert str(root) not in documents_response.text
            canon_url = "/api/v1/documents/canon-lore?story_id=demo&timeline_id=main"
            canon_get = await client.get(canon_url, headers=headers)
            assert canon_get.status_code == 200, canon_get.text
            original = canon_get.json()
            assert original["content"] == {"content": "山城建在两条河流交汇处。"}
            assert original["document_revision"] == 1
            old_source_hash = original["source_ref"]["source_hash"]

            new_canon_text = "山城建在两条河流交汇处，旧桥连接南北两岸。"
            canon_put = await client.put("/api/v1/documents/canon-lore", headers=headers, json={
                "story_id": "demo", "timeline_id": "main",
                "expected_revision": original["document_revision"],
                "expected_source_hash": old_source_hash,
                "content": new_canon_text,
            })
            assert canon_put.status_code == 200, canon_put.text
            updated = canon_put.json()
            assert updated["document_id"] == "canon-lore"
            assert updated["document_revision"] == 2
            assert updated["source_ref"]["source_hash"] != old_source_hash
            assert updated["content"] == {"content": new_canon_text}
            assert read_yaml_mapping(canon_path)["content"] == new_canon_text
            assert canon_path.read_bytes() != initial_canon_bytes
            source_backups = list((workspace / "demo" / "main" / "source-versions").rglob("*.yaml"))
            assert any(path.read_bytes() == initial_canon_bytes for path in source_backups)
            committed_canon_bytes = canon_path.read_bytes()

            stale_revision = await client.put("/api/v1/documents/canon-lore", headers=headers, json={
                "story_id": "demo", "timeline_id": "main", "expected_revision": 1,
                "expected_source_hash": updated["source_ref"]["source_hash"],
                "content": "旧revision不应改写Canon。",
            })
            assert stale_revision.status_code == 409, stale_revision.text
            assert stale_revision.json()["error"]["code"] == "revision_conflict"
            assert canon_path.read_bytes() == committed_canon_bytes

            stale_hash = await client.put("/api/v1/documents/canon-lore", headers=headers, json={
                "story_id": "demo", "timeline_id": "main", "expected_revision": 2,
                "expected_source_hash": old_source_hash,
                "content": "旧文件hash不应改写Canon。",
            })
            assert stale_hash.status_code == 409, stale_hash.text
            assert stale_hash.json()["error"]["code"] == "revision_conflict"
            assert canon_path.read_bytes() == committed_canon_bytes

            wrong_scope_edit = await client.put("/api/v1/documents/canon-lore", headers=headers, json={
                "story_id": "other", "timeline_id": "main", "expected_revision": 2,
                "expected_source_hash": updated["source_ref"]["source_hash"],
                "content": "跨书编辑不得改动Canon。",
            })
            assert wrong_scope_edit.status_code == 400, wrong_scope_edit.text
            assert wrong_scope_edit.json()["error"]["code"] == "scope_denied"
            assert canon_path.read_bytes() == committed_canon_bytes

        assert app.state.service.store is not None

    asyncio.run(scenario())


def test_summary_author_edit_invalidates_old_memory_projection_without_losing_batch(tmp_path: Path) -> None:
    """验证参考摘要编辑采用文件hash CAS、保存作者归属并使旧记忆投影失效。

    依赖：真实Web资料路由、SourceCorpus、DraftStore、MemoryService与SummaryEditor。
    输入：临时History正文来源、真实summary YAML投影、元数据外改和作者编辑内容。
    输出：旧hash/旧revision冲突、author_note元数据、批次保留及失效状态缺口。
    实现：回读实际YAML和MemoryService投影，证明元数据-only变化不会被旧表单覆盖。
    """
    async def scenario() -> None:
        """依赖：实际ASGI lifespan、带token Web API和规范StoredMemoryBatch辅助器。
        输入：有效History DocumentRef、memory_projection summary及旧/新文件版本。
        输出：有效状态转为invalidated、作者批注保留原批次以及双CAS字节保护。
        实现：先确认投影可见，再执行元数据-only外改、CAS拒绝和SummaryEditor作者更新。
        """
        root = make_library(tmp_path)
        workspace = tmp_path / "workspace"
        config_path = tmp_path / "model-config.json"
        canon_path = root / "stories" / "demo" / "common" / "canon" / "canon-lore.yaml"
        write_yaml(canon_path, {
            "metadata": {
                "document_id": "canon-lore", "story_id": "demo", "timeline_id": "main",
                "document_type": "canon", "title": "山城设定", "status": "canon",
                "version": "1", "source_revision": 1,
            },
            "content": "西岸的古井常年泛着冷雾。",
        })
        scope = GraphKey("demo", "main")
        put_document(root, "well-observed", "甲抵达西岸古井，亲见井口的冷雾。")
        source_ref = load_story_sources(root, scope).source_refs["well-observed"].as_dict()
        position = _document_position(StoryCoordinate(1, 1, 1))
        batch = _formal_batch(source_ref, state={
            "entry_id": "stale-projection-well-state",
            "value": "西岸古井常年有冷雾。",
            "narrative_position": position,
        })
        summary_path = _write_projection(root, batch, document_id="memory-projection")
        initial_summary_bytes = summary_path.read_bytes()
        app = create_app(root, workspace, config_path)

        async with _asgi_client(app) as client:
            bootstrap = (await client.get("/api/v1/bootstrap")).json()
            headers = _token_headers(bootstrap["token"])
            run = _create_run(root, app.state.service.store, coordinate=None, branch="web-summary-edit")
            run_id = run["run_id"]
            before_edit = app.state.service.memory.recall(run_id)
            assert [entry["entry_id"] for entry in before_edit["state_view"]["entries"]] == [
                "stale-projection-well-state",
            ]

            documents = await client.get("/api/v1/documents?story_id=demo&timeline_id=main", headers=headers)
            assert documents.status_code == 200, documents.text
            listed = {row["document_id"]: row for row in documents.json()}
            assert listed["memory-projection"]["document_type"] == "summary"
            summary_url = "/api/v1/documents/memory-projection?story_id=demo&timeline_id=main"
            summary_get = await client.get(summary_url, headers=headers)
            assert summary_get.status_code == 200, summary_get.text
            stale_form = summary_get.json()
            assert stale_form["document_revision"] == 1
            assert stale_form["metadata"]["memory_kind"] == "memory_projection"
            old_summary_hash = stale_form["source_ref"]["source_hash"]

            external_yaml = read_yaml_mapping(summary_path)
            external_yaml["metadata"]["title"] = "作者在另一处调整过标题"
            write_yaml(summary_path, external_yaml)
            external_bytes = summary_path.read_bytes()
            assert external_bytes != initial_summary_bytes
            rejected_hash = await client.put("/api/v1/documents/memory-projection", headers=headers, json={
                "story_id": "demo", "timeline_id": "main",
                "expected_revision": stale_form["document_revision"],
                "expected_source_hash": old_summary_hash,
                "content": "旧表单不得覆盖元数据-only外改。",
            })
            assert rejected_hash.status_code == 409, rejected_hash.text
            assert rejected_hash.json()["error"]["code"] == "revision_conflict"
            assert summary_path.read_bytes() == external_bytes

            current_form_response = await client.get(summary_url, headers=headers)
            assert current_form_response.status_code == 200, current_form_response.text
            current_form = current_form_response.json()
            assert current_form["source_ref"]["source_hash"] != old_summary_hash
            authored_note = "西岸古井附近常年泛冷雾；这条笔记由作者维护。"
            authored = await client.put("/api/v1/documents/memory-projection", headers=headers, json={
                "story_id": "demo", "timeline_id": "main",
                "expected_revision": current_form["document_revision"],
                "expected_source_hash": current_form["source_ref"]["source_hash"],
                "content": authored_note,
            })
            assert authored.status_code == 200, authored.text
            authored_doc = authored.json()
            assert authored_doc["document_revision"] == 2
            assert authored_doc["content"]["content"] == authored_note
            assert authored_doc["metadata"]["ownership"] == "user"
            assert authored_doc["metadata"]["memory_kind"] == "author_note"
            assert authored_doc["metadata"]["memory_batches"] == [batch]
            edited_yaml = read_yaml_mapping(summary_path)
            assert edited_yaml["metadata"]["ownership"] == "user"
            assert edited_yaml["metadata"]["memory_kind"] == "author_note"
            assert edited_yaml["metadata"]["memory_batches"] == [batch]

            authored_bytes = summary_path.read_bytes()
            stale_revision = await client.put("/api/v1/documents/memory-projection", headers=headers, json={
                "story_id": "demo", "timeline_id": "main", "expected_revision": 1,
                "expected_source_hash": authored_doc["source_ref"]["source_hash"],
                "content": "旧revision不得覆盖作者笔记。",
            })
            assert stale_revision.status_code == 409, stale_revision.text
            assert stale_revision.json()["error"]["code"] == "revision_conflict"
            assert summary_path.read_bytes() == authored_bytes

            after_edit = app.state.service.memory.recall(run_id)
            assert after_edit["state_view"]["entries"] == []
            assert after_edit["state_view"]["invalidated_keys"] == ["stale-projection-well-state"]
            assert any("作者编辑笔记，旧投影失效" in gap for gap in after_edit["gaps"])

        assert app.state.service.store.load(run_id)["run_id"] == run_id

    asyncio.run(scenario())
