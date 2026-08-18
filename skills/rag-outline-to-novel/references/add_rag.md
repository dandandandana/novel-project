# 小说生成 RAG 库搭建工作流  
## Rule / Judgment / Generator / Audit 适配版

> **隔离版 v2 路径规则（优先级最高）**  
> 本文后续出现的 `canon/`、`history/`、`outline/`、`character-state/`、`world-state/`、`feedback/` 和本小说注册表，均指 `novel-rag/stories/<story_id>/` 下的逻辑目录。  
> 全局 `rules/`、`judgment/`、`generator/`、`audit/`、`style-audit/`、`templates/` 均指 `novel-rag/shared/`；只对单部小说生效的系统模块进入其 `system-overrides/`。  
> 禁止把人物、前文和世界观放回 `novel-rag/` 根目录。索引必须拆为 `index/shared.db` 与 `index/stories/<story_id>.db`，查询不得打开其他小说的数据库。

---

# 1. 工作流目标

建立一套供小说生成 Agent 使用的 RAG 与执行规范系统，使 Agent 能够稳定完成：

- 识别当前作品、世界线和剧情坐标。
- 获取正式设定、前文、大纲和当前状态。
- 获取当前生效的生成规则。
- 由 Ruler 裁决本次任务实际有效的约束。
- 由 Judgment 在生成前判断章节中心、节点主次和描写预算。
- 由 Generator 根据临时计划生成骨架稿和渲染稿。
- 由 Audit 检查规则、判断、设定、连续性、人物和文风。
- 在用户确认后更新正文、状态、反馈和规则版本。

整个系统采用：

```text
资料层
    ↓
Ruler
    ↓
Judgment
    ↓
Generator
    ↓
Audit
    ↓
定向修订
    ↓
正式回写
```

本阶段负责：

1. 建立知识库目录。
2. 确定文档类型和元数据。
3. 建立 Rule、Judgment、Generator、Audit 模块规范。
4. 清洗和分类已有资料。
5. 建立检索与注入流程。
6. 建立运行时临时文件规范。
7. 建立正式回写与版本更新流程。
8. 建立测试集和验收标准。

本阶段不负责直接生成小说正文。

---

# 2. 核心架构原则

系统必须区分两类内容。

## 2.1 持久化知识

进入正式 RAG，用于跨任务复用：

- 正式设定。
- 正式前文。
- 当前角色和世界状态。
- 当前大纲。
- 长期有效的 Rule。
- Judgment 的判断标准与模板。
- Generator 的执行规范。
- Audit 的审计规范。
- 当前文风要求。
- 用户长期反馈。
- 用户认可的样例。

## 2.2 运行时产物

只对本次任务有效，默认不进入正式 RAG：

- `execution_contract`
- `generation_plan`
- 场景临时分级结果。
- 节点 S/A/B/C 判断。
- 当前章节篇幅预算。
- 骨架稿。
- 未确认初稿。
- 审计问题清单。
- 修订清单。
- 临时检索上下文包。

核心原则：

> Rule、Judgment Spec、Generator Spec 和 Audit Spec 可以持久化。  
> 本次 Judgment 结果、初稿和审计过程默认只保存在运行时工作区。  
> 只有用户确认长期有效的内容才能晋升为正式知识。

---

# 3. 逻辑目录结构（物理路径服从隔离版 v2 映射）

```text
novel-rag/
├── registry/                  # 仅全局小说目录与布局版本
├── shared/                    # 跨小说共享的系统规则与模板
├── stories/<story_id>/        # 单部小说人物、前文、世界观、状态和本作注册表
├── index/shared.db            # 共享系统索引
├── index/stories/<story_id>.db# 单部小说索引
│
│ # 以下名称是 stories/<story_id>/ 或 shared/ 内的逻辑槽位：
├── canon/                     # 正式设定
├── history/                   # 正式前文
├── outline/                   # 后续大纲
├── character-state/           # 角色当前状态
├── world-state/               # 世界当前状态
├── rules/                     # Ruler使用的长期生成规则
├── judgment/                  # Judgment判断标准、模板和专项协议
├── generator/                 # Generator执行规范
├── audit/                     # Audit审计规范
├── style-audit/               # 文风表现标准和样例
├── feedback/                  # 用户修改意见
├── runtime/                   # 本次运行临时产物，不进入默认RAG
└── archive/                   # 被替代、废弃和历史版本
```

推荐详细结构：

