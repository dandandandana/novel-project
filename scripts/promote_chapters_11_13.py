from __future__ import annotations

import copy
import re
import shutil
from datetime import date
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "novel-rag"
LIBRARY = CATALOG / "stories" / "overturned-world-fujimaru"
SOURCE = ROOT / "outputs" / "第四卷_第11至13章_续写.txt"
STORY_ID = "overturned-world-fujimaru"
TIMELINE_ID = "main"
TODAY = date(2026, 7, 14).isoformat()

CN = {
    "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7,
    "八": 8, "九": 9, "十": 10, "十一": 11, "十二": 12, "十三": 13,
}


def dump(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=120),
        encoding="utf-8",
    )


def parse_chapters(text: str) -> list[tuple[int, str, list[str]]]:
    pattern = re.compile(r"(?m)^第四卷\s+第([一二三四五六七八九十]+)章\s+(.+?)\s*$")
    matches = list(pattern.finditer(text))
    chapters: list[tuple[int, str, list[str]]] = []
    for index, match in enumerate(matches):
        number = CN[match.group(1)]
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = text[match.end():end].strip()
        paragraphs = [item.strip() for item in re.split(r"\r?\n\s*\r?\n", body) if item.strip()]
        chapters.append((number, match.group(2).strip(), paragraphs))
    if [number for number, _, _ in chapters] != [11, 12, 13]:
        raise RuntimeError(f"章节识别失败: {[number for number, _, _ in chapters]}")
    return chapters


def scene_groups(paragraphs: list[str], target: int = 1800, maximum: int = 2500) -> list[list[str]]:
    groups: list[list[str]] = []
    current: list[str] = []
    size = 0
    for paragraph in paragraphs:
        addition = len(paragraph) + 2
        if current and size + addition > target:
            groups.append(current)
            current, size = [], 0
        if len(paragraph) > maximum:
            if current:
                groups.append(current)
                current, size = [], 0
            groups.append([paragraph])
        else:
            current.append(paragraph)
            size += addition
    if current:
        groups.append(current)
    return groups


def promote_history() -> tuple[int, int]:
    chapters = parse_chapters(SOURCE.read_text(encoding="utf-8-sig"))
    specs: list[tuple[int, str, int, list[str], Path, str]] = []
    for number, title, paragraphs in chapters:
        chapter_dir = LIBRARY / "history" / "volume-04" / f"chapter-{number:03d}"
        if chapter_dir.exists():
            shutil.rmtree(chapter_dir)
        for scene, group in enumerate(scene_groups(paragraphs), start=1):
            document_id = f"history-v04-c{number:03d}-s{scene:03d}-v1.0"
            path = chapter_dir / f"scene-{scene:03d}.yaml"
            specs.append((number, title, scene, group, path, document_id))

    previous = "history-v04-c010-s004-v1.0"
    for index, (chapter, title, scene, group, path, document_id) in enumerate(specs):
        next_id = specs[index + 1][5] if index + 1 < len(specs) else None
        dump(path, {
            "metadata": {
                "document_id": document_id,
                "story_id": STORY_ID,
                "timeline_id": TIMELINE_ID,
                "document_type": "history",
                "title": f"第四卷 第{chapter}章 {title} 场景{scene}",
                "volume": 4,
                "chapter": chapter,
                "scene": scene,
                "pov_character": "多视角",
                "character_ids": [],
                "location_ids": [],
                "event_tags": ["日本下篇", "伊耶那岐金地决战准备"],
                "start_state": [],
                "end_state": [],
                "previous_scene": previous,
                "next_scene": next_id,
                "version": "1.0",
                "status": "canon",
                "canon_scope": "timeline",
                "created_at": TODAY,
                "updated_at": TODAY,
                "supersedes": None,
                "source_file": str(SOURCE),
            },
            "content": "\n\n".join(group),
        })
        previous = document_id
    return len(chapters), len(specs)


def archive_current(character_id: str) -> tuple[dict[str, Any] | None, str]:
    path = LIBRARY / "character-state" / "current" / f"{character_id}.yaml"
    if not path.exists():
        return None, "1.0"
    old = yaml.safe_load(path.read_text(encoding="utf-8"))
    old_version = str(old["metadata"]["version"])
    snapshot = copy.deepcopy(old)
    snapshot["metadata"].update({
        "document_id": f"state-snapshot-{character_id}-v{old_version}",
        "title": f"第4卷第10章后状态快照-{snapshot['metadata'].get('title', character_id).replace('当前状态-', '')}",
        "snapshot_type": "snapshot",
        "status": "canon",
    })
    dump(LIBRARY / "character-state" / "snapshots" / "volume-04-chapter-010" / f"{character_id}.yaml", snapshot)
    major, minor = (int(part) for part in old_version.split(".", 1))
    return old, f"{major}.{minor + 1}"


