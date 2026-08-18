from __future__ import annotations

import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from novel_rag.documents import load_document, validate_document


LIBRARY = ROOT / "novel-rag"
STORY = LIBRARY / "stories" / "shirouxcile"
SOURCE = ROOT / "outputs" / "shirouXcile_第一章_新生回去_强化版.txt"
DATE = "2026-08-09"
HISTORY_TEMPLATE = LIBRARY / "shared" / "templates" / "history-scene.yaml"
CHARACTER_TEMPLATE = LIBRARY / "shared" / "templates" / "character-current.yaml"
WORLD_TEMPLATE = LIBRARY / "shared" / "templates" / "world-current.yaml"


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


def split_chapter() -> list[str]:
    source = SOURCE.read_text(encoding="utf-8").replace("\r\n", "\n").strip()
    title, body = source.split("\n\n", 1)
    if title != "第一章　新生？回去？":
        raise ValueError(f"未识别的章节标题: {title}")
    markers = [
        "解除手续用了大半天。",
        "饭馆重新开业后，希耶尔理所当然地没有掌勺。",
        "第一个月，饭馆收支平衡。",
        "第四个月末，冬雨落了好几天。",
        "卧室衣柜最下面压着她从教会带回来的旧箱。",
        "希耶尔握着手机，在黑下去的屏幕前笑了一会儿。",
    ]
    positions = [body.index(marker) for marker in markers]
    if positions != sorted(positions):
        raise ValueError("第一章场景标记顺序异常")
    boundaries = [0, *positions, len(body)]
    scenes = [body[boundaries[index] : boundaries[index + 1]].strip() for index in range(7)]
    reconstructed = "\n\n".join(scenes)
    if reconstructed != body.strip():
        raise AssertionError("第一章场景切分未能逐字还原正文")
    return scenes


def write_history() -> list[str]:
    template = load_yaml(HISTORY_TEMPLATE)
    scenes = split_chapter()
    titles = [
        "罗亚终结与解除现役",
        "交还武装与法国落脚",
        "咖喱饭馆的普通生活",
        "平静日子里的裂缝",
        "无风之海与归队决定",
        "归队申请与安翰斯任务",
        "留灯离店与新的路线",
    ]
    locations = [
        ["tokyo-temporary-clinic", "burial-agency-office"],
        ["burial-agency-armory", "france-old-town", "curry-restaurant"],
        ["curry-restaurant"],
        ["curry-restaurant", "france-old-town"],
        ["curry-restaurant"],
        ["curry-restaurant-attic", "burial-agency-office"],
        ["curry-restaurant", "eastbound-train-route"],
    ]
    tags = [
        ["罗亚彻底死亡", "不死性消失", "解除现役"],
        ["第七圣典交还", "返回法国", "购入咖喱店"],
        ["咖喱饭馆", "普通生活", "萨米尔"],
        ["失眠", "危险习惯", "日常不适"],
        ["海与星", "人生方向", "申请归队"],
        ["纳鲁巴列克", "安翰斯任务", "圣葬炮典"],
        ["饭馆继续经营", "启程追踪", "法国东部"],
    ]
    starts = [
        ["东京事件结束，罗亚是否彻底死亡仍待最终检查确认"],
        ["希耶尔已签署解除现役文件，准备交还机关物品"],
        ["希耶尔买下法国旧城的咖喱饭馆，准备重新营业"],
        ["饭馆经营稳定，希耶尔开始拥有重复而平稳的日常"],
        ["数月普通生活后，希耶尔无法回答自己想走向哪里"],
        ["希耶尔决定联系纳鲁巴列克并申请恢复行动"],
        ["纳鲁巴列克已下达追踪安翰斯、回收圣葬炮典的能力复核任务"],
    ]
    ends = [
        ["罗亚确认彻底死亡，希耶尔失去不死性并接受解除现役命令"],
        ["希耶尔交还第七圣典与权限，在法国买下咖喱饭馆"],
        ["希耶尔真心喜欢饭馆、常客与无关紧要的日常快乐"],
        ["希耶尔确认自己熟悉危险，却仍不知平稳生活要通向哪里"],
        ["希耶尔承认自己没有方向，决定暂时向旧工作借一条路"],
        ["希耶尔接受能力复核任务，得知安翰斯正在法国东部活动"],
        ["饭馆留给萨米尔继续经营，希耶尔带黑键乘夜车开始追踪"],
    ]
    paths: list[Path] = []
    documents: list[dict[str, Any]] = []
    for scene_number, content in enumerate(scenes, start=1):
        document = deepcopy(template)
        document_id = f"history-shirouxcile-v01-c001-s{scene_number:03d}-v1.0"
        document["metadata"].update(
            {
                "document_id": document_id,
                "story_id": "shirouxcile",
                "timeline_id": "main",
                "document_type": "history",
                "title": f"第一卷 第一章 新生？回去？ 场景{scene_number}：{titles[scene_number - 1]}",
                "volume": 1,
                "chapter": 1,
                "scene": scene_number,
                "pov_character": "希耶尔",
                "character_ids": ["ciel"] + (["enhance"] if scene_number >= 6 else []),
                "location_ids": locations[scene_number - 1],
                "event_tags": tags[scene_number - 1],
                "start_state": starts[scene_number - 1],
                "end_state": ends[scene_number - 1],
                "previous_scene": None if scene_number == 1 else f"history-shirouxcile-v01-c001-s{scene_number - 1:03d}-v1.0",
                "next_scene": None if scene_number == 7 else f"history-shirouxcile-v01-c001-s{scene_number + 1:03d}-v1.0",
                "version": "1.0",
                "status": "canon",
                "supersedes": None,
                "source_file": str(SOURCE),
                "canon_scope": "timeline",
                "created_at": DATE,
                "updated_at": DATE,
            }
        )
        document["content"] = content
        path = STORY / "history" / "volume-01" / "chapter-001" / f"scene-{scene_number:03d}.yaml"
        write_yaml(path, document)
        paths.append(path)
        documents.append(document)

    restored = "\n\n".join(str(document["content"]) for document in documents)
    original = SOURCE.read_text(encoding="utf-8").replace("\r\n", "\n").strip().split("\n\n", 1)[1]
    if restored != original:
        raise AssertionError("写入后的 History 未逐字保留强化版第一章正文")
    return [str(document["metadata"]["document_id"]) for document in documents]