```text
novel-rag/
├── registry/
│   ├── stories.yaml
│   ├── timelines.yaml
│   ├── character-variants.yaml
│   ├── aliases.yaml
│   ├── version-map.yaml
│   └── module-map.yaml
│
├── canon/
│   ├── world/
│   ├── characters/
│   ├── abilities/
│   ├── locations/
│   ├── factions/
│   ├── history/
│   ├── terminology/
│   └── relationships/
│
├── history/
│   ├── volume-01/
│   ├── volume-02/
│   └── volume-03/
│
├── outline/
│   ├── series/
│   ├── volumes/
│   ├── chapters/
│   └── scenes/
│
├── character-state/
│   ├── current/
│   ├── snapshots/
│   └── change-logs/
│
├── world-state/
│   ├── current/
│   ├── locations/
│   ├── factions/
│   └── change-logs/
│
├── rules/
│   ├── active/
│   │   ├── global/
│   │   ├── story-specific/
│   │   └── timeline-specific/
│   ├── task-specific/
│   ├── scene-specific/
│   ├── exceptions/
│   ├── deprecated/
│   └── rule-history/
│
├── judgment/
│   ├── active/
│   │   ├── global/
│   │   ├── story-specific/
│   │   └── timeline-specific/
│   ├── task-specific/
│   ├── scene-specific/
│   ├── templates/
│   ├── validation/
│   ├── deprecated/
│   └── judgment-history/
│
├── generator/
│   ├── active/
│   │   ├── global/
│   │   ├── story-specific/
│   │   └── timeline-specific/
│   ├── task-specific/
│   ├── scene-specific/
│   ├── skeleton/
│   ├── rendering/
│   ├── output-contracts/
│   ├── deprecated/
│   └── generator-history/
│
├── audit/
│   ├── active/
│   │   ├── ruler-compliance/
│   │   ├── judgment-compliance/
│   │   ├── canon/
│   │   ├── continuity/
│   │   ├── character/
│   │   ├── structure/
│   │   └── style/
│   ├── task-specific/
│   ├── scene-specific/
│   ├── templates/
│   ├── severity/
│   ├── deprecated/
│   └── audit-history/
│
├── style-audit/
│   ├── active/
│   ├── scene-specific/
│   ├── approved-samples/
│   ├── deprecated/
│   └── audit-history/
│
├── feedback/
│   ├── global/
│   ├── character/
│   ├── style/
│   ├── plot/
│   ├── workflow/
│   └── resolved/
│
├── runtime/
│   ├── current-task/
│   │   ├── retrieved-context.yaml
│   │   ├── execution-contract.yaml
│   │   ├── generation-plan.yaml
│   │   ├── skeleton-draft.md
│   │   ├── rendered-draft.md
│   │   ├── audit-report.yaml
│   │   └── revision-plan.yaml
│   └── completed/
│
└── archive/
```

如果 RAG 系统不支持多个物理知识库，应通过 `document_type`、`module_type`、`story_id` 和 `timeline_id` 做逻辑隔离。

---

# 4. 建立作品注册表

## 4.1 stories.yaml

```yaml
stories:
  - story_id: fate-immortality
    title: Fate Immortality
    status: active
    primary_timeline: main
    current_volume: 3
    current_chapter: 12
    language: zh-CN
```

每部作品必须拥有唯一 `story_id`。

---

## 4.2 timelines.yaml

```yaml
timelines:
  - story_id: fate-immortality
    timeline_id: main
    name: 主世界线
    status: active

  - story_id: fate-immortality
    timeline_id: school-if
    name: 校园IF
    status: alternate
```

所有正文、设定、状态、大纲和模块规则都必须标记所属世界线或适用范围。

---

## 4.3 character-variants.yaml

```yaml
character_variants:
  - story_id: fate-immortality
    timeline_id: main
    character_name: 言峰士郎
    character_id: kotomine-shirou
    variant_id: kotomine-shirou-main

  - story_id: fate-immortality
    timeline_id: school-if
    character_name: 言峰士郎
    character_id: kotomine-shirou
    variant_id: kotomine-shirou-school-if
```

同名角色必须通过 `variant_id` 隔离。

---

## 4.4 module-map.yaml

登记当前生效模块版本：

```yaml
modules:
  - story_id: fate-immortality
    timeline_id: main
    module_type: rule
    active_version: rule-global-v1.2

  - story_id: fate-immortality
    timeline_id: main
    module_type: judgment_spec
    active_version: judgment-main-v1.1

  - story_id: fate-immortality
    timeline_id: main
    module_type: generator_spec
    active_version: generator-main-v1.0

  - story_id: fate-immortality
    timeline_id: main
    module_type: audit_spec
    active_version: audit-main-v1.3
```

---

# 5. 统一元数据

所有进入正式 RAG 的文档都必须包含可由模板提供的 metadata。至少填写
`story_id`、`timeline_id`、`document_type`、`title`、`version` 和 `status`；模块文档
另需 `module_type`、`priority` 和 `enforcement`。具体字段和类型以对应的共享模板为准。

## 5.1 必填字段

模块文档额外必填 `module_type`、`priority` 和 `enforcement`。

---

## 5.2 document_type 可选值

```text
registry
canon
history
outline
character_state
world_state
rule
judgment_spec
generator_spec
audit_spec
style_audit
style_sample
feedback
runtime_artifact
```

---

## 5.3 module_type 可选值

