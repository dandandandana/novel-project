from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RAG = ROOT / "novel-rag" / "stories" / "overturned-world-fujimaru"
DOCUMENT_DIRS = (
    "canon",
    "history",
    "outline",
    "character-state",
    "world-state",
    "rules",
    "judgment",
    "generator",
    "audit",
    "style-audit",
    "feedback",
)
ABILITY_SLUGS = (
    "civilization-erosion",
    "collector",
    "servant-disguise",
    "territory-creation",
    "hear-cries-and-relieve-suffering",
    "great-compassion-dharma",
    "all-desires-of-this-world",
    "transformation-at-will",
    "vajra",
    "willow-branch-purification-vase",
)
ABILITY_NAMES = (
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
)


def read(path: Path) -> str:
    value = path.read_text(encoding="utf-8")
    assert "\ufffd" not in value, f"replacement character in {path}"
    assert "\t" not in value, f"tab indentation in {path}"
    return value


def count_block(text: str, start: str, end: str | None = None) -> str:
    assert start in text, f"missing block start: {start}"
    block = text.split(start, 1)[1]
    if end is not None:
        assert end in block, f"missing block end: {end}"
        block = block.split(end, 1)[0]
    return block


def main() -> None:
    character_path = RAG / "canon" / "characters" / "qihuang.yaml"
    character = read(character_path)
    assert "document_id: canon-character-qihuang-v1.0" in character
    assert "retrieval_key: qihuang_profile" in character
    assert "master: null" in character
    assert "classes:\n    - Pretender\n    - SAVER" in character
    assert "external_class_disguise: Lancer" in character
    assert "本世界线更倾向保护人类" in character
    assert "不得把祁荒的慈悲写成对苦难的真实共情" in character
    assert "source_profile: |-" in character

    ability_paths = sorted((RAG / "canon" / "abilities").glob("qihuang-*.yaml"))
    assert len(ability_paths) == 10, f"expected 10 ability docs, got {len(ability_paths)}"
    for slug, name in zip(ABILITY_SLUGS, ABILITY_NAMES, strict=True):
        path = RAG / "canon" / "abilities" / f"qihuang-{slug}.yaml"
        text = read(path)
        expected_id = f"canon-ability-qihuang-{slug}-v1.0"
        assert f"document_id: {expected_id}" in text
        assert f"name: {name}" in text
        assert "owner_id: qihuang" in text
        assert "status: canon" in text
        assert "cost:" in text and "limitations:" in text and "failure_conditions:" in text

    current = read(RAG / "character-state" / "current" / "qihuang.yaml")
    assert '"document_id": "state-current-qihuang-v1.2"' in current
    assert '"supersedes": "state-current-qihuang-v1.1"' in current
    available = count_block(current, '"available": [', '"unavailable":')
    for name in ABILITY_NAMES:
        assert f'"{name}"' in available
    assert available.count('"') == 20
    assert '"newly_acquired": []' in current
    assert '"location": "伊耶那岐金地地下第三层创造空间"' in current
    assert '"千子村正"' in current

    snapshot = read(
        RAG
        / "character-state"
        / "snapshots"
        / "volume-04-chapter-013"
        / "qihuang-v1.0.yaml"
    )
    assert "document_id: state-current-qihuang-v1.0" in snapshot
    assert "snapshot_type: snapshot" in snapshot
    assert "status: archived" in snapshot

    aliases = read(RAG / "registry" / "aliases.yaml")
    assert aliases.count("- canonical_id: qihuang\n") == 1
    for name in ("祁荒", "观世音·祁荒", "魔性菩萨", "Pretender祁荒", "Saver祁荒", "Lancer祁荒"):
        assert f"  - {name}" in aliases

    variants = read(RAG / "registry" / "character-variants.yaml")
    assert variants.count("  variant_id: qihuang-main\n") == 1

    version_map = read(RAG / "registry" / "version-map.yaml")
    families = ("canon-character-qihuang", "state-current-qihuang") + tuple(
        f"canon-ability-qihuang-{slug}" for slug in ABILITY_SLUGS
    )
    for family in families:
        assert version_map.count(f"- document_family: {family}\n") == 1

    retrieval = read(RAG / "retrieval-tests.yaml")
    for case_id in (
        "canon-qihuang-profile",
        "canon-qihuang-all-desires",
        "canon-qihuang-purification-vase",
        "state-qihuang-abilities",
    ):
        assert retrieval.count(f"- id: {case_id}\n") == 1

    document_ids: dict[str, Path] = {}
    document_count = 0
    for directory in DOCUMENT_DIRS:
        for path in (RAG / directory).rglob("*.yaml"):
            text = read(path)
            if text.lstrip().startswith("{"):
                document_id = str(json.loads(text)["metadata"]["document_id"])
            else:
                match = re.search(r"(?m)^  document_id:\s*(\S+)\s*$", text)
                assert match, f"missing metadata.document_id in {path}"
                document_id = match.group(1)
            assert document_id not in document_ids, (
                f"duplicate document_id {document_id}: {document_ids[document_id]} and {path}"
            )
            document_ids[document_id] = path
            document_count += 1

    assert document_count >= 537, f"expected at least 537 document files, got {document_count}"
    print(f"qihuang_import=ok abilities={len(ability_paths)} documents={document_count}")


if __name__ == "__main__":
    main()
