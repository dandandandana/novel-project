from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
RAG = ROOT / "novel-rag"
JUDGMENT_ACTIVE = RAG / "judgment" / "active" / "global"
JUDGMENT_DEPRECATED = RAG / "judgment" / "deprecated"
STYLE_ACTIVE = RAG / "style-audit" / "active"
STYLE_DEPRECATED = RAG / "style-audit" / "deprecated"
MODULE_MAP = RAG / "registry" / "module-map.yaml"
VERSION_MAP = RAG / "registry" / "version-map.yaml"
RETRIEVAL_TESTS = RAG / "retrieval-tests.yaml"

STORY_ID = "overturned-world-fujimaru"
TIMELINE_ID = "main"
TODAY = "2026-07-17"
SOURCE_REF = "user-message:2026-07-17/native-chinese-dialogue-rules"

SOURCE_TEXT = r"""# 中文母语感对白生成与翻译腔修正规则

## 一、核心目标

生成对白时，优先保证角色说出来的话具有自然的中文母语感，而不只是语义正确。

对白必须像具体的人在具体关系、具体情绪和具体场景下说出来的话，而不是：

- 将英文句式逐字翻译成中文；
- 用书面概念代替日常表达；
- 让角色像系统、报告、字幕或说明书一样交换信息；
- 把所有台词写成短促、完整、平直的主谓宾陈述句。

每句对白都应同时包含以下至少两项：

1. 实际信息；
2. 当前情绪；
3. 人物关系；
4. 对上一句话的反应；
5. 未直接说出口的潜台词；
6. 推进、回避、试探、反驳、缓和或拉扯的意图。

对白不是信息清单，而是人物关系正在发生变化的过程。

---

## 二、禁止翻译腔与概念化表达

不得为了“准确”而使用日常人物不会自然说出口的概念化词语。

### 常见翻译腔

- 你是旅行的主要体验者。
- 我是监管人。
- 这是你的个人选择。
- 我对此没有意见。
- 这不是当前讨论的重点。
- 你正在回避我的问题。
- 我能够理解你的感受。
- 你没有必要这样做。
- 我不认为这是一个好主意。

### 优先改写为自然口语

- 真正出去玩的人不是你吗？
- 我那时候不就是负责看着你嘛。
- 反正是你自己选的。
- 我又没说不行。
- 现在说的不是这个吧？
- 你别岔开话题。
- 我知道你难受。
- 你不用非得这样。
- 我看还是算了吧。

不得机械保留原句的抽象名词、身份标签和逻辑结构。

应先理解角色真正想表达什么，再用中文人物自然会采用的说法重新组织。

---

## 三、对白必须具有中文语气

根据人物身份、关系和情绪，自然使用中文语气助词，包括但不限于：

- 了
- 呢
- 啊
- 吧
- 嘛
- 呀
- 呗
- 哦
- 来着
- 似的
- 才怪
- 行不行
- 好不好
- 怎么了
- 干什么
- 算了
- 得了吧

语气助词不能平均分配，也不能为了口语感强行塞进每句话。

它们必须承担实际功能：

- “了”：表示状态变化、确认、催促或不耐烦；
- “呢”：追问、对照、未完意味或轻微施压；
- “啊”：强调、提醒、惊讶、撒娇或解释；
- “吧”：缓和判断、试探、建议或不确定；
- “嘛”：解释理所当然、撒娇、抱怨或拉近距离；
- “呀”：轻快、亲近、惊讶或故意柔化；
- “呗”：无奈、赌气、随口接受或反讽。

### 错误示例

“你不需要担心我。”

### 自然改写

- “你不用这么担心我。”
- “我又不会出什么事。”
- “好了，我知道你担心。”
- “你怎么还在想这个啊？”
- “都已经没事了，不是吗？”

---

## 四、避免所有台词都是完整陈述句

自然对白允许并鼓励：

- 省略；
- 倒装；
- 重复；
- 改口；
- 停顿；
- 半句话；
- 反问；
- 答非所问；
- 抓住对方措辞反击；
- 故意曲解；
- 先否认再承认；
- 说到一半停住；
- 用动作代替后半句。

### 平直写法

“我担心你。”

“你不需要担心。”

“这是我的决定。”

### 自然写法

“我就是有点担心你，不行吗？”

“我又没说不行。”

“那你刚才躲什么？”

“……谁躲了。”

对白应允许“不完整”，但不能让读者看不懂人物真正的情绪和关系变化。

---

## 五、每句台词必须承接上一句

角色不能只围绕同一主题各说各的。

新台词应明确回应上一句话中的至少一个部分：

- 内容；
- 措辞；
- 情绪；
- 回避；
- 暗示；
- 称呼；
- 语气变化。

### 机械对话

“欧洲三个月基本都是我在选。”

“你是旅行的主要体验者。”

“你也在旅行。”

“我是监管人。”

“现在不是。”

### 自然对话

“在欧洲那三个月，不一直都是我挑地方吗？”

“可真正出去玩的人是你啊。”

“说得好像你没跟着一起似的。”

“我那时候主要是负责看着你。”

“那现在呢？”

“……现在不算了。”

后一句应从前一句中“接话”，而不是只提供新的事实。

---

## 六、对白必须体现人物关系

同一句意思，根据关系不同，表达方式必须变化。

### 陌生人

“抱歉，我想确认一下，您刚才的意思是？”

### 熟人

“等等，你刚才什么意思？”

### 恋人

“你这话什么意思啊？”

### 正在吵架的恋人

“你把刚才那句话再说一遍？”

### 上下级

“您的意思是，这件事暂时不需要继续处理？”

### 亲密但嘴硬

“所以呢？你该不会是在担心我吧？”

生成前必须判断：

- 两人熟不熟；
- 谁更强势；
- 谁正在心虚；
- 谁在试探；
- 谁想结束话题；
- 谁想让对方继续问；
- 是否存在暧昧、敌意、愧疚、依赖或戒备。

不能让所有人物共享同一种“标准普通话人格”。

---

## 七、对白要有潜台词

人物不应总是直接说出真实意图。

以下情形优先使用潜台词：

- 害羞；
- 心虚；
- 暧昧；
- 愤怒；
- 愧疚；
- 不想示弱；
- 想被挽留；
- 想让对方主动；
- 已经知道答案，却仍然追问。

### 直接说明

“我希望你陪我。”

### 潜台词表达

- “你今晚还有别的事吗？”
- “反正我一个人也没关系。”
- “你不是说今天有空？”
- “这么晚了，你还要走啊？”
- “……再坐一会儿吧。”

不要把人物心理报告直接写成台词。

---

## 八、对白节奏不能过度整齐

禁止连续多句都采用同样长度、同样结构和同样语调。

尤其避免：

- 每句都在十个字以内；
- 每句都是“主语＋判断”；
- 每句都以句号结束；
- 一问一答过于完整；
- 情绪越强，句子反而越工整；
- 所有人都像冷静地等待对方说完。

应混合使用：

- 短句；
- 长句；
- 停顿；
- 打断；
- 追问；
- 重复；
- 自我修正；
- 动作插入；
- 沉默；
- 未说完的话。

### 示例

“我没生气。”

“你每次这么说的时候都在生气。”

“我说了没有。”

“行。没有。”

“……你那是什么语气？”

---

## 九、叙述动作要辅助语气

当一句话仅靠文字无法准确传达态度时，使用简短动作、神态或停顿提供语境。

### 平淡写法

“现在不是。”

### 改写

他停了一下，视线从她脸上移开。

“……现在不算了。”

动作不能替代对白，也不能每句话都追加表情说明。

只在以下情况使用动作：

- 语气存在歧义；
- 人物口是心非；
- 关系发生变化；
- 情绪突然停顿；
- 台词本身很轻，但含义很重。

---

## 十、避免过度书面化

对白中谨慎使用以下结构：

- 对此；
- 关于这一点；
- 从某种意义上来说；
- 我认为；
- 你应该意识到；
- 这意味着；
- 这并不代表；
- 你所做的行为；
- 当前阶段；
- 主要体验者；
- 监管人；
- 行动主体；
- 情绪状态；
- 个人选择；
- 必要性；
- 合理性。

除非角色本身就是刻意使用官腔、学术腔、机械腔或外交辞令，否则应改为普通人物会说的话。

### 书面表达

“这并不意味着我认可你的行为。”

### 口语表达

- “我可没说你做得对。”
- “理解归理解，我还是不赞成。”
- “别误会，我没打算夸你。”
- “你少拿这个当我同意了。”

---

## 十一、保留角色的个体语言习惯

不同角色应拥有稳定且可辨认的表达习惯。

可从以下维度区分：

- 句子长短；
- 是否爱反问；
- 是否习惯解释；
- 是否嘴硬；
- 是否常省略主语；
- 是否使用敬语；
- 是否爱叫对方名字；
- 是否会说脏话；
- 是否会改口；
- 是否直白；
- 是否喜欢用比喻；
- 是否擅长绕开问题；
- 情绪激动时变得更沉默还是更啰嗦。

不得只通过口癖区分人物。

真正的人物语言差异，应体现在他们如何理解问题、如何回应对方、如何隐藏自身需求。

---

## 十二、避免“过度精炼导致失去人味”

不要为了让对白显得利落，就删掉所有中文口语中的缓冲成分。

以下词语在合适位置可以保留：

- 就是；
- 其实；
- 反正；
- 本来；
- 好歹；
- 再说；
- 不是；
- 等等；
- 怎么说呢；
- 我是说；
- 算了；
- 行了；
- 得了；
- 你看；
- 我知道；
- 所以呢；
- 那又怎么了；
- 话是这么说。

这些词不一定提供新信息，但会提供人物思考、犹豫、态度和关系感。

不得将所有“非信息性成分”都视为冗余。

---

## 十三、生成步骤

生成对白前，在内部依次判断：

1. 这句话是谁说的？
2. 他和听者是什么关系？
3. 他现在真正想达到什么目的？
4. 他愿不愿意直接说出真实想法？
5. 上一句话中，哪个词或态度刺激了他？
6. 他的情绪会让句子变长、变短，还是说到一半停住？
7. 是否需要语气助词、反问、改口或停顿？
8. 这句话是否像翻译字幕、系统提示或书面报告？
9. 换成现实中的中国人，会不会这样开口？
10. 删除人物名字后，这句话是否仍然具有角色辨识度？

完成判断后再生成台词。

---

## 十四、输出后的自检

生成完成后，逐句检查：

- 是否出现生硬的抽象概念？
- 是否可以换成更日常的动词？
- 是否连续三句以上都是短促陈述句？
- 是否缺少“了、呢、啊、吧、嘛”等必要语气？
- 是否为了添加语气助词而显得做作？
- 后一句是否真正承接前一句？
- 人物是否在直接朗读自己的心理活动？
- 对话是否只有信息，没有情绪和关系？
- 不同角色说话是否过于相似？
- 是否像中文母语者会自然说出口的话？

若存在以上问题，必须重写，而不是仅在句末机械添加语气词。

---

## 十五、最终原则

语义正确只是最低标准。

对白的最终标准是：

- 人物说得出口；
- 中国读者听得顺；
- 语气与关系吻合；
- 每一句都在回应对方；
- 信息、情绪与潜台词同时存在；
- 不像翻译文本；
- 不像系统提示；
- 不像人物轮流朗读剧情摘要。

宁可让台词略带重复、停顿和含混，也不要为了简洁而牺牲中文口语中的气口、人味和关系感。""".strip()


