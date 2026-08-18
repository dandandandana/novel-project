from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RAG = ROOT / "novel-rag" / "stories" / "overturned-world-fujimaru"
SOURCE = str(ROOT / "outputs" / "第四卷_第14章_续写.txt")
TODAY = "2026-07-17"


def metadata(name: str, character_id: str, variant_id: str, version: str, supersedes: str | None) -> dict:
    return {
        "document_id": f"state-current-{character_id}-v{version}",
        "story_id": "overturned-world-fujimaru",
        "timeline_id": "main",
        "document_type": "character_state",
        "title": f"当前状态-{name}",
        "character_id": character_id,
        "variant_id": variant_id,
        "snapshot_type": "current",
        "effective_at": "volume-04-chapter-014",
        "last_updated": TODAY,
        "version": version,
        "status": "active",
        "supersedes": supersedes,
        "source_file": SOURCE,
    }


def physical(health: str, injuries: list[str], fatigue: str = "重度战斗消耗") -> dict:
    return {
        "health": health,
        "injuries": injuries,
        "fatigue": fatigue,
        "temporary_conditions": [],
        "permanent_changes": [],
    }


def knowledge(known: list[str], unknown: list[str]) -> dict:
    return {
        "known": known,
        "unknown": unknown,
        "mistaken_beliefs": [],
        "suspicions": [],
        "secrets_held": [],
    }


def goals(immediate: list[str], obstacles: list[str]) -> dict:
    return {
        "immediate": immediate,
        "short_term": ["完成对弥勒的降格、主炮与创造之禊祓衔接"],
        "long_term": ["修复特异点"],
        "priorities": ["完成任务", "同伴生存"],
        "obstacles": obstacles,
    }


def abilities(available: list[str], unavailable: list[str] | None = None, newly: list[str] | None = None,
              consumed: list[str] | None = None, costs: list[str] | None = None) -> dict:
    return {
        "available": available,
        "unavailable": unavailable or [],
        "newly_acquired": newly or [],
        "consumed_resources": consumed or [],
        "active_costs": costs or [],
    }


def narrative(completed: list[str], unresolved: list[str], future: list[str]) -> dict:
    return {
        "current_arc": "日本下篇：伊耶那岐金地决战",
        "completed_changes": completed,
        "unresolved_flags": unresolved,
        "active_promises": [],
        "future_pressure": future,
    }


