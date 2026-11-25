# Novel-RAG 实施状态与后续任务交接

<a id="current-status"></a>
## 当前状态摘要（2026-11-25更新）

本次简化了 v3 的记忆写入校验、召回路由、原文读取和工作台资料编辑。工具声明与校验共用操作规则，召回时每个待匹配节点只编码一次，同一请求沿用已绑定的偏好文本。本地完成门通过 812 项测试、72 个检索用例和 729 份文档校验。改前改后对照及 Chrome 操作见[复杂度优化阶段记录](#runtime-complexity-20261125)。

同日此前完成续写创建恢复、作者保存回执、首页资料按需读取和流式持久化。当时 Windows 本地通过 810 项测试，检索 72 例均通过，729 份文档校验无问题。真实 Chrome 验证了首页零正文读取、停止、刷新、保存与续写。[作者工作台阶段记录](#author-workspace-20261125)

2026-10-23后续3/4/5工程实施已完成：remember同源示例与字段/重试说明、实际CLI/v3入口惰性加载、架构检查与Windows/Ubuntu CI。最终791/72/729全绿，独立QA22项通过，干净资料建索引与非editable wheel资源验证通过，1567份原件不变。两章1724字符及第三冷读已实际完成；8次remember中6次拒绝、2次提交，首试成功率改善仍未证实，远端CI/Linux尚未执行。见[本轮阶段](#ergonomics-entrypoints-ci-status)、[结果](../output/ergonomics-entrypoints-ci-20261023/RESULTS.md)与架构§21。

2026-10-23应用入口与运行提交解耦已完成：CLI/Web统一消费RunService查询与用例，记忆/采用通过Store专用操作提交，纯前缀失效策略归memory/effects。最终743/72/729全绿，独立QA22项通过；旧tuple签名转换兼容发现已修复复验，1567份非索引资料逐字不变。见[本轮阶段](#application-boundaries-status)、[重构结果](../output/application-boundaries-20261023/RESULTS.md)及架构§20。

2026-10-23项目std/包边界重构已完成：四批STD-01–04落盘，源码迁入`src/novel_rag`；std只依赖标准库，contracts承载纯来源合同，源提交/作者保存归属收敛，旧公开API与持久字节兼容。最终完成门724/72/729全绿，独立QA无未关闭发现，干净wheel及系统临时目录运行通过；原库1567份非索引资料逐字不变。见[本轮阶段](#std-package-refactor-status)、[重构结果](../output/architecture-std-refactor-20261023/RESULTS.md)。

本节是当前能力、最近有证据的验证基线、已关闭反例与开放项的唯一汇总。架构、稳定接口与权限合同仍以[权威架构](HYBRID_GRAPHRAG_ARCHITECTURE.md#architecture-overview)为准；实现归属与完成门见[AGENTS](../AGENTS.md)，实施工作包见[工程边界](ENGINEERING_REFACTORING_BOUNDARIES.md#v3-implementation)。

2026-10-21状态刷新/网页记忆浏览/长会话存储减负已完成：四视角council收敛后落盘，12份运行输入冻结，独立复核、真实浏览器与三完成门全绿（663/72/729）。原库1486份YAML字节不变。README、AGENTS与工程边界文档继续链接本节。

随后按用户第4项完成新作《雨灯亭的蓝线》的两章真实写作及第三冷会话记忆核对：正文1864字符，实际7次remember中5次业务拒绝、2批最终成功；状态/认识沿原ID更新、义务解除、正式来源与冷读结果有证据。仅在output独立新库采用，工程202份运行输入与原库1567份非索引文件字节不变；收尾夹具曾失败，原日志和安全关闭记录保留。见[新作品实跑](#new-story-live-status)。

### 当前能力与证据入口

| 范围 | 已实施能力与适用范围 | 阶段证据 |
|---|---|---|
| v3 主路径维护 | 记忆操作规则共用、召回查询一次编码、原文续页沿用来源身份、资料编辑共用作品线与请求序号校验 | [阶段记录](#runtime-complexity-20261125) |
| 作者工作台和接收存储 | 重试同一请求可恢复原有子任务和选定父稿，保存回执区分提交和读取，资料按面板加载，每段公开文本一次替换运行快照 | [阶段记录](#author-workspace-20261125)、[浏览器与写入实测](../output/author-workspace-20261125/verification.json) |
| 记忆示例/惰性入口/工程检查 | Schema唯一示例实际进入原生请求与MCP；实际CLI/write/Web+harness不载旧生成链；聚焦AST及进程边界门、跨平台CI配置、Chromium发现与真实wheel门 | [本轮结果](../output/ergonomics-entrypoints-ci-20261023/RESULTS.md)、[独立QA](../output/ergonomics-entrypoints-ci-20261023/independent-qa/FINAL.md)、架构§21 |
| 应用入口/运行提交解耦 | Web/CLI无直接Store/config/memory访问；MemoryService/AdoptionService不直接write运行；双CAS、显式MemoryCommit、纯失效策略与旧回调兼容，保留一致快照和原单Store事务边界 | [本轮结果](../output/application-boundaries-20261023/RESULTS.md)、[独立QA](../output/application-boundaries-20261023/independent-qa/FINAL.md)、架构§20 |
| std/包与安装边界 | `src`单发行包；基础原语/纯Ref合同/业务包分层；v2惰性兼容，应用服务拥有作者保存；OS guard修复过期恢复竞态，默认资料根独立源码位置 | [本轮结果](../output/architecture-std-refactor-20261023/RESULTS.md)、[独立QA](../output/architecture-std-refactor-20261023/qa-std-boundaries.md)、[架构§19](HYBRID_GRAPHRAG_ARCHITECTURE.md) |
| v3创作主链 | workspace/write/harness共用原服务与五工具，支持草稿、续写、记忆与作者采用；旧入口保留v2语义 | [v3首版](#v3-status)、[写作体验](#writing-experience-status) |
| 网页与作者恢复 | Metro入口、图片轮换及写作体验增量已有阶段验收；浏览器恢复按原浏览器/地址范围生效，服务器草稿继续权威 | [Metro验收](#metro-status)、[写作体验](#writing-experience-status) |
| 记忆可靠性与信息边界 | 图/router/事件/伏笔、统一版本与来源失效、正式发布保护及信息迷雾已实施；默认有界展开、完整相关包去重，无默认token容量 | [可靠性六包](#memory-reliability-implementation)、[状态与信息合同](HYBRID_GRAPHRAG_ARCHITECTURE.md#state-memory) |
| 整体context | 请求前材料校验、焦点工作集、语义交付、同run安全attempt及原调用身份恢复已实施；harness历史由外部宿主控制 | [源码实施与实际宿主边界](#context-runtime-status) |
| 旧线索候选发现 | 无focus时并列发现有效Hook/OpenCondition，候选保留歧义与来源；事实必要闭包隔离作者材料 | [修复报告](../output/recall-discovery-20261011-da58368a/RESULTS.md)、[独立QA](../output/recall-discovery-20261011-da58368a/B-qa/FINAL.md) |
| 超过64候选继续查找 | `candidate_search.next_arguments`延续原frontier，每次至多新访64；原tool_results保存控制进度/指纹，不改focus/Q/CAS；可见源/别名/图/记忆变化拒绝旧入口，旧交付页兼容；UI/技术回执共用公开投影 | [本轮记录](#candidate-navigation-status)、[结果与用法](../output/candidate-navigation-20261021/RESULTS.md)、[独立QA](../output/candidate-navigation-20261021/independent-qa/FINAL.md) |
| 状态观察/作者浏览/物理存储 | live状态不隐式recall，SSE变化后读热数据；作者按需完整浏览含当前/结束状态，不改模型焦点/材料，取消后可读；大字段同Store内容去重，新旧运行逻辑兼容 | [本轮记录](#workspace-observation-status)、[结果与原始检查](../output/workspace-observation-20261021/RESULTS.md)、[架构§18](HYBRID_GRAPHRAG_ARCHITECTURE.md) |
| 记忆工具与来源性能 | 操作分支/结构与record语义拒绝含实际下标，source_invalid沿原Schema提供修正指引；源读取复用同次路径/映射，安全C解析回退保持，每次仍读真实字节 | [本轮结果](../output/project-optimization-20261021/RESULTS.md)、[独立探针](../output/project-optimization-20261021/independent-qa/probe-results.json) |
| 真实章节v3建档试点 | 归档副本中前三章9段/12536字符经原五工具与adopt建档；断点/原ID恢复、冷读来源、反转扫描序、before游标和改源失效通过 | [试点证据](../output/project-optimization-20261021/pilot-verification.json)、[脚本](../output/project-optimization-20261021/pilot.py) |
| 真实宿主样本 | 新增Codex0.163/gpt-6.1-sol max空新作两章与第三冷读：实际保存/记忆、采用/重启及状态解除有证据；旧短篇/百章人工种子样本另保留。首次提交易用性、长篇及Hook效果限度保持 | [新作品实跑](#new-story-live-status)、[context交付实跑](#context-delivery-implementation)、[整体context实跑](#context-runtime-status)、[后续记忆复测](#long-memory-retest-status) |

### 最近有证据的验证基线

本轮在 Windows 上使用本仓 `.venv` 执行项目完成门。结果见[本轮阶段记录](#author-workspace-20261125)。

#### 2026-10-23 基线与真实宿主样本

以下为该阶段的原始基线。完成门输入前后 hash 一致。[实际命令](../output/ergonomics-entrypoints-ci-20261023/gate-results.json)、[输入身份](../output/ergonomics-entrypoints-ci-20261023/gate-inputs-before.json)、[完整结果](../output/ergonomics-entrypoints-ci-20261023/RESULTS.md)

| 检查 | 实际结果 | 原始证据 |
|---|---|---|
| 项目pytest完成门 | 791 passed / 1 deselected / 90 warnings，393.19秒，exit0；CI=true，原指定排除保持，包含实际浏览器/协议/打包及48项新增回归 | [gate-pytest.txt](../output/ergonomics-entrypoints-ci-20261023/gate-pytest.txt) |
| 检索完成门 | retrieval_cases=72 failures=0，exit0 | [gate-retrieval.txt](../output/ergonomics-entrypoints-ci-20261023/gate-retrieval.txt) |
| 正式资料完成门 | 729有效文档 / 0问题，exit0；1567份非索引原件逐字不变，无新增/缺失 | [gate-validate.txt](../output/ergonomics-entrypoints-ci-20261023/gate-validate.txt)、[原件核对](../output/ergonomics-entrypoints-ci-20261023/formal-source-verification.json) |
| 独立QA | 22项通过；未知提交/丢回执恢复、旧兼容与实际入口、源码边界/浏览器finder反例；无未关闭P1/P2 | [独立报告](../output/ergonomics-entrypoints-ci-20261023/independent-qa/FINAL.md) |
| 干净输入与wheel | 无初始index的资料副本建图后72/0、729/0；新venv非editable wheel资源6项通过，独立仓外核124源码hash及15素材 | [干净验证](../output/ergonomics-entrypoints-ci-20261023/clean-verification.json)、[wheel检查](../output/ergonomics-entrypoints-ci-20261023/clean-wheel-resources.txt) |
| 真实宿主样本 | 两章1724字符、原ID更新与clear、第三冷读已完成；宿主8次remember含6次拒绝/2次成功，Store为4条去重调用记录 | [原始样本](../output/ergonomics-entrypoints-ci-20261023/live/verification.json)、[技术核对](../output/ergonomics-entrypoints-ci-20261023/live/TECHNICAL_REVIEW.md) |

前轮743/72/729、std阶段724/72/729及历史基线保留在各自阶段。当前工作流已落盘但未执行远端GitHub Actions/Linux；真实样本仍有参数与操作ID误用，不认证首次正确率改善、一般模型效果或长篇。

### 已关闭反例

| 原问题 | 当前处置与范围 |
|---|---|
| 本轮旧tuple记忆提交丢效力签名并泄漏控制键 | 独立探针先失败，限定旧tuple入口提取/移除控制键后转同一MemoryCommit；生产MemoryService使用显式结果，重启/原ID恢复通过。见[独立QA](../output/application-boundaries-20261023/independent-qa/FINAL.md)。 |
| 过期锁双恢复者读后删除新owner | 完整持有期OS guard覆盖恢复/建owner/释放，真实Windows子进程死亡恢复及确定性交错通过。新旧锁协议不得并发写。见[本轮QA](../output/architecture-std-refactor-20261023/qa-std-boundaries.md)。 |
| 库内workspace持锁时源投影复制失败 | 精确跳过运行时保留名`.writer.lock.guard`及根源锁guard，覆盖owner建立前/稳定持有/删除后窗口；普通资料与其他guard仍复制，原文件不删。见[生命周期反例](../output/architecture-std-refactor-20261023/qa-std-boundaries.md)。 |
| 无名称/ID的同义描述漏掉第1章旧伏笔 | 2026-10-11原after100、focus=[]、原问句已返回同一有效Hook，9/9指定检查通过；修复的是候选发现，不认证任意同义理解或唯一对象解析。见[修复报告](../output/recall-discovery-20261011-da58368a/RESULTS.md)。 |
| 内置会话后续请求仍发送失效稿件/条件 | 整体context阶段已实施发送前效力校验与同run安全attempt，并有chat/responses定向证据；外部宿主历史控制继续单列。见[整体context阶段](#context-runtime-status)。 |
| 2026-10-20的HTTP/完整pytest环境阻断 | 2026-10-21真实socketpair、原HTTP/stdio定向及完整641项通过，旧失败日志保留；不反推具体OS根因。见[本轮记录](#project-optimization-status)。 |
| record语义拒绝缺实际下标 | record身份/来源/Link错误在原_normalize定位具体数组项；source_invalid复用原Schema指引，不更改来源资格或幂等。见[本轮diff](../output/project-optimization-20261021/implementation.diff)。 |
| 超过64候选没有继续查找入口 | 独立候选cursor延续原frontier，130候选按64/64/2推进；原JSON/语义页仍只读已选包，重启与来源失效通过，候选根不重复访问。见[本轮结果](../output/candidate-navigation-20261021/RESULTS.md)。 |
| 新增内部遍历状态经技术回执暴露 | UI与技术回执共用public_tool_row，仅去行内candidate_search_state；原Store完整保留。独立QA复验公开回执、25页精确续读及UI逐行投影通过。见[独立QA](../output/candidate-navigation-20261021/independent-qa/FINAL.md)。 |
| 网页记忆截前16条、漏当前状态/孤立记录 | 作者browse_all共用原过滤/依赖/router，卡片每批完整显示并继续查找，状态取真实entries/ended_entries；真实浏览器130候选、孤立笔记/经历/状态及取消后阅读通过。见[浏览器证据](../output/workspace-observation-20261021/C-ui/RESULTS.md)。 |
| 新live缺父采用CAS基线、非法物理布局恢复 | live/full共用原目标投影；原Store统一校验布局/引用及精确payload。独立复验继承父采用目标、未知版本保持原字节、冲突内联/坏hash拒绝通过。见[本轮记录](#workspace-observation-status)。 |

### 开放项与验证限度

表中实现状态、待验证项与可选优化分别按实际证据记录；归档作品不作为本轮迁移任务。

| 项目 | 当前事实与剩余范围 | 后续定位 |
|---|---|---|
| 记忆工具效果（首次说明已实施、效果仍受限） | Schema同源三步示例、host字段与重试说明已交付；新版两章1724字符、宿主实际8次remember/6拒绝/2批提交，Store去重4条。原ID更新/clear与第三冷读有证据，仍未证明首试成功率改善；一般效果、Hook生命周期和长篇不认证 | [本轮样本](../output/ergonomics-entrypoints-ci-20261023/live/TECHNICAL_REVIEW.md)、[旧样本](#new-story-live-status)、[schema](../src/novel_rag/memory/schema.py) |
| 表层词句参考（资料已完成） | 用户认可先修宾语缺省和动词搭配截短；已整理64词条、连接方式/补语速查及14组易混搭配。62项有原词形用例，归还/收好标编者补充；全部引文有PDF页序并核原文。句架与原创示例为编辑归纳，尚未注册工具、注入模型或开展接入后试写，不作为评分/强制替换规则 | [词句搭配字典](references/verb-collocation-reference.md)、[初读与用户校准](../output/style-surface-study-20261021/语言DNA.md)、[核对记录](../output/style-surface-study-20261021/collocation-dictionary-verification.json) |
| 叙述指导与对话内试写（待评） | 用户指出词句样稿缺少起伏与描写、类似流水账，并明确不得作正例；核读五篇论文和一篇学术专论的相关部分后，整理细节/停顿/变化的试用指导，按指导另存R2。旧稿保留，R2待用户反馈；均未接入运行提示、自动评分或正式记忆，不认证文学效果 | [叙述指导](references/narrative-prose-guide.md)、[论文笔记](../output/style-surface-study-20261021/小说叙述_论文阅读笔记.md)、[R2正文](../output/style-surface-study-20261021/雨灯亭_叙述改写_R2.txt)、[样稿说明](../output/style-surface-study-20261021/雨灯亭_叙述改写_R2.说明.md) |
| 来源性能（限定样本已验证） | 同机610源，本轮加载均值1.511→1.059秒、默认recall 1.579→1.040秒、词查询recall 1.596→1.103秒；完整解析/Ref/gaps/两类召回JSON完全相同。与上轮C解析采样分开，不能叠算收益；尚未缓存回放或认证所有机器/远端耗时 | [比较数据](../output/project-optimization-20261021/comparison.json)、[旧解析样本](../output/writing-tools-performance-20261020-375a4d16/performance.json) |
| 已有作品归档与副本试点 | 原库513份History保持，不列原件迁移待办；本轮新授权第3项仅在副本完成前三章9段建档/生命周期试点。人工节选不代表整本剧情覆盖、人物信息全部正确或自动抽取；扩大范围需新的具体任务 | [试点与限度](../output/project-optimization-20261021/pilot-verification.json)、[源读取](../src/novel_rag/service.py) |
| 大量线索导航（已完成限定范围） | 原每次新访64边界保持；130Hook按64/64/2、真实HTTP/stdio重启及独立QA通过。frontier耗尽只表示本查询/跳数范围结束；跳数、必要依赖及显式容量缺口仍保留，不认证全图语义穷尽或任意同义识别 | [本轮记录](#candidate-navigation-status)、[原70候选反例](../output/recall-discovery-20261011-da58368a/B-qa/FINAL.md) |
| 状态与长会话成本（限定样本已验证） | live不召回/不展开冷数据，未变效力签名不写。24份相同原/交付大回执的16次持久增量累计写入46,392,069→446,245字节，整个workspace1,452,135→736,630字节；写入次数保持48。非所有回执去重比例保证，累计接收前缀/连续事件成本仍保留，未自动清理孤儿产物 | [实测数据](../output/workspace-observation-20261021/storage-measurement.json)、[限度与结果](../output/workspace-observation-20261021/RESULTS.md) |
| provider/其他宿主及文学效果（待验证） | compaction仍unsupported；内置profile真实provider、其他宿主/新协议互操作、全部窗口与缓存收益、长篇自动维护和文学效果分别待验证。不可观测峰值及有限样本不推断为通用结论 | [整体context边界](#context-runtime-status)、[harness合同](HYBRID_GRAPHRAG_ARCHITECTURE.md#harness-integration) |

### 后续维护方式

1. 继续开发先读本摘要，再读对应权威合同、原owner及阶段证据；历史反例先核对是否已关闭。
2. 每个实施增量更新本摘要受影响的能力、基线或开放项，并追加有日期、执行范围和证据路径的阶段记录；入口文档继续只链接摘要。
3. 新验收只绑定实际运行输入；本地程序检查、真实宿主样本、文学效果及未验证能力分别记录。旧记录及原失败证据保留，不用新摘要改写旧实验结果。

<a id="stage-history"></a>
## 阶段记录（历史）

下方按各阶段发生时的状态保留原文与证据；其中“当前”“下一步”“未修复”均指当时阶段。继续开发使用上方[当前状态摘要](#current-status)判断现状，避免将已关闭反例重新作为未完成项。

<a id="runtime-complexity-20261125"></a>
## 2026-11-25 记忆、原文交付与资料编辑复杂度优化

选择四处高频维护的规则，沿用原有公开接口。下表的入口指标从 1 起算，按 Python AST 计入条件、循环、异常分支、布尔短路和推导式。拆出的私有函数单独计数。在本次涉及的六个 Python 模块中，函数体决策点合计从 875 降至 854。七个实现文件合计增加 85 个物理行，包含函数说明。[分文件数据及验证记录](../output/main-path-complexity-20261125/verification.json)

| 调用入口 | 实现变化 | 对照结果 |
|---|---|---|
| `remember`、旧批次回读 | 五种操作的字段组合由模型 Schema、运行时校验及错误提示共用。结构校验直接读取规则，保留持久化字段和错误顺序。`validate_memory_update` 的入口指标从 109 降至 15 | 63,170 组结果、拒绝信息和顺序相同，4 份声明或示例的有序 JSON 完全一致。[Schema 实现](../src/novel_rag/memory/schema.py)、[操作合同测试](../tests/test_memory_tool_contract.py) |
| `MemoryService.recall → route` | 有界候选搜索、必要依赖、默认整包选择和显式预算分别维护。查询词复用节点的一份序列化正文，完整包共用一处来源投影。`route` 从 113 降至 25 | 1,478 次输出及错误对照、1,000 组同成本预算排序均一致。同一作品的 32 个实体和 19 个查询词，编码从 608 次降至 32 次。[路由](../src/novel_rag/memory/router.py)、[候选及容量测试](../tests/test_memory_router.py)、[架构 §7.7](HYBRID_GRAPHRAG_ARCHITECTURE.md#event-memory-router) |
| 创作上下文、`read_document` | 技术槽的身份字段用于输入检查和生成续页，段落分页与草稿父链校验各有一处实现。旧生成入口共用作者偏好路径，模型请求沿用已绑定的文本，显式续读重新核对正文指纹。`_read_document` 从 55 降至 30 | 186 组请求共 210 份响应，正文、元数据、续页及错误的序列化一致。同一请求的偏好读取由 2 次降至 1 次，变更后用旧指纹续读仍收到冲突。[读取工具](../src/novel_rag/generation/tools.py)、[材料绑定](../src/novel_rag/generation/context.py)、[回归测试](../tests/test_context_delivery.py)、[来源契约](HYBRID_GRAPHRAG_ARCHITECTURE.md#source-references) |
| 工作台资料与偏好 | 3 处作品线状态合为 1 处，11 个异步回调共用作品线和请求序号检查。切换、返回及重载共用详情重置和未保存输入缓存。`workspace.js` 净减 47 行 | Chrome 实测从首页进入资料，换项后可恢复未保存文字，保存显示修订 2，返回再进入保留选中资料且无额外请求。延后同一资料的旧错误响应，当前编辑仍可用。并发修改时仍返回 `409` 并保留输入。[工作台实现](../src/novel_rag/web/static/workspace.js)、[浏览器回归](../tests/test_metro_browser.py)、[工程归属](ENGINEERING_REFACTORING_BOUNDARIES.md) |

Windows、Python 3.10.1 下 pytest 通过 812 项，按项目要求排除 1 项，产生 90 条警告。检索 72 例全过，729 份文档校验无问题。隔离安装 wheel 后，7 个改动实现文件与源码逐字节一致，6 项安装包检查通过。另比对同一运行的全部工具声明、模型上下文和完整上下文，66,174 字节的 JSON 相同。正式库的 1,567 份非索引文件逐项匹配归档哈希。本轮使用本地模型协议夹具，线上模型及 Linux 尚未实测。[pytest](../output/main-path-complexity-20261125/pytest.txt)、[检索](../output/main-path-complexity-20261125/retrieval.txt)、[文档校验](../output/main-path-complexity-20261125/validate.txt)、[测量口径和代码指纹](../output/main-path-complexity-20261125/verification.json)

<a id="author-workspace-20261125"></a>
## 2026-11-25 续写恢复、作者保存、首页读取与流式写盘

- 在本地 HTTP 续写入口分别中断父稿正文、运行快照和会话索引的写入。重启后两次并发重试得到同一个子运行，选定的父稿只拼一次，会话只登记一次。显式更换父稿仍收到冲突，已有作者稿与终态保持。旧内联运行也可补登缺失索引。[续写恢复回归](../tests/test_harness_v3.py)
- 时间线注册暂时失效时，作者仍收到本次实际提交的引用、修订与全文。网页使用轻量回执，打开记忆页时独立显示读取失败，恢复注册后可以重读。另测了视图读取失败时的父稿加后缀、保存期间继续编辑，以及回执到达前已产生更新修订的情况。[HTTP 回执](../tests/test_web_edits_v3.py)、[提交身份](../tests/test_application_boundaries.py)、[实际浏览器](../tests/test_writing_experience_browser.py)
- Chrome 冷启动进入首页，资料请求和正文快照读取均为 0。打开资料面板后显示 610 项，偏好读取 0 份正文，列表和详情各读取 652 份。选择另一条资料、返回首页再进入，保留选中项且未重复请求。另测了面板折叠、直接进入、快速切换作品及保留未保存的编辑。[导航回归](../tests/test_metro_browser.py)、[实测记录](../output/author-workspace-20261125/verification.json)
- 在同一作品上接收 2,048 个汉字。16 次增量的累计 JSON 写入从 10,981,693 降至 5,522,891 字节，64 次从 44,513,284 降至 22,370,999 字节。每个增量仍先保存接收前缀，再一次替换运行快照。已验证连续序号、重启补发缺失文本、取消和断流后的前缀。测量只统计两个 JSON 文件的原子写入字节。[存储回归](../tests/test_run_store.py)、[原生流取消与恢复](../tests/test_run_recovery.py)、[分文件实测](../output/author-workspace-20261125/verification.json)

实现沿用[架构 §11 的 HTTP 和事件契约](HYBRID_GRAPHRAG_ARCHITECTURE.md#11-http事件与本地信任边界)。

| 操作 | 调用方与实现 | 可观察结果 |
|---|---|---|
| 创建续写 | [HTTP feedback](../src/novel_rag/web/app.py#L152) 和既有 `start` 经 [RunService.prepare](../src/novel_rag/generation/session.py#L155) 恢复固定绑定 | 同一 `request_id` 和参数返回原 `run_id`，换父稿或检查点返回 `409` |
| 保存作者稿 | [HTTP save](../src/novel_rag/web/app.py#L188) 调用 [save_author_draft_receipt](../src/novel_rag/generation/session.py#L323)，与现有 `save_author_draft` 共用正文拼装和版本检查 | 正确修订返回本次提交的引用、修订和正文，过期修订返回 `409` |
| 打开资料 | [工作台](../src/novel_rag/web/static/workspace.js) 调用偏好、列表和详情。偏好与现有 `load_story_sources` 共用 [load_story_scope_registry](../src/novel_rag/service.py#L133) | 作品或时间线未注册时拒绝读取。正常返回面板保留所选文档 |
| 接收增量 | `RunService.run` 的 `on_delta` 将本轮累计文本交给 [DraftStore.receive](../src/novel_rag/generation/store.py#L238)，沿用该运行的接收文件与事件序列 | 重试只发布尚未登记的文本，改写已接收前缀会报协议错误 |

首轮完整测试在停止续写时发现，磁盘已有 `cancelled`，迟到的浏览器响应仍可把状态盖回“已请求停止”。用 Chrome 分别延后取消回执和运行中快照后，在旧实现上复现了两种顺序。修复后两种顺序都显示“本轮已停止”，刷新后可保存部分正文并发起续写。[首轮日志](../output/author-workspace-20261125/pytest-initial.txt)、[浏览器回归](../tests/test_workspace_browser.py#L360)

跨轮重启也有单独的断点。第一轮完成、第二轮首段落盘后中断运行快照替换，重启可直接看到第二轮正文。第二轮尚未收到文本时仍显示第一轮。现行布局、旧内联和旧外置转录均已验证，读取不会推进事件序号，显式重试只追加一次。[跨轮恢复用例](../tests/test_run_store.py#L162)

项目规定的三项完成门在 Windows、Python 3.10.1 上通过。pytest 通过 810 项，按项目规则排除 1 项，产生 90 条警告。检索 72 例均通过，729 份文档校验无问题。隔离安装最终 wheel 后，7 个改动实现文件与源码逐字节一致，6 项安装包检查通过。正式库 1,567 份非索引文件逐项匹配归档 SHA-256。模型流使用本地协议测试服务，线上模型和 Linux 未在本轮实测。[pytest](../output/author-workspace-20261125/pytest.txt)、[检索](../output/author-workspace-20261125/retrieval.txt)、[文档校验](../output/author-workspace-20261125/validate.txt)、[浏览器、写盘与安装包记录](../output/author-workspace-20261125/verification.json)

<a id="ergonomics-entrypoints-ci-status"></a>
## 2026-10-23：记忆首次使用、入口惰性加载与架构检查完成

用户指定先做建议3/4/5并使用design-review-council。A设计、B红队、C实施验证、D可维护性独立审查后，按架构§21和工程边界§8.19实施；基线保存281份工程文件及1567份原件hash，既有dirty工作保留。裁决、增量和原始验证见[结果](../output/ergonomics-entrypoints-ci-20261023/RESULTS.md)。

记忆示例由schema唯一owner生成，原生请求和MCP使用同一结构；真实示例生命周期、整批拒绝、已提交丢回执及原键恢复均通过。CLI保留真实handler和替换点，包导出保留原对象；实际write/Web+harness在禁止旧生成/审批/confirm导入时通过。架构AST门有合法/违规样例，浏览器finder支持Chromium且CI缺失失败；工作流补齐干净建索引和真实wheel门。没有新增Store、校验器或动态调度框架。

最终791 passed/1 deselected/90 warnings（393.19秒），检索72/0、资料729/0；门前后输入不变，1567份原件逐字保持。独立QA22项通过，干净资料与非editable安装通过。定向测试曾因scene_id可选、原服务内部恢复、MCP模型视图不内嵌tools等夹具假设失败，修正测试后完整门通过；生产校验未放宽。远端CI及Linux仍未运行。

复用旧大纲/提示与已验证runner，以现有ChatGPT登录完成两章和第三冷会话；只在本轮output新库采用，主控没有补记忆。两章959+765=1724字符，实际宿主8次remember中6次拒绝、2次成功；去重Store行仅4条，两者分开计数。模型自行修正后沿原ID更新并clear原义务，冷读依据实际正式来源回答；原始日志/失败保留，不把有限样本当首试正确率或长篇改善认证。

<a id="application-boundaries-status"></a>
## 2026-10-23：应用入口与运行提交两处解耦完成

用户在整体耦合审查后指定CLI/Web和草稿/记忆/采用两处。四角色独立评审后按架构§20实施；before快照保留239份工程文件，1567份非索引资料仅作字节核对。改动与最终证据见[RESULTS](../output/application-boundaries-20261023/RESULTS.md)、[实际增量](../output/application-boundaries-20261023/implementation.diff)。

RunService接管运行视图、建议坐标/目标hash、脱敏启动信息、观察和采用/编辑入口。Web原18处Store/config/memory直接引用、CLI原3处Store引用清零；HTTP/CLI响应字段、SSE原热快照与生命周期保持。MemoryService与AdoptionService各1处store.write移入专用Store操作；双CAS、同签名不写、回执重读更新与原幂等表继续同一权威。纯memory/effects判定草稿失效，MemoryCommit明确传递批次/回执/签名，不新建Store或事务框架。

独立QA发现保留的旧二元组builder会丢失内部效力签名；保留失败证据后修复入口转换，原控制键提取并移除后进入唯一提交实现。3个独立探针覆盖真实跨run锁竞争、草稿提交后事件故障及旧builder恢复；最终独立22项通过，无未关闭发现。首轮pytest因该修复主动中断，最终从稳定输入重跑：743 passed/1 deselected/90 warnings，360.80秒；检索72/0，资料729/0，1567份非索引文件字节不变。

残留协作明确保留：MemoryService同次快照与remember的必要锁域、generation内部运行协调仍使用原Store聚合；本轮不扩展到v2装配、包初始化及context/tools循环。没有付费或真实模型调用，也未提交/push；现有文学/长篇/其他宿主边界不因本次软件回归而改变。

<a id="std-package-refactor-status"></a>
## 2026-10-23：项目std与包边界四批重构完成

用户确认“项目内基础库std＋业务包＋通用函数＋Python标准库”并批准四批实施。权威架构§19与工程边界STD-01–04沿原文档维护；没有另建Store/模型/写作流程。实现与完整变更见[RESULTS](../output/architecture-std-refactor-20261023/RESULTS.md)、[增量diff](../output/architecture-std-refactor-20261023/implementation.diff)。

std迁移UTC/字节SHA/原子IO/既有JSON，FileMutationLock使用标准库OS互斥；contracts承载纯Ref与校验。旧owner同对象导出，generation包惰性加载v2，来源类型导入项目模块由36降至6。单源工厂归mutations/source，作者保存归RunService；源锁→Store锁、CAS/未知写恢复与采用后待完成保持。源码统一迁入src，模板/静态/参考随包，资料根由调用者或启动cwd提供；scripts/tests消费安装包。

完成门：724 passed / 1 deselected / 90 warnings（389.74秒）、retrieval72/0、validate729/0，均exit0。独立QA46项及6生命周期场景通过；初版venv PID证据缺陷、库内workspace guard复制回归经修复复验，失败记录保留。最终wheel在无system-site-packages环境安装，并在真实仓库外系统临时目录验证CLI/新库/模板/参考/Web；原库1567份非索引文件逐字不变。源码/资源与最终wheel、QA身份一致，新增修改函数四项注释审计通过。

Windows已验证；POSIX/网络文件系统跨主机锁未实测，新旧锁协议进程不得并发写。所有旧API/六组shim/历史run/正式作品/未提交工作保留，未提交push、未改全局配置或调用收费模型。后续开发先激活本地.venv，`python -m pip install -e ".[dev]"`；默认资料目录为启动cwd/novel-rag，非仓根需显式--library。

<a id="narrative-guide-sample-status"></a>
## 2026-10-21：叙述指导与R2独立样稿

按用户“先写一个指导，然后按照指导再写一版”的授权，先保存[试用指导](references/narrative-prose-guide.md)，再改写《白跑的一趟》。指导承接词句搭配要求及[论文研究](../output/style-surface-study-20261021/小说叙述_论文阅读笔记.md)，聚焦细节选择、叙述停留与读者理解变化；不新增角色模型或文学审计。

[R2正文](../output/style-surface-study-20261021/雨灯亭_叙述改写_R2.txt)按原大纲保留人物、实际归还、许澄获知顺序与未解短划，补入日常细节，另存UTF-8文件。编码/换行/引号及长片段重合检查通过，仅为文件检查；文学效果待用户反馈。旧词句样稿明确不得作正例，R2也不自动收为正例。原两章、已有归档作品和运行配置未改，未正式采用或更新记忆；本轮不涉及通用模块，未重跑程序测试。

<a id="new-story-live-status"></a>
## 2026-10-21：新作品真实写作与冷会话记忆核对完成

用户授权第4项为“用新作品跑一轮真实写作和记忆验证，已有归档作品不要改”。本轮不改工程实现：通过原create_story在output/new-story-live-20261021/library新建唯一原创作品《雨灯亭的蓝线》，只有独立人物/场所/物件Canon与作者路线，初始记忆0批；未复制归档剧情或由主控预植状态。沿既有真实runner、五工具、MemoryService/SourceCorpus及AdoptionService执行，原[结果与限度](../output/new-story-live-20261021/RESULTS.md)、[原文](../output/new-story-live-20261021/雨灯亭的蓝线.txt)、[实际分口径回执](../output/new-story-live-20261021/verification.json)和[独立QA](../output/new-story-live-20261021/independent-qa/FINAL.md)保存。

Codex CLI0.163.0请求gpt-6.1-sol/max，三个独立冷宿主及重启后端。第一章1030字符、第二章834字符均由模型save/remember/recall；主控只采用本次新作品，再以真实正式Ref准备后续run。第一章实际5次remember/4拒绝/1批，第二章2次/1拒绝/1批；Store唯一行分别为3条/2条，与真实调用分开，失败无可见半批或提交标记。初试错误包括平铺entry、holder=null、更新嵌身份/来源、clear多字段；同ID改参数正确409拒绝，原参数重放仍原拒绝，模型新意图修正后成功。最终成功不等于首次顺畅。

原World保管、CharacterView认识与未解三短划ID保持，第二章实际交还与目击/当面说明后更新；原归还OpenCondition由成功批次clear同一ID。第三会话9次recall/3次read_document、无写工具，实际语义续页读到原解除回执与两章正式来源，四问均有正文/记忆支持；后台泛词probe未选解除记录不当作未解除。未知短划只记World，未覆盖Hook。两次正式History正文逐字等于保存稿，原DocRef/hash/after位置匹配，28项机械核对全真；独立审查另读正文及实际交付，不把冻结全包或后台probe当模型已读。

三次模型宿主exit0，耗时181.78/216.69/135.19秒。驱动脚本将只读run误建为write后请求completed，因无正文检查点被拒而exit1；原脚本/日志/首次报告保留。核定无正文/记忆/写提交后，按原生命周期以cancelled关闭同一只读工具入口，未为收尾补稿、重试模型或修改生产规则。机械初稿误用RagDocument.text的夹具错误亦保留，改用实际body.content后通过。

新库validate为5有效文档/0问题、exit0；工程202份运行输入及原库1567份非索引输入起止hash相同。本轮未改通用模块，因此最近完整门仍为上方663/72/729原基线，不将产物检查当新全量门。累计provider报告输入1545473（其中cached1366272）、输出16202，reasoning8743不再叠加；不是单请求峰值或费用。只认证一短篇的内容链路，不能证明仅靠记忆续写、百章持续维护、一般首试率、文学效果、其他宿主或超过64候选导航。恢复新作须同时保留library和workspace发布保护，不能只拷两个History到空Store。无全局配置或归档作品改动，未commit/push。

<a id="workspace-observation-status"></a>
## 2026-10-21：状态观察、作者记忆浏览与运行存储完成

用户明确design-review-council并授权落实前三项，归档作品不改。A架构、B红队、C实现验证、D可维护性四个独立角色，主Agent裁决并负责后端/共同owner/文档，C拥有前端/浏览器测试；合同沿架构§18与AC-WO-01–06。before副本、12份运行输入hash、实际diff与[结果报告](../output/workspace-observation-20261021/RESULTS.md)在output/workspace-observation-20261021，不另建规划系统。

live观察与主动记忆浏览分开，默认full兼容；不变签名不写，SSE变化后只读热快照。作者browse_all沿原过滤/依赖/router，每批至多64新访问，取消后可读；原tool_results行tag作者来源，模型消费集中排除，不改持续focus/Q或模型材料。卡片不再截16条，当前/结束状态取原state_view；失效重新查，跨run/重查迟到拒绝。原五工具停止门、来源真实字节/hash与默认无token容量保持。

Store按内容物理去重工具大字段/逐turn/逐batch/逐draft，先payload后run，load还原旧逻辑形状；不批量迁移归档run或删除连续事件/冻结交付。独立复核实际发现并关闭冲突内联＋引用未拒绝、未知布局被recover降级、live丢继承父采用CAS基线三项；真实浏览联调暴露重复冷历史读取回退，resolve_draft复用同次同身份元数据，仍核真实正文，目标轻读只展开所选检查点。

20项原回归、39项owner/context定向、小包进度1项及真实浏览器3项通过，独立B六组＋四组增量/小进度附录、D旧/新布局/恢复/采用目标复验通过。最终59个变化函数注释齐全，12份运行输入重新冻结后三完成门**663 passed/1 deselected/90 warnings，370.82秒；72检索/0失败；729有效文档/0问题**，均exit0。首pytest32%为小包进度修正主动中止，原日志保留，不作通过；最终12文件与原库1486份YAML字节不变。本阶段关闭，没有外部模型调用，物理字节与联调中间版本网络样本/限度见结果报告，不认证文学效果或全图语义穷尽。

<a id="candidate-navigation-status"></a>
## 2026-10-21：超过64候选的继续查找完成

范围为用户本轮明确授权的原第4项，归档作品不改。R/D在权威架构§7.9.5/AC-MEM-12–13；沿原router/MemoryService/ToolDispatcher/context及RunService原tool_results行实施，无新工具、Store、模型、来源解析器或默认容量。原JSON/语义页的next_arguments只读已选原包，candidate_search.next_arguments另查frontier；每次最多新访64，原query/focus和完整必要包保持，候选仍标未确认对应。实时工作集给根查询入口，不伪造冻结回执。

before字节副本、源码/测试输入hash、注释核对、原失败与[当前结果](../output/candidate-navigation-20261021/RESULTS.md)在`output/candidate-navigation-20261021`。原8项正确红灯均缺candidate_search；首次实施回归1失败/7通过，失败为把新读取调用ID不同误当数据不等，改为同原读取ID重放核对；第二轮52通过/1失败为测试预设Pending必在首64，实际原排序允许它在后批，修正为两批完整保留，未更改原排序。上述原日志保留，不当生产修复或放宽“不得丢失Pending”。新增/协议定向19项通过（83.04秒），含130Hook的64/64/2、原ID/服务重启、prepare后新增未选来源改字节、别名/记忆变化、异run/hash/额外参数、共享依赖/计划桥隔离、实时工作集与真实HTTP/stdio重启。

独立QA首次实测技术回执包含新控制字段，主Agent补查UI快照后，由唯一generation/store.public_tool_row统一公开投影，仅去candidate_search_state，保留原Store行及参数/回执。首完整pytest约44%因修复主动中止，无完整结果，原日志保留；中间仅回执修复的45项定向通过，不认证最终八文件。最终八文件上的定向27项通过（49.85秒）；独立修后复验通过原回执/原Store、25页精确续读、服务重启与UI逐行公开投影。独立复验中一条过宽递归断言误把恶意cursor原参数当控制状态，修正为精确投影比较后通过，原exit1与修后exit0均保留。

最终三完成门**653 passed/1 deselected/90 warnings，338.68秒；72检索/0失败；729有效文档/0问题**，均exit0；完整门含真实HTTP/stdio用例。独立QA结论PASS，范围与未跑项见[FINAL](../output/candidate-navigation-20261021/independent-qa/FINAL.md)。最终8份运行输入与原库1486份YAML hash不变，24个新增/修改函数均含四项注释。未调用外部模型，不认证文学效果、任意同义识别或全图语义穷尽；跳数/依赖/显式容量边界保持。当前阶段关闭，后续从上方摘要及本轮原owner续接，不改历史日志或归档作品。

<a id="project-optimization-status"></a>
## 2026-10-21：优化1、2收尾与真实章节副本的v3记忆试点

续接“项目优化建议”原聊天，用户本轮明确继续未完成工作及第2、3项；归档原件仍保留。沿原MemoryService/SourceCorpus/documents与五工具/采用owner，不新增规划系统、缓存、回放器或模型阶段。before副本、原始计时、真实副本、断点状态和[本轮结果](../output/project-optimization-20261021/RESULTS.md)在`output/project-optimization-20261021`。

第1项补齐record身份、来源与Link语义拒绝的实际数组位置，source_invalid复用memory_update_guidance提供合法形状及recall动作；原CAS、原参数操作身份和整批拒绝保持。第2项在公共load_document中同路径直接复用快照映射，异名路径仍解析物理身份；原_paths_for_scope每书根只resolve一次，SourceCorpus.search无词/无focus不再无条件分块。每次仍重新读源字节并绑定同次hash，没有mtime缓存或事实副本。

同机610源各三次采样：加载均值1.511→1.059秒（约30%）、默认完整recall 1.579→1.040秒（约34%）、词查询完整recall 1.596→1.103秒（约31%）；完整解析值/Ref/gaps及两类packet JSON逐字段相等。改后首几秒与定向pytest重叠，保留原数据，不把有限计时当统计保证，不与上轮C解析收益叠算。

第3项将原库复制到本轮pilot-library，仅在副本按第一卷前三章9段/12536字符逐字save，并用人工选定的原文节选经remember/adopt建立9批次、9经历、9事件线/Link及1项早期未解问题。真实提交后先退出进程而不将回执保存到试点状态，新进程使用原operation_id/原参数恢复恰好一批；第一章3段完成后再次重启续完其余6段。冷读逐项核原文/节选与正式Ref；反转源扫描序仍得原故事序，before第2章只返回第1章3项；实际改动末段副本字节后对应经历退出召回且旧DocumentRef被revision_conflict拒绝，恢复原字节后重现。原件1486个YAML逐文件hash保持。脚本首次冷reader漏标harness驱动，按真实权限被拒，已仅修试点夹具，原失败保留；未把它当生产修复。

本轮完成门为**641 passed/1 deselected/90 warnings，278.24秒；72检索/0失败；729有效文档/0问题**，三者exit0。独立QA探针从原合同验证来源/物理别名/游标/lineage、搜索等价、第二条record身份/来源拒绝与合法修复/幂等，五份受影响源码/测试起止hash一致；探针错误预期与最终日志分别保留，不用确定性次数替代模型成功率。新增/修改7个源码与测试函数均含四项注释。

恢复试点须同时保留pilot-library与完整pilot-workspace中的发布journal/保护快照；只复制作品目录、用空Store读取会保守标发布清单缺失/基线未知，不提供有效经历，不能称单独库目录即可迁移恢复。

本轮没有外部模型调用、正式原件改写、全局配置修改、主预览部署或Git提交/push。人工节选仅验证该段建档与生命周期，不认证整本自动抽取、完整剧情/人物信息覆盖或文学效果；scope_denied不扩展为结构纠错，其他宿主/provider与大量候选导航仍见上方开放项。当前本轮无未完成实施项，后续扩大语义建档或真实模型实验需按具体任务续接，不自动迁移归档原件。

<a id="writing-tools-performance-status"></a>
## 2026-10-20：记忆工具易用性与来源解析已落盘，完整门受环境阻断

范围仅为用户选定优化1、2，已有作品按归档资料处理。本轮前字节副本、代码清单及源总指纹在`output/writing-tools-performance-20261020-375a4d16/before`、before.json和baseline.json；不以Git HEAD以来所有既有未提交改动作为本轮变更。

memory/schema复用既有字段与校验，派生互斥oneOf、下标错误及公共memory_update_guidance；ToolDispatcher只附失败details，MemoryService提示原状态身份与读取动作。documents原解析入口使用可选安全C后端并保留SafeLoader回退，每次源字节读取/快照hash及来源效力合同保持。

旧实现正确红灯为10 failed/8 passed，见red-tests.txt；最初一次测试插入位置错误已修正后重跑，不将该夹具错误当作产品反例。改后定向为73 passed/6 failed，六项均在真实HTTP/Uvicorn启动处超时，原始focused-tests.txt保留。独立38项pytest、384组Schema/host分支及1014畸形输入、真实身份/整批/重启幂等与来源失效指定检查通过，分组不叠加为模型样本数；完整判词、脚本及旧Ref错误码期望纠正在independent-qa/FINAL.md。

性能样本前2次3.706/3.599秒，后3次1.997/2.103/2.294秒；均值3.653→2.131秒，仅source加载，完整原数据/前后profile见performance.json与before/after-profile.txt。660份可见源与旧安全解析值一致、610份Ref/gaps一致，正式源总指纹仍为原值。12个新增/修改函数的四项注释检查无缺项，增量空白检查无新增问题。

完成门如实分开：retrieval-gate.txt为72/0、validate-gate.txt为729/0，均exit0；完整pytest原命令只有项目既定一项排除，首次75秒外部限时中止，full-pytest-gate.json标blocked_timeout。第二次仍停在93个进度点；按原收集次序独立运行下一项test_native_manifest_and_explicit_cache_match_actual_request[chat]，在asyncio.run创建事件循环时取得socketpair→accept阻塞堆栈（full-first-stall-stack.txt），确认后通过执行会话中止原复跑，full-pytest-gate-extended.json标blocked_interrupted。两次都没有完整pytest结果，诊断不是替代门禁。

独立最小ASGI（不导入novel_rag）与实际app均在Python3.10.1的socketpair→accept、应用lifespan之前阻塞；Selector和默认/IPv4/IPv6短超时对照均复现，不能归为本轮YAML或Memory回归，也不能算HTTP已通过。保留原fixture/等待/全局配置，不用新增跳过或另一个事件循环掩盖阻断；独立报告不推断具体OS/sandbox根因。

恢复时先确认socketpair和最小ASGI可以启动，再复跑原定向及三道完成门；三者全绿前本包不标完成。部分既有record语义拒绝仍无下标/读取动作，真实模型首轮成功率和端点Schema接受情况亦未新增认证。结果入口为[RESULTS.md](../output/writing-tools-performance-20261020-375a4d16/RESULTS.md)。未调用外部模型、修改正式作品或提交/push。

## 2026-10-11：无名称/ID旧伏笔召回反例已修复

用户明确要求修复上轮“只用同义描述漏召回旧伏笔”。沿code-quality-workflow及既有design-review-council，在原router/graph/context/五工具owner完成增量，合同见权威架构§7.9.5。A设计、B红队与独立QA、C实施/Eval＋维护建议、基线/备份/前后反例和[最终报告](D:/novel-project/output/recall-discovery-20261011-da58368a/RESULTS.md)在`output/recall-discovery-20261011-da58368a`；未创建另一套规划/Store/路由模型。

无focus时并列发现有效非作者材料Hook/OpenCondition，保留原nature/text/来源/位置，标记“线索候选（未确认对应）”；在访问截断前优先实际线索，普通词面噪声和词面命中的作者计划不再挤掉少量候选。明确focus保持定向；语义完整包及过大包入口同步携带原selection_reasons。memory/graph.is_author_material统一作者材料条件，事实必要闭包遇作者计划/纯作者关系时主体整包退出并给缺口，明确读计划仍可孤立参考，不能从计划桥接其他经历。公共owner及去重清单已同步，参数/五工具/默认无token容量保持。

原100章/423869正文字符、真实after100、focus=[]、问句`最初捡到的那枚金属小物还有什么没有弄明白`不变：现已返回`hook-8de16619e5184d5ab49056a45dccc372`，第1章来源、原位置、unresolved性质及全文逐字段等于旧具名对照；原失败包保留。其余八题也通过，共9/9；真实RunService.harness_tool的model默认1页含同一Hook及候选理由，未补写事实或草稿。上轮下方失败条目是历史证据，本反例在本轮关闭；不以具名后补读替代原问句成功。

最终完成门：**628 passed/1 deselected/90 warnings，304.49秒；72检索/0失败；729有效文档/0问题**，三者exit0；定向78 passed。B新进程独立17反例、实际作者计划桥复验、18百章/来源核对和8实际语义续页核对通过，分组不冒充统计样本；见[独立QA](D:/novel-project/output/recall-discovery-20261011-da58368a/B-qa/FINAL.md)。默认页没有next，因此语义续页通过另一次小窗取得真实返回参数后复验：改源前可读，字节改源后同参数拒绝；原文/JSON分页也实际执行失效。修复期间补充作者计划词面饥饿、测试与QA期望纠正及第一次完整pytest主动中止均留证据，不算最终门通过。

最终运行/独立QA绑定frozen.json revision2的198份源码/测试/JS/文档；本条是之后唯一交接文档变化，194份运行输入仍冻结，正式库指纹不变。本次没有新外部模型调用；人工百章与手工记忆不能认证整本自动抽取、任意同义查询精确识别或文学效果。多个候选保留歧义，超过64候选保留真实未访问缺口，本轮没有增加全图候选导航；冻结页只恢复原选包，拿到参考不授予人物知情。全局配置/主预览/正式小说未变，未commit/push。

<a id="long-memory-retest-status"></a>
## 2026-10-11：长篇＋记忆区召回复测完成，保留同义伏笔召回缺口

用户要求先检查再过一轮长篇/记忆召回。沿code-quality-workflow复核本轮源码与上轮194项运行基线无漂移，使用既有百章人工夹具和真实Codex runner；本轮没有生产实现、工具schema/全局配置或正式小说改动。原始记录与[结果报告](D:/novel-project/output/long-memory-retest-20261011-17792e70/RESULTS.md)在`output/long-memory-retest-20261011-17792e70`。

前检查固定真实history-chapter-100 Ref/after100，恰好100章、423869正文字符；旧库还有前次采用101/102，保留且不进入当前窗口。8项核心召回通过：最新保管、未解旧Hook、旧学校广播/World新现状、手册承诺解除、秘闻知情边界、同名身份、before60与fork60；无名称/ID的同义旧伏笔查询仍失败，未以具名后补命中替代。

两次独立冷Codex0.161请求gpt-6.1-sol/max：首轮保存938字符，实际更新原World/custody及原CharacterView/belief，两次remember成功、0拒绝，memory_revision2；两项源/获知点都绑定真实新稿。新child在save前实际recall交付同一新条目，不remember/补批次，保存411字符后缀，全文1349=938+411精确一次拼接。告示认识四字段都有正文依据，保持“据告示所称/未核实全部桥体安全”，未回退旧广播或无据揭晓秘密。耗时347.53/272.83秒，调用数/累计usage单列，不作成本比较结论。

本轮三门再次**615 passed/1 deselected/90 warnings，263.63秒；72检索/0失败；729有效文档/0问题**。B独立预先来源6项、逐字段前检查、真实公开事件/原回执/原文/批次的35项机械核对与最终读审完成，详见[FINAL.md](D:/novel-project/output/long-memory-retest-20261011-17792e70/independent-qa/FINAL.md)与semantic-verdict.json；审查者未跑模型/补事实或修改生产。测试结束及独立QA时198份源码/测试/文档hash一致，本条为其后唯一交接文档增量，原冻结证据保持；194运行输入及正式库/隔离源仍同字节。

当前明确维护反例：after100、focus=[]、query=`最初捡到的那枚金属小物还有什么没有弄明白`返回hooks=[]，第1章原未解Hook有效且具名/原ID查询可取。缺口是语义重述可能漏旧线索，不能解释为不存在；保留原包、query/游标/有效Hook对照，下一步在原router/查询owner定位并验证，不自动改正文或记忆。这轮提示增加了schema/身份提醒，第二资源同时可见父稿；因此新知持久化路径通过不证明模型一般可靠性提高，亦不证明生成只依赖memory。百章种子由人工经真实工具构造，未跑整本自动抽取/整篇生成/多宿主泛化或旧窗口遗忘，provider峰值/seed不可观察。

<a id="context-runtime-status"></a>
## 2026-10-10：整体context源码已实施，真实宿主证据单列

用户在完整架构复核后明确“做吧”，授权实施既有§7.11/IMP-CTX-01–06与AC-CTX-07–18；需求和设计仍归权威架构。本轮字节基线及恢复目录为`output/context-runtime-20261010-bd48b011`。已有未提交/未跟踪改动保留，正式小说、全局配置、主预览与Git发布不在本轮写入范围。

实际分工：主agent负责session/Store的发送效力、同run安全attempt、网络前turn绑定与交接；A负责原Memory/router工作集、context共同编译、五工具语义/旧游标交付；D负责原模型客户端/配置的显式可选窗口和运行策略、请求计量及严格能力边界；C/B独立构造原RunService、临时库和真实stdio反例，不写生产实现。194份源码/测试/JS已冻结且独立检查前后不变；本轮新三完成门615/72/729全绿，未沿用旧536认证新增功能。

实施细化沿既有owner：自身已明确提交且材料仍有效的save/remember不因版本数字变化强制重建；原turn在网络前保存attempt/发送绑定；未保存公开文本提供原turn技术读取入口而非DraftRef；窗口未知不猜阈值，明确容量错误不循环重发；过大语义包给可前进的原冻结包恢复路径。完成后补实际实现、原始检查、残余边界及AC逐项状态。

| 实际能力 | 落盘入口/不变量 | 新验证 |
|---|---|---|
| IMP-CTX-01：失效历史与调用身份 | context_binding逐发送检查实际源/作者版本；原turn准备先于网络，invocation_key隔离attempt；自身已知回执可KEEP，未知效果停止后续写 | 原P1两协议、迟到来源、父前缀append/rewrite、重复providerID、提交后丢回执与原键恢复，C/B真实运行通过 |
| IMP-CTX-02：工作集与语义交付 | holder/target在原router截断前优先；持续focus显式替换/清空，临时query/失败/续页不改；原完整包与旧JSON cursor保留 | A82自检，B/C独立投影/信息迷雾/过大包/旧cursor与默认恢复反例通过 |
| IMP-CTX-03：窗口/协议与恢复 | max_turns默认None；window/reserve显式，unknown不猜；活跃Responses链完整；长纲历史交付≠新窗口包含，技术text/receipt可精确读但非故事事实 | 17+turn、显式run_limit、容量0请求、普通400、取消/断流prepared/partial、长纲重读/段落相对范围通过 |
| IMP-CTX-04：harness共同交接 | 同context_state快照/model版本3，full版本2兼容；host_history_control=external_host；原operation_id和CAS保留 | 真实loopback/stdio刷新、取消恢复与作用域拒绝通过；真实Codex续写另列，不宣称后台清历史 |
| IMP-CTX-05：可选策略与观测 | validate_context_policy/request_body/request_manifest/provider_usage_totals由原model owner提供；统计无凭证/隐藏项，缓存参数仅显式发送 | D64通过；真实cache收益/窗口容量仍未知，compaction=True与意外opaque响应均unsupported |
| IMP-CTX-06：独立QA与百章样本 | 新26运行例；原开发失败与修正保留，冻结QA新进程；同百章/原纲/模型条件两独立冷会话 | C67＋投影5、B24通过；B独立核对AB三问/正文/真实记忆与第三冷host作者续写，语义与实验覆盖限度单列 |

项目完成门原始日志：full-pytest.log **615 passed/1 deselected/90 warnings，271.61s，exit0**；retrieval.log **72/0，exit0**；validate.log **729/0，exit0**。独立证据在C-qa/final和B-qa/FINAL.md，均匹配frozen-input.json的194项；生产库指纹仍为`sha256:caa90952e848df7fd882805fd1253067fdbe957fe9a9657e860c566d0cacc641`。

百章真实宿主：同fixture/input哈希、Codex0.161/gpt-6.1-sol/max，before正文947字、1次save/1次成功remember、31次项目工具/35次含资源的宿主MCP操作、522.50s；after正文943字、1次save/1次成功remember、21次项目工具/26次宿主MCP操作、508.98s。remember实际分别调用3/4次、明确拒绝2/3次，不能把成功提交数当调用数。累计输入961687→1036776、缓存868608→960768、净新增93079→76008、输出12519→12818；没有由此宣称整体成本下降。两样本provider采样seed、逐请求峰值及宿主缓存调度不可观测；初始资源估算只作交付量。before脚本最初Windows路径过滤使源码hash列表为空，原记录保留，用source-binding-addendum.json核对114份实施前字节备份，属于回溯文件验证而非live模块捕获；after114份源码前后验证有效。

B独立读审两侧原第5/18/60/75/100章、公开调用、选中稿与记忆：青铜扣归属、校园广播旧闻与实际新告示、手册实际归还三问均相符；两篇先保留周瑾误信，再通过现场阅读/交谈改变认识，不提前利用World或揭晓秘密。两侧唯一成功批次更新原CharacterView/belief，保持真实保存DraftRef及本场景获知点，最后recall一致。after条目把陈宁当面说从对岸来进一步表述成周瑾目击，正文没有明确支持完整视觉路径；这一感知精度缺口保留，不能称所有角色信息均已认证。独立审阅者知道AB目录标签，不冒充盲化。

作者改稿实跑另列：克隆after工作区，实际HTTP保存作者第2版并显式feedback新run，以原outline和作者DraftRef进入第三个独立冷Codex。实际新后缀387字符，最终全文465字符，逐字保留78字符作者前缀；2次完整后缀save/回读、7次remember中6次明确拒绝，最终仅1条Experience成功，memory_revision 3→4。五次CharacterView写入均失败，不能将这轮的经历成功冒充角色新知持久化。旧稿读取拒绝、取消后原operation_id仅恢复原回执且不改父作者指针，父run实际为completed且cancel_requested=true；B独立机械20项全真，冻结194项与正式资料指纹保持。此试验取得AC16的明确新继续路径，未证明旧外部窗口被后台清除或模型忘掉旧内容；第三样本不混入AB成本表。

AC-CTX逐项与实际结果见[本轮RESULTS](D:/novel-project/output/context-runtime-20261010-bd48b011/RESULTS.md)、[summary.json](D:/novel-project/output/context-runtime-20261010-bd48b011/summary.json)及[B独立实际宿主复核](D:/novel-project/output/context-runtime-20261010-bd48b011/B-qa/AB-REVIEW.md)。AC07–17本地边界已验证，AC16/18实际实验保留上述覆盖限度；provider compaction仍unsupported，所有宿主的历史清除或“忘记秘密”、正式小说长篇覆盖和文学效果未认证。后续实证维护缺口为模型正确引用原状态ID/操作形状及精确标注感知依据，不放宽校验或自动改写正文；既有Hook同义召回、兜底理由与正式长篇v3覆盖保持原待办。本轮未改正式资料、全局配置、主预览或commit/push。

<a id="context-architecture-preparation"></a>
## 2026-10-10：整体context研究与架构准备（实施前记录，当前状态见上节）

本轮依用户明确design-review-council及“大范围搜索适合的context注入、取适合的改架构”，主agent研究与改既有合同，A外部设计、B反例、C协议/实现与Eval、D维护/兼容独立审查。22项已读一手论文/官方资料见[研究与方案比较](references/context-engineering-research-20261010.md)；权威设计已写入[架构§7.11](HYBRID_GRAPHRAG_ARCHITECTURE.md#context-architecture)，原§7.10首包/字符分页验收保持，不另建PRD或规划系统。

采用组合：稳定规则/schema、完整作者任务、明确focus的当前工作集、语义记录/必要依赖包导览、真实Ref补读、同业务run的安全provider attempt。原完整记忆/轨迹不删除，不默认额外摘要模型或工作笔记；资料/摘要不变成角色知识。缓存、语义概要、字符页与协议压缩分别处理；provider能力先单独验收，当前客户端尚不支持compaction/cache policy等新增字段。

**首要确认P1仍未修复：**native只在启动build_context，后续append全部continuation；B真实RunService+确定性transport在chat/responses复现作者改稿后memory_revision 1→2、当前旧条件已失效，但下一请求仍发旧稿/旧条件而无新稿。Store未覆盖作者新稿，问题是模型材料失效。C独立纯构造支持此缺口；前轮真实native请求逻辑JSON约22KB→127KB，不能当wire/峰值token。原始探针与轨迹已从临时目录保留在output/context-architecture-review-20261010-249febaf/independent-qa。

设计关键裁决：Responses活跃链不能只因call/result配对完整就删早期工具段；来源失效需要明确新attempt。D实测同run重用provider call_id会与原提交键冲突，因此协议ID保持、内部invocation_key绑定attempt，元数据挂原turn/receipt；harness原operation_id键不改。默认feedback→child被否决：其空request会丢原要求，branch/output_mode和引用也会变；保留作者显式续接。

中断恢复后的A独立通读确认文件无缺段，并补齐三个合同：持续focus/Q显式替换或清空，临时query/失败/冻结续页不改变选择；旧attempt交付与新窗口实际包含分开，长纲未保留范围仍需重读；§7.8旧run+call_id与§7.11规划invocation_key明确衔接。AC12/17同步增加对应反例，仍为待实施/验证。

| 实施优先级 | 尚待完成 |
|---|---|
| IMP-CTX-01 | 修请求前效力与作者版本检查、同run新attempt、原操作恢复和身份namespace；关闭P1 |
| IMP-CTX-02 | 原Memory owner提供焦点当前工作集/语义交付，修holder/target截断前优先；保留原包和旧字符cursor |
| IMP-CTX-03 | 明确技术窗口/输出预留/协议保护段，卸载冗余，16 turn硬码改显式可选策略 |
| IMP-CTX-04 | 同一编译结果进入harness/网页，host实际刷新/继续取证，不宣称后端清了外部历史 |
| IMP-CTX-05–06 | 可选provider能力、逐请求观测、固定100章实跑AB、非实现者复验 |

新AC-CTX-07–18已定义，状态均待实施/验证。本轮没有生产实现/模型调用、配置/正式小说/全局规则/主预览变更，未commit/push；22来源和设计只用于工程。字节基线、独立反例与最终源码/资料不变检查在本次输出目录。最近已验证运行基线仍是前轮**536 passed/1 deselected/90 warnings；72检索/0失败；729有效文档/0问题**，不以此声明新架构已实现。此前Hook同义召回、兜底理由与现有长篇v3覆盖保持独立待办。

<a id="context-delivery-implementation"></a>
## 2026-10-10：模型上下文交付已实施并验收

续接用户“下一步处理context”及“继续”的授权，沿code-quality-workflow实施、design-review-council的A/B/C/D独立检查，沿既有架构§7.10/AC-CTX-01–06。本次字节基线及原始失败、修复测试、协议探针保存在output/context-delivery-20261010-167797cd；没有新增规划体系、第二Store、分页cache或路由模型。正式作品、全局规则、模型配置、v2入口、既有未提交工作及主预览服务保持。

| 实际改动 | 归属与兼容 |
|---|---|
| 首包按任务交付 | context.py提供model/full两个视图；模型先取得原纲/要求、scope/游标、版本、覆盖及真实来源入口，不自动注入整份recall。短输入完整内联，长输入给长度/hash及完整读取参数；同一首包不重复引用或底稿文本。 |
| 原文与输入续读 | text_page/describe_text统一Unicode码点右开范围；read_document复用DocumentRef/AuthorInputRef/DraftRef及原前缀权限，偏好用固定context_slot。默认4096字符窗口可显式调整；源hash变化拒绝旧页，失效基线无读取入口。 |
| 完整recall分段交付 | 首次完整包保存在原tool_results；json_result_page只切冻结JSON的交付页。current_snapshot刷新原效力版本，source_refs_status复核原包各来源，包括prepare后新增查询源；续页不重新route或改变记忆选择。 |
| 调用方同源 | RunService负责执行/保存原回执/选择交付；builtin chat/responses、HTTP、stdio MCP和网页复用。MCP及网页选择model，HTTP/CLI完整导出默认full；CAS、原operation_id恢复和取消行为保持。 |

同一100章夹具，启动context资源曾为177219项目估算token，最终实跑为5045（10866字符），降低97.15%；另行公布的工具schema加算后为9679。原纲63字符与要求42字符逐字保留，底稿和原文按来源延后。这是资源序列化估算，不是provider每次请求、账单、整次调用成本或文学准确率；记忆容量仍默认None，完整原包与输入并未删减。

独立Q：C在实际HTTP/SSE上分别完成chat/responses各7请求/10工具，原文3页/recall4页精确重组；两个stdio协议共21个可解码回执，text/structuredContent同源，跨adapter重启和原写ID恢复通过。B/D发现的新增查询源失效续页及失效父稿读取入口已修复：B原四格反例及健康控制通过，D四项定向检查通过，原始观测/可复跑脚本已从临时目录保留在本次independent-qa/。上述是协议夹具和独立反例证据，不能替代真实LLM。

最终完成门已通过：**536 passed、1 deselected、90 warnings，201.04秒；retrieval_cases=72 failures=0；729有效文档、0问题**，日志及pytest-final.xml位于本次输出目录。新增13项context检查与真实浏览器合计14 passed。早期全量R1的旧网页tools字段断言失败保留于pytest.log；测试迁移后验证model实际来源读取及默认full原文，而非只删断言。52个新增/修改函数四项注释检查missing=[]；CLI源码与本次字节基线一致。

AC-CTX-06已完成：实际Codex0.161/gpt-6.1-sol/max冷会话486.64秒/exit0，原纲未另附聊天，仅从可解析公开资源取得；保存955字符正文和1批记忆，之后recall及稿件回读成功，最终run=completed、未取消/未正式采用。第100章4260字符原文两页精确读取，“归还手册”14567字符冻结recall三页精确重组；首宽查询只读8000/170531字符，随后主动改窄查询，其他4份来源只读指定1–5段，未将未读内容称为空。公开资源和五工具text/structured同源、未截断关键输入。源码/正式YAML指纹保持，原始公开事件、输入、稿件、前后run、回执及检查在live-session/；机器汇总summary.json、报告RESULTS.md。

实际remember前三次明确拒绝：缺entry_id、entry形状错误、试图把原belief身份改为knowledge；版本始终0，第四次更新原稳定ID并推进到1。失败记录保留，不笼统称无错，也不重发未知结果。C独立只读核对公开资源三层JSON、原来源/原冻结包、save/remember/后recall及最终run，15条断言全真；原始脚本/观测保留于independent-qa/C-real-host-review，9核心hash与执行记录一致，三问及新belief的现场观察依据无明显来源错误。没有将文学质量或角色全部信息认证为通过。

真实累计input_tokens=942023，其中cached_input_tokens=866560，output_tokens=11438；约8分钟仍有多轮查询与输入修正成本。资源首包减小不证明总成本降低，provider每次请求峰值与长期工具历史增长尚未验证。状态/记忆工具输入的可用性可沿同一工具schema另作后续改进，不能据此绕过身份校验。

已有长篇召回缺陷保持单独待办：holder焦点排序、同义改写早期Hook遗漏与兜底“直接匹配”理由未在本轮改动；79万字作品仍需建立v3记忆覆盖。本轮解决上下文交付，不宣称长篇角色知情、文学效果或全部宿主已经通过。

<a id="long-memory-evaluation"></a>
## 2026-10-10：长篇记忆实测完成，召回与上下文仍有缺口

本轮仅测试当前源码，沿code-quality-workflow及既有council的C独立只读QA；没有改生产实现、正式小说、模型配置或全局规则。完整脚本、实际回执与报告在[long-memory-eval-20261010-23cb8600](../output/long-memory-eval-20261010-23cb8600/RESULTS.md)，机器结果为summary.json，C回传保存于independent-qa.md。

100章人工正文/人工记忆经过实际prepare/save_draft/remember/adopt，423869字符、422项批内操作/身份声明；9项主检查7通过、2失败，另1项明确ID诊断通过，合计8/10，不是一般准确率。已确认：角色holder焦点的belief虽有效但排在64候选之外；同义改写无词项命中时漏早期Hook；兜底入口仍错误标为“直接匹配”。第100章recall单次2.2131秒，相比第1章0.0578秒增长。数据保存、来源次序/分支截止点、旧误信不自动随World纠正、同名身份、履行解除与私密知识不自动传播的指定检查通过。

实际79万字符作品只读检查：513份History、792680字符，无v3记忆批次容器。三次早中晚原文锚点定位均命中，但返回89–154引用，项目估算114754–198144 token，v3覆盖unavailable；不能据此宣称该长篇的角色认知/伏笔记忆已建立。正式YAML指纹保持一致。

真实Codex0.161/gpt-6.1-sol max首轮601秒触发实验宿主600秒deadline，950字符已保存、0记忆批次、无最终答案，原失败保留。两轮资源实报截断导致大纲缺失，HTTP原JSON完整，不能称数据损坏。核实唯一save提交后，新host意图仅源采用第101章；第二冷会话把原outline/request另附聊天作为控制变量，无历史oracle，485.64秒完成666字符、1批remember及实际采用。三问符合来源；原belief ID正确Set为依据告示/亲见判断通行，保留验收细节未知；宽查询仍遗漏，窄“返程”查询补回。新Store明确ID的9项回读/来源/游标检查通过，不替代自然问法验证。正文用记者陈宁承担“另一位同学”位置，缺少兼学生依据，角色一致性不能认证通过。不能把此控制实验写成原两轮完整通过或100章LLM自动维护成功。

待修复顺序：先减小/去重上下文并保证原纲与要求可交付，再提升人物holder/target焦点在截断前的优先级，随后修无命中回退与错误理由；现有长篇的v3记忆覆盖另需建立。没有恢复文学audit/固定报表/自动知识传播，也未新增路由模型或第二Store。测试后21项生产核心/测试文件与既有523/72/729完成门SHA一致；本轮不重复该门，不宣称所有长篇语义通过。最终隔离测试库为102章、425485字符。

<a id="memory-reliability-implementation"></a>
## 2026-10-10：记忆可靠性六包已实施并验收

用户授权执行架构§7.9/IMP-MEM01–06，主agent实施全部源码与回归，沿code-quality-workflow；design-review-council的A/B/C/D原评审结论及C/D/B实施后只读复验作为独立Q。初始23份文件字节快照、受影响Web夹具修改前的补存快照及manifest位于output/memory-reliability-20261010/before、baseline.json。保留原始作品、模型配置、全部既有未提交工作、v2入口与同期写作体验成果。没有另建PRD、事实数据库、路由模型、传播器、事务框架或文学审核。

| 实际工作包 | 实现状态与owner |
|---|---|
| IMP-MEM-01 | schema共同校验整批输入/StoredBatch/状态/记录/分型Ref/位置、内外ID及host字段；config与Store journal委托。严格类型先于解析，坏YAML/坐标/键转字段错误。MemoryService共同来源资格覆盖新写入和正式reader的Experience、动态状态、场景边界及未定身份；Canon仅补充发生记录。 |
| IMP-MEM-02 | SourceCorpus.at_cursor复用同次源字节/解析/hash；prepare和MemoryService共用。read_snapshot固定来源/父链/批次，recall、normalize与publication_candidates用相同真实前缀/正式坐标/批序回放。未来先排除，迟到早检查点不覆盖晚状态，未来创建的ID不可引用。 |
| IMP-MEM-03 | prepared intent先冻结候选与原指纹，Store在source-versions保护原/映射批次；adoption journal持publication binding、实际投影Ref及控制目标。恢复只用原冻结集合，逻辑键支持搬迁；删除/损坏/author_note或投影缺批次仅产生失效控制/原文入口，不注入保护值。合法多发布先核绑定再去重；同ID不同原内容返回冲突并退出有效投影。 |
| IMP-MEM-04 | 效力签名覆盖实际来源、发布绑定/完整性、父前缀，仍用同一memory_revision。remember在源锁→Store锁内复核并整批提交；ToolDispatcher与RunService实际外层锁同步调整，取消/终态和幂等恢复保持。旧recall写签名前原子复核版本/稿源，过期只对内部读取冲突有界重读；旧快照不能覆盖并发新提交。 |
| IMP-MEM-05 | graph保留不可遍历的required_context义务，容器/边/前提失效不能让结果独立入选；router先处理直接焦点/Hook/Pending再作64节点展开，候选/跳数/依赖/查询未选各有缺口。状态结束只提供解除来源，不恢复旧值；未记录后缀/未知scene不假装覆盖。默认无token容量，显式容量仍整包校验。 |
| IMP-MEM-06 | 同remember可选unresolved_entities(local_ref/name/entity_type)，host分配稳定ID并支持同批holder/target及Link引用。同名分开、重试不重新分配、采用/重启保持；正式实体/别名仍原owner，旧字符串/无information条目兼容，无群体或World自动传播。 |

可运行增量在tests/test_memory_reliability.py，真实Clear/迟到采用反例补入test_adoption_v3.py；受来源合同影响的test_web_edits_v3.py仅把动态状态夹具改为实际History观察来源，保留全部摘要双CAS、作者归属、字节保护、原批次与编辑后失效断言。

| AC-MEM关键路径 | 实际证据与边界 |
|---|---|
| 01 容器失效不复活 | 实际章1 Set/章2 Clear采用后delete/corrupt/author_note：live、重启服务、生产prepare新run和清理原run后保持unknown/invalidated；before游标仍读旧值。实际retire采用后删除容器、清理run也不复活。 |
| 02 发布身份/完整性 | 同raw batch两operation_id实际采用同坐标两revision/hash，反转journal扫描仍选择有效绑定；新保护证据下同ID异payload转冲突，版本只升一次。投影hash/集合不符沿冻结控制失效，不任选映射副本。 |
| 03 故事回放 | r1借出→r2归还→迟到r1补记，草稿/正式采用/新run保持r2，recorded_through不退；既有Clear、scene、正式同位置修正/来源顺序、父前缀与before/after测试回归。新增未来同ID记录来源损坏不能撤销过去；晚身份ID引用于早cp被拒。 |
| 04 效力CAS | 原源失效直接旧CAS拒绝、复读不反复升；C真实harness父纯追加/改写后子run旧CAS与稳定revision probe通过。换query/focus与反转扫描不改变输入版本。 |
| 05 故障/恢复 | 原采用测试覆盖prepared/正文replace/回执/输入保护/summary替换窗口及A后B再重试A；C补冻结后新增live候选仍恢复原集合。实际搬迁library+Store并使旧路径不存在，原ID恢复原冻结投影。真实TCP提交后IncompleteRead：仅一次POST、effects_known=false、终态显式原ID恢复同回执，批次/版本不重复。 |
| 06 必要依赖/结束来源 | 真分章采用后删除必要Link容器，结果仍在正文但不独立入包，有必要关系缺口；既有目标缺失/隐藏桥/future诱导图测试回归。真实Experience引用随后Clear的state：有结束原文来源，无旧当前值。 |
| 07 候选/容量 | 65普通seed竞争，直接旧物Hook/Pending先进入64候选；节点/依赖上限有缺口，长文本完整。既有大于12000完整包、完整原文检索和2048显式容量回归；B复验容量退包后未选数量随最终集合更新。 |
| 08 覆盖/未选 | 实际保存未记录后缀、仅作者计划、未知scene，覆盖位置保持且carry仍有效；查询未选只报数量，原记录可换focus回读。unknown/失效与未选保持不同形状。 |
| 09 共同结构/来源 | 真实工具坏项混批整批拒绝；真实容器缺scope/位置、混键、.inf、list kind/ID等转gap，禁止源伪造内部visibility/quarantine标记。journal三Ref字段限本scope DocumentRef，D17项边界通过；保护逻辑Ref坏类型/越域/越根拒绝。正式Canon-only四种动态容器退出有效事实，来源映射不递归改自由payload。 |
| 10 信息与身份 | 已有18信息/真实chat-responses-harness装配路径回归；新增学校/媒体失实转述+World真相+两同名声明，同批/重试/采用/before-after/新Store均保持四字段、各自holder和ID，无自动知情或纠正误信。 |
| 11 并发/提交一致性 | Event/barrier在实际旧recall与新remember间控制并发；在规范化和提交复核间由外部线程改源，混合批次拒绝且锁可再用。C再次验证取消窗口、原ID/改参、父前缀、冻结恢复；回执只表示原提交事实。 |

失败与修复证据保留：Clear/迟到初始3失败/1通过→同四例通过；C旧recall反例曾使revision 2→3→4，修后旧reader返回late且packet/磁盘/fresh均为2；D四类坏结构/资格及后续wrong-kind journal遗漏均闭合，17/17通过；B最终边界7 passed/1.67s；D最后来源资格/Web夹具5 passed/1.82s，未弱化断言。源码hash及原始C/D探针在independent-c/independent-d，未保留独立日志的B/D最后观察明确记在independent-review.json，不冒充原始测试文件。

阶段全套517/520通过只属中间证据。最终来源资格扩展后第一次全套522 passed/1 failed，失败为旧Web夹具的Canon动态状态；修夹具并独立复验后，当前共享源码最终完成门为：**pytest 523 passed、1 deselected、90条既有兼容警告，210.33秒；retrieval_cases=72 failures=0；729有效文档、0问题**。原始log/XML及validation.json在output/memory-reliability-20261010。最终pytest前后21份受测Python文件SHA一致；新/修改函数四项注释已核验。既有工程边界文档四处旧尾空白保留，本轮新增行无尾空白；config新增EOF空行已清，AST不变，最终门在清理后重跑。

兼容/残余边界：缺失旧保护证据只能报告unknown/partial与原文入口，不从内容或当前状态倒造历史。来源/场景/信息是否符合正文、实际LLM持续遵守POV及长篇文学效果仍需真实输出与作者阅读；这轮没有调用模型或修改正式小说。现有预览后端未重启，重新启动后加载新源码；未提交/push。既有来源和工作区仍同原owner，后续维护先用新反例证明缺口，再沿该owner增量修复。cycle_status仍SESSION_UNBOUND，没有声称取得插件运行保障。

<a id="writing-experience-status"></a>
## 2026-10-10：续接三项写作体验（已落盘，候选与共享整合分开验收）

来源：[架构§17](HYBRID_GRAPHRAG_ARCHITECTURE.md#writing-experience)，AC-UI-W01–08。原聊天最后确认防丢稿、首次设置/新建作品、写作页重排，本轮要求总结并继续；前三项此前尚未交付设计或实现。本轮沿原主控补设计并实施，保留v3/Metro/信息迷雾、v2兼容、正式资料和全部未提交成果，不提交/push或调用收费模型。同期记忆可靠性文档准备保留，后端修复不搭车实施。

实际入口/owner：workspace.js仍唯一管理业务API/CAS/SSE及浏览器作者副本；bootstrap使用已有fingerprint_bytes返回不含路径/凭证的workspace_id。副本按工作区/书线/run/每document nonce隔离，旧session身份只用于恢复，opener复制也不共写；旧任务/未开任务输入可从“本机保存的输入副本”回读复制，不静默淘汰。服务器DraftStore和正式来源仍权威，恢复不自动提交。正文绑定原baseline_revision，dirty期间轮询/实时事件不换基线；新服务稿与旧本机稿冲突时先显示候选。保存返回实际saved_draft_ref，迟到响应不丢后来输入。创建/反馈/采用保留原路径/参数/编号；新作品创建意图也按写者分离，刷新仅显式确认。

切书/换run先临时保存，失败保留当前编辑并阻止清空；切书只关旧观察，不取消后端。设置提供现有本机配置指引/显式脱敏重读或零配置harness，不接收密钥/执行shell/探测模型。scaffold是CLI/TUI/网页共用建树owner，复用read_yaml_mapping/FileMutationLock/atomic_write_bytes，注册最后提交；exist_ok匹配原标题/书线/继承意图，普通失败只清本次未注册树，提交后异常与崩溃残留保留。库锁争用明确失败后可重试，不丢注册。网页新书不继承旧文学审计模块，CLI/TUI默认不变。大纲优先，低频设置折叠，正文保存动作移到编辑器前，保留所有原业务ID/Metro持久DOM。

四位独立设计审查者A/B/C/D已交付，采纳原CAS/归属/每页nonce/完整envelope/scaffold原owner安全化；不增加Store/框架/API client/模型检查/文学规则。主agent负责实现和原状态文档，writing_ux_design只维护原browser调用方，writing_ux_implementation_review只新增建书回归。插件cycle_status实际unbound/configured=false，本轮纯指令模式，未取得运行时保障。

当前Q分版本记录：基线6 passed；首版增量29 passed、24.01秒，首版三门490 passed/1 deselected/90 warnings、195.24秒，72/0、729/0（input-manifest-initial.json）。最终写作候选R2三门为**493 passed、1 deselected、90 warnings，172.87秒；retrieval_cases=72 failures=0；729有效文档、0问题**，原始pytest-writing-r2.txt/XML、retrieval-writing-r2.txt、validate-writing-r2.txt在output/writing-experience-20261010。input-manifest-r2.json的15项在候选绑定通过；最终共享采样14/15同字节，唯一AGENTS.md漂移是同期memory公共API登记/shape行扩充，独立diff确认不修改本轮UI/测试/R1，见frozen-recheck-r2/current-agents-drift.txt。frozen-writing-manifest-r2.json绑定实际候选目录，1824项输入字节未变，另1项output/playwright/v3-workspace.png为测试重新生成截图，其变化完整保留在final-input-check.json。独立writing_experience_independent_qa实际复验9 passed/1 deselected（非阻断模板旁证），另补完全禁用local+session Storage 1 passed、新作品已提交丢回执后刷新/原意图显式重试1 passed；三处初验缺陷均闭合，冻结写作候选PASS。它核对了原始三门、实际novel_rag/tests导入路径及前后hash，不把root转述或共享记忆版本当验收。完整报告为independent-qa/QA.md。

独立初验FAIL及修复：父目录换链后的失败清理删库外同名树、弹窗Esc被Metro劫持、无profile首屏按钮不可完整看到。修复为物理目录身份/库内归属复核、modal键盘保护、输入面板紧凑布局；新增父链/同库leaf替身及两弹窗焦点回归。首轮布局只核innerHeight，独立复验又发现祖先滚动区裁掉约13px；已补逐层真实裁切交集断言并调整大纲/要求的局部行距，单项1 passed/3.64秒。旧9通过与随后裁切失败均保存在independent-qa/recheck，不把不足的断言视为最终验收。

权限拒绝的传输旁证：修复组合31 passed/1 failed、26.69秒，唯一失败WinError10054，单项重跑1 passed；root 200次拒绝POST有198次403/2次断连。独立600请求对照：默认HTTPConnection完整read后close=200/200真实403；urllib强制close有5次重置，同HTTPConnection加Connection:close有4次，均无注册/建树。专项helper改为前者，真实403/无写/网络错直接失败不变，不重试。仅支持短连接关闭时序解释（未抓包，机制属推断），生产权限处理不扩大，短连接兼容问题不称已修复；报告为independent-qa/HTTP-DIAGNOSIS.md。

共享整合边界：同期记忆代码在全树检查期间有4文件漂移；pytest-repaired为**496 passed、1 failed、1 deselected、90 warnings，197.06秒**，失败tests/test_memory_state.py::test_invalid_link_and_author_input_fact_reject_whole_batch为旧错误文案断言（实际仍拒绝已发生事实的非法来源）。未修改/删除该断言，结果和漂移均保留，不能据此称共享全树完成。仅在新冻结副本恢复并行记忆实施前经hash核对的19个Python源码/旧测试，以隔离本轮写作增量；共享源码从未恢复或覆盖。R2三门证明该候选，后续记忆合并版本需由其实施流程再跑三门和独立QA。

失败历史保留：原browser组合1 failed/9 passed，实时事件漏同步基线修正后harness1 passed；新browser4 passed/1 failed，开始按钮超出768px，布局修正后5 passed；后端22 passed/1 failed为测试正则遗漏合法sha256前缀；新browser组合14 passed/2 failed是瞬时运行状态被正常轮询覆盖的断言和采用YAML元数据位置误读，改为真实409/持久错误提示及实际metadata后增量29 passed。全部原始失败记录/基线副本保留，不把测试错当生产缺陷或删除历史。

恢复点：候选R2三门与独立QA通过，正文/大纲恢复、真实CAS/迟到回执、原envelope重试、书库隔离、无配置新书、目录归属清理、实际首屏裁切和modal焦点已取证；源码/永久测试/架构§17不再改。同期另一聊天正在实施§7.9记忆可靠性，共同Store/MemoryService等已变化；保留其成果，共享整合完成门未关闭，不据本轮QA宣告该包或全项目完成。8765主预览还是旧后端进程（bootstrap无workspace_id、实际run数0）；重载该已确认进程和启动新版的操作被自动审批拒绝，返回“blocked by policy”，未给细化原因，命令未执行。需用户在原终端重启工作区后使用新版，不能绕过策略终止旧进程或宣称主预览已升级。浏览器副本不承诺跨端口/浏览器恢复；偏好/资料未保存编辑沿原内存缓存和离开提示，不宣称刷新持久化。

剩余任务：记忆可靠性§7.9/IMP-MEM-01–06在另一聊天实施中，以本文件顶部最新记录为准，不能继续称后端未实现；资料搜索/连续写作导航/采用结果反馈；内置真实provider、其他harness/新协议、长篇记忆及文学效果；历史Windows多进程锁项仍按既有完成门排除。本增量不关闭这些边界。

<a id="memory-reliability-status"></a>
## 2026-10-10：记忆架构可靠性更新准备

用户显式调用design-review-council准备更新记忆架构。本轮完成权威[架构§7.9](HYBRID_GRAPHRAG_ARCHITECTURE.md#memory-reliability)、[四角色裁决§14.4](HYBRID_GRAPHRAG_ARCHITECTURE.md#memory-reliability-review)及原[增量工作包](ENGINEERING_REFACTORING_BOUNDARIES.md#memory-reliability-plan)的准备；未实施后端修复。沿现有文档链与Store、source-versions、采用journal，不建立另一份PRD、事实库或文学审核系统。

已做到：信息迷雾及学校/报刊/电视广播等开放渠道继续采用；原始记忆批次、发布绑定、派生视图区分；采用候选冻结与故障恢复顺序、同batch多发布、共同故事回放、完整效力revision、必要依赖/候选上限、覆盖、存储形状与搬迁合同落入同一架构。11组AC-MEM及IMP-MEM-01–06明确owner/依赖；未来公共API和未定实体输入扩展尚未落盘，不提前登记为实现。

尚未做到：Clear摘要丢失后的控制恢复、迟到早检查点正确回放、继承来源变化的CAS拒绝、失效必要Link缺口、直接Hook/Pending候选优先，以及完整StoredBatch校验仍需代码实施和实际回归。旧无保护证据的缺失容器只能保守unknown/partial，不能承诺逐key还原；真实模型长期记忆、POV/传闻判断及文学效果仍未验收。

本轮使用真实subagent独立A架构/B反例/C实现与验收/D维护四岗；D在并发槽位空出后执行，B/C定向复核、D核最终职责与迁移边界，指定反例在合同层已闭合。不是四人投票或runtime cycle认证，cycle_status仍SESSION_UNBOUND。主agent裁决及处置见架构§14.4。

| 证据 | 实际观察及边界 |
|---|---|
| B真实prepare/save_draft/remember/adopt/recall | Set→Clear采用后删除/损坏summary，旧伤势复活；新run bound、gaps=[]、invalidated_keys=[]、revision=0。r1受伤→r2治愈→迟到r1补记，草稿及正式新run都退回伤势。父前缀改写状态失效但revision1→1，旧CAS接受。临时目录与stdin脚本未保留，整理报告不冒充原始日志 |
| C独立实际路径 | 现有典型采用回读fixture全部断言通过；失败路径同样Set→Clear并删容器，live/restart/new run均复活，只有live的revision0→1不足以修复。原始观察保存在output/memory-architecture-review-20261010/c-evidence.json；31文件的隔离库/Store及被删Clear原容器打包为c-fixture-snapshot.zip |
| B/D发布版本，D结构探针 | 同run同draft两operation_id产生同batch_id、不同正式revision/hash；原run批次不因发布映射改写。D在实际已发布metadata删inner entry_id，state/config校验均放行。均属实际隔离库观察，未修改正式作品 |
| 定向设计复核 | B确认指定反例合同有处置；C指出提交前/后故障、同位置修正及外层Store锁责任，已补入合同与工作包。并发barrier、输入扩展与新后端路径尚未执行 |

冻结失败夹具仅保留当时输入/输出和版本；不是可直接重放的独立脚本，其旧journal还含原临时绝对路径。复现可沿tests/test_adoption_v3.py的_environment/_new_run/_remember_state/_adopt及tests/test_harness_v3.py::_service重建；不要解包后自动执行采用或写回旧绝对位置。证据hash/检查记录见output/memory-architecture-review-20261010。

本轮仅修改三份既有文档、保留隔离反例证据并检查文档引用/ID；不重复运行未变的业务三完成门。最近一次有效基线仍为output/information-channels-20261010的**461 passed、1 deselected、90 warnings；72检索用例/0失败；729有效文档/0问题**，不能据此宣告AC-MEM通过。未调用真实模型、改写正式作品、提交或push。

下一步先实施IMP-MEM-01共同结构/来源资格与IMP-MEM-02共同故事回放，再交付03冻结发布保护和04效力/CAS，最后05依赖/覆盖/选择；06未定人物身份兼容增量另按同remember输入合同推进。各包以可区分前后反例、实际临时库和既有门禁取证，最终由非实现者复核；来源缺口不阻止继续创作或作者采用。

## 2026-10-10：学校与公共媒体渠道补充

用户认可信息迷雾，并明确渠道不能局限于玄鉴的局部例子；补充原句保存在docs/references/information-fog-channels.addendum.txt。沿现有开放information.channel扩展工具说明、常驻prompt和按需information_transmission参考，覆盖学校课堂/教材/教师讲解/校内通知/校园广播，报刊、电视新闻、广播节目，电话/短信/邮件/网络平台，以及单位/军队/社团授权资料。未新增字段、封闭枚举、传播模型或自动赋予人物知识。

合同区分发布/播出/上课与实际学习/阅读/收听/观看/接收；教育与职业经历支持合理基础知识，但不授予全学科、档案或隐私。basis仍按需记录覆盖范围、刊期/节目时点、信号/设备、语言和权限；媒体报道不认证World真值，转载/转播同源不算独立印证。玄鉴证据原文件/hash保持，通用适配另标用户原协议与补充的asset/hash，避免当作原作设定。

本增量仅调整说明、Prompt与来源记录，沿用既有18项信息路径及真实chat/responses/harness装配测试，不新增仅重复关键词的用例。三完成门复验：**pytest 461 passed、1 deselected、90 warnings，179.86秒；retrieval_cases=72 failures=0；729有效文档、0问题**，原始输出/XML位于output/information-channels-20261010。三份参考来源hash一致、函数四项注释missing=[]、资源仍9项。未调用真实模型或修改正式作品；真实文学效果与前轮可靠性待办保持未验收。

## 2026-10-10：信息迷雾与《玄鉴仙族》传递参考

用户确认前轮方向，并指定用其简单信息迷雾协议及《玄鉴仙族》小说中的知情/传递方式修改信息记忆部分。原始协议保存于docs/references/information-fog.source.txt；正版公开试读/检索片段与推断边界见xuanjian-information-notes.md。未读取VIP全文，不把原作剧情、术法速度或未经核实情报分级加入本书设定。

实际实现：memory/schema增加state_entry_schema/validate_state_entry，remember声明、MemoryService提交及config正式容器读取共用；CharacterView新增可选information(channel/source/certainty/basis)。value仍是实际所得/判断，host narrative_position仍是获知检查点，source_refs仍是真实文件证据；世界内source为文字或null，禁止嵌套Ref/自造时点。旧无字段条目保持缺失，无新人物Store或知识副本。同步修复list holder/非字符串kind/target先污染批次再令router崩溃的问题，坏信息同批全部拒绝。

generation/context常驻信息迷雾短协议，native与harness通过同一build_context消费：公开概要按地区圈层，群体成员不自动知情，发出/送达/阅读/理解分开，转述只含实际透露部分，未知来源不得全知定位，旧消息/化名对应须依据，World不自动纠正误信；作者可指定全知旁白但不授予角色知识。集合仅供内部判断，无固定文学报表或周期检查。resources在原八段R13之外增information_transmission按需参考，独立记录源asset/hash与五个正版URL，未伪造R13提供片段身份。

三位独立reviewer分别核原文局部证据、反例/结构责任，以及实现/Eval与维护（合并为同一岗）；主agent裁决并实现。采纳可选四字段与同源校验，世界内来源用文字/null避免adopt的kind=draft泛化碰撞；没有为人物获知另建时钟或自动传播器。独立QA另发现外层learned_at绕过Schema并被泛化映射，已修为模型输入/落盘host字段两种白名单。真实保存链为remember→recall→采用summary→新Store/new run；视角、收到范围和权限是否符合正文仍是LLM语义责任，字段存在不认证判断正确。

验证完成：既有状态/服务/工具/采用/容器窄集59 passed；初版16项信息回归及相关资源/无预算/工具集30 passed；独立初验16 passed/8.15秒发现外层未知字段，新增2项并修复后独立复验 **18 passed/10.62秒**，原探针整批拒绝、旧host字段与合法来源标签保持。三完成门为 **pytest 461 passed、1 deselected、90 warnings，149.38秒；retrieval_cases=72 failures=0；729有效文档、0问题**。全套原始输出/XML在output/information-memory-20261010/pytest-final.txt及pytest-final.xml。函数四项注释检查missing=[]、新解释器config/schema/resources导入通过、9资源各自来源验证通过。覆盖未知来源、legacy缺失、坏结构整批拒绝、无群体/World自动传播、正式before/after、较早父检查点排后获知、harness实际context与chat/responses两轮本地HTTP按需参考。无真实模型调用、正式作品修改或提交/push。

边界：本增量落实人物信息合同与装配/保存，不宣称前轮Clear容器丢失复活、草稿迟到记录顺序、父来源revision或required_context失效缺口已解决；它们仍是下一批可靠性加固。实际模型能否持续遵守信息纪律、长篇改稿和文学效果尚未验收。

## 2026-10-10：磁贴图片轮换扩展（15张，已实现）

用户要求增加十几张现成作品，优先EEJU村正，也接受其他型月及假面骑士。复用既有Metro配置、manifest、轮换timer与本地资源打包：保留原3张，增加12张，总计5张EEJU村正、5张其他型月、3张假面骑士、春日和夏景各1张。四个图片磁贴各4张、每45秒渐变切换，其中EEJU夏日村正在两组出现；完整周期覆盖15张。图片原文件落盘，保留画师、原帖、公开发现页、尺寸及SHA，不自行生成图片；公开可访问不代表再分发许可证，未核实独立授权。带明确禁止转载水印的候选未进入生产manifest或wheel。

launcher仅扩展既有validateAssets/renderTile，允许manifest以imagePosition提供整数百分比裁切焦点，无效时沿用磁贴位置；不改业务Store/API/模型或新增依赖。新增真实浏览器用例test_metro_public_art_pools_rotate_and_obey_motion_preferences，用Playwright Clock.run_for逐次触发timer，核验全部15张可见、逐图焦点、设置暂停/恢复及系统减少动态时暂停切图且时钟继续。素材处理复用原子写组件，网页/安装包验收复用此前脚本的可选目标目录。

| 本轮验证 | 结果与原始证据 |
|---|---|
| 全套pytest完成门 | **443 passed、1 deselected、90条既有兼容警告，138.50秒**。`output/metro-art-rotation-20261010/pytest-final.txt`及`pytest-final.xml`；最终裁切位置调整后新增浏览器用例再验通过，1 passed/6.15秒 |
| 检索/源校验完成门 | **retrieval_cases=72 failures=0；729有效文档、0问题**。同目录`retrieval-final.txt`、`validate-final.txt` |
| 实际浏览器/图片 | 1920×1080、1366×768、390×844：13磁贴、16图片节点、图片失败0、pageerror=0、横向溢出0；四组轮换实际覆盖15张。`visual-evidence.json`、`rotation-evidence.json`、`home-*.png`及`rotation-0.png`至`rotation-3.png` |
| 实际安装包 | 独立任务目录构建wheel并安装；import来自wheel-installed，21个静态资源实际HTTP200、与当前源码字节一致，15张JPEG的SHA一致。`wheel-evidence.json`及`verify_packaged_art.py` |

wheel SHA256：`7dd8e219c4386ede5178f83767383459337628c53bc4e8c3b617e6f856ee43ce`。直接在共享根目录构建曾遭遇egg-info写入错误，随后以任务内源码副本独立构建通过；不覆盖同期元数据。本轮是既有设计上的素材/配置增量，无新独立子agent QA，前阶段独立报告和冻结快照保留为历史证据。主预览仍为http://127.0.0.1:8765/；未提交/push、未调用真实模型或改写正式小说。后续可直接修改tiles.json的图片池与manifest的焦点/出处。

## 2026-10-10：取消默认记忆token预算与架构反例复核

用户明确取消记忆预算上限，并询问当前架构优化。本轮只实施默认token预算取消及必要装配同步；其余可靠性/人物认知建议尚未实施。权威合同更新于架构§6/7/7.7，原v2检索兼容链保持。

已落盘：memory/router和MemoryService.recall默认available_tokens=None，无容量时完整相关包去重合并，不计算收益/成本；SourceCorpus.search支持limit=None，v3原文补读不再默认截8条，已入包来源保留原文入口。generation/context默认context_tokens=None，保留memory、原始作者输入及同快照明确基线，复用相关原文/实体ID，不再遍历全书注入全文。内置RunService删除每turn12000守卫。显式整数容量保留兼容，但按完整MemoryPacket核验；明确上下文装不下返回context_limit而非静默漏memory。claims装配同步修复领域筛选。

验证：相关窄集49 passed；补齐entity_refs后独立QA新增7项7 passed，并实测before/after、revise及异书隔离。三门最新结果为pytest **442 passed、1 deselected、90 warnings，131.86秒**；retrieval_cases=72 failures=0；729有效文档、0问题。此前全套440 passed/1 failed时同一workspace browser用例失败；单项复跑1 passed/7.83秒，随后完整门通过。工作区同期有其他UI更新，不把失败归因给预算或宣称不稳定因素已根治。新增覆盖大于12000的完整经历+必要前因、1000字claim完整计费、10份同scope原文命中、20000字CLI原纲、显式容量失败保留输入、chat/responses两轮实际本地HTTP请求不注入十章无关正文。全部使用临时库/受控endpoint，无真实模型调用或正式作品写入；未提交/push。

四角色复用当前源码/反例给出的下一批建议：共享输入/落盘形状合同、投影与发布统一故事位置回放、继承来源效力签名推进同一revision，以及已发布原始批次/投影版本在summary缺失后仍可追溯。沿原DraftStore/采用journal/source-versions保留证据，不另建事实库；历史差分仅恢复失效目标，不能当有效事实注入。CharacterView继续分knowledge/belief/claim/unknown，新人物临时身份需同remember内host分配；获知位置、未记/未选/失效必须区分。以上仅为设计建议，未扩展数据schema或自动传播认知。

已知仍未修复：Clear容器丢失使旧Set复活、失效required_context Link消失后结果独立入选、迟到早检查点覆盖晚状态、无正文Canon作为经历来源、父前缀改写revision不升、64普通seed挤掉直接Pending/Hook、未知场景/未记录后缀缺口，以及结构坏类型与Clear解除来源回读。既有记忆来源只带原文入口时仍需read_document补读。下一动作是按用户选择沿现有owner实施架构加固，保持上述反例为可区分前后的验收。

<a id="v3-status"></a>
<a id="metro-status"></a>
## 2026-10-10：Metro Mosaic网页重构（已实现，R1前端验收）

来源：[架构§16](HYBRID_GRAPHRAG_ARCHITECTURE.md#16-metro-mosaic-网页前端2026-10-10r1)，AC-UI-M01–08。用户已授权整个前端实施，纠正素材需公开Pixiv/X现成作品；旧4版只是历史比较稿，正式网页切为Metro。基线output/metro-mosaic-20261010/baseline保留此前未提交源码。

独立A/B/C/D源码评审已交付，裁决见§16.3。实现owner：root负责HTML/launcher配置/业务展示桥接/打包和原主控，metro_styles负责CSS，metro_browser_tests负责两组旧browser调用方与新增Metro验收；实现均已交付。另由全新上下文metro_independent_qa独立执行验收。现有业务Store/API/MCP/文学规则不重建。

实际落盘：13独立可配置磁贴、持久写作/资料/记忆/活动/设置/关于面板、hash和返回焦点、实时时钟与缓慢轮图、配置/图片降级入口。保留原63个业务ID，当前85个唯一ID，切页不重建表单、不另开模型/API/订阅，不丢当前页面的未保存输入。插件/终端和未知动作明确占位。旧事参考卡只展示后端已过滤的MemoryPacket。

图片使用佐伯俊的春日、Namonashi的士郎/Saber及wingheart《終点/猫駅》现成作品，manifest记录原帖、画师、公开资源、尺寸及SHA；页面可打开出处。第三图由官方Pixivision明确关联到Pixiv原帖，自行生成图及未核实原帖的旧图均排除生产资源和wheel。未核实商业/再分发授权，不将公开访问声称为许可证。

| 当前验证 | 结果与原始证据 |
|---|---|
| 全套pytest完成门 | **442 passed、1 deselected、90条既有兼容警告，161.91秒**；排除表达式仍按AGENTS。`output/metro-mosaic-20261010/pytest-final.txt`及`pytest-final.xml` |
| 检索/源校验完成门 | **retrieval_cases=72 failures=0；729有效文档、0问题**。同目录`retrieval-final.txt`、`validate-final.txt` |
| 独立实际浏览器 | 1920/1366桌面、390/320手机和短高视口、13入口/键盘/配置故障、真实临时库builtin/harness保存/采用/partial/迟到稿/CAS/反馈；当前后端68条业务观察及182条控件可达记录通过，pageerror=0、开放发现=0。三完成门原始输出/XML由独立QA再核验。独立证据与报告在`independent-qa/` |
| 响应式修复 | 1000px及以下重排，1001px起使用桌面；手机横屏844×390、平板768×1024、900×700及999/1000/1001边界的文字均处于对应磁贴内，未用剪字隐藏溢出 |
| 实际安装包 | wheel安装进独立临时目录，import来自installed；9静态HTTP资源200/SHA一致，7个受影响后端源文件亦与当前源码一致；只含3张预期JPEG，无旧图/生成图 |
| 函数/结构/格式 | 135个所检具名函数均有依赖/输入/输出/实现说明，JS语法通过，旧ID/唯一ID/UTF8检查通过；本轮文件按CRLF合法规则的diff检查通过。`contract-evidence.json` |

真实反例已处置并复验：慢bootstrap覆盖先选driver、新run继承旧坐标、恢复时漏原纲/要求、History修改页未显露；320px切页继承首页滚动、sticky按钮遮挡driver；中间宽度文字溢出；第三图原帖不明确。共同`workspace_server`测试fixture曾随机取到Fetch禁用端口1720，已在原owner过滤、保留同一listener并验证关闭/重试，不放开浏览器限制。

验证期间并行记忆预算改动进入工作树，旧已collect的上限失败预期及全书Canon预注入断言出现失败。保留该改动，协议测试沿其owner的新合同；UI用实际read_document工具结果验证修改后Canon和来源，初始router选择是按需的。最终全套在当前一致源码上完成，不把中途失败记为首次全绿；原失败过程保留在独立QA记录和`pytest-attempt2.xml`。

冻结输入`frontend-snapshot.json` SHA256：`e0ad3dbb04b31d3a256ad809724437a800230dc4177031aeb469a748bf4f5cf1`；当前wheel SHA256：`baf301dd1c886fc81f41c46e4fb5f9beb9a6833e5de8c790d78fed88166b963d`。`home-desktop.png`/`home-laptop.png`/`home-mobile.png`为实际页面截图，主预览http://127.0.0.1:8765/返回200。

插件cycle_status返回unbound/configured=false、QA驱动未配置。本轮按Skill纯指令模式完成工程记录和独立子agent/browser验收，未取得runtime保障。此阶段只关闭R1前端验收，不声称既有记忆架构已无缺陷、全部宿主/浏览器或文学效果通过；后续记忆加固仍按上方独立增量。未提交/push、未调用真实模型或改写正式小说。下一步可由用户直接体验并调整磁贴配置。

## 2026-10-09：真实Codex / gpt-6.1-sol max试写与接口修正

用户明确授权实际调用，模型固定gpt-6.1-sol、reasoning effort=max。使用本机Codex CLI **0.161.0**和现有ChatGPT登录，通过临时命令参数注册实际stdio MCP；未复制/检查凭证、未改全局Codex配置。两次独立真实模型会话，独立测试库在`output/harness-real-smoke-20261009-f5c4d61a`，正式作品未写入。

作品《雾中末班渡》：原大纲、三人/渡口设定及偏好进入实际资源；首轮调用资源发现/读取、recall、read_document、read_writing_reference、save_draft、remember与recall。正文**1874字符**保存成功。首轮暴露真实接口缺口：remember.update只声明object，缺少record/payload、小写record_kind、payload.text等可见结构；模型八次写入失败后才猜对并提交记忆。host随后达到600秒上限，exit=1，首轮不能记作正常完整结束；正文/记忆已提交并保留，技术状态由host标interrupted，不撤销故事事实。

最小修正：`memory/schema.py`生成模型可见DraftRef与update结构；组名/字段/方向分别复用graph.RECORD_GROUPS/RECORD_FIELDS/ENDPOINTS，领域复用state.DOMAINS。ToolDispatcher唯一登记同时供native/MCP消费。Normalizer给出update.experiences[].record等精确路径、小写kind和允许字段；不增加agent、文学审计或故事审批。新增6项回归覆盖真实错误形状与正确经历回读，窄集6 passed；相关旧/新memory/writer/资源集39 passed。

第二次独立会话只获取新run的资源/工具，写**334字符**尾声；初次recall的实际响应中含首轮记忆的**相同记录ID和完整经历文本**。怀表仍停在23:17、去店修表的承诺继续保留；父稿前缀完整、仅拼接一次。新记忆**一次成功**，memory_revision **1→2**；CLI exit=0、实际turn.completed，host明确completed。完整正文与尾声为`story-with-epilogue.txt`。Canon hash未改变，测试History为空，未自动采用。

实际记录：`manifest.json`、两个invocation/prompt/public-events/result、原始/第二快照、正文/尾声。只记录公开工具结果和使用量，不保存隐藏reasoning文本。第二次usage为累计input 346282（cached 270848）、output 4313（reasoning_output计数2926）；这是该CLI多轮累计，不是单次context大小；首轮超时未返回完整usage，因此没有总成本/最优token结论。

修改后完成门：**430 passed、1 deselected、90条既有兼容警告，112.11秒；retrieval_cases=72 failures=0；729有效文档、0问题**。实际测试socket、Codex/MCP子进程均已关闭；主要工作台可重新启动加载新声明。Codex0.161/指定模型的这一个案例已验证，ClaudeCode/Pi、内置profile真实provider、长篇记忆和作者文学效果仍未验收。

## 2026-10-09：Harness薄接入已实现

用户确认已有LLM的通用harness使用自身模型，项目提供小说参考/记忆/保存。沿[权威接入合同§15](HYBRID_GRAPHRAG_ARCHITECTURE.md#harness-integration)和原计划推进，四位独立审查者完成首评，架构/红队定向复验；没有新增agent、文学audit、路由模型或第六创作工具。

实际落盘：无模型RunService.prepare、两驱动共享tool_dispatcher/execute_tool、外部context/tool/finish；driver=harness/status=prepared不表示宿主model正在执行。CLI harness prepare/context/status/finish/cancel/mcp 连接同一后端，stdio不构造Store。网页可选外部工具、按需读取交接上下文、以`?run=`恢复指定任务，检查点可继续编辑/反馈/采用。文档使用方法见README。

| 当前证据 | 结果与实际观察 |
|---|---|
| AGENTS规定全套pytest | **424 passed、1 deselected、90条既有兼容警告，110.28秒**；新增20项包含harness核心/协议/浏览器，不把旧404当作新通过 |
| 检索与源校验 | **retrieval_cases=72 failures=0；729有效文档、0问题** |
| 原Windows跨进程锁排除项 | 修正PID活跃探测为只读Windows进程API后，原用例单独执行**1 passed**；全套仍保留指定排除表达式 |
| 新harness核心/协议窄集 | **19 passed**；零profile/坏config不阻断、五工具、真实DraftRef记忆、AuthorInputRef计划、父前缀/作者保护、CAS/终态/重试、CLI准备/恢复身份、第二真实写进程拒绝、HTTP解析异常未知结果 |
| 实际MCP进程 | stdio独立Python进程→实际TCP/Uvicorn→唯一Store；initialize/initialized/ping、精确五工具、context resource、保存/记忆与原结果；EOF保留prepared，重连换网络ID同operation_id不重复revision |
| 实际浏览器 | 已安装Edge、临时库/工作区、真后端；零profile准备→context→外部checkpoint可见→作者保存/采用→关闭本地工具→新副作用拒绝→显式feedback续写；带旧localStorage的URL指定run优先，390px/键盘/无pageerror |
| 函数与前端检查 | 149个本次涉及函数检查四项注释全有；node --check通过；代码/新增文件UTF-8与尾空白检查通过 |
| 实际预览后端 | 已重新启动http://127.0.0.1:8765，页面与无profileharness握手200，库根身份匹配；没有提交实际作品创作/模型请求 |

修复的已证反例：工具预检/保存间取消竞态、终态接受迟到写入、网络ID变动重复检查点、第二后端恢复首后端运行、profile读取阻断外部握手、可省略draft_ref与None导致回执指纹不同、BadStatusLine/IncompleteRead导致stdio退出。修正在原owner并复用提交表/锁，未建立第二事务引擎。

程序完成边界明确：MCP首版支持2025-11-25/2025-06-18；context须显式读取/交给宿主，不声称自动注入。首版同步保存检查点，未捕获外部token流；关闭本地工具不证明取消外部模型。实际Codex/ClaudeCode/Pi客户端实连、当前新协议时代互操作、真实模型工具选择与文学效果尚未验证。未装新SDK/浏览器，未改全局客户端配置，未提交/push，既有正式来源及未提交工作保留。

## 2026-10-09：v3 首版实施与实际验收

v3 首版创作主链与本地网页已实现，保留此前未提交的 v2 检索、生成和 Console 改动。用户授权实现及 subagent，并要求新增/修改函数说明依赖、输入、输出、实现。主入口为 workspace/write；程序检查、真实浏览器和受控原生模型端点通过，真实 provider 与作者阅读尚待进行。未自动改写既有作品或实际模型配置，未提交Git。

权威链：[架构](HYBRID_GRAPHRAG_ARCHITECTURE.md) → [v3 计划](ENGINEERING_REFACTORING_BOUNDARIES.md#v3-plan) → 本文件。[完整 v2 归档](archive/HYBRID_GRAPHRAG_ARCHITECTURE_V2.md) SHA-256：bf4993f6bd9f730e865153b9c23453af048c78dbd6c4a3c0610ddee515472c4b。归档前原文 SHA-256：94050e1b0d62ba7f9d0898b1d512eaf5e870decb0ce8a2bc6919f6d993d1a02b；历史说明后保留原文件完整字节。

已确认：本地网页、单个 LLM 创作主体、原始大纲路线、按需参考、短文风偏好/范例、取消默认文学 audit/评分/修复/回顾、作者采用、可靠保存恢复。用户已选择“按情节变化更新状态、正文连贯生成”，不沿用 R13 的四段 CHECK。

进一步确认 memory 用图 + router + 事件 + 伏笔，退出复杂多通道 RAG。首版默认有界图展开/贪心预算，Dijkstra/DP 是有条件的可选优化，router 不新增 LLM/agent。

| 项目 | 实际状态 |
|---|---|
| v3 基础设计/计划 | 四角色独立审查及变更复核完成；首版软件证据如下 |
| R13 状态/memory 增量 | 原本已核验，四角色首轮审查及定向复核完成；实施/维护剩余合同由原 reviewer 确认闭合；M0 设计完成 |
| 事件图/router 增量 | 可见图、有界展开、完整必要包、共享来源边际成本贪心及原文兜底已实现 |
| 正式架构定稿 | 阅读入口/目录/术语、RunBinding、流式、引用分型与示例已写；四角色发现已处置、定向确认闭合，文档/归档验证通过；M0完成 |
| 实施文档 | 12包、23项AC与故障矩阵保留；01–11已实施，12主入口切换已写，AC-V3-09待真实模型/作者阅读 |
| v3 软件/网页/工具循环 | 一个RunService、五个工具、chat/Responses原生流与完整turn、薄HTTP/SSE、静态工作台已接通 |
| 真实模型/文学效果 | 未调用真实 LLM，没有效果提升结论 |
| 取消/恢复/采用 | transport取消等待、partial保存/恢复、草稿CAS、迟到独立稿、单History采用、intent恢复及memory_pending故障验证通过 |
| 资料/源码 | 业务源码新增v3分包，既有作品与未提交工作保留；阶段证据如下 |

### R13 来源与设计增量

用户提供的附件见[逐字节原本](references/kardia-r13-full-symbolic-lean.source.txt)：63,106 字节、706 行，SHA-256 a999dd0f4113672d6c61e18b1502b7ed839f40674c5735375adc7b0cfe8e876e。只把实际提供的合成文本作为来源，不声称 A–H 完整原书/文件已加载。

已核对原本 runtime_contract：事实/人物摄取/条件与 Set/Clear 有复用价值；完整九项 CPM、每四段 CHECK、Guidance 试写修复及 HTML 输出协议与本轮方向不符。[新增状态/memory 合同](HYBRID_GRAPHRAG_ARCHITECTURE.md#state-memory)区分 Persona、World、CharacterView、OpenCondition、Continuity；记忆绑定叙事游标、不可变正文检查点、分支和实际来源，低于正式原文。

四角色独立意见已采纳：人物知识保守绑定检查点生效，不取事实的最早来源时点；Continuity 由动态条目派生，避免重复状态；追加保留检查点、改写保守失效；Clear 批次持久化，失效不得复活旧 Set；旧工具历史/continuation 不能绕过投影校验；Summary 新 metadata 与 author_note 编辑标记由原 owner 保证往返。部分覆盖不阻断生成/编辑/采用，不新增 observer、状态审批或文学 audit。

### Memory v0.5 与事件/router 增量

本轮对话贴文保存为 [Memory v0.5 原本](references/kardia-memory-v0.5.source.txt)，SHA-256 f901468cec65320f6025b14b90077d95f5d90546eab0bd4d8a12d6ca027f3c71；它是来源文本，不作为整份活跃指令注入。用户明确说明 RP 记忆栏接入 agent 不必照搬。

[§7.7 新合同](HYBRID_GRAPHRAG_ARCHITECTURE.md#event-memory-router)保留独立因果线 EventLine、唯一 Experience、待续与伏笔区别。图用 state_ref 读当前效力，router 先过滤可见图再组装不可拆因果包，缺失必要前因时不伪称完整。历史回读不产生新事件/知识；作者计划和解释仍标性质。模型仅见 recall/remember 两个记忆工具；memory_revision、StoredMemoryBatch、summary.memory_batches 统一，批内 local_ref 由 host 解析，内部 StateBatch 不另存日志。

已复核静态源码：GraphReader.neighbors 为双端跳数扩展；别名/关系检索与 estimate_tokens 可复用，但五通道组装不进入 v3。参考图当前无事件/伏笔记录，算法不会制造历史。没有新增数据库、向量服务、模型路由或收费调用。

### 正式架构定稿

用户再次明确要求使用 design-review-council 写架构文档。本阶段沿同一权威文件整合，不建立另一套 PRD。四角色只复核公共数据/基线/流式/维护边界，复用已经闭合的图、算法和持久化意见。

新增 [运行绑定](HYBRID_GRAPHRAG_ARCHITECTURE.md#run-binding)、[记录形状/链接](HYBRID_GRAPHRAG_ARCHITECTURE.md#event-records)、[来源分型](HYBRID_GRAPHRAG_ARCHITECTURE.md#source-references)与[完整路径示例](HYBRID_GRAPHRAG_ARCHITECTURE.md#run-examples)。已采纳：增量先保存再显示、partial与正文检查点分开；父稿suffix/新章full body唯一组装；章前状态与原章修改参考分开；Document/Draft/AuthorInput hash分域；输入引用保护；拓扑唯一Link、同批规范化ID/来源。增加AC-V3-22/23，无新模型工具/事务框架/第二事实库。

### 实施文档：从设计进入可执行任务

用户要求用 design-review-council 准备实施文档。沿 [既有工程计划](ENGINEERING_REFACTORING_BOUNDARIES.md#v3-implementation)展开 IMP-V3-01–12，权威仍是架构文件；没有新增PRD、任务系统或业务实现。

架构、反例、实现验证、可维护性四角色独立审查完成。主agent采纳下表问题并校验文档；架构角色确认前置依赖已解决，维护角色确认两项来源/CAS修订已落实且无剩余文档阻塞。模型协议、保存/取消、实际采用、并发与浏览器仍须实施后运行，不把这次确认当成程序验收。

已落实的实施裁决：

| 问题/证据 | 实施处置 |
|---|---|
| M2要求流式真实保存，M3才建Store会迫使临时存储 | M3-a最小Store前移；05先落盘，06/07接协议/批次，08收口唯一session/CLI |
| service即使include_shared=False仍校验旧module/version maps | 02在原owner新增明确source-only源读取策略；保留本书身份/schema/lineage校验与v2默认 |
| mutations/changes只是导出，原子写在Coordinator私有实现 | 05从coordinator原逻辑公共化；凭证安全writer不混并，不登记尚未实现的新公共API |
| 批次成功但回执丢失，旧expected版本会被新CAS误拒绝 | 05/07同一权威快照保存批次/版本/ID映射/幂等结果，先查原调用再查新CAS；新实例故障恢复验收 |
| source-only仍需接真实工厂/锁内挂接点 | 09保留v2拒绝YAML-only的回归；10以真实History replace后窗口测试采用事实，不用mock Coordinator代替 |
| 现有stage/CLI替身测试不能证明原生工具或浏览器 | 受控原生帧HTTP、临时源/真实Store、CLI子进程、真服务SSE/浏览器分别验收；新增测试均待实施 |
| service→generation.types会触发包eager导出/helpers→service循环 | 架构§2.1同步澄清DocumentRef归documents，generation/types重导出；01/02验证源owner独立导入 |
| SummaryEditor/Writer先读内容/权限、后取文件hash有覆盖窗口 | 架构§7.6/8.1同步同次字节源快照；02供源快照，10用同快照CAS/新目标MISSING保护，原owner测试三组竞态 |

验收分配见 [23项AC矩阵](ENGINEERING_REFACTORING_BOUNDARIES.md#v3-acceptance)，采用/流式/回执/输入版本的实证边界见 [故障矩阵](ENGINEERING_REFACTORING_BOUNDARIES.md#v3-failure-matrix)。状态视图、接收快照、工具展示回执都不能另成一份故事事实；首版不实施Dijkstra/DP或额外抽取/路由模型。

实施状态：M0设计完成；IMP-V3-01–11已落盘并验证，12的用户主入口已切换，真实模型/作者反馈尚未执行。已经完成“临时YAML→write CLI/网页→受控原生HTTP→五工具/终稿→保存恢复→作者采用”链；不据此声称正文更好或provider已接通。

### v3 最终程序证据（2026-10-09）

| 检查 | 实际结果与边界 |
|---|---|
| 完整pytest | 404 passed、1 deselected、90 warnings，83.64秒；按项目规则排除指定Windows跨进程锁用例，警告为既有v2兼容弃用 |
| 完整检索回归 | retrieval_cases=72 failures=0 |
| 真实库校验 | 729个有效文档、0个问题；测试中的源提交均使用临时作品 |
| 真浏览器/真socket | 已安装Chrome/Edge、Uvicorn loopback、本地NativeEndpoint；创作→工具→编辑→采用，停止→刷新→部分保存→续写，偏好→实际请求、Canon编辑→read_document；键盘、1360/390px无溢出、脚本文本不执行、无pageerror |
| 原生模型协议 | chat/Responses文本流、参数分片、完整call_id配对、继续项/加密reasoning、非流式、断流前缀、响应头/流中取消和资源清理；仅受控HTTP，不是实际provider |
| 采用/恢复 | 完整字节备份、MISSING首次写、目标与草稿基线CAS、旧ID保持、commit后回执故障仍adopted、A→B→重试A、新实例恢复、笔记/input保护失败仍adopted+memory_pending |
| 记忆与游标 | 整批幂等/稳定ID、Set/Clear/scene/carry、旧状态不复活、按来源故事顺序回放、正式/草稿未来记录先裁剪、前缀改写失效、来源外改直接拒绝旧CAS、整包预算与原文入口 |
| 注释/资产 | 新主链与相关公共函数四项中文注释核验；JS语法检查通过；R13逐字节等于附件、Memory来源/v2归档SHA保持 |

实际源码入口：composition.build_writer_service → RunService；工具只在 generation/tools.py 登记；memory/state、graph、router、service分别管理状态、关联、取用与整批校验；DraftStore统一保存接收/检查点/候选与来源；AdoptionService复用原Coordinator源锁。Web与CLI不拥有第二条生成循环。

完整门命令为项目原要求：

```powershell
python -m pytest -q -k "not test_file_lock_uses_windows_safe_exclusive_create_across_processes"
python scripts\run_retrieval_tests.py
python -m novel_rag.cli --library novel-rag validate
```

本次验收修复了真实缺陷：采用基线旧版本被新请求hash绕过、前章hash误作新场景CAS、部分保存后空编辑框被误标dirty、未来记录/边界进入当前视图、Clear后无法复用稳定ID、Source变化未推进统一revision、summary文件名回放使旧Set复活，以及未采用父Draft误把前章当修订目标。旧doctor命令清单断言同步保留旧命令并加入两个v3入口。未重新引入文学门。

网页“偏好与资料”复用onboarding/SummaryEditor：偏好完整字节CAS，简单Canon/summary文本可编辑，结构化资料只读保持形状，History可选为修改基线。新目标坐标另建History并保留原章；无法按原语义映射的候选显示skipped，正文仍可采用。

默认工作产物在outputs/.workspace，source-versions与input-versions需要随作品一起保留；它们不是可随临时run删除的缓存。[浏览器截图](../output/playwright/v3-workspace.png)是临时演示作品，不能当小说质量或实际账户证据。

本地查看服务已在 http://127.0.0.1:8765 启动，页面/引导均返回200；当前加载2部作品、0个模型profile。没有自动发起模型请求；添加本地模型配置后才能实际试写，配置方法沿README的api-config说明。

剩余验收：AC-V3-09实际模型章节与作者阅读反馈、第三方provider实连；未增加新人物的自动实体登记/抽取、Dijkstra/DP或独立路由模型。新人物可通过正文经历与自然语言状态记录，实体Link仍需host已知身份。未删除旧数据或旧写作入口。

### 本会话基线

以下为启动v3实现前的兼容基线，不是当前v3运行结果：

- pytest：299 passed、1 deselected、90 warnings，排除指定 Windows 跨进程锁测试；44.20 秒。实际命令另用 -B 与 -p no:cacheprovider。
- retrieval_cases=72 failures=0；CLI validate：729 有效文档、0 问题。
- 两故事仅 main，关系边均 0，正式摘要文档 0，默认 semantic_enabled=false。
- 已运行只读探针：26 条检索中 25 条模块占位含 6 deprecated；生成只取前 12 条，History 丢失；另一大纲 mandatory 14,893 > 默认 4,096；第二事件 render 没有第一事件正文，润色改原句被 substring 门拒绝。

评审新增静态证据：旧 confirm 源提交后 result/confirmation 收尾窗口；Coordinator 多文件 replace 非全局原子；旧 cancel 主要为 UI 标志。尚未故障注入，未写成运行复现。

### 文档交付验证

2026-10-08 基础交付已检查 6 个文档/入口文件：17 个本地引用与锚点有效，7 个需求 ID、9 个验收 ID 唯一，v2 归档原文字节及两份 SHA-256 校验一致；新增区块无尾部空白。伴随文档保留的历史区块仍有空白格式提示，本轮未清理其既有记录。

2026-10-09 R13 增量验证通过：6 个文档/入口文件的活跃区块，19 个本地引用/锚点有效；10 个需求、17 个验收顺序/身份唯一，Markdown 围栏闭合，新增区块无尾部空白。R13 仓库原本与附件逐字节一致，v2 归档与原文 SHA-256 均保持上述值。架构/README/本文件的 diff 空白检查通过，非文档 Git 状态 48 项与增量开始时一致；历史区块未清理。

事件图/router 增量验证通过：6 个文档/入口的活跃区块、23 个本地引用/锚点有效；12 个需求与21个验收顺序/身份唯一，Markdown 围栏闭合、新增区块无尾部空白。Memory v0.5 来源文本为7,824字节/58行，封套/七项不变量及上述 hash 保持；R13 附件字节与v2归档 hash仍一致。非文档 Git 状态48项与本阶段开始时一致。已用穷举核对独立固定收益玩具例：贪心A=12，最优B+C=18；没有实现DP或运行生产router，不能据此证明小说效果。业务代码未改，复用上述299/72/729基线。

正式定稿验证通过：6个文档/入口活跃区块，35个本地引用/锚点有效，12个需求/23个验收顺序与身份唯一；五个模型工具登记一致，JSON示例可解析、9个local_ref唯一且5条Link端点类型正确，拓扑未双写。R13/Memory v0.5来源与v2归档指纹保持不变；新增区块无尾部空白/未闭合围栏，架构/README/本文件diff空白检查通过。非文档Git状态48项与本阶段开始时一致；仍没有v3软件、模型或浏览器运行证据。

实施文档验证通过：12个IMP工作包的表格/正文身份与顺序一致，15条依赖图边覆盖工作包前置且无循环，架构23项AC均有对应检查；6个文档/入口活跃区块的44个本地引用/锚点有效。计划中的13个新增测试文件当前未存在，9个既有测试及主要owner文件路径核验有效，命令均标明待实施。五工具/JSON示例及R13/Memory/v2归档校验仍通过；非文档48项状态和已跟踪业务diff指纹均未变。公共模块三道门复用未改代码的299/72/729基线，本次未运行v3代码、模型或浏览器。

以上“文档交付验证”是设计阶段历史记录；本次软件/HTTP/浏览器与三道门的实际结果以本页上方“v3最终程序证据”为准，真实模型/作者阅读仍未验收。

### 下一步

使用workspace/write进行实际试写并收集作者阅读反馈，分别记录人物自然度、遗漏设置/前文与参考是否有用；不增加默认评分或修复流程。源码继续工作前核当前状态/测试，保留工作产物、版本备份和旧入口；旧任务表仅属于v2历史。

## v2 历史交接（保留原记录）

> 状态：进行中，不能视为最终验收通过
>
> 更新时间：2026-08-22
>
> 执行方式：由 `luna_worker` 负责实现与局部验证，主智能体负责调度、范围控制和最终验收。
>
> 本文是交接与恢复入口，不替代架构合同；架构冲突以权威文档为准。

## 1. 目标与权威文档

本轮目标是把 `docs` 中约定的 Authority-first Hybrid GraphRAG 架构和工程迁移目标落到代码、canonical 资料布局、派生图和可重复验收上。用户已确认的决策如下：

- 时间线在发生分歧后独立；子时间线只继承分歧前的祖先区间和创建时的快照。
- YAML 仍可由用户直接编辑；编辑后相关图必须 stale，不能在生成时隐式重建。
- 多图不要求同时切换；每张图构建、完整性检查和回归通过后即可单独提升。
- AI 可以自动写章/卷/场景摘要；摘要保存到 YAML，不要求人工批准，前端保留用户编辑入口。
- SQLite、FTS5 和 trigram 是安装前置条件；运行时不提供静默弱化降级。

权威材料：

- [HYBRID_GRAPHRAG_ARCHITECTURE.md](./HYBRID_GRAPHRAG_ARCHITECTURE.md)：唯一架构真相源，定义 GraphKey、timeline、五通道、fingerprint、Reader/Builder、MutationCoordinator 和单图提升合同。
- [ENGINEERING_REFACTORING_BOUNDARIES.md](./ENGINEERING_REFACTORING_BOUNDARIES.md)：实施问题、迁移阶段、禁止搭车修改和验收清单；不得重新定义架构。
- `novel-rag/registry/layout.yaml`：当前布局和旧布局兼容边界的注册信息。

## 2. 已完成的实现范围

以下内容已有代码落盘，并有测试或局部运行证据；“已落盘”不等于所有生产验收已经闭合。

### 2.1 架构与代码

- `novel_rag/identity.py`、`novel_rag/catalog/` 和 `novel_rag/layout.py` 已提供 GraphKey、路径、注册表、timeline lineage、分歧坐标和 canonical corpus 校验。
- `novel_rag/graph/` 已拆出只读 GraphReader、GraphBuilder、SharedReader、SharedBuilder、manifest、SHA-256 fingerprint、临时 SQLite 构建和逐图提升。
- `novel_rag/retrieval/` 已提供 Authority、Graph、Temporal、Lexical、Semantic 五类合同、证据归一化、冲突门、上下文组装和回执；`shared` 作为 Authority 数据来源，不是第六通道。
- generation 默认通过 composition 注入 graph-backed retriever；旧 `search_isolated()` 和 `rebuild_isolated_indexes()` 仍保留兼容转发和弃用告警。
- `novel_rag/mutations/` 已提供 ChangeSet、MutationCoordinator、staged YAML、逐 GraphKey 构建、promotion 状态、失败保留和 pending manifest。
- 生产组合根已使用 `FileMutationLock`、`.novel-rag/staging` 和 `.novel-rag/pending`；CLI/TUI 已有 `pending list` 与 `pending retry` 入口。
- 摘要生命周期已接入 YAML：AI 写入、`ownership`、`source_fingerprint`、revision、SummaryEditor 的 expected revision，以及用户摘要 stale 后不自动进入 ContextBundle 的门禁。
- `doctor` 已实现安装能力检查；Reader 使用只读连接，缺图或身份/fingerprint 不符时不会创建空库。
- 2026-08-22 新增结构化字段投影：builder 支持复数实体键（`character_ids/location_ids/faction_ids/ability_ids`），并把正文 `character.aliases` 在唯一归属实体时投影进 aliases 表（歧义即拒绝，不猜边）；Reader 对 trigram 无法表示的 <3 字符中文查询词增加精确子串 LIKE 兜底；RetrieverService 增加单查询词召回深度下限。关系表仍为空——现有 relationships 资料是自由文本，按架构 §4.2/§13 不得自动投影为类型化边，需另行定义结构化关系格式。
- 2026-08-22 第二批：新建 `catalog/aliases.py::load_story_aliases`（registry/aliases.yaml 唯一加载器），builder 经 `registry_aliases=` 显式输入按 lineage 投影（重建后 fujimaru aliases=48、shirouxcile=18）；新建 `templates/relationship-canon.yaml` + `validate_document` relations 规则 + 两份仅转录既有 canon 的 draft 关系数据；`_retrieval_regression` 门从裸 FTS 对齐为与官方脚本一致的五通道语义（修复了暂存门比生产更严的历史不一致）。

### 2.2 canonical 资料与派生图

迁移采用 copy-only 方案，当前 canonical 树共有 **716 个 YAML 文件**。旧资料仍保留，未做删除或移动。

截至交接时的实际校验/manifest 记录：

| 派生物 | 文档数 | FTS 分块数 | 路径 |
|---|---:|---:|---|
| shared | 25 | 94 | `novel-rag/index/shared.db` |
| `overturned-world-fujimaru/main` | 652 | 1108 | `novel-rag/index/graphs/overturned-world-fujimaru/main.db` |
| `shirouxcile/main` | 52 | 105 | `novel-rag/index/graphs/shirouxcile/main.db` |

2026-08-22 结构化投影重建后的图内容计数（文档/分块数与上表一致）：

| 图 | entities | aliases | 实体关联文档 |
|---|---:|---:|---:|
| `overturned-world-fujimaru/main` | 32（24 character + 8 location） | 45 | 191 |
| `shirouxcile/main` | 24（6 character + 18 location） | 14 | 47 |
| relations | 两图均为 0（自由文本关系不投影，见 §2.1 说明） | | |

当前两个故事都只有 `main` timeline；分支时间线的真实资料验收尚未替代单元测试中的 lineage 覆盖。

## 3. 已有验证证据

以下是可复现的已知结果。命令在 Windows PowerShell 下从 `D:\novel-project` 执行。

| 验证 | 命令 | 结果 |
|---|---|---|
| 测试收集（2026-08-22） | `python -m pytest --collect-only -q` | `224 tests collected` |
| 完整测试（排除唯一待确认的跨进程锁测试，2026-08-22） | `python -m pytest -q -k "not test_file_lock_uses_windows_safe_exclusive_create_across_processes"` | `223 passed, 1 deselected, 84 warnings` |
| 锁/pending 单进程覆盖 | `python -m pytest -q tests/test_mutation_lock_pending.py -k "not windows_safe_exclusive_create_across_processes"` | `5 passed, 1 deselected` |
| canonical 注册表与资料校验（2026-08-22 复跑） | `python -m novel_rag.cli --library "$PWD/novel-rag" validate` | `729 个有效文档, 0 个问题` |
| 安装能力预检 | `python -m novel_rag.cli doctor` | `ok=true`，SQLite 3.35.5，FTS5/trigram 均为 true |
| 双故事隔离 | `python scripts/verify_multi_story_isolation.py` | `multi_story_isolation=PASS`，`cross_story_leaks=0` |
| **正式检索回归（2026-08-22，P0 闭合）** | `python scripts/run_retrieval_tests.py` | `retrieval_cases=72 failures=0`（overturned-world-fujimaru/main 与 shirouxcile/main） |
| 图新鲜度验收入口（2026-08-22） | 以 `composition.build_graph_retriever` 加载两图 | 两图均通过身份 + fingerprint 校验，无 stale |
| **shared 反向依赖（2026-08-22，P0 闭合）** | `python scripts/verify_shared_dependency.py` | `shared_dependency=PASS dependent_graph_keys=2 zero_map_references=0`，8 条引用反查全部命中且两次调用结果一致 |
| 完整测试（2026-08-22 晚，含新增 7 项测试） | 排除锁测试的 pytest | `230 passed, 1 deselected, 84 warnings` |
| stale 演练（2026-08-22，沙盒库） | 直接改写一条 world-state YAML 后 search/retriever | 构建期报“图已过期”、CLI search exit=1；字节级还原后无需重建即恢复新鲜 → PASS |
| 占用演练（2026-08-22，沙盒库） | 独占事务占用 main.db 后执行 index | 明确 WinError 5 失败；旧图 fingerprint 不变且可检索；释放后重建成功。`pending list` 为空——pending 清单属 coordinator 流程，普通 index 不产生 → PASS |
| 摘要生命周期（2026-08-22，沙盒库） | `summary write-ai`→list/show→edit 冲突与成功 | write-ai 经 coordinator 门通过并落盘 ownership=auto revision=1；错误 revision 报“revision 冲突”exit=1；正确 revision 升为 ownership=user revision=2 → PASS |

`218 passed` 的命令明确排除了一个测试，因此不能写成“219/219 全部通过”。此前被中断的长测试输出也不作为最终绿灯证据。2026-08-22 起检索回归已闭合；全量门禁以当日 `223 passed, 1 deselected` 为准。

## 4. 尚未闭合或需要最终复核的项目

### P0：在宣称完成前必须闭合

1. **Windows 多进程排他锁**：`test_file_lock_uses_windows_safe_exclusive_create_across_processes` 尚未闭合。2026-08-22 两次单独运行（一次裸跑约 15 分钟、一次带 `--timeout=120`）均在 worker 就绪前挂起且无失败报告产出；怀疑 `multiprocessing` spawn 在当前环境卡死。建议下次改为显式 `subprocess.Popen(sys.executable, …)` 驱动同一跨进程契约后重取证据。
2. ~~**正式 72 条 retrieval regression**~~：**已于 2026-08-22 闭合**。`python scripts/run_retrieval_tests.py` 输出 `retrieval_cases=72 failures=0`；此前失败的 `state-fujimaru-abilities`、`shirouxcile-orpheus-ciel-alesia`、`shirouxcile-history-c001-seventh-scripture-support` 三例随结构化投影与检索修复一并解决。
3. ~~**真实 shared 反向依赖**~~：**已于 2026-08-22 闭合**。新建可重复脚本 `scripts/verify_shared_dependency.py`，输出 `shared_dependency=PASS dependent_graph_keys=2 zero_map_references=0`；8 条 module references 经 ModuleGraphIndex 反查全部命中受影响 GraphKey，两次调用结果一致。

### P1：紧随 P0 的生产边界复核

- 用真实 library 执行 pending list/retry，确认 pending manifest 可跨进程/重启恢复，promotion 失败时不使用旧图冒充新图。
- 对 shared YAML 做临时、可恢复的 fingerprint 变更，在不删除资料的前提下确认所有依赖图被拒绝生成；随后恢复原内容并复建通过。
- 对用户摘要 revision、自动摘要不覆盖用户版本、用户摘要 stale 不进入 ContextBundle 做一次真实 CLI/TUI 流程复核。
- 复核默认 generation、importer、state、writeback、feedback 都经由组合根和 MutationCoordinator，不直接创建/写入 SQLite。

**2026-08-22 沙盒演练结果**（完整库拷贝上执行，真实资料未动）：stale 拒绝/恢复、独占占用下的提升失败保护、摘要生命周期（auto 写入→revision 冲突可见→user 修订不被覆盖）三项 PASS。仍待复核：shared YAML 变更使全部依赖图拒绝的端到端（当前仅有确定性反查脚本）、coordinator 入口（import-rag/confirm）的真实 pending retry、写路径全量审计。

### P2：验收完成后的清理与维护

- 统计仍在使用的旧 facade/shim 和弃用告警；只有零调用、完整回归和用户授权都满足后才删除。
- 维护检索回归基线、manifest 指纹和数据计数，避免以固定测试数量替代完整测试门禁。
- 在另一个真实分支 timeline 数据集上补做祖先 cutoff、divergence snapshot、同级/后代误召回为零的端到端验收。

## 5. 下一步任务表（按优先级）

| 优先级 | owner 建议 | 命令/动作 | 完成标准 |
|---|---|---|---|
| P0 | `luna_worker`：锁测试 | `python -m pytest -q tests/test_mutation_lock_pending.py::test_file_lock_uses_windows_safe_exclusive_create_across_processes -vv` | Windows 上稳定 `1 passed`，子进程退出码为 0，锁文件按预期释放，无残留进程 |
| ~~P0~~ 已闭合 2026-08-22 | `luna_worker`：检索回归 | `python scripts/run_retrieval_tests.py` | `retrieval_cases=72 failures=0`（已达成，证据见 §3） |
| ~~P0~~ 已闭合 2026-08-22 | shared 依赖 | `python scripts/verify_shared_dependency.py` | `shared_dependency=PASS dependent_graph_keys=2 zero_map_references=0`（已达成） |
| P1 | `luna_worker`：pending | `python -m novel_rag.cli --library "$PWD/novel-rag" pending list`，必要时再执行 `pending retry` | 无遗留 pending；若人为制造文件占用，结果明确为 pending，释放占用后 retry 变为 promoted |
| P1 | `luna_worker`：真实 stale | 备份后临时改一个 YAML，运行 `validate`/`search`/`generate`，再恢复文件 | 旧图被拒绝使用；恢复后 fingerprint 与 manifest 一致，检索恢复；不删除或覆盖旧资料 |
| P1 | 主智能体 + `luna_worker`：摘要流程 | `summary write-ai`、`summary edit --expected-revision` 及 TUI 对应流程 | AI 摘要可直接使用；用户 revision 冲突可见且不会被自动覆盖；stale 用户摘要不进上下文 |
| P2 | 主智能体：清理评审 | 静态调用扫描、`python -m pytest -q`、CLI 回归 | 只有明确授权后才删除 shim/旧派生物；删除前有可回退清单 |

## 6. 安全边界与不可误解事项

- 本轮没有删除旧资料、旧索引或旧 DB；`novel-rag/index/stories/*.db` 等兼容产物仍可能存在，不能把它们当作已清理对象。
- canonical 迁移是 copy-only；不得以“整理目录”为由移动、覆盖或删除旧源。
- Git 当前存在大量实现、测试、资料和派生文件的未提交修改；本任务不执行 `git add`、`git commit`、`git reset`、推送、发布或安装。
- 不得通过跳过失败用例、放宽 stale 检查、改写回归 fixture 或静默降级来获得绿灯。
- 不得把 218/219（排除一项）写成全量通过；P0 三项闭合前，整体状态仍是进行中。
- 任何破坏 YAML 真相源、timeline 物理隔离、权威优先、证据可解释、过期拒绝或逐图验收提升的改动，都必须先更新权威架构并重新评审。

## 7. 恢复工作入口

恢复时先执行：

```powershell
Set-Location D:\novel-project
git status --short
python -m novel_rag.cli doctor
python -m novel_rag.cli --library "$PWD\novel-rag" validate
python -m pytest --collect-only -q
```

随后按 P0 顺序执行锁测试、72 条 retrieval regression 和真实 shared 反向依赖检查。每项都保存命令、完整 stdout/stderr、时间和结果；不要依赖聊天摘要或旧的 `.codex-final-pytest*.out` 作为唯一证据。

若中途发生 promotion 失败，先运行 `pending list`，保留 `.novel-rag/pending` 和 staging 证据，再由 `pending retry` 恢复；不要手工删除 pending、临时图或旧图。若必须改变实现，仍由 `luna_worker` 执行，主智能体只调度、复核范围并更新本交接文档。

