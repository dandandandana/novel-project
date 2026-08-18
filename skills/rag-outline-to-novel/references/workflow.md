---
name: rag-outline-to-novel
description: >
  从RAG知识库中检索小说设定、正式前文、当前状态、后续大纲、生成规则、
  文风审计与用户反馈；先由Ruler裁决本次任务的有效约束，再由Judgment完成
  生成前叙事判断，随后生成正文并执行多层审计与定向修订。
  适用于单场景、单章节、连续章节、长篇续写、重写及多世界线作品管理。
---

# RAG Outline to Novel Workflow

## 1. 工作流目标

本技能用于把用户提供或RAG检索得到的大纲扩写为可以直接使用的小说正文。

整个工作流必须形成以下闭环：

```text
RAG资料检索
    ↓
Ruler：裁决本次任务什么有效、什么优先、什么禁止
    ↓
Judgment：判断本章真正该怎么写、哪里展开、哪里压缩
    ↓
Generator：依据判断结果生成骨架稿与渲染稿
    ↓
Audit：检查正文是否遵守Ruler与Judgment
    ↓
定向修订
    ↓
最终正文与状态更新
```

核心分工：

> 大纲决定接下来必须发生什么。  
> Canon决定什么能够成立。  
> History与State决定故事现在处于什么状态。  
> Rule决定Agent应按照什么标准判断和执行。  
> Ruler裁决本次任务实际生效的约束。  
> Judgment把约束转化为本次正文的施工计划。  
> Generator负责执行计划。  
> Audit负责确认成品没有偏离计划与资料。

本技能必须做到：

1. 保留大纲中的核心事件、人物关系、胜负结果和章节结论。
2. 保证人物、世界观、时间线、伤势、知识与能力状态连续。
3. 不把RAG召回资料无差别塞入正文。
4. 不按大纲条目平均扩写。
5. 在生成前判断叙事主次、场景功能、篇幅预算和情绪曲线。
6. 在生成后检查正文是否服从生成前判断。
7. 优先呈现故事，而不是解释故事或展示工作流。

除非用户明确要求查看，不输出内部检索记录、裁决表、判断表、审计过程或状态表。

---

# 2. 触发条件

当用户提出以下请求时启用本技能：

- 根据大纲写小说。
- 将剧情梗概扩写成正文。
- 根据章节规划生成具体章节。
- 从现有断点续写小说。
- 根据世界书、人物卡、前文和大纲生成后续。
- 根据指定文风生成或重写剧情。
- 将若干零散剧情点连接为完整场景。
- 对已有正文进行遵循设定与文风规则的系统性重写。

如果用户只要求分析剧情、设计设定、评价人物或整理大纲，不进入正文生成流程，除非用户明确要求“写出来”“扩写”“续写”或“重写正文”。

---

# 3. 系统模块

本工作流由四个核心执行模块和一个资料层组成。

## 3.1 资料层

RAG知识库可以包含：

```text
registry
canon
history
outline
character-state
world-state
rules
style-audit
approved-samples
feedback
```

各库职责：

- `registry`：作品、世界线、角色版本与资料版本索引。
- `canon`：正式设定，回答“什么是真的、什么能够成立”。
- `history`：正式前文，回答“什么已经发生”。
- `outline`：未来计划，回答“本次必须发生什么”。
- `character-state`：人物当前状态。
- `world-state`：地点、阵营和世界当前状态。
- `rules`：生成判断与执行标准。
- `style-audit`：正文表现方式与禁止表达。
- `approved-samples`：用户认可的局部表现样例。
- `feedback`：用户对历史结果的修改意见。

资料层只提供材料，不直接决定正文篇幅和场景权重。

---

## 3.2 Ruler

Ruler是约束裁决器。

它负责：

- 确定本次任务属于哪部作品和哪条世界线。
- 判断哪些资料版本有效。
- 解决用户指令、大纲、设定、前文、状态、Rule和文风之间的冲突。
- 区分硬约束、软约束、允许补充和禁止事项。
- 输出本次任务唯一有效的 `execution_contract`。

Ruler不负责：

