from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]
LIBRARY = ROOT / "novel-rag"
SOURCE = Path("D:/word2/第一卷 特异点F/人设.txt")
STORY_ID = "overturned-world-fujimaru"
TIMELINE_ID = "main"
TODAY = date(2026, 7, 13).isoformat()


def dump(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=120),
        encoding="utf-8",
    )


def slice_between(text: str, start: str, end: str | None) -> str:
    start_at = text.index(start)
    end_at = text.index(end, start_at + len(start)) if end else len(text)
    return text[start_at:end_at].strip()


def character_document(
    *,
    character_id: str,
    name: str,
    aliases: list[str],
    identity: str,
    age: str | None,
    appearance: list[str],
    personality_core: list[str],
    values: list[str],
    goals: list[str],
    abilities: list[str],
    limitations: list[str],
    relationships: list[str],
    prohibited_interpretations: list[str],
    source_profile: str,
    entity: str = "character",
) -> dict[str, Any]:
    return {
        "metadata": {
            "document_id": f"canon-character-{character_id}-v1.0",
            "story_id": STORY_ID,
            "timeline_id": TIMELINE_ID,
            "document_type": "canon",
            "title": f"角色设定-{name}",
            "entity": entity,
            "character_ids": [character_id],
            "version": "1.0",
            "status": "canon",
            "canon_scope": "timeline",
            "created_at": TODAY,
            "updated_at": TODAY,
            "supersedes": None,
            "source_file": str(SOURCE),
        },
        "character": {
            "name": name,
            "aliases": aliases,
            "identity": identity,
            "age": age,
            "appearance": appearance,
            "personality_core": personality_core,
            "surface_behavior": [],
            "values": values,
            "goals": goals,
            "fears": [],
            "boundaries": [],
            "speech_patterns": [],
            "abilities": abilities,
            "limitations": limitations,
            "relationships": relationships,
            "prohibited_interpretations": prohibited_interpretations,
            "source_profile": source_profile,
        },
    }


