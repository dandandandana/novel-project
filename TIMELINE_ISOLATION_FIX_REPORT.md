# A01 / A03 时间线来源隔离修复

2026-11-25 · 本地分支 `fix/timeline-isolation-a01-a03` · 父提交 `d08f0b9850aa37dfe0eda272df207ebe5532b657`。本报告随修复一同提交。原工作树停留在 `feat/hybrid-graphrag-v2` 的 `0540cf4`；修复从指定 v3 基线的独立干净工作树起步。

| 验收项 | 结论与证据 |
|---|---|
| Code Fixed | 作者写入先核真实目标归属；来源读取与建图在解释继承前校验物理位置和 YAML 声明。 |
| Regression Added | 30 个新增参数化用例，涵盖写服务、源提交器、v2 旧布局写入口、当前和历史图读取。 |
| Tests Passed | Windows 工程门通过 842 项，按项目约定排除 1 项。检索 72 例全部通过，729 份文档校验无问题。 |
| Production Data Preserved | 原工作树 1,522 个文件、基线工作树 1,517 个文件的相对路径、长度及 SHA-256 分别逐项一致，含 SQLite 索引。 |

## 原始问题与调用链

在 `d08f0b9` 上用合成的 main/child、分歧快照、同坐标章节和 common Canon 复现。A01 中，父章在子线可见；子线 run 对它修订并采用后，源事务替换了临时库的父线原件。旧回执使用发起 run 的 child scope。继承 Canon 和摘要的作者编辑也能选中父路径。两处旧版入口还有一个条件相同的反例：纯 legacy 布局使用同一物理槽位时，正文相同的确认及状态晋升均能将父线原件作为子线变更交给协调器。

A03 中，位于父线目录但自称 child 的 YAML 能绕过父线截止点，反向错标也会进入错误的语料。v3 的实体检索、工具读原文、记忆及上下文随后消费同一份语料。v2 的验证、直接图构建和已有错位图消费也曾接受其中的输入。复现仅作用于临时库、临时数据库和工作区。冻结基线与修复版本执行同一组断言的比较见下文。

```text
原始读路径
  资料路径 → 枚举本作品及祖先目录 → YAML 声明的 timeline → cutoff → SourceCorpus / DocumentRef
                                                              ├─ read / search / recall
                                                              └─ prepare / draft context
  资料路径 → load_valid_documents → ValidatedCorpus.for_graph → GraphBuilder → SQLite → 检索

原始写路径
  子 run + 固定草稿 → DraftStore.target_source_ref → 可见的父 History 路径
                  → AdoptionService.prepare → 目标路径与待写 metadata 内部一致 → 正式替换

修复后的写路径
  子 run + 固定草稿 → 解析实际文件身份 → 检查发起 scope 的写权限
                  → 核对原件及草稿版本 → 原 MutationCoordinator → 真实目标回执
```

## 十项身份与权限核对

| 问题 | 实现及合同 |
|---|---|
| 1. 物理文件归谁 | `catalog/layout.py::LegacyLayoutMapper.normalize_path` 将实际库内路径映射为 `NormalizedPath`。目标布局的作品与时间线由 `stories/<story>/timelines/<id>/` 确定。 |
| 2. 如何核对声明 | YAML Schema 继续由 `documents.validate_document` 检查；真实目录与元数据的对应关系由 catalog mapper 核对。冲突在 v3 返回带来源位置的 gap，该文档无法读出；v2 的正式语料/图构建拒绝含冲突的输入。 |
| 3. common | 规范的 `common/` 与兼容的旧式共同目录沿用 mapper，保留原有 main/common 声明和 Ref 约定。物理时间线文件上的 common 标签不能取得共同资料的可见性或写权限。 |
| 4. lineage 和 cutoff | `TimelineRegistry.lineage/cutoffs` 沿父链从根到目标，每段祖先以上一级亲子分歧坐标为上界，含分歧点。当前时间线没有祖先截止上界。真实祖先资料按自身坐标和对应上界筛选，叙事游标随后再裁取。 |
| 5. DocumentRef | 对同一次 YAML 快照返回不透明 ID、源修订、完整字节哈希、来源 scope 和坐标。继承读取保留实际父线 Ref；草稿或调用者不能替换其来源身份。 |
| 6. DraftRef | `RunService.prepare` 固定 run 的 scope、游标和基线；`DraftStore.resolve_draft` 核对检查点与正文，`target_source_ref` 沿所选草稿祖先解析原采用目标。草稿版本/正文及正式资料版本使用各自的 CAS。 |
| 7. 采用目标 | 对既有章的同坐标修订按绑定 Ref 的 ID 定位，验证真实身份和写权限；新坐标使用当前线的既有目标命名规则及防冲突验证。重复采用按已有 operation ID 和参数恢复。 |
| 8. v2 图来源 | `load_valid_documents/load_validated_corpus`、catalog `for_graph` 及 `graph.corpus.scope_corpus` 复用物理归属；非严格构造的适配语料在直接投影前仍会核验。无库根的 canonical 读取额外核对登记来源，历史图的能力边界见下文。 |
| 9. legacy 布局 | 旧树没有物理 timeline 目录的槽位按原声明和默认线映射。canon/registry 的共同资料、旧式 History 和已有平铺/内存适配保持兼容。共享物理槽位覆盖已有版本前，另查原件归属，防止通过新 metadata 改线。 |
| 10. 其他写入口 | `edit_reference`、SummaryEditor 的 source-only 提交、历史采用 journal、v2 `confirm_runtime` 与 `approve_state_proposal` 均检查了目标路径。正式 YAML 仍经原 MutationCoordinator；锁内 staged 验证和文件 CAS 继续生效。 |

