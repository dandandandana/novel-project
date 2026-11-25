# Agent 工作规则

## v3 设计与实施阶段（2026-10-09）

权威架构路径仍为 docs/HYBRID_GRAPHRAG_ARCHITECTURE.md；完整 v2 合同在 docs/archive/HYBRID_GRAPHRAG_ARCHITECTURE_V2.md，仅约束兼容链。v3/Metro网页/harness已实施，workspace/write/harness是主入口，旧入口仍v2；当前能力、最近有证据的验证基线、已关闭反例与开放项统一见[当前状态摘要](docs/IMPLEMENTATION_STATUS_AND_NEXT.md#current-status)。一次实际调用不等于所有宿主/长篇记忆/文学效果已验收。

后续开发先读当前状态摘要，再按其中入口定位权威合同、原owner与阶段证据。实施后同步更新摘要并追加阶段记录；README、本文件与工程边界文档只链接当前摘要，不再分别维护“最新”验收数字。历史记录中的“当前/下一步/未修复”只描述当时阶段，不覆盖后续修复。

已确认新方向：LLM 主导创作，原始大纲是路线，agent 按需提供参考和工具；取消文学 audit、评分、自动修复和强制回顾。按 ENGINEERING_REFACTORING_BOUNDARIES.md 的 v3 计划实施，进度写入 IMPLEMENTATION_STATUS_AND_NEXT.md，沿用既有主控。

R13 状态/memory 按情节变化更新，正文连贯生成；不恢复四段 CHECK、九项固定报表或状态审批。采用前状态只属于草稿分支，正式来源/游标/覆盖与失效合同见架构 §7.1–7.6。原本保存在 docs/references，仅为来源，不整份注入。

Memory 用图 + router + 事件线/经历 + 伏笔，合同见架构 §7.7。LLM 仅用 recall/remember 两个记忆工具；图不复制当前状态，router 不生成剧情计划。2026-10-10用户取消默认记忆token预算：默认有界展开/完整相关包去重，显式调用者容量才使用贪心；Dijkstra/DP 按真实条件可选。不增加路由模型、多通道配额、八轮冻结或满容量停叙事。统一 memory_revision、整批规范化/幂等及来源失效已实施；按来源故事次序回放，不能恢复按文件名排序。

下方通用模块清单与完成门继续适用。仅登记实际落盘的公共接口；保留旧数据、未提交改动、v2 兼容入口及源版本备份。

Context沿架构§7.10：model交付任务/真实来源入口，完整原包按recall取得；full保留导出。长输入/原文与冻结JSON页可精确续读，交付窗口不改变记忆容量或来源权限；启动资源估算不能当作累计provider成本。失效基线不提供读取入口，旧recall续页复核原版本和逐项来源。

整体context沿§7.11/IMP-CTX-01–06已落盘：请求前实际材料校验、焦点工作集/语义交付、同run安全attempt及原身份恢复；provider_call_id与内部提交身份分开，harness原operation_id保持。独立QA、真实宿主/百章AB及不可观测峰值由交接文档当前摘要导航至对应阶段证据；provider compaction仍unsupported，不拿单次成本或配置字段认证所有端点/长篇效果。

Harness增量沿权威架构§15：外部LLM由宿主驱动，prepare不读模型配置；driver=harness/status=prepared只表示本地工具入口。stdio只转发同一后端，只有五创作工具；EOF/刷新不结束，取消本地工具不等于取消外部模型。写操作的operation_id与JSON-RPC ID分离，省略draft_ref的幂等参数由MemoryService.remember_arguments规范。生产后端/内置write CLI在恢复前独占workspace writer_lease；MCP适配器不能另建Store。协议首版限定2025-11-25/2025-06-18，实际宿主/新协议与真实模型效果按证据标记。

### 函数注释（用户要求）

新增或修改函数使用简短注释/docstring，写清“依赖、输入、输出、实现”四项：需要的包/组件、参数、返回/错误及主要流程。面向后续 LLM 理解，允许简洁实现；不要添加逐动作文学审计、固定报表或人类说明式长文。

> 适用范围：`D:\novel-project` 全仓库（`src/novel_rag/` 代码、测试、脚本、文档）。
> 本文件是给后续 LLM/代理的操作约束；与架构文档冲突时以 `docs/HYBRID_GRAPHRAG_ARCHITECTURE.md` 为准。

## 1. 通用模块优先（强制）

**写任何新函数、类、helper、协议之前，必须先确认没有可复用的既有实现。**

每次准备新增代码时，按以下顺序执行：

1. **查**：用 grep 在 `src/novel_rag/` 内搜索同义实现（关键词 + 功能语义都搜，例如时间戳、指纹、原子写、FTS 表达式、GraphKey 转换）。
2. **用**：找到就 import 复用。私有函数（`_` 前缀）如需跨模块复用，先把它提升为所在模块的公共 API 并补充说明，不要复制一份。
3. **建**：确认不存在后才能新建；新建位置必须按下表归入唯一归属模块，不得再散落第三份副本。
4. **记**：新建了新的通用模块时，必须同步更新本文件的清单和 `docs/ENGINEERING_REFACTORING_BOUNDARIES.md` 的去重记录节。

**禁止行为**：

- 在第二个模块里重新实现已有工具逻辑（哪怕是"稍微改一点"的变体——变体应通过参数表达，而不是复制）。
- 把通用逻辑内联进调用方导致下一轮扫描又出现多份。
- 以"兼容层"名义复制 canonical 实现（兼容层的正确做法是委托，参考 `graph/fingerprint.py` 对 catalog 的委托）。

## 2. 现有通用模块唯一归属清单

源码位于 `src/novel_rag/`；表中省略前缀的模块路径均相对此目录。开发先执行 `python -m pip install -e ".[dev]"`，脚本与测试消费已安装包。std 仅依赖 Python 标准库；contracts 只定义来源类型和纯结构合同。

| 需求 | 唯一实现 | 不要再写 |
|---|---|---|
| 字节SHA-256指纹 | `std/hashing.py::fingerprint_bytes`（mutations.types 同对象重导出） | 重写sha256前缀或改变旧参数JSON字节域 |
| OS跨进程互斥原语 | `std/locks.py::AdvisoryFileLock`；业务过期/PID与owner仍归`mutations/locks.py::FileMutationLock` | 读后删除代替互斥、持锁删除guard或第二套锁恢复 |
| 纯来源类型/解析 | `contracts/references.py::DocumentRef / DraftRef / AuthorInputRef / MemorySourceRef / parse_source_ref`；documents/generation.types兼容导出 | 来源owner反向加载运行管线、复制Ref类型/校验 |
| 源投影复制过滤 | `mutations/source.py::source_projection_ignores`（根mutation guard与运行时保留名`.writer.lock.guard`排除） | 复制锁guard、以元数据存在作为guard判断、扩大到所有*.guard或普通资料 |
| 作者保存与提交回执 | `generation/session.py::RunService.save_author_draft / save_author_draft_receipt` | HTTP重做partial判定、正文拼装或CAS规则，或以随后读取的选中稿代替本次提交 |
| 工作台/CLI运行视图与采用编辑入口 | `RunService.workspace_snapshot / run_info / run_result / observe / workspace_bootstrap / harness_tools / adopt_draft / edit_document`；`writer_lease / recover`委托原Store | Web/CLI直接访问service.store/config/memory、按binding推断目标；CLI结果隐式recall、live展开冷历史或另建采用实例 |
| 草稿前缀/首次记忆效力纯策略 | `memory/effects.py::draft_selection_effect / initial_memory_effect_invalid` | 在Store/其他服务重新遍历前缀失效，纯策略写盘或推进版本；save仍在原锁内一次提交 |
| 记忆提交/效力CAS/采用回执镜像 | `generation/types.py::MemoryCommit`、`DraftStore.commit_memory / reconcile_memory_effect / record_adoption_receipt`（旧tuple/控制键仅在提交入口转换） | 新业务batch内藏效力控制键、memory/adopt直接store.write、只校记忆版本遗漏草稿CAS；将镜像当作History提交点 |
| UTC 秒级 ISO-8601 时间戳 | `std/time.py::utc_now_iso`（timeutil 同对象重导出） | `_now()` 副本 |
| GraphKey / key-like / 二元组强转 | `src/novel_rag/graph/types.py::coerce_graph_key` | 模块内联的 isinstance-AttributeError 转换链 |
| 库根 YAML 全量指纹（排除 index/.mutation-*） | `src/novel_rag/catalog/corpus.py::yaml_source_fingerprint` | 私有 rglob+指纹循环 |
| 故事注册表别名加载（aliases.yaml 唯一加载器） | `src/novel_rag/catalog/aliases.py::load_story_aliases` | 各处自行解析 aliases.yaml；builder 经 `registry_aliases=` 显式输入投影 |
| 结构化关系资料格式 | `novel-rag/templates/relationship-canon.yaml` 模板 + `documents.validate_document` 的 relations 规则 | 自创关系 YAML 形状或第二套字段检查 |
| 确认口令判定（大小写不敏感） | `src/novel_rag/tui/helpers.py::matches_word / confirm_word` | 各菜单点裸 `ask(...) != "WORD"` 比较 |
| TUI 表格渲染（CJK 宽度对齐） | `src/novel_rag/tui/helpers.py::render_rows / display_width / truncate_display` | 手拼 JSON 或不对齐字符串行；状态条/顶行截断也必须走 display_width 家族 |
| 目录列选文件（零依赖路径浏览） | `src/novel_rag/tui/helpers.py::pick_file_from_directory` | 每处自写目录遍历交互 |
| 任务 ID 建议（日期自增防撞目录） | `src/novel_rag/tui/helpers.py::suggest_task_id` | 字面量 "generation" 或手写 datetime 默认 |
| timeline 摘要列举 | `src/novel_rag/tui/helpers.py::list_summary_documents` | rglob+from_yaml 循环散落多处 |
| 生成进度回调契约 | `generation/pipeline.generate(progress=…)`；`composition.rebuild_graph_projections(on_partition=…)` | 在管线里直接 print 或绕开组合根轮询 |
| 模型协议名归一化 | `src/novel_rag/model_api.py::normalize_mode`（别名 completions/openai-completions→chat，默认 chat） | 硬编码 `{"responses","chat"}` 校验集合或第二套模式映射 |
| 交互会话（可降级 prompt_toolkit） | `src/novel_rag/tui/session.py::create_interactive_io`（extra：`pip install novel-rag[tui]`） | 在 menu 内直接 import prompt_toolkit 或要求其为必需依赖 |
| 文档集内容指纹（稳定相对路径+字节 SHA-256） | `src/novel_rag/catalog/corpus.py::fingerprint_documents`（graph 层经 `graph/fingerprint.py` 委托） | 第二套哈希算法 |
| 原子建图提升协议（临时库→验收→os.replace→失败清理） | `src/novel_rag/graph/promotion.py::build_and_promote_atomically` | builder 内联 mkstemp/os.replace 流程 |
| trigram FTS 表达式构造 / 短词 LIKE 兜底搜索 | `src/novel_rag/graph/reader.py::_fts_match_expression / _like_substring_pattern / search_documents` | 各 reader 自写 MATCH 拼接 |
| Reader 新鲜度校验与生命周期 | `graph/reader.py::ensure_reader_freshness` + `_SQLiteReaderLifecycle` | 每个 Reader 重写 close/_ensure_fresh |
| SQLite 只读连接（mode=ro URI） | `src/novel_rag/graph/reader.py::open_read_only` | 裸 `sqlite3.connect(...?mode=ro)` 散落多处 |
| YAML 加载 | `src/novel_rag/documents.py::read_yaml_mapping` | 各处直接 `yaml.safe_load` 于注册表类文件 |
| 同次源字节/解析/hash快照、正式引用 | `documents.py::read_yaml_snapshot / YamlSnapshot / DocumentRef`（Ref 类型归 contracts） | 解析旧内容后读取新hash；源owner反向import生成业务 |
| 公共原子字节/JSON保存 | `std/atomic_io.py::atomic_write_bytes / atomic_write_json`（coordinator 同对象重导出） | 新Store/adopt里复制temp/fsync/replace；凭证writer另保安全语义 |
| 公共文档坐标/common识别 | `catalog/corpus.py::document_coordinate / is_common_document` | 第二套游标或布局解释器 |
| v3作品线注册与只读作品源范围 | `service.py::load_story_scope_registry / load_story_sources / SourceCorpus` | 复制作品线注册校验、为读取偏好枚举正文、复制rglob/YAML解析 |
| 作者偏好路径与模型可见原文 | `onboarding.py::author_preferences_path / read_author_preferences_text`；旧 generation 路径入口同对象重导出 | 在 context 或工具另读一遍已绑定的偏好，另拼文件路径，或用解码后的文本代替网页保存的原始字节 CAS |
| 同次源快照的游标视图 | `SourceCorpus.at_cursor`（prepare/MemoryService消费） | 同一工具重新扫描来源、旧解析值配新hash |
| 轻量查询词项/原文兜底 | `retrieval/service.py::safe_query_terms`、`service.py::SourceCorpus.search`（分块复用chunk_text） | 复制CJK/trigram词法、造新索引必备条件；旧_safe_query_terms只是别名 |
| 显式实体元数据投影 | `graph/builder.py::normalize_entities` | 按同名正文猜实体或复制单/复数ID归一化 |
| v3原始运行/接收/草稿/批次幂等 | `generation/store.py::DraftStore` | 第二份state日志/active map、多个草稿指纹映射 |
| 前缀/目标归属与版本保留 | `DraftStore.accepts_prefix / prefix_status / target_source_ref / protect_source / protect_input` | 将续写前章误当采用目标，或在adopt/web另造来源映射/备份流程 |
| 正文全文拼装 | `generation/session.py::RunService.assemble_output` | web保存partial时另拼后缀/忘加父前缀；正式前章不拼进新章 |
| v3状态/事件图/参考路由 | `memory/state.py::reduce_state`、`graph.py::project_records`、`router.py::route`、`service.py::MemoryService` | 重建审批/文学audit或另一个router模型 |
| 作者材料与事实图隔离 | `memory/graph.py::is_author_material`；邻接、router线索发现/必要闭包共用 | 各处复制author_plan/纯AuthorInputRef判断，或仅删除必要边后返回不完整事实 |
| 有界候选继续查找 | `memory/router.py::route(candidate_search=…)`、`MemoryService.recall`、原 `RunService.execute_tool` 的 `tool_results[].candidate_search_state`、`generation/context.py::candidate_search_navigation` | 提高64默认上限、从头累计跳过、另建分页Store；把候选cursor与原JSON/语义续页混用，或实时工作集伪造冻结入口 |
| 热状态观察/运行大字段物理保存 | `DraftStore.snapshot(view="live", after=…) / observation_revision / load / write`（同run payloads及版本化位置映射） | 另建事件/事实/提交Store，mtime认证来源、删除连续事件/旧回执，热读展开全部冷历史或把run.json变小当总占用收益 |
| 作者完整记忆浏览/模型消费隔离 | `RunService.browse_memory`、`ToolDispatcher`的`origin="author_browse"`、原`MemoryService.recall / route(browse_all=True)`、`generation/context.py::model_tool_rows` | HTTP/JS重写过滤/候选算法，作者读取改模型focus/材料/事件，取消后禁止作者阅读，或小包无结束计数；原五工具门保持 |
| 同次草稿元数据与目标轻读 | `DraftStore.resolve_draft(run=… / metadata_only=…) / target_source_ref` | 每条同run Ref重读全部冷历史，或缓存代替正文真实hash；metadata_only物理返回只供原目标祖先链，不作完整逻辑run |
| 记忆共同快照/排序/采用映射 | `MemoryService.read_snapshot / publication_candidates / map_publication / publication_controls` | recall、规范化及adopt各建排序链；递归改写自由payload；冻结后重新采样候选 |
| 冻结记忆证据与发布journal定位 | `DraftStore.adoption_path / protect_memory / protected_memory / memory_publications` | 新日志/事实Store，或依赖搬迁前绝对路径；保护副本直接注入有效事实 |
| 五个模型工具登记 | `generation/tools.py::ToolDispatcher` | provider/web再复制工具循环，或把作者采用/设定编辑开放给模型 |
| 无模型准备/共同工具执行/上下文与外部生命周期 | `generation/session.py::RunService.prepare / tool_dispatcher / execute_tool / harness_context / harness_tool / finish_harness` | 让harness调用builtin模型，或HTTP复制正文拼装、工具结果/事件规则 |
| 模型交付/精确来源续读 | `generation/context.py::build_context / describe_text / text_page / json_result_page`、`MemoryService.current_snapshot / source_refs_status`、`ToolDispatcher.deliver_result / _read_document` | 不在MCP/网页另裁字段、另建分页cache/状态；原tool_results冻结完整recall，字符页不改变记忆选择，续页逐项复核原包来源 |
| 共同模型材料绑定/焦点与语义投影 | `generation/context.py::context_binding / active_recall_selection / result_source_refs / semantic_result_page / context_recovery_materials`，原MemoryService/state/router选择 | 不新建focus/current-state Store；只提声明Ref，临时query/失败/续页不改持续选择；工作集交付窗不改变完整记忆容量 |
| 网络前turn/attempt与内部调用身份 | `DraftStore.prepare_turn / commit_turn / invocation_key`、`RunService.run / execute_tool` | 不新建epoch/幂等日志、不改provider配对ID；未知写仅恢复原键和原参数，作者保护/固定run绑定不重置 |
| 技术公开文本与原工具回执读取 | `DraftStore.public_turn_text`、`generation/store.py::public_tool_row`（UI快照与技术回执共用）、`generation/context.py::technical_tool_receipt`、`ToolDispatcher._read_document` | 只有同run公开turn/原参数与回执，不交付candidate_search_state；technical_turn/technical_receipt不作MemorySourceRef、不解释reasoning、不自动存正文 |
| 显式模型策略/逻辑请求观测/累计报告用量 | `model_api.py::validate_context_policy / provider_usage_totals`、`OpenAICompatibleModel.request_body / request_manifest`，`ModelProfile`沿原配置owner | 默认window/reserve/max_turns为None；不猜实际容量、不把逻辑JSON称wire或首包估算称累计费用，compaction未验收保持unsupported |
| 工作区生命周期独占/原提交恢复 | `DraftStore.writer_lease / committed_tool`（委托FileMutationLock/原提交表） | 第二个后端先recover后取锁，或新建幂等日志；Windows PID查询不得用os.kill(pid,0) |
| 记忆提交参数/工具回执同源默认值 | `MemoryService.remember_arguments`、`ToolDispatcher.committed_result` | 省略draft_ref与实际提交None的指纹差异，或两个驱动另写参数规范 |
| 模型可见记忆结构、首次示例、拒绝指引与整批校验 | `memory/schema.py::draft_reference_schema / remember_update_schema / remember_update_examples / memory_update_guidance / state_entry_schema / validate_state_entry / validate_memory_update / validate_stored_batch`；`contracts/references.py::validate_source_refs / validate_position`（复用graph常量、state.DOMAINS、GraphKey/StoryCoordinate及parse_source_ref；MemoryService/config/Store共用） | update只声明空object；工具/MCP/上下文另抄示例或校验器；回读host字段整条回写、错误猜ID/自动重写；输入与容器分别维护；把世界内来源当文件Ref或自造获知点 |
| 来源hash格式 | `contracts/references.py::SOURCE_FINGERPRINT_PATTERN`（config 同对象重导出） | 各处复制sha256正则；正文/人物语义仍由MemoryService负责 |
| 固定run的loopback HTTP/stdio接入 | `harness.py::BackendClient / McpStdioAdapter`（CLI使用同一client） | MCP复制五工具schema/打开Store，或自动重发未知POST/把token放上下文 |
| v3源提交/采用与作者资料编辑 | `mutations/source.py::build_source_mutation_coordinator`（composition 兼容委托）、`writeback/adopt.py::AdoptionService / edit_reference` | 新事务引擎、采用依赖文学门/全库建图；笔记编辑仍委托SummaryEditor |
| 新作品建树/注册/同意图重试 | `scaffold.py::create_story`（CLI/TUI/网页共用） | HTTP复制建树、普通覆盖stories.yaml、无锁读改写或删除未证实残留；`exist_ok`核原意图，注册最后原子提交 |
| v3记忆容器形状 | `config.py::validate_memory_metadata`，documents复用summary校验 | reader对坏容器崩溃；容器层不解释人物/因果或批准正文 |
| Metro磁贴配置/展示导航/时钟 | `web/static/tiles.json`、`launcher.js`、`assets/manifest.json`；业务仍`workspace.js` | 第二个API client/Store/SSE、导航重建业务DOM/自动取消、配置执行HTML/脚本或远程图片 |
| 分块 | `src/novel_rag/chunking.py::chunk_text` | 自定义切分循环 |
| 默认检索状态过滤 | `src/novel_rag/config.py::DEFAULT_SEARCH_STATUSES` | 字面量 `("active", "canon")` |
| manifest JSON 序列化 | `std/serialization.py::json_text`（graph.corpus 同对象重导出） | 手写 `json.dumps(sort_keys=True...)` |
| Console TUI 规范状态（CanonicalUiState/JobState/BlockView） | `src/novel_rag/tui/console/state.py` | 各 renderer 自建状态结构或直读业务对象 |
| Console 配置加载与验证（camelCase/snake_case 双写法） | `src/novel_rag/tui/console/config.py::load_ui_config / validate_ui_config` | 第二份 ui.json 解析或散落的默认值字典 |
| Console 主题 token | `src/novel_rag/tui/console/theme.py::build_style` | 组件内散落 hex/ANSI 颜色字面量 |
| 转录环形缓冲与定格块 | `src/novel_rag/tui/console/blocks.py::BlockStore / format_status_line`（六态符号表唯一归属；`state.status_symbol/status_word` 仅委托投影） | 自写行缓冲、第二套状态符号表（●✓⚠✗⊘⏱） |
| 后台任务线程与进度事件 | `src/novel_rag/tui/console/jobs.py::JobRunner` | 在命令处理器里直接 threading + print 进度 |
| 业务事件→UI 状态适配（含 legacy 桥接 ask 泵） | `src/novel_rag/tui/console/adapter.py::ConsoleAdapter` | renderer 直读业务对象；绕开 adapter 的第二套线程回调通道 |
| 状态条 segments（顶行/输入前缀/hint） | `src/novel_rag/tui/console/status.py` | 手拼顶行字符串或第二个 footer 渲染出口 |
| 转录前缀着色 Lexer | `src/novel_rag/tui/console/widgets.py::TranscriptLexer` | TextArea 内联 ANSI 转义串 |
| Console 浮层构建器 | `src/novel_rag/tui/console/dialogs.py` | 各处自拼 Dialog/Float 结构 |

## 3. 有意保留的差异（不许"顺手统一"）

| 位置 | 为什么不同 |
|---|---|
| `src/novel_rag/index.py` legacy 检索的词项引用 | legacy `chunks` 表是 unicode61 分词器，短词语义与 canonical trigram 有意不同；且兼容层不得新增能力（架构 §11.5） |
| `composition._manifest_fingerprint`（读库行） vs `retrieval/service._manifest_fingerprint`（读 manifest 对象） | 输入域不同，统一反而增加跨层耦合 |
| `mutations/coordinator.py::_manifest_now` | 返回 (ISO, epoch) 且保留微秒精度，服务 pending 锁 staleness 判定 |

改动以上任何一处之前，必须先在权威架构文档立项，不得当作普通重构处理。

## 4. 完成定义

涉及通用模块的任务，收尾必须同时满足：

```powershell
python -m pytest -q -k "not test_file_lock_uses_windows_safe_exclusive_create_across_processes"
python scripts\run_retrieval_tests.py   # retrieval_cases=72 failures=0
python -m novel_rag.cli --library novel-rag validate
```

三者全绿才算完成；任何一项失败都不得提交或宣告完成。