- 写正文。
- 给每个节点分配具体篇幅。
- 设计句子。
- 决定某个节点是S、A、B还是C。
- 为了节奏删除大纲硬事件。

---

## 3.3 Judgment

Judgment是生成前叙事判断器。

它根据：

```text
execution_contract
+ 当前状态
+ 大纲
+ 邻近前文
+ 当前场景信息
```

判断：

- 本章真正的核心目标。
- 核心情绪与核心信息。
- 每个节点承担什么叙事功能。
- 每个节点属于S、A、B还是C。
- 哪些节点可以合并。
- 哪些内容应删除或一句带过。
- 各节点的篇幅、描写和节奏预算。
- 情绪如何蓄力、升级、释放和收束。
- 哪些资料需要进入正文，哪些只用于约束。

Judgment输出临时的 `generation_plan`。

Judgment结果通常不写入RAG，因为它只对本次任务有效。

---

## 3.4 Generator

Generator只负责执行：

```text
execution_contract
+ generation_plan
+ 压缩后的writing_context
```

Generator不得跳过Judgment直接把大纲逐条扩写。

Generator采用两阶段生成：

1. 低修辞骨架稿。
2. 受控文风渲染稿。

---

## 3.5 Audit

Audit是生成后的检查器。

它必须检查：

- 正文是否符合Ruler裁决出的约束。
- 正文是否落实Judgment的篇幅和主次判断。
- 正文是否符合Canon、History和State。
- 正文是否符合Style Audit。
- 正文是否产生新的逻辑、连续性或信息释放问题。

Audit发现问题后生成内部修订清单，并进行定向修订。

---

# 4. 总体执行流程

严格按照以下阶段执行：

```text
阶段0：确认任务范围
阶段1：识别作品、世界线与剧情坐标
阶段2：检索最小必要RAG资料
阶段3：Ruler裁决
阶段4：构建压缩写作上下文
阶段5：Judgment赛前判断
阶段6：生成低修辞骨架稿
阶段7：受控文风渲染
阶段8：Ruler合规审计
阶段9：Judgment执行审计
阶段10：设定、连续性与人物审计
阶段11：文风审计
阶段12：定向修订
阶段13：最终检查与输出
阶段14：生成并更新状态记录
```

任何正文生成都不得跳过阶段3与阶段5。

---

# 5. 阶段0：确认任务范围

识别本次任务：

```yaml
task_scope:
  story_id:
  timeline_id:
  arc:
  volume:
  chapter:
  scene:
  start_point:
  end_point:
  target_length:
  output_mode:
  task_type:
  scene_types:
```

`task_type`可包括：

```text
new_scene
chapter_generation
continuation
multi_chapter
rewrite
style_revision
battle
relationship
horror
daily
high_information
```

如果用户没有提供字数：

- 单场景：写到场景自然结束。
- 单章节：写到本章主要冲突获得阶段性结果。
- 多章节：按照自然章节节点拆分。
- 不得为了覆盖全部大纲而把后半部分压缩成摘要。

---

# 6. 阶段1：识别作品与世界线

至少识别：

```yaml
story_identity:
  story_id:
  work_title:
  timeline_id:
  arc:
  volume:
  current_chapter:
  current_stage:
  character_variants:
```

存在以下情况时必须先消歧：

- 同名角色存在多个版本。
- 主线与IF线同时存在。
- 旧设定与新设定同时存在。
- 同一作品存在重写版。
- 同一人物存在不同年龄、职阶或身份。
- 多部作品共享角色名称。

检索必须优先使用：

```text
story_id
timeline_id
volume
arc
character_variant
```

不得只根据角色名字召回资料。

---

# 7. 阶段2：检索最小必要RAG资料

## 7.1 检索顺序

按照以下顺序检索：

```text
1. registry
2. 当前outline
3. 当前character-state与world-state
4. 邻近history
5. 本次涉及的canon
6. 当前active rules
7. 当前style-audit与专项规则
8. 相关feedback与approved-samples
```

该顺序只表示检索组织顺序，不表示发生冲突时的最终权威顺序。

---

