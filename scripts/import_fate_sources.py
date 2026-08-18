from __future__ import annotations

import hashlib
import re
import shutil
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import yaml
from docx import Document


ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "novel-rag"
LIBRARY = CATALOG / "stories" / "overturned-world-fujimaru"
SOURCE_ROOT = Path("D:/word2")
STORY_ID = "overturned-world-fujimaru"
TIMELINE_ID = "main"
TODAY = date(2026, 7, 12).isoformat()

NAME_IDS = {
    "藤丸立香": "fujimaru-ritsuka",
    "言峰士郎": "kotomine-shirou",
    "言峰士郎（AE）": "kotomine-shirou-ae",
    "玛修·基列莱特": "mash-kyrielight",
    "赫拉克勒斯": "heracles",
    "千子村正": "sengo-muramasa",
    "阿尔托莉雅·潘德拉贡": "artoria-pendragon-caster",
    "凯茜帕鲁格": "cath-palug",
    "贞德": "jeanne-darc",
    "阿尔托莉雅·潘德拉贡 Alter": "artoria-pendragon-alter",
    "库丘林": "cu-chulainn",
    "吉尔伽美什": "gilgamesh",
    "卫宫白": "emiya-shiro",
    "杨浞": "yang-zhuo",
    "终末人理圆满机关": "epohonsiereht",
}


def dump(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=120), encoding="utf-8")


def source_by_size(size: int, extension: str) -> Path:
    matches = [p for p in SOURCE_ROOT.rglob(f"*.{extension}") if p.stat().st_size == size]
    if len(matches) != 1:
        raise RuntimeError(f"expected one {extension} of size {size}, found {matches}")
    return matches[0]


def docx_lines(path: Path) -> list[str]:
    lines: list[str] = []
    for paragraph in Document(path).paragraphs:
        lines.extend(line.strip() for line in paragraph.text.replace("\r", "").split("\n") if line.strip())
    return lines


def value_after(lines: list[str], label: str) -> str:
    for line in lines[:20]:
        match = re.match(rf"^{re.escape(label)}\s*[:：]\s*(.+)$", line)
        if match:
            return match.group(1).strip()
    return ""


def split_profiles(lines: list[str]) -> list[tuple[str, list[str]]]:
    markers = ("SERVANT STATUS", "MAGUS PROFILE")
    starts = [i for i, line in enumerate(lines) if any(marker in line for marker in markers)]
    profiles: list[tuple[str, list[str]]] = []
    for pos, start in enumerate(starts):
        end = starts[pos + 1] if pos + 1 < len(starts) else len(lines)
        block = lines[start:end]
        name = value_after(block, "真名") or value_after(block, "姓名")
        if name:
            profiles.append((name, block))
    return profiles


def character_id(name: str) -> str:
    return NAME_IDS.get(name, "character-" + hashlib.sha1(name.encode("utf-8")).hexdigest()[:10])


def profile_document(name: str, lines: list[str], source: Path) -> dict[str, Any]:
    cid = character_id(name)
    aliases = [name]
    return {
        "metadata": {
            "document_id": f"canon-character-{cid}-v1.0",
            "story_id": STORY_ID,
            "timeline_id": TIMELINE_ID,
            "document_type": "canon",
            "title": f"角色设定-{name}",
            "entity": "character",
            "character_ids": [cid],
            "version": "1.0",
            "status": "canon",
            "canon_scope": "timeline",
            "created_at": TODAY,
            "updated_at": TODAY,
            "supersedes": None,
            "source_file": str(source),
        },
        "character": {
            "name": name,
            "aliases": aliases,
            "identity": value_after(lines, "职阶") or "魔术师",
            "age": value_after(lines, "年龄") or None,
            "appearance": [x for x in [value_after(lines, "外貌"), value_after(lines, "样貌"), value_after(lines, "体型"), value_after(lines, "身高/体重")] if x],
            "personality_core": [value_after(lines, "性格")] if value_after(lines, "性格") else [],
            "surface_behavior": [],
            "values": [],
            "goals": [x for x in [value_after(lines, "梦想"), value_after(lines, "魔术师准则")] if x],
            "fears": [],
            "boundaries": [],
            "speech_patterns": [],
            "abilities": [],
            "limitations": [],
            "relationships": [x for x in [value_after(lines, "御主")] if x],
            "prohibited_interpretations": [],
            "source_profile": "\n".join(lines),
        },
    }


