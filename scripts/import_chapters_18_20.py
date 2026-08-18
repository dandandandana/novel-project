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
DATE = "2026-08-08"
SOURCES = [
    ROOT / "outputs" / "第四卷_第18章_续写.txt",
    ROOT / "outputs" / "第四卷_第19章_续写.txt",
    ROOT / "outputs" / "第四卷_第20章_续写.txt",
]
SOURCE_TEXT = "; ".join(str(path) for path in SOURCES)


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


def write_history() -> list[str]:
    chapter_specs = {
        18: {
            "title": "白桦木",
            "markers": ["杖尖朝下。", "地下忽然传来铁器拖地的声音。"],
            "titles": [
                "跨界窄门受阻／神琦灰现身",
                "灰白光炮覆盖金地／众人结盾",
                "最后令咒强化杨浞／白光被推回天羽羽斩裂隙",
            ],
            "characters": [
                ["fujimaru-ritsuka", "mash-kyrielight", "kotomine-shirou", "qihuang", "sengo-muramasa", "kotomine-shirou-ae", "artoria-pendragon-alter", "shenqi-hui"],
                ["fujimaru-ritsuka", "mash-kyrielight", "kotomine-shirou", "qihuang", "sengo-muramasa", "shenqi-hui"],
                ["fujimaru-ritsuka", "mash-kyrielight", "kotomine-shirou", "qihuang", "sengo-muramasa", "yang-zhuo", "gilgamesh", "epohonsiereht", "shenqi-hui"],
            ],
            "tags": [
                ["白桦木", "跨界窄门", "神琦灰", "卫宫白", "Alterego倒戈"],
                ["灰白光炮", "盾阵", "金地灭却危机"],
                ["最后一道令咒", "英杰之帜", "杨浞", "六重水火", "圣杯出现"],
            ],
        },
        19: {
            "title": "没有一条活路",
            "markers": ["Alterego的背脊猛然挺直。", "三十五。", "杨浞眼前再次暗下。"],
            "titles": [
                "终末机关显露BEAST反应／圣杯回收倒数开始",
                "神琦灰恢复Alterego／伊耶那美迎战",
                "终末机关残舰断裂／祁荒合击遭压制／杨浞挡杖",
                "杨浞遍历无数生路／选择牺牲",
            ],
            "characters": [
                ["fujimaru-ritsuka", "epohonsiereht", "gilgamesh", "izanami", "shenqi-hui"],
                ["fujimaru-ritsuka", "mash-kyrielight", "kotomine-shirou", "sengo-muramasa", "kotomine-shirou-ae", "artoria-pendragon-alter", "izanami", "shenqi-hui"],
                ["fujimaru-ritsuka", "mash-kyrielight", "kotomine-shirou", "qihuang", "sengo-muramasa", "yang-zhuo", "gilgamesh", "izanami", "epohonsiereht", "shenqi-hui"],
                ["fujimaru-ritsuka", "mash-kyrielight", "yang-zhuo", "shenqi-hui"],
            ],
            "tags": [
                ["圣杯", "BEAST", "第三宝具", "四十八秒", "伊耶那美"],
                ["Alterego恢复", "阿尔托莉雅", "救世之兽", "神琦灰"],
                ["终末机关牺牲", "祁荒", "宝具合击", "断鞭挡杖"],
                ["未来遍历", "没有一条活路", "杨浞牺牲", "问武平清觯破碎"],
            ],
        },
        20: {
            "title": "一剑之外",
            "markers": ["七秒。", "五秒。", "——\n\n立香摔在灵子转移筐体里。"],
            "titles": [
                "神琦灰压缩星空／卫宫白跨界出剑",
                "终末机关托送伤员／四人进入回收序列",
                "卫宫白一剑压回光海／圣杯回收与日本修复",
                "迦勒底确认回归／三人未归",
            ],
            "characters": [
                ["fujimaru-ritsuka", "mash-kyrielight", "kotomine-shirou", "qihuang", "sengo-muramasa", "shenqi-hui", "kotomine-shirou-ae", "artoria-pendragon-alter"],
                ["fujimaru-ritsuka", "mash-kyrielight", "kotomine-shirou", "qihuang", "sengo-muramasa", "gilgamesh", "izanami", "yang-zhuo", "epohonsiereht", "shenqi-hui"],
                ["fujimaru-ritsuka", "mash-kyrielight", "kotomine-shirou", "qihuang", "sengo-muramasa", "gilgamesh", "izanami", "epohonsiereht", "shenqi-hui", "kotomine-shirou-ae", "artoria-pendragon-alter"],
                ["fujimaru-ritsuka", "mash-kyrielight", "kotomine-shirou", "qihuang", "sengo-muramasa", "yang-zhuo", "gilgamesh"],
            ],
            "tags": [
                ["距离坠落", "卫宫白", "跨界", "一剑", "神琦灰"],
                ["灵子转移", "回收名单", "祁荒未归", "千子村正未归"],
                ["圣杯回收", "日本特异点修复", "终末机关消散", "伊耶那美归还时代"],
                ["迦勒底", "人理基盘修复", "杨浞未归", "祁荒未归", "千子村正未归"],
            ],
        },
    }
    all_ids: list[str] = []
    documents: list[tuple[int, int, dict[str, Any], str]] = []
    for source, chapter in zip(SOURCES, (18, 19, 20)):
        spec = chapter_specs[chapter]
        text = source.read_text(encoding="utf-8").strip()
        parts = split_at(text, spec["markers"])
        for scene, content in enumerate(parts, start=1):
            document_id = f"history-v04-c{chapter:03d}-s{scene:03d}-v1.0"
            all_ids.append(document_id)
            metadata = {
                "document_id": document_id,
                "story_id": STORY_ID,
                "timeline_id": "main",
                "document_type": "history",
                "title": f"第四卷 第{chapter}章 {spec['title']} 场景{scene}：{spec['titles'][scene - 1]}",
                "volume": 4,
                "chapter": chapter,
                "scene": scene,
                "pov_character": "多视角",
                "character_ids": spec["characters"][scene - 1],
                "location_ids": ["izanagi-golden-land", "cross-world-coordinate"],
                "event_tags": ["日本下篇", spec["title"], *spec["tags"][scene - 1]],
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
                "source_file": str(source),
            }
            documents.append((chapter, scene, metadata, content))
    for index, (chapter, scene, metadata, content) in enumerate(documents):
        metadata["previous_scene"] = "history-v04-c017-s005-v1.0" if index == 0 else documents[index - 1][2]["document_id"]
        metadata["next_scene"] = None if index == len(documents) - 1 else documents[index + 1][2]["document_id"]
        dump(
            STORY / "history" / "volume-04" / f"chapter-{chapter:03d}" / f"scene-{scene:03d}.yaml",
            {"metadata": metadata, "content": content},
        )
    previous = STORY / "history" / "volume-04" / "chapter-017" / "scene-005.yaml"
    previous_doc = load(previous)
    previous_doc["metadata"]["next_scene"] = all_ids[0]
    dump(previous, previous_doc)
    return all_ids