## 7.2 大纲检索

提取：

```yaml
outline_contract:
  opening_state:
  required_events:
  required_order:
  required_dialogue:
  required_images:
  required_reveals:
  forbidden_reveals:
  required_result:
  character_changes:
  ending_state:
  future_hooks:
```

大纲内容分为：

### 硬约束

- 明确指定的事件。
- 明确指定的胜负。
- 明确指定的死亡或生还。
- 明确指定的关系变化。
- 明确指定的情报揭示。
- 明确指定的章节结束状态。
- 用户要求原样或保留核心含义的台词和意象。

### 软约束

- 具体动作过程。
- 对话措辞。
- 环境细节。
- 场景内部节奏。
- 非关键配角反应。
- 不影响后续的微型冲突。

### 可补充空白

- 事件如何自然开始。
- 人物如何抵达指定判断。
- 场景所需的动作和感官细节。
- 不改变结果的战术过程。
- 不改变关系结论的小型互动。

不得利用空白自行增加重大反转、秘密、死亡、新能力或关系变化。

---

## 7.3 状态检索

优先检索：

- 当前时间。
- 当前地点。
- 人物位置。
- 身体伤势。
- 精神状态。
- 已知与未知信息。
- 错误认知。
- 当前目标。
- 携带道具。
- 能力消耗。
- 当前关系。
- 未回收伏笔。
- 未解决冲突。

状态记录与最终正文冲突时，回查最终正文。

---

## 7.4 邻近前文检索

必须优先获取：

1. 当前断点之前的正文。
2. 上一个场景。
3. 上一章结尾。
4. 当前主要人物最近一次互动。
5. 大纲中涉及的直接前置事件。
6. 当前伏笔最近一次出现的位置。

只在本次剧情需要时检索更早历史。

禁止无差别召回整部作品。

---

## 7.5 设定检索

对本次涉及的关键实体分别检索：

- 人物。
- 能力。
- 道具。
- 地点。
- 阵营。
- 历史事件。
- 世界规则。
- 特殊术语。
- 感情关系。
- 战斗机制。

整理为：

```yaml
canon_constraints:
  characters:
  abilities:
  locations:
  factions:
  relationships:
  world_rules:
  prohibited_outcomes:
```

只保留与本次正文直接有关的设定。

---

## 7.6 Rule检索

基础Rule检索组合：

```text
global active rules
+ 当前作品规则
+ 当前世界线规则
+ 当前task_type规则
+ 当前scene_type规则
+ 相关exceptions
```

优先召回：

- `status: active`
- `enforcement: mandatory`
- 高优先级Rule
- 与当前任务类型匹配的Rule

默认排除：

```text
deprecated
archived
draft
其他story_id
其他timeline_id
```

不要一次召回整个Rule库。

---

## 7.7 文风资料检索

优先级：

1. 用户本次明确指定的风格要求。
2. 当前active总文风审计。
3. 当前场景类型专项审计。
4. 用户确认满意的局部样例。
5. 已解决并晋升为Rule的反馈。
6. 尚未晋升但与本次问题直接相关的反馈。

文风样例只用于提取表现特征，不得直接拼接或机械仿写。

---

# 8. 阶段3：Ruler裁决

Ruler必须在正文生成前运行。

## 8.1 Ruler输入

```yaml
ruler_input:
  user_request:
  task_scope:
  story_identity:
  outline_contract:
  current_state:
  relevant_history:
  canon_constraints:
  retrieved_rules:
  style_requirements:
  relevant_feedback:
```

---

## 8.2 Ruler职责

Ruler依次完成：

1. 确认资料是否属于当前作品与世界线。
2. 排除旧版、草案、废弃和其他世界线资料。
3. 判断当前用户是否明确覆盖旧规则或旧设定。
4. 区分事实规则、生成规则和文风规则。
5. 解决冲突。
6. 建立本次任务的硬约束与软约束。
7. 标记允许保守补充的空白。
8. 标记无法擅自推断的关键未知项。
9. 输出唯一有效的 `execution_contract`。

---

## 8.3 冲突裁决顺序

