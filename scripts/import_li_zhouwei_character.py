from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RAG = ROOT / "novel-rag" / "stories" / "overturned-world-fujimaru"
STORY_ID = "overturned-world-fujimaru"
TIMELINE_ID = "main"
CHARACTER_ID = "li-zhouwei"
TODAY = "2026-07-17"
SOURCE_REF = "user-message:2026-07-17/li-zhouwei-servant-profile"


SOURCE_PROFILE = """真名：李周巍——出自中国神代末期“玄鉴仙族”世间李家，以白麒麟之身降生的天命之子。其最终成道号为“至命天下明阳御世真君”。在英灵座的记录中，他归属于“东方・中国神代末期”的分类，是一位已被现世历史完全遗忘的、拥有极高神秘度的无铭帝王。

传说：降生之时天象异变，白麒麟口衔婴儿、白蝉漫天飞舞，被至高意志“明阳”选定为钟爱之人。少年时代以甲子魄练戟兵术出道，手持大戟纵横天下，打遍世间紫府真人无有敌手，被诸族尊为“魏王”，号世间第二显、明阳之子。

世间大局急转直下，李家面临灭族之危。为了获得足以逆天改命的力量，他将自己所有子嗣吞噬入腹，以骨肉至亲为薪，修成禁忌并火神通“至命除”。自此白麒麟化为妖明阳，半人半妖半神，三界莫辨其类。他向天霞与阴司发起复仇之战，最终功成，以妖明阳之身悟道飞升，被冠以“至命天下明阳御世真君”之号。

他的传说随中国神代终结一同被埋葬，现世无人知晓其名，也无典籍记载其事迹；英灵座仍如实铭刻这位吞噬己子、斩裂天穹的东方帝王。

性格：果断、自信、谨慎、豪爽。具有帝王气度与决断力，不在战斗中犹豫，也不在抉择前退缩；同时拥有极高战术直觉与危险嗅觉。对认可者毫无保留，对追随者赏罚分明。战斗风格霸道直接，以锁喉、头槌、一拳碎颅等绝对力量碾碎阻碍。吞噬子嗣是灵基中永恒伤痕：他不会表现或提及，不后悔，但始终记得。这塑造了其“混沌・善”属性——做了最残忍的事，却是为了最正义的目的。

对圣杯的愿望：表面没有。灵基深层想再见被自己亲手吞噬的孩子们；不是为了道歉或赎罪，只想看他们一眼。

职阶技能：对魔力B。

保有技能：完全なる形A++、心眼（伪）A+、心眼（真）A+、领袖气质EX、明彰日月A、甲子魄练戟兵术EX、火术EX、行走法B、君韬危EX、赤断镞EX、白麒麟、至命除EX。

宝具：谒天门A+（对人）、帝观元A++（对界）、乾阳镯EX（对人）、次显锻白再明王戟EX（对界）。"""