def write_character_state() -> str:
    template = load_yaml(CHARACTER_TEMPLATE)
    document = deepcopy(template)
    document_id = "state-current-shirouxcile-ciel-v1.0"
    document["metadata"].update(
        {
            "document_id": document_id,
            "story_id": "shirouxcile",
            "timeline_id": "main",
            "document_type": "character_state",
            "title": "当前状态-希耶尔",
            "character_id": "ciel",
            "variant_id": "ciel-main",
            "snapshot_type": "current",
            "effective_at": "volume-01-chapter-001",
            "last_updated": DATE,
            "version": "1.0",
            "status": "active",
            "supersedes": None,
            "source_file": str(SOURCE),
        }
    )
    document["character_state"] = {
        "current_position": {
            "location": "从法国咖喱饭馆出发，乘夜车前往安翰斯最后活动的法国东部区域",
            "companions": [],
            "faction": "埋葬机关能力复核中的前第七位代行者／咖喱饭馆店主",
        },
        "physical": {
            "health": "当前无明确伤势，身体按普通人的速度愈合",
            "injuries": [],
            "fatigue": "可正常行动",
            "temporary_conditions": [],
            "permanent_changes": ["罗亚彻底死亡后，世界修正式不死性永久消失，致命伤不会再恢复"],
        },
        "mental": {
            "dominant_emotions": ["重新行动带来的熟悉感", "对未来方向仍不确定", "对饭馆与日常生活的真实留恋"],
            "current_pressure": ["必须以会死亡的身体重新调整战法", "需通过安翰斯任务证明当前能力"],
            "desires": ["完成任务并活着回来", "保留咖喱饭馆与普通生活", "找到不由罗亚或任务替自己规定的方向"],
            "fears": ["重新把全部人生交给任务", "仍会本能地把自身死亡当作战术成本"],
            "unresolved_conflicts": ["喜欢日常，却仍更熟悉危险与明确目标", "愿意活下去，却尚未回答以后想怎样生活"],
            "behavior_effects": ["会主动评估 mortal 身体的风险", "仍下意识观察出口、异常与潜在死徒活动"],
        },
        "knowledge": {
            "known": [
                "罗亚已经彻底死亡，自己失去不死性",
                "安翰斯曾夺走并非法改造圣葬炮典",
                "安翰斯三天前在法国东部活动并正在追踪另一名高阶死徒",
                "沿安翰斯路线发生的失踪案更可能由其追踪目标造成",
                "第七圣典可在正式申请后约十二小时获得支援",
            ],
            "unknown": [
                "安翰斯正在追踪的高阶死徒是奥尔菲斯·莫伊拉",
                "卫宫士郎正与安翰斯暂时同行",
                "安翰斯下一步会转移到马耳他",
            ],
            "mistaken_beliefs": [],
            "suspicions": ["高阶死徒可能正在减速或建立固定据点"],
            "secrets_held": ["自己恢复行动的深层理由是尚未学会为没有任务的人生选择方向"],
        },
        "goals": {
            "immediate": ["追踪安翰斯", "确认失踪案源头", "回收圣葬炮典"],
            "short_term": ["完成埋葬机关能力复核", "在失去不死性后建立新的战斗方式", "保持饭馆正常经营"],
            "long_term": ["寻找属于希耶尔自己的未来", "在职责与普通生活之间作出持续而非一次性的选择"],
            "priorities": ["阻止无辜者继续失踪", "活着完成任务", "不抛弃已经建立的日常"],
            "obstacles": ["安翰斯与未知高阶死徒的双重风险", "第七圣典目前未随身携带", "自身舍身战斗习惯"],
        },
        "relationships": [
            "纳鲁巴列克：批准能力复核并下达安翰斯任务，双方熟悉且会以挖苦掩饰关心",
            "萨米尔：饭馆厨师与代理经营者，能以打趣直指希耶尔的危险习惯；工资提高两成",
            "安翰斯：当前处决目标与偷走圣葬炮典的小偷，希耶尔拥有明确公私敌意",
        ],
        "abilities": {
            "available": ["黑键", "原理血戒与大型术式的使用知识", "对死徒专业猎杀技术", "埋葬机关战斗经验"],
            "unavailable": ["第七圣典未随身携带，仍封存在机关武装库"],
            "newly_acquired": [],
            "consumed_resources": [],
            "active_costs": ["任何致命伤都将永久致死，不能再以死亡换取攻击距离"],
        },
        "inventory": {
            "carried": ["一束黑键", "加密电话", "两套便于行动的衣服", "空白笔记", "咖喱饭馆钥匙"],
            "lost": [],
            "damaged": [],
        },
        "narrative": {
            "current_arc": "罗亚终结后的新生与安翰斯追捕任务",
            "completed_changes": ["接受自己已成为会正常死亡的人", "建立并真心喜欢普通生活", "选择恢复行动但没有卖掉饭馆"],
            "unresolved_flags": ["归队资格仍待任务完成后确认", "安翰斯与失踪案目标的真实位置", "如何同时保留日常与战斗生活"],
            "active_promises": ["每周查看饭馆账目", "尽量活着回来"],
            "future_pressure": ["追踪将把她带向安翰斯、卫宫士郎与原理Fate", "失去不死性后的舍身惯性会在实战中暴露"],
        },
    }
    current_path = STORY / "character-state" / "current" / "ciel.yaml"
    write_yaml(current_path, document)

    change = {
        "metadata": {
            "document_id": "state-change-shirouxcile-ciel-v01-c001-v1.0",
            "story_id": "shirouxcile",
            "timeline_id": "main",
            "document_type": "character_state",
            "title": "第一卷第一章状态变化-希耶尔",
            "character_id": "ciel",
            "variant_id": "ciel-main",
            "snapshot_type": "change_log",
            "effective_at": "volume-01-chapter-001",
            "last_updated": DATE,
            "version": "1.0",
            "status": "canon",
            "supersedes": None,
            "source_file": str(SOURCE),
        },
        "changes": [
            {
                "category": "chapter_001_outcome",
                "before": None,
                "after": document_id,
                "cause": "罗亚彻底死亡、普通生活尝试与安翰斯能力复核任务",
                "evidence": "history-shirouxcile-v01-c001-s001-v1.0 to history-shirouxcile-v01-c001-s007-v1.0",
            }
        ],
    }
    write_yaml(STORY / "character-state" / "change-logs" / "volume-01-chapter-001" / "ciel.yaml", change)
    return document_id


