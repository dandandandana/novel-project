from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]
RAG = ROOT / "novel-rag" / "stories" / "overturned-world-fujimaru"
TODAY = "2026-07-18"
STORY_ID = "overturned-world-fujimaru"
TIMELINE_ID = "main"
EFFECTIVE_AT = "volume-04-chapter-017"
SOURCES = {
    15: ROOT / "outputs" / "第四卷_第15章_重写.txt",
    16: ROOT / "outputs" / "第四卷_第16章_重写.txt",
    17: ROOT / "outputs" / "第四卷_第17章_重写.txt",
}
SOURCE_SUMMARY = "; ".join(str(SOURCES[number]) for number in sorted(SOURCES))
SNAPSHOT_DIR = RAG / "character-state" / "snapshots" / "volume-04-chapter-014"
WORLD_SNAPSHOT = (
    RAG
    / "world-state"
    / "change-logs"
    / "volume-04-chapter-014-pre-chapters-015-017.yaml"
)


SECTIONS: dict[int, list[dict[str, Any]]] = {
    15: [
        {
            "marker": "第十五章　十二秒",
            "label": "伤员撤入地下与降格开阵",
            "characters": [
                "fujimaru-ritsuka",
                "kotomine-shirou",
                "mash-kyrielight",
                "yang-zhuo",
                "gilgamesh",
                "sengo-muramasa",
                "qihuang",
                "maitreya",
            ],
            "locations": [
                "izanagi-golden-land-east-gate",
                "izanagi-golden-land-underground",
            ],
            "tags": ["伤员撤离", "降格准备", "创造之禊祓", "十二秒窗口"],
            "start": ["天照命败北后，弥勒开始拔除创造白火"],
            "end": ["藤丸立香进入祁荒守护的坐标阵，开始对弥勒实施降格"],
        },
        {
            "marker": "立香踏进阵心。",
            "label": "弥勒降格与真实佛身显露",
            "characters": [
                "fujimaru-ritsuka",
                "kotomine-shirou",
                "mash-kyrielight",
                "qihuang",
                "sengo-muramasa",
                "maitreya",
            ],
            "locations": ["izanagi-palace", "izanagi-golden-land-east-gate"],
            "tags": ["降格术", "真实佛身", "众生祈愿", "选择未来"],
            "start": ["藤丸立香从众生祈愿中寻找人类求生与弥勒代为决定的分界"],
            "end": ["弥勒的遍在性断开，金地居民首次看见其真实巨佛之身"],
        },
        {
            "marker": "北侧信标石台上",
            "label": "十二秒炮线疏散",
            "characters": ["kotomine-shirou-ae", "artoria-pendragon-alter", "maitreya"],
            "locations": ["izanagi-golden-land-north-ritual-road", "izanagi-palace"],
            "tags": ["主炮轴线", "居民疏散", "十二秒", "Alterego"],
            "start": ["降格完成后，主炮轴线内仍有大量居民"],
            "end": ["Alterego组在窗口结束前将炮线内生命信号清零"],
        },
        {
            "marker": "剩余一秒。",
            "label": "终末主炮解放",
            "characters": [
                "fujimaru-ritsuka",
                "kotomine-shirou",
                "mash-kyrielight",
                "qihuang",
                "sengo-muramasa",
                "epohonsiereht",
                "maitreya",
            ],
            "locations": ["izanagi-palace", "izanagi-golden-land-underground"],
            "tags": ["终末人理圆满装置", "第二宝具", "主炮", "启航星空"],
            "start": ["弥勒试图封住炮口，创造白火与祁荒道场共同稳定轴线"],
            "end": ["主炮贯穿弥勒巨佛之身并进入过热，目标仍然存续"],
        },
        {
            "marker": "她撤下降格术",
            "label": "主炮命中与弥勒压回人形",
            "characters": [
                "fujimaru-ritsuka",
                "kotomine-shirou",
                "mash-kyrielight",
                "qihuang",
                "sengo-muramasa",
                "kotomine-shirou-ae",
                "artoria-pendragon-alter",
                "maitreya",
            ],
            "locations": ["izanagi-palace"],
            "tags": ["人形弥勒", "主炮贯穿伤", "白火压制", "硬打"],
            "start": ["主炮结束，藤丸立香撤下降格术"],
            "end": ["弥勒压缩回人形并以陌生拳架起身，作战进入正面近战"],
        },
    ],
    16: [
        {
            "marker": "第十六章　次显明王",
            "label": "人形弥勒压制Alterego",
            "characters": ["kotomine-shirou-ae", "artoria-pendragon-alter", "maitreya"],
            "locations": ["izanagi-palace"],
            "tags": ["人形近战", "文明武技", "潘多拉承伤刻纹", "Alterego"],
            "start": ["弥勒以人形基础力量冲向Alterego组"],
            "end": ["Alterego组负伤并被持续压制，但没有退出宫殿废墟"],
        },
        {
            "marker": "两人同时被他提离地面。",
            "label": "藤丸立香止步与英杰之帜",
            "characters": [
                "fujimaru-ritsuka",
                "kotomine-shirou",
                "mash-kyrielight",
                "qihuang",
                "kotomine-shirou-ae",
                "artoria-pendragon-alter",
                "maitreya",
            ],
            "locations": ["izanagi-palace"],
            "tags": ["令咒", "英杰之帜", "玛修", "选择权"],
            "start": ["藤丸立香险些离开阵心亲自介入战斗"],
            "end": ["她留在阵心并消耗一道令咒，以英杰之帜强化玛修"],
        },
        {
            "marker": "四个方向同时落下。",
            "label": "四人合击与借物之问",
            "characters": [
                "kotomine-shirou",
                "mash-kyrielight",
                "kotomine-shirou-ae",
                "artoria-pendragon-alter",
                "maitreya",
            ],
            "locations": ["izanagi-palace"],
            "tags": ["四人合击", "拟造躯壳", "投影", "借物"],
            "start": ["士郎、玛修与Alterego组从四个方向围攻弥勒"],
            "end": ["弥勒以基础力量击退士郎，并指出众人都在借用他者之物"],
        },
        {
            "marker": "“吉尔伽美什。”杨浞的声音压得很低",
            "label": "王之财宝中的无名大戟",
            "characters": ["yang-zhuo", "gilgamesh", "kotomine-shirou", "maitreya"],
            "locations": ["izanagi-golden-land-underground", "izanagi-palace"],
            "tags": ["王之财宝", "无名大戟", "投影读取", "身份未知"],
            "start": ["杨浞提示吉尔伽美什寻找宝库深处无法看清的大戟"],
            "end": ["士郎只读到无名无面的残缺动作轨迹，并完成大戟投影"],
        },
        {
            "marker": "紧接着，士郎体内传来第一声骨响。",
            "label": "无名大戟重塑士郎战姿",
            "characters": ["kotomine-shirou", "maitreya"],
            "locations": ["izanagi-palace"],
            "tags": ["无名大戟", "紫火", "战姿重塑", "身份未知"],
            "start": ["无名大戟投影落地，士郎的骨骼与重心开始改变"],
            "end": ["弥勒主动退后并询问兵器来历，士郎明确回答不知道"],
        },
        {
            "marker": "宫殿废墟两侧同时传来诵经声。",
            "label": "法相围攻与士郎破阵",
            "characters": ["kotomine-shirou", "maitreya"],
            "locations": ["izanagi-palace"],
            "tags": ["残存法相", "大戟近战", "头槌", "紫火"],
            "start": ["残存法相与文明兵装从四面围攻士郎"],
            "end": ["十几尊法相被士郎以大戟与霸道近战全部击倒"],
        },
        {
            "marker": "士郎没有回头。",
            "label": "士郎锁喉钉住弥勒",
            "characters": ["kotomine-shirou", "mash-kyrielight", "maitreya"],
            "locations": ["izanagi-palace"],
            "tags": ["锁喉", "近身投技", "投影反作用", "白火接战"],
            "start": ["法相敌对标记全部熄灭，弥勒亲自冲向士郎"],
            "end": ["士郎以重伤为代价将大戟刺穿弥勒，为村正接战争取位置"],
        },
        {
            "marker": "白火从两人脚下升起。",
            "label": "村正选择向未来落刀",
            "characters": ["sengo-muramasa", "kotomine-shirou", "maitreya"],
            "locations": ["izanagi-palace"],
            "tags": ["千子村正", "创造之禊祓", "未来选择", "接战"],
            "start": ["创造白火分开士郎与弥勒，村正进入战场"],
            "end": ["村正拒绝替前人认输，决定先砍开道路再看未来"],
        },
    ],
    17: [
        {
            "marker": "第十七章　天羽羽斩",
            "label": "众人协同护送村正",
            "characters": [
                "fujimaru-ritsuka",
                "kotomine-shirou",
                "mash-kyrielight",
                "qihuang",
                "sengo-muramasa",
                "kotomine-shirou-ae",
                "artoria-pendragon-alter",
                "maitreya",
            ],
            "locations": ["izanagi-palace"],
            "tags": ["协同近战", "佛果分离", "杨枝净瓶", "护送村正"],
            "start": ["村正向前迈出第二步，弥勒直接阻截"],
            "end": ["祁荒把白火中的金色佛果分离并收进杨枝净瓶"],
        },
        {
            "marker": "不能再一拳一拳换。",
            "label": "三秒开路计划",
            "characters": [
                "fujimaru-ritsuka",
                "kotomine-shirou",
                "mash-kyrielight",
                "sengo-muramasa",
                "kotomine-shirou-ae",
                "artoria-pendragon-alter",
                "maitreya",
            ],
            "locations": ["izanagi-palace"],
            "tags": ["三秒", "最终合击", "正面余力", "村正开路"],
            "start": ["藤丸立香判断不能继续逐拳消耗"],
            "end": ["众人完成分工，准备一次打空弥勒正面余力"],
        },
        {
            "marker": "士郎踏碎地面。",
            "label": "三宝具对轰极乐一掌",
            "characters": [
                "kotomine-shirou",
                "mash-kyrielight",
                "kotomine-shirou-ae",
                "artoria-pendragon-alter",
                "maitreya",
            ],
            "locations": ["izanagi-palace"],
            "tags": ["锁喉", "追回明日的迦勒底利刃", "誓约胜利之剑", "天丛云村正伪"],
            "start": ["士郎用无名大戟清开文明兵装并从背后锁住弥勒"],
            "end": ["三件宝具与弥勒的极乐一掌相持，为村正争取三秒"],
        },
        {
            "marker": "弥勒第二步没能踏出。村正等到了第三秒。",
            "label": "村正集约禊祓锻成最终刀",
            "characters": ["sengo-muramasa", "maitreya"],
            "locations": ["izanagi-palace"],
            "tags": ["怨仇之禊祓", "斩尽三千繁华梦", "最终锻刀", "代价"],
            "start": ["弥勒被三件宝具拖住第二步，村正获得三秒"],
            "end": ["村正把战场火焰集约进刀，以斩尽三千繁华梦完成锻造"],
        },
        {
            "marker": "刀名落下，大地深处传来第二声剑鸣。",
            "label": "地底旧伤回应刀锋",
            "characters": ["sengo-muramasa", "maitreya"],
            "locations": ["izanagi-palace"],
            "tags": ["地下异常", "惨白弧面", "旧伤", "未确认原理"],
            "start": ["刀名落下后，大地深处传来无法定位的剑鸣"],
            "end": ["地缝露出带旧伤的惨白弧面，众人无法确认其本质"],
        },
        {
            "marker": "村正拔刀。",
            "label": "天羽羽斩斩开白昼",
            "characters": [
                "sengo-muramasa",
                "kotomine-shirou",
                "mash-kyrielight",
                "kotomine-shirou-ae",
                "artoria-pendragon-alter",
                "maitreya",
            ],
            "locations": ["izanagi-palace"],
            "tags": ["天羽羽斩", "白昼裂隙", "对星余波", "决着"],
            "start": ["三件宝具贯穿佛掌，村正拔刀"],
            "end": ["天羽羽斩切开弥勒与天空，并把向下余量折入地缝"],
        },
        {
            "marker": "人形佛身在他身后分成两半",
            "label": "弥勒承认人类自由并死亡",
            "characters": ["sengo-muramasa", "fujimaru-ritsuka", "maitreya"],
            "locations": ["izanagi-palace"],
            "tags": ["人类自由", "拒绝求赎", "祈愿核心停止", "弥勒死亡"],
            "start": ["弥勒被斩线分开，无法重新连接身体"],
            "end": ["弥勒主动停止维持祈愿核心，生命终止"],
        },
        {
            "marker": "很长一段时间，没有人说话。",
            "label": "终战伤势与金地解封",
            "characters": [
                "fujimaru-ritsuka",
                "kotomine-shirou",
                "mash-kyrielight",
                "qihuang",
                "sengo-muramasa",
                "kotomine-shirou-ae",
                "artoria-pendragon-alter",
                "epohonsiereht",
            ],
            "locations": ["izanagi-palace"],
            "tags": ["战后伤势", "佛像倒塌", "金地解封", "坐标偏移"],
            "start": ["弥勒死亡，众人从最终合击中落地"],
            "end": ["终末人理圆满装置确认弥勒信号归零、金地封锁解除且坐标偏移"],
        },
        {
            "marker": "回答到来之前，祁荒手中的金刚杵先震了一下。",
            "label": "未知来者挤压祁荒坐标",
            "characters": ["fujimaru-ritsuka", "qihuang"],
            "locations": ["izanagi-palace", "cross-world-coordinate"],
            "tags": ["特异点迁移", "无脸人影", "身份未确认", "跨界坐标"],
            "start": ["藤丸立香追问特异点坐标的偏移方向"],
            "end": ["祁荒确认有来者正在反向挤压远端坐标，但没有向立香说明身份"],
        },
        {
            "marker": "远离伊耶那岐金地的另一片世界里，卫宫白睁开眼。",
            "label": "卫宫白开启跨界窄门",
            "characters": ["qihuang"],
            "locations": ["cross-world-coordinate"],
            "tags": ["卫宫白", "透明坐标", "无脸人影", "跨界窄门"],
            "start": ["卫宫白看见透明坐标中无法稳定的无脸人影"],
            "end": ["她压住错位距离并打开通往伊耶那岐金地的窄门，尚未完成跨界"],
        },
    ],
}


