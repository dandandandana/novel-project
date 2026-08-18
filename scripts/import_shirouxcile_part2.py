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
SOURCE = ROOT / "outputs" / "shirouXcile_part2_马耳他_情绪强化版.txt"
DATE = "2026-08-09"
HISTORY_TEMPLATE = LIBRARY / "shared" / "templates" / "history-scene.yaml"
CHARACTER_TEMPLATE = LIBRARY / "shared" / "templates" / "character-current.yaml"
WORLD_TEMPLATE = LIBRARY / "shared" / "templates" / "world-current.yaml"


class LiteralDumper(yaml.SafeDumper):
    pass


def _represent_string(dumper: yaml.SafeDumper, value: str) -> yaml.ScalarNode:
    return dumper.represent_scalar(
        "tag:yaml.org,2002:str", value, style="|" if "\n" in value else None
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


CHAPTERS: dict[int, dict[str, Any]] = {
    2: {
        "title": "第二章　屋顶上的房客",
        "pov": "安翰斯",
        "markers": [
            "安翰斯醒来时，先听见了刀落在砧板上的声音。",
            "两人安静吃了一会儿。",
            "安翰斯靠回椅背。",
            "伤口重新缝好以后，安翰斯把裂开的杯子扔进垃圾桶。",
        ],
        "scene_titles": [
            "阁楼苏醒与房客早餐",
            "骑士之死与Fate线索",
            "安翰斯拒绝另一段人生",
            "圣葬炮典旧账与分头追踪",
        ],
        "characters": [
            ["enhance", "emiya-shirou"],
            ["enhance", "emiya-shirou", "orpheus-moira"],
            ["enhance", "emiya-shirou", "orpheus-moira"],
            ["enhance", "emiya-shirou", "ciel"],
        ],
        "locations": [["malta-garret"]] * 4,
    },
    3: {
        "title": "第三章　白石巷",
        "pov": "希耶尔",
        "markers": [
            "希耶尔在西西里岛南岸接通了线人的电话。",
            "医院骑士团在港区保留着一座旧院。",
            "希耶尔离开办公室前，请求见一名返回者。",
            "离开病房后，两人沿走廊走了很远。",
            "希耶尔在港区租了一间顶楼公寓。",
            "第三天，她找到了阁楼。",
            "第二天清晨，希耶尔检查了渠口。",
            "安翰斯在二十一点十七分走进那条巷子。",
            "“停手。”\n\n声音从门外传来。",
            "“你打算让他砍中左腹，再换他右臂。”",
            "火系式典在希耶尔掌中炸开。",
            "希耶尔撕开袖口，拔出肩侧细剑。",
            "安翰斯沿途留下了三处血迹。",
            "希耶尔回到地面时已经接近凌晨。",
            "回到公寓，希耶尔先反锁阳台门。",
        ],
        "scene_titles": [
            "西西里来电与赴岛",
            "医院骑士团与失踪简报",
            "艾琳娜的四十九年",
            "从幸存者到追踪目标",
            "马耳他三日追踪",
            "发现阁楼与疏散设计",
            "会死身体的战前预算",
            "白石巷压制安翰斯",
            "士郎介入与救出孩子",
            "舍身旧习被当面说破",
            "愤怒爆发与撤退资源耗尽",
            "认出同类与处决证据争执",
            "地下追逐与诱饵石墙",
            "港口决裂与姓名交换",
            "公寓失控与调查士郎",
        ],
        "characters": [
            ["ciel"],
            ["ciel", "enhance", "emiya-shirou"],
            ["ciel"],
            ["ciel", "orpheus-moira"],
            ["ciel", "enhance", "emiya-shirou"],
            ["ciel", "enhance", "emiya-shirou"],
            ["ciel", "enhance"],
            ["ciel", "enhance"],
            ["ciel", "enhance", "emiya-shirou"],
            ["ciel", "enhance", "emiya-shirou"],
            ["ciel", "emiya-shirou"],
            ["ciel", "emiya-shirou", "enhance"],
            ["ciel", "emiya-shirou", "enhance"],
            ["ciel", "emiya-shirou"],
            ["ciel", "emiya-shirou"],
        ],
        "locations": [
            ["sicily-ferry-terminal", "malta-ferry-route"],
            ["malta-hospitaller-old-hospital"],
            ["malta-hospitaller-old-hospital"],
            ["malta-hospitaller-old-hospital"],
            ["malta-port-district", "malta-fish-market"],
            ["malta-garret-district", "malta-old-waterway"],
            ["malta-garret-district"],
            ["malta-white-stone-alley"],
            ["malta-white-stone-alley"],
            ["malta-white-stone-alley"],
            ["malta-white-stone-alley"],
            ["malta-white-stone-alley"],
            ["malta-old-waterway"],
            ["malta-port-district"],
            ["ciel-malta-apartment"],
        ],
    },
    4: {
        "title": "第四章　咖喱、证据与命运",
        "pov": "希耶尔",
        "markers": [
            "卢卡泡完第一壶咖啡时，希耶尔已经拿到了卫宫士郎的出生记录。",
            "希耶尔确实躺到了床上。",
            "马耳他的街道在上午已经暖起来。",
            "第二份很快送来。",
            "米蕾拉笑着回柜台下单。",
            "那个陌生名字让希耶尔放下杯子。",
            "士郎把话题拉回去。",
            "安翰斯的处决可以复核。Fate不能等。",
        ],
        "scene_titles": [
            "卫宫士郎档案与同类证据",
            "安翰斯复核与精神检查",
            "蓝色小船的咖喱",
            "主厨身份与厨房玩笑",
            "安翰斯处决依据复核",
            "奥尔菲斯与Fate机制",
            "念珠线索与北侧巢穴",
            "八小时武装转运与临时合作",
        ],
        "characters": [
            ["ciel", "emiya-shirou"],
            ["ciel", "emiya-shirou", "enhance"],
            ["ciel", "emiya-shirou"],
            ["ciel", "emiya-shirou"],
            ["ciel", "emiya-shirou", "enhance"],
            ["ciel", "emiya-shirou", "enhance", "orpheus-moira"],
            ["ciel", "emiya-shirou", "enhance", "orpheus-moira"],
            ["ciel", "emiya-shirou", "enhance", "orpheus-moira"],
        ],
        "locations": [
            ["ciel-malta-apartment"],
            ["ciel-malta-apartment"],
            ["blue-boat-curry-restaurant"],
            ["blue-boat-curry-restaurant"],
            ["blue-boat-curry-restaurant"],
            ["blue-boat-curry-restaurant"],
            ["blue-boat-curry-restaurant"],
            ["blue-boat-curry-restaurant", "malta-garret"],
        ],
    },
}


def chapter_bodies() -> dict[int, str]:
    source = SOURCE.read_text(encoding="utf-8").replace("\r\n", "\n").strip()
    result: dict[int, str] = {}
    for chapter, spec in CHAPTERS.items():
        title = str(spec["title"])
        start = source.index(title) + len(title)
        if not source[start:].startswith("\n\n"):
            raise ValueError(f"章节标题后格式异常: {title}")
        start += 2
        if chapter < 4:
            next_title = str(CHAPTERS[chapter + 1]["title"])
            end = source.index("\n\n" + next_title, start)
        else:
            end = len(source)
        result[chapter] = source[start:end].strip()
    return result


def split_scenes(body: str, markers: list[str]) -> list[str]:
    positions = [body.index(marker) for marker in markers]
    if positions[0] != 0 or positions != sorted(positions):
        raise ValueError("场景标记缺失或顺序异常")
    boundaries = [*positions, len(body)]
    scenes = [body[boundaries[i] : boundaries[i + 1]].strip() for i in range(len(markers))]
    if "\n\n".join(scenes) != body:
        raise AssertionError("场景切分未能逐字还原章节正文")
    return scenes


def history_id(chapter: int, scene: int) -> str:
    return f"history-shirouxcile-v01-c{chapter:03d}-s{scene:03d}-v1.0"


def write_history() -> list[str]:
    template = load_yaml(HISTORY_TEMPLATE)
    bodies = chapter_bodies()
    ids: list[str] = []
    for chapter, spec in CHAPTERS.items():
        scenes = split_scenes(bodies[chapter], list(spec["markers"]))
        titles = list(spec["scene_titles"])
        if not (len(scenes) == len(titles) == len(spec["characters"]) == len(spec["locations"])):
            raise AssertionError(f"第{chapter}章场景元数据数量不一致")
        for scene_number, content in enumerate(scenes, start=1):
            document = deepcopy(template)
            document_id = history_id(chapter, scene_number)
            if scene_number > 1:
                previous_scene = history_id(chapter, scene_number - 1)
            elif chapter == 2:
                previous_scene = "history-shirouxcile-v01-c001-s007-v1.0"
            else:
                previous_scene = history_id(chapter - 1, len(CHAPTERS[chapter - 1]["markers"]))
            if scene_number < len(scenes):
                next_scene = history_id(chapter, scene_number + 1)
            elif chapter < 4:
                next_scene = history_id(chapter + 1, 1)
            else:
                next_scene = None
            scene_title = titles[scene_number - 1]
            document["metadata"].update(
                {
                    "document_id": document_id,
                    "story_id": "shirouxcile",
                    "timeline_id": "main",
                    "document_type": "history",
                    "title": f"第一卷 第{chapter}章 {str(spec['title']).split('　', 1)[1]} 场景{scene_number}：{scene_title}",
                    "volume": 1,
                    "chapter": chapter,
                    "scene": scene_number,
                    "pov_character": spec["pov"],
                    "character_ids": spec["characters"][scene_number - 1],
                    "location_ids": spec["locations"][scene_number - 1],
                    "event_tags": [scene_title],
                    "start_state": [f"进入事件：{scene_title}"],
                    "end_state": [f"已发生事件：{scene_title}"],
                    "previous_scene": previous_scene,
                    "next_scene": next_scene,
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
            path = STORY / "history" / "volume-01" / f"chapter-{chapter:03d}" / f"scene-{scene_number:03d}.yaml"
            write_yaml(path, document)
            ids.append(document_id)
    for chapter, original_body in bodies.items():
        restored = "\n\n".join(
            load_yaml(STORY / "history" / "volume-01" / f"chapter-{chapter:03d}" / f"scene-{scene:03d}.yaml")["content"]
            for scene in range(1, len(CHAPTERS[chapter]["markers"]) + 1)
        )
        if restored != original_body:
            raise AssertionError(f"写入后的 History 未逐字保留强化稿第{chapter}章")
    return ids


def archive_current(path: Path, archive_path: Path, *, snapshot_type: str | None = None) -> str | None:
    if not path.exists():
        return None
    old = load_yaml(path)
    old_id = str(old.get("metadata", {}).get("document_id", "")) or None
    old["metadata"]["status"] = "archived"
    if snapshot_type:
        old["metadata"]["snapshot_type"] = snapshot_type
    write_yaml(archive_path, old)
    return old_id


def make_character_state(
    *, character_id: str, name: str, version: str, supersedes: str | None, state: dict[str, Any]
) -> str:
    template = load_yaml(CHARACTER_TEMPLATE)
    document = deepcopy(template)
    document_id = f"state-current-shirouxcile-{character_id}-v{version}"
    document["metadata"].update(
        {
            "document_id": document_id,
            "story_id": "shirouxcile",
            "timeline_id": "main",
            "document_type": "character_state",
            "title": f"当前状态-{name}",
            "character_id": character_id,
            "variant_id": f"{character_id}-main",
            "snapshot_type": "current",
            "effective_at": "volume-01-chapter-004",
            "last_updated": DATE,
            "version": version,
            "status": "active",
            "supersedes": supersedes,
            "source_file": str(SOURCE),
        }
    )
    document["character_state"] = state
    write_yaml(STORY / "character-state" / "current" / f"{character_id}.yaml", document)
    return document_id


def write_character_states() -> dict[str, str]:
    ciel_current = STORY / "character-state" / "current" / "ciel.yaml"
    current_ciel_data = load_yaml(ciel_current) if ciel_current.exists() else {}
    if current_ciel_data.get("metadata", {}).get("document_id") == "state-current-shirouxcile-ciel-v1.1":
        old_ciel = current_ciel_data.get("metadata", {}).get("supersedes")
    else:
        old_ciel = archive_current(
            ciel_current,
            STORY / "character-state" / "snapshots" / "volume-01-chapter-001" / "ciel.yaml",
            snapshot_type="snapshot",
        )
    ciel = make_character_state(
        character_id="ciel",
        name="希耶尔",
        version="1.1",
        supersedes=old_ciel,
        state={
            "current_position": {"location": "马耳他蓝色小船餐厅，随后将与卫宫士郎前往阁楼取资料", "companions": ["emiya-shirou"], "faction": "埋葬机关能力复核中的行动人员／咖喱饭馆店主"},
            "physical": {"health": "可行动，但伤势按普通人速度恢复", "injuries": ["右肩七针缝合并再次渗血", "右手指关节砸裂后包扎", "腰侧青紫", "额角浅伤"], "fatigue": "追踪、战斗与通宵调查后睡眠不足", "temporary_conditions": ["右手缠有绷带", "右肩大幅动作受限"], "permanent_changes": ["罗亚彻底死亡后不死性永久消失"]},
            "mental": {"dominant_emotions": ["舍身惯性暴露后的愤怒与羞恼", "对卫宫士郎的警惕、好奇与同类感", "面对Fate事件的紧迫感"], "current_pressure": ["身体仍会先于判断选择以命换伤", "八小时内完成Fate行动准备"], "desires": ["活着解决Fate事件", "保住饭馆与普通生活", "弄清卫宫士郎为何熟悉舍身打法"], "fears": ["几个月的活着练习在战斗中失效", "Fate展示故乡未毁、艾蕾西亚继续生活的可能"], "unresolved_conflicts": ["承认遗憾而不否定如今的希耶尔", "职责、日常与生存本能尚未真正统一"], "behavior_effects": ["会精确分配撤退资源，却可能在刺激下耗尽", "拒绝被士郎用过来人口气提醒生死", "愿意复核处决依据并交换联络术式"]},
            "knowledge": {"known": ["安翰斯与卫宫士郎在马耳他共同追踪奥尔菲斯·莫伊拉", "Fate会让目标主观经历完整岔命并询问是否想要", "马耳他十七人失踪、七人返回且一名医院骑士死亡", "安翰斯近期救人且暂无平民死亡可直接归责", "卫宫士郎未受支配、曾杀死一名祖且反复以自身伤亡救人", "Fate疑似能从接受另一人生的渴望中获得力量", "临时巢穴范围在马耳他岛北侧", "第七圣典与原理血戒将在八小时后送达"], "unknown": ["奥尔菲斯临时巢穴的精确位置", "Fate完整捕食机制与同一目标可触发次数", "安翰斯当前地下藏身点", "卫宫士郎封闭的童年记忆细节"], "mistaken_beliefs": [], "suspicions": ["骑士可能在死亡前已被奥尔菲斯多次接触", "陪伴幸存者复述经历的人也可能成为后续目标"], "secrets_held": ["故乡未毁、艾蕾西亚继续生活是自己无法轻易拒绝的岔命"]},
            "goals": {"immediate": ["看完阁楼中的全部Fate资料", "等待第七圣典和原理血戒运抵马耳他", "重新处理右肩伤口", "与卫宫士郎核查岛北侧巢穴"], "short_term": ["优先处理奥尔菲斯·莫伊拉", "复核安翰斯处决依据并回收圣葬炮典", "检查Fate相关接触名单"], "long_term": ["找到不否定艾蕾西亚也不否定希耶尔的未来", "保留职责之外的日常生活"], "priorities": ["Fate事件优先", "保护平民与幸存者", "装备到达前避免单独进入巢穴"], "obstacles": ["撤退用黑键与最后一份魔力已在白石巷耗尽", "当前伤势与疲劳", "士郎也有擅自救人的倾向"]},
            "relationships": ["卫宫士郎：由战斗敌对转为高度戒备的临时合作；彼此交换八小时联络术式，也彼此监督不得单独入巢", "安翰斯：处决暂缓、圣葬炮典仍须回收；承认其近期救人和追踪Fate的事实", "纳鲁巴列克：批准Fate优先和八小时武装转运，并继续以挖苦提醒希耶尔先吃饭", "卢卡：连夜调查士郎与安翰斯并提供档案", "艾琳娜：Fate返回者，其四十九年岔命让希耶尔理解诱惑的真实性"],
            "abilities": {"available": ["剩余黑键", "土火水冰四个式典的使用能力", "铁甲", "对死徒专业猎杀技术", "埋葬机关战斗经验"], "unavailable": ["第七圣典尚在运输途中", "原理血戒尚在运输途中"], "newly_acquired": ["与卫宫士郎互换的八小时临时联络术式"], "consumed_resources": ["六枚撤退用黑键", "战前预留的最后一份魔力", "部分式典组件"], "active_costs": ["任何致命伤均会永久致死", "右肩和右手伤势限制动作", "大魔术完整展开当前仅能可靠承担一次"]},
            "inventory": {"carried": ["加密电话", "空白笔记", "咖喱饭馆钥匙", "剩余黑键", "临时联络圣句"], "lost": [], "damaged": ["白石巷战斗中消耗和遗失的多枚黑键", "右肩外套与固定带受损"]},
            "narrative": {"current_arc": "马耳他Fate事件与学习不以生命换伤", "completed_changes": ["亲口承认身体在战场上仍先选择旧的舍身路线", "不再仅凭祖的身份当场处决安翰斯，转而要求证据复核", "与卫宫士郎建立有限且相互监督的临时合作"], "unresolved_flags": ["奥尔菲斯的具体巢穴与完整能力", "安翰斯去向及圣葬炮典回收", "希耶尔和士郎各自会在Fate中看见什么"], "active_promises": ["装备到达前能避免时不单独进入巢穴", "每周查看法国饭馆账目", "与士郎互通目标警报"], "future_pressure": ["Fate会直接触及艾蕾西亚未被罗亚选中的人生", "士郎的舍身习惯会继续刺激她对自身旧习的认识"]},
        },
    )
    shirou = make_character_state(
        character_id="emiya-shirou",
        name="卫宫士郎",
        version="1.0",
        supersedes=None,
        state={
            "current_position": {"location": "马耳他蓝色小船餐厅，准备带希耶尔前往合租阁楼", "companions": ["ciel"], "faction": "独立行动的魔术师／奥尔菲斯追踪者"},
            "physical": {"health": "可正常行动", "injuries": ["右肩被希耶尔扭伤并撞伤", "颈侧有黑键浅切伤", "战斗后全身多处轻微撞伤"], "fatigue": "连续追踪、战斗、写报告与餐厅早班后疲劳", "temporary_conditions": ["右肩发力略慢"], "permanent_changes": []},
            "mental": {"dominant_emotions": ["担心希耶尔的舍身打法", "对她的怒火保持克制", "阻止Fate继续害人的专注"], "current_pressure": ["安翰斯失联", "Fate巢穴可能随时再次带走平民"], "desires": ["救回失踪者并阻止奥尔菲斯", "避免希耶尔和安翰斯互相杀死", "让行动建立在证据上"], "fears": ["有人在八小时等待期内当场失踪", "同伴用生命换取战术收益"], "unresolved_conflicts": ["自己同样习惯把自身放进代价，却试图阻止希耶尔这样做"], "behavior_effects": ["会优先救平民并保留对手退路", "必要时仍可能无视等待命令进入危险区域"]},
            "knowledge": {"known": ["希耶尔已失去不死性且仍有舍身战斗惯性", "希耶尔暂缓处决安翰斯但坚持回收圣葬炮典", "奥尔菲斯的Fate会以真实因果构造另一段人生", "马耳他医院骑士团与教会已进入Fate优先应对", "第七圣典和原理血戒八小时后抵达"], "unknown": ["安翰斯当前藏身处", "希耶尔与罗亚、艾蕾西亚的完整过去", "奥尔菲斯精确巢穴和完整原理"], "mistaken_beliefs": [], "suspicions": ["奥尔菲斯通过接受岔命的愿望获取力量", "骑士的念珠在死亡前已被取走说明接触发生得更早"], "secrets_held": ["1994年冬木灾害与自身封闭的童年记忆"]},
            "goals": {"immediate": ["带希耶尔查看阁楼资料", "寻找安翰斯", "核对岛北侧旧建筑和接触名单"], "short_term": ["阻止奥尔菲斯继续捕食", "保护失踪者与返回者", "维持与希耶尔的临时合作"], "long_term": ["继续处理死徒事件并救助无辜者"], "priorities": ["平民即时安全", "Fate事件", "避免无证据处决"], "obstacles": ["安翰斯失联", "希耶尔对其协助祖的立场不信任", "自身也容易违反撤离和等待命令"]},
            "relationships": ["希耶尔：从拦截处决的交战者转为相互监督的临时同伴；已看穿彼此的舍身倾向", "安翰斯：二十七天的目标合作与合租关系，互相嫌弃但彼此会回去找对方", "米蕾拉：蓝色小船店主，熟悉士郎在厨房帮忙并会拿他与希耶尔打趣", "医院骑士团：共享档案、现场报告和救援合作"],
            "abilities": {"available": ["投影魔术", "多种近战兵器与剑雨", "兵器残留技艺的读取与运用", "结界和临时联络术式", "战场救援与伤口处理"], "unavailable": [], "newly_acquired": ["与希耶尔互换的八小时临时联络术式"], "consumed_resources": ["白石巷连续投影所耗魔力"], "active_costs": ["右肩伤影响大幅发力"]},
            "inventory": {"carried": ["手机", "临时通行证", "临时联络剑印"], "lost": [], "damaged": ["深色外套下摆烧损"]},
            "narrative": {"current_arc": "与安翰斯追踪奥尔菲斯，并与希耶尔形成临时共斗", "completed_changes": ["向希耶尔公开安翰斯与奥尔菲斯的追踪关系", "以证据促使安翰斯的即时处决暂缓", "与希耶尔交换联络术式"], "unresolved_flags": ["安翰斯是否会返回阁楼", "Fate对士郎会展示1994年冬木何种岔命", "等待装备期间是否会出现即时救援"], "active_promises": ["发现目标时第一时间通知希耶尔", "能等待时不独自进入巢穴"], "future_pressure": ["Fate会利用士郎愿意以自身不存在换取火灾死者生还的倾向"]},
        },
    )
    enhance = make_character_state(
        character_id="enhance",
        name="安翰斯",
        version="1.0",
        supersedes=None,
        state={
            "current_position": {"location": "马耳他港区地下旧渠之外的未知藏身处", "companions": [], "faction": "独立祖／奥尔菲斯追踪者"},
            "physical": {"health": "重伤但仍在再生，恢复受双武装反噬拖慢", "injuries": ["肋骨再次断裂", "鼻骨断裂", "右肩反复脱臼与贯穿伤", "左肩圣葬炮典旧伤炸裂", "左腿冻伤", "手掌被黑键切穿"], "fatigue": "长时间追踪与连续战斗后消耗明显", "temporary_conditions": ["圣葬炮典供能结构受损", "Avenger与圣葬炮典持续妨碍再生"], "permanent_changes": []},
            "mental": {"dominant_emotions": ["逃脱后的警戒", "对医院骑士团泄露行动的不满", "对士郎介入的默认信任"], "current_pressure": ["希耶尔已抵达马耳他并掌握住处", "奥尔菲斯仍在岛北活动"], "desires": ["继续追杀奥尔菲斯", "保住圣葬炮典与Avenger", "避免被希耶尔处决"], "fears": [], "unresolved_conflicts": ["与希耶尔的圣葬炮典旧账", "与士郎合作结束后的立场"], "behavior_effects": ["会预设多条地下逃生与诱饵路线", "受伤时仍以嘴上占便宜维持节奏"]},
            "knowledge": {"known": ["希耶尔已经失去不死性并开始重新计算死亡风险", "士郎会阻止无证据处决并优先救平民", "医院骑士团掌握自己的马耳他活动与路线", "奥尔菲斯在岛北建立临时活动范围"], "unknown": ["希耶尔与士郎已达成八小时临时合作", "埋葬机关正在转运第七圣典与原理血戒", "希耶尔已复核自己的近期击杀记录"], "mistaken_beliefs": ["医院骑士团主动把抓捕计划卖给希耶尔"], "suspicions": ["奥尔菲斯可能已重复接触同一批幸存者和骑士"], "secrets_held": ["曾在Fate中看见没有复仇必要、家人仍活着的人生并拒绝"]},
            "goals": {"immediate": ["藏匿并恢复伤势", "避开希耶尔追踪", "重新取得与士郎的联系"], "short_term": ["找到并杀死奥尔菲斯", "阻止Fate继续扩大"], "long_term": ["继续执行自己的复仇与猎祖名单"], "priorities": ["生存与恢复", "奥尔菲斯", "避免平民成为Fate食物"], "obstacles": ["严重伤势与双武装反噬", "希耶尔掌握炮典结构和作战习惯", "马耳他地下路线已部分暴露"]},
            "relationships": ["卫宫士郎：二十七天目标合作与合租同伴；相信士郎会回来找自己", "希耶尔：追杀十余年的旧敌与圣葬炮典原主，互相熟悉战术", "医院骑士团：曾共同救人并获得地方居民帮助，现因抓捕泄密产生不满", "奥尔菲斯·莫伊拉：复仇名单上的高阶祖，原理对安翰斯收益异常低"],
            "abilities": {"available": ["Avenger", "受损的圣葬炮典", "祖级身体与再生", "地下路线与反追踪经验"], "unavailable": ["圣葬炮典完整稳定装填"], "newly_acquired": [], "consumed_resources": ["白石巷逃脱与诱饵路线消耗的血液和魔力"], "active_costs": ["Avenger与圣葬炮典同时侵蚀身体", "多处伤势反复再生"]},
            "inventory": {"carried": ["Avenger", "圣葬炮典", "港区地下路线情报"], "lost": ["阁楼里的地图", "留在阁楼的两件外套"], "damaged": ["炮典外侧保险和供能导管", "黑色长外套"]},
            "narrative": {"current_arc": "马耳他Fate追踪与白石巷逃脱", "completed_changes": ["被希耶尔正面压制后从地下诱饵路线逃脱", "士郎公开介入并阻止即时处决"], "unresolved_flags": ["是否返回阁楼", "如何面对希耶尔暂缓处决后的追问", "奥尔菲斯巢穴的最终位置"], "active_promises": ["中午十二点旧钟塔汇合已因战斗失约", "继续奥尔菲斯追踪"], "future_pressure": ["希耶尔将携第七圣典和原理血戒加入Fate战斗", "严重伤势可能迫使其接受士郎再次治疗"]},
        },
    )
    ids = {"ciel": ciel, "emiya-shirou": shirou, "enhance": enhance}
    for character_id, document_id in ids.items():
        previous = old_ciel if character_id == "ciel" else None
        change = {
            "metadata": {"document_id": f"state-change-shirouxcile-{character_id}-v01-c002-c004-v1.0", "story_id": "shirouxcile", "timeline_id": "main", "document_type": "character_state", "title": f"第一卷第二至四章状态变化-{character_id}", "character_id": character_id, "variant_id": f"{character_id}-main", "snapshot_type": "change_log", "effective_at": "volume-01-chapter-004", "last_updated": DATE, "version": "1.0", "status": "canon", "supersedes": None, "source_file": str(SOURCE)},
            "changes": [{"category": "chapters_002_004_outcome", "before": previous, "after": document_id, "cause": "马耳他追踪、白石巷交战与Fate事件优先处置", "evidence": f"{history_id(2, 1)} to {history_id(4, len(CHAPTERS[4]['markers']))}"}],
        }
        write_yaml(STORY / "character-state" / "change-logs" / "volume-01-chapters-002-004" / f"{character_id}.yaml", change)
    return ids


def write_world_state() -> str:
    world_current = STORY / "world-state" / "current" / "current.yaml"
    current_world_data = load_yaml(world_current) if world_current.exists() else {}
    if current_world_data.get("metadata", {}).get("document_id") == "world-state-shirouxcile-current-v1.1":
        old_world = current_world_data.get("metadata", {}).get("supersedes")
    else:
        old_world = archive_current(
            world_current,
            STORY / "world-state" / "snapshots" / "volume-01-chapter-001.yaml",
        )
    template = load_yaml(WORLD_TEMPLATE)
    document = deepcopy(template)
    document_id = "world-state-shirouxcile-current-v1.1"
    document["metadata"].update({"document_id": document_id, "story_id": "shirouxcile", "timeline_id": "main", "document_type": "world_state", "title": "第一卷第四章后世界状态", "version": "1.1", "status": "active", "effective_at": "volume-01-chapter-004", "supersedes": old_world, "source_file": str(SOURCE), "updated_at": DATE})
    document["world_state"] = {
        "timeline_position": "第一卷第四章末，马耳他Fate事件成为首要目标，第七圣典等武装八小时后抵达",
        "locations": [
            {"location_id": "malta-garret", "current_condition": "卫宫士郎与安翰斯的合租据点仍存有地图、档案和安翰斯衣物，住址已被希耶尔掌握", "controlling_faction": "卫宫士郎租住", "accessibility": "希耶尔将与士郎共同前往", "known_hazards": ["可能被奥尔菲斯监视"], "recent_events": ["安翰斯在白石巷后尚未返回"]},
            {"location_id": "malta-white-stone-alley", "current_condition": "居民疏散后发生祖级交战，储藏室、屋顶、墙面与地下旧渠受损", "controlling_faction": "医院骑士团维持封锁与善后", "accessibility": "居民正在返回", "known_hazards": ["残留武器与术式", "旧渠海水倒灌"], "recent_events": ["希耶尔压制安翰斯", "士郎救出遗漏男孩并阻止处决", "安翰斯从地下路线逃脱"]},
            {"location_id": "malta-hospitaller-old-hospital", "current_condition": "收治Fate返回者并重新检查接触链", "controlling_faction": "医院骑士团", "accessibility": "联合行动人员可进入", "known_hazards": ["返回者仍受完整岔命记忆影响", "询问者可能已进入奥尔菲斯接触范围"], "recent_events": ["累计十七人失踪、七人返回、一名骑士死亡", "开始核查念珠和复述经历者"]},
            {"location_id": "blue-boat-curry-restaurant", "current_condition": "正常营业，卫宫士郎临时负责早班厨房", "controlling_faction": "米蕾拉", "accessibility": "对公众开放", "known_hazards": [], "recent_events": ["希耶尔与士郎交换Fate情报并达成临时合作"]},
            {"location_id": "malta-north-fate-area", "current_condition": "奥尔菲斯临时巢穴范围已缩小到岛北旧建筑群，精确位置未明", "controlling_faction": "奥尔菲斯·莫伊拉疑似活动", "accessibility": "装备抵达前外围封锁", "known_hazards": ["Fate岔命", "精神捕食", "可能重复接触同一目标"], "recent_events": ["医院骑士在此掉队并死亡"]},
        ],
        "factions": [
            {"faction_id": "burial-agency", "current_goal": "Fate事件优先，八小时内向马耳他转运第七圣典、原理血戒和补充武装", "leadership": "纳鲁巴列克", "alliances": ["医院骑士团", "卫宫士郎的临时合作"], "enemies": ["奥尔菲斯·莫伊拉"], "known_information": ["Fate相关症状与旧档一致", "安翰斯处决暂缓但圣葬炮典仍须回收"], "resources": ["第七圣典", "原理血戒", "三套黑键", "四式典补充组件"], "recent_changes": ["任务由安翰斯能力复核转为Fate事件优先"]},
            {"faction_id": "knights-hospitaller", "current_goal": "保护马耳他居民、返回者并协助定位Fate巢穴", "leadership": "马耳他医院骑士团地方指挥", "alliances": ["埋葬机关", "卫宫士郎"], "enemies": ["奥尔菲斯·莫伊拉"], "known_information": ["安翰斯与士郎曾救出多人", "Fate返回者主观经历可达数十年"], "resources": ["医院", "巡逻队", "旧建筑和地下水道档案", "西西里运输线"], "recent_changes": ["白石巷疏散完成", "开始扩大接触名单检查"]},
        ],
        "global_events": ["奥尔菲斯·莫伊拉的Fate原理在马耳他获得确认", "安翰斯即时处决暂缓", "希耶尔与卫宫士郎建立八小时临时联络和共同行动约束"],
        "public_knowledge": ["白石巷以煤气泄漏名义疏散并发生墙体损坏", "蓝色小船餐厅正常营业"],
        "hidden_world_changes": ["第七圣典与原理血戒分线转运，预计八小时后抵达", "Fate可能在事件发生前已取走受害者贴身物并完成早期接触", "安翰斯重伤后藏入未知地下路线"],
        "unresolved_world_flags": ["奥尔菲斯巢穴精确位置", "十名未返回失踪者的状态", "Fate完整捕食与强化机制", "安翰斯是否返回阁楼", "希耶尔和士郎面对各自岔命时的选择"],
    }
    write_yaml(STORY / "world-state" / "current" / "current.yaml", document)
    change = {
        "metadata": {"document_id": "world-state-shirouxcile-change-v01-c002-c004-v1.0", "story_id": "shirouxcile", "timeline_id": "main", "document_type": "world_state", "title": "第一卷第二至四章世界状态变化", "version": "1.0", "status": "canon", "effective_at": "volume-01-chapter-004", "supersedes": None, "source_file": str(SOURCE)},
        "changes": [{"category": "chapters_002_004_outcome", "before": old_world, "after": document_id, "cause": "马耳他失踪事件、白石巷交战与Fate联合应对", "evidence": f"{history_id(2, 1)} to {history_id(4, len(CHAPTERS[4]['markers']))}"}],
    }
    write_yaml(STORY / "world-state" / "change-logs" / "volume-01-chapters-002-004.yaml", change)
    return document_id


def update_registries(history_ids: list[str], states: dict[str, str], world_id: str) -> None:
    stories_path = LIBRARY / "registry" / "stories.yaml"
    stories = load_yaml(stories_path)
    for row in stories.get("stories", []):
        if row.get("story_id") == "shirouxcile":
            row["current_volume"] = 1
            row["current_chapter"] = 4
    write_yaml(stories_path, stories)

    path = STORY / "registry" / "version-map.yaml"
    data = load_yaml(path)
    versions = data.setdefault("versions", [])
    for document_id in history_ids:
        family = document_id.rsplit("-v", 1)[0]
        upsert(versions, "document_family", family, {"document_family": family, "current": document_id, "supersedes": [], "reason": "回写用户确认的马耳他篇正式正文。"})
    for character_id, state_id in states.items():
        previous = ["state-current-shirouxcile-ciel-v1.0"] if character_id == "ciel" else []
        upsert(versions, "document_family", f"state-current-{character_id}", {"document_family": f"state-current-{character_id}", "current": state_id, "supersedes": previous, "reason": "回写第一卷第二至四章后的当前角色状态。"})
    upsert(versions, "document_family", "world-state-current", {"document_family": "world-state-current", "current": world_id, "supersedes": ["world-state-shirouxcile-current-v1.0"], "reason": "回写马耳他Fate事件、白石巷战斗与八小时武装转运状态。"})
    write_yaml(path, data)


def retrieval_case(case_id: str, query: str, document_type: str, expected: str) -> dict[str, Any]:
    return {"id": case_id, "story_id": "shirouxcile", "timeline_id": "main", "query": query, "document_types": [document_type], "expected_document_ids": [expected], "forbidden_statuses": ["draft", "deprecated", "archived"], "checks": ["correctness", "timeline_isolation", "version", "content_type"]}


def update_retrieval_tests(states: dict[str, str], world_id: str) -> None:
    path = STORY / "retrieval-tests.yaml"
    data = load_yaml(path)
    tests = data.setdefault("tests", [])
    cases = [
        retrieval_case("shirouxcile-history-c003-sacrifice-exposed", "你打算让他砍中左腹", "history", history_id(3, 10)),
        retrieval_case("shirouxcile-history-c003-retreat-resources", "你刚才把撤退用的那份也用了", "history", history_id(3, 13)),
        retrieval_case("shirouxcile-history-c004-blue-boat", "招牌上画着一艘蓝色小船", "history", history_id(4, 3)),
        retrieval_case("shirouxcile-state-ciel-mortal-combat", "六枚撤退用黑键", "character_state", states["ciel"]),
        retrieval_case("shirouxcile-state-shirou-mutual-alert", "临时联络剑印", "character_state", states["emiya-shirou"]),
        retrieval_case("shirouxcile-state-enhance-underground", "马耳他港区地下旧渠之外的未知藏身处", "character_state", states["enhance"]),
        retrieval_case("shirouxcile-world-eastern-france-trail", "奥尔菲斯临时巢穴范围已缩小到岛北旧建筑群", "world_state", world_id),
        retrieval_case("shirouxcile-world-malta-fate-priority", "第七圣典与原理血戒分线转运", "world_state", world_id),
    ]
    for case in cases:
        upsert(tests, "id", str(case["id"]), case)
    write_yaml(path, data)


def validate_written_documents() -> None:
    roots = [
        STORY / "history" / "volume-01" / "chapter-002",
        STORY / "history" / "volume-01" / "chapter-003",
        STORY / "history" / "volume-01" / "chapter-004",
        STORY / "character-state" / "current",
        STORY / "character-state" / "snapshots",
        STORY / "character-state" / "change-logs" / "volume-01-chapters-002-004",
        STORY / "world-state" / "current",
        STORY / "world-state" / "snapshots",
        STORY / "world-state" / "change-logs",
    ]
    errors: list[str] = []
    for root in roots:
        if not root.exists():
            continue
        for path in sorted(root.rglob("*.yaml")):
            errors.extend(f"{path}: {error}" for error in validate_document(load_document(path)))
    if errors:
        raise ValueError("\n".join(errors))


def main() -> None:
    if not SOURCE.exists():
        raise FileNotFoundError(SOURCE)
    history_ids = write_history()
    states = write_character_states()
    world_id = write_world_state()
    update_registries(history_ids, states, world_id)
    update_retrieval_tests(states, world_id)
    validate_written_documents()
    print(f"history_documents={len(history_ids)} states={len(states)} world={world_id}")


if __name__ == "__main__":
    main()