def load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def write_yaml(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=120),
        encoding="utf-8",
        newline="\n",
    )


def add_unique(values: list, value) -> None:
    if value not in values:
        values.append(value)


def upsert_by_key(values: list[dict], key: str, item: dict) -> None:
    target = item[key]
    values[:] = [value for value in values if value.get(key) != target]
    values.append(item)


def dialogue_planning_policy() -> dict:
    return {
        "retrieval_key": "native_chinese_dialogue_judgment",
        "source_rules": SOURCE_TEXT,
        "applies_when": [
            "节点包含两人或多人对白",
            "任务要求改写生硬对白或修正翻译腔",
            "对白承担关系变化、试探、回避、冲突、缓和或信息交换功能",
        ],
        "planning_goal": "在生成前明确每轮对白的关系位置、真实意图、接话触发点、潜台词和中文口语节奏权限。",
        "line_function_minimum": 2,
        "line_function_options": [
            "actual_information",
            "current_emotion",
            "relationship_signal",
            "response_to_previous_line",
            "subtext",
            "advance_avoid_probe_refute_soften_or_pull",
        ],
        "pre_generation_checks": [
            "说话人和听者是谁",
            "双方熟悉程度与当前关系",
            "谁更强势、谁心虚、谁试探、谁想结束或延续话题",
            "说话人真正想达到什么目的",
            "说话人是否愿意直接说出真实意图",
            "上一句话中哪个内容、措辞、情绪、回避、暗示、称呼或语气刺激了回应",
            "当前情绪会让句子变长、变短、改口、停顿还是说到一半停住",
            "角色稳定语言习惯及其在当前压力下的变化",
        ],
        "exchange_continuity": {
            "required": "后一句必须承接前一句的至少一个具体部分，而不是只围绕同一主题提供新事实。",
            "response_targets": ["内容", "措辞", "情绪", "回避", "暗示", "称呼", "语气变化"],
        },
        "relationship_dimensions": [
            "familiarity",
            "power_balance",
            "guilt_or_defensiveness",
            "probing_or_avoidance",
            "desire_to_end_or_continue",
            "ambiguity_hostility_dependence_or_guardedness",
        ],
        "subtext_priority_when": [
            "害羞",
            "心虚",
            "暧昧",
            "愤怒",
            "愧疚",
            "不想示弱",
            "想被挽留",
            "想让对方主动",
            "已经知道答案却仍然追问",
        ],
        "rhythm_permissions": [
            "省略",
            "倒装",
            "重复",
            "改口",
            "停顿",
            "半句话",
            "反问",
            "答非所问",
            "抓住措辞反击",
            "故意曲解",
            "先否认再承认",
            "动作代替后半句",
            "长短句混合",
            "打断与沉默",
        ],
        "particle_policy": "可按身份、关系和情绪授权语气助词，但不能平均分配或为口语感机械添加。",
        "action_support_only_when": [
            "语气存在歧义",
            "人物口是心非",
            "关系发生变化",
            "情绪突然停顿",
            "台词很轻但含义很重",
        ],
        "forbidden_treatments": [
            "逐字保留英文式逻辑结构",
            "用抽象名词和身份标签代替日常表达",
            "让所有人物共享标准普通话人格",
            "连续多句使用同长度、同结构、同语调的完整陈述句",
            "把人物心理报告直接写成台词",
            "为了利落删除全部口语缓冲成分",
            "每句台词都追加动作、神态或语气说明",
            "只在句末机械添加语气词来修复翻译腔",
        ],
        "generation_plan_requirements": [
            "含对白的节点必须填写 dialogue_plan",
            "dialogue_plan 必须记录关系状态、力量位置、说话意图、直接程度和上一句触发点",
            "dialogue_plan 必须明确至少两种台词功能、潜台词、节奏权限与禁用处理",
            "Judgment 只规划功能和权限，不编写完整台词",
        ],
    }