STATE_SPECS: dict[str, dict[str, Any]] = {
    "fujimaru-ritsuka": {
        "position": ["迦勒底灵子转移筐体与医疗区", ["玛修·基列莱特", "言峰士郎", "吉尔伽美什"]],
        "health": ["重度疲劳但清醒", ["脸侧旧伤再次裂开", "圣杯杯沿割伤掌心", "三道令咒全部消耗"], "终战、圣杯回收与灵子转移后的重度消耗"],
        "mental": [["悲痛", "克制", "继续前进的决意"], ["杨浞信号丢失", "祁荒与千子村正未返回迦勒底"], ["先救治回归伤员，再确认未归同伴去向"]],
        "known": ["神琦灰以白桦木法杖袭击金地", "终末人理圆满机关显露BEAST反应并牺牲自身", "圣杯已回收，日本特异点与人理基盘完成修复", "杨浞信号丢失", "祁荒与千子村正没有返回迦勒底"],
        "unknown": ["祁荒与千子村正当前所在世界坐标", "杨浞是否存在可恢复残留", "卫宫白与神琦灰对峙结果"],
        "goals": [["组织伤员救治", "确认祁荒与千子村正去向"], ["整理日本特异点报告并准备后续行动"], ["继续修复人理"], ["同伴生存", "寻找未归同伴"]],
        "abilities": [["降格术"], ["英杰之帜（令咒耗尽，当前不可发动）"], ["最后一道令咒用于强化杨浞"], ["令咒归零"]],
        "narrative": ["日本篇结束：返回迦勒底", ["回收圣杯并完成日本人理修复", "以最后令咒强化杨浞", "接受杨浞留下断后"], ["杨浞失联", "祁荒与千子村正未归", "卫宫白与神琦灰对峙结果"], ["日本篇结束但队伍出现三名未归者"]],
    },
    "mash-kyrielight": {
        "position": ["迦勒底灵子转移筐体与医疗区", ["藤丸立香", "言峰士郎", "吉尔伽美什"]],
        "health": ["重伤回归，保持清醒", ["左肩与左臂严重损伤", "多功能武装盾面内凹", "脊柱与双腿承受多次冲击"], "英杰之帜、宝具解放与连续防御后的极重度消耗"],
        "mental": [["担忧", "悲痛", "保护意志"], ["前辈失去全部令咒", "杨浞、祁荒与村正未归"], ["保护立香并协助救治"]],
        "known": ["圣杯回收与日本人理修复完成", "杨浞以牺牲换取转移时间", "祁荒与千子村正没有返回迦勒底"],
        "unknown": ["未归三人的后续状态", "神琦灰与卫宫白战斗结果"],
        "goals": [["接受治疗并守护立香", "协助确认未归同伴"], ["恢复盾与左臂功能"], ["继续修复人理"], ["前辈安全", "同伴去向"]],
        "abilities": [["圆桌之盾", "多功能武装"], [], [], ["左臂与盾甲重创"]],
        "narrative": ["日本篇结束：返回迦勒底", ["参与圣杯回收防御", "抱住立香进入灵子转移"], ["左臂与武装修复", "三名同伴未归"], ["回归后立即进入救治与失联确认阶段"]],
    },
    "kotomine-shirou": {
        "position": ["迦勒底灵子转移筐体与医疗区", ["藤丸立香", "玛修·基列莱特", "吉尔伽美什"]],
        "health": ["重伤回归", ["右肩与右臂完全失去知觉", "左腕折断", "耳后深切伤", "左肩、腰侧和大腿中刃"], "双臂近乎失用，拟造躯壳缓慢修复"],
        "mental": [["克制", "保护欲", "对未归同伴的警惕"], ["双臂重伤", "祁荒与村正未归"], ["留在立香身边并确认失联者"]],
        "known": ["神琦灰能够恢复并驱使Alterego言峰士郎", "圣杯回收和日本修复完成", "祁荒与千子村正没有返回迦勒底"],
        "unknown": ["卫宫白与自己相似的原因", "Alterego与阿尔托莉雅后续", "未归同伴坐标"],
        "goals": [["接受双臂与投影回路治疗", "保护藤丸立香"], ["追查未归同伴"], ["继续修复人理"], ["同伴生存", "恢复行动能力"]],
        "abilities": [["拟造躯壳"], ["双臂重伤时的正常投影战斗"], [], ["右侧回路爆裂", "左腕折断"]],
        "narrative": ["日本篇结束：返回迦勒底", ["与Alterego言峰士郎短暂交战", "进入圣杯回收阵"], ["双臂恢复", "卫宫白身份", "祁荒与村正未归"], ["与另一把刀和卫宫白的关联仍未解明"]],
    },
    "qihuang": {
        "position": ["跨界窄门一侧；未返回迦勒底，具体世界坐标未确认", ["千子村正", "卫宫白（隔门协同）"]],
        "health": ["负伤且持续维持坐标", ["双手多处裂伤", "右臂被金刚杵重压砸落", "杨枝净瓶出现长裂纹"], "连续维持窄门、净瓶与欲望干涉后的重度消耗"],
        "mental": [["警觉", "坚持", "以笑掩饰压力"], ["未进入迦勒底回收序列", "神琦灰压迫跨界坐标"], ["守住窄门并确认自身与村正的落点"]],
        "known": ["神琦灰是挤压坐标的来者", "卫宫白已跨过窄门并压制神琦灰炮击", "自己与千子村正没有返回迦勒底"],
        "unknown": ["当前具体世界坐标", "迦勒底是否能重新锁定两人", "卫宫白与神琦灰对峙结果"],
        "goals": [["守住跨界坐标", "保护破损净瓶", "确认千子村正状态"], ["与迦勒底重新建立联系"], ["处理净瓶内金色佛果"], ["维持坐标", "同伴生存"]],
        "abilities": [["文明侵蚀", "阵地建造", "寻声救苦", "此世全部之欲", "金刚杵", "杨枝净瓶"], [], [], ["金刚杵与窄门持续承压", "杨枝净瓶破裂"]],
        "narrative": ["日本篇结束后的跨界失联", ["以众生欲望偏转神琦灰法杖", "重钉窄门补足转移阵"], ["未返回迦勒底", "具体落点未知", "净瓶内佛果"], ["与千子村正共同滞留在迦勒底回收序列之外"]],
    },
    "sengo-muramasa": {
        "position": ["跨界窄门一侧；未返回迦勒底，具体世界坐标未确认", ["祁荒"]],
        "health": ["重伤且未返回迦勒底", ["右臂大半烧毁", "右肋撕裂", "右肩与肩甲被阿尔托莉雅黑剑掀开", "剩余白火被压回胸口"], "连续锻刀、战斗与对抗神琦灰后的极重度消耗"],
        "mental": [["强撑", "务实", "警惕"], ["未进入迦勒底回收序列", "与祁荒滞留未知坐标"], ["确认自身与祁荒的生存和落点"]],
        "known": ["神琦灰能够压制众人宝具与白火", "卫宫白以一剑压回神琦灰炮击", "自己与祁荒没有返回迦勒底"],
        "unknown": ["当前具体世界坐标", "迦勒底能否重新建立联络", "卫宫白与神琦灰结果"],
        "goals": [["维持伤势并确认祁荒状态"], ["寻找返回或联络迦勒底的方法"], ["继续完成必要的刀"], ["同伴生存", "确认坐标"]],
        "abilities": [["创造之禊祓残余白火", "锻刀"], ["右臂正常使用"], [], ["白火被压回胸口", "右臂与右肩重创"]],
        "narrative": ["日本篇结束后的跨界失联", ["协助抵御神琦灰", "以白火支援士郎箭矢"], ["未返回迦勒底", "具体落点未知", "右臂与白火状态"], ["与祁荒共同滞留在迦勒底回收序列之外"]],
    },
    "yang-zhuo": {
        "position": ["伊耶那岐金地最终战场；灵基与生命信号丢失", []],
        "health": ["死亡／信号丢失", ["断鞭贯胸", "胸口透光贯穿伤", "全身在神琦灰炮击与重压中崩坏"], "生命活动终止"],
        "mental": [["决绝", "释然"], ["无一条生路能让所有人跨过最终之门"], ["让藤丸立香等人继续向前"]],
        "known": ["遍历大量自身存活但同伴最终失去的未来", "选择不进入任何个人生路", "圣杯回收需要自己拖延神琦灰"],
        "unknown": [],
        "goals": [[], [], [], []],
        "abilities": [[], ["全部战斗能力"], [], ["问武平清觯断裂", "灵基与生命信号丢失"]],
        "narrative": ["日本篇终局：牺牲", ["以最后令咒强化挡下光炮", "遍历未来后选择断后", "为圣杯回收争取最后时间"], ["是否存在可恢复残留"], ["留下‘等你们跨越未来，我们还会再见’的承诺"]],
    },
    "gilgamesh": {
        "position": ["迦勒底灵子转移筐体与医疗区", ["藤丸立香", "玛修·基列莱特", "言峰士郎"]],
        "health": ["重伤回归", ["左肩、锁骨与胸腔缺损", "左腿无法支撑", "右手虎口裂伤"], "地下支援与灵子转移后的重度消耗"],
        "mental": [["愤怒", "悲痛", "克制"], ["杨浞信号丢失", "问武平清觯断裂"], ["接受治疗并保留杨浞遗物"]],
        "known": ["杨浞选择牺牲并且信号丢失", "问武平清觯在其死亡时断裂", "圣杯回收与日本人理修复完成", "祁荒与村正未返回迦勒底"],
        "unknown": ["杨浞是否存在残留", "祁荒与村正当前坐标"],
        "goals": [["保存断裂的问武平清觯", "稳定重伤"], ["确认未归同伴去向"], ["继续修复人理"], ["王的尊严", "同伴遗留"]],
        "abilities": [["王之财宝", "EA", "千里眼"], [], [], ["重伤限制移动", "宝库门扉连续开启"]],
        "narrative": ["日本篇结束：返回迦勒底", ["保管问武平清觯", "打开回收门扉但未能带回杨浞"], ["杨浞残留", "祁荒与村正未归"], ["回归时仍携带断裂的问武平清觯"]],
    },
    "izanami": {
        "position": ["日本原有时代；随特异点修复被归还", []],
        "health": ["重伤后被归还时代", ["胸前遭白桦木杖重击", "右臂、长枪与月刃被自身雷霆撕碎"], "救世之兽战斗形态后的极重度消耗"],
        "mental": [["决绝", "平静"], ["阻挡神琦灰直至圣杯回收"], ["随日本山海复原"]],
        "known": ["圣杯回收倒数启动", "自己作为本地神灵无法被带离", "神琦灰压倒性强大"],
        "unknown": ["迦勒底回归后的状况", "卫宫白与神琦灰对峙结果"],
        "goals": [["回归并维持日本山海"], [], ["守护原有时代"], ["日本世界存续"]],
        "abilities": [["日本神灵权能（随时代归还）"], [], [], ["右臂与武装在终战中毁损"]],
        "narrative": ["日本篇结束：归还原有时代", ["以黑月和长枪迎战神琦灰", "在特异点修复时散回日本山海"], ["归还后的个体状态"], ["本地神灵没有进入迦勒底转移筐体"]],
    },
    "epohonsiereht": {
        "position": ["伊耶那岐金地；机关残体在转移完成时全部崩散", []],
        "health": ["机关本体消散／功能终止", ["第三宝具执行后转化为BEAST形态", "舰身被自身炮击切断", "残余手掌在维持转移阵时全部崩散"], "系统终止"],
        "mental": [["冷静", "决绝"], ["必须完成圣杯回收与人理修复"], ["要求人类继续向前"]],
        "known": ["第三宝具已在弥勒死亡后执行", "自身出现BEAST判定", "圣杯回收与灵子转移需要四十八秒"],
        "unknown": [],
        "goals": [[], [], [], []],
        "abilities": [[], ["全部机关与主炮功能"], ["第三宝具已执行"], ["机关完全崩散"]],
        "narrative": ["日本篇终局：完成使命并消散", ["交付圣杯", "显露BEAST形态阻挡神琦灰", "以最后手掌维持转移阵"], [], ["留下‘人类，请继续向前’的最终请求"]],
    },
    "kotomine-shirou-ae": {
        "position": ["神琦灰所在裂隙一侧；未随迦勒底返回", ["阿尔托莉雅·潘德拉贡 Alter", "神琦灰"]],
        "health": ["被神琦灰恢复后保持行动能力", ["曾被伊耶那美截断后由神琦灰复原"], "状态受神琦灰力量影响"],
        "mental": [["复杂", "警惕", "克制"], ["神琦灰与卫宫白对峙"], ["与阿尔托莉雅留在裂隙一侧"]],
        "known": ["神琦灰能恢复自己的致命伤", "迦勒底完成圣杯回收", "言峰士郎有返回捡回自己的意图"],
        "unknown": ["神琦灰与卫宫白对峙结果", "自身后续选择"],
        "goals": [["保护阿尔托莉雅并观察神琦灰"], [], [], ["阿尔托莉雅安全"]],
        "abilities": [["无限剑制", "黑弓"], [], [], ["受神琦灰指令限制"]],
        "narrative": ["日本篇结束：留在裂隙另一侧", ["被神琦灰恢复并与言峰士郎交战", "目送迦勒底转移"], ["自身与神琦灰关系", "卫宫白对峙结果"], ["没有进入迦勒底回收序列"]],
    },
    "artoria-pendragon-alter": {
        "position": ["神琦灰所在裂隙一侧；未随迦勒底返回", ["言峰士郎（AE）", "神琦灰"]],
        "health": ["保持行动能力", ["黑剑与承伤刻纹持续受损"], "受神琦灰战场力量影响"],
        "mental": [["关切", "敌意", "克制"], ["Alterego言峰士郎受神琦灰控制", "卫宫白与神琦灰对峙"], ["抓住Alterego并留在其身边"]],
        "known": ["神琦灰能复原Alterego致命伤", "迦勒底完成圣杯回收", "立香承诺会记得他们"],
        "unknown": ["对峙结果", "自身后续去向"],
        "goals": [["留在Alterego身边"], [], [], ["同伴存续"]],
        "abilities": [["潘多拉臂铠", "誓约胜利之剑"], [], [], ["承伤刻纹继续消耗"]],
        "narrative": ["日本篇结束：留在裂隙另一侧", ["对神琦灰显露杀意", "在转移前请求立香记住"], ["卫宫白与神琦灰对峙结果"], ["没有进入迦勒底回收序列"]],
    },
}


