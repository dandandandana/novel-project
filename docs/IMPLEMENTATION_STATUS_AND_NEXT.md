# Novel-RAG 实施状态与后续任务交接

> 状态：进行中，不能视为最终验收通过
>
> 更新时间：2026-08-20
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

### 2.2 canonical 资料与派生图

迁移采用 copy-only 方案，当前 canonical 树共有 **716 个 YAML 文件**。旧资料仍保留，未做删除或移动。

截至交接时的实际校验/manifest 记录：

| 派生物 | 文档数 | FTS 分块数 | 路径 |
|---|---:|---:|---|
| shared | 25 | 94 | `novel-rag/index/shared.db` |
| `overturned-world-fujimaru/main` | 652 | 1108 | `novel-rag/index/graphs/overturned-world-fujimaru/main.db` |
| `shirouxcile/main` | 52 | 105 | `novel-rag/index/graphs/shirouxcile/main.db` |

当前两个故事都只有 `main` timeline；分支时间线的真实资料验收尚未替代单元测试中的 lineage 覆盖。

## 3. 已有验证证据

以下是可复现的已知结果。命令在 Windows PowerShell 下从 `D:\novel-project` 执行。

| 验证 | 命令 | 结果 |
|---|---|---|
| 测试收集 | `python -m pytest --collect-only -q` | `219 tests collected` |
| 完整测试（排除唯一待确认的跨进程锁测试） | `python -m pytest -q -k "not test_file_lock_uses_windows_safe_exclusive_create_across_processes"` | `218 passed, 1 deselected, 84 warnings` |
| 锁/pending 单进程覆盖 | `python -m pytest -q tests/test_mutation_lock_pending.py -k "not windows_safe_exclusive_create_across_processes"` | `5 passed, 1 deselected` |
| canonical 注册表与资料校验 | `python -m novel_rag.cli --library "$PWD/novel-rag" validate` | `729 个有效文档, 0 个问题` |
| 安装能力预检 | `python -m novel_rag.cli doctor` | `ok=true`，SQLite 3.35.5，FTS5/trigram 均为 true |
| 双故事隔离 | `python scripts/verify_multi_story_isolation.py` | `multi_story_isolation=PASS`，`cross_story_leaks=0` |

`218 passed` 的命令明确排除了一个测试，因此不能写成“219/219 全部通过”。此前被中断的长测试输出也不作为最终绿灯证据。

## 4. 尚未闭合或需要最终复核的项目

### P0：在宣称完成前必须闭合

1. **Windows 多进程排他锁**：`test_file_lock_uses_windows_safe_exclusive_create_across_processes` 尚未独立得到稳定的 `1 passed` 证据。当前仅证明同进程竞争、死 owner 恢复、pending 重启和 CLI 入口的 5 项通过。跨进程测试曾出现进程启动/中断风险，必须单独复核。
2. **正式 72 条 retrieval regression**：两部作品的正式回归总数已知为 72，但最终运行结果尚未在本交接中闭合。必须得到 `retrieval_cases=72 failures=0`，并记录两部 story/timeline 的结果。
3. **真实 shared 反向依赖**：`SharedReader.dependent_graph_keys()` 的单元测试已覆盖，但仍需对当前 `shared.db` 和两个真实 graph manifest 运行一次，确认 module-map 变化能列出所有受影响 GraphKey，并使其 stale。

### P1：紧随 P0 的生产边界复核

- 用真实 library 执行 pending list/retry，确认 pending manifest 可跨进程/重启恢复，promotion 失败时不使用旧图冒充新图。
- 对 shared YAML 做临时、可恢复的 fingerprint 变更，在不删除资料的前提下确认所有依赖图被拒绝生成；随后恢复原内容并复建通过。
- 对用户摘要 revision、自动摘要不覆盖用户版本、用户摘要 stale 不进入 ContextBundle 做一次真实 CLI/TUI 流程复核。
- 复核默认 generation、importer、state、writeback、feedback 都经由组合根和 MutationCoordinator，不直接创建/写入 SQLite。

### P2：验收完成后的清理与维护

- 统计仍在使用的旧 facade/shim 和弃用告警；只有零调用、完整回归和用户授权都满足后才删除。
- 维护检索回归基线、manifest 指纹和数据计数，避免以固定测试数量替代完整测试门禁。
- 在另一个真实分支 timeline 数据集上补做祖先 cutoff、divergence snapshot、同级/后代误召回为零的端到端验收。

## 5. 下一步任务表（按优先级）

| 优先级 | owner 建议 | 命令/动作 | 完成标准 |
|---|---|---|---|
| P0 | `luna_worker`：锁测试 | `python -m pytest -q tests/test_mutation_lock_pending.py::test_file_lock_uses_windows_safe_exclusive_create_across_processes -vv` | Windows 上稳定 `1 passed`，子进程退出码为 0，锁文件按预期释放，无残留进程 |
| P0 | `luna_worker`：检索回归 | `python scripts/run_retrieval_tests.py` | 输出 `retrieval_cases=72 failures=0`；失败时保留完整 case、返回 ID、禁止状态和 GraphKey |
| P0 | `luna_worker`：shared 依赖 | 以只读脚本加载 `SharedReader`、两个真实 `graph_manifest`，调用 `dependent_graph_keys()` | 返回完整、确定性排序的受影响 GraphKey；与两个 manifest 的 module references 一致；变更传播 stale 断言通过 |
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