def upgrade_judgment() -> None:
    v10 = JUDGMENT_ACTIVE / "judgment-global-v1.0.yaml"
    v11 = JUDGMENT_ACTIVE / "judgment-global-v1.1.yaml"
    current_path = v11 if v11.exists() else v10
    current = load_yaml(current_path)
    document_id = current["metadata"]["document_id"]
    if document_id not in {"judgment-global-v1.0", "judgment-global-v1.1"}:
        raise ValueError(f"unexpected Judgment version: {document_id}")

    if document_id == "judgment-global-v1.0":
        archived = deepcopy(current)
        archived["metadata"]["status"] = "deprecated"
        archived["metadata"]["updated_at"] = TODAY
        write_yaml(JUDGMENT_DEPRECATED / "judgment-global-v1.0.yaml", archived)

    upgraded = deepcopy(current)
    upgraded["metadata"].update(
        {
            "document_id": "judgment-global-v1.1",
            "version": "1.1",
            "status": "active",
            "updated_at": TODAY,
            "supersedes": "judgment-global-v1.0",
            "source_file": (
                "C:/Users/dandandandana/.codex/attachments/"
                "960de0fb-a5e4-4f21-bc81-98ff04d2e6a0/pasted-text-1.txt"
                f" + {SOURCE_REF}"
            ),
        }
    )
    judgment = upgraded["judgment"]
    reordered: dict = {}
    for key, value in judgment.items():
        if key == "generator_directives":
            reordered["dialogue_planning_policy"] = dialogue_planning_policy()
        if key != "dialogue_planning_policy":
            reordered[key] = value
    if "dialogue_planning_policy" not in reordered:
        reordered["dialogue_planning_policy"] = dialogue_planning_policy()
    upgraded["judgment"] = reordered
    judgment = upgraded["judgment"]

    skeleton_directives = judgment["generator_directives"]["skeleton_stage"]
    rendering_directives = judgment["generator_directives"]["rendering_stage"]
    add_unique(skeleton_directives, "对白骨架先落实接话关系、真实意图、潜台词和关系变化，不写成轮流播报信息")
    add_unique(rendering_directives, "对白渲染必须服从 dialogue_plan，并执行中文母语感与翻译腔修正规则")
    add_unique(rendering_directives, "不得用机械语气词、统一口癖或逐句动作说明伪造口语感")

    template = judgment["output_contract"]["yaml_template"]
    marker_line = next(
        (line for line in template.splitlines(keepends=True) if line.strip() == "forbidden_treatment: []"),
        None,
    )
    if marker_line is None:
        raise ValueError("generation_plan node template marker missing")
    indent = marker_line[: len(marker_line) - len(marker_line.lstrip())]
    child_indent = indent + "  "
    dialogue_block = "".join(
        [
            f"{indent}dialogue_plan:\n",
            f"{child_indent}enabled:\n",
            f"{child_indent}speaker:\n",
            f"{child_indent}listener:\n",
            f"{child_indent}relationship_state:\n",
            f"{child_indent}power_balance:\n",
            f"{child_indent}speaker_intent:\n",
            f"{child_indent}directness:\n",
            f"{child_indent}trigger_from_previous_line:\n",
            f"{child_indent}required_functions: []\n",
            f"{child_indent}subtext:\n",
            f"{child_indent}rhythm_permissions: []\n",
            f"{child_indent}particle_permissions: []\n",
            f"{child_indent}action_support:\n",
            f"{child_indent}forbidden_treatments: []\n",
        ]
    )
    if f"{indent}dialogue_plan:\n" not in template:
        template = template.replace(marker_line, marker_line + dialogue_block, 1)
        judgment["output_contract"]["yaml_template"] = template

    for check in [
        "含对白的节点已经填写 dialogue_plan",
        "对白计划已明确关系、意图、接话触发点、潜台词和至少两种台词功能",
        "对白计划允许符合角色的省略、改口、停顿和长短句变化",
        "对白计划禁止翻译腔、概念化表达、标准普通话人格和机械语气词修补",
    ]:
        add_unique(judgment["validation"], check)

    write_yaml(v11, upgraded)
    if v10.exists():
        v10.unlink()


