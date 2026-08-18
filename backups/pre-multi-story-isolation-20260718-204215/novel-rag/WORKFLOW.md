# 章节确认与知识库更新工作流

## 进入正式库的前置条件

只有用户明确确认的正文才能标记为 `canon`。初稿、讨论记录、Agent 推测及尚未发生的大纲内容都不能更新当前状态。

## 固定顺序

1. 用户确认章节为正式版本。
2. 按场景拆分正文并写入 `history/volume-XX/chapter-XXX/`。
3. 提取主要角色变化，生成人工待审的 change log。
4. 人工核对变化证据只来自已确认正文。
5. 保存章节后完整角色快照，并以版本化方式更新 `character-state/current`。
6. 提取地点、阵营和全局变化，人工审核后更新 `world-state`。
7. 更新未解决事件与伏笔。
8. 将已执行的大纲节点生成新版本；旧版标记 `deprecated` 并由 `supersedes` 串联。
9. 保存用户对本章的长期反馈。
10. 执行 `novel-rag validate`、`novel-rag index` 和固定检索测试。

## 版本规则

- 不无痕覆盖正式资料。
- 新版本设置新的 `document_id`、递增 `version`，并用 `supersedes` 指向旧文档 ID。
- 被替代版本改为 `deprecated`。
- `character-state/current` 每个 `story_id + timeline_id + variant_id` 只能有一个 active 文档。
- 每部作品每条世界线最好只保留一个全局 active 文风审计文档。

## 人工审核表

- [ ] 正文已由用户明确确认。
- [ ] 每条状态变化有对应章节/场景证据。
- [ ] 没有从未来大纲推导当前事实。
- [ ] 没有混入其他世界线角色版本。
- [ ] 旧版本已标记 deprecated，supersedes 链正确。
- [ ] 检索测试未召回 draft、deprecated 或 archived 内容。

