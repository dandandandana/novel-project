# 多小说隔离架构 v2

## 目标

系统保留可跨作品复用的规则、Judgment、Generator、Audit、文风审计与模板，但人物、前文、世界观、大纲、角色状态、世界状态和反馈必须按小说物理隔离。隔离不能只依赖查询参数，也必须体现在目录和 SQLite 文件上。

## 三层结构

### 全局目录层

`registry/stories.yaml` 只登记小说，不存放任何单部小说的世界线、人物或版本关系。`registry/layout.yaml` 固定当前布局版本为 `2.0`。

### 共享系统层

`shared/` 只允许以下系统文档：

- `rule`
- `judgment_spec`
- `generator_spec`
- `audit_spec`
- `style_audit`

这些文档统一使用 `story_id: __shared__`、`timeline_id: global`。`shared/registry/module-defaults.yaml` 定义新小说默认继承的模块，`shared/registry/version-map.yaml` 只允许指向共享文档。

### 小说隔离层

每部小说位于 `stories/<story_id>/`，包含自己的：

- 正式设定、前文与大纲；
- 角色和世界当前状态、快照与变更记录；
- 用户反馈；
- 世界线、角色变体、别名、版本表和模块映射；
- 检索回归用例；
- 可选的 `system-overrides/`。

小说文档的 `metadata.story_id` 必须等于物理目录名。普通内容不得进入 `system-overrides`；小说专属系统文档不得混入 `canon`、`history` 等内容目录。

## 索引与查询边界

索引文件按物理范围拆分：

```text
index/shared.db
index/stories/<story_id>.db
```

一次普通查询只打开目标小说的数据库和 `shared.db`。实现没有“搜索所有小说后再过滤”的步骤，因此其他小说的人物、前文和世界观不会进入候选集。`--no-shared` 会只打开目标小说数据库。

## 新建小说

```powershell
novel-rag create-story <story_id> --title "作品名"
```

该命令会创建完整隔离目录、主世界线注册、空人物/别名/版本表、检索测试文件和系统覆盖目录，并复制共享模块引用到本小说的 `module-map.yaml`。随后将资料写入新目录，执行 `validate`、`index` 和检索测试。

## 系统级更新

更新共享规则或文风时：

1. 在 `shared/<module>/` 创建新版本并废弃旧版本；
2. 更新 `shared/registry/version-map.yaml`；
3. 更新 `shared/registry/module-defaults.yaml`；
4. 对需要采用新版本的各小说更新其 `registry/module-map.yaml`；
5. 为受影响小说增加检索用例；
6. 全量校验并重建所有隔离索引。

## 单部小说回写

先将 `STORY_ROOT` 解析为 `stories/<story_id>`，随后所有设定、正文、状态、版本表和检索用例都只能在该根目录内修改。根 `registry/stories.yaml` 只更新卷章坐标，不承载人物与剧情内容。

## 备份与恢复

迁移前快照位于：

`backups/pre-multi-story-isolation-20260718-204215/`

`BACKUP-MANIFEST.json` 记录 726 个文件的相对路径、字节数和 SHA-256。迁移脚本在改动资料前逐文件验证清单。

如需恢复旧版，先停止任何写入，再将当前工作目录另行备份，然后把快照中的 `novel-rag/`、`novel_rag/`、`scripts/`、`tests/`、`README.md` 和 `pyproject.toml` 复制回 `D:\Novel`。这是覆盖式恢复，执行前必须再次确认目标目录。迁移记录保存在 `registry/migration-v2.yaml`，旧的混合索引仅归档在 `archive/legacy-index/`，运行时不会读取。

## 强制不变量

- 根目录不得重新出现旧版 `canon/`、`history/`、`rules/` 等平铺库。
- 未登记在 `registry/stories.yaml` 的小说目录无效。
- 共享版本表不得指向小说文档，小说版本表不得指向其他范围文档。
- 模块映射只能指向本小说系统覆盖或共享系统文档。
- `document_id` 在当前加载范围内必须唯一。
- 任一校验错误都会阻止索引更新。