CHAPTER_TITLES = {15: "十二秒", 16: "次显明王", 17: "天羽羽斩"}
CHAPTER_PREFIXES = {15: "第十五章", 16: "第十六章", 17: "第十七章"}


def split_paragraphs(text: str, max_chars: int = 2300) -> list[str]:
    paragraphs = [part.strip() for part in re.split(r"\r?\n\r?\n", text.strip()) if part.strip()]
    chunks: list[str] = []
    current: list[str] = []
    size = 0
    for paragraph in paragraphs:
        added = len(paragraph) + (2 if current else 0)
        if current and size + added > max_chars:
            chunks.append("\n\n".join(current))
            current = [paragraph]
            size = len(paragraph)
        else:
            current.append(paragraph)
            size += added
    if current:
        chunks.append("\n\n".join(current))
    if len(chunks) > 1 and len(chunks[-1]) < 500:
        merged = f"{chunks[-2]}\n\n{chunks[-1]}"
        if len(merged) <= 2600:
            chunks[-2:] = [merged]
    return chunks


def section_texts(chapter: int, text: str) -> list[tuple[dict[str, Any], str]]:
    sections = SECTIONS[chapter]
    positions = [text.find(section["marker"]) for section in sections]
    assert all(position >= 0 for position in positions), (chapter, positions)
    assert positions == sorted(positions) and len(set(positions)) == len(positions)
    output: list[tuple[dict[str, Any], str]] = []
    for index, section in enumerate(sections):
        end = positions[index + 1] if index + 1 < len(positions) else len(text)
        output.append((section, text[positions[index] : end].strip()))
    return output


