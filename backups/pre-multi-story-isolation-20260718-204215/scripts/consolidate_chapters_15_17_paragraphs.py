from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CHAPTERS = [ROOT / "outputs" / f"第四卷_第{number}章_续写.txt" for number in (15, 16, 17)]

SCENE_OPENERS = (
    "第一粒米被黑金孔雀啄进嘴里时",
    "北侧信标石台上",
    "弥勒恰在此刻",
    "一扇金色门扉",
    "白火从两人脚下升起",
    "与此同时，远离这处特异点",
)
PROTECTED_NARRATIVE = {
    "降格继续向上。",
    "白光穿出地面。",
    "真君级。",
    "弥勒第一次主动后撤。",
    "两拳。",
    "决着只需一刀。",
    "刀从左下向右上挥过。",
    "白昼被切成两半。",
    "弥勒死了。",
}


def is_dialogue(paragraph: str) -> bool:
    return paragraph.startswith(("“", "‘"))


def main() -> None:
    for chapter in CHAPTERS:
        text = chapter.read_text(encoding="utf-8")
        source = [item.strip() for item in re.split(r"\n\s*\n", text) if item.strip()]
        title, units = source[0], source[1:]
        output: list[str] = [title]
        buffer: list[str] = []

        def flush() -> None:
            if buffer:
                output.append("".join(buffer))
                buffer.clear()

        for unit in units:
            if unit.startswith(SCENE_OPENERS) or unit in PROTECTED_NARRATIVE:
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
            if len("".join(buffer)) >= 110:
                flush()
        flush()

        chapter.write_text("\n\n".join(output) + "\n", encoding="utf-8", newline="\n")
        print(f"{chapter.name}: paragraphs_before={len(source)} paragraphs_after={len(output)}")


if __name__ == "__main__":
    main()