def build_state_body(old: dict[str, Any], spec: dict[str, Any]) -> dict[str, Any]:
    state = deepcopy(old.get("character_state", {}))
    location, companions = spec["position"]
    state["current_position"] = {"location": location, "companions": companions, "faction": old["character_state"]["current_position"].get("faction", "")}
    health, injuries, fatigue = spec["health"]
    state["physical"] = {"health": health, "injuries": injuries, "fatigue": fatigue, "temporary_conditions": [], "permanent_changes": []}
    emotions, pressures, desires = spec["mental"]
    state["mental"] = {"dominant_emotions": emotions, "current_pressure": pressures, "desires": desires, "fears": [], "unresolved_conflicts": [], "behavior_effects": []}
    state["knowledge"] = {"known": spec["known"], "unknown": spec["unknown"], "mistaken_beliefs": [], "suspicions": [], "secrets_held": []}
    immediate, short_term, long_term, priorities = spec["goals"]
    state["goals"] = {"immediate": immediate, "short_term": short_term, "long_term": long_term, "priorities": priorities, "obstacles": injuries[:3]}
    state["relationships"] = old["character_state"].get("relationships", [])
    available, unavailable, consumed, costs = spec["abilities"]
    state["abilities"] = {"available": available, "unavailable": unavailable, "newly_acquired": [], "consumed_resources": consumed, "active_costs": costs}
    state["inventory"] = old["character_state"].get("inventory", {"carried": [], "lost": [], "damaged": []})
    arc, completed, unresolved, future = spec["narrative"]
    state["narrative"] = {"current_arc": arc, "completed_changes": completed, "unresolved_flags": unresolved, "active_promises": [], "future_pressure": future}
    return state