## 修改与错误行为

- **读取和投影。** catalog 复用已有布局解释器统一物理身份，`service.py` 将结果用于原文、搜索及进入记忆和草稿上下文的来源。v2 图沿用文档坐标与祖先截止合同。`composition.py` 和图指纹/读取边界在已有图查询时检查相关来源。对坏文件不返回可消费的原文、DocumentRef 或检索项。[目录映射](src/novel_rag/catalog/layout.py) · [语料](src/novel_rag/catalog/corpus.py) · [v3 来源](src/novel_rag/service.py) · [v2 图边界](src/novel_rag/graph/corpus.py)
- **写权限。** `require_source_write_scope` 接受已解析的来源身份、请求方 GraphKey 和显式的 common 权限。History 只能由所属作品线修改。同作品 common Canon 和笔记保留原作者编辑能力。既有原件和候选新版本分别校验，写入与请求的身份、版本、指纹不符时拒绝。源提交器继续使用原锁、暂存与 CAS。[单源协调器](src/novel_rag/mutations/source.py) · [采用与资料编辑](src/novel_rag/writeback/adopt.py)
- **采用及重试。** 跨线同坐标修订在保护源副本、新建 intent 和正式替换前返回 `scope_denied`，保留 DraftRef，可用原 operation ID 重试并得到同一拒绝。合法采用的回执对应真实目标的 scope、坐标与 source_hash。历史 prepared/adopted journal 指向祖先的错误记录不能恢复成子线成功，后续合法操作仍可进行。
- **子线本地修订的决定。** 系统没有“子文档遮蔽父文档”的读取合同；新建禁止占用已有可见的 History 坐标，替换只绑定一个目标及 CAS。本次选择安全拒绝同坐标继承修订。子线可以沿用继承资料在合法的新坐标创建独立 History，也可凭自己的 DocumentRef 修改现有的同坐标子章；均保留原始来源和父章字节。
- **v2 兼容写入。** 正文确认将已有目标的身份检查和指纹绑定同一份源快照，确认回执重放核验目标。状态晋升校验正式文档的原属与待写归属，版本映射仍沿用原专门规则。[正文确认](src/novel_rag/writeback/confirm.py) · [状态晋升](src/novel_rag/state/review.py)

## 测试与数据保护

同一组 27 项入口断言在冻结的 `d08f0b9` 源码上有 19 项按预期失败，8 项合法行为通过。修复后 27 项全部通过。另有 3 项直接覆盖新写权限接口的回归，共计 30 项。指定的六个原测试模块（`test_identity_catalog`、`test_adoption_v3`、`test_source_snapshots`、`test_graph_projection`、`test_memory_cursor`、`test_retrieval_contracts`）与新增回归一起执行，129 项通过。另在既有[公开索引兼容测试](tests/test_index.py)中验证了平铺内存语料的检索。

三条工程门的业务命令如下。pytest 同时使用临时 basetemp 并关闭 cacheprovider；检索和 CLI 使用各自隔离的资料副本。

