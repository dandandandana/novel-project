# Novel RAG

面向长篇小说生成 Agent 的元数据优先 RAG 基础框架。当前版本只搭建库结构、数据契约、校验与本地检索，不包含任何作品内容，也不会自动修改正式设定。

## 已具备

- 九类逻辑库：设定、前文、大纲、角色状态、世界状态、Rule、Judgment Spec、文风审计、反馈。
- 作品、世界线、角色变体、别名、版本与当前模块注册表。
- YAML 文档模板和统一必填元数据。
- 注册引用、枚举值、角色状态身份和文档 ID 校验。
- 按自然段聚合的分块器；场景应在导入前保持为独立文档。
- SQLite FTS5 本地索引，无需启动外部服务。
- 查询时强制指定 `story_id` 和 `timeline_id`，默认只召回 `active/canon`。
- 章节确认后的人工审核更新清单。

## 快速开始

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
novel-rag validate
novel-rag index
```

当前仓库已经导入作品资料与工作流模块；实际文档和分块数量以 `validate`、`index` 输出为准，校验问题应保持为零。

## 用户提供资料后的导入顺序

1. 编辑 `novel-rag/registry/stories.yaml` 注册唯一作品 ID。
2. 编辑 `timelines.yaml` 注册世界线；同名角色有多版本时编辑 `character-variants.yaml`。
3. 从 `novel-rag/templates/` 复制相应模板到对应逻辑库，填写所有必填字段。
4. 依次导入正式设定、正式前文、当前大纲、角色状态、世界状态、Rule、Judgment Spec、文风审计和长期反馈。
5. 执行 `novel-rag validate`，修完全部错误后执行 `novel-rag index`。

模板目录不会被索引。正式前文建议使用以下结构：

```text
novel-rag/history/volume-01/chapter-001/scene-001.yaml
```

## 查询

```powershell
novel-rag search "上一章结束时发生了什么" `
  --story example-story --timeline main --type history

novel-rag search "execution_contract" `
  --story example-story --timeline main --type rule

novel-rag search "generation_plan" `
  --story example-story --timeline main --type judgment_spec
```

默认状态过滤为 `active/canon`。只有明确需要草稿或旧版时才显式使用 `--status draft` 或 `--status deprecated`。

## 检索策略

当前基线是可复现的关键词检索，适合先验证资料清洗、隔离与版本规则。以后接入向量检索时，应保留相同的强过滤顺序：

1. `story_id`
2. `timeline_id`
3. `status`（默认 active/canon）
4. `document_type`
5. 向量或关键词相关度排序

不要用相似度代替前四项过滤。混合检索后端可实现与 `SqliteIndex.search` 相同的输入/输出契约。

## 章节完成后的更新

严格遵循 [章节确认工作流](novel-rag/WORKFLOW.md)。未确认正文只能保留在仓库外的编辑区或标为 `draft`，不能成为默认检索事实，也不能更新角色或世界的 current 状态。

## 测试

```powershell
python -m pytest
```

固定的业务检索问题后续写入 `novel-rag/retrieval-tests.yaml`。除了命中正确文档，还应验证世界线隔离、版本、时间状态和资料类型。