def write_world_state() -> str:
    template = load_yaml(WORLD_TEMPLATE)
    document = deepcopy(template)
    document_id = "world-state-shirouxcile-current-v1.0"
    document["metadata"].update(
        {
            "document_id": document_id,
            "story_id": "shirouxcile",
            "timeline_id": "main",
            "document_type": "world_state",
            "title": "第一卷第一章后世界状态",
            "version": "1.0",
            "status": "active",
            "effective_at": "volume-01-chapter-001",
            "supersedes": None,
            "source_file": str(SOURCE),
            "updated_at": DATE,
        }
    )
    document["world_state"] = {
        "timeline_position": "第一卷第一章末，罗亚终结数月后，希耶尔开始追踪安翰斯",
        "locations": [
            {
                "location_id": "curry-restaurant",
                "current_condition": "法国旧城中的咖喱饭馆正常营业，扩建完成，由萨米尔代理经营",
                "controlling_faction": "希耶尔所有／萨米尔代理",
                "accessibility": "对公众正常开放",
                "known_hazards": [],
                "recent_events": ["希耶尔启程执行能力复核任务", "下周限定菜单计划为加辣椰奶咖喱"],
            },
            {
                "location_id": "burial-agency-armory",
                "current_condition": "第七圣典已移除希耶尔个人认证并重新封存",
                "controlling_faction": "圣堂教会埋葬机关",
                "accessibility": "希耶尔正式申请后可获得约十二小时内的任务支援",
                "known_hazards": [],
                "recent_events": ["希耶尔解除现役时完成武装交接"],
            },
            {
                "location_id": "eastern-france-trail",
                "current_condition": "安翰斯三天前出现，沿其移动路线已有数人失踪，地点间隔持续缩短",
                "controlling_faction": "未确认",
                "accessibility": "希耶尔正乘夜车接近",
                "known_hazards": ["祖级目标安翰斯", "身份未明的高阶死徒", "持续失踪事件"],
                "recent_events": ["圣葬炮典近期再次开火", "安翰斯追踪目标的移动速度可能下降"],
            },
        ],
        "factions": [
            {
                "faction_id": "burial-agency",
                "current_goal": "通过能力复核确认希耶尔能否恢复席位，并回收圣葬炮典",
                "leadership": "纳鲁巴列克",
                "alliances": [],
                "enemies": ["安翰斯", "制造失踪事件的未知高阶死徒"],
                "known_information": ["罗亚已彻底死亡", "希耶尔失去不死性", "安翰斯最近在法国东部活动"],
                "resources": ["第七圣典", "欧洲情报与后勤网络"],
                "recent_changes": ["希耶尔由解除现役转为能力复核中的行动人员"],
            }
        ],
        "global_events": ["罗亚彻底死亡且转生反应消失", "希耶尔失去世界修正式不死性", "希耶尔开始追踪安翰斯"],
        "public_knowledge": ["法国旧城咖喱饭馆由萨米尔继续营业"],
        "hidden_world_changes": ["安翰斯正在追踪另一名高阶死徒", "希耶尔尚不知道卫宫士郎已与安翰斯暂时同行"],
        "unresolved_world_flags": ["法国东部失踪案的直接凶手", "安翰斯与未知高阶死徒的下一处位置", "希耶尔能力复核结果"],
    }
    write_yaml(STORY / "world-state" / "current" / "current.yaml", document)
    change = {
        "metadata": {
            "document_id": "world-state-shirouxcile-change-v01-c001-v1.0",
            "story_id": "shirouxcile",
            "timeline_id": "main",
            "document_type": "world_state",
            "title": "第一卷第一章世界状态变化",
            "version": "1.0",
            "status": "canon",
            "effective_at": "volume-01-chapter-001",
            "supersedes": None,
            "source_file": str(SOURCE),
        },
        "changes": [
            {
                "category": "chapter_001_outcome",
                "before": None,
                "after": document_id,
                "cause": "第一章确认的罗亚终结、饭馆经营与安翰斯追踪任务",
                "evidence": "history-shirouxcile-v01-c001-s001-v1.0 to history-shirouxcile-v01-c001-s007-v1.0",
            }
        ],
    }
    write_yaml(STORY / "world-state" / "change-logs" / "volume-01-chapter-001.yaml", change)
    return document_id