POSITIONS = {
    "fujimaru-ritsuka": ("藤丸立香", "伊耶那岐金地北侧旧祭道", ["言峰士郎", "玛修·基列莱特"], "实施降格术并完成主炮信标校准"),
    "kotomine-shirou": ("言峰士郎", "伊耶那岐金地北侧旧祭道", ["藤丸立香", "玛修·基列莱特"], "携带并安放主炮信标，完成后返回"),
    "mash-kyrielight": ("玛修·基列莱特", "伊耶那岐金地北侧旧祭道", ["藤丸立香", "言峰士郎"], "保护藤丸立香并维持撤离链"),
    "yang-zhuo": ("杨浞", "伊耶那岐金地东门九层阵地", ["吉尔伽美什"], "牵制天照命世尊与假修武星侧战力"),
    "gilgamesh": ("吉尔伽美什", "伊耶那岐金地东门九层阵地", ["杨浞"], "与杨浞协同牵制天照命世尊"),
    "sengo-muramasa": ("千子村正", "伊耶那岐金地地下第三层封锁区", ["祁荒"], "查明创造之禊祓闭锁原因并尝试唤醒"),
    "qihuang": ("祁荒", "伊耶那岐金地地下第三层封锁区", ["千子村正"], "调查人格容器与创造之禊祓"),
    "izanami": ("伊耶娜美", "月读命金地城主府", [], "维持四千九百二十六名居民的生命联系"),
}


def base_state(name: str, location: str, companions: list[str], goal: str) -> dict[str, Any]:
    return {
        "current_position": {"location": location, "companions": companions, "faction": "迦勒底协同行动方"},
        "physical": {"health": "正文未明确异常", "injuries": [], "fatigue": "正文未明确", "temporary_conditions": [], "permanent_changes": []},
        "mental": {"dominant_emotions": ["专注"], "current_pressure": ["伊耶那岐金地决战已经开始"], "desires": [goal], "fears": [], "unresolved_conflicts": [], "behavior_effects": ["按三线作战计划执行当前任务"]},
        "knowledge": {
            "known": ["三线作战计划已经启动", "创造之禊祓处于自主闭锁状态", "主炮只有一发且降格后窗口为十二秒"],
            "unknown": ["终末人理圆满装置隐瞒的最终目的", "创造之禊祓是否会同意协助"],
            "mistaken_beliefs": [], "suspicions": [], "secrets_held": [],
        },
        "goals": {"immediate": [goal], "short_term": ["完成伊耶那岐金地决战中的本组任务"], "long_term": ["修复特异点"], "priorities": ["完成任务", "同伴生存"], "obstacles": ["天照命世尊", "弥勒与九十六尊法相"]},
        "relationships": [],
        "abilities": {"available": [], "unavailable": [], "newly_acquired": [], "consumed_resources": [], "active_costs": []},
        "inventory": {"carried": [], "lost": [], "damaged": []},
        "narrative": {
            "current_arc": "日本下篇：伊耶那岐金地决战",
            "completed_changes": ["完成战前部署并进入各自战位"],
            "unresolved_flags": ["创造之禊祓尚未唤醒", "主炮尚未发射", "弥勒尚未降格"],
            "active_promises": [],
            "future_pressure": ["三线必须在十二秒窗口内完成衔接"],
        },
    }


def promote_states() -> int:
    for character_id, (name, location, companions, goal) in POSITIONS.items():
        old, version = archive_current(character_id)
        previous_id = old["metadata"]["document_id"] if old else None
        state = base_state(name, location, companions, goal)
        if old:
            old_state = old.get("character_state", {})
            state["relationships"] = old_state.get("relationships", [])
            state["abilities"] = old_state.get("abilities", state["abilities"])
            state["inventory"] = old_state.get("inventory", state["inventory"])
        if character_id == "fujimaru-ritsuka":
            state["abilities"]["available"] = ["降格术", "英杰之帜"]
        if character_id == "kotomine-shirou":
            state["inventory"]["carried"] = ["主炮信标", "纸星星复制品"]
            state["narrative"]["active_promises"] = ["完成信标任务后回到藤丸立香身边"]
        if character_id == "yang-zhuo":
            state["knowledge"]["known"].append("天照命世尊持有与杨浞同源的一生记忆")
        if character_id == "izanami":
            state["knowledge"]["known"].extend(["自身神话记忆与亲历记忆并不完全重合", "地下存在大量失败人格容器"])

        metadata = {
            "document_id": f"state-current-{character_id}-v{version}",
            "story_id": STORY_ID,
            "timeline_id": TIMELINE_ID,
            "document_type": "character_state",
            "title": f"当前状态-{name}",
            "character_id": character_id,
            "variant_id": f"{character_id}-main",
            "snapshot_type": "current",
            "effective_at": "volume-04-chapter-013",
            "last_updated": TODAY,
            "version": version,
            "status": "active",
            "supersedes": previous_id,
            "source_file": str(SOURCE),
        }
        dump(LIBRARY / "character-state" / "current" / f"{character_id}.yaml", {"metadata": metadata, "character_state": state})
        dump(LIBRARY / "character-state" / "change-logs" / "volume-04-chapter-013" / f"{character_id}.yaml", {
            "metadata": {
                **metadata,
                "document_id": f"state-change-{character_id}-v04-c013-v1.0",
                "title": f"第4卷第11至13章状态变化-{name}",
                "snapshot_type": "change_log",
                "version": "1.0",
                "status": "canon",
                "supersedes": None,
            },
            "changes": [{
                "category": "current_position_and_goal",
                "before": old.get("character_state", {}).get("current_position") if old else "无既有current记录",
                "after": state["current_position"],
                "cause": "第四卷第11至13章三线作战部署与决战开场",
                "evidence": "history-v04-c013",
            }],
        })
    return len(POSITIONS)