def main() -> None:
    text = SOURCE.read_text(encoding="utf-8-sig")
    kanzaki = slice_between(text, "================= MAGUS PROFILE =================", "# Caster·天照命")
    amaterasu = slice_between(text, "# Caster·天照命", "# 弥勒")
    old_maitreya = slice_between(text, "# 弥勒", "# 日本篇终局战斗体系·重塑版")
    finale = slice_between(text, "# 日本篇终局战斗体系·重塑版", "# 伊耶娜美")
    maitreya = slice_between(finale, "# 弥勒", None)
    izanami = slice_between(text, "# 伊耶娜美", "# 救世之兽·伊耶娜美")
    beast_izanami = slice_between(text, "# 救世之兽·伊耶娜美", None)

    destination = LIBRARY / "canon" / "characters"
    documents = {
        "shenqi-hui.yaml": character_document(
            character_id="shenqi-hui",
            name="神琦灰",
            aliases=["神琦灰", "故尊复现·神琦灰"],
            identity="魔术师 / 根源主人神琦灰的故尊复现",
            age="5",
            appearance=["金发碧眼，可爱又精致的面庞", "体型匀称"],
            personality_core=["自信", "偏执", "为了目的不择手段", "被根源认定为极度自信且无法无天"],
            values=["证明自身优于愿主神琦灰"],
            goals=["彻底成为根源", "超越愿主神琦灰"],
            abilities=["万能魔术", "剑术精通", "根源魔术"],
            limitations=["根源魔术距离极致仍差一步", "需要盖提亚维持特异点，因此暂不杀死迦勒底一行"],
            relationships=["愿主神琦灰", "迦勒底", "盖提亚"],
            prohibited_interpretations=["不得将她写成愿主神琦灰本人", "不得忽略其自信、偏执与目的优先"],
            source_profile=kanzaki,
        ),
        "amaterasu-no-mikoto.yaml": character_document(
            character_id="amaterasu-no-mikoto",
            name="天照命",
            aliases=["天照命", "伊耶那岐金地世尊", "窃命世尊", "至命至性并火大圣", "无名孔雀"],
            identity="Caster / 伊耶那岐金地世尊 / 承受天照之命的无名孔雀",
            age=None,
            appearance=["黑发黑眸，面庞精美端正，妆容以朱、金、乌三色描绘", "平时身披乌金法衣，战斗时展开火焰孔雀翼"],
            personality_core=["果断", "贤明", "悲悯", "认为自己有资格替所有人决定未来"],
            values=["保护人类", "不允许人类在弥勒支配下失去未来"],
            goals=["让法相成熟后回收其命，抵达至命至性并火大圣", "杀死弥勒，为人类强行打开未来"],
            abilities=["阵地作成EX", "道具作成EX", "天照御名A++", "佛果·伊耶那岐金地世尊A+", "乌从欲EX", "孔雀卵生EX", "食恶开明A++", "卵藏诸世EX", "诸生未至之明日EX", "天无二日EX", "至命除EX"],
            limitations=["天照之名并非本生真名，会被审判真实与剥离神性的能力削弱", "佛果来自弥勒，存在授予关系", "回收法相会永久失去亲手孕育的生命", "时间之卵不能创造从未存在的未来且展开次数有限"],
            relationships=["弥勒", "法相子嗣", "伊耶那岐金地众生"],
            prohibited_interpretations=["不得写成原本的天照大神", "不得把慈悲写成虚伪表演", "不得忽略法相是她的孩子而非普通消耗品"],
            source_profile=amaterasu,
        ),
        "maitreya.yaml": character_document(
            character_id="maitreya",
            name="弥勒",
            aliases=["弥勒", "第一代救世主", "Saver弥勒"],
            identity="Saver / 第一代救世主 / 人类思潮生命",
            age=None,
            appearance=[],
            personality_core=["确实爱人类", "无法接受人类在迈向星空时牺牲", "以保护为理由阻止人类离开地球"],
            values=["人类存续", "地上圆满", "阻止人类承担星际开拓风险"],
            goals=["把人类留在地上净土", "阻止文明迈向星空"],
            abilities=["极乐佛身EX", "千代武藏EX", "极乐大源EX", "文明兵装A至EX", "大慈大悲掌", "金刚撞", "千手并击", "极乐金轮", "文明光雨", "无远佛步", "极乐大佛·人间无远EX", "众生止步·极乐一掌EX"],
            limitations=["降格后高维、遍在与思潮复活等不可交战性质失效", "降格不会削弱其肉体、魔力、武技、兵装与恢复力", "文明兵装会被破坏并耗尽", "巨大化会降低速度"],
            relationships=["人类", "天照命", "迦勒底"],
            prohibited_interpretations=["不得写成单纯憎恨人类的恶人", "不得写成自动无效化一切人类成果", "降格不等于削弱或自动胜利"],
            source_profile=maitreya,
            entity="savior",
        ),
        "izanami.yaml": character_document(
            character_id="izanami",
            name="伊耶娜美",
            aliases=["伊耶娜美", "月读命金地之主", "第二代救世主"],
            identity="Saver / Lancer / 第二代救世主 / 创世大神与黄泉津大神的故尊复现",
            age=None,
            appearance=[],
            personality_core=["承担救世职责", "擅长直接冲入敌阵", "知道自身出手代价后选择留守保护居民"],
            values=["对抗弥勒", "保护月读命金地居民"],
            goals=["支撑后方结界与接收伤员", "在不牺牲居民的前提下协助终局决战"],
            abilities=["创世神躯EX", "黄泉黑月EX", "八雷神EX", "五法运用A++", "天沼枪术·开国", "天沼枪术·神生", "黄泉落", "八雷穿", "黑月坠", "天沼矛·大八洲国生EX", "黄泉津大神·黑月八雷葬EX"],
            limitations=["不是神话原主的完整复活，部分痛苦与仇恨记忆被删除", "离开月读命金地会消耗居民生命", "神躯恢复有速度上限", "五法运用消耗巨大且不能无限连续使用"],
            relationships=["千子村正", "月读命金地居民", "天沼", "弥勒"],
            prohibited_interpretations=["不得写成原本神话人物的完整复活", "不得因其留守就误写为战力不足", "不得忽略她离开金地会消耗居民生命"],
            source_profile=izanami,
            entity="savior",
        ),
        "izanami-savior-beast.yaml": character_document(
            character_id="izanami-savior-beast",
            name="救世之兽·伊耶娜美",
            aliases=["救世之兽·伊耶娜美", "救世之兽", "Beast伊耶娜美"],
            identity="Beast / 伊耶娜美舍弃大部分救世主结构后的压缩形态",
            age=None,
            appearance=["黑色长发，额角短角，黑白战装与黄泉白骨轻甲", "背后悬浮八条雷霆兽尾，黑月缩为头后暗色光环"],
            personality_core=["即使世界放弃救世仍继续战斗", "动作更快、更直接、更少犹豫"],
            values=["保护仍想活下去的人", "不再替别人决定谁应牺牲"],
            goals=["跟随藤丸立香参加最终近身战", "保护友军"],
            abilities=["救世本能EX", "黄泉兽血A++", "八雷兽尾EX", "黄泉救援A++", "兽步·黄泉闪", "八雷裂", "黑月咬", "黄泉返身", "救世之兽·八雷黄泉奔A++", "已被世界舍弃，仍要伸出的手A+"],
            limitations=["综合实力低于完整伊耶娜美", "失去大规模创世、世界修正、世尊佛果、金地统治和五法综合运用", "黄泉救援收容过多会失去行动能力", "转移过量致命伤会死亡"],
            relationships=["藤丸立香", "迦勒底友军"],
            prohibited_interpretations=["不得写成完整伊耶娜美的单纯强化形态", "不得将伤害转移写成无代价复活", "该形态可以被真正击伤和杀死"],
            source_profile=beast_izanami,
            entity="beast_form",
        ),
    }

    for filename, document in documents.items():
        dump(destination / filename, document)

    documents["maitreya.yaml"]["metadata"]["supersedes"] = "canon-character-maitreya-v0.9"
    dump(destination / "maitreya.yaml", documents["maitreya.yaml"])
    dump(
        destination / "deprecated" / "maitreya-v0.9.yaml",
        {
            "metadata": {
                "document_id": "canon-character-maitreya-v0.9",
                "story_id": STORY_ID,
                "timeline_id": TIMELINE_ID,
                "document_type": "canon",
                "title": "角色设定-弥勒-重塑前版本",
                "entity": "savior",
                "character_ids": ["maitreya"],
                "version": "0.9",
                "status": "deprecated",
                "canon_scope": "timeline",
                "created_at": TODAY,
                "updated_at": TODAY,
                "supersedes": None,
                "source_file": str(SOURCE),
            },
            "archive": {
                "reason": "同一来源文件后部存在明确标记的日本篇终局战斗体系重塑版；默认检索应使用v1.0重塑版。",
                "source_profile": old_maitreya,
            },
        },
    )

    finale_rules = slice_between(finale, "# 日本篇终局战斗体系·重塑版", "# 弥勒")
    final_strength = slice_between(text, "# 【最终强度关系】", None)
    dump(
        LIBRARY / "canon" / "world" / "japan-finale-combat-system.yaml",
        {
            "metadata": {
                "document_id": "canon-world-japan-finale-combat-system-v1.0",
                "story_id": STORY_ID,
                "timeline_id": TIMELINE_ID,
                "document_type": "canon",
                "title": "日本篇终局战斗体系与强度关系",
                "entity": "world_rule",
                "character_ids": ["fujimaru-ritsuka", "maitreya", "izanami", "izanami-savior-beast", "yang-zhuo", "gilgamesh"],
                "location_ids": ["izanagi-golden-land"],
                "event_tags": ["日本篇", "终局战", "降格术", "弥勒"],
                "version": "1.0",
                "status": "canon",
                "canon_scope": "timeline",
                "created_at": TODAY,
                "updated_at": TODAY,
                "supersedes": None,
                "source_file": str(SOURCE),
            },
            "world": {
                "scope": "日本篇终局战斗专项应用规则",
                "rules": finale_rules,
                "final_strength_relationship": final_strength,
                "priority_note": "藤丸立香的降格术通用定义以独立能力文档为准；本文件只说明日本篇终局中的具体战斗应用。",
            },
        },
    )
    print(f"characters={len(documents)} deprecated=1 world_rules=1 source={SOURCE}")


if __name__ == "__main__":
    main()