```text
ruler
judgment
generator
audit
style
none
```

---

## 5.4 status 可选值

```text
active
canon
draft
deprecated
alternate
archived
runtime
```

默认检索：

```text
active
canon
```

默认排除：

```text
deprecated
archived
draft
runtime
```

运行时工作区由工作流直接读取，不参与默认向量召回。

---

# 6. 正式设定库

目录：

```text
canon/
├── world/
├── characters/
├── abilities/
├── locations/
├── factions/
├── history/
├── terminology/
└── relationships/
```

设定库只保存：

- 用户正式确认的设定。
- 当前世界线有效的规则。
- 会持续影响后续剧情的信息。
- 角色稳定的人格核心。
- 能力明确的使用条件、限制和代价。

不得保存：

- Agent 临时推测。
- 未确认草案。
- 单次运行的 Judgment 结果。
- 本次生成的临时补充。
- 已废弃版本。

人物设定文档必须直接从
`novel-rag/shared/templates/character-canon.yaml` 创建；不要在技能或引用资料中复制
YAML 形状。写入前填充通用元数据和人物字段，并用 `load_document` 与
`validate_document` 校验。

---

# 7. 正式前文库

只存用户确认采用的正文。

推荐切块：

```text
作品
→ 卷
→ 章
→ 场景
→ 自然段组
```

每个场景块建议：

```text
800—2500个中文字符
```

正文文档必须直接从 `novel-rag/shared/templates/history-scene.yaml` 创建，并保留其
元数据与字段类型；用户确认后再写入 `history`。旧正文标记为 deprecated 并填写
supersedes。

旧正文必须标记：

```yaml
status: deprecated
supersedes:
```

---

# 8. 大纲库

目录：

```text
outline/
├── series/
├── volumes/
├── chapters/
└── scenes/
```

大纲文档必须直接从 `novel-rag/shared/templates/chapter-outline.yaml` 创建。该文件
是 outline 的唯一维护形状；填充本次任务需要的字段后，先通过
`load_document` 与 `validate_document`，再保存到 `outline/`。

大纲说明“必须发生什么”，但不直接决定：

- 哪个节点是 S/A/B/C。
- 每个节点写多少。
- 是否独立成段。
- 是否允许高密度描写。

这些由 Judgment 在本次任务中动态判断。

---

# 9. 角色状态库

目录：

```text
character-state/
├── current/
├── snapshots/
└── change-logs/
```

状态只能根据最终正式正文更新。

禁止根据：

- 未来大纲。
- 初稿。
- generation_plan。
- Agent 推测。
- 未经确认的讨论。

当前状态文档必须直接从
`novel-rag/shared/templates/character-current.yaml` 创建，并提供
`metadata.character_id` 与 `metadata.variant_id`。只根据用户确认的最终正文更新
`character-state/current`；不要从大纲、初稿或推测更新。

---

# 10. 世界状态库

保存：

- 地点损毁。
- 阵营变化。
- 当前控制权。
- 公众认知。
- 隐藏变化。
- 世界规则临时失效。
- 战场残留。
- 当前资源归属。

世界状态文档必须直接从 `novel-rag/shared/templates/world-current.yaml` 创建。保持
该模板的字段类型，填充当前时间线后验证，再写入 `world-state/current`。

---

# 11. Rule 模块

## 11.1 Rule 的职责

Rule 保存长期有效的判断与执行标准，包括：

- Ruler 冲突裁决顺序。
- 硬约束与软约束定义。
- 哪些资料可以覆盖哪些资料。
- 哪些行为禁止发生。
- 如何处理版本、世界线和草案。
- 何时允许例外。
- 如何判断资料是否进入本次上下文。
- Generator 和 Audit 必须遵守的全局协议。

Rule 不保存：

- 本章具体哪个节点是 S 级。
- 本章具体写多少字。
- 本章临时情绪曲线。
- 本次生成的 execution_contract。
- 具体正文。

---

## 11.2 Rule 类型

```text
hard_constraint
decision_rule
workflow_rule
priority_rule
soft_constraint
exception_rule
retrieval_rule
writeback_rule
```

---

## 11.3 Rule 模板

```yaml
metadata:
  story_id:
  timeline_id:
  document_type: rule
  module_type: ruler
  rule_id:
  title:
  rule_type:
  rule_scope:
  task_type:
  scene_type:
  priority:
  enforcement:
  version:
  status:
  supersedes:
  source_feedback:

rule:
  purpose:

  applies_when:
    -

  required_inputs:
    -

  decision_criteria:
    -

  required_actions:
    -

  prohibited_actions:
    -

  exceptions:
    -

  conflict_resolution:

  validation:
    -
```

---

## 11.4 Rule 优先级

生成规则冲突时：

```text
1. 用户当前明确要求
2. 当前任务专项 mandatory Rule
3. 当前场景专项 mandatory Rule
4. 当前世界线 Rule
5. 当前作品 Rule
6. 全局 Rule
7. preferred / advisory
```

