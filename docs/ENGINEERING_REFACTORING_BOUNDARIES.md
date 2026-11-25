# Novel-RAG 工程问题与迁移边界

> 实施状态：v3/harness/信息迷雾、记忆可靠性、整体context与旧线索候选发现已有实现；当前能力、最近有证据的验证基线、已关闭反例与开放项统一见[当前状态摘要](IMPLEMENTATION_STATUS_AND_NEXT.md#current-status)。下方工作包、授权与验收数字保留各阶段范围，后续实施从摘要定位对应证据。
>
> 权威声明：架构、布局、依赖方向和稳定接口只由 `HYBRID_GRAPHRAG_ARCHITECTURE.md` 定义。本文件记录现状问题、迁移顺序、禁止搭车修改和验收证据；不得成为第二份架构规范。
>
> 本文件不授权删除资料、改变 Canon、安装运行时服务、引入向量数据库、提交 Git 或发布部署。


<a id="v3-plan"></a>
## v3 实施计划

### 2026-10-23 项目std与包边界重构（已完成，结果见当前摘要）

本轮用户接受整体审查并指示“合理 做吧”；依照权威架构§19执行四批，不另建规划系统。工作区254份源码/测试/脚本/契约的before副本与1567份非索引资料hash保存于`output/architecture-std-refactor-20261023/baseline.json`及`before/`；不能把HEAD以来旧改动算成本轮改动。

| 批次 | 范围与owner | 验收与恢复 |
|---|---|---|
| STD-01 | mutations锁修复/标准库OS guard，聚焦并发回归 | 双恢复者、子进程互斥/死亡恢复；保留元数据与锁域 |
| STD-02 | std时间/字节hash/原子IO/既有JSON及调用迁移，旧owner兼容导出 | 字节格式、旧参数幂等、只依赖标准库；不动正式资料 |
| STD-03 | contracts来源合同、惰性v2导出、mutations/source、RunService作者保存 | 来源导入边界、旧API、源锁→Store锁、采用/取消/恢复 |
| STD-04 | src布局/资料与资源根、依赖分组、脚本测试适配 | 隔离副本构建与仓外安装验证，三完成门，独立QA |

允许改动工程源码、对应测试/脚本、pyproject、README/AGENTS及既有三份契约；保留原作品、原运行、凭证、历史验证产物。回退依据本轮before与文件清单，只还原本轮变更。不提交/push或调用付费模型。每批先聚焦验证，最终对实际运行输入执行项目三完成门；问题修复后仅重验受影响范围及必要完成门。

### 2026-10-23 应用入口与运行提交解耦（已完成，结果见当前摘要）

用户指定CLI/Web与草稿/记忆/采用两处，合同见权威架构§20。AB-01将运行视图/目标建议/采用编辑及观察收进RunService，保持HTTP响应字段、SSE帧、CLI结果及生命周期；AB-02用纯记忆效力函数、明确MemoryCommit及Store专用CAS/回执操作收拢跨包写入。只改变这些边界；不搭车处理v2导入或context/tools循环。基线为`output/application-boundaries-20261023/before/`的239份文件和`baseline.json`的1567份非索引资料。旧724/72/729属于上一轮，不认证本轮。完成门、独立QA与当前结果沿当前摘要更新。

本节承接 [v3 唯一架构](HYBRID_GRAPHRAG_ARCHITECTURE.md)。下方原 v2 目标、R1–R6 和验收记录保留历史语义，不把“保持现有写作行为”用作阻止已确认 v3 创作流程的条件。

### 授权与实施边界

本次已授权架构准备、实施文档与独立评审；本轮不改业务代码、原始作品或模型配置。实施承接下列工作包，不重复确认单 agent、取消文学 audit、作者采用，以及“按情节变化更新状态、正文连贯生成”这些已决方向。安装依赖、收费模型、Git 提交/推送和发布不由评审自动授权。

用户进一步确认memory用图 + router + 事件 + 伏笔。2026-10-10取消默认token预算：沿架构§7.7有界展开后去重合并完整相关包，显式容量兼容路径才用贪心；初始上下文按相关原文/明确基线装配。Dijkstra/DP仅在声明条件成立时可选，不引入旧五通道、社区摘要或第二个路由模型。

保留现有未提交改动。启动实施时重新记录 source diff 和资料清单，复用未变的有效验证；各阶段执行受影响检查和项目必需门禁，不为文学内容建立评分、审计或自动修复门。

| 阶段 | 范围与依赖 | 完成条件 |
|---|---|---|
| M0 设计 | 正式架构/阅读入口、目录/数据/流式/基线合同、计划/状态、原本与v2归档 | 四角色发现闭合，示例/引用可校验；代码仍v2，M1–M6可按owner实施 |
| M1 参考入口 | service/catalog/documents 的 scope + narrative cursor 公共入口；memory/service/state/graph/router 只读合同、generation/context；M0 | AC-V3-01/07/14/15/18/19/20：原文可读、可见图先过滤、因果包完整、关键待续/伏笔可路由；无图/无记录显示缺口 |
| M2 会话工具 | model_api turn/on_text_delta、generation/session/types/tools、composition；recall/remember与实际资源；M1、M3-a | AC-V3-02/03/16：两协议共用循环，真实落盘后显示、完整turn后工具；原大纲保留，无额外模型/报表 |
| M3-a 保存基础 | store接收快照/输入快照/checkpoint/RunBinding/幂等结果；M1；先于M2交付 | partial与DraftRef分开；持久化批次/版本/ID映射和结果可由新Store实例恢复 |
| M3-b 运行恢复 | 统一记忆批次/CAS、正文映射、取消/恢复、write CLI；M2 | AC-V3-04/05/10/11/12/13/21/23：partial恢复/明确冻结，迟到不覆盖；唯一正文组装，章前/父前缀继承；幂等/类型拒绝 |
| M4 作者采用 | writeback/adopt、source-only锁域；summary.memory_batches往返、正文映射与保护输入引用；M3 | AC-V3-06/13/17/21/22：History/adoption_id恢复；Document/Draft/Input分型，input-versions先保留再发布，memory_pending不撤销正文 |
| M5 本地网页 | web/app/static、事件观察、编辑/采用、可展开的来源/覆盖缺口；M3/M4 | AC-V3-08/15：真服务浏览器创作/编辑/采用及停止/刷新/恢复；键盘、四态与同源凭证；partial 不阻断正文 |
| M6 主入口切换 | composition/CLI/README、兼容说明、实际章节；M1–M5 | workspace/write 为主入口，旧命令语义保留；AC-V3-09 记录作者反馈及真实输出，不用 v2 绿灯或结构化状态测试代替文学效果 |

每阶段可回退 v3 入口，保留 v2 资料/调用链。M6 前不删除旧 pipeline、shim、规则、状态能力；后续收缩另列调用清单。

M 是交付里程碑，不是要求 M2 完成后才允许写 store。具体开发顺序以下面的 IMP-V3 工作包为准；M3-a 提前解决 M2 的真实流式保存依赖，避免临时内存 Store 或第二条工具循环。

### 组件复用与唯一归属

| 能力 | 复用/演进 owner | 防止重复 |
|---|---|---|
| 身份、路径、别名、lineage、叙事游标 | identity、catalog/paths、aliases、ValidatedCorpus.for_graph；原 owner 公共化 StoryCoordinate/文档坐标选择 | search/read/recent/state 共用可见范围；不另建目录解释器或时点解析器 |
| scope YAML/格式 | service/documents 公共入口，v2 模块登记策略保留 | memory/web 不写 rglob+safe_load，新字段由 documents 校验 |
| 时间/指纹 | timeutil、catalog/corpus、mutations/types fingerprint_bytes/file | 正文 hash 和完整 YAML hash 分域，不另写算法 |
| 分块/FTS/短词/只读连接 | chunking、graph/reader，跨域私有能力先公共化 | 不复制 MATCH/LIKE 或裸 SQLite 连接 |
| 原子文本/checkpoint | mutations/coordinator 公共化已有 staging/temp/fsync/replace 原语，store/writeback 委托 | changes.py 只是兼容导出；不复制直接 JSON write/.tmp；凭证权限由 model_config 保留 |
| 草稿分支、检查点来源映射 | generation/store；remember、state、writeback 委托 | 同一前缀核验与保守失效规则，不逐字语义重定位或另写三套 hash 绑定 |
| v3 状态记录、Set/Clear、视图及覆盖失效 | memory/state.py；generation/context/tools 消费合同 | 不复制 SceneState、不复用旧字段审批/merge 作新 reducer，不建 current_state.json 或规则 DSL |
| 事件线/经历/伏笔与派生邻接 | memory/graph.py；引用既有实体/关系原语与状态 ID | 历史经历只存 Experience；不另存知识/物品/Pending 当前值，不改 GraphReader 双端邻接语义 |
| 路由/因果包/显式容量 | memory/router.py，memory/service组合；显式容量复用estimate_tokens | 默认完整相关包无token上限；先可见图，有限必要依赖与来源去重，显式容量含完整返回结构；不复制五通道或建router LLM |
| 统一候选版本/持久批次 | generation/store；memory/state/graph 解释同一 StoredMemoryBatch | 单 memory_revision，批内 local_ref 一次解析；StateBatch 仅内部视图，不另建状态/事件日志 |
| RunBinding与输出组装 | generation/session，store保存选择结果 | BaseRef/父前缀唯一，full_body/append_suffix共用组装；原章只作修改参考，状态章前起步 |
| 文本增量与部分恢复 | model_api解码→generation回调→store→web观察 | 先保存后SSE；接收缓冲不推进Draft，完整turn后执行工具，部分内容明确冻结才作来源 |
| 分型来源与输入保留 | catalog/源读取解析Document；store解析Draft/Input | Hash按输入域，原输入不作正文事实；保护已发布InputRef的input-versions，无第二事实库 |
| 正式引用类型与一致源快照 | documents 定义 DocumentRef/源解析；catalog/service 复用；generation/types 重导出 | 解析值/hash 同次读取；源 owner 不反向 import generation；旧 content 不配新 hash |
| 源提交/锁 | MutationCoordinator、ThreadMutationLock、FileMutationLock、source-only 工厂 | 不造新事务引擎，不把嵌套文件锁当重入，不宣称多文件全局原子 |
| 偏好 | onboarding 路径 owner，generation/CLI 委托 | 一个文风源，v3 空偏好可运行，v2 parser 保留 |
| 配置/模型协议 | ModelConfigStore、ModelProfile、normalize_mode、model_api turn | 不复制模式映射/循环；可选依赖延迟加载 |
| 笔记 revision/ownership 与 metadata 往返 | mutations/summary 原语，documents 负责结构，memory 解释 memory_batches | 同一批保存 Clear/事件/links；v3 必填来源/时点；编辑存 author_note，旧链置缺口；不覆盖 user ownership |
| R13 活跃提示与资源选择 | generation/context 的组装；tools 在唯一登记处读取实际条目 | 原本只作来源；范例/文风不进入事实索引，不整份注入 HTML/CHECK/修复协议 |

此表保留实施责任；实际公共接口已落盘并登记在 AGENTS 与下方8.8。完成证据见 IMPLEMENTATION_STATUS_AND_NEXT.md，不把设计示例或真实模型待办写成已验收。

### 根因、验证与回退

新 reference/context 解决占位模块、deprecated、12 条截取；turn/会话替代 stage/逐事件/原句锁；新采用替代 audit pass/清正文；既有 owner 装配 source-only，正文提交与笔记/索引解耦；运行 owner 替代 UI 取消标志及长期 reader。R13 适配保留事实/认知/条件与连续性，状态按情节变化记录；软件只验证结构、来源与生命周期，不识别人物撒谎或审批文风。

下方工作包/验收矩阵已对应实际源码和测试。采用受控本地 HTTP、临时 YAML/SQLite、真服务浏览器，覆盖取消/提交窗口、元数据-only 编辑、旧章缺显式 ID、A 已提交回执失败后 B 采用再重试 A 等路径；最终结果以状态文件记录为准。

状态 fixtures 使用已明确分类的记录，检查 World/claim/belief 分开、请求未兑现、Set/Clear/继承、scene/carry、纯追加/覆盖前缀改写/部分采用/分支恢复、章前知识与人物摄取时点、来源变化和旧工具结果失效。Summary 新 metadata 往返、user 编辑保护与 source-only 发布必须有真实保存检查。这些只能证明程序按声明管理记录；“LLM 是否记全重要设定、人物是否自然、正文是否更好”仍需实际输出和作者阅读。

图/router fixtures 覆盖隐藏/未来桥梁、跨章同线、同经历多线、旧约定已解除、借用条件不被预算裁掉、部分帮助剩余 Pending、伏笔再出现未兑现、替代解释未决、空图/旧章无记录、共享来源边际成本与稳定同分。候选超限显示 gap/原文入口，不自动总结或停叙事。同批新记录引用、CAS/来源错误整批拒绝、重试 ID 稳定和 source-only 保存应有临时库实证。可选 Dijkstra/DP 只有启用时才加受控路径/枚举对照，不把它们作为首版完成的前置功能。

正式文档新增的AC-V3-22/23及§12.1示例用于来源/调用夹具：三类引用按真正字节指纹核验；无正文作者计划不进事实图；保留输入后可恢复；同revision不同稿定位、继续前缀只拼一次、修改早章不带章末知识。流式HTTP夹具需验证已发布前缀持久化、工具参数片段不执行、回调保存失败、最终UI不重复追加，不只mock最终字符串。

通用模块实施后的门禁：

~~~powershell
python -m pytest -q -k "not test_file_lock_uses_windows_safe_exclusive_create_across_processes"
python scripts\run_retrieval_tests.py
python -m novel_rag.cli --library novel-rag validate
~~~

文档阶段的299/72/729是历史基线；本次实际首版检查为404 passed、1 deselected、90条既有兼容警告，retrieval 72/0、资料729/0。回退保留run、未决intent、版本备份和graph pending。

<a id="memory-reliability-plan"></a>
### 2026-10-10 记忆可靠性增量工作包（已实施，证据见状态记录）

用户显式调用design-review-council并已授权执行六个工作包。数据、语义、失效和并发合同只定义在[权威架构§7.9](HYBRID_GRAPHRAG_ARCHITECTURE.md#memory-reliability)；本节仅规定实施依赖、文件owner和证据。保持已有五工具、唯一Store/memory_revision、默认无token上限和v2兼容入口。六包已经落盘；完成门、独立QA与实际验收边界只以IMPLEMENTATION_STATUS_AND_NEXT.md本轮记录为准。

| 工作包 | 唯一实施责任及实际调用方 | 依赖与验收 | 回退/保留 |
|---|---|---|---|
| IMP-MEM-01 结构与来源资格 | memory/schema演进共同输入/落盘校验；config/documents委托；MemoryService核正文/计划来源。查复用state_entry_schema、validate_state_entry和graph字段/端点表 | 先交付可运行坏输入/坏容器及来源反例；AC-MEM-09，保留18项信息路径 | 旧无information/旧合法批次可读；保留原始坏容器供显式查阅，不自动修复作品 |
| IMP-MEM-02 一次快照与故事回放 | MemoryService组合一次源/父链/批次快照和共同回放；Store提供现有检查点/前缀证据；recall、normalize、AdoptionService消费同一入口 | 01；AC-MEM-03及11中的读取一致性。采用映射前保留顺序；确认未来ID与已折叠旧序的边界 | 不重写原始批次；旧不可比较位置留下来源与缺口，不以到达序兜底 |
| IMP-MEM-03 冻结发布与来源存续 | DraftStore保护确切批次/来源版本；AdoptionService演进prepared intent/publication binding；SummaryWriter仍唯一保存summary；state/graph消费失效效果 | 02；AC-MEM-01/02/05。先冻结再提交/发布，异常逐窗口恢复；覆盖删除、损坏、author_note、原run清理与新run | 正文已采用不撤销；失败memory_pending；保留绑定/快照/input-versions/source-versions；无证据旧源保守缺口 |
| IMP-MEM-04 效力revision与CAS | MemoryService协调同一效力签名；DraftStore保持唯一原子提交/幂等表；源协调器沿既有锁域；generation/tools.py与session.py共同调整工具外层持锁，保留取消/终态提交保护 | 02/03；AC-MEM-04/11及05提交后未知回执。父纯追加不误升；复读不反复升；从实际native/harness入口验证源锁→Store锁 | 无第二版本计数器/提交日志；旧回执可追溯，不冒充当前效力；不自动重发未知POST |
| IMP-MEM-05 必要依赖、选择与覆盖 | graph保留不可遍历的依赖缺口；router在访问截断前处理直接焦点；state/MemoryService给覆盖/解除入口；context/harness/web消费同一包 | 03/04；AC-MEM-06/07/08；复验既有隐藏桥、事件/伏笔、显式容量和before/after信息测试 | 保留有界BFS/默认无token上限，缺口不阻断写作/采用；不增加配额、自动传播或文学报表 |
| IMP-MEM-06 人物身份兼容增量 | MemoryService/schema同remember可选未定身份声明与local_ref；DraftStore/批次保留身份；catalog/aliases继续正式身份owner | 01–05后实施；先核旧字符串输入/调用方，再定新增输入Schema并验证AC-MEM-10身份部分 | 原四字段information保持；旧ID不静默改挂，同名不合并；无allocate工具或第二知识表 |

实际公共API登记见AGENTS.md与下方§8.11；工作包名称仍是实施责任。所有新增能力先核既有owner；没有另拆memory框架。source角色与状态/图语义归原owner，容器层不解释人物或因果。

实施开始时记录本轮实际diff与资料身份，逐包完成最小有效回归，新增/修改函数按AGENTS写依赖/输入/输出/实现四项注释。关键验收使用真实临时库与prepare→save_draft→remember→adopt→新run，不能只把stale对象手动传给reducer代替丢失容器路径，也不能只检查工具Schema。故障测试控制保存/提交窗口，不调用付费模型。

核心完成门：AC-MEM-01–09/11及既有信息路径通过，再运行AGENTS三道门并由非实现者复核受影响反例。IMP-MEM-06完成后才宣告AC-MEM-10身份部分通过；本轮已有学校/媒体渠道仅代表结构、保存与装配证据。最终状态记录每个工作包实际diff、通过证据、残余迁移边界和下一步；不把设计定稿、旧461基线或审查共识写成后端修复完成。

<a id="v3-implementation"></a>
### 可执行工作包与交付顺序

本节保留已确认架构的工作包定义；标“新增/计划”表示当时规划，实际文件和执行证据已进入状态记录。数据形状、工具及HTTP合同引用权威架构；本节不把AC-V3-09的作者阅读待办混入程序完成。

~~~mermaid
flowchart LR
    P01["01 纯合同与装配边界"] --> P02["02 源读取/游标"]
    P02 --> P03["03 状态/事件只读投影"]
    P03 --> P04["04 router/context"]
    P04 --> P05["05 持久化基础"]
    P05 --> P06["06 原生模型turn"]
    P05 --> P07["07 remember整批提交"]
    P06 --> P08["08 唯一会话/CLI"]
    P07 --> P08
    P05 --> P09["09 source-only源提交"]
    P07 --> P10["10 采用/记忆发布"]
    P08 --> P10
    P09 --> P10
    P08 --> P11["11 本地网页"]
    P10 --> P11
    P11 --> P12["12 主入口/作者阅读"]
~~~

默认按 01→12 开发；06/07/09 在 05 完成后可分别推进，但 composition、generation/types、documents、公共导出与依赖配置由主实施者串行收口。分配的是文件/职责，不允许多人在共享文件里各建一种合同。

| 工作包 | 里程碑 | 必需前置 | 唯一责任与主要文件 |
|---|---|---|---|
| IMP-V3-01 | M1 | M0 | 纯正式引用：documents.py；运行/草稿/输入合同：generation/types.py；装配：composition.py、包 __init__.py |
| IMP-V3-02 | M1 | 01 | 源读取/游标：service.py、catalog/corpus.py、catalog/paths.py、catalog/timelines.py、documents.py |
| IMP-V3-03 | M1 | 02 | 新增 memory/state.py、graph.py；只读组合入口 memory/service.py |
| IMP-V3-04 | M1 | 03 | 新增 memory/router.py、generation/context.py；资源读取由 tools 的唯一登记处接续 |
| IMP-V3-05 | M3-a | 01–04 | 新增 generation/store.py；原子写原语由 mutations/coordinator.py 公共化 |
| IMP-V3-06 | M2 | 01、05 | model_api.py 原生 turn/流解码；pyproject.toml 可选依赖与现有 model_config 适配 |
| IMP-V3-07 | M3-b | 03、05 | memory/service.py 校验整批；state/graph 解释差分；store 保存同一批次与幂等结果 |
| IMP-V3-08 | M2/M3-b | 04–07 | 新增 generation/session.py、tools.py；composition.py、cli/arguments.py、commands.py 接新 write |
| IMP-V3-09 | M4 | 02、05 | mutations/coordinator.py 锁内挂接点；composition.py 明确 source-only 工厂/策略 |
| IMP-V3-10 | M4 | 07–09 | 新增 writeback/adopt.py；mutations/summary.py、documents.py；store 来源保护/发布映射 |
| IMP-V3-11 | M5 | 08、10 | 新增 web/app.py、web/static/；CLI workspace 仅启动同一应用服务 |
| IMP-V3-12 | M6 | 01–11 | composition/CLI/README 的主入口说明；状态文件中的实际章节与作者反馈证据 |

#### IMP-V3-01：先建立纯合同和显式装配边界

参考：[目录与依赖](HYBRID_GRAPHRAG_ARCHITECTURE.md#implementation-layout)、[RunBinding](HYBRID_GRAPHRAG_ARCHITECTURE.md#run-binding)、架构 §6/8.1。

- documents 定义正式 DocumentRef 的纯值类型；generation/types.py 引用/重导出并组成来源 Union，添加 RunBinding、BaseRef、DraftRef、AuthorInputRef 及运行错误，不复制正式来源类型。ModelTurn/ToolCall 属于 model_api 的模型协议责任，在06实现；状态/事件领域类型仍归 memory。现有 Model、GenerationError、STAGE_INSTRUCTIONS 保留；纯类型不导入 session/store 或 optional web/network 库，model_api 不反向依赖生成业务。
- composition 显式分开 v2 与 v3 工厂；新入口延迟 import v3 runtime。检查 generation、writeback、CLI 的包导出及同名 module/package shim，保留旧转发，不能把安装 web extra 变成 v2 导入条件。
- 输出证据：基础安装以独立进程分别先 import service、documents、catalog 与 model_api/旧 CLI，旧 stage Callable 保持；v3 缺依赖返回具名 capability 错误。service 不能顶层 import generation.types，否则当前 generation.__init__→helpers→service 会闭环。先固定版本/schema 边界，再写运行实现，不创建临时 MemoryBatch 或同义 SceneState。

#### IMP-V3-02：让本书原文在无索引时也能读

参考：架构 §7.5/8.1/12；AC-V3-01/07/14/22。

- 在 service.py 的现有加载责任内新增显式 v3 source-only 入口/策略。继续校验本书身份、物理布局、文档 schema、重复 ID、timeline 注册及 lineage；不让无关旧 shared/module-map/version-map 阻断本书原文。现 load_valid_documents 即使 include_shared=False 也校验 module/version maps，不能把这个参数当成 v3 接入已经完成。
- catalog/corpus.py 将 _document_coordinate 公共化并保留原调用委托；复用 StoryCoordinate、ValidatedCorpus.for_graph、timeline cutoffs、aliases/path owner。search/read/recent/state 共用范围选择结果，新增 before/after 游标过滤，不各写一套时点比较。解析失败显示 source_invalid；旧无时点资料标覆盖缺口。
- 在 documents 的原读取/解析责任内提供同次字节源快照，供 catalog/service 和 summary owner 复用；正文、metadata、引用及 fingerprint_bytes 来自同一份实际文件字节，不在解析后另读新文件 hash。指纹仍复用 mutations/types 的既有实现，避免 documents 顶层 import mutations 包触发 summary→documents；可在运行函数内延迟依赖或由调用方计算同份字节指纹，不复制哈希算法。DocumentRef 用完整 YAML 指纹和实际来源 scope；通过 catalog ID 解析最终路径、校验符号链接及归属。源变化后下一次读取返回新引用；测试 read→外部修改后，旧快照 hash 不能为新源背书。索引缺失/旧模块损坏与本书原文损坏分别测试；无图不自动建图。
- 交付真实临时 corpus 用例：两作品、父子/兄弟线、分歧前后、common、早章 revise、同名实体；同一源结果可送给 read_document 和记忆投影。此阶段仅正式源可运行，草稿解析接口等待 05 注入，不造内存版生产 Store。

#### IMP-V3-03：实现唯一状态 reducer 与事件只读图

参考：[状态合同](HYBRID_GRAPHRAG_ARCHITECTURE.md#state-memory)、[记录与链接](HYBRID_GRAPHRAG_ARCHITECTURE.md#event-records)；AC-V3-10–15/18/20。

- memory/state.py 解释有序变化批次，分开 World、CharacterView、OpenCondition，Persona 只读，Continuity 由同一条目派生。Set/Clear、scene/carry、摄取时点、失效 key 和 coverage/gaps 在这里处理；不调用旧 _deep_merge/state-approve，不保存第二个 current_state 文件。
- memory/graph.py 解释 EventLine、唯一 Experience、Hook、Note、Link 的低权威记录。成员/参与者/铺垫/状态引用由 Link 派生，拓扑仅存一次；一个 Experience 可连多条事件线，别名不自行合并 unresolved 身份。plans/claims 与事实投影保持性质，图距离不产生人物知识。
- memory/service.py 组合正式来源、Summary 容器与投影；先经 02 的可见范围/有效来源过滤，再建立诱导图，不能先 GraphReader.neighbors 多跳后删除隐藏结果。覆盖不完整时仍给原文入口。M1 用临时 YAML 中真实保存的批次检验读取，不声称已有模型抽取或正式写入。
- 最小反例：Set 后 Clear 来源失效不复活旧值；事实第一章存在但人物第三章获知；技术 run 结束不完成请求或切场景；隐藏节点不能连接两个可见节点；重复 recall 不产生新历史。

#### IMP-V3-04：用小参考包组装真正模型输入

参考：架构 §4.1/7.7；AC-V3-01/15/16/18–20。

- memory/router.py默认有界BFS、必要依赖闭包、稳定顺序和完整包去重并集。默认无token预算；显式容量的贪心兼容路径核验完整返回结构。整个包纳入或返回gap/原文入口，不因causes、邻接或单选explanation确认因果/答案。
- generation/context.py保留原始大纲、要求、完整明确基线及召回得到的相关参考/版本；默认无12000/2048额度。复用原文搜索命中而非遍历全库注入全文；显式上下文容量不足报context_limit并保留输入，不静默省略memory。内置会话也取消每turn12000守卫。
- R13 只装配已选语义及实际资源内容；写法/范例不进事实记忆。资源 ID→内容由唯一登记处读取，未提供完整原书不能声称已读。工具登记在 08 合并到 generation/tools.py，context 不另留一份工具/资源名分发表。
- 交付原始输入→临时源→最终 messages 的检查；图为空仍含近期原文并显示缺口，借用条件/解除/剩余 Pending 不被切半。首版不实施 Dijkstra/DP；将来启用时沿原 router 内策略增加路径/枚举对照，无新服务或模型。

#### IMP-V3-05：先把 run、草稿和结果保存可靠

参考：架构 §6/7.4/7.6/8/10；AC-V3-04/05/13/21–23。

- 从 mutations/coordinator.py::_atomic_write_json、_stage_changes 的既有临时文件/flush/fsync/replace 逻辑公共化最小字节/JSON 写入口，旧 Coordinator 委托。mutations/changes.py 仅兼容导出；model_config/store.py 的凭证权限写入保持其安全语义。公共化后追踪 Coordinator、store、adopt 的调用并同步 AGENTS 实际清单。
- generation/store.py 保存固定 RunBinding、请求文本槽、独立 received 快照、不可变正文修订/checkpoint、分支父关系、原始 StoredMemoryBatch 和调用结果。统一 store 锁内核验 expected_revision/memory_revision；正文文件先落盘，再让权威运行快照引用它，孤立文件不能被误读成成功修订。
- 批次、版本、稳定 ID/local_ref 映射及可恢复幂等结果必须进入同一权威保存单元；外部 tool-results/展示回执失败不能把已提交批次变成未知或再写一次。优先沿 run.json 的版本化运行快照表达；展示文件只作派生追溯，不加第二 journal。先识别同 run+call_id 的已保存参数 hash/结果，再判断新 CAS；同 ID 不同参数返回冲突。
- received 与 DraftRef 分开：保存过的 partial 不推进正文 revision，作者明确保存/继续才冻结。检查点保存真实正文 UTF-8 hash；追加只验证已覆盖前缀字节，改写保守失效。同 revision 两份正文通过 draft_document_id/checkpoint 唯一定位。三类引用按各自实际字节核验。
- 用真实临时目录、故障点和新 Store 实例检验：正文文件落盘但运行快照失败、批次落盘但回执失败、接收快照失败、重启 interrupted、选父前缀/兄弟分支、已覆盖前缀被改写。此包先闭合保存原语与版本边界，完整 session 行为在 08 收口。

#### IMP-V3-06：接原生工具协议和文本流

参考：架构 §6/10；AC-V3-02/05，保留 tests/test_model_api.py、test_model_config.py 的兼容回归。

- 在 model_api.py 演进异步 complete_turn；chat/responses 仅在协议编解码处不同，共用上层循环。保存实际 call_id、公开 content_blocks、必要 continuation、finish_reason/usage；公开 delta 拼接必须等于完整 turn.text，不把隐藏 reasoning 当正文。
- HTTPX 客户端负责等待响应头、分块读取、取消、超时、重试等待及 response/client 关闭；callback 由 generation 注入并 await。工具参数片段只累积，到完整 turn 持久化后才执行。已经收到部分正文时不得自动重发；网络/协议/保存错误分开保留恢复内容。
- FastAPI/Uvicorn/HTTPX 放 web 可选组并延迟加载。实施时验证 Python >=3.10 的兼容依赖范围；基础环境检查 v2，装有 extra 的独立环境检查 v3。依赖版本未在本次文档阶段安装/确认。
- 使用真实本地 HTTP 分块服务器连接模型客户端与 05 的磁盘 sink：两协议至少走一轮工具返回后终稿，并测非流式、混合文本/工具、截断 JSON 参数、头部等待取消、流中断、保存失败。断言观察到的文本可由新 Store 恢复，不能仅 mock 最终字符串或记录 callback 次数。

#### IMP-V3-07：remember 作为一次整批记录

参考：架构 §7.2/7.8/8.1；AC-V3-10–13/17/21/22。

- memory/service.py 在一个调用内校验来源/分支/CAS、所有 Set/Clear 与 RecordWrite、local_ref 和 Link 类型，完成稳定 ID 规范化后才交 store。非法端点、悬空引用、纯输入假装正文事实、来源失效及版本冲突都整批拒绝；此前保存正文保持可读。
- 保存一个 StoredMemoryBatch，再由 state/graph 重建视图；StoredStateBatch 是内部视图，不独立落盘/计数。scene_boundary 可零变化声明，人物摄取默认检查点末端；source/baseline 失效推进同一版本，并保留 Clear 失效链的缺口。
- DraftRef 仅接受本分支/明确父前缀的有效检查点；AuthorInputRef 只支持计划 Hook/Note 及计划 links。读工具历史不直接重灌当前状态；旧 continuation 含失效项时由 08 建新 attempt 上下文。保持单创作模型，无 observer 或补记模型。
- 直接从真实 Store 恢复一个同批状态/经历/伏笔/local_ref/Link 的结果；回执失败后相同 call_id/参数复用原版本及 ID，先查成功结果而非用旧 expected_revision 再报冲突。改变参数必须拒绝；同包 update Link 后所有派生成员一致。

#### IMP-V3-08：形成唯一会话循环和第一条创作实证

参考：架构 §5/5.1/6/10/12；AC-V3-02–05/13/16/23。

- generation/session.py 唯一完成 start/feedback、context→完整 turn→工具→下一 turn、结束/取消/恢复。generation/tools.py 在同一登记处定义五个工具及 handler。完整 turn/工具结果先持久化；副作用前后检查取消。工具失败作为具体结果返回，不启动文学 repair 或另一模拟 JSON agent。
- session 唯一按 full_body/append_suffix 组装正文；save_draft 与最终保存复用规则。选父草稿只拼一次，前一正式章不拼进新章；revise 从章前状态起步，原章只作 edit_reference。中间工具 turn 的文字是过程，最终无工具文本才保存目标稿；discuss 只进会话。
- 每个模型回调绑定 run/attempt/turn/BaseRef；先 store 后观察事件。作者编辑采用 CAS，迟到结果只保存独立生成稿，不移动作者版本；UI 切书不改变 run scope。取消等 transport/callback/worker 清理后释放单创作槽，SSE 断开不等于 cancel，未知请求不自动重发。
- composition 将源/投影、Store、模型、工具注入同一 RunService；同步资料工作进入受控 worker，Reader 在其所在 worker 创建/关闭。新增 CLI write 仅调用该服务，顶层创建异步循环。generate/continue/confirm/state-* 及 package shim 保持 v2。
- 首条可运行交付：临时本书 YAML→新 write CLI 子进程→本地受控原生工具 HTTP→recall/read/save/remember→终稿/checkpoint→新 Store 恢复，History 字节未变。它证明软件链路，不称为真实 provider 或文学效果通过。单次直接终稿也能零记忆工具调用完成，不强迫写状态表。

#### IMP-V3-09：在既有源锁里增加 source-only 提交

参考：架构 §9/10；AC-V3-06/07/17。

- composition.build_mutation_coordinator 当前正式策略拒绝空 affected_graph_keys；新增显式 v3 source-only 工厂/策略，复用同一个 MutationCoordinator、源锁路径、staging 和目标文件指纹。校验本书目标源，退出整库 module/graph build 的写前条件，v2 默认仍拒绝 YAML-only。
- Coordinator 增加可选锁内预提交挂接点，默认无动作；使恢复 intent、核验/备份、写 durable intent 与 stage/validate/单文件 replace 同属一次 FileMutationLock 获取。adopt 的进程内 ThreadMutationLock 覆盖整次采用/回执整理，禁止外层再取同路径文件锁或依赖 _owned 重入。
- 用真实工厂/Coordinator、临时 History YAML 与锁对象验证 source-only 成功，无索引也能提交；备份/验证/replace 前失败源不变。原 test_mutation_composition_rejects_yaml_only_changes 继续验证 v2 的拒绝；mock coordinator 接空 keys 不算接入完成。只扩展本路径，不泛化成多文件原子提交框架。

#### IMP-V3-10：作者采用与参考发布分开收口

参考：架构 §7.4/7.6/8/8.1/9；AC-V3-06/13/17/21/22。

- writeback/adopt.py 在 09 锁内恢复目标未决 intent，核验目标完整文件指纹、旧源完整备份、草稿检查点及 operation_id 参数；正式提交仅一个 History 文件，adoption_id/正文同文件。既有 document_id/坐标保持，旧缺 ID 由源 owner 固化稳定身份；正文 hash 与完整文件 hash 分域。
- 恢复只按三种实际结果：身份/adoption_id/正文 hash 匹配→adopted；仍为 expected_source_hash（含原本不存在）→未提交，不自动重放；其它→冲突并保留 intent。A 已提交回执失败时，新 B 采用前必须先记实 A；之后重试 A 不用 B 的当前源误判 A 未提交。
- 正文已提交后发布可映射候选。summary owner 原容器保存 memory_batches/metadata 与 ownership/revision，显式 source-only；不调用 state-approve。SummaryEditor/Writer 直接使用02同次字节快照的 expected hash，或将读取/ownership/revision核验置入既有源锁；不能先读取旧内容再 fingerprint_file 新文件。新目标显式 MISSING_FINGERPRINT，原 revision/user ownership 保护适用于 v2/v3 共同调用方，不在 web 另造写路径。
- 作者编辑 content 同步保存 author_note，旧投影及依赖链失效，历史批次保留。发布只映射完整保留的同起点检查点前缀，改写/中段搬移/基线目标改变不硬配。受控交错覆盖：读后作者编辑、auto发布与user接管、双方创建同一新目标；后提交方必须冲突而非覆盖。
- 发布 AuthorInputRef 前先保留精确输入文本至 input-versions 并核验；source-versions 保留原 YAML 字节。版本来源可在 run 清理/作品备份后回读，不靠原 run.json 永存。保留/笔记保存失败返回 adopted+memory_pending；重试同 ID/来源，不撤销正文，不额外调用模型总结，空候选直接结束。
- 交付真实保存/重启矩阵：双击、并发修订/创建、元数据-only 外改、旧 ID/revision、新 B 后重试 A、源备份失败、笔记失败、user ownership、仅 content 编辑、输入版本保留失败、部分采用。旧 v2 图按既有语义 stale，显式重建后可读新 History；采用不等待图回归。

#### IMP-V3-11：网页只承接创作服务与恢复状态

参考：架构 §3/11；AC-V3-04/05/08/15。

- web/app.py 实现已定义 /api/v1 参数校验和 RunService/AdoptionService 调用，静态 HTML/CSS/JS 展示大纲、正文、编辑/采用及可展开来源/覆盖缺口。执行状态与 memory coverage 分开显示；partial/stale 不灰掉继续或采用。CLI workspace 启动同一个组合根，不在页面/HTTP 里另写工具循环或记忆策略。
- SSE 按持久化状态发布 seq，Last-Event-ID 重连，过期游标以快照接续；终稿替换相应预览，不能把全文再追加一次。编辑 revision 冲突保存作者输入，迟到生成可切换查看独立稿。停止显式 POST；关闭页面/断流观察仍可刷新恢复。
- loopback、同源 token/Origin、ID→路径及符号链接校验、纯文本渲染、profile 脱敏在真实边界执行。页面键盘焦点/编辑操作可用，错误带恢复动作但不清输入，不返回密钥/任意本地文件。静态资源不需要 Node 构建或桌面壳。
- 真 ASGI/Uvicorn 服务+本地受控模型端点验证 HTTP/SSE 的磁盘前缀与事件顺序，再以真实浏览器完成输入→工具创作→编辑→采用、停止→刷新→partial明确保存/继续、作品切换及重连。ASGI transport 用于参数测试，不替代 socket/SSE/浏览器验收。

#### IMP-V3-12：切主入口并留下作者能比较的作品

参考：架构 §12/13；AC-V3-09。

- 01–11 所需检查通过后，将 workspace/write 作为推荐入口；README 说明依赖组、配置复用、正文采用、恢复和回退。旧命令名称/结果 schema 不静默改成 v3；保留旧风格资料、未提交改动、intent、版本备份和 v2 pending。
- 用固定大纲、参考、实际模型/参数记录至少一条目标章节的真实输出、调用/耗时/用量和作者阅读反馈。模型调用遵循当时授权；缺真实 provider/作者反馈就在状态文件写待验证，不用本地 fixture、299/72/729 或结构化记录成功冒充效果提升。
- 文学效果由作者反馈判断，技术检查只验证保存/隔离/来源/恢复。回退关闭新入口，保留 v3 工作产物，必要时显式重建 v2 图；删除旧 pipeline/style 资料另列真实调用方清单和授权，不搭车实施。

<a id="v3-acceptance"></a>
### 验收分配与最小检查

下表只分配 [架构 §13 的验收](HYBRID_GRAPHRAG_ARCHITECTURE.md)，不新增文学规则。AC 的正式含义以架构为准。03/04 的纯读取测试、05/07 的保存测试、08 的真实循环、11 的网页分别观察不同边界，不能互相替代。

| 架构验收 | 主工作包 | 计划检查与实际观察点 |
|---|---|---|
| AC-V3-01 | 02/04/08 | test_memory_context：真实 YAML/原始大纲/选定参考进入实际最终请求；无占位与二次截取 |
| AC-V3-02 | 05/06/08/11 | test_model_turn、test_writer_session、test_web_api：两协议原生帧→磁盘增量→观察事件→完整turn/工具→最终稿 |
| AC-V3-03 | 08 | test_writer_session：记录实际 HTTP 请求，默认无旧 stage/repair 循环；终稿存在、History 字节未变 |
| AC-V3-04 | 05/08/11 | test_writer_session、test_web_api：迟到响应与作者新 revision、固定 scope、独立生成稿 |
| AC-V3-05 | 05/06/08/11 | test_run_store、test_run_recovery、test_model_turn：头部等待/断流/保存失败/取消释放；新实例恢复真实前缀 |
| AC-V3-06 | 09/10 | test_adoption_v3、实际 composition/Coordinator：并发/双击/元数据外改/缺ID/源replace后回执失败/A→B→A |
| AC-V3-07 | 02/09 | test_memory_cursor、test_composition：坏旧模块/无索引可读有效本书；坏本书报错，lineage/作用域隔离 |
| AC-V3-08 | 11 | 真服务浏览器：输入→创作→编辑→采用，停止→刷新→恢复，键盘路径 |
| AC-V3-09 | 12 | 实际章节产物与作者反馈；缺 provider/评读时单列待验证 |
| AC-V3-10 | 03/07 | test_memory_state：显式 world/claim/belief、持有人及不对称关系往返；不声称自然语言分类正确 |
| AC-V3-11 | 03/07/08 | test_memory_state：请求/承诺/尝试/计划阶段，技术运行结束不转移、不产生知情 |
| AC-V3-12 | 03/07 | test_memory_state：真实批次 Set/Clear/继承、零变化 scene 边界、scene/carry、Persona 不变 |
| AC-V3-13 | 05/07/08/10 | test_run_recovery、test_adoption_v3：追加/前缀改写/部分采用/搬移/分支/旧continuation/CAS/幂等 |
| AC-V3-14 | 02/03/08 | test_memory_cursor、test_writer_session：早章章前状态、摄取末端、检查点/父线cutoff/旧未知时点 |
| AC-V3-15 | 03/04/11 | test_memory_context、test_memory_state、网页：来源/recorded_through/gaps 真实可见，失效Clear不复活，仍可写作 |
| AC-V3-16 | 04/08 | test_prompt_resource_assembly：实际 messages/资源内容，无强制 CHECK/九项报表/Guidance复查 |
| AC-V3-17 | 07/09/10 | test_summary_mutations、test_adoption_v3：新 metadata/YAML批次往返、content编辑后author_note、source-only、memory_pending |
| AC-V3-18 | 02/03/04 | test_memory_graph、test_memory_router：先可见诱导图，隐藏/未来节点不桥接，不把距离当知情 |
| AC-V3-19 | 04 | test_memory_router：完整必要依赖包或未选+gap；共享前因去重，最终结构预算可复算 |
| AC-V3-20 | 03/04/07 | test_memory_graph、test_memory_router：跨章同线/同经历多线/物品召回旧伏笔，重复提及/回读不自动兑现 |
| AC-V3-21 | 05/07/10 | test_run_store、test_memory_state/graph：同批local_ref/稳定ID/Link更新、整批拒绝、磁盘提交后回执丢失 |
| AC-V3-22 | 02/05/07/10 | test_run_store、test_adoption_v3：三类来源真正字节/hash、计划不入事实、保留输入后发布、run移除后仍回读 |
| AC-V3-23 | 05/08 | test_writer_session、test_writer_cli：同revision两稿身份、父前缀唯一组装、正式前章不拼新章、revise/迟到编辑 |

测试文件是目标划分；若一个实际 fixture 已覆盖多个 AC，复用并登记，不为每个 ID 复制测试。共享夹具只保留实际需要的三类：规范临时 corpus、本地原生协议 HTTP 端点、带 barrier 的真实持久化故障。优先从现有 composition/identity 测试提取构造能力，不把旧 generation 的空 legacy DB 当 v3 资料库。HTTP 预期帧独立编写，不能调用生产 codec 生成自身“预期”；断言读取磁盘/实际请求，不只看返回的 persisted/complete 字段。

阶段窄集如下，全部为对应实现落地后执行的计划命令。异步测试可在普通测试函数内 asyncio.run，不仅为此引入测试框架。

~~~powershell
# M1：正式源、投影与上下文
python -m pytest -q tests/test_memory_context.py tests/test_memory_cursor.py tests/test_memory_graph.py tests/test_memory_router.py

# M3-a：真实 store；随后 M2 的 transport/循环/资源
python -m pytest -q tests/test_run_store.py
python -m pytest -q tests/test_model_turn.py tests/test_writer_session.py tests/test_prompt_resource_assembly.py tests/test_model_api.py tests/test_model_config.py

# M3-b：状态、故障恢复与 CLI 子进程
python -m pytest -q tests/test_memory_state.py tests/test_run_recovery.py tests/test_writer_cli.py

# M4：真实源提交与 summary；保留 v2 锁语义
python -m pytest -q tests/test_adoption_v3.py tests/test_summary_mutations.py tests/test_mutations_coordinator.py tests/test_mutation_lock_pending.py -k "not test_file_lock_uses_windows_safe_exclusive_create_across_processes"

# M5 API 参数/真实 HTTP；另外记录真服务浏览器验收
python -m pytest -q tests/test_web_api.py

# M6 兼容窄集；随后公共模块三道门
python -m pytest -q tests/test_cli_legacy.py tests/test_generation_cli.py tests/test_resume.py tests/test_writeback.py tests/test_model_config.py
~~~

基础安装与 web extra 使用两个隔离环境验证已安装包：基础环境以 python -I 检查导入/CLI help/doctor/validate，web 环境运行新 turn/CLI/HTTP。记录实际 Python/依赖版本，避免工作区 sys.path 或开发环境已装 HTTPX 掩盖缺依赖。浏览器沿用已有 Playwright 能力；未安装的可选依赖与浏览器不在本轮文档阶段安装。

涉及公共模块的阶段收口仍须执行上方 AGENTS 三道门，窄集不能替代；排除的 Windows 跨进程锁用例单列“未验证”，API 并发测试不能冒充跨进程锁证据。旧 test_model_api/test_generation/CLI 的 opener/FakeModel/mock 回归保护 v2，不能当新 HTTP/恢复/browser 已验收。

<a id="v3-failure-matrix"></a>
### 故障、重试与恢复观察点

所有注入点用事件/barrier 和有限超时同步，收尾释放阻塞、关闭响应/服务/进程，不靠长 sleep 制造竞态。保存失败后核验真实权威文件：未变是未提交，已完整保存是提交事实，无法核验是未知；未知不盲重放。

| 实际中断位置 | 必须保留/返回 | 验证方式 |
|---|---|---|
| immutable draft 已落盘、run快照未保存 | 不推进可见revision，旧稿可读；孤立文件不当成功 | 新Store只从权威引用解析；同调用重新核验 |
| memory batch/幂等结果已提交，派生receipt/返回失败 | 恢复原ID/映射/结果版本；记录当前是否仍有效分开判断 | 销毁实例，旧expected版本重试同call；批次数/revision不增加 |
| 同call_id参数不同，或新调用CAS过期 | 冲突/整批不写，正文保留 | 比较批次/运行快照字节和原正文 |
| 响应头等待、UTF-8/协议帧拆块、未完成工具参数 | 取消可释放；参数未完整不执行 | 受控HTTP请求记录和handler执行次数 |
| SSE已见文本后断流/取消，或接收保存失败 | 已显示前缀可恢复；未完整turn保持partial；save_failed明确 | socket观察时检查磁盘，新实例读取；不自动重发同turn |
| 作者先保存新revision，旧模型块/终稿迟到 | 作者稿不变，旧run独立生成稿/partial保留 | barrier后放行旧响应，比较作者稿与分支引用 |
| SSE观察断开、Last-Event-ID重连/游标过期 | 创作继续；按seq接续或快照，终稿不重复 | 真服务HTTP与浏览器的独立网络连接 |
| source备份/intent/stage/validate/replace前失败 | 正式源未变，无伪adopted | 完整旧YAML字节/hash及intent状态 |
| History单文件已replace，runtime回执失败 | adopted事实可恢复，不能称未提交 | 新服务核验adoption_id/正文hash/旧源备份；A→B→A不覆盖B |
| pending intent当前源为原hash/已匹配/其它内容 | 未提交/已提交/冲突三分，未知不自动覆盖 | 实际正式源三组文件与新服务恢复 |
| History已提交，input-versions保留或summary保存失败 | adopted+memory_pending；不发布悬空输入，不丢唯一待重试快照 | 独立注入两处失败；重试同ID/hash并读取保存内容 |
| Summary读后作者改稿/user接管/并发新建 | 旧快照提交冲突；不替旧内容配新文件hash | 原SummaryEditor/Writer真实保存，barrier交错及MISSING_FINGERPRINT |
| 发布后临时run移除、作者只改summary content、原源改写 | 输入版本仍可回读；author_note/失效链有gap，不复活Clear前旧值 | 新loader/Store读真实YAML/保护版本；图从有效源重建 |

### 本轮实施文档评审裁决

按用户要求复用四个独立角色，范围是实施顺序、实际复用点、故障验收与维护成本。评审只读，主实施者将建议写入本文件；以下源码窗口尚未运行故障复现，不能记作已修复。

| 角色/问题类别 | 证据或具体反例 | 裁决与落点 |
|---|---|---|
| 架构：阶段依赖风险 | M2先接session/工具/流式、M3才做Store，会出现临时Store/双循环 | 采纳：M3-a前置，03/04只读真YAML，05真Store，06/07/08贯通；最终依赖已由架构角色确认 |
| 反例：提交成功回执丢失 | remember成功后旧expected版本重试，若先CAS就把成功当冲突 | 采纳：批次/版本/ID映射/幂等结果一次权威保存，查询旧提交先于新CAS；05/07新实例恢复 |
| 反例：正式源接入待实施 | 现composition拒绝空graph keys，Coordinator尚无锁内hook；mock绕过会遮住失败 | 采纳：09真实source-only factory/hook；10真实replace后恢复、A→B→A、input保留失败 |
| 实现验证：现有证据不覆盖新路径 | opener/FakeModel/CLI parser回归没有原生帧、磁盘恢复及socket/SSE | 采纳：保留v2窄集，新增真实HTTP/Store/CLI/browser及独立协议夹具；23AC有观察边界 |
| 维护：拟议类型归属导致循环 | service→generation.types触发generation.__init__→helpers→service | 采纳：DocumentRef下沉既有documents；01独立导入，02同次字节源快照；权威架构同步 |
| 维护：现有源码有Summary并发覆盖窗口 | Summary先读content/revision/ownership，后取当前file hash；新目标无不存在约束 | 采纳：02提供一致快照，10原owner用快照CAS/锁内核验、新目标MISSING；三组受控交错，v2/v3共用修正 |
| 文学效果：待验证 | 结构正确/受控端点不能证明重要设定全记住或文风改善 | 保留AC-V3-09的真实输出与作者评读；无文学评分、强制回顾或额外模型 |

### 证据、状态与下一包的交接

实施证据写回 [唯一状态文件](IMPLEMENTATION_STATUS_AND_NEXT.md#v3-status)，每个工作包只记录：改动文件/公共API及直接调用方、实际命令/退出码/环境、AC结果、关键产物位置、残余失败或未验证边界。失败从 run/attempt/turn/call_id/operation_id 定位，不另建审计平台；记录脱敏参数，不抄 API key 或无关私有正文。

阶段收口检查实际 Git diff 与资料清单，完成公共化后同步 AGENTS/去重记录。保留 v2 回归及源版本备份；回退只切入口，不能删 run/intent/source-versions/input-versions 或未提交工作。本轮文档验证沿用业务未变的299/72/729基线，不能登记为v3测试通过。

IMP-V3-01–11已实施并通过程序检查；12的主入口说明已切换，AC-V3-09真实模型/作者反馈尚待进行。继续时先读状态文件与实测，不重新采访已确认产品方向；不要求文学audit证明才能采用。

## v2 历史目标与记录

以下对应 [v2 归档](archive/HYBRID_GRAPHRAG_ARCHITECTURE_V2.md)，用于兼容链维护与追溯。

## 1. 重构目标

在不改变现有写作行为的前提下，把当前系统迁移到：

```text
YAML truth source
→ catalog validation
→ shared projection + per-GraphKey projection
→ five-channel retrieval
→ ContextBundle
→ generation
```

写入统一由 ChangeSet 和 MutationCoordinator 协调；用户仍可直接编辑 YAML，但直接编辑只会使相关图 stale，不会触发隐式重建。

## 2. 当前问题证据

行号随代码变化可能漂移，实施前应重新确认。

| 等级 | 当前问题 | 当前证据 | 工程后果 | 目标落点 |
|---|---|---|---|---|
| Critical | generation 直接依赖具体检索实现 | `novel_rag/generation/helpers.py` 直接调用 `search_isolated()` | SQLite、FTS 或图策略变化侵入生成核心 | `Retriever` / `ContextBundle` |
| Warning | 多套写入与回滚流程 | importers、state、writeback 分别处理写入、备份和重建 | 容易漏掉受影响图或形成部分回滚 | `mutations/coordinator.py` |
| Warning | Reader 与 Builder 混合 | `novel_rag/index.py` 的连接路径可能创建数据库并执行 schema | 查询拥有写权限，缺图可能变成空库 | `graph/reader.py` 与 `graph/builder.py` |
| Warning | helpers 已形成隐含子系统 | state、generation、importers、cli 的 helpers/commands 体积持续增长 | 新职责没有稳定归属 | 按阶段提取 contracts、projection、validation |
| Warning | 内容过期检测不足 | 现有索引未冻结强制内容 fingerprint | 手工编辑 YAML 后可能继续读旧图 | manifest + SHA-256 fingerprint |
| Warning | 当前布局没有 timeline 物理分支目录 | story 根目录同时承载全部资料 | 新分支加入后难以证明祖先区间与分歧后隔离 | `common/ + timelines/<id>/ + lineage cutoffs` |
| Warning | shared 索引生命周期不完整 | shared.db 的 builder、manifest 和反向依赖未统一 | shared 变化可能遗漏故事图 | SharedBuilder/Reader + module dependency set |
| Suggestion | shim 与一次性脚本边界不清 | 同名 module/package、机器私有路径和遗留 DOCX 依赖 | 维护者可能改错入口 | facade + `legacy_migrations/` |

## 3. 修复清单

### R1 — 生成依赖具体索引 `[guided]`

Symptom: generation 调用具体搜索函数。

Source: *Clean Architecture* — Dependency Inversion Principle。

Consequence: 任一检索实现变化都会传播到生成策略和测试。

Remedy: 在 `novel_rag/retrieval/types.py` 定义 `RetrievalRequest`、`Evidence`、`ContextBundle`，在 `service.py` 实现 Retriever；先由兼容适配器保持旧返回行为，再迁移 `generation/helpers.py`。这样 generation 只依赖稳定合同。

### R2 — 多套资料提交流程 `[guided]`

Symptom: state、writeback、importers 和 feedback 各自承担部分事务。

Source: *Refactoring* — Shotgun Surgery。

Consequence: 新图上线后，一个资料变更可能只更新部分派生物。

Remedy: 新建 `novel_rag/mutations/changes.py` 和 `coordinator.py`；调用方只构造 ChangeSet。Coordinator 先验证 staged YAML 并构建全部临时图，再提交 YAML 和逐图提升。这样失败状态可报告、可重试，同时不宣称不存在的跨文件全局原子性。

### R3 — Reader 带写副作用 `[quick-fix]`

Symptom: 查询路径可创建数据库或 schema。

Source: *Working Effectively with Legacy Code* — Seam Model。

Consequence: 缺图和损坏图难以测试，读路径权限过大。

Remedy: 在 `novel_rag/graph/reader.py` 使用 SQLite URI `mode=ro`，打开时验证 manifest、schema 和 fingerprint；创建表只留在 builder。这样读写边界可以独立测试。

### R4 — timeline 作用域依靠逻辑过滤 `[manual]`

Symptom: 当前 story 根布局没有分歧后独立目录和图。

Source: *Domain-Driven Design* — Bounded Context。

Consequence: 新 timeline 容易读到父线分歧后的可变状态。

Remedy: 目标布局使用 `stories/<story>/common` 与 `timelines/<timeline>`；旧布局的 canon/registry 默认映射到 common，其余剧情资料默认映射到 main。分歧注册表记录 parent、divergence_at 和 divergence snapshot；建图读取 common、受 cutoff 限制的祖先区间与目标 timeline，拒绝祖先分歧后的资料。

### R5 — 摘要没有可编辑生命周期 `[guided]`

Symptom: AI 摘要、用户修改和来源变化之间没有覆盖规则。

Source: *A Philosophy of Software Design* — Information Hiding。

Consequence: 自动重建可能覆盖用户整理，旧摘要也可能继续召回。

Remedy: 摘要保存为 timeline 下的 YAML，带 `ownership`、covers、source fingerprint 和 revision。AI 摘要可直接使用；前端通过带 expected revision 的 SummaryEditor 保存并切换为 user ownership。来源变化时只标 stale、不自动覆盖，也不把 stale 用户摘要自动送入生成上下文。

### R6 — shared 变化传播不确定 `[guided]`

Symptom: shared.db 与故事图之间没有完整依赖登记。

Source: *Clean Architecture* — Stable Dependencies Principle。

Consequence: 共享规则修改后，部分故事图可能看起来新鲜但实际引用旧模块。

Remedy: SharedBuilder 输出独立 manifest；module-map 建立 `module → GraphKey` 集合，故事 manifest 记录 shared fingerprint。任何已引用模块变化都使对应图 stale。

## 4. 允许与禁止

### 4.1 允许实施的区域

- `novel_rag/identity.py`
- `novel_rag/catalog/`
- `novel_rag/graph/`
- `novel_rag/retrieval/`
- `novel_rag/mutations/`
- generation、state、writeback、importers 的兼容调用点
- timeline/common 布局迁移器
- AI 摘要写入与前端编辑接口
- 对应 tests、CLI doctor/index 命令和文档

### 4.2 必须经过兼容层

- `search_isolated()`、`rebuild_isolated_indexes()` 保留签名并转发。
- `novel_rag/index.py` 可以保留 facade，但不再增加业务能力。
- 同名 shim 在调用点归零且完整测试通过后才能删除。
- 当前 story 根布局在数据迁移验收前继续可读；canon/registry 默认映射到 common，其余剧情资料默认映射到 timeline `main`，并服从 metadata 的显式作用域。

### 4.3 禁止事项

- generation、state、writeback、importers 直接访问 SQLite 图表。
- Reader 创建数据库、执行 schema 或自动重建。
- Builder 从自由文本猜实体、关系、别名或 Canon。
- 一个图读取另一个 story/timeline 的资料。
- 自动任务覆盖 `ownership: user` 的摘要。
- SQLite/trigram 缺失时静默进入弱化运行模式。
- 引入 Neo4j、ORM、向量数据库、DI 容器或运行时服务。
- 为清理失败而删除、放宽或跳过回归。
- 在架构迁移中顺带改变生成文本行为。

## 5. 分阶段实施

| 阶段 | 工作 | 完成门 |
|---|---|---|
| 0. 基线 | 记录完整测试、公开入口、两部故事检索回归和当前索引 | 命令与输出可复现，不依赖固定测试数量 |
| 1. 安装与身份 | `doctor`、GraphKey、路径校验、manifest、内容 fingerprint、只读打开 | SQLite/trigram 不合格时安装诊断明确；Reader 不建库 |
| 2. Catalog | common/timeline 规范化、lineage cutoff、legacy 根布局适配、引用校验 | 身份不一致、路径穿越、同级/后代/祖先越界引用全部拒绝 |
| 3. 投影 | SharedBuilder、GraphBuilder、临时图、回归、逐图提升 | 每个 GraphKey 独立构建；失败保留旧图 |
| 4. 检索 | 五通道、ConflictGuard、ContextAssembler、Receipt | 每条证据带来源和理由；无跨通道真相分数 |
| 5. 兼容 | 旧搜索与重建 API 转发 | 旧调用可用，新 API 不反向依赖旧私有函数 |
| 6. 调用迁移 | generation → CLI/TUI → importers/state/writeback/feedback | 应用层不直接访问 SQLite |
| 7. 写入协调 | ChangeSet、staged build、YAML 提交、逐图提升、pending 重试 | 图必须先验收；切换窗口 stale 拒绝生成 |
| 8. 摘要 | AI 写 YAML、前端编辑、ownership 与 stale | 自动摘要直接可用，用户版本不被覆盖 |
| 9. 布局迁移 | 建立 common/timelines 并迁移 main | 新旧结果回归一致，旧布局停止默认读取 |
| 10. 清理 | 删除零调用 shim，归档机器私有脚本 | 静态调用图、CLI 和完整测试均通过 |

每个阶段只进入一个新的稳定边界；helpers 拆分、目录移动和行为改变不得揉成同一批修改。

## 6. 验收证据

### 6.1 数据与 timeline

- [ ] common 只包含明确适用于全部 timeline 的稳定资料，不包含 current state。
- [ ] 每个 GraphKey 只加载 common、允许的祖先区间与目标 timeline。
- [ ] parent、divergence_at 和 divergence snapshot 有注册表验证。
- [ ] 祖先分歧后资料不得进入子图，祖先分歧前修订会使对应后代图 stale。
- [ ] 跨 story、跨 timeline、metadata 不一致和悬空引用使构建失败。
- [ ] 手工编辑 YAML 后旧图 stale，生成被拒绝并提示 index 命令。

### 6.2 图与共享模块

- [ ] SharedBuilder 和 GraphBuilder 都先构建临时文件并完成回归。
- [ ] 每张图单独原子提升；多图不宣称同时切换。
- [ ] shared 模块变化可列出所有受影响 GraphKey。
- [ ] Reader 只读，缺图或 manifest 不符时不创建空库。
- [ ] Windows 文件占用和失败重试有确定行为。

### 6.3 摘要

- [ ] AI 摘要以 YAML 保存并记录来源 fingerprint。
- [ ] AI 摘要无需批准即可进入 Temporal，但不成为 Canon。
- [ ] 前端通过 SummaryEditor 和 expected revision 生成新 revision 与 `ownership: user`。
- [ ] 来源变化不会自动覆盖用户摘要，stale 用户摘要不自动进入 ContextBundle。

### 6.4 检索与兼容

- [ ] Authority、Graph、Temporal、Lexical、Semantic 可独立测试。
- [ ] shared 资料通过 Authority 返回，不出现第六个 shared channel。
- [ ] 冲突按 fact type、timeline、时间、状态和 authority 处理。
- [ ] `token_budget=None` 使用配置默认值，非正显式预算被拒绝。
- [ ] 旧 API 在迁移期可用，删除前有零调用证据。
- [ ] 完整测试集和新增隔离、stale、冲突、误召回、预算回归全部通过。

## 7. Fix Summary

| Finding | Tier | Target | Action |
|---|---|---|---|
| 生成依赖具体索引 | guided | `generation/helpers.py`、`retrieval/` | 引入 Retriever 与 ContextBundle，旧入口适配 |
| 多套提交流程 | guided | `mutations/`、state/writeback/importers | 集中 ChangeSet、临时建图和逐图提升 |
| Reader 带写副作用 | quick-fix | `graph/reader.py` | `mode=ro` + manifest/fingerprint 验证 |
| timeline 逻辑隔离 | manual | `stories/`、catalog、registry | 迁移 common/timelines 与分歧注册表 |
| 摘要生命周期 | guided | timeline summaries、前端接口 | YAML revision、ownership、防覆盖 |
| shared 传播 | guided | shared builder、module-map | manifest 与 module → GraphKey 反向依赖 |

本文件的完成标准不是目录变得整齐，而是每项问题都能对应到权威架构中的一个稳定边界，并且每个阶段都有可重复的验收证据。

## 8. 通用模块去重记录（2026-08-22）

对
ovel_rag/ 生产代码做了一次"可复用但被多次建立"的专项扫描。以下重复实现已统一到唯一可维护模块；本节只记录事实，不改变架构合同。

### 8.1 已合并

| 重复逻辑 | 原副本位置 | 统一后归属 |
|---|---|---|
| GraphKey 强转（_coerce_key，3 份：builder / reader / ModuleGraphIndex.register 内联） | graph/builder.py、graph/reader.py、graph/types.py | graph/types.py::coerce_graph_key |
| UTC 秒级 ISO-Z 时间戳（_now，3 份） | graph/builder.py、graph/shared.py、
eedback.py | 	imeutil.py::utc_now_iso |
| 库根 YAML 指纹（rglob + 排除 index/.mutation-*，逐字符相同 2 份） | composition.py::_yaml_source_fingerprint、importers/helpers.py::_yaml_source_fingerprint | catalog/corpus.py::yaml_source_fingerprint |
| trigram MATCH 表达式构造与短词 LIKE 兜底搜索（reader / shared 两份完整搜索体） | graph/reader.py、graph/shared.py | graph/reader.py::search_documents（shared 导入复用） |
| Reader 新鲜度协议（_ensure_fresh 主体 + close/enter/exit/del 生命周期） | GraphReader、SharedReader | graph/reader.py::ensure_reader_freshness + _SQLiteReaderLifecycle |
| 原子建图提升协议（mkstemp → populate → accept 回归 → os.replace → 失败清理，约 55 行 ×2） | GraphBuilder.build()、SharedBuilder.build() | graph/promotion.py::build_and_promote_atomically |

### 8.2 复核后不合并（非真重复）

| 候选 | 理由 |
|---|---|
| legacy index.py 的 FTS 词项引用 | legacy chunks 表使用 unicode61 分词器，短词语义与 canonical trigram 路径**有意不同**；兼容层也不得新增能力（架构 §11.5） |
| composition._manifest_fingerprint（读库行） vs 
etrieval/service._manifest_fingerprint（读 manifest 对象） | 输入域不同，强行统一反而增加跨层耦合 |
| mutations/coordinator.py::_manifest_now | 返回 (ISO 字符串, epoch) 二元组且保留微秒精度，服务于 pending 锁 staleness 判定，语义不同 |

### 8.3 验证证据

- python -m pytest -q -k "not test_file_lock_uses_windows_safe_exclusive_create_across_processes" → 223 passed, 1 deselected
- python scripts/run_retrieval_tests.py → 
etrieval_cases=72 failures=0
- python -m novel_rag.cli --library novel-rag validate → 729 个有效文档, 0 个问题
- 提升锁测试的 monkeypatch 目标随协议下沉同步迁移至 graph/promotion.os.replace（行为断言不变）。
### 8.4 新建通用模块记录（2026-08-22 第二批）

随结构化投影补齐，以下通用能力首次建立唯一归属（此前不存在，属新建而非去重）：

| 能力 | 唯一归属 | 说明 |
|---|---|---|
| 故事注册表别名加载 |
ovel_rag/catalog/aliases.py::load_story_aliases | 
egistry/aliases.yaml 此前只有 service 校验、无统一加载器；builder 经 GraphBuilder(registry_aliases=...) 显式输入投影进 aliases 表（按 lineage 过滤、未知实体跳过） |
| 结构化关系格式 |
ovel-rag/templates/relationship-canon.yaml + documents.validate_document relations 规则 | metadata.relations 需非空 subject_id/relation_type/object_id；builder 既有投影直接消费 |
| shared 反向依赖验证工具 | scripts/verify_shared_dependency.py | P0-3 可重复验证：真实库上 dependent_graph_keys 确定性 + 引用反查完整性 |

同日已闭合：P0-3（脚本输出 shared_dependency=PASS dependent_graph_keys=2 zero_map_references=0）。草稿关系数据两份（status: draft，仅转录既有 canon 明确陈述）：overturned-world-fujimaru/canon/relationships/gilgamesh-shenqi-hui-draft-v0.1-draft.yaml、shirouxcile/canon/relationships/orpheus-moira-enhance-draft-v0.1-draft.yaml。
### 8.5 TUI 可用性批次新建的通用组件（2026-08-22 第三批）

| 组件 | 唯一归属 | 说明 |
|---|---|---|
| 确认口令判定 | 	ui/helpers.py::matches_word / confirm_word | 大小写不敏感；全部危险操作（YES/IMPORT/FEEDBACK/SAVE/CREATE/DELETE/APPROVE/REJECT/RETRY/EDIT）统一走此路径 |
| CJK 宽度对齐表格渲染 | 	ui/helpers.py::render_rows | unicodedata east_asian_width 计宽；检索/Feedback/Pending 人读输出唯一入口 |
| 目录列选 | 	ui/helpers.py::pick_file_from_directory | 零依赖路径浏览（数字进目录/选文件、.. 上级、回车取消、任意路径直采） |
| 任务 ID 建议 | 	ui/helpers.py::suggest_task_id | YYYYMMDD 当日自增，替代字面量 generation |
| 摘要列举 | 	ui/helpers.py::list_summary_documents | summaries 目录唯一列举入口 |
| 进度回调契约 | pipeline.generate(progress=…) / 
ebuild_graph_projections(on_partition=…) | 生产 API 扩展（默认 None 完全向后兼容）；TUI 经 lambda 透传，禁止管线内直接 print |
| 可降级交互会话 | 	ui/session.py::create_interactive_io | prompt_toolkit 为 tui extra 非必需依赖；无控制台/tty 自动回落裸 input；run_tui 仅在默认 input 时启用，注入契约不变 |

同批 M 级功能（部分批准 character_ids/include_world、检索过滤、局部重建、length minimum/maximum、Feedback examples/history_id、api-config timeout/retries/max_output_tokens——注意存储层键名为 	imeout 而非 timeout_seconds）均为既有生产参数的 TUI 透传，未新增第二实现。
### 8.6 全屏控制台批次新建的通用组件（2026-08-23 第四批）

| 组件 | 唯一归属 | 说明 |
|---|---|---|
| 规范 UI 状态 | `tui/console/state.py` | CanonicalUiState/JobState/BlockView/NotificationItem；六态符号表唯一归属 blocks.py，state::status_symbol/status_word 仅作委托投影；renderer 禁止直读业务对象 |
| ui.json 配置 | `tui/console/config.py::load_ui_config / validate_ui_config` | camelCase/snake_case 双写法归一；缺失/损坏回退默认并告警，不崩溃 |
| 主题 token | `tui/console/theme.py::build_style` | hex 全色 + ANSI safe 双套；组件零散颜色字面量禁止 |
| 转录环形缓冲 | `tui/console/blocks.py::BlockStore` | 定格块 + 活动行原位刷新；超限丢最旧整块；dirty 驱动重绘 |
| 后台任务线程 | `tui/console/jobs.py::JobRunner` | daemon worker + emit/progress/finish 事件投递；取消=协作标志（线程不可强杀，输出抑制） |
| UI 状态适配器 | `tui/console/adapter.py::ConsoleAdapter` | 业务事件→UiState 唯一翻译层；含 legacy 桥接 (input_fn,output) 泵——wizards/menu 函数零改动复用 |
| 状态条 segments | `tui/console/status.py` | 顶行/输入前缀/hint 三出口同源 CanonicalStatusState；无常驻 footer（F1 决议） |
| 转录着色 Lexer | `tui/console/widgets.py::TranscriptLexer` | 行前缀正则→样式片段；TextArea+SearchToolbar 公开 API 组合 |
| 浮层构建器 | `tui/console/dialogs.py` | help/procs/viewer/confirm/form 五类 Float 工厂；Esc 栈式关闭 |

接线决议：`menu._summary_menu/_pending_menu` 提升为公共 `summary_menu/pending_menu`（plain 与 console 共用）；`session._stdin_is_interactive` 增加公共包装 `stdin_is_interactive`。console 命令处理器为表现层编排（调用既有生产 API），不复制业务规则；`FlowExit` 已移除，流程内取消一律经桥接 KeyboardInterrupt → ⊘ 定格。

降级链：`novel-rag tui` 默认 auto（PT 可用+tty→控制台；否则/异常→经典菜单）；`--console/--plain` 强制。门禁三绿复核：pytest 284 passed、retrieval 72/0、validate exit 0。
### 8.7 TUI 缺陷修复与去重批次（2026-08-25 第五批）

去重与死代码清理：

| 项 | 处置 | 说明 |
|---|---|---|
| 第二套状态符号表 | 合并 | `state.py::status_symbol/status_word` 改为委托 `blocks.STATUS_SYMBOLS/STATUS_WORDS`；零引用的 `style_token_for_status` 删除 |
| ui.json 死旋钮 | 删除 | `density` / `overlay_width_percent` / `overlay_height_percent` 校验齐全但零消费，连字段、camel 别名、校验分支一并移除；未知键路径天然拒绝旧写法 |
| session 死标记 | 删除 | `input_fn.interactive_session` 无任何读取方 |

新建公共 API（同模块内私有提升，非第二实现）：

| 能力 | 唯一归属 | 说明 |
|---|---|---|
| CJK 显示宽度计算/截断 | `tui/helpers.py::display_width / truncate_display` | 由私有 `_display_width/_pad_display` 提升为公共 API；`console/status.py` 顶行与 hint 截断改按显示宽度（此前 `len()` 对宽字符失真） |

缺陷修复（行为变更点）：

1. `_sync_text` 光标保持：`set_document` 前保存旧光标位，非贴底时恢复——修复任务运行期间视口被进度刷新强制拽回底部的问题。
2. `adapter._event_finish` 的 `jobs.pop` 移入锁内——消除与 `snapshot()` 迭代的并发 RuntimeError 风险。
3. `dispatch` 异常网追加 `RuntimeError/KeyError`：后台满额（JobRunner 上限）不再穿透 accept_handler 崩溃全屏应用；`run_flow` 在 submit 抛错时给块头补 `✗ FAIL …未能启动` 行，消除悬空块头。
4. 桥接回答一律不写入 `~/.novel-rag/console-history`：`api` 向导等经 `secret()` 输入的密钥不再明文落盘；普通命令历史行为不变。
5. `_VerbCompleter` 参数路由重写：PathCompleter 把整段 text_before_cursor 当路径处理，原实现带动词前缀时永远补不出结果；现剥出参数段单独构造 Document 再委托，尾随空格即进入参数模式。
6. `close_overlay` 栈语义：仅当浮层栈清空才回落 command 模式并聚焦输入框，栈中仍有浮层时聚焦上一层。
7. `_pick_source` 手输路径即时存在性校验，不存在则提示并取消，而非等到 preview 才抛 FileNotFoundError。

### 8.8 v3 首版实际公共化与新增归属（2026-10-09）

下表登记本次已经落盘的能力，沿原模块归属；旧批次记录不改写。

| 能力 | 实际唯一owner与使用方 | 去重/兼容结果 |
|---|---|---|
| 同次源字节、DocumentRef与YamlSnapshot | documents；catalog/service/summary复用 | 不再旧内容配新hash；正式引用不反向依赖generation |
| 文档坐标与common判断 | catalog/corpus公共函数，旧私有包装委托 | 既有lineage算法保留，v3游标也消费同一坐标类型 |
| 词项与实体投影 | retrieval/service.safe_query_terms、graph/builder.normalize_entities；SourceCorpus.search/entities与context/tools复用 | 私有入口为别名；分块继续走chunk_text，不复制trigram或元数据提取算法 |
| 原子字节/JSON | mutations/coordinator公共原语；Store、onboarding、adopt复用 | UUID同目录temp→fsync→replace，失败只清自己的temp；旧staging/JSON调用委托 |
| 原始run/前缀与真正目标 | DraftStore；MemoryService/RunService/AdoptionService/Web消费 | 同一memory_revision与原始批次；selected父检查点、target_source_ref、源/input版本备份只此一处 |
| 单循环/正文拼装/工具 | RunService.assemble_output与ToolDispatcher | 五工具唯一登记；Web保存partial也走同一全文拼装；旧generate仍v2 |
| 状态、图、选择、整批记录 | memory/state、graph、router、service | 只读派生与统一remember；按故事来源顺序，未来先裁，完整包计实际边际成本，无路由LLM |
| 正式采用与作者编辑 | writeback/adopt + composition source-only factory | 原源锁/Coordinator hook；单History提交；新坐标不覆盖原章，笔记失败不撤正文 |
| summary与偏好生命周期 | 原SummaryEditor/Writer、onboarding；Web仅调用 | Source-only显式策略、双CAS、author_note/user ownership、旧原始批次保留；偏好使用同次旧bytes备份 |
| v3容器格式 | config.validate_memory_metadata，经documents旧summary入口调用 | 仅格式/来源形状；损坏容器作为gap，不引入状态审批或文学审查 |

最终完成门：404 passed、1 deselected、90条既有兼容警告；retrieval_cases=72 failures=0；729有效文档、0问题。真实Chrome/Edge/Uvicorn工作台流程也通过。具体故障、截图、来源资产指纹和实际provider/作者阅读待办见 [实施状态](IMPLEMENTATION_STATUS_AND_NEXT.md#v3-status)。没有安装服务、创建新向量库、删除旧数据、提交Git或调用收费模型。

### 8.10 写作体验续接与去重（2026-10-10）

沿权威架构§17 AC-UI-W01–08实施三项旧任务。workspace.js仍唯一管理API/CAS/SSE，本机记录仅为作者输入副本；bootstrap复用fingerprint_bytes派生稳定归属，不复制hash算法。scaffold.create_story共用CLI/TUI/网页，默认兼容，显式exist_ok核同意图；原owner复用read_yaml_mapping/FileMutationLock/atomic_write_bytes，网页只薄POST，不再建树/Store/事务/凭证逻辑。test_workspace_browser.installed_browser_path提升为公共测试能力，新增验收复用真实workspace_server/原建库夹具，不下载浏览器。

指定反例：dirty正文借最新revision、换run清正文、未知操作仅内存、无锁普通注册/失败残留；修复均在原owner。设置只提供本机指引/脱敏重读/外部工具，大纲优先并折叠低频项，保留Metro/原ID/持久DOM。实现、失败历史、当前输入身份与完成门沿IMPLEMENTATION_STATUS_AND_NEXT.md本增量，不拿历史443/461代替当前通过。

独立验收反例在同owner闭合：清理前重核库内范围/原目录物理身份与当前注册，未知归属保留；原生modal键盘先于Metro导航；首屏检查取全部滚动/裁切祖先的可视交集，不只比窗口高度。最终写作R2候选493/72/729三门和独立QA通过，同期记忆代码仅在隔离副本回到其实施前基线取证，共享源码未回退；共享整合门保留失败记录并由记忆实施流程续验，不称全项目完成。

### 8.9 Harness增量公共owner与验收（2026-10-09）

沿架构§15和用户授权实现，不另建PRD或新agent。四角色首评完成，架构/红队已定向复核。原404/72/729是首版证据；本次增量最终门沿实施状态更新，不把历史数值算本次通过。

| 实际能力 | 唯一owner/直接消费者 | 兼容与去重 |
|---|---|---|
| prepare/start与五工具执行 | RunService.prepare/tool_dispatcher/execute_tool；网页、内置CLI、harness HTTP | 准备不读profile，内置start保留原签名/旧请求hash；事件、结果、正文拼装和作者保护同源 |
| 外部上下文/技术结束 | RunService.harness_context/harness_tool/finish_harness；HTTP、CLI与MCP资源 | prepared不是外部model正在运行；source/记忆仍原owner；finish不审正文/不自动保存聊天 |
| 写者独占/旧回执 | DraftStore.writer_lease/committed_tool；后端lifespan与writeCLI/ToolDispatcher | 复用FileMutationLock/原tool_commits，无第二事务协议；Windows只读进程查询替代危险kill(0) |
| 可省略稿源的幂等参数 | MemoryService.remember_arguments→remember和ToolDispatcher.committed_result | 省略draft_ref与None同意图，恢复先于取消/终态，不复制默认值 |
| 模型可见记忆写入形状与状态校验 | memory/schema.draft_reference_schema/remember_update_schema/state_entry_schema/validate_state_entry；ToolDispatcher/native/MCP、MemoryService与config共同消费 | 组名/字段/方向来自graph常量，领域来自reducer；基础身份及可选information共用形状规则，来源/获知点仍由host绑定，不复制知识表或文学审核 |
| loopback HTTP/stdio | harness.BackendClient/McpStdioAdapter；CLI和外部宿主进程 | schema来自原registry；稳定operation_id为transport元数据；不缓存小说状态、不重试未知POST |
| 真后端测试夹具 | tests/native_http_fixture.workspace_server；旧browser alias与harness protocol/browser用例 | 将原socket helper公共化并委托，不复制服务器/引入测试框架 |
| Metro展示/磁贴/图片 | web/static/launcher.js、tiles.json、assets/manifest.json；index和现有workspace.js消费者 | 仅持久DOM显隐/焦点/展示计时，API、业务state/CAS/SSE沿原owner；CSS唯一样式，图片包含于wheel |

关键复现与修正：取消通过预检后排队仍提交→同锁；作者稿保护下换网络编号重复checkpoint→稳定操作ID；第二后端recover中断首后端→生命周期独占；坏profile阻断外部握手→无profile引导；省略draft_ref重试冲突→同源规范；HTTP BadStatusLine/IncompleteRead逃逸stdio→唯一client结构化未知结果。

验收使用临时作品/真TCP/stdio子进程/已安装Edge，不调用收费模型。新增核心与协议测试、真实网页交接/编辑/采用、三完成门状态见IMPLEMENTATION_STATUS_AND_NEXT.md。实际Codex/ClaudeCode/Pi配置与真实模型、自动token流仍未验证。无需新增MCP SDK；协议只声明已测试的2025 profile。


### 8.11 记忆可靠性公共owner与去重（2026-10-10）

沿权威架构§7.9及IMP-MEM01–06落地，主agent实施，A/B/C/D评审及C/D/B定向只读复验。仅登记实际公共能力，验收结果与残余迁移边界见状态记录。

| 实际能力 | 唯一owner与消费者 | 兼容/去重结果 |
|---|---|---|
| 整批/StoredBatch/Ref/位置结构 | memory/schema.validate_memory_update/validate_stored_batch/validate_source_refs/validate_position；config、MemoryService及Store journal共用 | 复用state/graph常量与GraphKey/StoryCoordinate/parse_source_ref；config.SOURCE_FINGERPRINT_PATTERN公共化，不复制hash正则；来源资格留MemoryService |
| 作品线与游标快照 | `service.load_story_scope_registry` 供偏好与 `load_story_sources` 共用，`SourceCorpus.at_cursor` 供 prepare、MemoryService 消费 | 偏好只校验注册。原文使用同次源字节、Ref 和时间线继承边界 |
| 作者偏好路径与交付文本 | `onboarding.author_preferences_path / read_author_preferences_text` 供材料绑定、上下文和 `read_document` 使用，旧生成入口重导出同一路径函数 | 当前请求沿已绑定文本交付。显式读取核对当时正文，网页保存继续按原始文件字节做版本检查 |
| 共同故事回放与发布映射 | MemoryService.read_snapshot/publication_candidates/map_publication/publication_controls；recall/normalize/AdoptionService | 共用草稿真实前缀/正式坐标/稳定批序；未来先过滤；只映射声明Ref，不递归改自由payload |
| 冻结保护/逻辑journal键 | DraftStore.adoption_path/protect_memory/protected_memory/memory_publications；AdoptionService/MemoryService | 复用既有source-versions与adoptions、原子保存/指纹，无新事实库/日志；证据只能产生失效控制，不能复活事实 |
| 单一效力版本与提交保护 | MemoryService/DraftStore；ToolDispatcher/RunService实际调用方 | 源锁→Store锁、原CAS/提交表/停止判定；旧读取先复核版本，过期只重读；unknown POST不自动重发 |
| 模型上下文与完整结果交付 | generation/context.py；MemoryService.current_snapshot/source_refs_status；ToolDispatcher/RunService；HTTP/MCP/网页显式视图 | 复用原Ref/字符读取与tool_results，full兼容导出/模型来源入口同owner，冻结续页委托原来源效力校验；不新建Store/cache/serializer，不改router容量 |
| 依赖/选择/覆盖 | memory/graph、router、state；MemoryService组合 | 不可遍历必要义务、焦点先于64节点截断；查询未选/访问上限/未记录后缀不同缺口；结束来源单列，不恢复旧值 |
| 可选未定身份 | memory/schema/MemoryService同remember输入和规范批次；router只派生entity_refs | host稳定ID、同名不合并、未来ID拒绝；正式实体/别名仍catalog owner，不增加allocate工具或知识副本 |

回归复用writer_fixtures、既有采用与harness夹具、真实workspace_server和BackendClient；没有第二测试服务器/事务框架。发布批次指纹在来源映射前计算，等效合法发布绑定先校验再去重；不同原内容冲突转缺口。原始run/旧journal/v2兼容及同期写作体验成果保留。

### 8.12 整体context架构实施边界（2026-10-10，源码已实施）

唯一合同见权威架构§7.11；22项外部依据与选择见references/context-engineering-research-20261010.md。实际源码与冻结QA见IMPLEMENTATION_STATUS_AND_NEXT.md和output/context-runtime-20261010-bd48b011。保留§8.11原分页/full能力与完整运行日志，新公共API已按实际落盘更新AGENTS，未新增通用模块或独立状态Store。

| 已落盘能力 | 现有owner与实际消费者 | 禁止复制或越界 |
|---|---|---|
| 请求前材料编译/效力 | generation/context.py、RunService；委托MemoryService.current_snapshot/source_refs_status、SourceCorpus与DraftStore | 不在native/MCP/网页各造当前状态或效力算法，不建workset事实缓存 |
| 焦点当前工作集/语义证据页 | MemoryService/state/router选择、ToolDispatcher交付、context消费 | holder/target种子修在原router；不从关键词猜人物在场，不另造router或摘要事实 |
| 同run provider attempt/调用身份 | RunService生成并由原Store记录attempt/invocation关联，ModelClient保留协议ID | 构造规则只有一个owner；不新建epoch日志、不改harnessoperation_id、不默认反馈fork来缩历史 |
| 安全卸载/恢复与观测 | 原turns/tool_results/tool_commits及公共Ref/指纹/JSON能力 | 日志不删，原参数不另存一套；消息投影不改变取消/CAS/作者指针，不把片段hash当全文偏移 |
| 能力与技术容量 | 原model_config/model_api、显式用户策略；harness由宿主控制 | 不猜provider窗口、不偷加记忆预算、不默认额外摘要LLM，不将opaque摘要存终稿 |

实施顺序为IMP-CTX-01效力/attempt/身份→02工作集与语义交付→03容量/协议组/显式运行限制→04harness共同交接→05可选provider能力与观测→06实跑AB与独立复验。AC-CTX-07–18逐项区分源码/协议/宿主/来源效果；不得用现有536/72/729或单次首包瘦身替代新增验收。

原P1已由RunService发送前context_binding、真实回执预期推进及安全新attempt修复；独立chat/responses反例已复验。新615/72/729全绿，C67＋投影5/B24均绑定194份冻结源码/测试/JS。原设计反例保留在output/context-architecture-review-20261010-249febaf，新实际模型样本单列，不把首包估算、opaque能力guard或单次AB称全部长篇/端点验收。

去重记录增量：共同编译/语义/恢复字段归原context owner；原tool_results保存真实arguments/交付关联供焦点与恢复派生，原turn保存准备/完成与attempt绑定，原tool_commits继续唯一幂等证据。模型原_turn_body委托公开request_body，策略校验与provider用量聚合归model_api；native/harness/配置共同消费，不复制另一份JSON/时间/指纹/源效力算法。完整源与正文读取仍复用SourceCorpus、DocumentRef、DraftRef、AuthorInputRef及text_page。

### 8.13 无名称线索候选与作者材料隔离（2026-10-11）

沿架构§7.9.5修复百章同义描述漏旧Hook：候选选择仍归router，词项仍复用safe_query_terms，来源/故事排序仍归MemoryService；没有focus时并列有效Hook/OpenCondition，保留原性质并标未确认对应。显式focus/五工具/默认无token上限保持；不新增模型、Store、同义词表或全图分页API。

公共判定memory/graph.is_author_material提取原邻接已有的author_plan/纯AuthorInputRef条件，visible_adjacency及router的发现/必要闭包共同消费；事实依赖作者材料时整包拒选，不能删边伪造完整事实。generation/context.semantic_result_page在原合并单位及过大包入口传递原selection_reasons，不改原冻结JSON/来源效力或另建分类器。具体前后反例、源码冻结与完成门见IMPLEMENTATION_STATUS_AND_NEXT.md本次记录。

### 8.14 记忆工具易用性与安全源解析（2026-10-20）

本轮沿用户已选的优化1、2实施；已有作品视为归档资料，仅只读检查兼容与指纹，不补建记忆、不修改正式源。当前进度和完成门统一见[当前状态摘要](IMPLEMENTATION_STATUS_AND_NEXT.md#current-status)。

| 现有owner | 实际增量与复用 | 边界 |
|---|---|---|
| memory/schema | remember_update_schema派生互斥操作分支，validate_memory_update消费同一必需/禁用键并给实际下标；新增公共memory_update_guidance从原Schema/校验派生最小形状及原ID的recall入口 | 不建立第二校验器或工具参数规范；stored路径保留原容器兼容，不猜ID或自动修正文 |
| MemoryService / ToolDispatcher | 原_normalize定位状态身份拒绝并提示原身份；原工具失败回执附details，提交/CAS/幂等/来源检查保持原owner | 错误指引只读，不自动执行、重试或将人物判断升级为世界知识 |
| documents | 原_parse_yaml_bytes使用可选CSafeLoader，无C时回退SafeLoader；read_yaml_snapshot/read_yaml_mapping继续共同消费 | 不新增依赖、缓存或第二来源Store；仍读取真实字节并绑定同次hash，原正式作品不改 |

回归复用writer_fixtures、真实harness及既有记忆/来源/协议用例；安全解析覆盖C/纯Python、merge/Unicode/块正文与危险Python标签拒绝。性能前后只比较同机source加载，另逐项对照两书660份可见源的旧安全解析值、Ref/gaps及正式源总指纹；不由该测量推断完整recall、远端模型成本或文学效果。

### 8.15 超过64候选的继续查找（2026-10-21）

沿用户原第4项与权威架构§7.9.5/AC-MEM-12–13增量，已有归档作品只读。router唯一负责候选frontier/已访问集合/图输入指纹，每次至多新访64根，必要依赖仍整包；MemoryService在同次来源/别名快照核效力，源/图/记忆变化拒绝旧进度。候选控制状态与原完整结果一起写入原tool_results行，由state_hash绑定，不新增Store或事实副本；原result中仅保存小进度，控制状态不占事实选择容量。

ToolDispatcher沿原recall的分型continuation定位本run原行/hash；`kind=candidates`继续搜索，原JSON/语义cursor继续交付已选包，均不改持续focus/Q。公共generation/context.candidate_search_navigation统一full/JSON/语义结果的候选入口，HTTP/stdio只转发原五工具；实时working_set先给根recall读取参数，不伪造冻结cursor。复用公共json_text/fingerprint_bytes、SourceCorpus、原源码/安全来源/Store权限与回放，不复制哈希、来源解析、路由或分页缓存。实际结果与三道门统一见[当前状态摘要](IMPLEMENTATION_STATUS_AND_NEXT.md#current-status)。

独立QA发现原技术回执直接返回新增控制字段；由原generation/store新增唯一public_tool_row公开投影，DraftStore.snapshot与context.technical_tool_receipt共同复用，只排除candidate_search_state，保持原参数/result/delivered_result与原Store行。UI/技术入口不重复实现字段过滤，原候选恢复控制数据仍在同一Store。

### 8.16 状态观察、作者浏览与运行存储（2026-10-21）

权威合同见架构§18。A/B/C/D独立评审后仍沿原DraftStore/MemoryService/router/ToolDispatcher/RunService/context及workspace.js，不新增Store、模型、事件框架或分页缓存。已有归档作品只读；旧内联run按需兼容，不批量迁移。

Store独占热快照/事件高水位/观察变化提示及冷字段物理布局：工具行的大参数/结果/交付/控制状态、逐turn、逐batch与逐draft值可外置到本run按内容hash保存的JSON；run用独立位置映射引用，用户payload不解释为内部指针。公共json_text/fingerprint_bytes、SOURCE_FINGERPRINT_PATTERN、atomic_write_bytes/json复用；先产物后run引用。load重建精确逻辑形状，缺失/坏hash/冲突内联/非法位置/未知版本拒绝；恢复与写回共用布局校验，live/接收/事件不展开无关冷字段。事件连续数组不裁剪，持久前缀先于显示，原幂等/回执/cursor保持。

原resolve_draft接受同次同身份run元数据，正文仍每次真实读/hash；异run沿原owner读取。metadata_only仅供target_source_ref祖先链按需展开选中检查点，live/full共用原建议坐标与采用目标投影，不丢CAS基线。来源签名相同的_reconcile在原锁/CAS后不写盘；仅观察run文件替换的stat不能证明来源有效。

作者浏览沿共同recall校验及冻结结果，origin=author_browse原工具行保存精确cursor进度；context.model_tool_rows为模型选择/交付历史/恢复材料的共同过滤，作者浏览不计模型工具事件，终态仍可读。router的显式browse_all在原权限快照内列所有可见根，小包也给结束计数；模型默认选择不变。workspace.js单一API client管理live请求单飞及独立浏览run/generation，完整批和下一候选分开，状态来自state_view.entries/ended_entries，来源失效重新查。实际完成门与性能样本统一见[当前状态摘要](IMPLEMENTATION_STATUS_AND_NEXT.md#current-status)。


### 8.17 项目std、纯来源合同与包布局（2026-10-23）

源码现位于`src/novel_rag`，单一发行包与既有业务包保持。下列是本次迁移后的公共owner；表内路径相对源码包。三完成门、安装态和独立QA以[当前摘要](IMPLEMENTATION_STATUS_AND_NEXT.md#current-status)为准。

| 能力 | 唯一owner与使用方 | 兼容边界 |
|---|---|---|
| UTC/字节SHA/紧凑JSON/原子保存 | std/time、hashing、serialization、atomic_io；Store/context/tools/memory/adopt/model及既有业务消费 | timeutil、mutations.types/coordinator、graph.corpus同对象重导出；旧缩进、紧凑与参数JSON格式分别保持 |
| OS互斥 | std/locks.AdvisoryFileLock；FileMutationLock持有guard覆盖owner整个生命周期 | 元数据、PID/stale与业务错误仍在mutations/locks；稳定guard不能删除；Windows真实进程验证 |
| 来源类型/纯校验 | contracts/references；documents/config/generation.types/memory.schema重导出 | 来源签发/效力、状态/人物语义、RunBinding留原owner；generation旧v2 API惰性加载 |
| 单源提交与投影过滤 | mutations/source.build_source_mutation_coordinator、source_projection_ignores；MemoryService/Adoption/Summary及两条v2投影消费 | composition委托旧公开工厂；保留源锁→Store锁、普通资料及采用后待完成恢复；投影精确跳过根mutation guard和所有目录的运行时保留名.writer.lock.guard，原文件不删 |
| 作者保存 | `RunService.save_author_draft` 返回引用，Web 委托 `save_author_draft_receipt` 取得回执 | 同一锁内决定 partial、拼装前缀并按原 CAS 提交。回执携带本次保存的全文，后续状态和记忆读取有各自结果 |
| 安装资源与资料根 | config以调用工作目录为默认；state/helpers从显式库优先读模板，再用随包两份默认；pyproject声明resources/static | src包安装后可仓外运行；脚本消费安装包，缺源码身份直接失败；正式库不搬迁 |

基础包只依赖Python标准库；业务专有逻辑仍按稳定职责留原包，不因同名或行数再造通用框架。凭证writer安全语义、legacy词法、两种manifest输入域与六组shim保持。

### 8.18 应用入口与运行提交公共owner（2026-10-23）

沿架构§20与用户指定两处解耦，保留RunService、DraftStore、MemoryService、AdoptionService四个owner。CLI/Web消费RunService的工作台快照、运行信息/结果、观察、脱敏启动查询、harness工具查询及采用/编辑操作；生命周期租约/恢复委托原Store。公开响应字段不变，适配层不解释内部binding或直接读Store/config/memory；SSE仍发送原热快照与事件。

记忆领域新增唯一纯策略`memory/effects.py::draft_selection_effect / initial_memory_effect_invalid`，调用方为Store.save与MemoryService._reconcile。明确`generation/types.py::MemoryCommit`承载规范化批次、回执与效力签名；旧二元组及其`_effect_signature`只在commit_memory入口转换成明确结构，移除旧控制键后进入唯一提交实现。新MemoryService不再生成隐藏字段。Store的`reconcile_memory_effect`同时校验记忆版本与选中稿、同签名不写；`record_adoption_receipt`同锁重读后更新镜像。MemoryService与AdoptionService不直接write整个run。

记忆同次read_snapshot和remember仍持有必要的一致性锁；generation内部运行协调仍用原Store锁域。没有增加generic update_run、第二提交日志、Repository/UoW、策略fallback或新模型。实际验收与原库字节核对以[当前摘要](IMPLEMENTATION_STATUS_AND_NEXT.md#current-status)为准。

### 8.19 记忆指引、惰性入口与工程检查（2026-10-23）

沿架构§21实施用户指定3/4/5：记忆操作示例与可写字段说明继续归`memory/schema.py`，公共`remember_update_examples`供同一Schema的description/examples复用，由ToolDispatcher定义原样交付原生模型与MCP；不另建校验器或模型专用Store。CLI保留原command函数和执行接缝，重依赖按命令解析；writeback/retrieval采用既有generation惰性导出模式，兼容名字仍委托原owner。

架构规则归既有pytest入口，新进程覆盖实际加载，聚焦AST规则覆盖已确认owner边界，测试以合法与违规样例验证规则有效。浏览器选择复用原测试finder；CI安装Chromium、先建canonical索引、运行原三完成门并验证实际wheel。测试工具不进入生产std，也不新建规则DSL/任务框架。工作流与本地证据、远端CI、真实创作样本分别报告，最新结果见[当前摘要](IMPLEMENTATION_STATUS_AND_NEXT.md#current-status)。