def promote_world_state() -> None:
    current_path = LIBRARY / "world-state" / "current" / "current.yaml"
    old = yaml.safe_load(current_path.read_text(encoding="utf-8"))
    old_version = str(old["metadata"]["version"])
    archived = copy.deepcopy(old)
    archived["metadata"].update({
        "document_id": f"world-state-snapshot-v{old_version}",
        "title": "第4卷第10章后世界状态快照",
        "status": "canon",
    })
    dump(LIBRARY / "world-state" / "change-logs" / "volume-04-chapter-010-snapshot.yaml", archived)
    world = {
        "metadata": {
            "document_id": "world-state-current-v1.2",
            "story_id": STORY_ID,
            "timeline_id": TIMELINE_ID,
            "document_type": "world_state",
            "title": "第四卷第13章后世界状态",
            "version": "1.2",
            "status": "active",
            "effective_at": "volume-04-chapter-013",
            "supersedes": old["metadata"]["document_id"],
            "source_file": str(SOURCE),
            "updated_at": TODAY,
        },
        "world_state": {
            "timeline_position": "第四卷第13章末，伊耶那岐金地决战开始",
            "locations": [
                {"location_id": "izanagi-golden-land", "current_condition": "东门、地下与北侧祭道三线同时交战", "controlling_faction": "弥勒侧", "accessibility": "迦勒底三组已经进入", "known_hazards": ["九十六尊法相", "天照命世尊", "假修武星"], "recent_events": ["天照命世尊与杨浞、吉尔伽美什开始交战"]},
                {"location_id": "izanagi-golden-land-underground", "current_condition": "第三层以后通信中断", "controlling_faction": "未知", "accessibility": "千子村正与祁荒已潜入", "known_hazards": ["人格容器", "空间封锁"], "recent_events": ["确认人格汇聚实验失败记录"]},
                {"location_id": "tsukuyomi-golden-land", "current_condition": "城门关闭，居民集中避难", "controlling_faction": "伊耶娜美", "accessibility": "受限", "known_hazards": ["居民与伊耶娜美生命相连"], "recent_events": ["伊耶娜美留守维持生命联系"]},
            ],
            "factions": [{"faction_id": "chaldea", "current_goal": "完成降格、信标、主炮与创造之禊祓的十二秒衔接", "leadership": "藤丸立香", "alliances": ["伊耶娜美", "终末人理圆满装置（阶段性）"], "enemies": ["弥勒", "天照命世尊", "法相"], "known_information": ["主炮只有一发", "创造之禊祓自主闭锁"], "resources": ["主炮一发", "降格术", "英杰之帜", "Rider杨浞"], "recent_changes": ["三线决战计划启动"]}],
            "global_events": ["修武星持续照耀，正常昼夜被打乱", "伊耶那岐金地决战开始"],
            "public_knowledge": [],
            "hidden_world_changes": ["地下人格汇聚实验与失踪容器的去向尚不明确"],
            "unresolved_world_flags": ["创造之禊祓是否同意协助", "假修武星来源", "终末人理圆满装置最终目的", "主炮衔接尚未完成"],
        },
    }
    dump(current_path, world)


def update_registry() -> None:
    path = CATALOG / "registry" / "stories.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    for story in data.get("stories", []):
        if story.get("story_id") == STORY_ID:
            story["current_volume"] = 4
            story["current_chapter"] = 13
    dump(path, data)


def main() -> None:
    chapters, scenes = promote_history()
    states = promote_states()
    promote_world_state()
    update_registry()
    print(f"promoted_chapters={chapters} scenes={scenes} current_states={states} world_state=1")


if __name__ == "__main__":
    main()