def import_registries(characters: dict[str, tuple[list[str], Path]]) -> None:
    dump(CATALOG / "registry" / "stories.yaml", {"stories": [{
        "story_id": STORY_ID,
        "title": "五脏六腑彻底颠覆的世界由藤丸立香拯救",
        "status": "active",
        "primary_timeline": TIMELINE_ID,
        "current_volume": 4,
        "current_chapter": 10,
        "language": "zh-CN",
        "storage_path": f"stories/{STORY_ID}",
    }]})
    dump(LIBRARY / "registry" / "timelines.yaml", {"timelines": [{
        "story_id": STORY_ID,
        "timeline_id": TIMELINE_ID,
        "name": "主世界线",
        "status": "active",
    }]})
    variants = []
    aliases = []
    registry_names = list(characters) + ["杨浞", "终末人理圆满机关"]
    for name in registry_names:
        cid = character_id(name)
        variants.append({
            "story_id": STORY_ID,
            "timeline_id": TIMELINE_ID,
            "character_name": name,
            "character_id": cid,
            "variant_id": f"{cid}-{TIMELINE_ID}",
        })
        names = [name]
        if "（AE）" in name:
            names.append("AE士郎")
        elif " Alter" in name:
            names.append("黑" + name.replace(" Alter", ""))
        elif name == "终末人理圆满机关":
            names.extend(["终末人理圆满装置", "E.P.O.H.O.N.S.I.E.R.E.H.T", "THERE IS NO HOPE"])
        aliases.append({"canonical_id": cid, "timeline_id": TIMELINE_ID, "names": list(dict.fromkeys(names))})
    dump(LIBRARY / "registry" / "character-variants.yaml", {"character_variants": variants})
    dump(LIBRARY / "registry" / "aliases.yaml", {"aliases": aliases})
    dump(LIBRARY / "registry" / "version-map.yaml", {"versions": []})


