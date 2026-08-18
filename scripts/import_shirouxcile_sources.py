from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]
LIBRARY = ROOT / "novel-rag"
STORY_ID = "shirouxcile"
STORY = LIBRARY / "stories" / STORY_ID
SOURCE_ROOT = Path(r"D:\士学姐")
TODAY = date(2026, 8, 9).isoformat()


class LiteralDumper(yaml.SafeDumper):
    pass


def _represent_string(dumper: yaml.SafeDumper, value: str) -> yaml.ScalarNode:
    style = "|" if "\n" in value else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", value, style=style)


LiteralDumper.add_representer(str, _represent_string)


def read_source(name: str) -> str:
    return (SOURCE_ROOT / name).read_text(encoding="utf-8").strip()


def write_yaml(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.dump(
            value,
            Dumper=LiteralDumper,
            allow_unicode=True,
            sort_keys=False,
            width=120,
        ),
        encoding="utf-8",
        newline="\n",
    )


def metadata(
    document_id: str,
    title: str,
    *,
    source_file: str,
    character_ids: list[str] | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "document_id": document_id,
        "story_id": STORY_ID,
        "timeline_id": "main",
        "document_type": "canon",
        "title": title,
        "version": "1.0",
        "status": "canon",
        "canon_scope": "timeline",
        "created_at": TODAY,
        "updated_at": TODAY,
        "supersedes": None,
        "source_file": source_file,
    }
    if character_ids is not None:
        result["character_ids"] = character_ids
    return result