def create_style_module() -> None:
    data = {
        "metadata": {
            "document_id": "style-native-chinese-dialogue-v1.0",
            "story_id": STORY_ID,
            "timeline_id": TIMELINE_ID,
            "document_type": "style_audit",
            "module_type": "style",
            "title": "中文母语感对白生成与翻译腔修正规则",
            "audit_scope": "global_module",
            "scene_type": "dialogue",
            "module_id": "native-chinese-dialogue",
            "priority": "high",
            "enforcement": "mandatory",
            "version": "1.0",
            "status": "active",
            "created_at": TODAY,
            "updated_at": TODAY,
            "supersedes": None,
            "source_file": SOURCE_REF,
        },
        "style_rules": {
            "activation": "active",
            "retrieval_key": "native_chinese_dialogue_style",
            "priority": "high",
            "enforcement": "mandatory",
            "scope": "global_dialogue",
            "content": SOURCE_TEXT,
        },
        "audit_checks": {
            "line_function_minimum": 2,
            "line_functions": [
                "实际信息",
                "当前情绪",
                "人物关系",
                "对上一句话的反应",
                "潜台词",
                "推进、回避、试探、反驳、缓和或拉扯的意图",
            ],
            "must_verify": [
                "台词像具体角色在当前关系和情绪下说出口的话",
                "后一句承接前一句的内容、措辞、情绪、回避、暗示、称呼或语气变化",
                "语气助词承担实际功能且未被平均分配",
                "省略、倒装、重复、改口、停顿、反问、打断和沉默符合人物状态",
                "对白体现熟悉程度、强弱位置、试探、心虚、依赖、敌意或戒备",
                "需要隐藏真实意图时使用潜台词而非心理报告",
                "台词长短、结构和标点节奏不过度整齐",
                "动作只在语气歧义、口是心非、关系变化或重含义轻台词时辅助",
                "不同角色具有稳定且可辨认的语言习惯",
                "适当保留口语缓冲成分，不因过度精炼失去人味",
            ],
            "rewrite_required_when": [
                "出现生硬抽象概念或英文式逻辑结构",
                "连续三句以上都是短促完整陈述句",
                "对白只有信息而没有情绪、关系或潜台词",
                "不同角色声音过度相似",
                "人物直接朗读心理活动",
                "后一句没有真正承接前一句",
                "台词像翻译字幕、系统提示、书面报告或剧情摘要",
            ],
            "prohibited_fix": "不得仅在句末机械添加语气词；必须从真实意图、关系、接话点和中文口语结构重写。",
        },
    }
    write_yaml(STYLE_ACTIVE / "native-chinese-dialogue.yaml", data)