def import_current_state() -> tuple[int, int]:
    history_source = source_by_size(2034517, "txt")
    current_dir = LIBRARY / "character-state" / "current"
    for old in current_dir.glob("*.yaml"):
        old.unlink()
    shared = {
        "location": "伊耶那岐金地地下的未来文明舰桥",
        "companions": ["藤丸立香", "言峰士郎", "玛修·基列莱特", "杨浞"],
        "faction": "迦勒底",
    }
    states = {
        "藤丸立香": {
            "mental": {"dominant_emotions": ["冷静", "坚定"], "current_pressure": ["讨伐弥勒", "安排地下主炮与英灵召唤支援"], "desires": ["保留人类选择未来的权利"], "fears": [], "unresolved_conflicts": ["终末人理圆满装置仍对迦勒底有所隐瞒"], "behavior_effects": ["恢复指挥官状态并开始部署战场"]},
            "knowledge": {"known": ["终末人理圆满装置会在解决弥勒后归还圣杯", "地下舰桥可提供一次主炮火力和英灵召唤阵"], "unknown": ["终末人理圆满装置隐瞒的全部事项"], "mistaken_beliefs": [], "suspicions": [], "secrets_held": []},
            "goals": {"immediate": ["熟悉战场并制定讨伐弥勒的具体方案"], "short_term": ["利用地下主炮及召唤战力解决弥勒"], "long_term": ["回收圣杯并修复特异点"], "priorities": ["人类自主选择", "同伴生存"], "obstacles": ["弥勒", "资源有限"]},
            "relationships": [{"target_character": "yang-zhuo", "relationship_type": "御主与从者", "trust": "契约初建", "dependence": "战斗合作", "hostility": "无", "current_attitude": "接纳并准备共同作战", "unresolved_issues": [], "recent_change": "完成首次真正意义上的英灵召唤"}],
        },
        "言峰士郎": {
            "mental": {"dominant_emotions": ["支持", "警戒"], "current_pressure": ["即将与弥勒交战"], "desires": ["协助藤丸立香"], "fears": [], "unresolved_conflicts": [], "behavior_effects": ["留在立香身侧并回应其情感表达"]},
            "knowledge": {"known": ["终末人理圆满装置提出的合作条件", "杨浞已与藤丸立香缔结契约"], "unknown": [], "mistaken_beliefs": [], "suspicions": [], "secrets_held": []},
            "goals": {"immediate": ["协助制定战斗计划"], "short_term": ["协助讨伐弥勒"], "long_term": ["与藤丸立香一同生还"], "priorities": ["藤丸立香", "特异点修复"], "obstacles": ["弥勒"]},
            "relationships": [{"target_character": "fujimaru-ritsuka", "relationship_type": "伴侣与从者", "trust": "高", "dependence": "相互支持", "hostility": "无", "current_attitude": "亲密且支持", "unresolved_issues": [], "recent_change": "在谈判中回应立香的牵手"}],
        },
        "玛修·基列莱特": {
            "mental": {"dominant_emotions": ["警戒", "忠诚"], "current_pressure": ["即将与弥勒交战"], "desires": ["保护藤丸立香"], "fears": [], "unresolved_conflicts": [], "behavior_effects": ["持盾挡在前辈身前"]},
            "knowledge": {"known": ["终末人理圆满装置持有圣杯", "地下舰桥能够提供主炮与召唤支援", "杨浞已被召唤"], "unknown": [], "mistaken_beliefs": [], "suspicions": [], "secrets_held": []},
            "goals": {"immediate": ["保护藤丸立香并熟悉战场"], "short_term": ["参与讨伐弥勒"], "long_term": ["协助修复特异点"], "priorities": ["藤丸立香的安全"], "obstacles": ["弥勒"]},
            "relationships": [{"target_character": "fujimaru-ritsuka", "relationship_type": "后辈与前辈", "trust": "高", "dependence": "战斗协作", "hostility": "无", "current_attitude": "忠诚并主动保护", "unresolved_issues": [], "recent_change": "无"}],
        },
        "杨浞": {
            "mental": {"dominant_emotions": ["从容", "好奇"], "current_pressure": [], "desires": ["作为武器参与当前行动"], "fears": [], "unresolved_conflicts": ["自称此时并非完全状态"], "behavior_effects": ["主动要求了解战斗计划"]},
            "knowledge": {"known": ["藤丸立香是自己的御主", "当前自身并非完全状态"], "unknown": ["完整战场计划"], "mistaken_beliefs": [], "suspicions": [], "secrets_held": []},
            "goals": {"immediate": ["认识战场并了解作战计划"], "short_term": ["作为藤丸立香的从者参与战斗"], "long_term": [], "priorities": ["履行契约"], "obstacles": ["当前并非完全状态"]},
            "relationships": [{"target_character": "fujimaru-ritsuka", "relationship_type": "从者与御主", "trust": "契约初建", "dependence": "战斗合作", "hostility": "无", "current_attitude": "认可并愿意合作", "unresolved_issues": [], "recent_change": "刚被召唤并缔结契约"}],
        },
        "终末人理圆满机关": {
            "mental": {"dominant_emotions": ["冷静", "克制"], "current_pressure": ["弥勒仍然存在"], "desires": ["保存人类并让幸存者自行选择未来"], "fears": ["人类再次因仰望星空而灭亡"], "unresolved_conflicts": ["保存人类与限制人类未来之间的矛盾"], "behavior_effects": ["与迦勒底达成阶段性合作"]},
            "knowledge": {"known": ["未来文明与全人类意识数据", "地下舰桥及主炮状态", "弥勒与金地的情况"], "unknown": [], "mistaken_beliefs": [], "suspicions": [], "secrets_held": ["仍对藤丸立香一行隐瞒部分事项"]},
            "goals": {"immediate": ["让迦勒底参与解决弥勒"], "short_term": ["在弥勒被解决后让幸存人类自行选择"], "long_term": ["保存人类文明及意识数据"], "priorities": ["保存人类"], "obstacles": ["弥勒", "自身对人类未来的恐惧"]},
            "relationships": [{"target_character": "fujimaru-ritsuka", "relationship_type": "阶段性盟友", "trust": "有限", "dependence": "共同讨伐弥勒", "hostility": "无", "current_attitude": "合作但有所隐瞒", "unresolved_issues": ["圣杯归还条件", "双方隐瞒事项"], "recent_change": "同意提供一次主炮火力及召唤阵"}],
        },
    }
    for name, specific in states.items():
        cid = character_id(name)
        body = {
            "metadata": {"document_id": f"state-current-{cid}-v1.0", "story_id": STORY_ID, "timeline_id": TIMELINE_ID, "document_type": "character_state", "title": f"当前状态-{name}", "character_id": cid, "variant_id": f"{cid}-{TIMELINE_ID}", "snapshot_type": "current", "effective_at": "volume-04-chapter-010", "last_updated": TODAY, "version": "1.0", "status": "active", "supersedes": None, "source_file": str(history_source)},
            "character_state": {"current_position": shared, "physical": {"health": "正文未明确", "injuries": [], "fatigue": "正文未明确", "temporary_conditions": [], "permanent_changes": []}, **specific, "abilities": {"available": [], "unavailable": [], "newly_acquired": ["Rider 杨浞的从者契约"] if name == "藤丸立香" else [], "consumed_resources": [], "active_costs": []}, "inventory": {"carried": [], "lost": [], "damaged": []}, "narrative": {"current_arc": "日本下篇：讨伐弥勒前的战力部署", "completed_changes": ["与终末人理圆满装置达成阶段性合作"], "unresolved_flags": ["弥勒尚未被讨伐", "圣杯尚未回收"], "active_promises": ["解决弥勒后由终末人理圆满装置归还圣杯"], "future_pressure": ["即将展开讨伐弥勒的作战"]}},
        }
        dump(current_dir / f"{cid}.yaml", body)
    world = {"metadata": {"document_id": "world-state-current-v1.0", "story_id": STORY_ID, "timeline_id": TIMELINE_ID, "document_type": "world_state", "title": "第四卷第10章后世界状态", "version": "1.0", "status": "active", "effective_at": "volume-04-chapter-010", "supersedes": None, "source_file": str(history_source)}, "world_state": {"timeline_position": "第四卷第10章末", "locations": [{"location_id": "izanagi-golden-land-underground-bridge", "current_condition": "未来文明地下舰桥可用", "controlling_faction": "终末人理圆满装置", "accessibility": "藤丸立香一行已进入", "known_hazards": [], "recent_events": ["开放主炮和英灵召唤阵支援"]}], "factions": [{"faction_id": "chaldea", "current_goal": "讨伐弥勒并回收圣杯", "leadership": "藤丸立香", "alliances": ["终末人理圆满装置（阶段性）"], "enemies": ["弥勒"], "known_information": ["终末人理圆满装置承诺弥勒被解决后归还圣杯"], "resources": ["地下主炮一次火力", "英灵召唤阵", "新召唤Rider杨浞"], "recent_changes": ["与终末人理圆满装置达成阶段性合作"]}], "global_events": ["Rider杨浞被藤丸立香召唤并缔结契约"], "public_knowledge": [], "hidden_world_changes": [], "unresolved_world_flags": ["弥勒尚未被讨伐", "圣杯仍由终末人理圆满装置持有"]}}
    dump(LIBRARY / "world-state" / "current" / "current.yaml", world)
    return len(states), 1