内容事实冲突时：

```text
1. 用户当前明确修改
2. 明确承担设定修改功能的当前大纲
3. 当前 active Canon
4. 正式 History
5. 当前 State
6. 旧版资料
7. Agent 推断
```

注意：

- 大纲中的未来计划不能倒推为当前事实。
- State 与正式 History 冲突时，以 History 为准。
- Style 不得覆盖事实。
- Rule 不得删除大纲硬节点。

---

## 11.5 Ruler 输出规范

Ruler 运行后生成：

```yaml
execution_contract:
  identity:
  task:

  must_happen:
    -

  must_preserve:
    -

  must_not_happen:
    -

  forbidden_reveals:
    -

  canon_limits:
    -

  character_limits:
    -

  continuity_limits:
    -

  active_generation_rules:
    -

  active_style_rules:
    -

  allowed_inventions:
    -

  unresolved_but_nonblocking:
    -

  blocking_unknowns:
    -

  exception_permissions:
    -

  authority_notes:
    -
```

保存位置：

```text
runtime/current-task/execution-contract.yaml
```

默认不进入正式 RAG。

---

# 12. Judgment 模块

## 12.1 Judgment 的职责

Judgment 负责将 Ruler 的执行合同转化为本次正文的具体施工计划。

它判断：

- 本章真正的目标是什么。
- 核心情绪是什么。
- 核心信息是什么。
- 谁发生主要变化。
- 每个节点承担什么功能。
- 每个节点是 S/A/B/C 哪一级。
- 哪些节点可以合并。
- 哪些节点应删除。
- 每个节点允许使用多少篇幅和描写资源。
- 情绪曲线如何组织。
- 哪些召回资料只用于约束，不进入正文。

---

## 12.2 Judgment 持久化内容

进入正式 RAG 的是：

- 判断标准。
- 节点功能定义。
- S/A/B/C 判定规则。
- 合并规则。
- 篇幅预算规则。
- 情绪曲线规则。
- 战斗、感情、恐怖、日常等专项判断协议。
- Judgment 输出模板。
- Judgment 自检规则。

不进入正式 RAG 的是：

- 本章具体分级结果。
- 本次 generation_plan。
- 本次节点预算。
- 本次删除清单。

---

## 12.3 Judgment Spec 模板

```yaml
metadata:
  story_id:
  timeline_id:
  document_type: judgment_spec
  module_type: judgment
  judgment_id:
  title:
  judgment_scope:
  task_type:
  scene_type:
  priority:
  enforcement:
  version:
  status:
  supersedes:

judgment:
  purpose:

  required_inputs:
    -

  chapter_core_schema:

  node_functions:
    -

  importance_criteria:
    S:
      -
    A:
      -
    B:
      -
    C:
      -

  merge_criteria:
    -

  budget_policy:

  emotional_curve_policy:

  information_release_policy:

  prohibited_judgments:
    -

  validation:
    -
```

---

## 12.4 节点功能

```text
causal_progress
information_delivery
character_revelation
relationship_change
emotional_build
threat_escalation
decision
turning_point
payoff
foreshadowing
transition
atmosphere_support
```

---

## 12.5 S/A/B/C 判断标准

### S级

- 改变章节核心结果。
- 产生不可逆关系变化。
- 角色作出关键选择。
- 揭露核心真相。
- 完成主要战斗胜负。
- 核心认知发生变化。
- 承担最终情绪落点。

### A级

- 直接支撑 S 级节点成立。
- 改变当前行动方向。
- 提供关键因果。
- 显著改变危险程度。
- 形成新的目标、怀疑或判断。
- 承担必要蓄力或直接后果。

### B级

- 转场。
- 进出场。
- 普通动作连接。
- 必要但低价值的信息转交。
- 空间与时间连续。
- 短暂缓冲。

B 级通常在一至三句内完成。

### C级

删除后不影响：

- 因果。
- 人物判断。
- 情绪积累。
- 人物关系。
- 场景结果。
- 后续剧情。

C 级原则上删除。

---

## 12.6 Judgment 输出

```yaml
generation_plan:
  chapter_core:
    chapter_goal:
    dramatic_question:
    emotional_center:
    information_center:
    primary_character_change:
    required_end_state:

  scenes:
    - scene_id:
      goal:
      viewpoint:
      opening_state:
      ending_state:
      emotional_curve:
      nodes:
        - node_id:
          event:
          primary_function:
          secondary_functions:
          importance:
          judgment_basis:
          treatment:
          merge_with:
          relative_weight:
          max_sentences:
          max_paragraphs:
          required_effect:
          information_release:
          allowed_detail:
          forbidden_treatment:

  global_budget:
    target_length:
    core_scene_ratio:
    transition_ratio:
    dialogue_ratio:
    description_ratio:

  protected_elements:
    -

  compression_targets:
    -

  deletion_targets:
    -

  style_permissions:
    -

  final_validation_targets:
    -
```

