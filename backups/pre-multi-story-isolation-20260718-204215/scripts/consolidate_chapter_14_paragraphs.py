from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CHAPTER = ROOT / "outputs" / "第四卷_第14章_续写.txt"

SCENE_OPENERS = (
    "与此同时，伊耶那岐金地地下第三层",
    "北侧祭道上",
    "地下第三层。",
    "白火抵达东门时",
    "北侧祭道外",
    "立香已经抵达固有结界外缘",
    "固有结界内",
    "荒原消失",
    "黑色穹顶消失后",
    "东门盆地里",
)
RITUAL_LINES = (
    "“——乌从欲。”",
    "“——至命除。”",
    "“天武真炁神煞真君——现界。”",
    "“——『问武平清觯』。”",
    "“——『奉真策玄鞭』！”",
)


def is_dialogue(paragraph: str) -> bool:
    return paragraph.startswith(("“", "‘"))


def main() -> None:
    text = CHAPTER.read_text(encoding="utf-8")
    source = [item.strip() for item in re.split(r"\n\s*\n", text) if item.strip()]
    title, units = source[0], source[1:]
    output: list[str] = [title]
    buffer: list[str] = []

    def flush() -> None:
        if buffer:
            output.append("".join(buffer))
            buffer.clear()

    for unit in units:
        if unit.startswith(SCENE_OPENERS) or unit in RITUAL_LINES:
            flush()
            output.append(unit)
            continue
        if is_dialogue(unit):
            flush()
            output.append(unit)
            continue
        projected = len("".join(buffer)) + len(unit)
        if buffer and projected > 190:
            flush()
        buffer.append(unit)
        if len("".join(buffer)) >= 115:
            flush()
    flush()

    CHAPTER.write_text("\n\n".join(output) + "\n", encoding="utf-8", newline="\n")
    print(f"paragraphs_before={len(source)}")
    print(f"paragraphs_after={len(output)}")


if __name__ == "__main__":
    main()
