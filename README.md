# Novel RAG

当前能力、最近有证据的验证基线、已关闭反例与开放项统一见[当前状态摘要](docs/IMPLEMENTATION_STATUS_AND_NEXT.md#current-status)。继续开发先读摘要，再定位权威架构、原组件与阶段证据；本页保留使用说明，各阶段验收数字在交接记录中按当时范围保存。

v3 信息记忆现按[信息迷雾合同](docs/HYBRID_GRAPHRAG_ARCHITECTURE.md#state-memory)区分作者参考与角色所知。CharacterView可记录渠道、世界内来源、确定程度和实际摄取依据，获知时点仍由正文检查点绑定；群体身份、在场或全知旁白不自动产生角色知识。渠道开放支持学校课堂/通知、报刊、电视广播、电话网络等，须适合本书时代，并区分发布与实际接收。[《玄鉴仙族》公开片段的传递写法](docs/references/xuanjian-information-notes.md)及用户补充的通用渠道，可通过`read_writing_reference(resource_id="information_transmission")`按需读取，各自保留来源，原八段R13资源保持。

v3 小说创作工作台已落地：[架构阅读入口](docs/HYBRID_GRAPHRAG_ARCHITECTURE.md#architecture-overview)、[实施文档（12个工作包）](docs/ENGINEERING_REFACTORING_BOUNDARIES.md#v3-implementation)、[实际验收与待办](docs/IMPLEMENTATION_STATUS_AND_NEXT.md#current-status)。

本轮续接了[三项写作体验](docs/IMPLEMENTATION_STATUS_AND_NEXT.md#writing-experience-status)：大纲、要求与未保存正文可在本机浏览器恢复，旧版本冲突先保留副本；作品旁可新建独立小说，无模型配置时可查看本机设置指引或选择外部工具；写作页大纲优先，时间线、模型和本轮方式折叠。浏览器副本只属于当前浏览器与地址，正式草稿仍需点击保存；资料和偏好编辑不在本轮刷新持久化范围。

主入口为本地网页：丢入原始大纲，让一个 LLM 连贯创作，按需读取参考、保存草稿和记忆。作者可以编辑、停止、刷新恢复、反馈续写、采用正文，并编辑偏好与简单设定/笔记。新主链没有文学审计、评分、自动修复或强制回顾。旧 generate/continue/confirm 等命令继续保留 v2 语义。

网页首页采用全屏 Metro 拼贴磁贴，使用15张现成插画：5张EEJU村正、5张其他型月、3张假面骑士，以及春日和夏日场景。四组图片磁贴每45秒渐变切换，可在设置中暂停；系统减少动态时保持静态，实时时钟和独立功能画面保留。点击“把故事写下去”进入创作，资料、偏好、记忆和工具活动可从各自磁贴打开；返回磁贴保留当前页面的未保存输入。插件/终端是明确标记的预留入口。

磁贴内容与位置由 `src/novel_rag/web/static/tiles.json` 配置；图片和画师来源在 `static/assets/manifest.json`，本地图片随安装包交付。可选 `imagePosition` 使用两个0–100整数百分比指定图片裁切焦点，例如 `50% 22%`；省略或无效时沿用磁贴位置。系统减少动态时使用静态画面，配置或图片失败仍有工作台入口。`?run=` 深链继续恢复对应草稿；完整刷新恢复服务器已保存内容。

在项目目录激活已安装的环境后启动：

```powershell
python -m novel_rag.cli --library novel-rag workspace
```

浏览器打开 http://127.0.0.1:8765。新环境按下方安装步骤安装 `.[web]`；沿用下方 api-config 或本地模型配置文件选择支持原生工具调用的 profile。网页不会显示或保存模型密钥，不需要先建 GraphRAG 索引。

网页后端未运行时，可使用同一核心的内置单次生成入口：

```powershell
python -m novel_rag.cli --library novel-rag write --story <story_id> --timeline main --outline-file outline.txt --profile default
```

后端独占同一工作区；网页运行期间用页面生成，或让 harness 连接该后端。不要另开 write 进程写入相同工作区。

## 使用自己的 harness

网页选择“自己的写作工具”，粘贴大纲并准备任务，不需要项目模型配置。页面交接区可读取原样上下文，显示当前任务的 MCP 启动命令。harness 使用自己的 LLM；五工具继续使用同一份原文、草稿和记忆。`workspace` 只启动本地后端，也可不打开浏览器使用。

已有后端运行时，CLI 可准备和读取任务：

```powershell
python -m novel_rag.cli harness prepare --backend http://127.0.0.1:8765 --story <story_id> --outline-file outline.txt --request-id outline-001
python -m novel_rag.cli harness context --backend http://127.0.0.1:8765 --run-id <返回的run_id>
```

prepare 返回 `run_id`、原样 `context` 和带 `?run=` 的工作台链接；harness 子命令使用所选后端的库，不在命令进程创建 Store。准备结果未知时沿用同一 request-id 与原参数。将 context 交给宿主自己的模型，或明确读取 MCP 的 `novel://runs/<run_id>/context`；注册资源不表示宿主已自动注入它。

在 harness 中登记以下进程为 stdio MCP server，工作目录设为本项目。替换 run_id 后启动；这份命令不修改宿主全局配置，不需要项目 API key：

```powershell
python -m novel_rag.cli harness mcp --backend http://127.0.0.1:8765 --run-id <返回的run_id>
```

模型可调用 recall、read_document、read_writing_reference、save_draft、remember。save_draft 和 remember 需要独立的稳定 `operation_id`；未知结果恢复用原编号和原参数，即使网络请求编号已改变。保存返回真实 DraftRef，记忆才可引用该正文。append_suffix 保存该 run 完整新后缀，host 只添加固定父稿一次。聊天里的最终正文不会自动保存，必须明确调用 save_draft。

已保存检查点在网页可编辑、反馈续写和作者采用。host 可显式标记结束并查看原操作结果：

```powershell
python -m novel_rag.cli harness status --run-id <run_id>
python -m novel_rag.cli harness finish --run-id <run_id> --status completed
```

stdio 退出不会结束任务。网页“停止本地工具”或 harness cancel 只关闭项目工具入口；外部模型在其宿主里停止。首版同步明确保存的检查点，不自动捕获外部 token 流。协议明确支持 MCP 2025-11-25 / 2025-06-18。已实际用 Codex CLI 0.161.0、gpt-6.1-sol/max 完成短篇保存、记忆回读和独立会话续写；首轮接口失败及修正后的证据见[实施状态](docs/IMPLEMENTATION_STATUS_AND_NEXT.md#v3-status)。Claude Code/Pi及当前新协议时代互操作仍须单独验证。具体边界见[接入合同](docs/HYBRID_GRAPHRAG_ARCHITECTURE.md#harness-integration)。

运行、接收前缀、不可变草稿、候选记忆和源版本备份默认在 outputs/.workspace；已采用正文仍是兼容 History YAML。验证基线与剩余边界统一见[当前状态摘要](docs/IMPLEMENTATION_STATUS_AND_NEXT.md#current-status)；[写作体验候选及同期整合的阶段记录](docs/IMPLEMENTATION_STATUS_AND_NEXT.md#writing-experience-status)保留各自验收范围。Metro轮图与安装包有既有阶段验收；Codex harness已有有限真实模型样本，内置profile的真实provider与长篇文学效果仍待验证。

[状态与 memory 设计](docs/HYBRID_GRAPHRAG_ARCHITECTURE.md#state-memory)按情节变化记录，不按段落数检查；区分事实、人物认知和未完成事项，保留原文回读及改稿后的来源失效。

[事件图与 router](docs/HYBRID_GRAPHRAG_ARCHITECTURE.md#event-memory-router)围绕事件线、经历与伏笔提供完整相关参考；模型用 recall/remember，默认有界展开与去重合并，不设项目默认token上限。初始上下文保留作者输入、明确正文基线和相关原文，更多原文通过现有工具按需读取。

现有资料按作品/时间线隔离。下方 shared 系统层、索引与分阶段生成说明属于 v2 兼容工具；v3 直接读取本书有效原文与小参考包，不默认注入旧文风审计或模块占位。

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

## 安装与开发环境

项目使用单一 `novel-rag` 发行包，代码在 `src/novel_rag`，作品资料保留在 `novel-rag/`。运行命令和仓库脚本前先安装包；脚本直接消费当前环境安装的代码。

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

基础安装只依赖 PyYAML；`.[model]` 提供内置模型的 HTTPX 传输，`.[web]` 提供网页并兼容包含模型传输，`.[tui]` 提供交互终端。`.[dev]` 包含这些入口、pytest、Playwright 和构建工具。浏览器测试使用本机 Chrome/Edge 或已安装的 Playwright Chromium；需要时运行 `python -m playwright install --with-deps chromium`。安装 Python 依赖不会自动安装浏览器，CI 缺少浏览器时明确失败。

默认资料根是启动时当前工作目录下的 `novel-rag/`，索引默认位于所选资料库的 `index/`；代码安装目录不存放作品资料。仓库根启动保留原位置，在其他目录使用原资料库时传入绝对路径：

```powershell
novel-rag --library D:\novel-project\novel-rag validate
novel-rag --library D:\novel-project\novel-rag workspace --workspace D:\novel-project\outputs\.workspace
```

状态模板优先读取用户资料库的 `shared/templates`、`templates`，再读取安装包内的默认模板。内置写作参考和网页静态资源随包交付，读取资源不修改用户资料。

## 兼容检索工具的快速开始

```powershell
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

## v2 从大纲生成正文（兼容入口）

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
也可以在 TUI 的“本地模型 API 配置”菜单中填写；key 输入不会回显：

```powershell
novel-rag api-config path
novel-rag api-config set `
  --name default `
  --base-url https://api.openai.com/v1 `
  --model <model-name> `
  --mode completions `
  --api-key-file <仅包含-key-的本地文件> `
  --active

novel-rag generate `
  --story <story_id> `
  --timeline main `
  --outline outline.txt
```

协议名支持别名：`chat` 即 `completions`/`openai-completions`（默认），
`responses` 即 `openai-responses`；存储层始终保存规范值 `chat`/`responses`。

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

具体顺序见 [章节确认工作流](novel-rag/WORKFLOW.md) 与 [add_rag 工作流](skills/rag-outline-to-novel/references/add_rag.md)。

## 验证

在项目虚拟环境中运行下列完成门。干净 checkout 需先建 canonical 索引，检索测试不会自动创建索引。架构边界检查包含在 pytest 中，也可单独运行 `python -m pytest -q tests/test_architecture_boundaries.py tests/test_import_boundaries.py`。

```powershell
python -m pytest -q -k "not test_file_lock_uses_windows_safe_exclusive_create_across_processes"
python -m novel_rag.cli --library novel-rag index
python scripts\run_retrieval_tests.py
python -m novel_rag.cli --library novel-rag validate
```

[CI 工作流](.github/workflows/ci.yml)在 Windows/Ubuntu、Python 3.10 上执行相同完成门、SQLite 能力检查与真实 wheel 安装验证。最新本地及远端验证范围见[当前状态摘要](docs/IMPLEMENTATION_STATUS_AND_NEXT.md#current-status)。

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
