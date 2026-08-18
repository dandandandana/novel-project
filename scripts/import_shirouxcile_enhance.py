from __future__ import annotations

import sys
from datetime import date
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from novel_rag.documents import load_document, validate_document


STORY = ROOT / "novel-rag" / "stories" / "shirouxcile"
SOURCE = Path(r"D:\士学姐\人设.txt")
DOCUMENT = STORY / "canon" / "characters" / "enhance.yaml"
TODAY = date(2026, 8, 9).isoformat()


class LiteralDumper(yaml.SafeDumper):
    pass


def _represent_string(dumper: yaml.SafeDumper, value: str) -> yaml.ScalarNode:
    return dumper.represent_scalar(
        "tag:yaml.org,2002:str",
        value,
        style="|" if "\n" in value else None,
    )


LiteralDumper.add_representer(str, _represent_string)


def load_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(value, dict):
        raise ValueError(f"YAML 根节点必须为映射: {path}")
    return value


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


def upsert(rows: list[dict[str, Any]], key: str, value: str, item: dict[str, Any]) -> None:
    for index, row in enumerate(rows):
        if str(row.get(key)) == value:
            rows[index] = item
            return
    rows.append(item)


def main() -> None:
    if not STORY.exists():
        raise FileNotFoundError(f"目标小说目录不存在: {STORY}")
    source_profile = SOURCE.read_text(encoding="utf-8").strip()
    if not source_profile.startswith("# 安翰斯｜Enhance"):
        raise ValueError("人设.txt 不是预期的安翰斯角色卡")

    document: dict[str, Any] = {
        "metadata": {
            "document_id": "canon-character-enhance-v1.0",
            "story_id": "shirouxcile",
            "timeline_id": "main",
            "document_type": "canon",
            "title": "角色设定：安翰斯",
            "entity": "character",
            "character_ids": ["enhance"],
            "version": "1.0",
            "status": "canon",
            "canon_scope": "timeline",
            "created_at": TODAY,
            "updated_at": TODAY,
            "supersedes": None,
            "source_file": str(SOURCE),
        },
        "character": {
            "name": "安翰斯",
            "aliases": ["Enhance", "复仇骑", "Enhance Sword", "片刃"],
            "identity": "死徒二十七祖第十八位／反死徒猎手／独立行动者",
            "age": None,
            "appearance": [],
            "personality_core": ["复仇偏执", "冷淡", "嘴欠恶劣", "实用主义", "独狼", "自我损耗"],
            "surface_behavior": [
                "对陌生人缺乏交流欲望，也懒得纠正误解",
                "熟悉后会在危险环境里说让人火大的话",
                "不讲公平决斗，偷袭、陷阱、枪械、毒、爆炸物和圣具都可使用",
                "顺手能救普通人时通常不会刻意让其死亡，但拒绝承认自己在救人",
            ],
            "values": [
                "杀死二十七祖与其他复仇对象",
                "结果和实用性高于公平与他人评价",
                "维持继续复仇的行动能力",
                "不主动捕食普通人",
            ],
            "goals": [
                "逐一猎杀二十七祖",
                "追踪并杀死当前制造多起大规模失踪事件的高阶死徒",
            ],
            "fears": [],
            "boundaries": [
                "不主动捕食普通人，以其他死徒、使魔、人工生命资源或储存血液维持自身",
                "极度饥饿时仍可能袭击人类，因此不自认属于人类阵营",
                "救人若妨碍杀死主要目标，会主张舍弃救援",
                "教会与死徒社会都将其视为敌人",
            ],
            "speech_patterns": [
                "话少但并非冰山式沉默",
                "说话直接、刻薄，常用实用主义结论激怒同行者",
                "几乎不解释猎祖动机，常以“因为他们应该死”终止追问",
                "不会轻易承认卫宫士郎是伙伴",
            ],
            "abilities": [
                "一流从者级综合战斗力，祖中基础规格偏弱但实际猎杀能力高于面板",
                "A-级附近筋力、一流从者级近战速度与短距离爆发",
                "死徒高速再生、身体强化、血液魔术、简单使魔、夜间感知与魔力吸收",
                "魔剑Avenger可吞噬魔力、侵蚀高神秘生命并妨碍死徒再生",
                "改造后的圣葬炮典可发射高穿透、高神秘、吸血种特攻且抑制再生的圣化魔弹",
                "右手Avenger、左手圣葬炮典的双武装战法",
                "简洁、暴力、以致命和扩大不可再生伤口为核心的近战",
                "擅长情报、逃生路线、陷阱、圣具、魔术炸药与地形准备，能够猎杀强于自身的目标",
                "最高战力“复仇骑”可完全解放双武装并以生命换取接近一流顶端从者的短时爆发",
                "掌握祖、死徒社会、血族关系、领地、行为习惯与弱点等专业情报",
            ],
            "limitations": [
                "单论死徒规格仅处于二十七祖下位至中下位，无法以技术稳定填平顶级祖的规格差",
                "不是不死存在，心脏、脑部或重要灵核部位被高神秘攻击摧毁仍会死亡",
                "教会圣骸和概念武装会显著压制其再生",
                "Avenger并不真正认可他，长时间使用会破坏右臂神经与魔术结构，极端时右臂失能",
                "他身为死徒，每次使用圣葬炮典都会遭圣性反噬，连续射击会使左臂炭化、坏死乃至骨骼侵蚀",
                "“复仇骑”持续时间极短，结束后必然重伤并可能直接死亡",
                "没有大型血族、领地、势力与庞大资源，几乎始终独自行动",
                "卫宫士郎明显强于他，无限剑制展开时通常必须撤退",
                "希耶尔对其拥有规格、装备与情报优势，认真处决时他的现实目标是逃生而非取胜",
            ],
            "relationships": [
                "前任第十八祖：安翰斯的上代，被其杀死并夺走祖位、力量与魔剑Avenger",
                "卫宫士郎：因追踪共同高危死徒而暂时同行；信任其战斗判断并可交付后背，但不承认是伙伴",
                "希耶尔：明确敌对的处决者；安翰斯曾趁其重伤夺走并非法改造圣葬炮典",
                "圣堂教会：敌对，因其祖身份与盗取教会武装而追杀",
                "死徒社会：敌对，视其为专门猎杀同类的叛徒",
            ],
            "prohibited_interpretations": [
                "不得写成以保护人类为目标的冷酷救世主",
                "不得写成拥有顶级祖规格、庞大血族或世界级原理的强者",
                "不得写成希耶尔的旧友，两人是明确敌对关系",
                "不得写成卫宫士郎的忠诚伙伴；两人应长期保持战斗互信与互相嫌弃",
                "不得让安翰斯在正常正面对决中稳定胜过卫宫士郎或希耶尔",
                "不得忽略双武装同时损毁其左右手与身体的核心代价",
                "不得把不主动捕食普通人等同于已经回归人类阵营",
            ],
            "source_profile": source_profile,
        },
    }
    write_yaml(DOCUMENT, document)

    errors = validate_document(load_document(DOCUMENT))
    if errors:
        raise ValueError("安翰斯人物文档校验失败: " + "; ".join(errors))

    variants_path = STORY / "registry" / "character-variants.yaml"
    variants_data = load_yaml(variants_path)
    variants = variants_data.setdefault("character_variants", [])
    upsert(
        variants,
        "variant_id",
        "enhance-main",
        {
            "story_id": "shirouxcile",
            "timeline_id": "main",
            "character_name": "安翰斯",
            "character_id": "enhance",
            "variant_id": "enhance-main",
        },
    )
    write_yaml(variants_path, variants_data)

    aliases_path = STORY / "registry" / "aliases.yaml"
    aliases_data = load_yaml(aliases_path)
    aliases = aliases_data.setdefault("aliases", [])
    upsert(
        aliases,
        "canonical_id",
        "enhance",
        {
            "canonical_id": "enhance",
            "timeline_id": "main",
            "names": ["安翰斯", "Enhance", "复仇骑", "Enhance Sword", "片刃"],
        },
    )
    write_yaml(aliases_path, aliases_data)

    versions_path = STORY / "registry" / "version-map.yaml"
    versions_data = load_yaml(versions_path)
    versions = versions_data.setdefault("versions", [])
    upsert(
        versions,
        "document_family",
        "canon-character-enhance",
        {
            "document_family": "canon-character-enhance",
            "current": "canon-character-enhance-v1.0",
            "supersedes": [],
            "reason": "导入用户确认的安翰斯完整人物设定。",
        },
    )
    write_yaml(versions_path, versions_data)

    tests_path = STORY / "retrieval-tests.yaml"
    tests_data = load_yaml(tests_path)
    tests = tests_data.setdefault("tests", [])
    for case in (
        {
            "id": "shirouxcile-enhance-avenger",
            "story_id": "shirouxcile",
            "timeline_id": "main",
            "query": "Avenger 再生妨碍",
            "document_types": ["canon"],
            "expected_document_ids": ["canon-character-enhance-v1.0"],
            "forbidden_statuses": ["draft", "deprecated", "archived"],
            "checks": ["correctness", "timeline_isolation", "version", "content_type"],
        },
        {
            "id": "shirouxcile-enhance-double-recoil",
            "story_id": "shirouxcile",
            "timeline_id": "main",
            "query": "两件武器都在同时杀他",
            "document_types": ["canon"],
            "expected_document_ids": ["canon-character-enhance-v1.0"],
            "forbidden_statuses": ["draft", "deprecated", "archived"],
            "checks": ["correctness", "timeline_isolation", "version", "content_type"],
        },
    ):
        upsert(tests, "id", str(case["id"]), case)
    write_yaml(tests_path, tests_data)

    if load_yaml(DOCUMENT)["character"]["source_profile"] != source_profile:
        raise AssertionError("安翰斯原始人设未逐字保留")

    print("imported character=enhance document=canon-character-enhance-v1.0 retrieval_tests=2")


if __name__ == "__main__":
    main()
