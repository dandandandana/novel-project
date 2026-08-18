from __future__ import annotations

import collections
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CHAPTER = ROOT / "outputs" / "第四卷_第14章_续写.txt"

NEGATIVE_OPENERS = (
    "没有",
    "不是",
    "他没有",
    "她没有",
    "杨浞没有",
    "天照命没有",
    "吉尔伽美什没有",
    "立香没有",
    "玛修没有",
    "士郎没有",
    "村正没有",
)
WEAK_LINKERS = ("与此同时", "下一瞬", "紧接着", "随之", "开始", "继续")
CAUSAL_LINKERS = (
    "于是",
    "因此",
    "因而",
    "反而",
    "随即",
    "继而",
    "旋即",
    "顺势",
    "借此",
    "趁机",
    "既然",
    "只要",
    "却",
    "才",
    "便",
)
SOUND_WORDS = (
    "声",
    "响",
    "鸣",
    "啸",
    "震",
    "嗡",
    "铮",
    "脆",
    "闷",
    "沙沙",
    "诵经",
    "呼吸",
    "寂静",
    "失声",
)
SUBJECTS = ("杨浞", "天照命", "吉尔伽美什", "立香", "玛修", "士郎", "村正", "祁荒")


def main() -> None:
    text = CHAPTER.read_text(encoding="utf-8")
    paragraphs = [item.strip() for item in re.split(r"\n\s*\n", text) if item.strip()]
    prose = paragraphs[1:]
    narrative_paragraphs = [item for item in prose if not item.startswith(("“", "‘"))]
    sentences = [item for item in re.split(r"(?<=[。！？])", text) if item.strip()]

    negative_openers = [item for item in prose if item.startswith(NEGATIVE_OPENERS)]
    short_paragraphs = [item for item in prose if len(item) < 24]
    very_short_paragraphs = [item for item in prose if len(item) < 12]
    weak_counts = {word: text.count(word) for word in WEAK_LINKERS}
    causal_count = sum(text.count(word) for word in CAUSAL_LINKERS)
    sound_count = sum(text.count(word) for word in SOUND_WORDS)

    subject_runs: list[tuple[str, int]] = []
    current_subject = ""
    current_count = 0
    for sentence in sentences:
        stripped = sentence.lstrip("\n ")
        subject = next((name for name in SUBJECTS if stripped.startswith(name)), "")
        if subject and subject == current_subject:
            current_count += 1
        else:
            if current_subject and current_count >= 3:
                subject_runs.append((current_subject, current_count))
            current_subject = subject
            current_count = 1 if subject else 0
    if current_subject and current_count >= 3:
        subject_runs.append((current_subject, current_count))

    paragraph_lengths = sorted(map(len, prose))
    median = paragraph_lengths[len(paragraph_lengths) // 2]
    narrative_lengths = sorted(map(len, narrative_paragraphs))
    narrative_median = narrative_lengths[len(narrative_lengths) // 2]
    print(f"paragraphs={len(paragraphs)} median={median}")
    print(f"narrative_paragraphs={len(narrative_paragraphs)} narrative_median={narrative_median}")
    print(f"short_under24={len(short_paragraphs)} very_short_under12={len(very_short_paragraphs)}")
    print(f"negative_openers={len(negative_openers)}")
    print(f"causal_linkers={causal_count} sound_markers={sound_count}")
    print("weak_linkers=" + ",".join(f"{key}:{value}" for key, value in weak_counts.items()))
    print(f"subject_runs_ge3={len(subject_runs)}")
    for item, count in collections.Counter(negative_openers).most_common(5):
        print(f"negative_example[{count}]={item[:80]}")

    if len(negative_openers) > 2:
        raise AssertionError(f"否定前置段落过多: {len(negative_openers)}")
    if narrative_median < 80:
        raise AssertionError(f"叙述段落中位长度过短: {narrative_median}")
    if causal_count < 180:
        raise AssertionError(f"因果与承接标记不足: {causal_count}")
    if sound_count < 150:
        raise AssertionError(f"战斗声场标记不足: {sound_count}")
    if weak_counts["下一瞬"] > 2 or weak_counts["与此同时"] > 2:
        raise AssertionError(f"弱连接词过多: {weak_counts}")
    print("style_continuity_sound=PASS")


if __name__ == "__main__":
    main()
