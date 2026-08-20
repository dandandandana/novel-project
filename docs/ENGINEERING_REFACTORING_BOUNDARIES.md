# Novel-RAG 工程问题与迁移边界

> 状态：实施伴随文档（v2）
>
> 权威声明：架构、布局、依赖方向和稳定接口只由 `HYBRID_GRAPHRAG_ARCHITECTURE.md` 定义。本文件记录现状问题、迁移顺序、禁止搭车修改和验收证据；不得成为第二份架构规范。
>
> 本文件不授权删除资料、改变 Canon、安装运行时服务、引入向量数据库、提交 Git 或发布部署。

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
