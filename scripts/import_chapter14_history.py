from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RAG = ROOT / "novel-rag" / "stories" / "overturned-world-fujimaru"
SOURCE = ROOT / "outputs" / "第四卷_第14章_续写.txt"
HISTORY_DIR = RAG / "history" / "volume-04" / "chapter-014"
SNAPSHOT_DIR = RAG / "character-state" / "snapshots" / "volume-04-chapter-013"
TODAY = "2026-07-17"


SECTIONS = [
    {
        "marker": "第四卷 第十四章 至命之火",
        "label": "东门试探与法相救援",
        "characters": ["yang-zhuo", "gilgamesh", "amaterasu-no-mikoto"],
        "locations": ["izanagi-golden-land-east-gate"],
        "tags": ["天照命", "真炁六水火", "王之财宝", "法相"],
        "start": ["杨浞与吉尔伽美什在东门九层太阳阵地迎战天照命"],
        "end": ["两人确认天照命的多重身份、孔雀卵与法相母子线"],
    },
    {
        "marker": "与此同时，伊耶那岐金地地下第三层",
        "label": "地下故尊复现真相",
        "characters": ["sengo-muramasa", "qihuang", "izanami"],
        "locations": ["izanagi-golden-land-underground"],
        "tags": ["故尊复现", "伊耶娜美", "人格容器", "创造之禊祓"],
        "start": ["千子村正与祁荒抵达地下第三层白墙"],
        "end": ["两人确认伊耶娜美是从冲突记忆中自主活下来的故尊复现个体"],
    },
    {
        "marker": "玛修的盾还保持着横击后的角度。",
        "label": "北侧信标安置与合围",
        "characters": ["fujimaru-ritsuka", "kotomine-shirou", "mash-kyrielight"],
        "locations": ["izanagi-golden-land-north-ritual-road"],
        "tags": ["主炮信标", "法相", "掌中城", "信标自锁"],
        "start": ["藤丸立香、言峰士郎与玛修向主炮信标石台推进"],
        "end": ["主炮信标被安置，三人遭法相与掌中城合围"],
    },
    {
        "marker": "“一群人守一根柱子，还能把自己弄得这么难看。”",
        "label": "Alterego接管信标防守",
        "characters": ["fujimaru-ritsuka", "kotomine-shirou", "mash-kyrielight", "kotomine-shirou-ae", "artoria-pendragon-alter"],
        "locations": ["izanagi-golden-land-north-ritual-road"],
        "tags": ["Alterego", "潘多拉", "神琦灰", "主炮信标"],
        "start": ["信标守卫濒临被掌中城与法相压垮"],
        "end": ["Alterego言峰士郎与阿尔托莉雅接管信标防守，主角组三人撤向东门"],
    },
    {
        "marker": "因为它看见过伊耶那岐创造出的神",
        "label": "创造之禊祓苏醒",
        "characters": ["sengo-muramasa", "qihuang", "izanami"],
        "locations": ["izanagi-golden-land-underground"],
        "tags": ["创造之禊祓", "灼阳之禊祓", "白火", "第三枚黑钉"],
        "start": ["创造之禊祓拒绝完成任何创造"],
        "end": ["千子村正取得创造之禊祓，白火开始洗去弥勒佛印与封锁"],
    },
    {
        "marker": "白火抵达东门时",
        "label": "天照命身份剥离与乌从欲",
        "characters": ["yang-zhuo", "gilgamesh", "amaterasu-no-mikoto", "sengo-muramasa"],
        "locations": ["izanagi-golden-land-east-gate"],
        "tags": ["乌从欲", "修武星", "创造之禊祓", "天照御名"],
        "start": ["创造白火抵达东门并洗去阵地佛印"],
        "end": ["天照命发动乌从欲，黑日收集众生欲望"],
    },
    {
        "marker": "【至命至性并火大圣】，现界。",
        "label": "魔性孔雀现界与英杰之帜",
        "characters": ["yang-zhuo", "gilgamesh", "amaterasu-no-mikoto", "fujimaru-ritsuka", "kotomine-shirou", "mash-kyrielight"],
        "locations": ["izanagi-golden-land-east-gate", "izanagi-golden-land-north-ritual-road"],
        "tags": ["至命至性并火大圣", "至命除", "英杰之帜", "令咒"],
        "start": ["天照命以至命至性并火大圣形态现界"],
        "end": ["藤丸立香消耗一道令咒，令杨浞抵达本体顶峰"],
    },
    {
        "marker": "固有结界内，插在荒原上的铁鞭先立了起来。",
        "label": "开天荒原中的欲望攻防",
        "characters": ["yang-zhuo", "gilgamesh", "amaterasu-no-mikoto"],
        "locations": ["ea-primordial-wasteland-reality-marble"],
        "tags": ["天武真炁神煞真君", "EA", "乌从欲", "天照御名"],
        "start": ["吉尔伽美什以EA展开开天前荒原包裹战场"],
        "end": ["杨浞与吉尔伽美什分别破解乌从欲对欲望的支配"],
    },
    {
        "marker": "这次他叫了全名。",
        "label": "藤丸立香完成天照命降格",
        "characters": ["fujimaru-ritsuka", "kotomine-shirou", "mash-kyrielight", "yang-zhuo", "amaterasu-no-mikoto", "sengo-muramasa", "qihuang"],
        "locations": ["izanagi-golden-land-east-gate", "ea-primordial-wasteland-reality-marble"],
        "tags": ["降格术", "三线衔接", "创造之禊祓", "主炮信标"],
        "start": ["杨浞要求藤丸立香执行降格"],
        "end": ["天照命失去伤势转移、卵中再生与历史复归等不可交战机制"],
    },
    {
        "marker": "灰火只停了一息",
        "label": "切断母子伤害回路",
        "characters": ["yang-zhuo", "gilgamesh", "amaterasu-no-mikoto"],
        "locations": ["ea-primordial-wasteland-reality-marble"],
        "tags": ["食恶开明", "至命除", "母子线", "六十六尊法相"],
        "start": ["降格后的天照命仍保有全部基础力量"],
        "end": ["杨浞与吉尔伽美什切断六十六个孩子替天照命承担伤害的回路"],
    },
    {
        "marker": "天照命的灰日聚至针尖大小",
        "label": "双宝具与EA最终对波",
        "characters": ["yang-zhuo", "gilgamesh", "amaterasu-no-mikoto"],
        "locations": ["ea-primordial-wasteland-reality-marble"],
        "tags": ["问武平清觯", "奉真策玄鞭", "开天辟地乖离之星", "最终对波"],
        "start": ["天照命燃烧自身与保存的失败未来发动灰日"],
        "end": ["天照命主动停止继续燃烧众生命并在三重宝具对波中败北"],
    },
    {
        "marker": "天照命落在最后。",
        "label": "天照命败北后的东门",
        "characters": ["amaterasu-no-mikoto", "yang-zhuo", "gilgamesh"],
        "locations": ["izanagi-golden-land-east-gate"],
        "tags": ["天照命败北", "黑金孔雀", "东门盆地", "太阳权能剥离"],
        "start": ["EA固有结界崩塌，战斗者返回伊耶那岐金地"],
        "end": ["天照命退化为普通大小黑金孔雀，杨浞与吉尔伽美什重伤"],
    },
    {
        "marker": "“也许你们真的能拯救......他们。”",
        "label": "伤员会合与弥勒战续行",
        "characters": ["fujimaru-ritsuka", "kotomine-shirou", "mash-kyrielight", "yang-zhuo", "gilgamesh", "amaterasu-no-mikoto", "sengo-muramasa", "qihuang", "kotomine-shirou-ae", "artoria-pendragon-alter", "maitreya"],
        "locations": ["izanagi-golden-land-east-gate", "izanagi-golden-land-underground", "izanagi-golden-land-north-ritual-road"],
        "tags": ["战后会合", "弥勒未解决", "伤员撤离", "普通日光"],
        "start": ["天照命承认迦勒底或许能够拯救众人"],
        "end": ["主角组准备治疗伤员并继续对弥勒的主炮与降格计划"],
    },
]