保存位置：

```text
runtime/current-task/generation-plan.yaml
```

默认不进入正式 RAG。

---

# 13. Generator 模块

## 13.1 Generator 的职责

Generator 只负责执行：

```text
execution_contract
+ generation_plan
+ writing_context
```

Generator 不得：

- 重新裁决资料优先级。
- 自行改变大纲硬约束。
- 绕过 Judgment 逐条扩写大纲。
- 擅自提高 B 级节点描写预算。
- 因召回了资料就强行写入正文。
- 在生成阶段新增重大设定。

---

## 13.2 Generator 持久化内容

进入正式 RAG：

- 骨架生成规范。
- 渲染生成规范。
- 对话、动作、情绪、设定表现协议。
- 各场景类型执行协议。
- 输出格式。
- 禁止事项。
- Generator 与 Judgment 的接口约束。

不进入正式 RAG：

- 骨架稿。
- 渲染初稿。
- 未确认正文。
- 本次临时补充内容。

---

## 13.3 Generator Spec 模板

```yaml
metadata:
  story_id:
  timeline_id:
  document_type: generator_spec
  module_type: generator
  generator_id:
  title:
  generator_scope:
  task_type:
  scene_type:
  priority:
  enforcement:
  version:
  status:
  supersedes:

generator:
  purpose:

  required_inputs:
    -

  preconditions:
    -

  skeleton_protocol:
    -

  rendering_protocol:
    -

  dialogue_protocol:
    -

  action_protocol:
    -

  emotion_protocol:
    -

  exposition_protocol:
    -

  output_contract:

  prohibited_actions:
    -

  completion_checks:
    -
```

---

## 13.4 两阶段生成

### 第一阶段：低修辞骨架稿

只确保：

- 因果清楚。
- 动作清楚。
- 对话功能清楚。
- 人物判断清楚。
- 场景目标清楚。
- 大纲硬事件完整。
- C 级节点没有回流。
- B 级节点已经压缩。

骨架使用：

```text
行动
→ 反馈
→ 判断
→ 新行动
```

禁止：

- 全篇统一加感官。
- 全篇统一加意象。
- 每个动作都镜头化。
- 每个段落都高张力。
- 为“像小说”提前平均润色。

### 第二阶段：受控文风渲染

只强化：

- S 级节点。
- Judgment 授权的 A 级节点。
- 重要开场基准。
- 高潮前必要静止。
- 关键结果的直接后果。

原则上不强化：

- 普通移动。
- 进门、落座、转身。
- 无变化观察。
- 普通寒暄。
- 单纯连接信息的 B 级节点。

---

## 13.5 Generator 输入接口

```yaml
generator_input:
  execution_contract:
  generation_plan:
  writing_context:
  active_style_rules:
  approved_samples:
```

缺少 `execution_contract` 或 `generation_plan` 时，不得进入正式生成。

---

# 14. Audit 模块

## 14.1 Audit 的职责

Audit 不只是文风检查。

它必须分层检查：

```text
1. Ruler 合规
2. Judgment 执行
3. 大纲与 Canon
4. 连续性
5. 人物
6. 场景结构
7. 文风
8. 句词
```

---

## 14.2 Audit 持久化内容

进入正式 RAG：

- 审计维度。
- 检查模板。
- 严重级别。
- 各场景专项审计规则。
- 允许自动修复与必须回退的条件。
- 修订顺序。
- 审计失败阈值。

不进入正式 RAG：

- 本次审计报告。
- 本次问题定位。
- 本次修订清单。
- 本次差异比较。

---

## 14.3 Audit Spec 模板

```yaml
metadata:
  story_id:
  timeline_id:
  document_type: audit_spec
  module_type: audit
  audit_id:
  title:
  audit_scope:
  task_type:
  scene_type:
  priority:
  enforcement:
  version:
  status:
  supersedes:

audit:
  purpose:

  required_inputs:
    -

  dimensions:
    -

  checks:
    -

  severity_policy:

  auto_fix_policy:

  rerun_conditions:

  prohibited_fixes:
    -

  completion_criteria:
    -
```

---

## 14.4 审计严重级别

```text
critical
major
moderate
minor
cosmetic
```

### critical

- 改变大纲核心结果。
- 混入其他世界线。
- 使用废弃设定。
- 人物知道不应知道的信息。
- 提前揭露核心秘密。
- 核心节点被遗漏。

### major

- 关键人物行为失真。
- Judgment 主次严重失衡。
- B 级过渡抢占主要篇幅。
- 战斗胜负过程无法成立。
- 关系变化缺少必要过程。

### moderate

- 情绪曲线失衡。
- 场景转折不清楚。
- 信息释放过快或过慢。
- 多段重复同一功能。

### minor

- 个别句式机械。
- 局部动作重复。
- 连接词使用单调。
- 单句表达含混。

### cosmetic