STATES = {
    "fujimaru-ritsuka": {
        "metadata": metadata("藤丸立香", "fujimaru-ritsuka", "fujimaru-ritsuka-main", "1.3", "state-current-fujimaru-ritsuka-v1.2"),
        "character_state": {
            "current_position": {"location": "伊耶那岐金地东门盆地外围", "companions": ["言峰士郎", "玛修·基列莱特"], "faction": "迦勒底协同行动方"},
            "physical": physical("无明确新增伤势", [], "持续作战，疲劳程度未明确"),
            "mental": {"dominant_emotions": ["专注", "警惕"], "current_pressure": ["杨浞与吉尔伽美什重伤", "弥勒仍未解决"], "desires": ["治疗伤员并继续完成弥勒降格与主炮计划"], "fears": [], "unresolved_conflicts": [], "behavior_effects": ["天照命败北后仍保持主炮计划不变"]},
            "knowledge": knowledge(["主炮信标已自锁并由Alterego组防守", "创造之禊祓已由千子村正取得", "天照命已被降格并失去继续战斗能力", "神琦灰的目标不止于维持当前人理", "Alterego阿尔托莉雅仍保留潘多拉宝具"], ["创造之禊祓的具体代价", "神琦灰超越当前人理的真实目标", "终末人理圆满装置隐瞒的最终目的"]),
            "goals": goals(["治疗杨浞与吉尔伽美什", "建立通往地下的伤员撤离路线"], ["弥勒", "北侧新增十七尊法相", "伤员战力严重下降"]),
            "relationships": [{"target_character": "yang-zhuo", "relationship_type": "御主与从者", "trust": "已完成关键战斗协同", "dependence": "战斗合作", "hostility": "无", "current_attitude": "优先确认其存活并安排治疗", "unresolved_issues": [], "recent_change": "消耗一道令咒以英杰之帜将其推至本体顶峰"}],
            "abilities": abilities(["降格术", "英杰之帜"], consumed=["一道令咒（英杰之帜用于杨浞）"], costs=["剩余令咒两道"]),
            "inventory": {"carried": [], "lost": [], "damaged": []},
            "narrative": narrative(["完成主炮信标安置与自锁", "对天照命完成降格", "确认创造之禊祓已取得"], ["主炮尚未发射", "弥勒尚未降格", "创造之禊祓代价未知"], ["必须在伤员严重受损的条件下继续弥勒终局战"]),
        },
    },
    "yang-zhuo": {
        "metadata": metadata("杨浞", "yang-zhuo", "yang-zhuo-main", "1.2", "state-current-yang-zhuo-v1.1"),
        "character_state": {
            "current_position": {"location": "伊耶那岐金地东门盆地，正向外围移动", "companions": ["吉尔伽美什", "藤丸立香", "言峰士郎", "玛修·基列莱特"], "faction": "迦勒底协同行动方"},
            "physical": physical("重伤但存活，仍能勉强移动", ["左臂缺失，章末尚未恢复", "右肩开放性断裂，锁骨外露", "腹部贯穿且多次裂开，暂由真炁封住", "左腿受至命除影响，行动迟缓", "灵基持续受至命除余火干扰"]),
            "mental": {"dominant_emotions": ["倔强", "专注"], "current_pressure": ["重伤且弥勒仍未解决"], "desires": ["接受治疗并继续履行从者契约"], "fears": [], "unresolved_conflicts": [], "behavior_effects": ["即使重伤仍试图自行行走并与吉尔伽美什较劲"]},
            "knowledge": knowledge(["天照命由无名孔雀、天照御名、弥勒佛果与母子线等结构叠加", "乌从欲会沿目标所求之事侵蚀", "至命除曾以法相和失败未来支付代价", "天照命已停止燃烧众生命并败北"], ["英杰之帜强化在章末是否继续维持", "能否在弥勒终战前恢复"]),
            "goals": goals(["接受治疗", "维持继续作战的可能"], ["严重伤势", "问武平清觯与奉真策玄鞭受损", "弥勒"]),
            "relationships": [{"target_character": "fujimaru-ritsuka", "relationship_type": "从者与御主", "trust": "已完成关键战斗协同", "dependence": "契约与支援", "hostility": "无", "current_attitude": "认可御主判断并继续履约", "unresolved_issues": [], "recent_change": "接受英杰之帜并完成天照命决战"}],
            "abilities": abilities(["真炁六水火", "修武星", "霞羽客", "檀真", "天武真炁神煞真君", "问武平清觯", "奉真策玄鞭"], costs=["英杰之帜强化是否仍维持未明确", "问武平清觯恢复速度受裂纹与至命除余火影响"]),
            "inventory": {"carried": ["真武正性剑", "问武平清觯", "奉真策玄鞭"], "lost": [], "damaged": ["问武平清觯杯壁出现裂纹", "奉真策玄鞭出现接近贯穿的裂口", "檀真左翼重创后化回水火"]},
            "narrative": narrative(["与吉尔伽美什共同击败天照命", "救出六十六个法相光影"], ["重伤治疗", "弥勒终战", "英杰之帜是否继续维持"], ["当前战力与宝具状态不足以无代价继续高强度作战"]),
        },
    },
    "gilgamesh": {
        "metadata": metadata("吉尔伽美什", "gilgamesh", "gilgamesh-main", "1.1", "state-current-gilgamesh-v1.0"),
        "character_state": {
            "current_position": {"location": "伊耶那岐金地东门盆地，正向外围移动", "companions": ["杨浞", "藤丸立香", "言峰士郎", "玛修·基列莱特"], "faction": "迦勒底协同行动方"},
            "physical": physical("重伤但存活，需要EA支撑移动", ["左肩、锁骨和部分胸腔被灰火抹除", "左腿从膝盖向上失去知觉", "右手虎口裂至腕部"]),
            "mental": {"dominant_emotions": ["高傲", "专注"], "current_pressure": ["重伤且弥勒仍未解决"], "desires": ["接受治疗并保留继续对弥勒作战的能力"], "fears": [], "unresolved_conflicts": [], "behavior_effects": ["用王之财宝门扉强行完成移动，不承认落后于杨浞"]},
            "knowledge": knowledge(["天照命的孔雀卵、城市羽目、乌从欲与至命除机制", "天照命已经败北并退化为普通大小孔雀"], ["能否在弥勒终战前恢复"]),
            "goals": goals(["接受治疗", "保留EA与王之财宝的后续作战能力"], ["严重伤势", "连续解放EA造成的负担", "弥勒"]),
            "relationships": [{"target_character": "yang-zhuo", "relationship_type": "并肩作战的王者", "trust": "战斗协同成立", "dependence": "互相补足机制与火力", "hostility": "竞争性口角", "current_attitude": "认可其战力但拒绝示弱", "unresolved_issues": [], "recent_change": "共同完成对天照命的最终对波"}],
            "abilities": abilities(["王之财宝", "EA／开天辟地乖离之星", "千里眼"], costs=["EA已连续用于隔离幕、固有结界、伤害回路切断与最终对波"]),
            "inventory": {"carried": ["EA", "九枚脱离燃料状态的时间卵"], "lost": [], "damaged": []},
            "narrative": narrative(["与杨浞共同击败天照命", "收纳九枚时间卵"], ["重伤治疗", "弥勒终战"], ["需要在保留王之财宝与EA战力的同时处理严重伤势"]),
        },
    },
    "sengo-muramasa": {
        "metadata": metadata("千子村正", "sengo-muramasa", "sengo-muramasa-main", "1.1", "state-current-sengo-muramasa-v1.0"),
        "character_state": {
            "current_position": {"location": "伊耶那岐金地地下第三层创造空间", "companions": ["祁荒"], "faction": "迦勒底协同行动方"},
            "physical": physical("右手被白火抹除后已经重生", ["掌心至心口留下白色火纹"], "持续承载创造之禊祓，消耗未明确"),
            "mental": {"dominant_emotions": ["坚定", "专注"], "current_pressure": ["需要维持白火洗除并打开撤离通道"], "desires": ["把选择结局的权利交还创造物自身"], "fears": [], "unresolved_conflicts": [], "behavior_effects": ["拒绝以说服或强制方式取得创造之禊祓，以锻造和自身承担促使其选择"]},
            "knowledge": knowledge(["伊耶娜美是从互相冲突的故尊记忆中自主活下来的个体", "创造之禊祓因恐惧创造物受苦而拒绝完成任何创造", "天照命已败北", "东门需要地下伤员撤离通道"], ["创造之禊祓的具体代价", "白色火纹的长期影响"]),
            "goals": goals(["与祁荒打开第三层出口", "维持对弥勒佛印与封锁的洗除"], ["弥勒封锁", "创造之禊祓代价未知"]),
            "relationships": [],
            "abilities": abilities(["灼阳之禊祓", "创造之禊祓"], newly=["创造之禊祓"], costs=["右手重生并留下贯穿掌心至心口的白色火纹", "具体使用代价未知"]),
            "inventory": {"carried": ["创造之禊祓"], "lost": [], "damaged": ["用于开门的短刀已经崩断并被白火抹去"]},
            "narrative": narrative(["确认故尊复现真相", "唤醒并取得创造之禊祓", "白火开始沿地脉洗除弥勒佛印"], ["创造之禊祓代价", "地下出口尚未完全打开"], ["必须先建立伤员撤离路线，再与主炮和降格计划衔接"]),
        },
    },
    "qihuang": {
        "metadata": metadata("祁荒", "qihuang", "qihuang-main", "1.2", "state-current-qihuang-v1.1"),
        "character_state": {
            "current_position": {"location": "伊耶那岐金地地下第三层创造空间", "companions": ["千子村正"], "faction": "迦勒底协同行动方"},
            "physical": physical("无明确新增伤势", [], "正文未明确"),
            "mental": {"dominant_emotions": ["观察", "专注"], "current_pressure": ["需要协助打开地下出口"], "desires": ["继续调查人格汇聚实验与众生欲望"], "fears": [], "unresolved_conflicts": [], "behavior_effects": ["尊重千子村正要求，没有直接插手创造之禊祓的选择"]},
            "knowledge": knowledge(["伊耶娜美是从冲突故尊记忆中自主活下来的个体", "创造之禊祓已选择千子村正", "天照命已败北", "东门伤员需要地下撤离路线"], ["创造之禊祓具体代价", "终末人理圆满装置隐瞒的最终目的"]),
            "goals": goals(["协助千子村正打开第三层出口", "继续调查人格汇聚实验"], ["弥勒封锁", "地下结构仍未完全查明"]),
            "relationships": [{"target_character": "sengo-muramasa", "relationship_type": "同行协作者", "trust": "已完成创造之禊祓协同", "dependence": "情报与行动配合", "hostility": "无", "current_attitude": "尊重其选择并提供故尊记忆", "unresolved_issues": [], "recent_change": "共同唤醒创造之禊祓"}],
            "abilities": abilities(["文明侵蚀", "收藏家", "伪装从者", "阵地建造", "寻声救苦", "大慈大悲法门", "此世全部之欲", "变化自在", "金刚杵", "杨枝净瓶"], consumed=["第三枚黑钉已用于导入故尊复现记忆"]),
            "inventory": {"carried": [], "lost": ["第三枚黑钉（已使用）"], "damaged": []},
            "narrative": narrative(["协助确认故尊复现真相", "以第三枚黑钉向创造空间导入伊耶娜美记忆"], ["人格汇聚实验仍未完全查明", "地下出口尚未完全打开"], ["先建立伤员撤离通道，再继续深入调查"]),
        },
    },
    "kotomine-shirou": {
        "metadata": metadata("言峰士郎", "kotomine-shirou", "kotomine-shirou-main", "1.2", "state-current-kotomine-shirou-v1.1"),
        "character_state": {
            "current_position": {"location": "伊耶那岐金地东门盆地外围", "companions": ["藤丸立香", "玛修·基列莱特"], "faction": "迦勒底协同行动方"},
            "physical": physical("仍可移动和战斗", ["右腕至手肘存在承担信标佛光造成的投影回路裂伤"], "持续战斗后的疲劳未明确"),
            "mental": {"dominant_emotions": ["专注", "克制"], "current_pressure": ["伤员救治与弥勒终战"], "desires": ["继续陪同藤丸立香完成计划"], "fears": [], "unresolved_conflicts": [], "behavior_effects": ["完成信标任务后回到立香身边"]},
            "knowledge": knowledge(["主炮信标已自锁并由Alterego组防守", "神琦灰的目标不止于维持当前人理", "创造之禊祓已取得", "天照命已败北"], ["神琦灰的真实目标", "创造之禊祓代价", "终末人理圆满装置最终目的"]),
            "goals": goals(["协助治疗与护送伤员", "继续保护藤丸立香"], ["投影回路裂伤", "弥勒"]),
            "relationships": [{"target_character": "fujimaru-ritsuka", "relationship_type": "伴侣与从者", "trust": "高", "dependence": "相互支持", "hostility": "无", "current_attitude": "亲密且支持", "unresolved_issues": [], "recent_change": "完成信标任务并按约回到立香身边"}],
            "abilities": abilities([], costs=["右腕至手肘投影回路裂伤"]),
            "inventory": {"carried": ["纸星星复制品"], "lost": ["主炮信标（已完成安置并自锁）"], "damaged": []},
            "narrative": narrative(["完成主炮信标安置与自锁", "在Alterego组接防后返回藤丸立香身边"], ["弥勒终战", "右臂投影回路伤势"], ["需在负伤状态下继续协助伤员撤离与终局计划"]),
        },
    },
    "mash-kyrielight": {
        "metadata": metadata("玛修·基列莱特", "mash-kyrielight", "mash-kyrielight-main", "1.2", "state-current-mash-kyrielight-v1.1"),
        "character_state": {
            "current_position": {"location": "伊耶那岐金地东门盆地外围", "companions": ["藤丸立香", "言峰士郎"], "faction": "迦勒底协同行动方"},
            "physical": physical("左臂受伤出血，仍能持盾并执行救援", ["左臂在承受金色巨掌重量时受伤并出血"], "持续作战后的疲劳未明确"),
            "mental": {"dominant_emotions": ["专注", "担忧"], "current_pressure": ["杨浞与吉尔伽美什重伤", "弥勒仍未解决"], "desires": ["保护前辈并为伤员提供治疗支援"], "fears": [], "unresolved_conflicts": [], "behavior_effects": ["立即赶往东门准备治疗"]},
            "knowledge": knowledge(["主炮信标已自锁", "天照命已败北", "杨浞与吉尔伽美什重伤", "创造之禊祓已取得"], ["创造之禊祓代价", "弥勒终战结果"]),
            "goals": goals(["为杨浞与吉尔伽美什提供保护和治疗支援"], ["左臂伤势", "弥勒", "北侧十七尊法相"]),
            "relationships": [{"target_character": "fujimaru-ritsuka", "relationship_type": "后辈与前辈", "trust": "高", "dependence": "战斗协作", "hostility": "无", "current_attitude": "忠诚并主动保护", "unresolved_issues": [], "recent_change": "在信标合围中共同承受掌中城压力"}],
            "abilities": abilities([]),
            "inventory": {"carried": ["圆桌之盾"], "lost": [], "damaged": []},
            "narrative": narrative(["协助完成信标安置与自锁", "赶赴东门接应重伤友军"], ["伤员治疗", "弥勒终战"], ["必须在自身左臂受伤时继续承担防护与救援"]),
        },
    },
    "izanami": {
        "metadata": metadata("伊耶娜美", "izanami", "izanami-main", "1.1", "state-current-izanami-v1.0"),
        "character_state": {
            "current_position": {"location": "月读命金地城主府", "companions": [], "faction": "迦勒底协同行动方"},
            "physical": physical("正文未明确异常", [], "正文未明确"),
            "mental": {"dominant_emotions": ["专注"], "current_pressure": ["持续维持四千九百二十六名居民的生命联系"], "desires": ["保护月读命金地居民"], "fears": [], "unresolved_conflicts": [], "behavior_effects": ["继续留守城主府维持生命联系"]},
            "knowledge": knowledge(["自身神话记忆与亲历记忆并不完全重合", "地下存在大量失败人格容器"], ["千子村正与祁荒对其故尊复现本质的最新判断", "创造之禊祓是否会解除居民生命联系", "终末人理圆满装置隐瞒的最终目的"]),
            "goals": goals(["维持四千九百二十六名居民生命联系"], ["弥勒", "居民与自身生命相连"]),
            "relationships": [],
            "abilities": abilities([]),
            "inventory": {"carried": [], "lost": [], "damaged": []},
            "narrative": narrative(["第十四章期间继续维持居民生命联系"], ["居民生命联系尚未解除", "弥勒终战"], ["创造之禊祓的白火可能改变金地与居民状态"]),
        },
    },
    "amaterasu-no-mikoto": {
        "metadata": metadata("天照命", "amaterasu-no-mikoto", "amaterasu-no-mikoto-main", "1.0", None),
        "character_state": {
            "current_position": {"location": "伊耶那岐金地东门残存金砖", "companions": [], "faction": "已败北的原敌对方；当前失去战斗能力"},
            "physical": physical("重伤并失去继续战斗能力，但仍存活且能够说话", ["退化为普通大小黑金孔雀", "仅余三根尾羽", "额骨与全身承受最终对波重创"], "极重度消耗"),
            "mental": {"dominant_emotions": ["疲惫", "动摇后的平静"], "current_pressure": ["已经失去借来的身份与权能"], "desires": ["观察迦勒底是否真能让众生自己选择未来"], "fears": [], "unresolved_conflicts": [], "behavior_effects": ["主动停止继续燃烧众生命", "不再坚持替众人锁死未来"]},
            "knowledge": knowledge(["迦勒底或许能够拯救众人", "真正决定是否走下去的是众人自己", "自身已能被正常伤害和败北"], ["迦勒底能否击败弥勒", "自己接下来是否会协助迦勒底"]),
            "goals": {"immediate": ["休息并观察后续战局"], "short_term": ["未明确"], "long_term": ["未明确"], "priorities": ["不再燃烧众生命"], "obstacles": ["重伤", "失去战斗能力"]},
            "relationships": [{"target_character": "yang-zhuo", "relationship_type": "战败对手", "trust": "有限", "dependence": "无", "hostility": "已经停止战斗", "current_attitude": "接受其关于众生自行选择的回答", "unresolved_issues": [], "recent_change": "被击败后承认迦勒底或许能够拯救众人"}],
            "abilities": abilities([], unavailable=["伊耶那岐金地世尊佛果", "天照御名与太阳权能", "乌从欲连接", "至命除", "孔雀卵伤势转移", "法相代偿", "历史记录复归"]),
            "inventory": {"carried": [], "lost": ["伊耶那岐金地世尊佛果", "天照御名", "太阳权能"], "damaged": []},
            "narrative": narrative(["被藤丸立香降格", "在三重宝具对波中败北", "主动停止燃烧众生命"], ["是否会协助迦勒底", "六十六个孩子的后续安置"], ["弥勒仍然存在，天照命的立场可能影响最终战"]),
        },
    },
    "kotomine-shirou-ae": {
        "metadata": metadata("言峰士郎（AE）", "kotomine-shirou-ae", "kotomine-shirou-ae-main", "1.0", None),
        "character_state": {
            "current_position": {"location": "伊耶那岐金地北侧信标石台", "companions": ["阿尔托莉雅·潘德拉贡 Alter"], "faction": "迦勒底阶段性协同行动方"},
            "physical": physical("正文未明确异常", [], "持续防守"),
            "mental": {"dominant_emotions": ["不耐烦", "专注"], "current_pressure": ["北侧新增十七尊法相"], "desires": ["守住主炮信标并修复特异点"], "fears": [], "unresolved_conflicts": [], "behavior_effects": ["接管信标防守并催促藤丸立香继续任务"]},
            "knowledge": knowledge(["神琦灰的目标不止于保住当前人理", "迦勒底不是神琦灰的唯一手段", "天照命已败北"], ["神琦灰的完整计划"]),
            "goals": goals(["与Alterego阿尔托莉雅守住主炮信标"], ["北侧十七尊法相", "弥勒"]),
            "relationships": [{"target_character": "artoria-pendragon-alter", "relationship_type": "协同行动者", "trust": "能够共同守卫信标", "dependence": "战斗协作", "hostility": "无", "current_attitude": "禁止其在非必要时开启潘多拉", "unresolved_issues": [], "recent_change": "共同接管信标防守"}],
            "abilities": abilities([]),
            "inventory": {"carried": [], "lost": [], "damaged": []},
            "narrative": narrative(["救援信标组三人并接管防守", "透露神琦灰目标超越当前人理"], ["神琦灰真实目标", "北侧法相防守", "弥勒终战"], ["主炮发射前必须守住信标"]),
        },
    },
    "artoria-pendragon-alter": {
        "metadata": metadata("阿尔托莉雅·潘德拉贡 Alter", "artoria-pendragon-alter", "artoria-pendragon-alter-main", "1.0", None),
        "character_state": {
            "current_position": {"location": "伊耶那岐金地北侧信标石台", "companions": ["言峰士郎（AE）"], "faction": "迦勒底阶段性协同行动方"},
            "physical": physical("正文未明确异常", [], "持续防守"),
            "mental": {"dominant_emotions": ["冷静", "专注"], "current_pressure": ["北侧新增十七尊法相"], "desires": ["守住主炮信标"], "fears": [], "unresolved_conflicts": [], "behavior_effects": ["在未到必要时拒绝开启潘多拉"]},
            "knowledge": knowledge(["主炮信标已自锁", "天照命已败北", "北侧出现十七尊新法相"], ["何时必须开启潘多拉"]),
            "goals": goals(["与Alterego言峰士郎守住主炮信标"], ["北侧十七尊法相", "弥勒"]),
            "relationships": [{"target_character": "kotomine-shirou-ae", "relationship_type": "协同行动者", "trust": "能够共同守卫信标", "dependence": "战斗协作", "hostility": "无", "current_attitude": "接受其关于潘多拉开启时机的限制", "unresolved_issues": [], "recent_change": "共同接管信标防守"}],
            "abilities": abilities(["潘多拉臂铠", "开启吧，灾厄与希望"], costs=["潘多拉臂铠仍然闭合，七道承伤刻纹一条未亮"]),
            "inventory": {"carried": ["潘多拉臂铠"], "lost": [], "damaged": []},
            "narrative": narrative(["救援信标组三人并接管防守", "保留潘多拉宝具未动用"], ["潘多拉开启时机", "北侧法相防守", "弥勒终战"], ["必须把潘多拉留给弥勒或更严重的威胁"]),
        },
    },
}