def main() -> None:
    if not STORY.exists():
        raise FileNotFoundError(f"小说目录不存在: {STORY}")

    world_source = read_source("世界观.txt")
    people_source = read_source("人设.txt")
    background_source = read_source("背景故事.txt")

    shirou_marker = "# 卫宫士郎｜Emiya Shirou"
    if people_source.count(shirou_marker) != 1:
        raise ValueError("人设.txt 中未找到唯一的卫宫士郎分隔标题")
    ciel_source, shirou_tail = people_source.split(shirou_marker, 1)
    ciel_source = ciel_source.strip()
    shirou_source = f"{shirou_marker}{shirou_tail}".strip()

    world = {
        "metadata": metadata(
            "canon-world-core-premise-v1.0",
            "世界观：月姬世界线基准",
            source_file=str(SOURCE_ROOT / "世界观.txt"),
        ),
        "world": {
            "baseline": "型月体系下的月姬世界观。",
            "rules": [
                "本作品采用月姬世界观作为基准。",
                "本世界不存在英灵。",
                "死徒活动频繁，死徒与相关怪异事件构成主要超自然威胁。",
            ],
            "prohibited_interpretations": [
                "不得引入英灵、从者或英灵座作为本世界既有事实。",
                "不得默认发生第四次或第五次圣杯战争。",
                "不得把本作与其他小说的型月时间线混用。",
            ],
            "source_content": world_source,
        },
    }

    ciel = {
        "metadata": {
            **metadata(
                "canon-character-ciel-v1.0",
                "角色设定：希耶尔",
                source_file=str(SOURCE_ROOT / "人设.txt"),
                character_ids=["ciel"],
            ),
            "entity": "character",
        },
        "character": {
            "name": "希耶尔",
            "aliases": ["Ciel", "艾蕾西亚", "学姐"],
            "identity": "圣堂教会埋葬机关第七位／代行者／吸血鬼猎人／总耶学园高年级学生",
            "age": None,
            "appearance": ["蓝发蓝瞳", "外貌清秀端正", "日常温和亲切，战斗时气质果断凌厉"],
            "personality_core": ["温柔", "克制", "责任感极重", "自罚倾向", "专业", "坚韧", "行动派"],
            "surface_behavior": [
                "学校中表现为可靠温柔的学姐，礼貌并善于照顾他人",
                "执行任务时判断快速，能够切断私人情感并采取致命手段",
                "会开玩笑，也能享受普通女孩的日常",
            ],
            "values": ["保护无辜者", "完成职责", "不能忘记故乡惨剧与罗亚造成的死亡", "逐渐学习允许自己活下去"],
            "goals": [
                "执行处决复仇骑安翰斯并回收圣葬炮典的任务",
                "寻找罗亚消失以后属于自己的生活方向",
                "学会承认过去而不放弃未来",
            ],
            "fears": ["自己没有资格获得幸福", "别人为了她而牺牲", "无法偿还与罗亚相关的过去"],
            "boundaries": [
                "面对不可挽救且持续危害人类的目标可以下杀手",
                "默认将他人生命与任务置于自身安全之前",
                "罗亚彻底消失后已失去过去的不死性，死亡只会发生一次",
            ],
            "speech_patterns": ["日常温和礼貌", "工作时简洁专业", "谈及咖喱时会明显认真并更有热情"],
            "abilities": [
                "远超普通人的强化肉体、高速移动与近身战斗能力",
                "异常巨大的魔力量与罗亚积累的高级魔术知识",
                "黑键投射与空间控制，拥有“弓”的称号",
                "转生批判外典·第七圣典",
                "原理血戒与祖之原理大魔术",
                "超远距离超大规模攻击术式Calvaria之星",
                "针对死徒、不死与转生体系的专业猎杀能力",
            ],
            "limitations": [
                "罗亚消灭后不再拥有世界修正式不死性",
                "第七圣典和大型术式魔力消耗巨大",
                "基础规格并不稳定高于顶级二十七祖或真祖公主",
                "习惯把自身受伤与死亡视为任务成本",
            ],
            "relationships": [
                "罗亚：曾夺取其身体并造成故乡惨剧，现已被彻底消灭",
                "纳鲁巴列克：埋葬机关负责人，批准其恢复行动并下达安翰斯任务",
                "安翰斯：当前处决目标，曾夺走并改造圣葬炮典",
                "卫宫士郎：尚未正式相遇，但两人都习惯把自己当作完成目标的工具",
                "爱尔奎特与远野志贵：总耶事件相关人物，公主故事结束后希耶尔失去不死性",
            ],
            "prohibited_interpretations": [
                "不得写成阴沉寡言、只会自罚或完全不懂幸福的人",
                "不得忽略她作为顶级代行者的专业判断与行动力",
                "不得在罗亚消失后继续赋予她过去的不死性",
                "不得把咖喱偏好只写成脱离人物经历的搞笑梗",
                "不得让她轻易接受别人为自己牺牲",
            ],
            "source_profile": ciel_source,
        },
    }

    shirou = {
        "metadata": {
            **metadata(
                "canon-character-emiya-shirou-v1.0",
                "角色设定：卫宫士郎",
                source_file=str(SOURCE_ROOT / "人设.txt"),
                character_ids=["emiya-shirou"],
            ),
            "entity": "character",
        },
        "character": {
            "name": "卫宫士郎",
            "aliases": ["Emiya Shirou", "士郎"],
            "identity": "27岁魔术师／自由行动者／怪异与死徒事件处理者",
            "age": 27,
            "appearance": ["男性", "身高187厘米", "体重78公斤"],
            "personality_core": ["温和", "固执", "现实主义", "善良", "自我牺牲", "生活能力强", "面对熟人会毒舌"],
            "surface_behavior": [
                "平时说话简单直接，不主动讲大道理",
                "一边嫌弃熟人，一边把饭菜、伤口和修理工作全部处理好",
                "面对危险会先制定计划、撤退路线与损失控制方案",
            ],
            "values": [
                "能够救下的人不能因为害怕失败而放弃",
                "杀死目标不能成为为了方便而选择的最简单方案",
                "无辜者的生命通常高于任务与自身安全",
                "正义的伙伴是一条持续前进而非已经完成的道路",
            ],
            "goals": ["继续成为正义的伙伴", "处理死徒与怪异事件并救下现实可救之人"],
            "fears": ["因自己的放弃造成可避免的死亡", "无法保护被敌人用作筹码的普通人"],
            "boundaries": [
                "确认目标完全不可逆且会继续制造牺牲时可以下杀手",
                "会撤退并避免无价值的自杀",
                "若牺牲自己能明显换取他人生存，仍会把自己放上天平",
            ],
            "speech_patterns": [
                "简洁直接，很少把正义挂在嘴边",
                "面对熟人吐槽明显增加",
                "真正生气时语气会迅速冷下来而非大喊",
                "面对感谢常回答“没什么，正好能做而已”",
            ],
            "abilities": [
                "起源与魔术属性均为剑",
                "同调与极限同调，可解析结构、材质、武装概念与使用轨迹",
                "以完整理解为基础的高完成度剑类投影",
                "从投影武器中读取并模拟部分武技轨迹",
                "固有结界Unlimited Blade Works／无限剑制",
                "肉体、武器与工具强化",
                "针对目标弱点选择武装的近中远距离战术",
                "十余年魔术事件、怪异处理、死徒猎杀与人质救援经验",
                "做饭、清扫、缝补、维修与伤口处理等生活能力",
            ],
            "limitations": [
                "魔力量并非怪物级，无限剑制与高级投影负担巨大",
                "仍是人类，严重伤势无法依靠夸张再生恢复",
                "神造兵装、高等级概念武装与非剑类复杂神秘难以完美投影",
                "纯剑术未必胜过正统大剑豪",
                "无法稳定正面战胜祖级存在，依赖情报、准备、克制与战场条件",
                "保护普通人的倾向可以被敌人利用",
            ],
            "relationships": [
                "卫宫切嗣：养父与理想来源，未参加第四次圣杯战争，以追杀卫宫矩贤为人生目标",
                "卫宫矩贤：切嗣之父，研究时间后成为祖级死徒，是1994年冬木灾害源头",
                "安翰斯：为追踪共同高阶死徒目标而形成勉强的暂时合作",
                "希耶尔：尚未正式相遇；两人会互相识别对方的自我工具化倾向",
            ],
            "prohibited_interpretations": [
                "不得写成会原谅一切的圣父",
                "不得写成缺乏战术判断的热血笨蛋",
                "不得写成以杀戮为优先的冷酷处刑人",
                "不得套用红A式虚无主义或让他否定正义伙伴理想",
                "不得写成已经抵达理想终点的人",
                "不得抹去他的日常感情、毒舌、做饭能力和私人偏心",
                "不得让他拥有圣杯战争、Saber或Archer相关个人经历",
            ],
            "source_profile": shirou_source,
        },
    }

    background = {
        "metadata": metadata(
            "canon-history-background-v1.0",
            "背景历史：火灾、罗亚终结与复仇骑任务",
            source_file=str(SOURCE_ROOT / "背景故事.txt"),
            character_ids=["emiya-shirou", "ciel", "emiya-kiritsugu", "emiya-norikata", "enhance"],
        ),
        "background": {
            "chronology": [
                "卫宫矩贤研究时间、不死与生命，最终成为祖级死徒。",
                "卫宫切嗣没有参加第四次圣杯战争，而是长期追杀父亲卫宫矩贤。",
                "1994年冬木发生由矩贤术式与死徒化研究崩坏引发的城市灾害；切嗣阻止扩大并从废墟救出、收养卫宫士郎。",
                "本世界没有第五次圣杯战争，士郎未遇见Saber或Archer，而是独自将同调发展为投影与无限剑制。",
                "总耶市的远野志贵、爱尔奎特、弗洛夫与罗亚事件结束，罗亚被彻底消灭，爱尔奎特离开总耶。",
                "罗亚消灭后，希耶尔失去世界修正式不死性，并在尝试普通生活后申请恢复埋葬机关行动。",
                "纳鲁巴列克要求希耶尔处决二十七祖第十八位复仇骑安翰斯并回收被夺走、改造的圣葬炮典。",
                "安翰斯正在追踪一名制造大规模失踪事件的高阶死徒，并因情报与战力互补同卫宫士郎暂时合作。",
                "希耶尔正在接近安翰斯与士郎；这场追捕将迫使希耶尔和士郎思考没有任务替自己规定方向时的个人未来。",
            ],
            "current_story_setup": {
                "ciel": "恢复埋葬机关行动，任务是处决安翰斯并回收圣葬炮典。",
                "emiya_shirou": "27岁，在欧洲处理死徒事件，当前与安翰斯暂时同行追踪高阶死徒。",
                "enhance": "二十七祖第十八位复仇骑，曾夺走并非法改造圣葬炮典，正猎杀另一名高阶死徒。",
                "central_relationship_premise": "两个习惯把人生交给目标、把身体视为工具的人，将逐渐考虑自己想与谁同行、走向哪里。",
            },
            "source_content": background_source,
        },
    }

    write_yaml(STORY / "canon" / "world" / "core-premise.yaml", world)
    write_yaml(STORY / "canon" / "characters" / "ciel.yaml", ciel)
    write_yaml(STORY / "canon" / "characters" / "emiya-shirou.yaml", shirou)
    write_yaml(STORY / "canon" / "history" / "background.yaml", background)

    write_yaml(
        STORY / "registry" / "character-variants.yaml",
        {
            "character_variants": [
                {
                    "story_id": STORY_ID,
                    "timeline_id": "main",
                    "character_name": "希耶尔",
                    "character_id": "ciel",
                    "variant_id": "ciel-main",
                },
                {
                    "story_id": STORY_ID,
                    "timeline_id": "main",
                    "character_name": "卫宫士郎",
                    "character_id": "emiya-shirou",
                    "variant_id": "emiya-shirou-main",
                },
            ]
        },
    )
    write_yaml(
        STORY / "registry" / "aliases.yaml",
        {
            "aliases": [
                {
                    "canonical_id": "ciel",
                    "timeline_id": "main",
                    "names": ["希耶尔", "Ciel", "艾蕾西亚", "学姐"],
                },
                {
                    "canonical_id": "emiya-shirou",
                    "timeline_id": "main",
                    "names": ["卫宫士郎", "Emiya Shirou", "士郎"],
                },
                {
                    "canonical_id": "enhance",
                    "timeline_id": "main",
                    "names": ["安翰斯", "复仇骑"],
                },
            ]
        },
    )
    write_yaml(
        STORY / "registry" / "version-map.yaml",
        {
            "versions": [
                {
                    "document_family": "canon-world-core-premise",
                    "current": "canon-world-core-premise-v1.0",
                    "supersedes": [],
                    "reason": "导入用户确认的月姬世界线基准。",
                },
                {
                    "document_family": "canon-character-ciel",
                    "current": "canon-character-ciel-v1.0",
                    "supersedes": [],
                    "reason": "导入用户确认的希耶尔完整人物设定。",
                },
                {
                    "document_family": "canon-character-emiya-shirou",
                    "current": "canon-character-emiya-shirou-v1.0",
                    "supersedes": [],
                    "reason": "导入用户确认的月姬世界线卫宫士郎完整人物设定。",
                },
                {
                    "document_family": "canon-history-background",
                    "current": "canon-history-background-v1.0",
                    "supersedes": [],
                    "reason": "导入用户确认的1994年冬木灾害至安翰斯追捕任务背景。",
                },
            ]
        },
    )
    write_yaml(
        STORY / "retrieval-tests.yaml",
        {
            "tests": [
                {
                    "id": "shirouxcile-world-no-servants",
                    "story_id": STORY_ID,
                    "timeline_id": "main",
                    "query": "无英灵存在",
                    "document_types": ["canon"],
                    "expected_document_ids": ["canon-world-core-premise-v1.0"],
                    "forbidden_statuses": ["draft", "deprecated", "archived"],
                    "checks": ["correctness", "timeline_isolation", "content_type"],
                },
                {
                    "id": "shirouxcile-ciel-calvaria",
                    "story_id": STORY_ID,
                    "timeline_id": "main",
                    "query": "Calvaria之星",
                    "document_types": ["canon"],
                    "expected_document_ids": ["canon-character-ciel-v1.0"],
                    "forbidden_statuses": ["draft", "deprecated", "archived"],
                    "checks": ["correctness", "timeline_isolation", "version", "content_type"],
                },
                {
                    "id": "shirouxcile-shirou-limit-synchronization",
                    "story_id": STORY_ID,
                    "timeline_id": "main",
                    "query": "极限同调",
                    "document_types": ["canon"],
                    "expected_document_ids": ["canon-character-emiya-shirou-v1.0"],
                    "forbidden_statuses": ["draft", "deprecated", "archived"],
                    "checks": ["correctness", "timeline_isolation", "version", "content_type"],
                },
                {
                    "id": "shirouxcile-background-burial-cannon",
                    "story_id": STORY_ID,
                    "timeline_id": "main",
                    "query": "圣葬炮典",
                    "document_types": ["canon"],
                    "expected_document_ids": ["canon-history-background-v1.0"],
                    "forbidden_statuses": ["draft", "deprecated", "archived"],
                    "checks": ["correctness", "timeline_isolation", "version", "content_type"],
                },
            ]
        },
    )

    print(f"imported story={STORY_ID} canon_documents=4 retrieval_tests=4")


if __name__ == "__main__":
    main()
