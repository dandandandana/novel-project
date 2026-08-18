from __future__ import annotations

import collections
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CHAPTER = ROOT / "outputs" / "第四卷_第14章_续写.txt"

REQUIRED_IN_ORDER = [
    ("试探碰撞与辱骂", "花尾鸟，和人动手时把尾巴藏好"),
    ("故尊复现判断", "故尊复现"),
    ("信标安置与瓮中捉鳖", "瓮中捉鳖"),
    ("AE协助与神琦灰情报", "神琦灰让你们来的"),
    ("创造之禊祓取得", "创造之禊祓，拿到了"),
    ("乌从欲与大圣现界", "【至命至性并火大圣】，现界"),
    ("英杰之帜强化", "英杰之帜——杨浞"),
    ("天武现界", "本尊——天武真炁神煞真君"),
    ("EA固有结界", "吉尔伽美什以EA展开的固有结界"),
    ("降格完成", "降格术完成"),
    ("第一宝具", "『问武平清觯』"),
    ("第二宝具", "『奉真策玄鞭』"),
    ("结局台词", "也许你们真的能拯救......他们"),
]

BANNED_META = ["根据大纲", "按照设定", "RAG", "检索过程", "作为AI", "本章讲述"]

ABILITY_REVEALS = {
    "真武正性剑": "“真武正性剑，出鞘。”",
    "真炁六水火": "“真炁六水火。”",
    "无丈": "“无丈。”",
    "无擘": "“无擘。”",
    "无常": "“无常。”",
    "修武星": "“修武星，照。”",
    "无垠": "“无垠。”",
    "乌从欲": "“——乌从欲。”",
    "至命除": "“——至命除。”",
    "霞羽客": "“霞羽客。”",
    "无明": "“无明。”",
    "食恶开明": "“食恶开明。”",
    "檀真": "“檀真！”",
    "问武平清觯": "“——『问武平清觯』。”",
    "奉真策玄鞭": "“——『奉真策玄鞭』！”",
}

PREMATURE_EXPOSITION = [
    "天照命在借他的欲望",
    "每一次出剑都在给她添一分火",
    "神名、佛果、太阳权能与那只无名孔雀的生命被分成四层",
    "弥勒握着孩子的命",
    "食恶开明无法吞食",
]


def main() -> None:
    text = CHAPTER.read_text(encoding="utf-8")
    positions: list[tuple[str, int]] = []
    for label, needle in REQUIRED_IN_ORDER:
        position = text.find(needle)
        if position < 0:
            raise AssertionError(f"缺少大纲节点: {label} / {needle}")
        positions.append((label, position))
    if any(positions[index][1] >= positions[index + 1][1] for index in range(len(positions) - 1)):
        raise AssertionError(f"大纲节点顺序错误: {positions}")
    for phrase in BANNED_META:
        if phrase in text:
            raise AssertionError(f"正文出现元叙事禁词: {phrase}")

    for ability, reveal in ABILITY_REVEALS.items():
        reveal_position = text.find(reveal)
        if reveal_position < 0:
            raise AssertionError(f"缺少能力正式揭名: {ability} / {reveal}")
        if ability in text[:reveal_position]:
            raise AssertionError(f"能力在正式揭名前被叙述者提前点名: {ability}")
    for phrase in PREMATURE_EXPOSITION:
        if phrase in text:
            raise AssertionError(f"首次交锋出现过早机制说明: {phrase}")

    paragraphs = [item.strip() for item in re.split(r"\n\s*\n", text) if item.strip()]
    duplicates = [
        (item, count)
        for item, count in collections.Counter(paragraphs).items()
        if count > 1 and len(item) >= 30
    ]
    if duplicates:
        raise AssertionError(f"发现重复段落: {duplicates[:3]}")

    raw = CHAPTER.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        raise AssertionError("文件包含 UTF-8 BOM")
    if b"\r\n" in raw:
        raise AssertionError("文件不是 LF 换行")

    no_whitespace = sum(not character.isspace() for character in text)
    cjk = sum("\u4e00" <= character <= "\u9fff" for character in text)
    if no_whitespace < 20_000:
        raise AssertionError(f"去空白字数不足 20000: {no_whitespace}")
    if cjk < 20_000:
        raise AssertionError(f"纯汉字数不足 20000: {cjk}")

    print("outline_order=PASS")
    for label, position in positions:
        print(f"  {position:05d} {label}")
    print(f"chars_no_whitespace={no_whitespace}")
    print(f"cjk={cjk}")
    print(f"paragraphs={len(paragraphs)} duplicates=0 utf8_no_bom_lf=PASS")
    print("first_contact_epistemic_progression=PASS")
    for word in ["仿佛", "似乎", "某种", "一种", "很", "非常", "极其", "突然"]:
        print(f"{word}={text.count(word)}")


if __name__ == "__main__":
    main()
