# Novel RAG

这是一个“共享生成系统 + 多小说物理隔离”的长篇小说 RAG。规则、Judgment、Generator、Audit、文风审计和模板放在共享层；人物、前文、大纲、角色状态、世界状态与反馈按小说分别存放、分别建索引。

## 当前结构

```text
novel-rag/
├── registry/                         # 全局小说目录与布局版本
├── shared/                           # 所有小说可继承的系统层
│   ├── rules/ judgment/ generator/
│   ├── audit/ style-audit/ templates/
│   └── registry/                     # 共享模块默认值与版本表
├── stories/<story_id>/               # 某一部小说的独立资料层
│   ├── common/                       # 小说级共享资料与 registry
│   │   ├── canon/
│   │   └── registry/                 # timelines、version-map 等
│   └── timelines/<timeline_id>/      # 按世界线隔离的资料
│       ├── canon/ history/ outline/
│       ├── character-state/ world-state/ feedback/ summaries/
│       ├── registry/                 # 当前世界线的 module-map
│       ├── system-overrides/         # 必要时覆盖共享系统模块
│       └── retrieval-tests.yaml
└── index/
    ├── shared.db
    └── graphs/<story_id>/<timeline_id>.db
```

canonical GraphKey 图只写入 `index/graphs/<story_id>/<timeline_id>.db`；共享系统仍使用
`index/shared.db`。迁移期间保留旧的 `stories/<story_id>/...` 根布局和
`index/stories/<story_id>.db`，它们只作为显式 legacy 兼容输入，不会被默认检索、覆盖、删除或移动。
只有全部资料完成 GraphKey 迁移并通过验收后，才进入另行批准的归档门。

完整边界与恢复说明见 [混合 GraphRAG 架构](docs/HYBRID_GRAPHRAG_ARCHITECTURE.md)。

## 快速开始

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
novel-rag validate
novel-rag index
python scripts\run_retrieval_tests.py
```

## 新建一部小说

```powershell
novel-rag create-story second-novel --title "第二部小说"
novel-rag validate --story second-novel
novel-rag index
```

新小说会得到 `common/`、`timelines/main/`、注册表、检索测试和系统覆盖目录，并默认继承
`shared/registry/module-defaults.yaml`。内容资料必须写入对应的
`stories/second-novel/timelines/<timeline_id>/`，不能写到根目录或另一部小说下。

## 查询

```powershell
novel-rag search "上一章结束时发生了什么" `
  --story overturned-world-fujimaru --timeline main --type history

novel-rag search "native_chinese_dialogue_style" `
  --story overturned-world-fujimaru --timeline main --type style_audit

novel-rag search "只查本小说资料" `
  --story overturned-world-fujimaru --timeline main --no-shared
```

查询必须指定 `story_id` 和 `timeline_id`。默认组合“该小说独立索引 + 共享系统索引”，不会搜索其他小说；`--no-shared` 可关闭共享系统注入。默认状态仅为 `active/canon`。

## 从大纲生成正文

每部小说首次生成前，创建并填写作者偏好：

```powershell
novel-rag init-preferences --story <story_id>
```

随后通过可调用的模型命令生成正文。模型命令从标准输入接收包含 `stage` 和 `payload` 的 JSON，并向标准输出返回 JSON 或正文：

```powershell
novel-rag generate `
  --story <story_id> `
  --timeline main `
  --outline outline.txt `
  --reference reference.txt `
  --model-command "your-model-adapter"
```

推荐把模型接口保存在独立的本地配置文件中。默认位置是
`~/.novel-rag/model-api.json`，不属于 RAG、仓库或 `outputs`，可以直接用文本编辑器修改。
也可以在 TUI 菜单 12 中填写；key 输入不会回显：

```powershell
novel-rag api-config path
novel-rag api-config set `
  --name default `
  --base-url https://api.openai.com/v1 `
  --model <model-name> `
  --mode responses `
  --api-key-file <仅包含-key-的本地文件> `
  --active

novel-rag generate `
  --story <story_id> `
  --timeline main `
  --outline outline.txt