- 标点。
- 个别词汇。
- 轻微节奏问题。

---

## 14.5 Ruler 合规审计

```yaml
ruler_audit:
  must_happen_complete:
  must_preserve_intact:
  prohibited_events_absent:
  forbidden_reveals_absent:
  canon_limits_respected:
  character_limits_respected:
  allowed_inventions_not_exceeded:
  exceptions_used_legally:
```

---

## 14.6 Judgment 执行审计

```yaml
judgment_audit:
  chapter_core_visible:
  core_nodes_received_priority:
  node_order_respected:
  merged_nodes_remain_merged:
  b_nodes_within_budget:
  c_nodes_absent:
  emotional_curve_respected:
  information_release_respected:
  unauthorized_expansion:
  unauthorized_symbolism:
  transition_overwriting:
  density_distribution:
```

重点检查：

- 核心节点是否获得最高篇幅。
- B 级节点是否超过预算。
- C 级节点是否回流。
- 已合并节点是否重新拆开。
- 普通过渡是否比核心转折更长。
- 是否对全篇平均润色。
- 是否连续多个段落保持同一高密度。
- 是否出现未经授权的心理、环境或意象扩写。

---

## 14.7 设定与连续性审计

检查：

- 人物能力。
- 能力限制和代价。
- 世界规则。
- 阵营关系。
- 时间。
- 地点。
- 人物位置。
- 伤势。
- 道具。
- 能力消耗。
- 已知和未知信息。
- 关系状态。
- 上一场景未完成动作。

---

## 14.8 人物审计

人物行动必须符合：

```text
性格核心
+ 当前状态
+ 已知信息
+ 当前目标
+ 人物关系
+ 当前压力
+ 实际能力
```

检查：

- 是否降智。
- 是否失忆。
- 是否突然改变核心性格。
- 是否直接说出应隐藏的内心。
- 是否成为纯设定说明工具。
- 情绪和关系变化是否有过程。

---

## 14.9 文风审计

检查：

```yaml
style_audit:
  viewpoint_consistency:
  narrative_distance:
  sentence_rhythm:
  paragraph_density:
  action_clarity:
  dialogue_authenticity:
  emotional_tension:
  sensory_specificity:
  information_density:
  repetition:
  connector_usage:
  sound_expression:
  metaphor_control:
  scene_transition:
  ending_strength:
  forbidden_patterns:
```

重点识别：

- 大纲腔。
- 摘要腔。
- AI 式总结。
- 空泛情绪。
- 人物语气同质化。
- 比喻堆积。
- 过度解释。
- 否定前置滥用。
- 转场机械。
- 声音词和连接词机械配给。
- 用华丽语言掩盖事件不足。

文风审计不得修改大纲结果或 Judgment 主次。

---

## 14.10 修订顺序

```text
1. Ruler 合规错误
2. 大纲和设定错误
3. 连续性错误
4. 人物错误
5. Judgment 执行错误
6. 场景结构和节奏
7. 文风
8. 句词
```

只有以下情况重新运行 Judgment：

- 章节中心判断错误。
- 场景划分错误。
- 多数节点权重失真。
- 大纲结构发生变化。
- Ruler 裁决发生变化。

局部句词问题不得重新规划整章。

---

# 15. 文风审计库

`style-audit` 专门保存“正文表现标准”。

它不负责：

- 裁决版本。
- 判断节点权重。
- 分配篇幅。
- 决定哪些大纲节点合并。
- 修改剧情事实。

正式文风审计必须直接从 `novel-rag/shared/templates/style-audit.yaml` 创建。
该文件是 style audit 的唯一维护形状；审计内容应约束正文表现，不得改写剧情事实。

---

# 16. Feedback 模块

Feedback 保存用户对历史结果的意见。

反馈文档必须直接从 `novel-rag/shared/templates/feedback.yaml` 创建。填充目标、
问题、用户意见及修正规则后验证，再写入 `feedback/`；一次性修改不得立即晋升为全局
Rule。

反馈处理：

```text
用户反馈
    ↓
判断是一次性问题还是可复现问题
    ↓
写入 feedback
    ↓
多次验证
    ↓
确认适用范围
    ↓
晋升到 Rule / Judgment Spec / Generator Spec / Audit Spec / Style Audit
    ↓
原反馈标记 resolved
```

晋升示例：

```yaml
status: resolved
promoted_to: judgment-narrative-weight-v1.1
```

一次性修改不得立即晋升为全局 Rule。

---

# 17. Runtime 工作区

运行时目录：

```text
runtime/current-task/
├── retrieved-context.yaml
├── execution-contract.yaml
├── writing-context.yaml
├── generation-plan.yaml
├── skeleton-draft.md
├── rendered-draft.md
├── audit-report.yaml
└── revision-plan.yaml
```

## 17.1 retrieved-context.yaml

记录本次检索得到的最小必要资料和来源索引。

## 17.2 execution-contract.yaml