WORLD_STATE = {
    "metadata": {
        "document_id": "world-state-current-v1.3",
        "story_id": "overturned-world-fujimaru",
        "timeline_id": "main",
        "document_type": "world_state",
        "title": "第四卷第14章后世界状态",
        "version": "1.3",
        "status": "active",
        "effective_at": "volume-04-chapter-014",
        "supersedes": "world-state-current-v1.2",
        "source_file": SOURCE,
        "updated_at": TODAY,
    },
    "world_state": {
        "timeline_position": "第四卷第14章末，天照命败北，弥勒终战尚未完成",
        "locations": [
            {"location_id": "izanagi-golden-land-east-gate", "current_condition": "九层太阳阵地完全消失，形成数百米深圆形盆地，边缘留下白、灰、赤三圈结晶", "controlling_faction": "迦勒底取得阶段性战场控制", "accessibility": "主角组正在进入盆地接应伤员", "known_hazards": ["东西山系持续下沉", "战斗余波与不稳定金砖"], "recent_events": ["天照命败北并退化为普通大小黑金孔雀", "杨浞与吉尔伽美什重伤"]},
            {"location_id": "izanagi-golden-land-underground", "current_condition": "创造空间已开启，白火沿地脉洗去弥勒佛印与封锁", "controlling_faction": "千子村正与祁荒所在的迦勒底协同行动方", "accessibility": "第三层出口正在打开，计划作为伤员撤离通道", "known_hazards": ["创造之禊祓代价未知", "人格容器与地下实验尚未完全查明"], "recent_events": ["千子村正取得创造之禊祓", "确认伊耶娜美属于故尊复现"]},
            {"location_id": "izanagi-golden-land-north-ritual-road", "current_condition": "主炮信标已自锁并持续运作", "controlling_faction": "Alterego言峰士郎与阿尔托莉雅防守", "accessibility": "受十七尊新法相威胁", "known_hazards": ["十七尊法相", "弥勒佛光"], "recent_events": ["藤丸立香组完成信标安置", "Alterego组接管防守"]},
            {"location_id": "tsukuyomi-golden-land", "current_condition": "居民继续由伊耶娜美维持生命联系", "controlling_faction": "伊耶娜美", "accessibility": "受限", "known_hazards": ["四千九百二十六名居民与伊耶娜美生命相连"], "recent_events": ["地下组确认伊耶娜美是从冲突记忆中自主活下来的故尊复现个体"]},
            {"location_id": "izanagi-palace", "current_condition": "弥勒仍在宫中，古老刀痕处首次流出金血", "controlling_faction": "弥勒", "accessibility": "终局目标，尚未攻破", "known_hazards": ["弥勒佛掌", "未降格的救世主体制"], "recent_events": ["创造白火沿古老刀痕持续洗除佛印"]},
        ],
        "factions": [
            {"faction_id": "chaldea", "current_goal": "治疗伤员，并完成弥勒降格、主炮十二秒窗口与创造之禊祓衔接", "leadership": "藤丸立香", "alliances": ["伊耶娜美", "终末人理圆满装置（阶段性）", "Alterego言峰士郎与阿尔托莉雅（阶段性）"], "enemies": ["弥勒", "法相"], "known_information": ["天照命已败北", "主炮信标已自锁", "创造之禊祓已取得", "主炮尚未发射"], "resources": ["主炮一发", "降格术", "剩余两道令咒", "创造之禊祓", "潘多拉宝具（未开启）"], "recent_changes": ["天照命从主要敌人中移除", "杨浞与吉尔伽美什重伤"]},
        ],
        "global_events": ["黑色穹顶破碎", "天照命的太阳权能分散为普通日光", "乌从欲连接断开", "六十六个法相光影与伤害回路分离", "伊耶那岐金地决战进入对弥勒阶段"],
        "public_knowledge": [],
        "hidden_world_changes": ["神琦灰的目标不止于保住当前人理", "终末人理圆满装置仍隐瞒最终目的"],
        "unresolved_world_flags": ["弥勒的正式降格与主炮十二秒窗口", "杨浞与吉尔伽美什能否及时恢复", "天照命是否会协助迦勒底", "六十六个孩子的安置", "创造之禊祓具体代价", "潘多拉宝具开启时机", "神琦灰的真实目标", "伊耶娜美与居民生命联系能否解除"],
    },
}


def write_json_yaml(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    current_dir = RAG / "character-state" / "current"
    for filename, state in STATES.items():
        write_json_yaml(current_dir / f"{filename}.yaml", state)
    write_json_yaml(RAG / "world-state" / "current" / "current.yaml", WORLD_STATE)
    print(f"character_states={len(STATES)} world_state={WORLD_STATE['metadata']['document_id']}")


if __name__ == "__main__":
    main()