def bump_version(value: str) -> str:
    major, minor = value.split(".", 1)
    return f"{major}.{int(minor) + 1}"


def write_states() -> dict[str, str]:
    current_ids: dict[str, str] = {}
    snapshot_dir = STATE_ROOT / "snapshots" / "volume-04-chapter-020"
    change_dir = STATE_ROOT / "change-logs" / "volume-04-chapter-020"
    for character_id, spec in STATE_SPECS.items():
        current_path = STATE_ROOT / "current" / f"{character_id}.yaml"
        old = load(current_path)
        old_meta = old["metadata"]
        old_id = str(old_meta["document_id"])
        old_version = str(old_meta["version"])
        new_version = bump_version(old_version)
        new_id = f"state-current-{character_id}-v{new_version}"

        snapshot = deepcopy(old)
        snapshot["metadata"].update({"title": f"第四卷第17章末状态快照-{old_meta['title'].removeprefix('当前状态-')}", "snapshot_type": "snapshot", "status": "archived"})
        dump(snapshot_dir / f"{character_id}-v{old_version}.yaml", snapshot)

        new_doc = deepcopy(old)
        new_doc["metadata"].update({
            "document_id": new_id,
            "snapshot_type": "current",
            "effective_at": "volume-04-chapter-020",
            "last_updated": DATE,
            "version": new_version,
            "status": "active",
            "supersedes": old_id,
            "source_file": SOURCE_TEXT,
        })
        new_doc["character_state"] = build_state_body(old, spec)
        if character_id == "qihuang":
            new_doc["character_state"]["inventory"] = {"carried": ["金刚杵", "开裂的杨枝净瓶（内有金色佛果）"], "lost": [], "damaged": ["杨枝净瓶出现长裂纹"]}
        elif character_id == "sengo-muramasa":
            new_doc["character_state"]["inventory"]["damaged"] = ["右臂、肩甲与刀鞘严重受损"]
        elif character_id == "gilgamesh":
            new_doc["character_state"]["inventory"] = {"carried": ["EA", "断裂的问武平清觯"], "lost": [], "damaged": ["问武平清觯断成两半"]}
        elif character_id == "yang-zhuo":
            new_doc["character_state"]["inventory"] = {"carried": [], "lost": ["问武平清觯（由吉尔伽美什带回）"], "damaged": ["青铜铁鞭崩碎"]}
        dump(current_path, new_doc)

        change = {
            "metadata": {
                "document_id": f"state-change-{character_id}-v04-c020-v1.0",
                "story_id": STORY_ID,
                "timeline_id": "main",
                "document_type": "character_state",
                "title": f"第4卷第18至20章状态变化-{old_meta['title'].removeprefix('当前状态-')}",
                "character_id": old_meta["character_id"],
                "variant_id": old_meta["variant_id"],
                "snapshot_type": "change_log",
                "effective_at": "volume-04-chapter-020",
                "last_updated": DATE,
                "version": "1.0",
                "status": "canon",
                "supersedes": None,
                "source_file": SOURCE_TEXT,
            },
            "changes": [
                {"category": "chapter_18_to_20_outcome", "before": old_id, "after": new_id, "cause": "第四卷第18至20章神琦灰袭击、圣杯回收与日本人理修复", "evidence": "history-v04-c020"}
            ],
        }
        dump(change_dir / f"{character_id}.yaml", change)
        current_ids[character_id] = new_id

    template = load(LIBRARY / "shared" / "templates" / "character-current.yaml")
    shenqi_id = "state-current-shenqi-hui-v1.0"
    template["metadata"].update({
        "document_id": shenqi_id,
        "story_id": STORY_ID,
        "timeline_id": "main",
        "title": "当前状态-神琦灰",
        "character_id": "shenqi-hui",
        "variant_id": "shenqi-hui-main",
        "snapshot_type": "current",
        "effective_at": "volume-04-chapter-020",
        "last_updated": DATE,
        "version": "1.0",
        "status": "active",
        "supersedes": None,
        "source_file": SOURCE_TEXT,
    })
    template["character_state"] = {
        "current_position": {"location": "跨界裂隙另一侧", "companions": ["言峰士郎（AE）", "阿尔托莉雅·潘德拉贡 Alter"], "faction": "自身阵营"},
        "physical": {"health": "未见实质伤势，但被卫宫白逼退一步", "injuries": ["白裙、发梢与右侧袖口被斩断", "白桦木法杖被压弯"], "fatigue": "首次双手持杖并全力维持炮击", "temporary_conditions": [], "permanent_changes": []},
        "mental": {"dominant_emotions": ["自信", "恼怒", "专注"], "current_pressure": ["卫宫白一剑压回最强炮击"], "desires": ["突破斩线并继续追击"], "fears": [], "unresolved_conflicts": [], "behavior_effects": ["停止关注迦勒底，转而全力应对卫宫白"]},
        "knowledge": {"known": ["迦勒底完成圣杯回收", "卫宫白能够跨界并正面压制自身炮击"], "unknown": ["卫宫白斩线极限", "迦勒底后续去向"], "mistaken_beliefs": [], "suspicions": [], "secrets_held": []},
        "goals": {"immediate": ["突破卫宫白斩线"], "short_term": ["重新取得跨界主动权"], "long_term": ["彻底成为根源并超越愿主神琦灰"], "priorities": ["自身目标"], "obstacles": ["卫宫白"]},
        "relationships": [],
        "abilities": {"available": ["万能魔术", "根源魔术", "白桦木法杖"], "unavailable": [], "newly_acquired": [], "consumed_resources": [], "active_costs": ["最强炮击被一剑压回"]},
        "inventory": {"carried": ["白桦木法杖"], "lost": [], "damaged": ["法杖被压弯"]},
        "narrative": {"current_arc": "日本篇终局后的跨界对峙", "completed_changes": ["袭击伊耶那岐金地", "阻击圣杯回收", "被卫宫白逼退一步"], "unresolved_flags": ["与卫宫白对峙结果"], "active_promises": [], "future_pressure": ["已成为迦勒底后续道路上的明确敌人"]},
    }
    dump(STATE_ROOT / "current" / "shenqi-hui.yaml", template)
    current_ids["shenqi-hui"] = shenqi_id
    return current_ids


