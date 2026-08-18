# 章节确认与知识库更新工作流

以下所有相对路径均以目标小说的隔离根 `stories/<story_id>/` 为起点；不得把人物、正文或状态回写到 `novel-rag/` 根目录。

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
10. 执行 `novel-rag validate --story <story_id>`、全量 `novel-rag index` 和该小说固定检索测试。

当前实现中，`confirm` 只完成第 1、2 步并生成 `state-writeback-proposal.json`。作者必须通过
`state-review` 查看候选状态，再用 `state-approve --yes` 选择性晋升，或用 `state-reject --yes`
拒绝；未审核的提案不会改动 current。状态晋升会在一个事务中维护 snapshot、change-log、current
和 version-map，并重新校验、索引和运行检索回归。

上传 Canon、Outline 或 Feedback 时先预览版本族。已有 current 的新资料必须使用新版本并显式
`supersedes`；旧版本改为 `deprecated`。Feedback 的解决同样创建新版本，不原地修改旧反馈。

## 版本规则

- 不无痕覆盖正式资料。
- 新版本设置新的 `document_id`、递增 `version`，并用 `supersedes` 指向旧文档 ID。
- 被替代版本改为 `deprecated`。
- `character-state/current` 每个 `story_id + timeline_id + variant_id` 只能有一个 active 文档。
- 全局文风审计放在 `shared/style-audit`；仅本作生效的文风覆盖放在 `system-overrides/style-audit`。
- 本小说的 `version-map.yaml` 不得指向共享层或其他小说文档。

## 人工审核表

- [ ] 正文已由用户明确确认。
- [ ] 每条状态变化有对应章节/场景证据。
- [ ] 没有从未来大纲推导当前事实。
- [ ] 没有混入其他世界线角色版本。
- [ ] 所有写入均位于正确的 `stories/<story_id>/`，metadata.story_id 与目录一致。
- [ ] 旧版本已标记 deprecated，supersedes 链正确。
- [ ] 检索测试未召回 draft、deprecated 或 archived 内容。