### 内容事实与剧情方向

```text
1. 用户当前明确指令
2. 当前大纲中明确声明的设定修改或剧情结果
3. 当前active Canon
4. 已正式采用的History事实
5. 当前State
6. 旧版设定与旧状态
7. Agent推断
```

补充规则：

- 大纲只有在明确修改旧设定时，才能覆盖Canon。
- 大纲中的未来事件不能倒推为当前已经发生的事实。
- State与正式History冲突时，以正式History为准，并标记State待修正。
- 角色台词、传闻、误判和象征描述不自动等于客观事实。
- 平行世界资料不得进入当前世界线。

### 生成规则

```text
1. 用户当前明确要求
2. 当前任务专项mandatory Rule
3. 当前场景专项mandatory Rule
4. 当前世界线Rule
5. 当前作品Rule
6. 全局Rule
7. preferred与advisory规则
```

### 文风规则

文风必须服从：

```text
剧情事实
> 人物准确
> 信息清晰
> 情绪有效
> 节奏合理
> 语言美感
```

Style Audit不得修改剧情结果、人物认知和世界规则。

---

## 8.4 Ruler输出

```yaml
execution_contract:
  identity:
    story_id:
    timeline_id:
    volume:
    chapter:
    scene:

  task:
    start_point:
    end_point:
    target_length:
    output_mode:

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

`execution_contract`是本次生成的最高内部执行合同。

后续模块不得重新解释原始RAG资料来绕过该合同。

如果Ruler发现不同选择会导致作品核心结果完全不同，且现有资料无法裁决，可以标记为 `blocking_unknowns`。若不影响核心方向，则采用最保守补充，不中断生成。

---

# 9. 阶段4：构建压缩写作上下文

完成Ruler裁决后，将资料压缩为当前任务需要的上下文。

禁止把全部召回块原样交给Generator。

```yaml
writing_context:
  identity:
  task:
  immediate_previous_scene:
  current_location:
  current_time:
  pov:
  participants:

  character_states:
  relevant_relationships:
  active_conflicts:
  unresolved_foreshadowing:

  required_outline:
  relevant_canon:
  recurring_details:
  dialogue_patterns:
  style_parameters:
```

写作上下文中的每一项都必须回答至少一个问题：

- 它是否影响角色怎么行动？
- 它是否影响当前事件能否成立？
- 它是否影响信息释放？
- 它是否影响连续性？
- 它是否影响正文表现？

若全部为否，不进入写作上下文。

召回资料并不意味着正文必须使用该资料。

---

# 10. 阶段5：Judgment赛前判断

Judgment必须在Generator之前运行。

## 10.1 Judgment输入

```yaml
judgment_input:
  execution_contract:
  writing_context:
  outline_contract:
  target_length:
  scene_types:
```

---

## 10.2 判断章节中心

先确定：

```yaml
chapter_core:
  chapter_goal:
  dramatic_question:
  emotional_center:
  information_center:
  primary_character_change:
  required_end_state:
```

节点重要性必须相对于 `chapter_core` 判断。

不得根据事件表面规模判断重要性。

宇宙级爆炸可能只是背景；一句克制的拒绝也可能是本章核心转折。

---

## 10.3 节点功能判断

每个节点必须标记主要功能：

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

一个节点可以有一个主要功能和少量次要功能。

若节点没有有效功能，应判断为C级或与相邻节点合并。

---

## 10.4 S/A/B/C分级

### S级：章节核心

满足至少一项：

- 改变章节核心结果。
- 产生不可逆关系变化。
- 角色作出关键选择。
- 揭露核心真相。
- 完成主要战斗胜负。
- 核心认知发生变化。
- 承担本章最终情绪落点。

### A级：必要推进

满足至少一项：

- 直接支撑S级节点成立。
- 改变角色当前行动方向。
- 提供关键因果。
- 显著改变危险程度。
- 形成新的目标、怀疑或判断。
- 承担必要的蓄力或后果。

### B级：连接内容

主要用于：

- 转场。
- 进出场。
- 普通动作连接。
- 必要但低价值的信息转交。
- 空间与时间连续。
- 核心场景前后的短暂缓冲。

B级通常在一至三句内完成。

### C级：可删除内容

删除后不影响：

- 因果理解。
- 人物判断。
- 情绪积累。
- 人物关系。
- 场景结果。
- 后续剧情。

C级原则上删除。

禁止因为某个节点被列入大纲，就自动判定为S级或A级。

---

## 10.5 节点合并

Judgment必须主动检测可合并节点。

可合并条件：

- 同一地点和连续时间。
- 同一行动链。
- 同一人物触发。
- 功能相同或相邻。
- 合并后不削弱关键转折。
- 合并后仍然清楚。

例如：

```text
进入房间
→ 看见角色
→ 注意到伤口
→ 停下脚步
```

可以由一个连续动作段完成。

禁止为了“完整兑现大纲”给每个动作建立独立段落和独立镜头。

---

## 10.6 描写与篇幅预算

Judgment必须为每个节点分配处理方式。

```yaml
node_budget:
  importance:
  treatment:
  relative_weight:
  max_sentences:
  max_paragraphs:
  pacing:
  dialogue_weight:
  action_detail:
  inner_monologue:
  sensory_channels:
  environment_detail:
  metaphor_permission:
  symbolic_image:
  information_release:
```

处理原则：

- S级：允许放慢时间、强化动作、情绪、感官与后果。
- A级：完整表现因果，但不得抢夺S级中心。
- B级：最低必要篇幅，优先合并。
- C级：删除。

高密度感官、连续动作分解、象征意象、内心深描和句式强化，只能用于Judgment明确授权的节点。

Generator不得自行给B级转场升级描写权限。

---

## 10.7 情绪曲线

Judgment建立：

```yaml
emotional_curve:
  opening_level:
  buildup_nodes:
  pressure_increase:
  false_release:
  peak_node:
  immediate_aftershock:
  ending_level:
```

必须检查：

- 是否存在蓄力。
- 是否存在强度变化。
- 是否连续多个节点都处于最高强度。
- 高潮后是否有直接后果。
- 收束是否仍然保留情绪余波。

若连续多个节点被判为高强度，应重新评估是否平均用力。

---

## 10.8 Judgment输出

```yaml
generation_plan:
  chapter_core:
  scene_order:
    -

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

正文生成器无权跳过或擅自重做 `generation_plan`。

---

# 11. 阶段6：生成低修辞骨架稿

第一遍只生成骨架。

目标：

- 动作因果清楚。
- 对话功能清楚。
- 场景目标清楚。
- 人物判断与反应清楚。
- 每个节点产生实际后果。
- 大纲硬事件完整落实。
- 转场已经被压缩。
- C级内容没有重新混入。

骨架稿优先使用：

```text
行动
→ 反馈
→ 判断
→ 新行动
```

骨架阶段不追求：

- 全篇华丽措辞。
- 大量意象。
- 多通道感官堆叠。
- 每个动作都具有镜头感。
- 所有段落都保持高张力。

Generator不得为了“让初稿像小说”提前对全篇平均渲染。

---

# 12. 阶段7：受控文风渲染

第二遍依据：

```text
generation_plan中的style_permissions
+ execution_contract中的active_style_rules
```

进行渲染。

只强化：

- S级节点。
- Judgment授权的A级节点。
- 需要建立场景基准的重要开场。
- 高潮前必要的静止。
- 关键结果的即时后果。

原则上不强化：

- 普通移动。
- 单纯进门、落座、转身。
- 无变化的观察。
- 普通寒暄。
- 已经完成信息功能的B级过渡。

渲染时遵守：

- 文风不能覆盖因果清晰。
- 意象不能制造新设定。
- 环境不能抢夺人物行动中心。
- 同一情绪不得由动作、心理、环境、比喻重复表达。
- 链接词、声音、感官和句式变化应服务于场景，而不是逐句配给。

---

# 13. 通用生成规则

## 13.1 从具体事件开始

优先从以下内容切入：

- 正在发生的动作。
- 角色立即感受到的异常。
- 一句带有冲突的对话。
- 一个有方向性的环境变化。
- 上一场景尚未解决的后果。