```

使用无鉴权的本地模型服务时，把地址设为 `http://localhost:1234/v1`、协议设为 `chat`，并使用
`--no-auth`。`api-config show` 只显示脱敏 key；支持多个 profile，通过 `api-config use <name>`
切换。命令行的 `--model-command`、`--api-model` 和环境变量读取只保留为兼容入口，正常使用不再需要环境变量。

不想填写长命令时，可以启动标准库行式 TUI：

```powershell
novel-rag tui
```

TUI 提供建书与作者偏好向导、生成草稿、任务冲突处理、作者指导续作、完整确认复核、状态提案审核、带版本的 Outline/RAG 上传、Feedback 管理及索引维护。TXT/Markdown 大纲会自动转换成正式的 chapter-outline YAML；同一版本族已有当前文档时，必须明确填写新版本和 `supersedes`，不会静默覆盖。RAG 上传接受符合 novel-rag 模板的 YAML；当前只允许 canon、outline 和 feedback，History 与 current 状态仍必须走正文确认/状态审核流程。确认迁移必须输入大写 `YES`，正式 RAG 上传必须输入大写 `IMPORT`。

运行时合同、上下文、草稿和审计结果保存在 `outputs/.workflow/<story_id>/<task_id>/`，不会自动写入正式 History 或当前状态。自动定向修复最多三次；仍无法解决时会请求作者继续提供写作指导。

## 写入与回写

- 全局规则、判断、生成、审计、文风模块：写入 `novel-rag/shared/`。
- 人物、设定、前文、大纲与状态：写入
  `novel-rag/stories/<story_id>/timelines/<timeline_id>/`；小说级共享资料写入 `common/`。
- 仅某部小说需要的系统规则：写入该世界线的 `system-overrides/`。
- 章节正文只有在用户确认后才能进入 `history` 并推动 current 状态。

具体顺序见 [章节确认工作流](novel-rag/WORKFLOW.md) 与 [add_rag 工作流](skills/add_rag.md)。

## 验证

```powershell
pytest -q
novel-rag validate
novel-rag index
python scripts\run_retrieval_tests.py
```

隔离版校验会拒绝未完成注册的目录、物理目录与 `metadata.story_id` 不一致、共享层混入人物/剧情资料，以及版本表跨小说引用；迁移期旧根资料只通过显式兼容入口读取。
确认生成正文并写入正式 History：

```powershell
python -m novel_rag.cli --library novel-rag confirm `
  --runtime outputs/.workflow/<story_id>/<task_id> `
  --yes --volume 1 --chapter 1 --scene 1
```

`confirm` 会校验正文、作品/时间线和运行状态，执行知识库校验、重建隔离索引并运行检索回归。
重复确认同一正文是安全的 no-op；同一场景已有不同正文时拒绝覆盖。角色和世界状态仅生成
`state-writeback-proposal.json` 待审，不会依据运行时推断自动覆盖 current。
迁移成功后会清除 runtime 中的草稿、润色稿、最终 TXT、审计、检索上下文和 Reference 临时文件，
并从 `result.json` 移除正文。只保留 contract、确认凭据、正文哈希和状态待审提案。

审核状态提案或继续需要作者指导的任务：

```powershell
novel-rag state-review --runtime outputs/.workflow/<story_id>/<task_id>
novel-rag state-approve --runtime outputs/.workflow/<story_id>/<task_id> --yes

novel-rag continue `
  --runtime outputs/.workflow/<story_id>/<task_id> `
  --guidance "保留结局，补足人物做出选择的动机" `
  --api-model <model-name>
```

`continue` 总是创建有 `parent_runtime`/`supersedes_runtime` 记录的新任务；`generate` 遇到已有 task 目录会拒绝，不再静默覆盖。状态批准只从已经确认的 History 证据生成版本化 current、snapshot、change-log 和 version-map；也可以用 `state-reject` 明确拒绝。

版本上传与 Feedback 也有非交互命令。`import-rag` 默认只预览，加 `--yes` 才提交；发生版本冲突时必须提供 `--version`、`--supersedes` 和正确的版本族。Feedback 使用 `feedback-create --yes`、`feedback-list`、`feedback-resolve --yes`，解决反馈会创建新版本并替代旧版本，不原地覆盖；TUI 新建 Feedback 也必须输入大写 `FEEDBACK`。