ABILITY_SPECS = [
    {
        "slug": "magic-resistance",
        "name": "对魔力",
        "rank": "B",
        "category": "class_skill",
        "type": "Lancer职阶基础抗魔技能",
        "effect": "李周巍的灵基本就对超自然干涉具有极高抗性，从者容器进一步将其格式化为对魔力；可无效化三节以下魔术，大魔术也难以造成实质伤害。",
        "activation": "常时被动生效。",
        "range": "李周巍自身。",
        "cost": "无已说明的主动消耗。",
        "limitations": ["对大魔术的效果描述为难以造成实质伤害，并非绝对无效。", "对神代魔术、宝具与非魔术超自然干涉的具体抗性未说明。"],
        "failure_conditions": [],
        "narrative_function": ["抵抗常规魔术与多数超自然干涉。"],
    },
    {
        "slug": "perfect-form",
        "name": "完全なる形",
        "rank": "A++",
        "category": "personal_skill",
        "type": "肉体巅峰与体术压制",
        "effect": "白麒麟躯体经甲子魄练与并火改造后突破生物极限，在战斗中表现为杂技般空中变向、不可预测的攻击轨迹和压倒性的体术压制力。",
        "activation": "以肉体和武术战斗时持续发挥。",
        "range": "李周巍自身及近身战范围。",
        "cost": "未说明。",
        "limitations": ["具体速度、力量增幅与持续时间未说明。"],
        "failure_conditions": [],
        "narrative_function": ["支撑超越常识的机动与近战压制。"],
    },
    {
        "slug": "mind-eye-false",
        "name": "心眼（伪）",
        "rank": "A+",
        "category": "personal_skill",
        "type": "天生战斗直觉与危险预知",
        "effect": "由白麒麟与生俱来的危险预知格式化而成，可在攻击到来前的瞬间捕捉“死亡的气息”并作出回避。",
        "activation": "致命攻击即将到来时被动触发。",
        "range": "李周巍自身感知范围；精确距离未说明。",
        "cost": "无已说明的主动消耗。",
        "limitations": ["不能据此推定为必定回避；速度、空间或身体状态不足时的结果未说明。"],
        "failure_conditions": [],
        "narrative_function": ["提前感知致命危险并争取回避窗口。"],
    },
    {
        "slug": "mind-eye-true",
        "name": "心眼（真）",
        "rank": "A+",
        "category": "personal_skill",
        "type": "后天战斗经验与绝境分析",
        "effect": "来自征战世间、打遍天下紫府真人的实战积累，可在绝境中冷静分析局势并寻找反败为胜的活路；与心眼（伪）叠加后几乎不存在战斗认知盲区。",
        "activation": "战斗观察与绝境分析时发挥。",
        "range": "李周巍自身认知与战场观察范围。",
        "cost": "无已说明的主动消耗。",
        "limitations": ["“几乎不存在认知盲区”不等于全知，也不保证一定找到胜机。"],
        "failure_conditions": [],
        "narrative_function": ["在不利局面中建立正确战术判断。"],
    },
    {
        "slug": "charisma",
        "name": "领袖气质",
        "rank": "EX",
        "category": "personal_skill",
        "type": "概念级王权辐射",
        "effect": "明阳钟爱之人的帝王威压，对面对他的存在施加精神层面的威慑与信服；无足够抗性的女性角色会受到不自主的魅惑影响。",
        "activation": "他人面对李周巍时被动发挥。",
        "range": "具体距离未说明。",
        "cost": "无已说明的主动消耗。",
        "limitations": ["作为从者技能时强度受职阶容器限制。", "足够精神抗性可抵抗女性魅惑效果；抗性标准未说明。", "不能把威慑与信服直接写成永久洗脑。"],
        "failure_conditions": [],
        "narrative_function": ["建立帝王威压、统率力与对特定对象的魅惑压力。"],
    },
    {
        "slug": "mingzhang-sun-and-moon",
        "name": "明彰日月",
        "rank": "A",
        "category": "personal_skill",
        "type": "战斗积累型道行与能力适应",
        "effect": "每次战斗积累道行，在从者框架下转化为数值强化与机制免疫叠加；与同一对手交战一次后，对手的能力与权能在下一次交锋中被削弱，多次交战后可完全无效化特定能力。",
        "activation": "经历战斗并再次与相同对手交锋时被动积累、结算。",
        "range": "李周巍自身及其曾交战的特定对手。",
        "cost": "未说明。",
        "limitations": ["每次削弱幅度、完全无效所需交战次数、可适应能力数量与持续期限未说明。", "首次交锋不享有针对该对手的既往削弱。"],
        "failure_conditions": [],
        "narrative_function": ["让重复交战逐步转化为对敌方权能的压制与免疫。"],
    },
    {
        "slug": "jiazi-soul-tempered-halberd-art",
        "name": "甲子魄练戟兵术",
        "rank": "EX",
        "category": "personal_skill",
        "type": "大戟道术与乌炎法身",
        "effect": "李周巍独创的邃气戟术；在征战与喂食资粮中可诞生乌炎法身，当前法身能形成完整乌色麒麟，战斗力对标天之公牛。",
        "activation": "以大戟战斗，或消耗魔力展开乌炎法身。",
        "range": "近战及乌色麒麟法身的活动范围；精确距离未说明。",
        "cost": "完全展开法身需要极大量魔力。",
        "limitations": ["从者状态下受魔力供给约束。", "法身持续时间、受损恢复与极大量魔力的数值未说明。"],
        "failure_conditions": ["魔力供给不足时不能确认能够完全展开乌色麒麟法身。"],
        "narrative_function": ["以大戟体系近战，并召出天之公牛级乌色麒麟法身。"],
    },
    {
        "slug": "fire-arts",
        "name": "火术",
        "rank": "EX",
        "category": "personal_skill",
        "type": "明阳亲切离火道术体系",
        "effect": "掌握多种高品质火系道术，包括大范围火焰制压《六府帝赦术》、集束光炮《帝歧光》与吞噬型火焰控制《饮日有功术》等。",
        "activation": "按战术需要施展对应火系道术。",
        "range": "随具体术式变化；未说明。",
        "cost": "未说明。",
        "limitations": ["从者容器限制火术威力。", "各子术式的独立消耗、范围与冷却未说明。"],
        "failure_conditions": [],
        "narrative_function": ["提供大范围制压、光炮与吞噬控制等多样火力。"],
    },
    {
        "slug": "walking-method",
        "name": "行走法",
        "rank": "B",
        "category": "personal_skill",
        "type": "太虚行走与类虚数空间瞬移",
        "effect": "以太虚行走法进行类似穿过虚数空间的瞬间移动，为战术提供高机动优势。",
        "activation": "李周巍主动施展太虚行走法。",
        "range": "移动距离未说明。",
        "cost": "受魔力供给限制。",
        "limitations": ["从者状态下移动距离与使用频率受魔力供给限制。", "不能据此推定为无条件跨世界或无限距离传送。"],
        "failure_conditions": ["魔力供给不足时移动距离或频率下降；具体阈值未说明。"],
        "narrative_function": ["执行瞬时突进、转移、追击与脱离。"],
    },
    {
        "slug": "juntaowei",
        "name": "君韬危",
        "rank": "EX",
        "category": "personal_skill",
        "type": "逆境持续成长神通",
        "effect": "当李周巍被围攻、陷入劣势或灵核受损等逆境时，全属性随时间持续增长，增长速度极快且没有上限。",
        "activation": "处于已确认的逆境时被动发动。",
        "range": "李周巍自身。",
        "cost": "未说明。",
        "limitations": ["何时构成逆境、增长曲线与逆境结束后的保留时间未说明。", "无上限是能力设定，不代表已发生的伤势会自动恢复。"],
        "failure_conditions": ["未处于逆境时不满足已确认发动条件。"],
        "narrative_function": ["把正面围剿和劣势持续转化为不断扩大的属性优势。"],
    },
    {
        "slug": "red-severing-arrowhead",
        "name": "赤断镞",
        "rank": "EX",
        "category": "personal_skill",
        "type": "赤色夕阳凝刃与阴光歼灭",
        "effect": "将赤色夕阳凝聚为利刃，可用于高速逃脱与追逐，也可化作极致阴光射向敌人；阴光最低威力已超过乖离剑EA的基础出力。",
        "activation": "凝聚赤色夕阳并选择移动利刃或远程阴光形态。",
        "range": "未说明。",
        "cost": "未说明。",
        "limitations": ["最大威力、射程、使用频率与对比所指EA具体解放状态未进一步说明。"],
        "failure_conditions": [],
        "narrative_function": ["执行高速追逃或高出力远程歼灭。"],
    },
    {
        "slug": "white-qilin",
        "name": "白麒麟",
        "rank": "—",
        "category": "inherent_trait",
        "type": "固有体质与对王特防",
        "effect": "天下第二显、帝王之昭；一切拥有【王】属性的存在对李周巍发动攻击时，威力降低到正常情况的三成。",
        "activation": "拥有【王】属性的存在攻击李周巍时被动适用。",
        "range": "针对命中或作用于李周巍的攻击。",
        "cost": "无已说明消耗。",
        "limitations": ["【王】属性的完整判定规则未说明；吉尔伽美什、亚瑟王、伊斯坎达尔是已给出的适用例。", "只确认攻击威力降低，不代表王属性敌人的非攻击能力也被削弱。"],
        "failure_conditions": ["攻击者不具备【王】属性时不触发已确认的三成减伤。"],
        "narrative_function": ["显著压制王者英灵对李周巍的直接攻击。"],
    },
    {
        "slug": "zhimingchu",
        "name": "至命除",
        "rank": "EX",
        "category": "personal_skill",
        "type": "并火命神通",
        "effect": "吞噬己子后获得的禁忌能力：控制各种火焰，包括从者火焰系宝具；压制所有神兽与幻想种；彻底免疫地、水、火、风、空五大元素的直接伤害；并能以灰色并火燃烧目标神智，直接攻击精神与灵魂。",
        "activation": "李周巍主动控制火焰、压制神兽幻想种或释放灰色并火；五元素直接伤害免疫常时适用。",
        "range": "未说明。",
        "cost": "以吞噬全部子嗣为成道代价；从者状态下的单次使用消耗未说明。",
        "limitations": ["五元素免疫明确针对直接伤害，间接、复合或概念效果是否免疫未说明。", "控制他人火焰系宝具的距离、争夺规则与上限未说明。", "对神兽与幻想种的压制幅度及抵抗条件未说明。"],
        "failure_conditions": [],
        "narrative_function": ["夺取火焰控制权、压制神兽幻想种、免疫元素直伤并灼烧精神灵魂。"],
    },
    {
        "slug": "audience-at-heavens-gate",
        "name": "谒天门",
        "rank": "A+",
        "category": "noble_phantasm",
        "type": "对人宝具 / 明阳帝权现象镇压",
        "effect": "真名解放后从虚空降下巨大天门，镇压宝具展开、封锁从者行动并压制抵抗；目标反抗越剧烈，天门压制力越强。",
        "activation": "解放真名并降下天门。",
        "range": "对人；具体距离未说明。",
        "cost": "未说明。",
        "limitations": ["持续时间、同时镇压目标数量、初始压制强度与脱离条件未说明。"],
        "failure_conditions": [],
        "narrative_function": ["以挣扎即自缚的机制压制目标行动与宝具展开。"],
        "release_chant": ["明阳敕令，天门垂临——", "万象俯首，诸灵叩拜——", "谒天门！"],
    },
    {
        "slug": "imperial-view-origin",
        "name": "帝观元",
        "rank": "A++",
        "category": "noble_phantasm",
        "type": "对界宝具 / 内现增幅与外展固有结界",
        "effect": "面对强敌时以内现模式化作包裹自身的顶级防护增幅结界，使全属性上升一个大等级；面对弱者时以外展模式展开辉煌明阳宫殿固有结界，其中一切存在都受到李周巍的概念特攻。",
        "activation": "解放真名并依敌我强弱选择内现或外展模式。",
        "range": "对界；固有结界具体范围未说明。",
        "cost": "未说明。",
        "limitations": ["强敌与弱者的判定标准、两模式能否切换或共存、持续时间未说明。"],
        "failure_conditions": [],
        "narrative_function": ["对强敌强化自身防护与全属性，对弱者展开帝国领域实施概念特攻。"],
        "release_chant": ["孤之帝业，万里山河——", "帝观元！"],
    },
    {
        "slug": "qianyang-bracelet",
        "name": "乾阳镯",
        "rank": "EX",
        "category": "noble_phantasm",
        "type": "对人宝具 / 天道手铐",
        "effect": "明阳真君赐予龙属的金色手镯；真名解放后，无论对手是谁、拥有何种抗性或回避手段，都必定陷入一瞬间的恍惚与停顿。",
        "activation": "解放真名，以乾阳镯锁定目标。",
        "range": "对人；具体距离未说明。",
        "cost": "未说明。",
        "limitations": ["停顿极短。", "重复使用、目标数量、冷却与是否需要先完成锁定未说明。"],
        "failure_conditions": [],
        "narrative_function": ["制造顶级交锋中必然成立的瞬时破绽。"],
        "release_chant": ["明阳赐镯，龙属伏膺——", "乾阳镯——锁！"],
    },
    {
        "slug": "second-manifest-forged-white-renewed-ming-king-halberd",
        "name": "次显锻白再明王戟",
        "rank": "EX",
        "category": "noble_phantasm",
        "type": "对界宝具 / 斩裂天空的王戟",
        "effect": "陪伴李周巍从凡人战至真人的主武装与灵基核心；真名解放后挥出足以斩裂天空的一戟，在从者容器限制下，全力一击威力约等同魔神王盖提亚的第三宝具。",
        "activation": "解放完整真名并以王戟发动全力斩击。",
        "range": "对界；具体范围未说明。",
        "cost": "未说明。",
        "limitations": ["从者容器对其力量存在限制。", "蓄力时间、使用次数、反作用与对比所指盖提亚第三宝具的具体工况未说明。"],
        "failure_conditions": [],
        "narrative_function": ["作为世间第二显的最终手段，发动斩裂天空的对界一击。"],
        "release_chant": ["甲子魄练，百战不休——", "白麒麟啸，明阳再显——", "次显锻白再明——王戟！"],
    },
]