def split_paragraphs(text: str, max_chars: int = 2300) -> list[str]:
    paragraphs = [part.strip() for part in re.split(r"\r?\n\r?\n", text.strip()) if part.strip()]
    chunks: list[str] = []
    current: list[str] = []
    current_size = 0
    for paragraph in paragraphs:
        added = len(paragraph) + (2 if current else 0)
        if current and current_size + added > max_chars:
            chunks.append("\n\n".join(current))
            current = [paragraph]
            current_size = len(paragraph)
        else:
            current.append(paragraph)
            current_size += added
    if current:
        chunks.append("\n\n".join(current))
    if len(chunks) > 1 and len(chunks[-1]) < 700:
        tail = chunks.pop()
        chunks[-1] = f"{chunks[-1]}\n\n{tail}"
    return chunks


def section_texts(chapter: str) -> list[tuple[dict, str]]:
    positions: list[int] = []
    for section in SECTIONS:
        position = chapter.find(section["marker"])
        assert position >= 0, f"missing chapter marker: {section['marker']}"
        positions.append(position)
    assert positions == sorted(positions) and len(set(positions)) == len(positions)
    values: list[tuple[dict, str]] = []
    for index, section in enumerate(SECTIONS):
        end = positions[index + 1] if index + 1 < len(positions) else len(chapter)
        values.append((section, chapter[positions[index]:end].strip()))
    return values