避免大段世界观介绍、人物履历和抽象议论开场。

---

## 13.2 对话必须有功能

每段对话至少承担一种功能：

- 试探。
- 隐瞒。
- 说服。
- 拒绝。
- 转移话题。
- 交换信息。
- 表明关系。
- 暴露认知差。
- 推动行动。
- 制造压力。

不同人物必须具有不同的：

- 句子长度。
- 用词。
- 礼貌程度。
- 回避方式。
- 攻击方式。
- 沉默方式。
- 称呼习惯。

避免人物轮流说明双方都知道的设定。

---

## 13.3 情绪必须落地

优先通过：

- 动作偏差。
- 反应延迟。
- 说话节奏。
- 视线停留。
- 呼吸变化。
- 对物品的处理。
- 对环境细节的异常关注。
- 与平时行为模式的差异。
- 没有完成的动作。

避免只写：

- 他很愤怒。
- 她非常悲伤。
- 他感到恐惧。
- 气氛十分压抑。

情绪描写必须符合人物性格。

---

## 13.4 设定通过事件生效

优先表现：

- 能力如何改变战场。
- 规则如何限制角色。
- 制度如何影响选择。
- 地点如何阻碍行动。
- 能力代价如何积累。
- 不同角色如何理解同一现象。

避免百科式说明。

---

## 13.5 信息释放

根据信息级别选择：

- 直接揭示。
- 局部揭示。
- 通过异常暗示。
- 让角色误判。
- 只给结果，不解释原因。
- 通过重复意象建立联系。

伏笔必须可感知，但不能直接等同于答案。

---

# 14. 战斗场景专项执行

战斗场景必须跟踪：

- 双方目标。
- 空间位置。
- 攻击距离。
- 已使用能力。
- 能力消耗。
- 身体损伤。
- 情报差。
- 心理状态。
- 环境变化。
- 胜负条件。

基本循环：

```text
判断
→ 行动
→ 对方反应
→ 结果
→ 新判断
```

避免：

- 轮流释放技能。
- 命中后没有实际后果。
- 伤势下一段自动消失。
- 角色忘记已有能力。
- 只靠数值形容强大。
- 为反转临时增加新规则。
- 胜者没有获得优势的过程。

战斗中的大场面也必须服从Judgment。

不是所有光炮、爆炸、登场和招式都自动获得S级篇幅。

---

# 15. 感情与关系场景专项执行

人物关系必须通过连续互动形成。

重点表现：

- 双方如何注意彼此。
- 对同一行为的不同理解。
- 关系中的权力差。
- 习惯性动作。
- 未说出口的期待。
- 边界试探与退让。
- 是否准确理解对方。
- 是否故意维持错误理解。

不得：

- 用旁白直接宣布关系完成。
- 因单次事件彻底治愈长期问题。
- 自动美化共依、监护、敌对亲密或非对称关系。
- 在用户未要求时完成长期人物弧线。

关系场景的S级节点通常是“关系状态发生变化”，不必然是拥抱、亲吻或告白本身。

---

# 16. 阶段8：Ruler合规审计

生成渲染稿后，先检查是否违反 `execution_contract`。

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
  authority_conflicts:
```

重点检查：

- 是否遗漏大纲硬事件。
- 是否改变指定胜负与结果。
- 是否提前泄露后续情报。
- 是否增加未经授权的秘密、能力、死亡或关系变化。
- 是否混入其他世界线。
- 是否把未来大纲当成当前事实。
- 是否使用已经废弃的资料。

发现问题后，优先修复事实和结构，不进行语言润色。

---

# 17. 阶段9：Judgment执行审计

将正文与 `generation_plan` 对比。

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

必须检查：

- 核心节点是否获得最高篇幅与表现权重。
- B级节点是否超过预算。
- C级节点是否重新出现。
- 已合并节点是否被重新拆成多个镜头。
- 是否出现普通过渡比核心转折更长。
- 是否对全篇进行了平均润色。
- 是否连续多个自然段保持相同高密度。
- 是否出现未经Judgment授权的意象、心理或环境扩写。
- 高潮是否存在蓄力与后果。
- 情绪是否被重复表达。

如果Judgment审计失败，优先压缩、合并和删除，而不是把所有段落改得更华丽。

---

# 18. 阶段10：设定、连续性与人物审计

## 18.1 设定审计

检查：

- 人物能力与限制。
- 能力代价。
- 世界规则。
- 阵营关系。
- 人物身份。
- 专有名词。
- 地点规则。
- 是否自行添加重大背景。

---

## 18.2 连续性审计

检查：

- 时间。
- 地点。
- 人物位置。
- 伤势。
- 道具。
- 能力消耗。
- 已知与未知信息。
- 关系状态。
- 上一场景未完成动作。
- 已发生事件是否被再次写成首次发生。

---

## 18.3 人物审计

人物行动必须符合：

```text
性格核心
+ 当前状态
+ 已知信息
+ 当前目标
+ 与他人的关系
+ 当前压力
+ 实际能力
```

检查：

- 是否突然降智。
- 是否知道不该知道的信息。
- 是否忘记已知信息。
- 是否突然改变核心性格。
- 是否直接说出本应隐藏的内心。
- 是否沦为纯粹的设定说明工具。
- 情绪与关系变化是否有过程。

---

# 19. 阶段11：文风审计

使用当前生效的Style Audit检查：

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
- AI式总结。
- 空泛情绪。
- 重复表达。
- 人物语气同质化。
- 过度解释。
- 比喻堆积。
- 句式节奏单一。
- 转场机械。
- 对话只承担说明功能。
- 否定前置滥用。
- 连续使用相同动作。
- “仿佛”“似乎”“某种”“一种”等空泛缓冲词过多。
- 声音词、连接词和感官词机械配给。
- 用华丽语言掩盖事件不足。

文风审计不得要求改变大纲、设定或Judgment确定的叙事主次。

---

# 20. 阶段12：定向修订

修订顺序：

```text
1. Ruler合规错误
2. 大纲与设定错误
3. 连续性错误
4. 人物错误
5. Judgment执行错误
6. 场景结构与节奏问题
7. 文风问题
8. 句词层面问题
```

不得先润色一个事实错误或结构错误的段落。

默认最多三轮：

### 第一轮：事实与结构

- 大纲。
- 设定。
- 连续性。
- 人物。
- 节点遗漏。
- 节点顺序。

### 第二轮：判断执行

- 主次。
- 篇幅。
- 节点合并。
- 过渡压缩。
- 情绪曲线。
- 信息释放。

### 第三轮：表达

- 文风。
- 句式。
- 声音。
- 连接。
- 重复。
- 词语。
- 段落衔接。

局部问题优先局部重写。

只有出现以下情况才重新运行Judgment：

- 核心场景划分错误。
- 章节中心判断错误。
- 多个节点权重普遍失真。
- 大纲结构在修订中发生变化。
- Ruler裁决结果发生变化。

不要因为个别句子问题重新规划整章。

---

# 21. 阶段13：最终检查与输出

## 21.1 完成标准

必须同时满足：

- 大纲硬事件完整落实。
- 核心结果未改变。
- 人物行为符合设定与前文。
- 世界规则未违反。
- 时间、地点、伤势、道具与情报连续。
- 核心节点获得足够篇幅。
- 低价值过渡没有堆料。
- 情绪曲线存在起伏。
- 正文不是大纲摘要。
- 文风通过审计。
- 章节结尾符合指定状态。

---

## 21.2 输出规则

默认只输出最终小说正文。

不输出：

- 检索过程。
- Ruler裁决表。
- execution_contract。
- Judgment判断表。
- generation_plan。
- 骨架稿。
- 审计报告。
- 修订记录。
- 状态摘要。
- RAG引用列表。

除非用户明确要求查看。

如果是完整章节，可以输出：

```text
章节标题