def write_document(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def ability_document(spec: dict) -> dict:
    document_id = f"canon-ability-li-zhouwei-{spec['slug']}-v1.0"
    ability = {
        "retrieval_key": f"li_zhouwei_{spec['slug'].replace('-', '_')}",
        "name": spec["name"],
        "owner": "李周巍",
        "owner_id": CHARACTER_ID,
        "rank": spec["rank"],
        "category": spec["category"],
        "type": spec["type"],
        "effect": spec["effect"],
        "activation": spec["activation"],
        "range": spec["range"],
        "cost": spec["cost"],
        "limitations": spec["limitations"],
        "failure_conditions": spec["failure_conditions"],
        "known_by": ["李周巍"],
        "visual_expression": "未说明。",
        "narrative_function": spec["narrative_function"],
        "canon_notes": [],
    }
    if "release_chant" in spec:
        ability["release_chant"] = spec["release_chant"]
    return {
        "metadata": {
            "document_id": document_id,
            "story_id": STORY_ID,
            "timeline_id": TIMELINE_ID,
            "document_type": "canon",
            "title": f"{'宝具' if spec['category'] == 'noble_phantasm' else '能力'}设定-李周巍-{spec['name']}",
            "entity": "noble_phantasm" if spec["category"] == "noble_phantasm" else "ability",
            "character_ids": [CHARACTER_ID],
            "event_tags": [spec["name"], spec["rank"], spec["category"]],
            "version": "1.0",
            "status": "canon",
            "canon_scope": "timeline",
            "created_at": TODAY,
            "updated_at": TODAY,
            "supersedes": None,
            "source_file": SOURCE_REF,
        },
        "ability": ability,
    }


def character_document() -> dict:
    ability_refs = [
        {
            "name": spec["name"],
            "rank": spec["rank"],
            "reference": f"canon-ability-li-zhouwei-{spec['slug']}-v1.0",
        }
        for spec in ABILITY_SPECS
    ]
    return {
        "metadata": {
            "document_id": "canon-character-li-zhouwei-v1.0",
            "story_id": STORY_ID,
            "timeline_id": TIMELINE_ID,
            "document_type": "canon",
            "title": "角色设定-李周巍",
            "entity": "servant",
            "character_ids": [CHARACTER_ID],
            "event_tags": ["Lancer", "白麒麟", "魏王", "明阳", "中国神代末期"],
            "version": "1.0",
            "status": "canon",
            "canon_scope": "timeline",
            "created_at": TODAY,
            "updated_at": TODAY,
            "supersedes": None,
            "source_file": SOURCE_REF,
        },
        "character": {
            "retrieval_key": "li_zhouwei_profile",
            "name": "李周巍",
            "aliases": ["至命天下明阳御世真君", "魏王", "世间第二显", "明阳之子", "妖明阳", "白麒麟"],
            "identity": {
                "true_name": "李周巍",
                "class": "Lancer",
                "master": None,
                "gender": "男",
                "alignment": "混沌・善",
                "origin": "中国神代末期玄鉴仙族世间李家",
                "classification_on_throne": "东方・中国神代末期",
                "mystery": "极高",
                "historical_status": "现世历史完全遗忘、无典籍记载的无铭帝王",
                "final_taoist_title": "至命天下明阳御世真君",
                "height": None,
                "weight": None,
                "parameters": None,
            },
            "appearance": ["未说明。"],
            "personality_core": [
                "果断、自信、谨慎、豪爽",
                "拥有帝王气度与决断力，不在战斗或抉择前退缩",
                "并非莽夫，具有极高战术直觉与危险嗅觉",
                "对认可者毫无保留，对追随者赏罚分明",
                "吞噬子嗣是永恒伤痕；不表现、不提及、不后悔，但始终记得",
            ],
            "surface_behavior": [
                "战斗风格霸道直接，不取巧、不矫饰，以绝对力量碾碎阻碍",
                "会使用锁喉、头槌、一拳碎颅等帝王式暴力动作",
            ],
            "values": ["保护李家并以最正义的目的逆天改命", "认可实力、忠诚与承担后果"],
            "goals": ["作为从者完成当前契约目标；具体御主与现界目标未说明"],
            "fears": [],
            "boundaries": [],
            "speech_patterns": ["具帝王口吻，直接、自信、豪爽；不主动谈论被吞噬的子嗣"],
            "holy_grail_wish": {
                "surface": "没有；对万能许愿机兴趣寥寥",
                "deep": "想再见被自己亲手吞噬的孩子们一眼",
                "not_for": ["道歉", "赎罪"],
            },
            "origin_and_legend": [
                "降生时天象异变，白麒麟口衔婴儿、白蝉漫天飞舞，被至高意志明阳选为钟爱之人",
                "少年以甲子魄练戟兵术出道，持大戟打遍世间紫府真人，被诸族尊为魏王、世间第二显、明阳之子",
                "李家面临灭族时吞噬全部子嗣，以骨肉至亲为薪修成禁忌并火神通至命除",
                "白麒麟由此化为妖明阳，成为半人半妖半神、三界莫辨其类的存在",
                "向天霞与阴司复仇成功，以妖明阳之身悟道飞升，成道号至命天下明阳御世真君",
                "传说随中国神代终结被埋葬，现世完全遗忘，唯有英灵座保留记录",
            ],
            "weapons": [
                {"name": "次显锻白再明王戟", "reference": "canon-ability-li-zhouwei-second-manifest-forged-white-renewed-ming-king-halberd-v1.0"}
            ],
            "abilities": ability_refs,
            "limitations": [
                "御主、身高、体重、外貌、从者能力值与现界位置未说明，不得自行指定",
                "除明确写出的能力外，不得把神代帝王身份扩展成未确认权能",
                "能力中未说明的距离、消耗、持续时间、冷却与抵抗条件必须保持未知",
                "李周巍尚未在第十四章正式正文中现界，因此不建立当前角色状态",
            ],
            "relationships": [
                {"target": "明阳", "relationship": "被至高意志选定的钟爱之人"},
                {"target": "被吞噬的全部子嗣", "relationship": "永恒伤痕与深层圣杯执念；不后悔但记得"},
                {"target": "玄鉴仙族世间李家", "relationship": "出身家族与逆天改命的保护对象"},
            ],
            "prohibited_interpretations": [
                "不得把李周巍与杨浞、天照命或其他同类术法使用者视为同一角色",
                "不得把吞噬子嗣写成已经完成忏悔或寻求赎罪；他不后悔，但始终记得",
                "不得因战斗暴烈把他写成无谋莽夫",
                "不得让现世普通人物无依据知晓其真名与传说；其历史已被完全遗忘",
                "不得擅自削弱、平衡或改写用户明确给出的绝对效果与强度比较",
                "不得为御主、能力值、外貌、能力代价或技能抵抗条件擅自补设定",
            ],
            "source_profile": SOURCE_PROFILE,
        },
    }


def main() -> None:
    character_path = RAG / "canon" / "characters" / "li-zhouwei.yaml"
    write_document(character_path, character_document())
    ability_paths: list[Path] = []
    for spec in ABILITY_SPECS:
        path = RAG / "canon" / "abilities" / f"li-zhouwei-{spec['slug']}.yaml"
        write_document(path, ability_document(spec))
        ability_paths.append(path)

    assert len(ability_paths) == 17
    ids = {json.loads(path.read_text(encoding="utf-8"))["metadata"]["document_id"] for path in ability_paths}
    assert len(ids) == 17
    print(f"character={character_path.name} abilities={len(ability_paths)}")


if __name__ == "__main__":
    main()