def upgrade_style_manifest() -> None:
    manifest_path = STYLE_ACTIVE / "manifest.yaml"
    manifest = load_yaml(manifest_path)
    document_id = manifest["metadata"]["document_id"]
    if document_id not in {"style-global-manifest-v1.2", "style-global-manifest-v1.3"}:
        raise ValueError(f"unexpected style manifest version: {document_id}")
    if document_id == "style-global-manifest-v1.2":
        archived = deepcopy(manifest)
        archived["metadata"]["status"] = "deprecated"
        archived["metadata"]["updated_at"] = TODAY
        write_yaml(STYLE_DEPRECATED / "manifest-v1.2.yaml", archived)

    manifest["metadata"].update(
        {
            "document_id": "style-global-manifest-v1.3",
            "module_type": "style",
            "priority": "highest",
            "enforcement": "mandatory",
            "version": "1.3",
            "status": "active",
            "updated_at": TODAY,
            "supersedes": "style-global-manifest-v1.2",
            "source_file": SOURCE_REF,
        }
    )
    modules = manifest["audit"]["active_modules"]
    upsert_by_key(
        modules,
        "module_id",
        {
            "module_id": "native-chinese-dialogue",
            "title": "中文母语感对白生成与翻译腔修正规则",
            "scope": "global_dialogue",
            "priority": "high",
            "enforcement": "mandatory",
        },
    )
    manifest["audit"]["conflict_rule"] = (
        "发生冲突时，以总纲补丁及更具体的当前场景规则为准；对白必须同时遵守角色私有性、"
        "接话连续性和中文母语感，不得为机械合规破坏正常叙事。"
    )
    write_yaml(manifest_path, manifest)