def write_world_state() -> str:
    path = STORY / "world-state" / "current" / "current.yaml"
    old = load(path)
    snapshot = deepcopy(old)
    snapshot["metadata"]["status"] = "archived"
    dump(STORY / "world-state" / "change-logs" / "volume-04-chapter-020-snapshot.yaml", snapshot)
    new_id = "world-state-current-v1.5"
    world = {
        "metadata": {
            "document_id": new_id,
            "story_id": STORY_ID,
            "timeline_id": "main",
            "document_type": "world_state",
            "title": "第四卷第20章后世界状态",
            "version": "1.5",
            "status": "active",
            "effective_at": "volume-04-chapter-020",
            "supersedes": old["metadata"]["document_id"],
            "source_file": SOURCE_TEXT,
            "updated_at": DATE,
        },
        "world_state": {
            "timeline_position": "第四卷第20章末，圣杯回收，日本特异点消失，人理基盘修复完成",
            "locations": [
                {"location_id": "chaldea", "current_condition": "立香、玛修、言峰士郎与吉尔伽美什已回归，伤员进入救治", "controlling_faction": "迦勒底", "accessibility": "灵子转移完成", "known_hazards": ["多人重伤", "三名同伴未归"], "recent_events": ["圣杯回收", "日本人理修复"]},
                {"location_id": "izanagi-golden-land", "current_condition": "特异点已经消失并归还原有时代", "controlling_faction": "不再适用", "accessibility": "迦勒底当前无法直接进入", "known_hazards": [], "recent_events": ["终末人理圆满机关消散", "杨浞信号丢失", "伊耶那美随日本山海归还"]},
                {"location_id": "cross-world-coordinate", "current_condition": "卫宫白以斩线压制神琦灰；祁荒与千子村正未进入迦勒底回收序列", "controlling_faction": "未确认", "accessibility": "跨界窄门状态未知", "known_hazards": ["神琦灰", "距离与世界结构失真"], "recent_events": ["卫宫白跨界", "祁荒与千子村正失联"]},
            ],
            "factions": [
                {"faction_id": "chaldea", "current_goal": "救治回归人员并确认未归同伴", "leadership": "藤丸立香", "alliances": [], "enemies": ["神琦灰"], "known_information": ["日本人理修复完成", "祁荒与千子村正未返回迦勒底", "杨浞信号丢失"], "resources": ["已回收圣杯", "藤丸立香令咒归零"], "recent_changes": ["日本特异点完成", "队伍回归不完整"]}
            ],
            "global_events": ["神琦灰袭击伊耶那岐金地", "终末人理圆满机关显露BEAST反应并消散", "圣杯回收确认", "日本特异点消失", "人理基盘修复完成"],
            "public_knowledge": ["日本原有时代随人理修复恢复"],
            "hidden_world_changes": ["卫宫白与神琦灰仍隔斩线对峙", "祁荒和千子村正未返回迦勒底且具体坐标未知"],
            "unresolved_world_flags": ["祁荒与千子村正当前坐标", "杨浞是否存在可恢复残留", "卫宫白与神琦灰对峙结果", "Alterego言峰士郎与阿尔托莉雅后续"],
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
            row["current_chapter"] = 20
    dump(stories_path, stories)

    version_path = STORY / "registry" / "version-map.yaml"
    version_map = load(version_path)
    rows = version_map.setdefault("versions", [])
    by_family = {row.get("document_family"): row for row in rows}
    for character_id, current_id in current_ids.items():
        family = f"state-current-{character_id}"
        row = by_family.get(family)
        if row is None:
            rows.append({"document_family": family, "current": current_id, "supersedes": [], "reason": "建立第四卷第20章后的当前状态"})
            continue
        previous = row.get("current")
        supersedes = row.setdefault("supersedes", [])
        if previous and previous not in supersedes:
            supersedes.insert(0, previous)
        row["current"] = current_id
        row["reason"] = "回写第四卷第18至20章后的神琦灰袭击、圣杯回收、人理修复与未归状态"
    world_row = by_family["world-state-current"]
    previous_world = world_row["current"]
    if previous_world not in world_row.setdefault("supersedes", []):
        world_row["supersedes"].insert(0, previous_world)
    world_row["current"] = world_id
    world_row["reason"] = "回写第四卷第18至20章后的圣杯回收、日本人理修复与未归人员状态"
    dump(version_path, version_map)


def update_retrieval_tests() -> None:
    path = STORY / "retrieval-tests.yaml"
    data = load(path)
    tests = data.setdefault("tests", [])
    existing = {row.get("id") for row in tests}
    additions = [
        {"id": "history-chapter-020-qihuang-muramasa-not-returned", "story_id": STORY_ID, "timeline_id": "main", "query": "祁荒 千子村正 没有随转移阵返回迦勒底", "document_types": ["history"], "expected_document_ids": ["history-v04-c020-s003-v1.0"], "forbidden_statuses": ["draft", "deprecated", "archived"], "checks": ["correctness", "temporal", "content_type"]},
        {"id": "state-qihuang-not-returned-chapter-020", "story_id": STORY_ID, "timeline_id": "main", "query": "祁荒 未返回迦勒底 具体世界坐标未确认", "document_types": ["character_state"], "expected_document_ids": ["state-current-qihuang-v1.4"], "forbidden_document_ids": ["state-current-qihuang-v1.3"], "forbidden_statuses": ["draft", "deprecated", "archived"], "checks": ["correctness", "temporal", "version"]},
        {"id": "state-muramasa-not-returned-chapter-020", "story_id": STORY_ID, "timeline_id": "main", "query": "千子村正 未返回迦勒底 具体世界坐标未确认", "document_types": ["character_state"], "expected_document_ids": ["state-current-sengo-muramasa-v1.3"], "forbidden_document_ids": ["state-current-sengo-muramasa-v1.2"], "forbidden_statuses": ["draft", "deprecated", "archived"], "checks": ["correctness", "temporal", "version"]},
        {"id": "world-state-after-chapter-020", "story_id": STORY_ID, "timeline_id": "main", "query": "日本特异点消失 人理基盘修复完成", "document_types": ["world_state"], "expected_document_ids": ["world-state-current-v1.5"], "forbidden_document_ids": ["world-state-current-v1.4"], "forbidden_statuses": ["draft", "deprecated", "archived"], "checks": ["correctness", "temporal", "version"]},
    ]
    tests.extend(item for item in additions if item["id"] not in existing)
    dump(path, data)


def main() -> None:
    history_ids = write_history()
    current_ids = write_states()
    world_id = write_world_state()
    update_registries(current_ids, world_id)
    update_retrieval_tests()
    print(f"history_documents={len(history_ids)} states={len(current_ids)} world={world_id}")


if __name__ == "__main__":
    main()