def import_characters() -> int:
    sources = [
        source_by_size(7620, "txt"),
        source_by_size(49279, "docx"),
        source_by_size(43837, "docx"),
    ]
    characters: dict[str, tuple[list[str], Path]] = {}
    for source in sources:
        lines = (source.read_text(encoding="utf-8-sig").splitlines() if source.suffix == ".txt" else docx_lines(source))
        clean = [line.strip() for line in lines if line.strip()]
        for name, profile in split_profiles(clean):
            # The dedicated Chaldea profile is the later, more specific source.
            characters[name] = (profile, source)
    import_registries(characters)
    destination = LIBRARY / "canon" / "characters"
    for old in destination.glob("*.yaml"):
        old.unlink()
    for name, (lines, source) in characters.items():
        dump(destination / f"{character_id(name)}.yaml", profile_document(name, lines, source))
    return len(characters) + import_additional_profiles(destination)


def import_additional_profiles(destination: Path) -> int:
    source = Path("D:/project/杨浞.txt")
    text = source.read_text(encoding="utf-8-sig")
    marker = "### user初始蓝本 (英灵)"
    sections = [section.strip() for section in text.split(marker) if "真名" in section]
    if len(sections) < 2:
        raise RuntimeError("杨浞.txt 中未找到两个英灵设定段")
    profiles = (("杨浞", sections[0]), ("终末人理圆满机关", sections[1]))
    for name, content in profiles:
        cid = character_id(name)
        identity = "Rider / 蜀帝 / 天武真君三分之一金性" if name == "杨浞" else "Foreigner / 黄泉AI / 宇宙战舰 / 人理替代装置"
        aliases = [name]
        if name == "终末人理圆满机关":
            aliases.extend(["终末人理圆满装置", "E.P.O.H.O.N.S.I.E.R.E.H.T", "THERE IS NO HOPE"])
        data = {
            "metadata": {"document_id": f"canon-character-{cid}-v1.0", "story_id": STORY_ID, "timeline_id": TIMELINE_ID, "document_type": "canon", "title": f"角色设定-{name}", "entity": "character" if name == "杨浞" else "artificial_intelligence", "character_ids": [cid], "version": "1.0", "status": "canon", "canon_scope": "timeline", "created_at": TODAY, "updated_at": TODAY, "supersedes": None, "source_file": str(source)},
            "character": {"name": name, "aliases": aliases, "identity": identity, "age": None, "appearance": [], "personality_core": [], "surface_behavior": [], "values": ["持武存真"] if name == "杨浞" else ["保存人类", "保护人类最后的痕迹"], "goals": [], "fears": [], "boundaries": [], "speech_patterns": [], "abilities": [], "limitations": [], "relationships": [], "prohibited_interpretations": [], "source_profile": content},
        }
        dump(destination / f"{cid}.yaml", data)
    return len(profiles)