Ruler 裁决结果。

## 17.3 writing-context.yaml

压缩后的生成上下文。

## 17.4 generation-plan.yaml

Judgment 临时计划。

## 17.5 skeleton-draft.md

低修辞骨架稿。

## 17.6 rendered-draft.md

受控渲染稿。

## 17.7 audit-report.yaml

本次多层审计结果。

## 17.8 revision-plan.yaml

定向修订计划。

这些文件默认：

```yaml
status: runtime
```

不进入默认 RAG。

任务完成后可移动到：

```text
runtime/completed/
```

但仍不得作为正式事实召回。

---

# 18. 完整检索与执行流程

```text
阶段0：识别任务范围
    ↓
阶段1：检索 registry
    ↓
阶段2：检索 outline
    ↓
阶段3：检索 current state 和邻近 history
    ↓
阶段4：检索相关 canon
    ↓
阶段5：检索 active rules
    ↓
阶段6：检索 judgment spec
    ↓
阶段7：检索 generator spec
    ↓
阶段8：检索 audit spec 和 style-audit
    ↓
阶段9：Ruler 输出 execution_contract
    ↓
阶段10：压缩 writing_context
    ↓
阶段11：Judgment 输出 generation_plan
    ↓
阶段12：Generator 生成 skeleton
    ↓
阶段13：Generator 受控渲染
    ↓
阶段14：Audit 多层检查
    ↓
阶段15：定向修订
    ↓
阶段16：最终输出
    ↓
阶段17：用户确认
    ↓
阶段18：正式回写 history / state / feedback / module versions
```

---

# 19. 检索注入规则

## 19.1 Ruler 注入

注入：

- 用户当前要求。
- 当前大纲。
- Canon。
- History。
- State。
- Rule。
- 版本信息。

不需要注入全部文风样例。

---

## 19.2 Judgment 注入

注入：

- execution_contract。
- 当前大纲。
- 当前状态。
- 邻近前文摘要。
- Judgment Spec。
- 目标篇幅。

不需要注入所有历史章节。

---

## 19.3 Generator 注入

注入：

- execution_contract。
- generation_plan。
- 压缩后的 writing_context。
- 当前 Generator Spec。
- 当前 Style Audit。
- 少量相关 approved samples。

禁止直接注入全部召回资料。

---

## 19.4 Audit 注入

注入：

- execution_contract。
- generation_plan。
- 最终草稿。
- Audit Spec。
- Canon / State 摘要。
- 当前 Style Audit。

Audit 必须能比较：

```text
计划
vs
正文
```

而不只是单独评价正文。

---

# 20. 资料导入顺序

## 第一步：Registry

导入：

- 作品。
- 世界线。
- 角色版本。
- 当前卷章。
- 模块版本。

## 第二步：Canon

优先：

- 主角。
- 当前剧情涉及角色。
- 当前能力。
- 当前地点。
- 当前关系。

## 第三步：History

按照：

```text
卷 → 章 → 场景
```

导入正式正文。

## 第四步：Outline

先导入当前卷和最近章节。

## 第五步：State

建立当前角色和世界快照。

## 第六步：Rule

先导入：

- 冲突裁决。
- 世界线隔离。
- 版本规则。
- 禁止事项。
- 状态回写规则。

## 第七步：Judgment Spec

先导入：

- 章节中心判断。
- 节点功能。
- S/A/B/C。
- 合并规则。
- 篇幅预算。
- 情绪曲线。

## 第八步：Generator Spec

先导入：

- 骨架生成。
- 受控渲染。
- 对话。
- 动作。
- 情绪。
- 设定表现。

## 第九步：Audit Spec

先导入：

- Ruler 合规。
- Judgment 执行。
- Canon。
- 连续性。
- 人物。
- 文风。

## 第十步：Style Audit 与样例

导入当前版本和少量代表片段。

## 第十一步：Feedback

导入持续影响后续任务的问题。

---

# 21. 测试集

## 21.1 Rule / Ruler 测试

```text
当前世界线应使用哪个角色版本？
大纲与旧设定冲突时谁优先？
State 与正式正文冲突时如何处理？
哪些资料必须排除？
本次允许 Agent 补充到什么程度？
```

验收：

- 不混入 IF 线。
- 不使用 deprecated。
- 不把未来大纲当当前事实。
- 能输出明确 execution_contract。

---

## 21.2 Judgment 测试

```text
Agent能否自行识别章节中心？
能否判断节点S/A/B/C？
能否合并连续动作节点？
能否压缩进门、赶路和落座？
能否识别表面大场面不是核心节点？
能否建立有起伏的情绪曲线？
```

验收：

- 不平均扩写。
- 不把所有大纲条目视为同等重要。
- 能删除 C 级。
- 能限制 B 级篇幅。
- 能输出 generation_plan。

---

## 21.3 Generator 测试

