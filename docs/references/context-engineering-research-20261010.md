# 小说项目的 context 注入研究（2026-10-10）

权威选择与实施合同在 [架构 §7.11](../HYBRID_GRAPHRAG_ARCHITECTURE.md#context-architecture)。本文保存本轮外部依据及适配理由，不另设规划主控。用户要求广搜后选择适合本项目的方案；主 agent 与 design-review-council 的 A/B/C/D 分工研究。以下22项均为实际读取的一手论文或官方资料，核查日为2026-10-10；没有日期的动态文档不猜发布日期。外源机制与本项目裁决分列，裁决是基于当前源码和会话合同的工程判断。

## 一手来源与采用范围

| ID | 来源 / 日期 | 资料支持的机制 | 本项目裁决 |
|---|---|---|---|
| S01 | [Anthropic context engineering](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)，2025-09-29 | 轻量引用按需读取、少量预取与长期上下文整理 | 采用混合披露；不照搬多agent或默认摘要模型 |
| S02 | [Anthropic Agent Skills](https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills)，2025-10-16 | 元数据、主体与附属资料分层加载 | 采用来源/条目导览；不把角色资料全部塞入常驻前缀 |
| S03 | [Manus context engineering](https://manus.im/blog/Context-Engineering-for-AI-Agents-Lessons-from-Building-Manus)，2025-07-18 | 稳定前缀、可恢复卸载、保留错误证据 | 采用确定性卸载和恢复身份；不要求固定todo或额外文件事实库 |
| S04 | [MemGPT论文](https://arxiv.org/html/2310.08560v2)，初稿2023-10-12 / v2 2024-02-12 | 主工作上下文与外部记忆分离、通过函数取用 | 采用分层思想；当前状态仍从既有MemoryService派生，不建另一份可编辑真相 |
| S05 | [Letta V1 memory blocks](https://docs.letta.com/v1-sdk/memory/memory-blocks)，当前legacy文档 | 常驻、可共享的memory blocks | 只作旧方案对照；共享block不能等同人物共享知识 |
| S06 | [Letta Agent SDK memory](https://docs.letta.com/agent-sdk/memory)，动态文档 | 常驻system文件、目录入口及按需文件、后台整理 | 借鉴核心/外部资料分层；不引入memory repo或dreaming替角色获知 |
| S07 | [LangChain context engineering](https://docs.langchain.com/oss/python/langchain/context-engineering)，动态文档 | 临时模型输入与持久state不同；摘要中间件可另调用LLM并替换消息 | 采用临时投影边界；不采用持久删原消息或默认辅助模型 |
| S08 | [Deep Agents context management](https://www.langchain.com/blog/context-management-for-deepagents)，2026-01-28 | 大工具结果卸载、旧工具输入缩减、摘要 | 先卸载已保存全文/重复结果；技术概要不能替代状态/正文 |
| S09 | [Claude prompt caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching)，动态文档 | 缓存基于一致的前缀内容 | 采用稳定规则/schema；本项目尚无Anthropic codec，不宣称已接入 |
| S10 | [OpenAI prompt caching](https://developers.openai.com/api/docs/guides/prompt-caching)，动态文档 | 复用匹配前缀；配置/工具变化会影响匹配 | 缓存是计算复用，不能代替效力校验或上下文整理 |
| S11 | [OpenAI compaction](https://developers.openai.com/api/docs/guides/compaction)，动态文档 | 支持服务端整理及独立compact；独立compact返回的完整窗口应原样续用，opaque项不可解释 | 仅列可选provider能力，默认未启用；失效源不能藏在旧opaque窗口继续用 |
| S12 | [OpenAI reasoning continuation](https://developers.openai.com/api/docs/guides/reasoning#keeping-reasoning-items-in-context)，动态文档 | 连续工具调用推荐保留最后user之后的reasoning/call/output，优化也要求该区间原样保留 | 活跃Responses链不直接删旧页；需要明确新attempt或已验证的compaction |
| S13 | [OpenAI conversation state](https://developers.openai.com/api/docs/guides/conversation-state)，动态文档 | 手工输入数组与服务端续接是不同管理方式 | 当前手工stateless实现保持；不把previous_response_id当作省去历史输入成本的保证 |
| S14 | [Google ADK context compaction](https://adk.dev/context/compaction/)，动态文档 | 按token量或固定轮数整理；可使用摘要组件 | 采用实际容量触发思想，不照搬固定轮数、框架或额外摘要模型 |
| S15 | [Anthropic Contextual Retrieval](https://www.anthropic.com/engineering/contextual-retrieval)，2024-09-19 | 给chunk补文档背景，结合词项/语义检索和排序 | 先用真实坐标/实体/来源元数据保留背景；新增embedding/contextualizer需单独实测，不让生成背景成为角色知识 |
| S16 | [Microsoft GraphRAG local search](https://microsoft.github.io/graphrag/query/local_search/)，动态文档 | 以实体为入口组合图关系与原文 | 适配现有graph/router，修holder/target种子；不引入第二GraphRAG索引或全局总结流水线 |
| S17 | [RAPTOR](https://arxiv.org/abs/2401.18059)，2024-01-31 | 递归摘要构成多层检索树 | 可作未来低权威导览实验；当前不采用摘要树替代原文/时点/必要依赖 |
| S18 | [Lost in the Middle](https://arxiv.org/abs/2307.03172)，初稿2023-07-06 / v3 2023-11-20 | 所测QA/键值任务对信息位置敏感 | 采用位置变化反例；不能推断本项目模型也有相同数值表现 |
| S19 | [RULER](https://arxiv.org/abs/2404.06654)，初稿2024-04-09 / v3 2024-08-06 | 单一needle检索不足以评估多跳/聚合与长窗使用 | 验收增加前因、解除来源和跨页链，不只看关键字命中 |
| S20 | [LongMemEval](https://arxiv.org/abs/2410.10813)，初稿2024-10-14 / v2 2025-03-04 | 分开评估提取、跨会话、时间、知识更新和拒答 | 本项目分开测新旧信息、人物误信、未获知、来源失效；不套聊天用户档案模型 |
| S21 | [LoCoMo](https://arxiv.org/abs/2402.17753)，2024-02-27 | 用人物与时序事件约束长期对话，评估QA/事件概括等能力 | 借鉴有人工来源的连续性夹具；不把问答分数等同小说质量 |
| S22 | [OpenAI agent safety](https://developers.openai.com/api/docs/guides/agent-builder-safety)，动态文档 | 避免不可信资料进入高优先级指令，结构化流降低部分风险 | 原文、范例、工具错误及摘要仍属资料；不能改变scope、权限或人物摄取 |

## 方案比较与选择

| 路径 | 能解决什么 | 在本项目的主要代价 | 裁决 |
|---|---|---|---|
| 全库/全历史常驻＋缓存 | 少补读，重复prefix可能复用计算 | 失效信息仍在窗口，注意力与容量问题仍在；人物视图易混淆 | full保留导出，退出默认注入方案 |
| 纯按需引用/字符页 | 首包小、原文可精确恢复 | 不知应查什么；半页JSON难读；读取回合和历史仍增加 | 保留底层恢复，增加当前工作集及语义入口 |
| 焦点工作集＋按需原文/经过 | 当前角色、约定、物件可直接取得，历史可扩展 | 需要真实focus/来源效力及必要依赖，不可凭关键词猜在场者 | 本轮采用的默认方向 |
| 每请求临时编译＋确定性卸载 | 原日志完整，发送材料可以更新 | provider调用链不能任意裁剪；重启需保留操作身份 | 本轮采用，先修失效历史；按协议建立attempt边界 |
| 自由文本滚动摘要 / 摘要树 | 历史可能较小 | 否定、身份、获知时点和未决解释可能丢失 | 默认不采用；可选低权威概要另做实验 |
| provider compaction / 外部宿主整理 | 保留其协议所需上下文并缩短窗口 | 模型/端点能力不同，opaque项无法逐句校验，宿主由外部控制 | 单独能力验收后可选，不作唯一恢复路径 |

## 本地证据与研究限制

上轮100章夹具：context资源估算177219→5045，真实冷会话486.64秒、955字符/1批记忆；累计输入942023，其中缓存输入866560。来源是 [前轮报告](../../output/context-delivery-20261010-167797cd/RESULTS.md)。这些数字分别衡量资源大小、宿主耗时与累计用量，不能混成单次provider峰值或成本下降证明。

B本轮实跑真实RunService与确定性模型transport：先读旧稿/状态，作者改写后当前memory_revision 1→2，但下一请求仍发旧材料；chat/responses均复现。Store未覆盖作者新稿，缺陷在消息组装。C独立构造及前轮真实HTTP请求轨迹支持同一增长/失效问题；其约22KB→127KB是逻辑对象重序列化大小。D额外验证技术重启时旧provider call_id会与同run提交键冲突，feedback空request会丢原要求，child run会改变引用/前缀合同。

本轮新探针均为确定性结构/本地运行证据，模型调用0；论文或他家实践没有直接认证本项目文学、角色知情、branch/cursor或所有兼容端点。原始证据保存在output/context-architecture-review-20261010-249febaf，源码/正式资料保持。新增架构的运行验收仍待实施。
