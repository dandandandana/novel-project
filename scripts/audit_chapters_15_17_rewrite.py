from __future__ import annotations

from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import scripts.audit_chapters_15_17 as base

base.CHAPTERS = [
    ROOT / "outputs" / f"第四卷_第{number}章_重写.txt"
    for number in (15, 16, 17)
]

base.REQUIRED_IN_ORDER = [
    ("弥勒降格", "降格继续向上"),
    ("居民目睹本相", "他们第一次看见了未来佛的本相"),
    ("AE组疏散完成", "炮线内生命信号，零"),
    ("终末装置第二宝具", "歼灭模式，启动。启航——星空"),
    ("主炮命中且目标存续", "目标存续。炮身过热"),
    ("计划结束转入硬战", "接下来，硬打"),
    ("立香承认世界线归属", "你们不是这条世界线的人"),
    ("英杰之帜强化玛修", "英杰之帜——玛修·基列莱特"),
    ("士郎躯壳被识破", "骨头、回路、连疼痛都给投影让了位置"),
    ("无名大戟出现", "门后没有宝具雨。只悬着一柄大戟"),
    ("投影改变士郎躯壳", "士郎体内传来第一声骨响"),
    ("十余法相围杀", "残存的十几尊法相"),
    ("尸山与紫火", "紫火从所有断口同时喷出"),
    ("村正为未来前进", "未来有没有，砍开再说"),
    ("弥勒宝具", "『众生止步·极乐一掌』"),
    ("玛修宝具", "『追回明日的迦勒底利刃』"),
    ("阿尔托莉雅宝具", "『誓约胜利之剑』"),
    ("AE士郎宝具", "『天丛云村正·伪』"),
    ("三色火焰汇入黑火", "黑火一口将白日吞了进去"),
    ("地下未知存在回应", "大地深处传来第二声剑鸣"),
    ("天羽羽斩决着", "『天羽羽斩』"),
    ("人类自由", "人类自由了"),
    ("十八层地狱", "若十八层地狱真有我的位置"),
    ("弥勒死亡", "弥勒死了"),
    ("卫宫白感知异动", "卫宫白睁开眼"),
    ("未知人影挤压坐标", "透明坐标已经失去原本形状"),
    ("沿祁荒坐标准备前来", "把坐标守好"),
]

base.BANNED_OOC = base.BANNED_OOC + (
    "李周巍",
    "故尊复现",
    "白麒麟",
    "真君级",
    "次显锻白再明王戟",
    "伊耶那岐神尸",
    "游星尖兵",
    "原主人使用它时所需的身体条件",
)


def audit_information_disclosure() -> None:
    combined = "\n\n".join(path.read_text(encoding="utf-8") for path in base.CHAPTERS)
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", combined) if part.strip()]
    prohibited_openers = (
        "实际上",
        "事实上",
        "他并不知道",
        "她真正的目的其实是",
        "这正是因为",
        "这意味着在未来",
        "这种力量的本质是",
    )
    offenders = [part for part in paragraphs if part.startswith(prohibited_openers)]
    if offenders:
        raise AssertionError(f"出现旁白泄底式说明开头: {offenders[:3]}")

    observable_anchors = (
        "没有姓名，没有面孔",
        "敌对标记在同一秒内全部熄灭",
        "没人来得及判断那是什么",
        "轮廓始终无法稳定",
        "五官仍是一片空白",
    )
    missing = [anchor for anchor in observable_anchors if anchor not in combined]
    if missing:
        raise AssertionError(f"缺少未知信息的现象化载体: {missing}")
    print("information_disclosure=PASS forbidden_labels_absent observable_unknowns_present")


if __name__ == "__main__":
    base.main()
    audit_information_disclosure()
