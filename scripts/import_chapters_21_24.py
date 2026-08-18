from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]
LIBRARY = ROOT / "novel-rag"
STORY_ID = "overturned-world-fujimaru"
STORY = LIBRARY / "stories" / STORY_ID
STATE_ROOT = STORY / "character-state"
SOURCE = ROOT / "outputs" / "第四卷_第21-24章_日本卷收尾.txt"
DATE = "2026-08-08"


def load(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected mapping: {path}")
    return value


def dump(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(value, allow_unicode=True, sort_keys=False, width=120),
        encoding="utf-8",
    )


def split_at(text: str, markers: list[str]) -> list[str]:
    positions = [0]
    for marker in markers:
        position = text.find(marker)
        if position < 0:
            raise ValueError(f"split marker missing: {marker}")
        positions.append(position)
    positions.append(len(text))
    return [text[positions[index] : positions[index + 1]].strip() for index in range(len(positions) - 1)]


def split_chapters(text: str) -> dict[int, str]:
    headings = {
        21: "第二十一章　休止符",
        22: "第二十二章　没有回应的名字",
        23: "第二十三章　不能改掉的人",
        24: "第二十四章　炉火应召",
    }
    positions = {chapter: text.index(heading) for chapter, heading in headings.items()}
    chapters: dict[int, str] = {}
    for chapter in headings:
        end = positions.get(chapter + 1, len(text))
        chapters[chapter] = text[positions[chapter] : end].strip()
    return chapters


def write_history() -> list[str]:
    if (STORY / "history" / "volume-04" / "chapter-024" / "scene-005.yaml").exists():
        raise RuntimeError("chapters 21-24 are already imported")

    specs: dict[int, dict[str, Any]] = {
        21: {
            "title": "休止符",
            "markers": ["管制室里比平时少了一半席位。", "通告结束后，立香没有马上离开。"],
            "scene_titles": [
                "回归一天后的医疗复查／失联名单",
                "第一特异点修复公告／休整令与未归记录",
                "纯人理召唤测试获准",
            ],
            "characters": [
                ["fujimaru-ritsuka", "mash-kyrielight", "leonardo-da-vinci"],
                ["fujimaru-ritsuka", "mash-kyrielight", "kotomine-shirou", "olga-marie-animusphere", "gilgamesh", "yang-zhuo", "qihuang", "sengo-muramasa"],
                ["fujimaru-ritsuka", "mash-kyrielight", "kotomine-shirou", "olga-marie-animusphere", "leonardo-da-vinci"],
            ],
            "locations": [["chaldea"], ["chaldea"], ["chaldea"]],
            "tags": [
                ["从者快速恢复", "失联名单", "回归休整"],
                ["第一特异点修复完成", "休整期", "杨浞失联", "祁荒未归", "千子村正未归"],
                ["人理支援验证", "英灵召唤计划", "无触媒"],
            ],
        },
        22: {
            "title": "没有回应的名字",
            "markers": ["方案由达·芬奇写了大半。", "下午两点，达·芬奇在召唤室门口收走方案。"],
            "scene_titles": [
                "休息日早餐／三人恢复",
                "无触媒召唤方案／观察室待命",
                "召唤室检查／立香约士郎夜谈",
            ],
            "characters": [
                ["fujimaru-ritsuka", "mash-kyrielight", "kotomine-shirou"],
                ["fujimaru-ritsuka", "mash-kyrielight", "kotomine-shirou"],
                ["fujimaru-ritsuka", "mash-kyrielight", "kotomine-shirou", "leonardo-da-vinci"],
            ],
            "locations": [["chaldea"], ["chaldea"], ["chaldea"]],
            "tags": [
                ["休整日", "从者伤势快速恢复", "日常"],
                ["纯人理召唤", "无触媒", "人理支援验证"],
                ["召唤室", "契约不切断", "夜谈邀约"],
            ],
        },
        23: {
            "title": "不能改掉的人",
            "markers": ["“我有时候会想，”立香说", "立香又亲了他一次"],
            "scene_titles": [
                "第二次谈心／是否改变过去",
                "立香告白／士郎确认相伴",
                "接吻后确认关系／约定同行",
            ],
            "characters": [
                ["fujimaru-ritsuka", "kotomine-shirou"],
                ["fujimaru-ritsuka", "kotomine-shirou"],
                ["fujimaru-ritsuka", "kotomine-shirou", "mash-kyrielight"],
            ],
            "locations": [["chaldea"], ["chaldea"], ["chaldea"]],
            "tags": [
                ["过去不可替代", "身份连续性", "关系谈心"],
                ["立香倾慕士郎", "相互告白", "确认关系", "接吻"],
                ["恋人", "继续同行", "召唤前夜"],
            ],
        },
        24: {
            "title": "炉火应召",
            "markers": [
                "观察室门打开。奥尔加玛丽独自走进召唤室。",
                "就在鞋底越过内环时，黑痕里响了一声。",
                "空间闭合。",
                "契约闭合。",
            ],
            "scene_titles": [
                "三次供能／人理无直接响应",
                "奥尔加玛丽确认立香仍是迦勒底御主",
                "跨界召唤响应／村正进入迦勒底／祁荒留在门后",
                "村正记忆与人格连续性验证／缔结契约",
                "灵基快速修复／祁荒路径待重建／日本卷收尾",
            ],
            "characters": [
                ["fujimaru-ritsuka", "mash-kyrielight", "kotomine-shirou", "olga-marie-animusphere", "leonardo-da-vinci"],
                ["fujimaru-ritsuka", "mash-kyrielight", "kotomine-shirou", "olga-marie-animusphere"],
                ["fujimaru-ritsuka", "mash-kyrielight", "kotomine-shirou", "qihuang", "sengo-muramasa", "olga-marie-animusphere", "leonardo-da-vinci"],
                ["fujimaru-ritsuka", "mash-kyrielight", "kotomine-shirou", "qihuang", "sengo-muramasa", "olga-marie-animusphere", "leonardo-da-vinci"],
                ["fujimaru-ritsuka", "mash-kyrielight", "kotomine-shirou", "qihuang", "sengo-muramasa", "olga-marie-animusphere"],
            ],
            "locations": [["chaldea"], ["chaldea"], ["chaldea", "cross-world-coordinate"], ["chaldea", "cross-world-coordinate"], ["chaldea"]],
            "tags": [
                ["召唤失败", "人理直接支援未恢复", "无触媒"],
                ["迦勒底核心御主", "奥尔加玛丽", "队伍确认"],
                ["跨界响应", "千子村正归队", "祁荒仍未归队", "路径锚点"],
                ["同一村正", "人格连续性", "日本记忆保留", "Saber契约"],
                ["从者快速恢复", "祁荒路径待重建", "日本卷收尾"],
            ],
        },
    }

    chapters = split_chapters(SOURCE.read_text(encoding="utf-8"))
    documents: list[tuple[Path, dict[str, Any]]] = []
    for chapter, spec in specs.items():
        parts = split_at(chapters[chapter], spec["markers"])
        for scene, content in enumerate(parts, start=1):
            document_id = f"history-v04-c{chapter:03d}-s{scene:03d}-v1.0"
            metadata = {
                "document_id": document_id,
                "story_id": STORY_ID,
                "timeline_id": "main",
                "document_type": "history",
                "title": f"第四卷 第{chapter}章 {spec['title']} 场景{scene}：{spec['scene_titles'][scene - 1]}",
                "volume": 4,
                "chapter": chapter,
                "scene": scene,
                "pov_character": "藤丸立香／多视角",
                "character_ids": spec["characters"][scene - 1],
                "location_ids": spec["locations"][scene - 1],
                "event_tags": ["日本卷收尾", spec["title"], *spec["tags"][scene - 1]],
                "start_state": [content.split("\n\n", 1)[0]],
                "end_state": [content.rsplit("\n\n", 1)[-1]],
                "previous_scene": None,
                "next_scene": None,
                "version": "1.0",
                "status": "canon",
                "canon_scope": "timeline",
                "created_at": DATE,
                "updated_at": DATE,
                "supersedes": None,
                "source_file": str(SOURCE),
            }
            path = STORY / "history" / "volume-04" / f"chapter-{chapter:03d}" / f"scene-{scene:03d}.yaml"
            documents.append((path, {"metadata": metadata, "content": content}))

    for index, (_, document) in enumerate(documents):
        metadata = document["metadata"]
        metadata["previous_scene"] = "history-v04-c020-s004-v1.0" if index == 0 else documents[index - 1][1]["metadata"]["document_id"]
        metadata["next_scene"] = None if index == len(documents) - 1 else documents[index + 1][1]["metadata"]["document_id"]
    for path, document in documents:
        dump(path, document)

    previous_path = STORY / "history" / "volume-04" / "chapter-020" / "scene-004.yaml"
    previous = load(previous_path)
    previous["metadata"]["next_scene"] = documents[0][1]["metadata"]["document_id"]
    previous["metadata"]["updated_at"] = DATE
    dump(previous_path, previous)
    return [document["metadata"]["document_id"] for _, document in documents]


def relationship(
    target: str,
    kind: str,
    attitude: str,
    recent: str,
    unresolved: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "target_character": target,
        "relationship_type": kind,
        "trust": "高",
        "dependence": "长期同行与战斗协作",
        "hostility": "无",
        "current_attitude": attitude,
        "unresolved_issues": unresolved or [],
        "recent_change": recent,
    }


def state_body(
    *,
    location: str,
    companions: list[str],
    faction: str,
    health: str,
    injuries: list[str],
    fatigue: str,
    emotions: list[str],
    pressures: list[str],
    desires: list[str],
    known: list[str],
    unknown: list[str],
    immediate: list[str],
    short_term: list[str],
    long_term: list[str],
    priorities: list[str],
    obstacles: list[str],
    relationships: list[dict[str, Any]],
    available: list[str],
    unavailable: list[str],
    acquired: list[str],
    consumed: list[str],
    costs: list[str],
    carried: list[str],
    lost: list[str],
    damaged: list[str],
    arc: str,
    completed: list[str],
    unresolved: list[str],
    promises: list[str],
    pressure: list[str],
) -> dict[str, Any]:
    return {
        "current_position": {"location": location, "companions": companions, "faction": faction},
        "physical": {"health": health, "injuries": injuries, "fatigue": fatigue, "temporary_conditions": [], "permanent_changes": []},
        "mental": {"dominant_emotions": emotions, "current_pressure": pressures, "desires": desires, "fears": [], "unresolved_conflicts": [], "behavior_effects": []},
        "knowledge": {"known": known, "unknown": unknown, "mistaken_beliefs": [], "suspicions": [], "secrets_held": []},
        "goals": {"immediate": immediate, "short_term": short_term, "long_term": long_term, "priorities": priorities, "obstacles": obstacles},
        "relationships": relationships,
        "abilities": {"available": available, "unavailable": unavailable, "newly_acquired": acquired, "consumed_resources": consumed, "active_costs": costs},
        "inventory": {"carried": carried, "lost": lost, "damaged": damaged},
        "narrative": {"current_arc": arc, "completed_changes": completed, "unresolved_flags": unresolved, "active_promises": promises, "future_pressure": pressure},
    }


STATE_BODIES: dict[str, dict[str, Any]] = {
    "fujimaru-ritsuka": state_body(
        location="迦勒底休整区与检查室",
        companions=["玛修·基列莱特", "言峰士郎", "千子村正"],
        faction="迦勒底",
        health="人类躯体仍在恢复，能够正常行动",
        injuries=["掌心伤口已包扎", "脸侧旧伤闭合", "三道令咒仍为耗尽状态"],
        fatigue="日本终战后的疲劳明显缓解",
        emotions=["安心", "警觉", "对后续道路的决意"],
        pressures=["人理直接召唤支援仍未确认", "祁荒仍未返回迦勒底", "杨浞仍失联"],
        desires=["恢复祁荒坐标路径", "准备下一处特异点", "与士郎继续同行"],
        known=["第一特异点修复完成，迦勒底进入休整期", "标准英灵召唤未得到人理直接响应", "日本特异点的千子村正本人经跨界响应返回并保留记忆与人格", "祁荒在召唤门闭合前仍存活且没有返回迦勒底", "自己与言峰士郎已相互告白并确认恋人关系"],
        unknown=["人理不直接支援迦勒底的原因", "祁荒当前完整坐标与回收方法", "杨浞是否存在可恢复残留", "卫宫白与神琦灰对峙结果"],
        immediate=["完成休整与契约稳定", "保存祁荒路径锚点"],
        short_term=["调查人理支援异常", "准备下一处特异点"],
        long_term=["继续修复人理并守住同行者"],
        priorities=["同伴生存", "路径恢复", "人理修复"],
        obstacles=["令咒耗尽", "人理直接召唤无响应", "跨界路径不稳定"],
        relationships=[
            relationship("mash-kyrielight", "前辈与后辈／御主与从者", "接受玛修照顾并继续共同出战", "日本终战后共同休整"),
            relationship("kotomine-shirou", "恋人／御主与从者", "明确倾慕并允许对方长期留在身边", "第二次谈心后相互告白、接吻并确认关系"),
            relationship("sengo-muramasa", "御主与从者", "确认她是日本特异点同一人格并接纳其归队", "以跨界响应完成Saber契约"),
        ],
        available=["降格术"],
        unavailable=["英杰之帜（令咒耗尽，当前不可发动）"],
        acquired=["千子村正的Saber契约"],
        consumed=[],
        costs=["令咒归零"],
        carried=[],
        lost=[],
        damaged=[],
        arc="日本卷收尾：休整、新关系与跨界召唤",
        completed=["确认第一特异点修复完成", "与言峰士郎确认恋人关系", "召回日本特异点的千子村正本人"],
        unresolved=["人理直接支援异常", "祁荒仍未归队", "杨浞失联", "卫宫白与神琦灰对峙结果"],
        promises=["与言峰士郎继续同行", "不丢失祁荒留下的坐标"],
        pressure=["下一处特异点出现前需要恢复队伍与召唤能力"],
    ),
    "mash-kyrielight": state_body(
        location="迦勒底休整区与检查室",
        companions=["藤丸立香", "言峰士郎", "千子村正"],
        faction="迦勒底",
        health="从者灵基伤势已快速恢复，能够正常行动",
        injuries=[],
        fatigue="终战疲劳已明显缓解",
        emotions=["安心", "关切", "期待"],
        pressures=["圆桌之盾与外骨骼仍在维修", "祁荒仍未归队"],
        desires=["陪伴立香休整并准备下一次行动"],
        known=["第一特异点修复完成", "人理没有直接响应标准英灵召唤", "千子村正以日本特异点同一人格返回", "祁荒仍在跨界坐标另一端", "立香与士郎已经确认关系"],
        unknown=["祁荒回收路径", "人理支援异常原因", "杨浞是否存在残留"],
        immediate=["完成盾与外骨骼维修"],
        short_term=["协助恢复祁荒路径", "准备下一特异点"],
        long_term=["继续保护藤丸立香并修复人理"],
        priorities=["前辈安全", "队伍恢复"],
        obstacles=["圆桌之盾尚在维修"],
        relationships=[relationship("fujimaru-ritsuka", "后辈与前辈／从者与御主", "继续照顾前辈并尊重其关系选择", "陪同完成召唤测试与村正归队")],
        available=["圆桌之盾（待完成维修）", "多功能武装（待完成维修）"],
        unavailable=[],
        acquired=[],
        consumed=[],
        costs=[],
        carried=[],
        lost=[],
        damaged=["圆桌之盾与外骨骼仍在维修"],
        arc="日本卷收尾：休整与队伍重组",
        completed=["灵基伤势快速恢复", "陪同纯人理召唤测试", "迎接千子村正归队"],
        unresolved=["盾与外骨骼维修", "祁荒回收路径"],
        promises=[],
        pressure=["下一处特异点可能随时被观测"],
    ),
    "kotomine-shirou": state_body(
        location="迦勒底休整区与检查室",
        companions=["藤丸立香", "玛修·基列莱特", "千子村正"],
        faction="迦勒底",
        health="拟造躯壳已快速修复主要伤势，能够正常行动",
        injuries=["耳后留有闭合的新痕", "右侧投影回路用力时偶有刺痛"],
        fatigue="终战疲劳已明显缓解",
        emotions=["安心", "坚定", "亲近"],
        pressures=["人理直接召唤无响应", "祁荒仍未归队"],
        desires=["留在立香身边并继续同行", "协助恢复未归同伴路径"],
        known=["过去是自身人格不可分割的一部分，全部改写等于杀死现在的自己", "第一特异点修复完成", "千子村正以同一人格与日本记忆返回", "立香倾慕自己并与自己确认恋人关系"],
        unknown=["无名大戟原主身份、完整来历与力量原理", "人理支援异常原因", "卫宫白与自己相似的原因", "祁荒当前坐标", "Alterego与阿尔托莉雅后续"],
        immediate=["陪伴立香休整", "完成回路复查"],
        short_term=["准备下一处特异点", "协助寻找祁荒"],
        long_term=["在立香身边继续修复人理"],
        priorities=["立香安全", "同伴归队"],
        obstacles=["人理支援异常", "跨界路径不稳定"],
        relationships=[relationship("fujimaru-ritsuka", "恋人／从者与御主", "明确喜欢立香并承诺一直留在她身边", "第二次谈心后相互告白、接吻并确认关系")],
        available=["拟造躯壳", "投影魔术"],
        unavailable=[],
        acquired=[],
        consumed=[],
        costs=["右侧投影回路仍需恢复"],
        carried=["纸星星复制品"],
        lost=[],
        damaged=[],
        arc="日本卷收尾：确认自我与恋人关系",
        completed=["拒绝以改写过去替换现在的自我", "与藤丸立香相互告白并确认恋人关系", "见证千子村正归队"],
        unresolved=["人理支援异常", "祁荒仍未归队", "卫宫白身份"],
        promises=["只要立香继续前进便留在她身边", "立香做错时会阻止她"],
        pressure=["必须在下一次行动前恢复投影回路稳定性"],
    ),
    "sengo-muramasa": state_body(
        location="迦勒底检查室；已完成跨界召唤归队",
        companions=["藤丸立香", "玛修·基列莱特", "言峰士郎"],
        faction="迦勒底／藤丸立香契约从者",
        health="得到迦勒底供魔后灵基伤势迅速修复，能够正常行动",
        injuries=["右掌与胸前保留淡色旧痕"],
        fatigue="跨界移动与召唤后的疲劳正在恢复",
        emotions=["务实", "安心", "担忧祁荒"],
        pressures=["祁荒仍留在跨界坐标另一端", "工房尚未安排"],
        desires=["完成检查并取得工房", "与迦勒底重建祁荒路径"],
        known=["自己就是日本特异点中行动至终局的千子村正本人", "日本特异点记忆与人格连续性完整保留", "祁荒用金刚杵与净瓶维持召唤路径并将自己送入迦勒底", "人理标准召唤没有直接响应立香"],
        unknown=["门闭合后祁荒的完整状态", "跨界路径重新开启方法", "卫宫白与神琦灰对峙结果"],
        immediate=["完成灵基检查", "取得锻造工房"],
        short_term=["协助解析白火切口与祁荒路径锚点"],
        long_term=["作为立香的Saber继续锻刀与开路"],
        priorities=["祁荒回收", "工房", "下一次行动"],
        obstacles=["跨界路径已经闭合", "断刀与衣甲未随灵基复原"],
        relationships=[
            relationship("fujimaru-ritsuka", "从者与御主", "认可立香为御主并愿继续替她锻刀开路", "主动响应呼唤并完成Saber契约"),
            relationship("qihuang", "跨界同行者", "确认祁荒仍在门后并要求迦勒底保存坐标", "由祁荒钉住路径送入迦勒底", ["祁荒尚未归队"]),
            relationship("kotomine-shirou", "并肩作战者", "恢复嘴硬互损的协作关系", "归队后确认士郎伤势已快速恢复"),
        ],
        available=["锻刀", "创造之禊祓残余回路"],
        unavailable=[],
        acquired=["藤丸立香的Saber契约"],
        consumed=[],
        costs=["跨界召唤消耗", "白火路径暂时闭合"],
        carried=["断刀", "受损刀鞘"],
        lost=[],
        damaged=["断刀与衣甲未随灵基复原"],
        arc="日本卷收尾：同一人格跨界归队",
        completed=["未随第20章灵子转移返回", "沿立香召唤请求跨界进入迦勒底", "通过灵基、记忆与人格连续性验证", "与立香缔结Saber契约", "灵基伤势快速修复"],
        unresolved=["祁荒仍未归队", "跨界路径重建", "工房安排"],
        promises=["作为Saber继续为立香锻刀与开路"],
        pressure=["需要利用白火切口协助迦勒底找回祁荒"],
    ),
    "qihuang": state_body(
        location="跨界坐标残痕另一端；仍未返回迦勒底，路径待重建",
        companions=[],
        faction="迦勒底协同行动方",
        health="召唤门闭合前生命反应存在，后续状态未确认",
        injuries=["双手裂伤", "杨枝净瓶贯穿性裂纹"],
        fatigue="持续以金刚杵和净瓶维持跨界坐标",
        emotions=["坚持", "从容", "警觉"],
        pressures=["独自留在跨界坐标另一端", "石台与路径不稳定"],
        desires=["让村正成功进入迦勒底", "维持自身与迦勒底可重建的路径"],
        known=["千子村正已沿召唤路径进入迦勒底", "迦勒底记录了万花筒残痕、金刚杵坐标和白火路径锚点", "自己仍未返回迦勒底"],
        unknown=["门闭合后的路径稳定时间", "迦勒底何时能够重新开启跨界门", "卫宫白与神琦灰对峙结果"],
        immediate=["稳定金刚杵与破损净瓶", "避免随石台坠入乱流"],
        short_term=["等待或协助迦勒底重建路径"],
        long_term=["返回迦勒底并处理净瓶内佛果"],
        priorities=["自身生存", "坐标维持", "与迦勒底重联"],
        obstacles=["跨界门闭合", "独自滞留", "净瓶破损"],
        relationships=[relationship("sengo-muramasa", "跨界同行者", "将村正送入召唤阵并留在门后维持路径", "确认村正成功返回迦勒底", ["自身尚未归队"])],
        available=["文明侵蚀", "阵地建造", "寻声救苦", "此世全部之欲", "金刚杵", "杨枝净瓶"],
        unavailable=[],
        acquired=[],
        consumed=[],
        costs=["金刚杵持续承压", "杨枝净瓶破裂"],
        carried=["金刚杵", "开裂的杨枝净瓶（内有金色佛果）"],
        lost=[],
        damaged=["杨枝净瓶出现贯穿性裂纹"],
        arc="日本卷收尾：独留跨界坐标",
        completed=["与村正在跨界乱流中存活", "钉住召唤路径并将村正送入迦勒底", "向立香留下下次见的约定"],
        unresolved=["仍未返回迦勒底", "完整世界坐标", "跨界路径重建", "净瓶内佛果"],
        promises=["下次见"],
        pressure=["召唤门已经闭合，当前只能依赖迦勒底保存的路径锚点"],
    ),
}


def bump_version(value: str) -> str:
    major, minor = value.split(".", 1)
    return f"{major}.{int(minor) + 1}"


def write_states() -> dict[str, str]:
    current_ids: dict[str, str] = {}
    snapshot_dir = STATE_ROOT / "snapshots" / "volume-04-chapter-024"
    change_dir = STATE_ROOT / "change-logs" / "volume-04-chapter-024"
    for character_id, body in STATE_BODIES.items():
        current_path = STATE_ROOT / "current" / f"{character_id}.yaml"
        old = load(current_path)
        old_metadata = old["metadata"]
        old_id = str(old_metadata["document_id"])
        old_version = str(old_metadata["version"])
        new_version = bump_version(old_version)
        new_id = f"state-current-{character_id}-v{new_version}"

        snapshot = deepcopy(old)
        snapshot["metadata"].update({
            "title": f"第四卷第20章末状态快照-{old_metadata['title'].removeprefix('当前状态-')}",
            "snapshot_type": "snapshot",
            "status": "archived",
        })
        dump(snapshot_dir / f"{character_id}-v{old_version}.yaml", snapshot)

        new_document = deepcopy(old)
        new_document["metadata"].update({
            "document_id": new_id,
            "snapshot_type": "current",
            "effective_at": "volume-04-chapter-024",
            "last_updated": DATE,
            "version": new_version,
            "status": "active",
            "supersedes": old_id,
            "source_file": str(SOURCE),
        })
        new_document["character_state"] = body
        dump(current_path, new_document)

        change = {
            "metadata": {
                "document_id": f"state-change-{character_id}-v04-c024-v1.0",
                "story_id": STORY_ID,
                "timeline_id": "main",
                "document_type": "character_state",
                "title": f"第4卷第21至24章状态变化-{old_metadata['title'].removeprefix('当前状态-')}",
                "character_id": old_metadata["character_id"],
                "variant_id": old_metadata["variant_id"],
                "snapshot_type": "change_log",
                "effective_at": "volume-04-chapter-024",
                "last_updated": DATE,
                "version": "1.0",
                "status": "canon",
                "supersedes": None,
                "source_file": str(SOURCE),
            },
            "changes": [{
                "category": "chapter_21_to_24_outcome",
                "before": old_id,
                "after": new_id,
                "cause": "第四卷第21至24章休整、关系确认、召唤验证与村正跨界归队",
                "evidence": "history-v04-c021-to-c024",
            }],
        }
        dump(change_dir / f"{character_id}.yaml", change)
        current_ids[character_id] = new_id
    return current_ids


def write_world_state() -> str:
    path = STORY / "world-state" / "current" / "current.yaml"
    old = load(path)
    old_id = str(old["metadata"]["document_id"])
    snapshot = deepcopy(old)
    snapshot["metadata"]["status"] = "archived"
    dump(STORY / "world-state" / "change-logs" / "volume-04-chapter-024-snapshot.yaml", snapshot)

    new_id = "world-state-current-v1.6"
    world = {
        "metadata": {
            "document_id": new_id,
            "story_id": STORY_ID,
            "timeline_id": "main",
            "document_type": "world_state",
            "title": "第四卷第24章后世界状态",
            "version": "1.6",
            "status": "active",
            "effective_at": "volume-04-chapter-024",
            "supersedes": old_id,
            "source_file": str(SOURCE),
            "updated_at": DATE,
        },
        "world_state": {
            "timeline_position": "第四卷第24章末，日本卷收尾，迦勒底进入下一特异点出现前的休整期",
            "locations": [
                {"location_id": "chaldea", "current_condition": "第一特异点修复完成；从者主要伤势已快速恢复；千子村正经跨界响应归队", "controlling_faction": "迦勒底", "accessibility": "正常", "known_hazards": ["人理直接召唤支援仍未确认"], "recent_events": ["发布休整令", "标准召唤无直接响应", "千子村正缔结Saber契约"]},
                {"location_id": "cross-world-coordinate", "current_condition": "祁荒独自留在召唤门另一端，召唤闭合前生命反应存在", "controlling_faction": "未确认", "accessibility": "路径已闭合，迦勒底保存万花筒残痕、金刚杵坐标与白火锚点", "known_hazards": ["世界乱流", "石台不稳定", "路径闭合"], "recent_events": ["祁荒将千子村正送入迦勒底召唤阵", "搜索状态改为路径待重建"]},
                {"location_id": "restored-japan", "current_condition": "第一特异点已完成修复并归还原有时代", "controlling_faction": "原有人理", "accessibility": "迦勒底当前无异常坐标入口", "known_hazards": [], "recent_events": ["日本特异点正式归档"]},
            ],
            "factions": [{
                "faction_id": "chaldea",
                "current_goal": "休整、调查人理支援异常、重建祁荒路径并等待下一特异点",
                "leadership": "奥尔加玛丽负责迦勒底运行；藤丸立香为核心御主",
                "alliances": ["千子村正（新缔结Saber契约）"],
                "enemies": ["神琦灰"],
                "known_information": ["第一特异点修复完成", "人理没有直接响应标准英灵召唤", "千子村正本人保留日本记忆与人格归队", "祁荒仍未返回迦勒底且路径待重建"],
                "resources": ["已回收圣杯（封存）", "千子村正的Saber契约", "祁荒跨界路径锚点"],
                "recent_changes": ["进入休整期", "队伍新增归队的千子村正", "祁荒搜索由无法定位改为路径待重建"],
            }],
            "global_events": ["弥勒生命与思潮信号归零", "第一特异点修复完成", "迦勒底进入休整期", "标准英灵召唤未得到人理直接响应", "千子村正以日本特异点同一人格跨界归队并缔结契约"],
            "public_knowledge": ["迦勒底第一特异点修复完成", "千子村正作为Saber加入迦勒底"],
            "hidden_world_changes": ["人理不直接支援迦勒底的原因仍未知", "祁荒仍独自留在跨界坐标另一端", "卫宫白与神琦灰对峙结果仍未知"],
            "unresolved_world_flags": ["人理直接召唤支援异常", "祁荒路径重建", "杨浞是否存在可恢复残留", "卫宫白与神琦灰对峙结果", "Alterego言峰士郎与阿尔托莉雅后续"],
        },
    }
    dump(path, world)
    return new_id


def update_registries(current_ids: dict[str, str], world_id: str) -> None:
    stories_path = LIBRARY / "registry" / "stories.yaml"
    stories = load(stories_path)
    for row in stories.get("stories", []):
        if row.get("story_id") == STORY_ID:
            row["current_volume"] = 4
            row["current_chapter"] = 24
    dump(stories_path, stories)

    version_path = STORY / "registry" / "version-map.yaml"
    version_map = load(version_path)
    rows = version_map.setdefault("versions", [])
    by_family = {str(row.get("document_family")): row for row in rows}
    for character_id, current_id in current_ids.items():
        family = f"state-current-{character_id}"
        row = by_family[family]
        previous = str(row["current"])
        supersedes = row.setdefault("supersedes", [])
        if previous not in supersedes:
            supersedes.insert(0, previous)
        row["current"] = current_id
        row["reason"] = "回写第四卷第21至24章后的休整、关系确认、村正跨界归队与祁荒路径待重建状态"

    world_row = by_family["world-state-current"]
    previous_world = str(world_row["current"])
    if previous_world not in world_row.setdefault("supersedes", []):
        world_row["supersedes"].insert(0, previous_world)
    world_row["current"] = world_id
    world_row["reason"] = "回写第四卷第21至24章后的第一特异点归档、休整期、人理召唤异常与村正跨界归队"
    dump(version_path, version_map)


def test_case(
    case_id: str,
    query: str,
    document_type: str,
    expected: str,
    forbidden: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "id": case_id,
        "story_id": STORY_ID,
        "timeline_id": "main",
        "query": query,
        "document_types": [document_type],
        "expected_document_ids": [expected],
        "forbidden_document_ids": forbidden or [],
        "forbidden_statuses": ["draft", "deprecated", "archived"],
        "checks": ["correctness", "temporal", "version", "content_type"],
    }


def update_retrieval_tests(current_ids: dict[str, str], world_id: str) -> None:
    path = STORY / "retrieval-tests.yaml"
    data = load(path)
    tests = data.setdefault("tests", [])
    old_to_new = {
        "state-current-fujimaru-ritsuka-v1.5": current_ids["fujimaru-ritsuka"],
        "state-current-mash-kyrielight-v1.4": current_ids["mash-kyrielight"],
        "state-current-kotomine-shirou-v1.4": current_ids["kotomine-shirou"],
        "state-current-sengo-muramasa-v1.3": current_ids["sengo-muramasa"],
        "state-current-qihuang-v1.4": current_ids["qihuang"],
        "world-state-current-v1.5": world_id,
    }

    filtered: list[dict[str, Any]] = []
    for row in tests:
        if row.get("id") == "state-muramasa-not-returned-chapter-020":
            continue
        expected_ids = row.get("expected_document_ids", [])
        for old_id, new_id in old_to_new.items():
            if old_id in expected_ids:
                row["expected_document_ids"] = [new_id if value == old_id else value for value in expected_ids]
                forbidden_ids = row.setdefault("forbidden_document_ids", [])
                if old_id not in forbidden_ids:
                    forbidden_ids.insert(0, old_id)
        if row.get("id") == "state-muramasa-creation-yanagi-no-misogi" or row.get("query") == "右臂大半皮肉烧尽":
            row["query"] = "日本特异点记忆与人格连续性完整保留"
        if row.get("id") == "state-qihuang-not-returned-chapter-020":
            row["query"] = "仍未返回迦勒底 路径待重建"
        if row.get("id") == "world-state-after-chapter-020":
            row["id"] = "world-state-after-chapter-024"
            row["query"] = "人理直接召唤支援仍未确认"
        filtered.append(row)

    additions = [
        test_case("history-chapter-021-first-singularity-rest", "第一特异点修复完成", "history", "history-v04-c021-s002-v1.0"),
        test_case("history-chapter-023-ritsuka-shirou-confession", "我也喜欢你", "history", "history-v04-c023-s002-v1.0"),
        test_case("history-chapter-024-muramasa-identity-continuity", "人格连续性：确认", "history", "history-v04-c024-s005-v1.0"),
        test_case("state-muramasa-returned-same-person", "日本特异点记忆与人格连续性完整保留", "character_state", current_ids["sengo-muramasa"], ["state-current-sengo-muramasa-v1.3"]),
        test_case("state-qihuang-still-not-returned", "仍未返回迦勒底 路径待重建", "character_state", current_ids["qihuang"], ["state-current-qihuang-v1.4"]),
        test_case("world-human-order-direct-support-unconfirmed", "人理直接召唤支援仍未确认", "world_state", world_id, ["world-state-current-v1.5"]),
    ]
    existing = {str(row.get("id")) for row in filtered}
    filtered.extend(row for row in additions if row["id"] not in existing)
    data["tests"] = filtered
    dump(path, data)


def main() -> None:
    history_ids = write_history()
    current_ids = write_states()
    world_id = write_world_state()
    update_registries(current_ids, world_id)
    update_retrieval_tests(current_ids, world_id)
    print(f"history_documents={len(history_ids)} states={len(current_ids)} world={world_id}")


if __name__ == "__main__":
    main()