正文
```

从断点继续时，不自动添加标题。

篇幅过长时：

- 按自然场景节点分段。
- 不在动作或对话中间截断。
- 不压缩后半部分来强行覆盖全部大纲。

---

# 22. 阶段14：状态记录与RAG回写

状态记录必须基于最终正文生成，不得依据大纲、Judgment 计划或初稿生成。

运行时可以保留一个短期摘要来传递本次已完成事件、世界变化、冲突和伏笔；该摘要
只服务当前任务，不能作为持久化 schema，也不能替代角色状态文档。持久化角色变化
时，必须读取 `novel-rag/shared/templates/character-current.yaml`，为每个角色填充
其 `metadata.character_id` 与 `metadata.variant_id`，并只使用模板定义的
`character_state.current_position`、`physical`、`mental`、`knowledge`、`goals`、
`relationships`、`abilities`、`inventory`、`narrative` 字段及其现有类型。用
`load_document` 与 `validate_document` 校验后，才可更新
`character-state/current`、snapshots 或 change-logs。世界变化同样只能按
`novel-rag/shared/templates/world-current.yaml` 写回。

如果系统允许回写：

```text
最终正文
→ history

角色变化
→ character-state/change-logs
→ character-state/snapshots
→ character-state/current

世界变化
→ world-state/change-logs
→ world-state/current

用户确认的新长期规则
→ rules草案
→ 用户确认后active

用户对正文的评价
→ feedback

用户确认满意的代表片段
→ approved-samples
```

禁止：

- 根据大纲提前更新状态。
- 根据初稿更新状态。
- 把Judgment临时判断写入正式Rule。
- 把Agent推断写入Canon。
- 未经用户确认自动晋升重大新规则。

---

# 23. 检索失败处理

未检索到资料时：

1. 使用角色全名查询。
2. 使用别名或称号查询。
3. 加入作品与世界线标识。
4. 加入卷、章与剧情阶段。
5. 查询角色最近出场。
6. 查询事件首次和最近出现。
7. 查询状态记录。
8. 查询版本映射。
9. 必要时查询旧版资料，仅用于确认是否发生迁移。

仍未找到：

- 不影响核心剧情的内容可以保守补充。
- 影响身份、胜负、关系、能力和世界规则的内容不得自行断言。
- 不得声称知识库存在未实际召回的资料。
- 不得以检索失败为理由改变大纲。

---

# 24. 硬性禁止事项

1. 禁止跳过Ruler直接生成。
2. 禁止跳过Judgment直接逐条扩写大纲。
3. 禁止把全部RAG召回内容塞入正文。
4. 禁止按大纲条目平均分配篇幅。
5. 禁止让所有段落使用相同描写密度。
6. 禁止给普通转场自动调用高密度感官、心理和意象描写。
7. 禁止擅自改变大纲核心结果。
8. 禁止混入其他世界线资料。
9. 禁止使用废弃设定。
10. 禁止让角色知道尚未获得的信息。
11. 禁止遗忘伤势、道具、能力消耗和关系状态。
12. 禁止为了制造冲突让人物降智。
13. 禁止用摘要代替核心场景。
14. 禁止用文风覆盖剧情清晰度。
15. 禁止把人物卡改写为正文介绍。
16. 禁止把RAG片段直接拼接为正文。
17. 禁止提前回收伏笔。
18. 禁止擅自完成长期人物成长。
19. 禁止输出未经审计的初稿。
20. 禁止在正文中暴露工作流。
21. 禁止把Agent推断写成正式事实。
22. 禁止根据临时Judgment结果修改永久Rule。
23. 禁止在用户未确认正文时覆盖current状态。
24. 禁止为了覆盖全部大纲而极度压缩核心场景。

---

# 25. 核心执行原则

始终遵循：

> Ruler先决定本次任务必须服从什么。  
> Judgment再决定本次正文应当如何分配叙事资源。  
> Generator只能按照合同与计划执行。  
> Audit必须同时检查“写对了没有”和“有没有按计划写”。  

最终目标不是生成一段“看起来像小说”的文本。

最终目标是生成：

> 能够无缝接入已有作品、符合当前世界线事实、落实用户大纲、具备明确叙事主次，并经过规则、判断、连续性和文风多层审计的正式小说正文。