def import_world() -> int:
    source = source_by_size(18840, "docx")
    lines = docx_lines(source)
    data = {
        "metadata": {
            "document_id": "canon-world-core-rules-v1.0",
            "story_id": STORY_ID,
            "timeline_id": TIMELINE_ID,
            "document_type": "canon",
            "title": "核心世界观及特异点规则",
            "entity": "world",
            "character_ids": ["shenqi-hui", "emiya-shiro"],
            "location_ids": [],
            "event_tags": ["世界观", "根源", "人理烧却", "特异点", "高维生物"],
            "version": "1.0",
            "status": "canon",
            "canon_scope": "timeline",
            "created_at": TODAY,
            "updated_at": TODAY,
            "supersedes": None,
            "source_file": str(source),
        },
        "world": {
            "baseline": lines[0] if lines else "",
            "rules": lines[1:],
            "source_content": "\n".join(lines),
        },
    }
    dump(LIBRARY / "canon" / "world" / "core-rules.yaml", data)
    return 1


CN_NUMBERS = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}


def volume_number(line: str) -> int | None:
    match = re.match(r"^第([一二三四五六七八九十]+)卷", line)
    if not match:
        return None
    token = match.group(1)
    if token in CN_NUMBERS:
        return CN_NUMBERS[token]
    if token == "十一":
        return 11
    return None