def merge_metadata(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    def unique(items: list[str]) -> list[str]:
        return list(dict.fromkeys(items))

    labels = unique([left["label"], right["label"]])
    return {
        "label": "／".join(labels),
        "characters": unique([*left["characters"], *right["characters"]]),
        "locations": unique([*left["locations"], *right["locations"]]),
        "tags": unique([*left["tags"], *right["tags"]]),
        "start": left["start"],
        "end": right["end"],
    }


def merge_small_records(
    records: list[tuple[dict[str, Any], str]], min_chars: int = 800, max_chars: int = 2500
) -> list[tuple[dict[str, Any], str]]:
    merged = list(records)
    while True:
        small_index = next((index for index, (_, content) in enumerate(merged) if len(content) < min_chars), None)
        if small_index is None:
            return merged
        candidates: list[tuple[int, int]] = []
        if small_index > 0:
            combined_size = len(merged[small_index - 1][1]) + 2 + len(merged[small_index][1])
            if combined_size <= max_chars:
                candidates.append((combined_size, small_index - 1))
        if small_index + 1 < len(merged):
            combined_size = len(merged[small_index][1]) + 2 + len(merged[small_index + 1][1])
            if combined_size <= max_chars:
                candidates.append((combined_size, small_index))
        if not candidates:
            return merged
        _, left_index = min(candidates)
        left_meta, left_content = merged[left_index]
        right_meta, right_content = merged[left_index + 1]
        merged[left_index : left_index + 2] = [
            (merge_metadata(left_meta, right_meta), f"{left_content}\n\n{right_content}")
        ]


def write_history() -> dict[int, list[Path]]:
    records: dict[int, list[tuple[dict[str, Any], str]]] = {}
    for chapter, source in SOURCES.items():
        text = source.read_text(encoding="utf-8").strip()
        assert text.startswith(CHAPTER_PREFIXES[chapter])
        for forbidden in ("李周巍", "故尊复现", "白麒麟", "真君级", "次显锻白再明王戟"):
            assert forbidden not in text, f"{source.name} contains forbidden reveal: {forbidden}"
        chapter_records: list[tuple[dict[str, Any], str]] = []
        for section, section_text in section_texts(chapter, text):
            chapter_records.extend((section, chunk) for chunk in split_paragraphs(section_text))
        records[chapter] = merge_small_records(chapter_records)

    written: dict[int, list[Path]] = {}
    for chapter, chapter_records in records.items():
        history_dir = RAG / "history" / "volume-04" / f"chapter-{chapter:03d}"
        history_dir.mkdir(parents=True, exist_ok=True)
        expected = {f"scene-{index:03d}.yaml" for index in range(1, len(chapter_records) + 1)}
        existing = {path.name for path in history_dir.glob("scene-*.yaml")}
        for old_name in sorted(existing - expected):
            old_path = history_dir / old_name
            old_document = json.loads(old_path.read_text(encoding="utf-8"))
            assert old_document["metadata"]["source_file"] == str(SOURCES[chapter])
            assert old_document["metadata"]["version"] == "1.0"
            assert old_document["metadata"]["status"] == "canon"
            old_path.unlink()
        paths: list[Path] = []
        for index, (section, content) in enumerate(chapter_records, start=1):
            document_id = f"history-v04-c{chapter:03d}-s{index:03d}-v1.0"
            if index > 1:
                previous_scene = f"history-v04-c{chapter:03d}-s{index - 1:03d}-v1.0"
            elif chapter == 15:
                previous_scene = "history-v04-c014-s017-v1.0"
            else:
                previous_count = len(records[chapter - 1])
                previous_scene = f"history-v04-c{chapter - 1:03d}-s{previous_count:03d}-v1.0"
            if index < len(chapter_records):
                next_scene = f"history-v04-c{chapter:03d}-s{index + 1:03d}-v1.0"
            elif chapter < 17:
                next_scene = f"history-v04-c{chapter + 1:03d}-s001-v1.0"
            else:
                next_scene = None
            document = {
                "metadata": {
                    "document_id": document_id,
                    "story_id": STORY_ID,
                    "timeline_id": TIMELINE_ID,
                    "document_type": "history",
                    "title": (
                        f"第四卷 第{chapter}章 {CHAPTER_TITLES[chapter]} "
                        f"场景{index}：{section['label']}"
                    ),
                    "volume": 4,
                    "chapter": chapter,
                    "scene": index,
                    "pov_character": "多视角",
                    "character_ids": section["characters"],
                    "location_ids": section["locations"],
                    "event_tags": ["日本下篇", CHAPTER_TITLES[chapter], *section["tags"]],
                    "start_state": section["start"],
                    "end_state": section["end"],
                    "previous_scene": previous_scene,
                    "next_scene": next_scene,
                    "version": "1.0",
                    "status": "canon",
                    "canon_scope": "timeline",
                    "created_at": TODAY,
                    "updated_at": TODAY,
                    "supersedes": None,
                    "source_file": str(SOURCES[chapter]),
                },
                "content": content,
            }
            path = history_dir / f"scene-{index:03d}.yaml"
            path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            paths.append(path)
        reconstructed = "\n\n".join(
            json.loads(path.read_text(encoding="utf-8"))["content"] for path in paths
        )
        source_text = SOURCES[chapter].read_text(encoding="utf-8").strip()
        assert reconstructed == source_text, f"chapter {chapter} history does not reconstruct source"
        written[chapter] = paths

    chapter_14_tail = RAG / "history" / "volume-04" / "chapter-014" / "scene-017.yaml"
    chapter_14_document = json.loads(chapter_14_tail.read_text(encoding="utf-8"))
    chapter_14_document["metadata"]["next_scene"] = "history-v04-c015-s001-v1.0"
    chapter_14_document["metadata"]["updated_at"] = TODAY
    chapter_14_tail.write_text(
        json.dumps(chapter_14_document, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return written


def physical(health: str, injuries: list[str], fatigue: str, temporary: list[str] | None = None) -> dict[str, Any]:
    return {
        "health": health,
        "injuries": injuries,
        "fatigue": fatigue,
        "temporary_conditions": temporary or [],
        "permanent_changes": [],
    }


def knowledge(known: list[str], unknown: list[str], suspicions: list[str] | None = None) -> dict[str, Any]:
    return {
        "known": known,
        "unknown": unknown,
        "mistaken_beliefs": [],
        "suspicions": suspicions or [],
        "secrets_held": [],
    }


def goals(immediate: list[str], short_term: list[str], obstacles: list[str]) -> dict[str, Any]:
    return {
        "immediate": immediate,
        "short_term": short_term,
        "long_term": ["修复特异点并返回正常人理"],
        "priorities": ["同伴生存", "确认特异点异常"],
        "obstacles": obstacles,
    }


def abilities(
    available: list[str],
    unavailable: list[str] | None = None,
    newly_acquired: list[str] | None = None,
    consumed: list[str] | None = None,
    costs: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "available": available,
        "unavailable": unavailable or [],
        "newly_acquired": newly_acquired or [],
        "consumed_resources": consumed or [],
        "active_costs": costs or [],
    }


def inventory(carried: list[str] | None = None, lost: list[str] | None = None, damaged: list[str] | None = None) -> dict[str, Any]:
    return {"carried": carried or [], "lost": lost or [], "damaged": damaged or []}


def narrative(completed: list[str], unresolved: list[str], pressure: list[str]) -> dict[str, Any]:
    return {
        "current_arc": "日本下篇：伊耶那岐金地终战后",
        "completed_changes": completed,
        "unresolved_flags": unresolved,
        "active_promises": [],
        "future_pressure": pressure,
    }


def mental(emotions: list[str], pressure: list[str], desires: list[str], effects: list[str]) -> dict[str, Any]:
    return {
        "dominant_emotions": emotions,
        "current_pressure": pressure,
        "desires": desires,
        "fears": [],
        "unresolved_conflicts": [],
        "behavior_effects": effects,
    }


STATE_UPDATES: dict[str, tuple[str, dict[str, Any]]] = {
    "fujimaru-ritsuka": (
        "1.4",
        {
            "current_position": {
                "location": "伊耶那岐宫废墟外围",
                "companions": ["言峰士郎", "玛修·基列莱特", "祁荒", "千子村正"],
                "faction": "迦勒底协同行动方",
            },
            "physical": physical(
                "重度疲劳但仍保持清醒",
                ["脸侧被文明兵装擦出细长伤口", "逆向术式过载导致指尖持续发颤"],
                "连续降格、坐标维持与终战指挥造成重度消耗",
            ),
            "mental": mental(
                ["警惕", "克制", "专注"],
                ["弥勒死后特异点坐标开始偏移", "同伴普遍重伤"],
                ["确认坐标偏移方向并稳定伤员与居民"],
                ["拒绝替本世界的人决定未来，只提供自己能够给予的支援"],
            ),
            "knowledge": knowledge(
                [
                    "弥勒已经被降格、主炮贯穿并最终死亡",
                    "伊耶那岐金地封锁解除",
                    "终末主炮已经过热，无法计算下次发射时间",
                    "祁荒确认有来者正在沿远端坐标接近",
                ],
                ["来者身份与目的", "特异点偏移终点", "终末人理圆满装置隐瞒的最终目的"],
            ),
            "goals": goals(
                ["救治重伤同伴", "确认特异点异常迁移"],
                ["稳定金地并查明跨界坐标异常"],
                ["只剩一道令咒", "主炮过热", "多人重伤", "跨界来者身份未明"],
            ),
            "relationships": [
                {
                    "target_character": "mash-kyrielight",
                    "relationship_type": "前辈与后辈／御主与从者",
                    "trust": "高",
                    "dependence": "战斗与精神支援",
                    "hostility": "无",
                    "current_attitude": "将最后两道令咒中的一道作为英杰之帜交给玛修",
                    "unresolved_issues": ["玛修左臂与武装伤势"],
                    "recent_change": "英杰之帜改由玛修承载并完成终战正面对轰",
                }
            ],
            "abilities": abilities(
                ["降格术", "英杰之帜"],
                consumed=["一道令咒用于强化杨浞", "一道令咒用于强化玛修"],
                costs=["剩余令咒一道", "逆向术式过载"],
            ),
            "inventory": inventory(),
            "narrative": narrative(
                ["完成弥勒降格", "指挥十二秒疏散与主炮命中", "指挥终战合击并确认弥勒死亡"],
                ["特异点异常迁移", "跨界来者身份与目的", "圣杯与人理修复核心仍未出现"],
                ["终战胜利立即转化为新的坐标危机"],
            ),
        },
    ),
    "kotomine-shirou": (
        "1.3",
        {
            "current_position": {
                "location": "伊耶那岐宫废墟",
                "companions": ["藤丸立香", "玛修·基列莱特", "千子村正"],
                "faction": "迦勒底协同行动方",
            },
            "physical": physical(
                "重伤，拟造躯壳正在缓慢封闭血管",
                [
                    "鼻梁与胸腔遭弥勒重击",
                    "右肩胛与右臂承受无名大戟反作用后重创",
                    "章末右臂从肩部向下完全失去知觉",
                    "右侧投影回路多处爆裂",
                ],
                "濒临灵基承载上限",
                ["右臂暂时无法使用"],
            ),
            "mental": mental(
                ["克制", "保护欲", "战后警惕"],
                ["右臂失去知觉", "特异点坐标偏移"],
                ["留在立香身边并确认新异常"],
                ["即使身体濒临崩溃，仍选择钉住弥勒为同伴开路"],
            ),
            "knowledge": knowledge(
                [
                    "王之财宝中存在一柄连吉尔伽美什也难以看清的无名大戟",
                    "自己只能从大戟中读到无姓名、无面孔的残缺动作轨迹",
                    "大戟投影会强行改变骨骼咬合、重心与发力方式",
                    "弥勒已经死亡，金地封锁解除",
                ],
                ["无名大戟原主身份、完整来历与力量原理", "特异点坐标偏移原因", "来者身份"],
            ),
            "goals": goals(
                ["稳定右臂与投影回路伤势", "保护藤丸立香"],
                ["协助确认特异点迁移与跨界异常"],
                ["右臂完全失去知觉", "拟造躯壳修复缓慢", "未知跨界来者"],
            ),
            "relationships": [
                {
                    "target_character": "fujimaru-ritsuka",
                    "relationship_type": "伴侣与从者",
                    "trust": "高",
                    "dependence": "相互支持",
                    "hostility": "无",
                    "current_attitude": "按立香指挥承担最危险的钉住任务",
                    "unresolved_issues": ["两人均处于严重消耗状态"],
                    "recent_change": "在终战中以身体与无名大戟投影为她争取三秒窗口",
                }
            ],
            "abilities": abilities(
                ["投影魔术", "拟造躯壳"],
                unavailable=["无名大戟投影已经崩散"],
                newly_acquired=["曾短时读取无名大戟的残缺动作轨迹"],
                costs=["右侧投影回路爆裂", "右肩胛断裂", "右臂失去知觉"],
            ),
            "inventory": inventory(["纸星星复制品"], damaged=["无名大戟投影已崩散"]),
            "narrative": narrative(
                ["投影无名大戟并击倒残存法相", "以锁喉和戟杆钉住弥勒", "参与终战开路"],
                ["无名大戟原主与原理未知", "右臂恢复时间未知", "坐标异常"],
                ["未知兵器带来的短时战力已经消失，只留下严重反作用"],
            ),
        },
    ),
    "mash-kyrielight": (
        "1.3",
        {
            "current_position": {
                "location": "伊耶那岐宫废墟",
                "companions": ["藤丸立香", "言峰士郎"],
                "faction": "迦勒底协同行动方",
            },
            "physical": physical(
                "重伤但清醒",
                [
                    "左肩多次脱臼并出现肌肉崩裂",
                    "左臂在最终对轰后完全垂下",
                    "炮击后坐力对脊柱与双腿造成严重负担",
                ],
                "英杰之帜强化与宝具解放后的重度消耗",
                ["左臂暂时无法使用"],
            ),
            "mental": mental(
                ["坚定", "担忧", "战后警惕"],
                ["自身与士郎的重伤", "特异点坐标偏移"],
                ["保护前辈并协助伤员救治"],
                ["即使盾与身体都会裂，仍保持防线不退"],
            ),
            "knowledge": knowledge(
                [
                    "英杰之帜不会消除伤势，只把自身与伤势一起推至灵基顶峰",
                    "弥勒已经死亡，金地封锁解除",
                    "特异点坐标正在偏移",
                ],
                ["英杰之帜强化还会维持多久", "来者身份", "多功能武装的完整受损程度"],
            ),
            "goals": goals(
                ["稳定左肩和左臂伤势", "协助保护前辈与其他伤员"],
                ["确认特异点异常并准备撤离或再战"],
                ["左臂失去功能", "武装受损", "跨界异常"],
            ),
            "relationships": [
                {
                    "target_character": "fujimaru-ritsuka",
                    "relationship_type": "后辈与前辈",
                    "trust": "高",
                    "dependence": "战斗协作",
                    "hostility": "无",
                    "current_attitude": "承接前辈交出的英杰之帜并完成使命",
                    "unresolved_issues": [],
                    "recent_change": "接受一道令咒所化的英杰之帜强化",
                }
            ],
            "abilities": abilities(
                ["圆桌之盾", "多功能武装", "追回明日的迦勒底利刃"],
                newly_acquired=["英杰之帜强化（持续时间未明确）"],
                costs=["左肩与左臂重创", "多功能武装炮形态在对轰后炸开"],
            ),
            "inventory": inventory(["圆桌之盾／多功能武装"], damaged=["炮形态装甲与外骨骼受损"]),
            "narrative": narrative(
                ["接受英杰之帜", "参与四人近战与最终三宝具对轰", "在士郎坠落时接住其衣领"],
                ["英杰之帜持续时间", "左臂与武装修复", "坐标异常"],
                ["胜利后仍需在左臂无法使用的情况下承担保护职责"],
            ),
        },
    ),
    "qihuang": (
        "1.3",
        {
            "current_position": {
                "location": "伊耶那岐宫废墟外围的破碎坐标阵",
                "companions": ["藤丸立香", "千子村正", "玛修·基列莱特", "言峰士郎"],
                "faction": "迦勒底协同行动方",
            },
            "physical": physical(
                "轻中度负伤，仍可行动",
                ["主炮余波令双手虎口裂开", "维持道场与净瓶承压造成持续出血"],
                "长时间维持坐标阵、道场与净瓶过滤",
            ),
            "mental": mental(
                ["满足", "警觉", "短暂意外"],
                ["远端坐标遭到反向挤压", "来者尚未完成跨界"],
                ["守住坐标并观察新的欲望来源"],
                ["弥勒死亡后仍因居民互相矛盾的愿望而真诚愉悦"],
            ),
            "knowledge": knowledge(
                [
                    "杨枝净瓶已经收纳从创造白火中分离的金色佛果",
                    "弥勒死亡后金地居民的愿望重新分化",
                    "自己留在远方的坐标正在被来者反向挤压",
                    "来者已经回应她的询问并要求守住坐标",
                ],
                ["无脸人影的完整状态与目的", "跨界完成时间", "特异点偏移最终结果"],
            ),
            "goals": goals(
                ["守住跨界坐标", "压制净瓶中停止冲撞的金色佛果"],
                ["观察来者与特异点迁移的关系"],
                ["坐标空间错位", "身份不稳定的无脸人影", "自身双手伤口"],
            ),
            "relationships": [
                {
                    "target_character": "fujimaru-ritsuka",
                    "relationship_type": "同行协作者",
                    "trust": "能够共同维持降格坐标",
                    "dependence": "坐标、防护与战场指挥协作",
                    "hostility": "无",
                    "current_attitude": "一边保护她，一边坦白自己对众生欲望的享受",
                    "unresolved_issues": ["来者身份尚未向立香说明"],
                    "recent_change": "维持降格坐标并在主炮余波中托住立香",
                }
            ],
            "abilities": abilities(
                [
                    "文明侵蚀",
                    "收藏家",
                    "伪装从者",
                    "阵地建造",
                    "寻声救苦",
                    "大慈大悲法门",
                    "此世全部之欲",
                    "变化自在",
                    "金刚杵",
                    "杨枝净瓶",
                ],
                costs=["金刚杵坐标阵与道场承压", "杨枝净瓶收纳金色佛果"],
            ),
            "inventory": inventory(["金刚杵", "杨枝净瓶（内有停止冲撞的金色佛果）"]),
            "narrative": narrative(
                ["稳定藤丸立香降格坐标", "过滤文明兵装与佛果", "感知远端坐标反向挤压"],
                ["无脸人影状态", "来者尚未抵达", "净瓶内佛果后续处理"],
                ["终战后的特异点空位正在吸引新的跨界异常"],
            ),
        },
    ),
    "yang-zhuo": (
        "1.3",
        {
            "current_position": {
                "location": "伊耶那岐金地地下第三层创造室外侧",
                "companions": ["吉尔伽美什"],
                "faction": "迦勒底协同行动方",
            },
            "physical": physical(
                "延续第十四章重伤，正在接受稳定治疗",
                [
                    "左臂缺失",
                    "右肩开放性断裂",
                    "腹部贯穿伤",
                    "左腿行动迟缓",
                    "灵基仍受灰色余火干扰",
                ],
                "重度战斗消耗，未返回正面战场",
            ),
            "mental": mental(
                ["专注", "倔强"],
                ["无法亲自返回弥勒战场"],
                ["通过通讯提供自己能够确认的战术提示"],
                ["提示吉尔伽美什寻找宝库深处无法看清的大戟，但没有说明来历"],
            ),
            "knowledge": knowledge(
                [
                    "吉尔伽美什宝库深处存在一柄连持有者也难以看清的大戟",
                    "该兵器的残缺动作轨迹能被士郎投影读取",
                    "弥勒已经死亡，金地封锁解除",
                ],
                ["士郎投影承受的完整代价", "特异点坐标偏移原因"],
            ),
            "goals": goals(
                ["稳定重伤", "保留进一步提供情报的能力"],
                ["确认终战后金地与特异点状态"],
                ["严重伤势", "宝具损伤", "行动能力不足"],
            ),
            "relationships": [
                {
                    "target_character": "gilgamesh",
                    "relationship_type": "并肩作战的王者",
                    "trust": "可以在关键时刻交换战术情报",
                    "dependence": "宝库与情报互补",
                    "hostility": "竞争性口角",
                    "current_attitude": "负伤期间仍直接指挥其从宝库取物",
                    "unresolved_issues": ["大戟来历没有在场上说明"],
                    "recent_change": "共同通过通讯把无名大戟交到士郎视野中",
                }
            ],
            "abilities": abilities(
                ["真炁六水火", "修武星", "霞羽客", "檀真", "天武真炁神煞真君", "问武平清觯", "奉真策玄鞭"],
                costs=["问武平清觯恢复缓慢", "奉真策玄鞭重损", "重伤限制行动"],
            ),
            "inventory": inventory(
                ["真武正性剑", "问武平清觯", "奉真策玄鞭"],
                damaged=["问武平清觯杯壁裂纹", "奉真策玄鞭接近贯穿的裂口"],
            ),
            "narrative": narrative(
                ["撤入地下接受治疗", "提示王之财宝中的无名大戟", "通过通讯见证弥勒终战"],
                ["重伤恢复", "宝具修复", "大戟相关情报仍未向主角组说明"],
                ["终战结束后仍缺乏重返战场的身体条件"],
            ),
        },
    ),
    "gilgamesh": (
        "1.2",
        {
            "current_position": {
                "location": "伊耶那岐金地地下第三层创造室外侧",
                "companions": ["杨浞"],
                "faction": "迦勒底协同行动方",
            },
            "physical": physical(
                "延续第十四章重伤，正在接受稳定治疗",
                ["左肩、锁骨和部分胸腔缺损", "左腿从膝盖向上失去知觉", "右手虎口裂至腕部"],
                "重度战斗消耗，未返回正面战场",
            ),
            "mental": mental(
                ["高傲", "专注"],
                ["重伤限制行动", "弥勒终战仍需支援"],
                ["以王之财宝提供战场需要的兵器原件"],
                ["按杨浞提示打开宝库最深处门扉，但只允许士郎观看原件"],
            ),
            "knowledge": knowledge(
                [
                    "自己的宝库深处存在一柄连千里眼也难以看清的大戟",
                    "士郎能够投影其外形与残缺动作轨迹",
                    "大戟原件始终留在王之财宝中",
                    "弥勒已经死亡，金地封锁解除",
                ],
                ["无名大戟为何存在于宝库", "杨浞为何知道这件藏品", "特异点偏移原因"],
            ),
            "goals": goals(
                ["稳定重伤", "维持王之财宝可用"],
                ["确认终战后特异点状态"],
                ["严重伤势", "连续解放EA后的消耗", "行动受限"],
            ),
            "relationships": [
                {
                    "target_character": "yang-zhuo",
                    "relationship_type": "并肩作战的王者",
                    "trust": "接受关键战术提示",
                    "dependence": "情报与宝库资源互补",
                    "hostility": "竞争性口角",
                    "current_attitude": "不满其卖关子，但仍立即按提示取出大戟",
                    "unresolved_issues": ["杨浞如何知道宝库藏品"],
                    "recent_change": "共同通过通讯支援士郎完成投影",
                }
            ],
            "abilities": abilities(
                ["王之财宝", "EA／开天辟地乖离之星", "千里眼"],
                costs=["EA连续解放后的重度消耗", "重伤限制移动"],
            ),
            "inventory": inventory(["EA", "九枚时间卵", "无名大戟原件（仍在王之财宝）"]),
            "narrative": narrative(
                ["撤入地下接受治疗", "从王之财宝展示无名大戟原件", "通过通讯见证弥勒终战"],
                ["无名大戟来历", "重伤恢复", "特异点偏移"],
                ["仍保有宝库资源，但本人暂时无法返回正面战场"],
            ),
        },
    ),
    "sengo-muramasa": (
        "1.2",
        {
            "current_position": {
                "location": "伊耶那岐宫废墟",
                "companions": ["藤丸立香", "言峰士郎", "玛修·基列莱特", "祁荒"],
                "faction": "迦勒底协同行动方",
            },
            "physical": physical(
                "重伤，仍能勉强站立与拖拽同伴",
                [
                    "右肋遭弥勒拳锋撕裂",
                    "右臂大半皮肉烧尽",
                    "裸露骨骼布满黑色裂纹",
                    "心口禊祓火纹在终战后熄灭",
                ],
                "连续承载多种禊祓并完成最终斩击后的极重度消耗",
                ["右臂暂时无法正常再生"],
            ),
            "mental": mental(
                ["坚定", "疲惫", "务实"],
                ["右臂严重损毁", "多种禊祓状态不明"],
                ["确认同伴伤势并处理终战后续"],
                ["拒绝因看不见未来而替养育自己的人认输"],
            ),
            "knowledge": knowledge(
                [
                    "众人能够为自己争取三秒开路窗口",
                    "斩尽三千繁华梦完成后地底出现带旧伤的惨白弧面",
                    "自己在斩击时无法确认地底异常的本质",
                    "弥勒已经死亡，金地封锁解除",
                ],
                ["地底惨白弧面的身份与完整结构", "四种禊祓恢复时间", "特异点偏移原因"],
            ),
            "goals": goals(
                ["稳定右臂与禊祓反噬", "协助照看负伤同伴"],
                ["查明地底异常与特异点偏移"],
                ["右臂骨骼裂纹", "禊祓状态不明", "多名同伴重伤"],
            ),
            "relationships": [
                {
                    "target_character": "kotomine-shirou",
                    "relationship_type": "并肩作战者",
                    "trust": "能够接替其拼命争取的战位",
                    "dependence": "终战开路协作",
                    "hostility": "无",
                    "current_attitude": "用嘴硬方式拉起同样右臂重伤的士郎",
                    "unresolved_issues": [],
                    "recent_change": "在士郎钉住弥勒后接手最后一刀",
                }
            ],
            "abilities": abilities(
                ["灼阳之禊祓", "清净之禊祓", "创造之禊祓", "怨仇之禊祓"],
                unavailable=["斩尽三千繁华梦与天羽羽斩已经崩散"],
                costs=["四种禊祓可用状态未明", "右臂大半烧毁", "心口火纹熄灭"],
            ),
            "inventory": inventory(damaged=["终战短刀与天羽羽斩均已崩散"]),
            "narrative": narrative(
                ["以三秒窗口集约禊祓完成最终刀", "解放斩尽三千繁华梦与天羽羽斩", "斩开弥勒并令对星余量折入地底"],
                ["地底异常本质", "禊祓恢复", "右臂修复", "特异点坐标偏移"],
                ["终战核心已经完成，但代价使其短期无法再次承担同等级斩击"],
            ),
        },
    ),
    "kotomine-shirou-ae": (
        "1.1",
        {
            "current_position": {
                "location": "伊耶那岐宫废墟",
                "companions": ["阿尔托莉雅·潘德拉贡 Alter"],
                "faction": "迦勒底阶段性协同行动方",
            },
            "physical": physical(
                "重伤但存活",
                ["下颌骨裂", "右耳失聪", "左侧两根肋骨骨折", "最终宝具后双手暂时无法握物"],
                "持续近战与宝具解放后的重度消耗",
                ["双手暂时无法握物"],
            ),
            "mental": mental(
                ["不耐烦", "放松一瞬", "警惕"],
                ["重伤", "特异点坐标偏移"],
                ["确认阿尔托莉雅状态并等待新异常"],
                ["即使仰面倒地仍以刻薄对话确认彼此存活"],
            ),
            "knowledge": knowledge(
                [
                    "十二秒窗口内的主炮轴线已经清空",
                    "弥勒已经死亡，金地封锁解除",
                    "特异点坐标正在偏移",
                ],
                ["神琦灰的完整计划", "跨界来者身份", "特异点偏移终点"],
            ),
            "goals": goals(
                ["稳定伤势并确认阿尔托莉雅存活"],
                ["观察特异点异常并准备再次行动"],
                ["双手无法握物", "右耳失聪", "肋骨骨折"],
            ),
            "relationships": [
                {
                    "target_character": "artoria-pendragon-alter",
                    "relationship_type": "父女式协同行动者",
                    "trust": "高于口头表现",
                    "dependence": "战斗协作",
                    "hostility": "口头刻薄，无实质敌意",
                    "current_attitude": "以互相挖苦确认对方仍然存活",
                    "unresolved_issues": [],
                    "recent_change": "共同完成主炮疏散、近战压制与最终宝具对轰",
                }
            ],
            "abilities": abilities(
                ["无限剑制", "天丛云村正·伪"],
                costs=["天丛云村正·伪已经崩散", "双手暂时无法握物"],
            ),
            "inventory": inventory(damaged=["投影黑刃与伪天丛云均已崩散"]),
            "narrative": narrative(
                ["完成主炮轴线疏散", "参与人形弥勒近战", "解放天丛云村正·伪"],
                ["神琦灰完整计划", "伤势恢复", "坐标异常"],
                ["终战后短期失去持械能力"],
            ),
        },
    ),
    "artoria-pendragon-alter": (
        "1.1",
        {
            "current_position": {
                "location": "伊耶那岐宫废墟",
                "companions": ["言峰士郎（AE）"],
                "faction": "迦勒底阶段性协同行动方",
            },
            "physical": physical(
                "重伤但仍能站立",
                ["胸甲与腕部多处受创", "黑金长剑断去前半", "七道承伤刻纹已消耗四道"],
                "居民疏散、持续近战与圣剑解放后的重度消耗",
            ),
            "mental": mental(
                ["冷静", "关切", "警惕"],
                ["Alterego言峰士郎重伤", "特异点坐标偏移"],
                ["确认同伴状态并保留潘多拉应对后续异常"],
                ["终战后首先确认言峰士郎（AE）是否存活"],
            ),
            "knowledge": knowledge(
                [
                    "十二秒窗口内的主炮轴线已经清空",
                    "弥勒已经死亡，金地封锁解除",
                    "潘多拉臂铠在终战中始终没有开启",
                ],
                ["跨界来者身份", "特异点偏移原因"],
            ),
            "goals": goals(
                ["确认Alterego言峰士郎伤势", "保留潘多拉应对新异常"],
                ["协助终战后的伤员与居民"],
                ["长剑断裂", "已消耗四道承伤刻纹", "特异点异常"],
            ),
            "relationships": [
                {
                    "target_character": "kotomine-shirou-ae",
                    "relationship_type": "父女式协同行动者",
                    "trust": "高于口头表现",
                    "dependence": "战斗协作",
                    "hostility": "口头挖苦，无实质敌意",
                    "current_attitude": "站在其身边确认存活后才继续观察战场",
                    "unresolved_issues": [],
                    "recent_change": "共同完成主炮疏散、近战压制与最终宝具对轰",
                }
            ],
            "abilities": abilities(
                ["潘多拉臂铠", "开启吧，灾厄与希望", "誓约胜利之剑"],
                consumed=["七道承伤刻纹中的四道"],
                costs=["黑金长剑断去前半", "潘多拉仍保持闭合"],
            ),
            "inventory": inventory(["潘多拉臂铠", "断裂的黑金长剑"], damaged=["黑金长剑断去前半"]),
            "narrative": narrative(
                ["完成炮线居民疏散", "参与人形弥勒近战", "解放誓约胜利之剑"],
                ["潘多拉开启时机", "伤势恢复", "坐标异常"],
                ["仍保留潘多拉底牌，但常规长剑与承伤刻纹已经受损"],
            ),
        },
    ),
    "epohonsiereht": (
        "1.1",
        {
            "current_position": {
                "location": "伊耶那岐金地地下的未来文明舰桥",
                "companions": [],
                "faction": "迦勒底阶段性盟友",
            },
            "physical": physical("机关本体状态未明确", [], "主炮发射后的系统负荷极高"),
            "mental": mental(
                ["冷静", "克制"],
                ["主炮过热", "特异点坐标偏移"],
                ["报告终战结果并继续观测坐标"],
                ["在主炮结束后恢复礼貌、平静的助手语气"],
            ),
            "knowledge": knowledge(
                [
                    "第二宝具主炮已经命中弥勒",
                    "弥勒生命与思潮信号归零",
                    "伊耶那岐金地封锁解除",
                    "特异点坐标正在偏移",
                ],
                ["跨界来者完整身份与目的"],
            ),
            "goals": goals(
                ["监测主炮过热与特异点坐标偏移"],
                ["履行弥勒解决后的阶段性约定"],
                ["主炮下一次发射时间无法计算", "坐标异常"],
            ),
            "relationships": [
                {
                    "target_character": "fujimaru-ritsuka",
                    "relationship_type": "阶段性盟友",
                    "trust": "有限",
                    "dependence": "共同完成弥勒终战",
                    "hostility": "无",
                    "current_attitude": "报告炮击、死亡信号、封锁解除与坐标偏移",
                    "unresolved_issues": ["圣杯归还条件", "双方隐瞒事项"],
                    "recent_change": "完成约定的一次主炮支援",
                }
            ],
            "abilities": abilities(
                ["未来文明主炮与全局观测"],
                unavailable=["第二宝具主炮暂时无法再次发射"],
                consumed=["一次主炮解放"],
                costs=["炮身过热，下一次发射时间无法计算"],
            ),
            "inventory": inventory(),
            "narrative": narrative(
                ["解放第二宝具贯穿弥勒", "确认弥勒信号归零", "报告金地解封与坐标偏移"],
                ["圣杯归还", "机关隐瞒的最终目的", "坐标偏移终点"],
                ["弥勒威胁解除后，双方阶段性盟约进入兑现阶段"],
            ),
        },
    ),
    "amaterasu-no-mikoto": (
        "1.1",
        {
            "current_position": {
                "location": "伊耶那岐金地东门残存金砖；第15至17章未再被观察",
                "companions": [],
                "faction": "已败北的原敌对方；当前失去战斗能力",
            },
            "physical": physical(
                "第15至17章未出现新的可观察变化；延续第十四章重伤",
                ["退化为普通大小黑金孔雀", "仅余三根尾羽", "额骨与全身承受最终对波重创"],
                "极重度消耗",
            ),
            "mental": mental(
                ["疲惫", "平静"],
                ["后续态度未在第15至17章呈现"],
                ["观察众人是否能自行选择未来"],
                ["第15至17章没有新的言行证据"],
            ),
            "knowledge": knowledge(
                ["截至最后一次被观察时，迦勒底正在继续对弥勒作战"],
                ["她是否亲眼确认弥勒死亡", "她是否得知特异点坐标偏移"],
            ),
            "goals": goals(
                ["休息并观察；第15至17章没有新证据"],
                ["未明确"],
                ["重伤", "失去战斗能力"],
            ),
            "relationships": [],
            "abilities": abilities(
                [],
                unavailable=["天照御名与太阳权能", "乌从欲连接", "至命除", "孔雀卵伤势转移", "法相代偿", "历史记录复归"],
            ),
            "inventory": inventory(lost=["伊耶那岐金地世尊佛果", "天照御名", "太阳权能"]),
            "narrative": narrative(
                ["第15至17章没有新的出场事件"],
                ["是否知晓弥勒死亡", "后续立场", "六十六个孩子的安置"],
                ["不得把世界状态变化自动写成她已经知晓的事实"],
            ),
        },
    ),
    "izanami": (
        "1.2",
        {
            "current_position": {
                "location": "月读命金地城主府；第15至17章未再被观察",
                "companions": [],
                "faction": "迦勒底协同行动方",
            },
            "physical": physical(
                "第15至17章没有新的可观察伤势",
                [],
                "是否仍持续承载居民生命联系未在正文确认",
            ),
            "mental": mental(
                ["专注"],
                ["第15至17章没有她的直接视角或对话"],
                ["延续保护月读命金地居民的目标"],
                ["不根据世界状态替她补写已知信息"],
            ),
            "knowledge": knowledge(
                ["截至最后一次被观察时，她仍在城主府维持居民生命联系"],
                ["她是否确认弥勒死亡", "居民生命联系是否随金地解封而变化", "特异点坐标偏移"],
            ),
            "goals": goals(
                ["维持并确认居民生命状态"],
                ["等待能够验证生命联系是否解除的直接证据"],
                ["自身与居民的生命联系状态未确认"],
            ),
            "relationships": [],
            "abilities": abilities([]),
            "inventory": inventory(),
            "narrative": narrative(
                ["第15至17章没有新的出场事件"],
                ["居民生命联系现状", "是否获知弥勒死亡", "特异点偏移"],
                ["不得把作者已经知道的终战结果自动赋予角色"],
            ),
        },
    ),
}


MAITREYA_STATE = {
    "metadata": {
        "document_id": "state-current-maitreya-v1.0",
        "story_id": STORY_ID,
        "timeline_id": TIMELINE_ID,
        "document_type": "character_state",
        "title": "当前状态-弥勒",
        "character_id": "maitreya",
        "variant_id": "maitreya-main",
        "snapshot_type": "current",
        "effective_at": EFFECTIVE_AT,
        "last_updated": TODAY,
        "version": "1.0",
        "status": "active",
        "supersedes": None,
        "source_file": SOURCE_SUMMARY,
    },
    "character_state": {
        "current_position": {"location": "伊耶那岐宫废墟", "companions": [], "faction": "已死亡"},
        "physical": physical(
            "死亡，生命与思潮信号归零",
            ["降格后遭主炮贯穿", "最终斩线切断身体与祈愿核心维持"],
            "不适用",
            ["无法复生；正文确认思潮信号归零"],
        ),
        "mental": mental(
            ["临终平静"],
            [],
            ["接受人类自行承担未来"],
            ["拒绝请求原谅或赎罪，并主动停止维持祈愿核心"],
        ),
        "knowledge": knowledge(
            ["人类已经获得自行选择未来的自由", "自己的拯救不能抵消对人类道路的阻拦"],
            [],
        ),
        "goals": {
            "immediate": [],
            "short_term": [],
            "long_term": [],
            "priorities": [],
            "obstacles": [],
        },
        "relationships": [],
        "abilities": abilities([], unavailable=["全部能力因死亡与思潮信号归零而不可用"]),
        "inventory": inventory(),
        "narrative": narrative(
            ["被藤丸立香降格", "被终末主炮贯穿", "被最终斩击切断", "主动停止维持祈愿核心并死亡"],
            [],
            ["其死亡造成金地解封与特异点坐标偏移"],
        ),
    },
}


WORLD_STATE = {
    "metadata": {
        "document_id": "world-state-current-v1.4",
        "story_id": STORY_ID,
        "timeline_id": TIMELINE_ID,
        "document_type": "world_state",
        "title": "第四卷第17章后世界状态",
        "version": "1.4",
        "status": "active",
        "effective_at": EFFECTIVE_AT,
        "supersedes": "world-state-current-v1.3",
        "source_file": SOURCE_SUMMARY,
        "updated_at": TODAY,
    },
    "world_state": {
        "timeline_position": "第四卷第17章末，弥勒死亡、金地解封，特异点坐标开始异常偏移",
        "locations": [
            {
                "location_id": "izanagi-palace",
                "current_condition": "宫殿毁灭，佛像失去支撑断首倒塌，地表与山系严重破坏",
                "controlling_faction": "无稳定控制者；迦勒底协同行动方暂时留在废墟",
                "accessibility": "金地封锁解除，但废墟、地层拱起与空间裂隙造成高风险",
                "known_hazards": ["持续下沉的山川", "未闭合的天空裂隙", "大量重伤人员"],
                "recent_events": ["弥勒死亡", "天羽羽斩切开天空", "佛像与宫殿失去神性支撑"],
            },
            {
                "location_id": "izanagi-golden-land-underground",
                "current_condition": "终末主炮已经发射并过热，地下第三层用作重伤员安置点",
                "controlling_faction": "终末人理圆满装置与迦勒底阶段性协作方",
                "accessibility": "地下出口已经由创造白火打开",
                "known_hazards": ["主炮过热", "地下结构受对星余波与地层变动影响"],
                "recent_events": ["杨浞与吉尔伽美什在创造室外接受稳定治疗", "主炮从地下贯穿弥勒"],
            },
            {
                "location_id": "cross-world-coordinate",
                "current_condition": "透明坐标被无法稳定的无脸人影挤压，距离发生错位",
                "controlling_faction": "未确认",
                "accessibility": "卫宫白已压缩错位距离并打开窄门，但尚未完成跨界",
                "known_hazards": ["空间距离失真", "无脸人影身份与目的未知"],
                "recent_events": ["祁荒感知远端坐标反向挤压", "卫宫白开始打开通往伊耶那岐金地的门"],
            },
        ],
        "factions": [
            {
                "faction_id": "chaldea",
                "current_goal": "救治重伤同伴、稳定金地并查明特异点迁移与跨界坐标异常",
                "leadership": "藤丸立香",
                "alliances": ["终末人理圆满装置（阶段性）", "Alterego言峰士郎与阿尔托莉雅（阶段性）"],
                "enemies": [],
                "known_information": [
                    "弥勒生命与思潮信号归零",
                    "金地封锁解除",
                    "主炮过热",
                    "特异点坐标正在偏移",
                ],
                "resources": [
                    "剩余一道令咒",
                    "祁荒的坐标阵与杨枝净瓶",
                    "潘多拉宝具仍未开启",
                    "终末人理圆满装置的观测能力",
                ],
                "recent_changes": ["弥勒从敌对方移除", "多数前线成员重伤", "终战目标转为坐标异常"],
            }
        ],
        "global_events": [
            "弥勒生命与思潮信号归零",
            "伊耶那岐金地封锁解除",
            "居民失去统一救世主庇护并开始自行决定未来",
            "天空留下白昼可见星光的裂隙",
            "终末主炮过热，下一次发射时间无法计算",
            "特异点坐标开始异常偏移",
        ],
        "public_knowledge": [
            "金地居民亲眼看见弥勒真实佛身、人形战斗与死亡",
            "居民已经知道未来不再由弥勒替他们决定",
            "城市与山川遭到严重破坏，后续生存和安置需要自行选择",
        ],
        "hidden_world_changes": [
            "弥勒死亡留下的特异点坐标空位正在遭到无法稳定的无脸人影挤压",
            "卫宫白已经在另一世界开启跨界窄门，但尚未抵达",
            "终末人理圆满装置仍未说明其完整最终目的",
        ],
        "unresolved_world_flags": [
            "特异点坐标偏移的终点与原因",
            "无脸人影的身份、状态与目的",
            "卫宫白能否完成跨界",
            "地下惨白弧面与新增贯通裂口的本质",
            "金地居民的安置、治理与星空选择",
            "杨枝净瓶内金色佛果的后续处理",
            "终战成员的重伤与禊祓恢复",
            "圣杯归还与人理修复核心仍未完成",
        ],
    },
}


def write_yaml(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(value, allow_unicode=True, sort_keys=False, width=1000),
        encoding="utf-8",
    )


def snapshot_and_write_states() -> list[str]:
    current_dir = RAG / "character-state" / "current"
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    document_ids: list[str] = []
    for filename, (version, state) in STATE_UPDATES.items():
        current_path = current_dir / f"{filename}.yaml"
        old = yaml.safe_load(current_path.read_text(encoding="utf-8"))
        old_id = str(old["metadata"]["document_id"])
        old_version = str(old["metadata"]["version"])
        new_id = f"state-current-{filename}-v{version}"
        if old_id == new_id:
            document_ids.append(new_id)
            continue
        snapshot = copy.deepcopy(old)
        snapshot["metadata"]["title"] = snapshot["metadata"]["title"].replace(
            "当前状态-", "第四卷第14章末状态快照-"
        )
        snapshot["metadata"]["snapshot_type"] = "snapshot"
        snapshot["metadata"]["status"] = "archived"
        snapshot_path = SNAPSHOT_DIR / f"{filename}-v{old_version}.yaml"
        write_yaml(snapshot_path, snapshot)

        updated = copy.deepcopy(old)
        updated["metadata"].update(
            {
                "document_id": new_id,
                "snapshot_type": "current",
                "effective_at": EFFECTIVE_AT,
                "last_updated": TODAY,
                "version": version,
                "status": "active",
                "supersedes": old_id,
                "source_file": SOURCE_SUMMARY,
            }
        )
        updated["character_state"] = state
        write_yaml(current_path, updated)
        document_ids.append(new_id)

    maitreya_path = current_dir / "maitreya.yaml"
    write_yaml(maitreya_path, MAITREYA_STATE)
    document_ids.append(MAITREYA_STATE["metadata"]["document_id"])
    return document_ids


def snapshot_and_write_world() -> str:
    current_path = RAG / "world-state" / "current" / "current.yaml"
    old = yaml.safe_load(current_path.read_text(encoding="utf-8"))
    if old["metadata"]["document_id"] == WORLD_STATE["metadata"]["document_id"]:
        return str(WORLD_STATE["metadata"]["document_id"])
    snapshot = copy.deepcopy(old)
    snapshot["metadata"]["title"] = "第四卷第14章末世界状态快照"
    snapshot["metadata"]["status"] = "archived"
    write_yaml(WORLD_SNAPSHOT, snapshot)
    write_yaml(current_path, WORLD_STATE)
    return str(WORLD_STATE["metadata"]["document_id"])


VERSION_UPDATES = {
    "state-current-fujimaru-ritsuka": ("state-current-fujimaru-ritsuka-v1.4", "回写第四卷第15至17章后的令咒、降格、终战与坐标偏移状态"),
    "state-current-kotomine-shirou": ("state-current-kotomine-shirou-v1.3", "回写第四卷第15至17章后的无名大戟投影、终战近战与右臂重伤状态"),
    "state-current-mash-kyrielight": ("state-current-mash-kyrielight-v1.3", "回写第四卷第15至17章后的英杰之帜、宝具解放与左臂重伤状态"),
    "state-current-qihuang": ("state-current-qihuang-v1.3", "回写第四卷第15至17章后的降格坐标、净瓶佛果与跨界感知状态"),
    "state-current-yang-zhuo": ("state-current-yang-zhuo-v1.3", "回写第四卷第15至17章后的地下治疗与无名大戟战术提示状态"),
    "state-current-gilgamesh": ("state-current-gilgamesh-v1.2", "回写第四卷第15至17章后的地下治疗与王之财宝无名大戟支援状态"),
    "state-current-sengo-muramasa": ("state-current-sengo-muramasa-v1.2", "回写第四卷第15至17章后的最终锻刀、天羽羽斩与右臂重伤状态"),
    "state-current-kotomine-shirou-ae": ("state-current-kotomine-shirou-ae-v1.1", "回写第四卷第15至17章后的疏散、宝具解放与双手重伤状态"),
    "state-current-artoria-pendragon-alter": ("state-current-artoria-pendragon-alter-v1.1", "回写第四卷第15至17章后的疏散、圣剑解放与承伤刻纹消耗"),
    "state-current-epohonsiereht": ("state-current-epohonsiereht-v1.1", "回写第四卷第15至17章后的主炮过热、弥勒信号归零与坐标偏移观测"),
    "state-current-amaterasu-no-mikoto": ("state-current-amaterasu-no-mikoto-v1.1", "记录第四卷第15至17章未再观察天照命，避免把终战结果越权写入其认知"),
    "state-current-izanami": ("state-current-izanami-v1.2", "记录第四卷第15至17章未再观察伊耶娜美，保留居民生命联系与认知边界"),
    "state-current-maitreya": ("state-current-maitreya-v1.0", "建立第四卷第17章死亡后弥勒的当前终止状态"),
    "world-state-current": ("world-state-current-v1.4", "回写第四卷第17章后弥勒死亡、金地解封、主炮过热与坐标偏移状态"),
}

INITIAL_SUPERSEDES = {
    "state-current-epohonsiereht": ["state-current-epohonsiereht-v1.0"],
}


def update_version_map() -> None:
    path = RAG / "registry" / "version-map.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    rows = data["versions"]
    by_family = {row["document_family"]: row for row in rows}
    for family, (new_id, reason) in VERSION_UPDATES.items():
        row = by_family.get(family)
        if row is None:
            row = {
                "document_family": family,
                "current": new_id,
                "supersedes": list(INITIAL_SUPERSEDES.get(family, [])),
                "reason": reason,
            }
            rows.append(row)
            by_family[family] = row
            continue
        old_current = str(row["current"])
        old_supersedes = [str(item) for item in row.get("supersedes", [])]
        if old_current != new_id:
            row["supersedes"] = [old_current, *[item for item in old_supersedes if item != old_current]]
        elif family in INITIAL_SUPERSEDES:
            row["supersedes"] = [
                *INITIAL_SUPERSEDES[family],
                *[item for item in old_supersedes if item not in INITIAL_SUPERSEDES[family]],
            ]
        row["current"] = new_id
        row["reason"] = reason
    write_yaml(path, data)


NEW_RETRIEVAL_TESTS = [
    {
        "id": "history-chapter-015-main-cannon-result",
        "story_id": STORY_ID,
        "timeline_id": TIMELINE_ID,
        "query": "降格完成 炮线清空 主炮命中 白火仍在燃烧",
        "document_types": ["history"],
        "expected_document_ids": ["history-v04-c015-s005-v1.0"],
        "forbidden_statuses": ["draft", "deprecated", "archived"],
        "checks": ["correctness", "timeline_isolation", "temporal", "content_type"],
    },
    {
        "id": "history-chapter-016-unnamed-halberd",
        "story_id": STORY_ID,
        "timeline_id": TIMELINE_ID,
        "query": "门后没有宝具雨 只悬着一柄大戟",
        "document_types": ["history"],
        "expected_document_ids": ["history-v04-c016-s004-v1.0"],
        "forbidden_statuses": ["draft", "deprecated", "archived"],
        "checks": ["correctness", "timeline_isolation", "temporal", "content_type"],
    },
    {
        "id": "history-chapter-017-sky-severed",
        "story_id": STORY_ID,
        "timeline_id": TIMELINE_ID,
        "query": "白昼被切成两半",
        "document_types": ["history"],
        "expected_document_ids": ["history-v04-c017-s004-v1.0"],
        "forbidden_statuses": ["draft", "deprecated", "archived"],
        "checks": ["correctness", "timeline_isolation", "temporal", "content_type"],
    },
    {
        "id": "history-chapter-017-cross-world-coordinate",
        "story_id": STORY_ID,
        "timeline_id": TIMELINE_ID,
        "query": "桌上的透明坐标已经失去原本形状",
        "document_types": ["history"],
        "expected_document_ids": ["history-v04-c017-s005-v1.0"],
        "forbidden_statuses": ["draft", "deprecated", "archived"],
        "checks": ["correctness", "timeline_isolation", "temporal", "content_type"],
    },
    {
        "id": "state-kotomine-unnamed-halberd-boundary",
        "story_id": STORY_ID,
        "timeline_id": TIMELINE_ID,
        "query": "无名大戟原主身份",
        "document_types": ["character_state"],
        "expected_document_ids": ["state-current-kotomine-shirou-v1.3"],
        "forbidden_document_ids": ["state-current-kotomine-shirou-v1.2"],
        "forbidden_statuses": ["draft", "deprecated", "archived"],
        "checks": ["correctness", "timeline_isolation", "temporal", "version", "content_type"],
    },
    {
        "id": "state-maitreya-deceased",
        "story_id": STORY_ID,
        "timeline_id": TIMELINE_ID,
        "query": "弥勒 生命与思潮信号归零 死亡",
        "document_types": ["character_state"],
        "expected_document_ids": ["state-current-maitreya-v1.0"],
        "forbidden_statuses": ["draft", "deprecated", "archived"],
        "checks": ["correctness", "timeline_isolation", "temporal", "version", "content_type"],
    },
    {
        "id": "state-epohonsiereht-main-cannon-overheat",
        "story_id": STORY_ID,
        "timeline_id": TIMELINE_ID,
        "query": "主炮过热 下一次发射时间无法计算",
        "document_types": ["character_state"],
        "expected_document_ids": ["state-current-epohonsiereht-v1.1"],
        "forbidden_document_ids": ["state-current-epohonsiereht-v1.0"],
        "forbidden_statuses": ["draft", "deprecated", "archived"],
        "checks": ["correctness", "timeline_isolation", "temporal", "version", "content_type"],
    },
    {
        "id": "world-state-after-chapter-017",
        "story_id": STORY_ID,
        "timeline_id": TIMELINE_ID,
        "query": "弥勒生命与思潮信号归零",
        "document_types": ["world_state"],
        "expected_document_ids": ["world-state-current-v1.4"],
        "forbidden_document_ids": ["world-state-current-v1.3"],
        "forbidden_statuses": ["draft", "deprecated", "archived"],
        "checks": ["correctness", "timeline_isolation", "temporal", "version", "content_type"],
    },
]


def update_retrieval_tests(history_counts: dict[int, int]) -> None:
    path = RAG / "retrieval-tests.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    tests = data["tests"]
    by_id = {test["id"]: test for test in tests}

    fujimaru = by_id["state-fujimaru-abilities"]
    fujimaru["expected_document_ids"] = ["state-current-fujimaru-ritsuka-v1.4"]
    fujimaru["forbidden_document_ids"] = [
        "state-current-fujimaru-ritsuka-v1.3",
        "state-current-fujimaru-ritsuka-v1.2",
        "state-current-fujimaru-ritsuka-v1.1",
    ]

    qihuang = by_id["state-qihuang-abilities"]
    qihuang["expected_document_ids"] = ["state-current-qihuang-v1.3"]
    qihuang["forbidden_document_ids"] = [
        "state-current-qihuang-v1.2",
        "state-current-qihuang-v1.1",
        "state-current-qihuang-v1.0",
    ]

    amaterasu = by_id["state-amaterasu-after-chapter-014"]
    amaterasu["expected_document_ids"] = ["state-current-amaterasu-no-mikoto-v1.1"]
    amaterasu["forbidden_document_ids"] = ["state-current-amaterasu-no-mikoto-v1.0"]

    muramasa = by_id["state-muramasa-creation-misogi"]
    muramasa["query"] = "右臂大半皮肉烧尽"
    muramasa["expected_document_ids"] = ["state-current-sengo-muramasa-v1.2"]
    muramasa["forbidden_document_ids"] = [
        "state-current-sengo-muramasa-v1.1",
        "state-current-sengo-muramasa-v1.0",
    ]

    # Expected history IDs depend on the deterministic scene split. These assertions make drift explicit.
    assert history_counts == {15: 5, 16: 6, 17: 5}, history_counts
    for case in NEW_RETRIEVAL_TESTS:
        existing = by_id.get(case["id"])
        if existing is None:
            tests.append(case)
            by_id[case["id"]] = case
        else:
            existing.clear()
            existing.update(case)
    write_yaml(path, data)


def main() -> None:
    history = write_history()
    history_counts = {chapter: len(paths) for chapter, paths in history.items()}
    state_ids = snapshot_and_write_states()
    world_id = snapshot_and_write_world()
    update_version_map()
    update_retrieval_tests(history_counts)
    print(
        json.dumps(
            {
                "history_scenes": history_counts,
                "state_documents": len(state_ids),
                "world_document": world_id,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