def write_history() -> list[Path]:
    chapter = SOURCE.read_text(encoding="utf-8").strip()
    assert chapter.startswith("第四卷 第十四章 至命之火")
    records: list[tuple[dict, str]] = []
    for section, text in section_texts(chapter):
        for chunk in split_paragraphs(text):
            records.append((section, chunk))

    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    expected_names = {f"scene-{index:03d}.yaml" for index in range(1, len(records) + 1)}
    for old_path in HISTORY_DIR.glob("scene-*.yaml"):
        assert old_path.name in expected_names, f"unexpected existing history file: {old_path}"

    paths: list[Path] = []
    for index, (section, content) in enumerate(records, start=1):
        document_id = f"history-v04-c014-s{index:03d}-v1.0"
        previous_scene = "history-v04-c013-s007-v1.0" if index == 1 else f"history-v04-c014-s{index - 1:03d}-v1.0"
        next_scene = None if index == len(records) else f"history-v04-c014-s{index + 1:03d}-v1.0"
        document = {
            "metadata": {
                "document_id": document_id,
                "story_id": "overturned-world-fujimaru",
                "timeline_id": "main",
                "document_type": "history",
                "title": f"第四卷 第14章 至命之火 场景{index}：{section['label']}",
                "volume": 4,
                "chapter": 14,
                "scene": index,
                "pov_character": "多视角",
                "character_ids": section["characters"],
                "location_ids": section["locations"],
                "event_tags": ["日本下篇", "至命之火", *section["tags"]],
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
                "source_file": str(SOURCE),
            },
            "content": content,
        }
        path = HISTORY_DIR / f"scene-{index:03d}.yaml"
        path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        paths.append(path)

    joined = "\n\n".join(json.loads(path.read_text(encoding="utf-8"))["content"] for path in paths)
    assert joined == chapter, "history chunks do not reconstruct the source chapter"
    return paths


def snapshot_current_states() -> list[Path]:
    current_dir = RAG / "character-state" / "current"
    names = (
        "fujimaru-ritsuka",
        "yang-zhuo",
        "gilgamesh",
        "sengo-muramasa",
        "qihuang",
        "kotomine-shirou",
        "mash-kyrielight",
        "izanami",
    )
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    outputs: list[Path] = []
    for name in names:
        source = current_dir / f"{name}.yaml"
        text = source.read_text(encoding="utf-8")
        if text.lstrip().startswith("{"):
            existing = sorted(SNAPSHOT_DIR.glob(f"{name}-v*.yaml"))
            assert existing, f"missing pre-chapter-014 snapshot for {name}"
            outputs.append(existing[-1])
            continue
        match = re.search(r"(?m)^  version: '([^']+)'\s*$", text)
        assert match, f"missing version in {source}"
        version = match.group(1)
        target = SNAPSHOT_DIR / f"{name}-v{version}.yaml"
        snapshot = text.replace("  snapshot_type: current\n", "  snapshot_type: snapshot\n", 1)
        snapshot = snapshot.replace("  status: active\n", "  status: archived\n", 1)
        snapshot = re.sub(
            r"(?m)^  title: (.+)$",
            lambda value: f"  title: 第四卷第13章末状态快照-{value.group(1).removeprefix('当前状态-')}",
            snapshot,
            count=1,
        )
        target.write_text(snapshot, encoding="utf-8", newline="\n")
        outputs.append(target)
    return outputs


def snapshot_world_state() -> Path:
    source = RAG / "world-state" / "current" / "current.yaml"
    text = source.read_text(encoding="utf-8")
    target = RAG / "world-state" / "change-logs" / "volume-04-chapter-013-pre-chapter-014.yaml"
    if text.lstrip().startswith("{"):
        assert target.exists(), "missing pre-chapter-014 world-state snapshot"
        return target
    snapshot = text.replace("  status: active\n", "  status: archived\n", 1)
    snapshot = re.sub(
        r"(?m)^  title: .+$",
        "  title: 第四卷第13章末世界状态快照",
        snapshot,
        count=1,
    )
    target.write_text(snapshot, encoding="utf-8", newline="\n")
    return target


def main() -> None:
    history = write_history()
    snapshots = snapshot_current_states()
    world_snapshot = snapshot_world_state()
    sizes = [len(json.loads(path.read_text(encoding="utf-8"))["content"]) for path in history]
    print(
        f"history_scenes={len(history)} min_chars={min(sizes)} max_chars={max(sizes)} "
        f"state_snapshots={len(snapshots)} world_snapshot={world_snapshot.name}"
    )


if __name__ == "__main__":
    main()