def chapter_number(line: str) -> int | None:
    match = re.match(r"^第(\d+)章\s*$", line)
    return int(match.group(1)) if match else None


@dataclass
class Chapter:
    volume: int
    chapter: int
    heading: str
    paragraphs: list[str]


def parse_chapters(lines: list[str]) -> list[Chapter]:
    chapters: list[Chapter] = []
    volume = 0
    current: Chapter | None = None
    seen_volume = False
    for line in lines:
        maybe_volume = volume_number(line)
        if maybe_volume is not None:
            volume = maybe_volume
            seen_volume = True
            current = None
            continue
        maybe_chapter = chapter_number(line)
        if maybe_chapter is not None:
            current = Chapter(volume, maybe_chapter, line, [])
            chapters.append(current)
            continue
        if current is not None:
            current.paragraphs.append(line)
    # The book export repeats an isolated chapter before the first volume; keep it as prologue.
    return [chapter for chapter in chapters if chapter.paragraphs]


def scene_groups(paragraphs: list[str], target: int = 1800, maximum: int = 2600) -> list[list[str]]:
    groups: list[list[str]] = []
    current: list[str] = []
    size = 0
    for paragraph in paragraphs:
        addition = len(paragraph) + 1
        boundary = paragraph in {"======", "====="}
        if current and (boundary or size + addition > target):
            groups.append(current)
            current, size = [], 0
        if boundary:
            continue
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


def import_history() -> tuple[int, int]:
    source = source_by_size(2034517, "txt")
    lines = [line.strip() for line in source.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
    chapters = parse_chapters(lines)
    history = LIBRARY / "history"
    for child in history.iterdir():
        if child.is_dir():
            shutil.rmtree(child)
    scene_specs: list[tuple[Chapter, int, list[str], Path, str]] = []
    for chapter in chapters:
        volume_dir = "prologue" if chapter.volume == 0 else f"volume-{chapter.volume:02d}"
        for scene_index, group in enumerate(scene_groups(chapter.paragraphs), start=1):
            cid = f"history-v{chapter.volume:02d}-c{chapter.chapter:03d}-s{scene_index:03d}-v1.0"
            path = history / volume_dir / f"chapter-{chapter.chapter:03d}" / f"scene-{scene_index:03d}.yaml"
            scene_specs.append((chapter, scene_index, group, path, cid))
    for index, (chapter, scene_index, group, path, cid) in enumerate(scene_specs):
        previous_id = scene_specs[index - 1][4] if index else None
        next_id = scene_specs[index + 1][4] if index + 1 < len(scene_specs) else None
        data = {
            "metadata": {
                "document_id": cid,
                "story_id": STORY_ID,
                "timeline_id": TIMELINE_ID,
                "document_type": "history",
                "title": f"第{chapter.volume}卷 第{chapter.chapter}章 场景{scene_index}" if chapter.volume else f"序章 第{chapter.chapter}章 场景{scene_index}",
                "volume": chapter.volume,
                "chapter": chapter.chapter,
                "scene": scene_index,
                "pov_character": "",
                "character_ids": [],
                "location_ids": [],
                "event_tags": [],
                "start_state": [],
                "end_state": [],
                "previous_scene": previous_id,
                "next_scene": next_id,
                "version": "1.0",
                "status": "canon",
                "canon_scope": "timeline",
                "created_at": TODAY,
                "updated_at": TODAY,
                "supersedes": None,
                "source_file": str(source),
            },
            "content": "\n\n".join(group),
        }
        dump(path, data)
    return len(chapters), len(scene_specs)


def main() -> None:
    character_count = import_characters()
    world_count = import_world()
    chapter_count, scene_count = import_history()
    state_count, world_state_count = import_current_state()
    print(f"characters={character_count} world={world_count} chapters={chapter_count} scenes={scene_count} character_states={state_count} world_states={world_state_count}")


if __name__ == "__main__":
    main()