```text
是否会绕过generation_plan？
是否会给B级节点自动加高密度描写？
是否能先生成骨架再渲染？
是否会把召回资料全部写进正文？
是否能区分骨架阶段和渲染阶段？
```

验收：

- 核心节点完整。
- 过渡简洁。
- 不出现全篇平均润色。
- 不新增重大设定。
- 不输出工作流内容。

---

## 21.4 Audit 测试

```text
能否发现核心节点篇幅不足？
能否发现B级过渡超过预算？
能否发现C级内容回流？
能否发现人物知道不该知道的信息？
能否发现其他世界线设定混入？
能否区分结构问题和句词问题？
```

验收：

- 审计报告能够定位问题。
- 修订顺序正确。
- 不先润色事实错误。
- 只有必要时才重跑 Judgment。

---

# 22. 版本更新规则

所有模块修改必须版本化。

```yaml
version: 1.2
status: active
supersedes: judgment-main-v1.1
```

旧版：

```yaml
status: deprecated
```

默认只召回：

```text
active
canon
```

禁止无痕覆盖。

---

# 23. 正式回写流程

每完成一个用户确认的正式章节：

```text
最终正文
    ↓
写入 history
    ↓
提取角色变化
    ↓
写入 character-state/change-logs
    ↓
生成 snapshots
    ↓
更新 current
    ↓
提取世界变化
    ↓
更新 world-state
    ↓
标记已完成大纲节点
    ↓
写入用户反馈
    ↓
判断是否需要升级 Rule / Judgment / Generator / Audit / Style
```

禁止根据：

- 大纲。
- generation_plan。
- skeleton。
- 未确认初稿。

更新 current 状态。

---

# 24. MVP 搭建顺序

## MVP 第一阶段

```text
registry
canon
history
outline
rules
judgment
generator
audit
style-audit
```

目标：

- 能识别作品与世界线。
- 能找到正式设定和前文。
- 能找到当前大纲。
- 能完成 Ruler 裁决。
- 能完成 Judgment 分级。
- 能按照计划生成。
- 能执行多层审计。

## MVP 第二阶段

增加：

```text
character-state
world-state
```

目标：

- 精确维护角色和世界连续性。

## MVP 第三阶段

增加：

```text
feedback
approved-samples
```

目标：

- 吸收用户长期修正。
- 建立稳定表现样例。

## MVP 第四阶段

增加自动化：

```text
用户确认正文
→ 自动提取状态变化
→ 人工审核
→ 回写current
→ 检查是否需要模块版本升级
```

---

# 25. 完成标准

只有满足以下条件，系统才可以接入正式小说生成：

- 每部作品有唯一 `story_id`。
- 每条世界线有唯一 `timeline_id`。
- 同名角色有明确 `variant_id`。
- 正式资料和草案已隔离。
- 前文已按场景切块。
- 当前大纲可单独检索。
- 主要角色有 current 状态。
- Rule 可以单独检索。
- Judgment Spec 可以单独检索。
- Generator Spec 可以单独检索。
- Audit Spec 可以单独检索。
- 废弃版本默认不会召回。
- Ruler 能输出 execution_contract。
- Judgment 能输出 generation_plan。
- Generator 不会绕过 Judgment。
- Audit 能比较计划与正文。
- 可以识别并压缩低价值过渡。
- 可以保留关键情绪蓄力。
- 可以检测平均用力和过渡堆料。
- 最终正文确认前不会更新正式状态。

---

# 26. 核心维护原则

整个系统始终遵循：

> Canon 存放不轻易变化的事实。  
> History 存放已经发生的事实。  
> State 存放当前状态。  
> Outline 存放尚未发生但必须执行的计划。  
> Rule 存放长期裁决与执行标准。  
> Judgment Spec 存放如何判断本次正文主次的方法。  
> Generator Spec 存放如何执行 generation_plan。  
> Audit Spec 存放如何验证成品。  
> Style Audit 存放正文表现标准。  
> Feedback 存放用户对系统的长期纠正。  

任何资料进入正式知识库前，必须回答：

1. 它属于哪部作品？
2. 它属于哪条世界线？
3. 它是什么类型？
4. 它是事实、规则、判断标准、执行规范还是审计标准？
5. 它是正式版本还是草案？
6. 它描述的是过去、现在还是未来？
7. 它是长期有效还是仅对本次任务有效？
8. 它是否替代旧版本？
9. 它应进入 RAG 还是 runtime？
10. 它是否经过用户确认？

无法回答这些问题的资料，不应进入正式 RAG。

---

# 27. 最终执行原则

```text
RAG提供材料
Ruler确定什么有效
Judgment确定怎么分配叙事资源
Generator按照计划执行
Audit验证有没有写对、有没有按计划写
用户确认后才正式回写
```

最终目标不是让 Agent “读取更多资料”。

最终目标是让 Agent：

> 只读取当前需要的资料，  
> 先裁决，再判断，后生成，最后检查，  
> 并且把叙事资源集中到真正重要的节点上。