def update_registries() -> None:
    module_map = load_yaml(MODULE_MAP)
    for row in module_map["modules"]:
        if row.get("story_id") == STORY_ID and row.get("timeline_id") == TIMELINE_ID and row.get("module_type") == "judgment_spec":
            row["active_version"] = "judgment-global-v1.1"
            break
    else:
        raise ValueError("judgment_spec module-map entry missing")
    write_yaml(MODULE_MAP, module_map)

    version_map = load_yaml(VERSION_MAP)
    versions = version_map.setdefault("versions", [])
    upsert_by_key(
        versions,
        "document_family",
        {
            "document_family": "judgment-global",
            "current": "judgment-global-v1.1",
            "supersedes": ["judgment-global-v1.0"],
            "reason": "加入中文母语感对白的关系、意图、潜台词、接话触发和节奏权限规划协议",
        },
    )
    upsert_by_key(
        versions,
        "document_family",
        {
            "document_family": "style-global-manifest",
            "current": "style-global-manifest-v1.3",
            "supersedes": ["style-global-manifest-v1.2", "style-global-manifest-v1.1", "style-global-manifest-v1.0"],
            "reason": "启用中文母语感对白生成与翻译腔修正模块",
        },
    )
    upsert_by_key(
        versions,
        "document_family",
        {
            "document_family": "style-native-chinese-dialogue",
            "current": "style-native-chinese-dialogue-v1.0",
            "supersedes": [],
            "reason": "导入用户确认的中文母语感对白生成与翻译腔修正规则",
        },
    )
    write_yaml(VERSION_MAP, version_map)


