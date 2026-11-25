"""薄HTTP/SSE层；写作、采用、记忆全部委托同一应用组件。"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import json
from pathlib import Path
from secrets import compare_digest, token_urlsafe
from urllib.parse import urlsplit


def create_app(library_root: Path, workspace_root: Path | None = None,
               model_config_path: Path | None = None):
    """依赖：延迟FastAPI/组合根。输入：库/工作根/模型配置路径。输出：ASGI app。实现：loopback同源token、薄路由和磁盘事件观察，无第二生成循环。"""
    try:
        from fastapi import FastAPI, Request
        from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
        from fastapi.staticfiles import StaticFiles
    except ImportError as exc:
        raise RuntimeError("capability: 请安装 novel-rag[web]") from exc
    from ..composition import build_writer_service
    from ..documents import read_yaml_mapping
    from ..catalog.paths import timeline_registry_path
    from ..identity import GraphKey
    from ..generation.store import StoreConflict
    from ..mutations.types import MISSING_FINGERPRINT, MutationConflictError, SummaryConflictError
    from ..std.hashing import fingerprint_bytes

    # Request注解在函数局部导入，FastAPI解析需要实际type，不能保留字符串。
    token, tasks = token_urlsafe(32), {}
    service = build_writer_service(library_root, workspace_root, model_config_path)
    root = Path(library_root).resolve()
    static = Path(__file__).with_name("static")

    @asynccontextmanager
    async def lifespan(application):
        """依赖：工作区生命周期锁/恢复/RunService取消。输入：ASGI生命周期。输出：运行期间yield。实现：独占后才恢复，退出等待内置transport清理再释放；harness不重发模型。"""
        with service.writer_lease():
            await asyncio.to_thread(service.recover)
            try:
                yield
            finally:
                current = list(tasks.items())
                for run_id, task in current:
                    service.cancel(run_id)
                if current:
                    await asyncio.gather(*(task for _, task in current), return_exceptions=True)

    app = FastAPI(title="小说创作工作台", lifespan=lifespan)
    app.state.service, app.state.token = service, token

    @app.middleware("http")
    async def local_boundary(request, call_next):
        """依赖：Origin/Host/token。输入：HTTP请求/下一层。输出：同源响应或403。实现：bootstrap仅引导例外，所有API校验token，禁止跨源凭证和非loopbackHost。"""
        host = request.headers.get("host", "")
        try:
            parsed = urlsplit("http://" + host)
            valid_host = parsed.hostname in {"127.0.0.1", "localhost", "::1"} and parsed.username is None
            _ = parsed.port
        except ValueError:
            valid_host = False
        origin = request.headers.get("origin")
        if not valid_host or origin and origin != f"{request.url.scheme}://{host}":
            return JSONResponse({"error": {"code": "scope_denied", "message": "仅允许本地同源访问"}}, status_code=403)
        if request.url.path.startswith("/api/") and request.url.path not in {"/api/v1/bootstrap", "/api/v1/harness/bootstrap"}:
            supplied = request.headers.get("x-workspace-token", "")
            if not supplied or not compare_digest(supplied, token):
                return JSONResponse({"error": {"code": "scope_denied", "message": "本地会话token无效"}}, status_code=403)
        try:
            return await call_next(request)
        except (ValueError, RuntimeError, OSError, KeyError, TypeError) as exc:
            text = str(exc)
            code = ("revision_conflict" if isinstance(exc, (StoreConflict, MutationConflictError, SummaryConflictError))
                    and "scope_denied" not in text and "source_invalid" not in text else
                    "save_failed" if isinstance(exc, OSError) else text.split(":", 1)[0])
            if code not in {"capability", "scope_denied", "revision_conflict", "model_network", "model_protocol", "context_limit", "source_invalid", "save_failed"}:
                code = "source_invalid"
            return JSONResponse({"error": {"code": code, "message": text,
                                "recovery": "输入和草稿已保留，可刷新状态或使用同一操作编号重试"}},
                                status_code=409 if code == "revision_conflict" else 400)

    def catalog():
        """依赖：原注册表/路径owner。输入：无。输出：作品与注册时间线。实现：不暴露任意路径/凭证，数据只作文本显示。"""
        rows = read_yaml_mapping(root / "registry" / "stories.yaml").get("stories", [])
        return [{"story_id": row["story_id"], "title": row.get("title", row["story_id"]),
                 "timelines": read_yaml_mapping(timeline_registry_path(root, row["story_id"])).get("timelines", [])}
                for row in rows]

    async def snapshot(run_id, request=None):
        """依赖：RunService工作台查询。输入：run及可选view/事件游标请求。输出：原full/live JSON。实现：HTTP仅解析查询参数，采用目标与记忆兼容投影归应用服务。"""
        view = request.query_params.get("view", "full") if request else "full"
        after = int(request.query_params.get("after", 0)) if request and view != "full" else 0
        return await asyncio.to_thread(service.workspace_snapshot, run_id, view=view, after=after)

    async def browse_memory(run_id, request):
        """依赖：RunService.browse_memory。输入：run及作者只读arguments。输出：原完整冻结包/错误。实现：HTTP仅转发，来源/cursor/作者隔离均归共同owner。"""
        data = await request.json()
        if not isinstance(data, dict) or set(data) - {"arguments"}:
            raise ValueError("source_invalid: 记忆浏览请求形状不合法")
        return await asyncio.to_thread(service.browse_memory, run_id, data.get("arguments", {}))

    def launch(run_id):
        """依赖：RunService调度描述。输入：已保存run。输出：后台task或None。实现：按应用可启动标志登记一个task，观察断开不取消，实际run再次复核状态。"""
        run = service.run_info(run_id)
        if run_id in tasks or not run["launchable"]:
            return tasks.get(run_id)
        task = tasks[run_id] = asyncio.create_task(service.run(run_id))

        def finished(completed):
            """依赖：后台task登记。输入：已结束task。输出：None。实现：释放引用并消费异常，运行事实仍由Store恢复。"""
            tasks.pop(run_id, None)
            if not completed.cancelled():
                completed.exception()

        task.add_done_callback(finished)
        return task

    async def bootstrap():
        """依赖：安全catalog/RunService启动查询。输入：无。输出：原选择列表/配置缺口/token。实现：HTTP加入本地token，配置降级与密钥隔离归应用服务。"""
        settings = await asyncio.to_thread(service.workspace_bootstrap)
        return {"token": token, "stories": await asyncio.to_thread(catalog), **settings}

    async def new_story(request):
        """依赖：唯一scaffold/同源token。输入：标题/稳定story_id。输出：脱敏新作品目录项。实现：显式同意图重试，共用建树锁；v3不继承文学审计模块。"""
        from ..scaffold import create_story
        data = await request.json()
        if not isinstance(data, dict) or set(data) != {"story_id", "title"}:
            raise ValueError("source_invalid: 新作品只接受story_id和title")
        await asyncio.to_thread(create_story, root, story_id=data["story_id"], title=data["title"],
                                inherit_shared=False, exist_ok=True)
        return next(row for row in await asyncio.to_thread(catalog) if row["story_id"] == data["story_id"])

    async def harness_bootstrap():
        """依赖：本地HTTP边界/RunService宿主身份。输入：无。输出：原临时token与后端身份。实现：应用查询走无模型配置分支，不发小说内容。"""
        return {"token": token, **service.workspace_bootstrap(harness=True)}

    async def start(request):
        """依赖：RunService.prepare/start。输入：原纲/书线/driver/profile。输出：run/session ID。实现：共用准备，harness不启动项目模型。"""
        data = await request.json()
        driver = data.get("driver", "builtin")
        if driver not in {"builtin", "harness"}:
            raise ValueError("source_invalid: 未知创作驱动")
        starter = service.prepare if driver == "harness" else service.start
        run_id = await asyncio.to_thread(starter, GraphKey(data["story_id"], data.get("timeline_id", "main")),
                                         data.get("task_kind", "write"), data.get("outline", ""), data.get("request", ""),
                                         data.get("base_ref"), data.get("target_coordinate"), data.get("profile_name"),
                                         request_id=data.get("request_id"))
        launch(run_id)
        run = service.run_info(run_id)
        return {"run_id": run_id, "session_id": run["session_id"]}

    async def feedback(session_id, request):
        """依赖：RunService.feedback。输入：父稿/动作及可选driver/profile。输出：新run/session。实现：明确父前缀，允许两种驱动交接，不复制准备逻辑。"""
        data = await request.json()
        run_id = await asyncio.to_thread(service.feedback, session_id, data["base_run_id"], data.get("task_kind", "write"),
                                         data.get("request", ""), data.get("base_ref"), data.get("selected_parent_checkpoint"),
                                         request_id=data.get("request_id"), driver=data.get("driver"), profile_name=data.get("profile_name"))
        launch(run_id)
        return {"run_id": run_id, "session_id": session_id}

    async def cancel(run_id):
        """依赖：RunService.cancel。输入：run ID。输出：停止快照。实现：内置等transport清理；harness只关闭本地工具，不推断宿主LLM状态。"""
        service.cancel(run_id)
        return await snapshot(run_id)

    async def harness_context(run_id, request):
        """依赖：RunService唯一上下文。输入：固定run/可选full或model视图。输出：交接或错误。实现：旧全文导出兼容，模型视图由同一owner生成。"""
        return await asyncio.to_thread(service.harness_context, run_id, view=request.query_params.get("view", "full"))

    async def harness_tools(run_id):
        """依赖：RunService宿主工具查询。输入：固定run ID。输出：原生五工具定义与宿主说明。实现：权限与schema归应用服务，HTTP不读运行字段或profile。"""
        return await asyncio.to_thread(service.harness_tools, run_id)

    async def harness_tool(run_id, request):
        """依赖：RunService.harness_tool。输入：名称/参数/operation ID/交付视图。输出：实际结果或页。实现：transport只转发，权限与分页由共同owner管理。"""
        data = await request.json()
        if not isinstance(data, dict) or set(data) - {"name", "arguments", "operation_id", "delivery"}:
            raise ValueError("source_invalid: 外部工具请求字段不合法")
        return await asyncio.to_thread(service.harness_tool, run_id, data["name"], data.get("arguments", {}), data.get("operation_id"), delivery=data.get("delivery", "full"))

    async def harness_finish(run_id, request):
        """依赖：RunService.finish_harness。输入：host结束状态/讨论文本。输出：安全快照。实现：只是技术生命周期，不添加模型工具或文学检查。"""
        data = await request.json()
        if not isinstance(data, dict) or set(data) - {"status", "discussion_text"}:
            raise ValueError("source_invalid: 外部结束请求字段不合法")
        return await asyncio.to_thread(service.finish_harness, run_id, data.get("status", "completed"), data.get("discussion_text"))

    async def save(run_id, request):
        """依赖：RunService作者保存回执。输入：作者文本、草稿CAS及所需视图。输出：已提交的修订和独立读取状态。实现：将一次保存交给应用服务，默认兼容完整视图。"""
        data = await request.json()
        return await asyncio.to_thread(service.save_author_draft_receipt, run_id, data["expected_revision"],
                                       data["text"], view=request.query_params.get("view", "full"))

    async def adopt(run_id, request):
        """依赖：RunService采用入口。输入：所选修订/hash/坐标/幂等ID。输出：提交事实快照。实现：只转发作者意图，单源采用与memory_pending含义由原owner保留。"""
        data = await request.json()
        await asyncio.to_thread(service.adopt_draft, run_id, data["draft_revision"], data.get("expected_source_hash"),
                                data.get("coordinates"), data["operation_id"])
        return await snapshot(run_id)

    async def events(run_id, request):
        """依赖：RunService观察/连续事件。输入：连接及原seq。输出：SSE。实现：保持last-event-id/reset/断连语义，变化提示与热读取由应用服务负责。"""
        after = int(request.headers.get("last-event-id") or request.query_params.get("after", 0))

        async def stream():
            """依赖：应用观察结果/live事件。输入：run/游标闭包。输出：SSE帧。实现：只发送持久seq，未变化不发帧，终态发完结束，断开不取消任务。"""
            nonlocal after
            revision = None
            while not await request.is_disconnected():
                observed = await asyncio.to_thread(service.observe, run_id, after=after, revision=revision)
                if observed is not None:
                    run = observed["snapshot"]
                    revision = observed["revision"]
                    if run["events_reset"]:
                        yield "event: snapshot\ndata: " + json.dumps(run, ensure_ascii=False) + "\n\n"
                        after = 0
                    for event in run["events"]:
                        yield f"id: {event['seq']}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
                        after = event["seq"]
                    if observed["terminal"]:
                        break
                await asyncio.sleep(0.1)
        return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})

    async def document(document_id, request):
        """依赖：当前scope源owner。输入：ID/书线查询。输出：实际文档与来源。实现：ID映射和symlink校验，HTTP不接受任意本地路径。"""
        from ..service import load_story_sources
        scope = GraphKey(request.query_params["story_id"], request.query_params.get("timeline_id", "main"))
        corpus = await asyncio.to_thread(load_story_sources, root, scope)
        doc, ref = corpus.read(document_id)
        return {"document_id": document_id, "source_ref": ref.as_dict(), "metadata": doc.metadata, "content": doc.body,
                "document_revision": doc.metadata.get("revision", ref.source_revision)}

    async def documents(request):
        """依赖：本书scope源映射。输入：作品/时间线查询。输出：可见资料选择列表。实现：只发ID/标题/版本，不提供文件路径或别书内容。"""
        from ..service import load_story_sources
        scope = GraphKey(request.query_params["story_id"], request.query_params.get("timeline_id", "main"))
        corpus = await asyncio.to_thread(load_story_sources, root, scope)
        return [{"document_id": doc.document_id, "title": doc.metadata.get("title", doc.document_id),
                 "document_type": doc.metadata["document_type"], "source_ref": corpus.source_refs[doc.document_id].as_dict()}
                for doc in corpus.documents]

    async def edit_document(document_id, request):
        """依赖：RunService作者编辑入口。输入：作者选中文档、scope、revision/hash及内容。输出：保存后实际源。实现：转发原双CAS与内容，应用服务委托唯一writeback owner。"""
        data = await request.json()
        return await asyncio.to_thread(service.edit_document,
                                       GraphKey(data["story_id"], data.get("timeline_id", "main")), document_id,
                                       data["expected_revision"], data["expected_source_hash"], data["content"])

    async def preferences(story_id, request):
        """依赖：作品线注册表和onboarding偏好文件。输入：书ID、GET或带hash CAS的PUT。输出：偏好原文与实际版本。实现：校验注册及文件路径，写入委托原锁和原子保存。"""
        from ..onboarding import author_preferences_path, save_author_preferences
        from ..service import load_story_scope_registry

        await asyncio.to_thread(load_story_scope_registry, root, GraphKey(story_id, request.query_params.get("timeline_id", "main")))
        path = author_preferences_path(root, story_id)
        path.resolve().relative_to((root / "stories" / story_id).resolve())
        if request.method == "PUT":
            data = await request.json()
            await asyncio.to_thread(save_author_preferences, root, story_id, data["content"], overwrite=True,
                                    expected_fingerprint=data["expected_revision"])
        raw = await asyncio.to_thread(path.read_bytes) if path.is_file() else None
        return {"story_id": story_id, "content": raw.decode("utf-8-sig") if raw is not None else "",
                "expected_revision": fingerprint_bytes(raw) if raw is not None else MISSING_FINGERPRINT}

    async def index():
        """依赖：包内静态入口。输入：无。输出：HTML。实现：只服务受控资产，小说数据由JSON文本渲染。"""
        return FileResponse(static / "index.html")

    # 设置真实Request类型，避免局部导入注解变成查询参数。
    for endpoint in (start, feedback, save, adopt, events, document, documents, edit_document, preferences, harness_context, harness_tool, harness_finish, new_story, snapshot, browse_memory):
        endpoint.__annotations__["request"] = Request
    for path, endpoint, methods in [
        ("/api/v1/bootstrap", bootstrap, ["GET"]), ("/api/v1/runs", start, ["POST"]),
        ("/api/v1/harness/bootstrap", harness_bootstrap, ["GET"]),
        ("/api/v1/runs/{run_id}/harness-context", harness_context, ["GET"]),
        ("/api/v1/runs/{run_id}/harness-tools", harness_tools, ["GET"]),
        ("/api/v1/runs/{run_id}/harness-tool", harness_tool, ["POST"]),
        ("/api/v1/runs/{run_id}/harness-finish", harness_finish, ["POST"]),
        ("/api/v1/stories", catalog, ["GET"]),
        ("/api/v1/stories", new_story, ["POST"]),
        ("/api/v1/sessions/{session_id}/feedback", feedback, ["POST"]),
        ("/api/v1/runs/{run_id}", snapshot, ["GET"]), ("/api/v1/runs/{run_id}/cancel", cancel, ["POST"]),
        ("/api/v1/runs/{run_id}/memory", browse_memory, ["POST"]),
        ("/api/v1/runs/{run_id}/draft", save, ["PUT"]), ("/api/v1/runs/{run_id}/adopt", adopt, ["POST"]),
        ("/api/v1/runs/{run_id}/events", events, ["GET"]), ("/api/v1/documents/{document_id}", document, ["GET"]),
        ("/api/v1/documents", documents, ["GET"]), ("/api/v1/documents/{document_id}", edit_document, ["PUT"]),
        ("/api/v1/preferences/{story_id}", preferences, ["GET", "PUT"]),
        ("/", index, ["GET"]),
    ]:
        app.add_api_route(path, endpoint, methods=methods)
    app.mount("/static", StaticFiles(directory=static), name="static")
    return app