def update_registries(state_id: str, world_id: str) -> None:
    stories_path = LIBRARY / "registry" / "stories.yaml"
    stories = load_yaml(stories_path)
    for row in stories.get("stories", []):
        if row.get("story_id") == "shirouxcile":
            row["current_volume"] = 1
            row["current_chapter"] = 1
    write_yaml(stories_path, stories)

    versions_path = STORY / "registry" / "version-map.yaml"
    versions_data = load_yaml(versions_path)
    versions = versions_data.setdefault("versions", [])
    upsert(
        versions,
        "document_family",
        "state-current-ciel",
        {
            "document_family": "state-current-ciel",
            "current": state_id,
            "supersedes": [],
            "reason": "回写强化版第一章后的希耶尔位置、知识、目标、装备与人物弧状态。",
        },
    )
    upsert(
        versions,
        "document_family",
        "world-state-current",
        {
            "document_family": "world-state-current",
            "current": world_id,
            "supersedes": [],
            "reason": "回写强化版第一章后的饭馆、埋葬机关武装与法国东部追踪状态。",
        },
    )
    write_yaml(versions_path, versions_data)


def update_retrieval_tests(state_id: str, world_id: str) -> None:
    path = STORY / "retrieval-tests.yaml"
    data = load_yaml(path)
    tests = data.setdefault("tests", [])
    cases = [
        {
            "id": "shirouxcile-history-c001-seventh-scripture-support",
            "story_id": "shirouxcile",
            "timeline_id": "main",
            "query": "安翰斯",
            "document_types": ["history"],
            "expected_document_ids": ["history-shirouxcile-v01-c001-s006-v1.0"],
            "forbidden_statuses": ["draft", "deprecated", "archived"],
            "checks": ["correctness", "timeline_isolation", "version", "content_type"],
        },
        {
            "id": "shirouxcile-history-c001-curry-shop-remains",
            "story_id": "shirouxcile",
            "timeline_id": "main",
            "query": "工资两成",
            "document_types": ["history"],
            "expected_document_ids": ["history-shirouxcile-v01-c001-s007-v1.0"],
            "forbidden_statuses": ["draft", "deprecated", "archived"],
            "checks": ["correctness", "timeline_isolation", "version", "content_type"],
        },
        {
            "id": "shirouxcile-state-ciel-mortal-combat",
            "story_id": "shirouxcile",
            "timeline_id": "main",
            "query": "尽量活着回来",
            "document_types": ["character_state"],
            "expected_document_ids": [state_id],
            "forbidden_statuses": ["draft", "deprecated", "archived"],
            "checks": ["correctness", "timeline_isolation", "version", "content_type"],
        },
        {
            "id": "shirouxcile-world-eastern-france-trail",
            "story_id": "shirouxcile",
            "timeline_id": "main",
            "query": "eastern",
            "document_types": ["world_state"],
            "expected_document_ids": [world_id],
            "forbidden_statuses": ["draft", "deprecated", "archived"],
            "checks": ["correctness", "timeline_isolation", "version", "content_type"],
        },
    ]
    for case in cases:
        upsert(tests, "id", str(case["id"]), case)
    write_yaml(path, data)


def validate_written_documents() -> None:
    roots = [
        STORY / "history" / "volume-01" / "chapter-001",
        STORY / "character-state" / "current",
        STORY / "character-state" / "change-logs" / "volume-01-chapter-001",
        STORY / "world-state" / "current",
        STORY / "world-state" / "change-logs",
    ]
    errors: list[str] = []
    for root in roots:
        for path in sorted(root.glob("*.yaml")):
            path_errors = validate_document(load_document(path))
            errors.extend(f"{path}: {error}" for error in path_errors)
    if errors:
        raise ValueError("\n".join(errors))


def main() -> None:
    if not SOURCE.exists():
        raise FileNotFoundError(SOURCE)
    history_ids = write_history()
    state_id = write_character_state()
    world_id = write_world_state()
    update_registries(state_id, world_id)
    update_retrieval_tests(state_id, world_id)
    validate_written_documents()
    print(f"history_documents={len(history_ids)} state={state_id} world={world_id}")


if __name__ == "__main__":
    main()