def update_retrieval_tests() -> None:
    data = load_yaml(RETRIEVAL_TESTS)
    tests = data["tests"]
    for case in tests:
        if case.get("id") == "judgment-global-generation-plan":
            case["expected_document_ids"] = ["judgment-global-v1.1"]
    upsert_by_key(
        tests,
        "id",
        {
            "id": "judgment-native-chinese-dialogue",
            "story_id": STORY_ID,
            "timeline_id": TIMELINE_ID,
            "query": "dialogue_planning_policy",
            "document_types": ["judgment_spec"],
            "expected_document_ids": ["judgment-global-v1.1"],
            "forbidden_document_ids": ["judgment-global-v1.0"],
            "forbidden_statuses": ["draft", "deprecated", "archived"],
            "checks": ["correctness", "timeline_isolation", "version", "content_type"],
        },
    )
    upsert_by_key(
        tests,
        "id",
        {
            "id": "style-native-chinese-dialogue",
            "story_id": STORY_ID,
            "timeline_id": TIMELINE_ID,
            "query": "native_chinese_dialogue_style",
            "document_types": ["style_audit"],
            "expected_document_ids": ["style-native-chinese-dialogue-v1.0"],
            "forbidden_statuses": ["draft", "deprecated", "archived"],
            "checks": ["correctness", "timeline_isolation", "version", "content_type"],
        },
    )
    write_yaml(RETRIEVAL_TESTS, data)


def main() -> None:
    upgrade_judgment()
    create_style_module()
    upgrade_style_manifest()
    update_registries()
    update_retrieval_tests()
    print("judgment=judgment-global-v1.1")
    print("style_manifest=style-global-manifest-v1.3")
    print("style_module=style-native-chinese-dialogue-v1.0")


if __name__ == "__main__":
    main()