```powershell
python -m pytest -q -k "not test_file_lock_uses_windows_safe_exclusive_create_across_processes"
python scripts/run_retrieval_tests.py
python -m novel_rag.cli --library novel-rag validate
```

首轮全套运行发现 3 项原有兼容行为失败，涉及平铺内存语料及导入后即时检索。修正后全套 842 项通过、1 项按项目规则排除，pytest 报告 90 条警告。检索输出为 `retrieval_cases=72 failures=0`，CLI 校验通过 729 份文档。既有图的来源复核见[图指纹](src/novel_rag/graph/fingerprint.py)和[读取入口](src/novel_rag/graph/reader.py)。

主回归在 [timeline 来源隔离测试](tests/test_timeline_source_isolation.py)。源事务的单文件原件/新版本归属验证见 [source-only 写权限测试](tests/test_source_write_scope.py)，旧版两个实际入口的拒绝与未调用提交器见 [旧版写回测试](tests/test_state_writeback_mutations.py)。覆盖情况如下。

| 行为 | 观察值 |
|---|---|
| 合法 lineage、cutoff、common 和 legacy | 父读本线；子读分歧前、分歧点及 common；分歧后父章不可见；旧式 main History 保留原 Ref 与字节。 |
| 错标与跨入口读取 | 双向物理/声明错位均有诊断，错标原文不进入选定上下文、read_document、recall/search 或 v2 严格/直接建图。 |
| 本线写、同坐标、共同资料同名 | main/child 各自修改所选 ID，正式回执与再次读出的 Ref 相同；同名 common 编辑只改选中文件。 |
| 继承修订、旧 CAS、来源移动或草稿变化 | 拒绝跨线覆盖或失效的引用，父源哈希与其他正式文件不变。移动但字节未改变也不能复用错位的正式身份。 |
| 重试及旧回执 | 合法操作幂等返回，旧跨线 prepared/adopted 意图拒绝；同一子线随后的合法操作能独立成功。 |

三条工程门在系统临时目录内的项目副本执行，使用独立 Python 环境及既有依赖，pytest 关闭缓存。全套运行后补齐了四个函数的说明；逐文件核对 239 个源码和测试输入，四处差异均为 docstring，去掉 docstring 的语法树一致。同步最终字节后，重新执行索引、建图、目录身份、来源隔离和旧版写回相关的 79 项测试，全部通过。因 Git 基线未携带两本作品的派生图，检索门在临时副本中创建 SQLite 投影。写入安全用例全部使用合成小说和临时数据库。

对原工作树与修复工作树分别记录 `novel-rag/shared/`、`novel-rag/stories/`、`novel-rag/index/` 的逐文件 `relative_path/size/sha256`。前后清单逐字节相同，新增、删除、大小或散列变化均为零。四份机器可读清单与本机试验日志保存在本地证据目录，未纳入提交。

| 资料树 | 文件数 | 前后相同的 JSONL SHA-256 |
|---|---:|---|
| 原工作树（含既有未跟踪文件） | 1,522 | `1b5623fa4a6069af41af81573be6dced70946a35b45bd26e2eca79d109aa8b24` |
| v3 基线修复工作树 | 1,517 | `615270d3f4758dfe24b41788521e8b8b0c8351d7db62362fa0c886017f74db36` |

本地证据目录中保留 `original-before.jsonl`、`original-after.jsonl`、`baseline-before.jsonl`、`baseline-after.jsonl` 和工程门原始输出。额外抽查发现，早期隔离测试的子进程在修复工作树生成了 59 个被 Git 忽略的 `.pyc` 文件。这批文件已清除，最终工程门在系统临时目录的独立副本运行。原工作树的 HEAD、索引和已有变更均保留。

## 边界与后续

对于缺少资料根的 canonical 图，读取器复查图中可定位的正式来源以及对应的祖先截止点。单靠这类图不能发现未登记的新文件。平铺的合成内存语料保留原调用合同。早于 canonical 图的 SQLite 兼容查询仍需调用者显式使用 `legacy=True`；这种旧索引无法提供正式源证明。

本次未运行真实模型创作，未在生产库模拟采用或恢复，未在其他操作系统实跑。历史审计中的其余问题保持单独处理，尤其是 v2 多文件提交部分失败的 A02。若未来需要在子线同坐标覆盖继承章节，应先明确定义覆盖后的读取优先级、文档身份、历史引用和 CAS，再扩展本地修订合同。
