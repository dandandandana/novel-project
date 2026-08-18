from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LIBRARY = ROOT / "novel-rag"
RAG = LIBRARY / "stories" / "overturned-world-fujimaru"
DOCUMENT_DIRS = (
    "canon", "history", "outline", "character-state", "world-state", "rules",
    "judgment", "generator", "audit", "style-audit", "feedback",
)
ABILITY_SLUGS = (
    "magic-resistance",
    "perfect-form",
    "mind-eye-false",
    "mind-eye-true",
    "charisma",
    "mingzhang-sun-and-moon",
    "jiazi-soul-tempered-halberd-art",
    "fire-arts",
    "walking-method",
    "juntaowei",
    "red-severing-arrowhead",
    "white-qilin",
    "zhimingchu",
    "audience-at-heavens-gate",
    "imperial-view-origin",
    "qianyang-bracelet",
    "second-manifest-forged-white-renewed-ming-king-halberd",
)
CURRENT_IDS = {
    "fujimaru-ritsuka": "state-current-fujimaru-ritsuka-v1.3",
    "yang-zhuo": "state-current-yang-zhuo-v1.2",
    "gilgamesh": "state-current-gilgamesh-v1.1",
    "sengo-muramasa": "state-current-sengo-muramasa-v1.1",
    "qihuang": "state-current-qihuang-v1.2",
    "kotomine-shirou": "state-current-kotomine-shirou-v1.2",
    "mash-kyrielight": "state-current-mash-kyrielight-v1.2",
    "izanami": "state-current-izanami-v1.1",
    "amaterasu-no-mikoto": "state-current-amaterasu-no-mikoto-v1.0",
    "kotomine-shirou-ae": "state-current-kotomine-shirou-ae-v1.0",
    "artoria-pendragon-alter": "state-current-artoria-pendragon-alter-v1.0",
}


def read(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    assert "\ufffd" not in text, f"replacement character in {path}"
    assert "\t" not in text, f"tab found in {path}"
    return text


def json_doc(path: Path) -> dict:
    return json.loads(read(path))


def document_id(path: Path, text: str) -> str:
    if text.lstrip().startswith("{"):
        return str(json.loads(text)["metadata"]["document_id"])
    match = re.search(r"(?m)^  document_id:\s*(\S+)\s*$", text)
    assert match, f"missing metadata.document_id in {path}"
    return match.group(1)


def main() -> None:
    chapter_source = read(ROOT / "outputs" / "第四卷_第14章_续写.txt").strip()
    history_dir = RAG / "history" / "volume-04" / "chapter-014"
    history_paths = sorted(history_dir.glob("scene-*.yaml"))
    assert len(history_paths) == 17, f"expected 17 history scenes, got {len(history_paths)}"
    history_docs = [json_doc(path) for path in history_paths]
    assert "\n\n".join(value["content"] for value in history_docs) == chapter_source
    for index, value in enumerate(history_docs, start=1):
        meta = value["metadata"]
        assert meta["document_id"] == f"history-v04-c014-s{index:03d}-v1.0"
        assert meta["status"] == "canon"
        assert meta["volume"] == 4 and meta["chapter"] == 14 and meta["scene"] == index
        assert 500 <= len(value["content"]) <= 2800
        expected_previous = "history-v04-c013-s007-v1.0" if index == 1 else f"history-v04-c014-s{index - 1:03d}-v1.0"
        expected_next = None if index == 17 else f"history-v04-c014-s{index + 1:03d}-v1.0"
        assert meta["previous_scene"] == expected_previous
        assert meta["next_scene"] == expected_next
    previous = read(RAG / "history" / "volume-04" / "chapter-013" / "scene-007.yaml")
    assert "next_scene: history-v04-c014-s001-v1.0" in previous

    character = json_doc(RAG / "canon" / "characters" / "li-zhouwei.yaml")
    assert character["metadata"]["document_id"] == "canon-character-li-zhouwei-v1.0"
    profile = character["character"]
    assert profile["retrieval_key"] == "li_zhouwei_profile"
    assert profile["identity"]["class"] == "Lancer"
    assert profile["identity"]["master"] is None
    assert profile["identity"]["parameters"] is None
    assert profile["holy_grail_wish"]["deep"] == "想再见被自己亲手吞噬的孩子们一眼"
    assert len(profile["abilities"]) == 17
    assert not (RAG / "character-state" / "current" / "li-zhouwei.yaml").exists()

    ability_paths = sorted((RAG / "canon" / "abilities").glob("li-zhouwei-*.yaml"))
    assert len(ability_paths) == 17
    for slug in ABILITY_SLUGS:
        path = RAG / "canon" / "abilities" / f"li-zhouwei-{slug}.yaml"
        value = json_doc(path)
        assert value["metadata"]["document_id"] == f"canon-ability-li-zhouwei-{slug}-v1.0"
        ability = value["ability"]
        assert ability["owner_id"] == "li-zhouwei"
        assert ability["effect"] and ability["activation"] and ability["cost"]
        assert isinstance(ability["limitations"], list)
        assert isinstance(ability["failure_conditions"], list)

    for filename, expected_id in CURRENT_IDS.items():
        value = json_doc(RAG / "character-state" / "current" / f"{filename}.yaml")
        assert value["metadata"]["document_id"] == expected_id
        assert value["metadata"]["effective_at"] == "volume-04-chapter-014"
        assert value["metadata"]["status"] == "active"
    amaterasu = json_doc(RAG / "character-state" / "current" / "amaterasu-no-mikoto.yaml")
    assert "退化为普通大小黑金孔雀" in amaterasu["character_state"]["physical"]["injuries"]
    muramasa = json_doc(RAG / "character-state" / "current" / "sengo-muramasa.yaml")
    assert "创造之禊祓" in muramasa["character_state"]["abilities"]["newly_acquired"]
    fujimaru = json_doc(RAG / "character-state" / "current" / "fujimaru-ritsuka.yaml")
    assert "一道令咒（英杰之帜用于杨浞）" in fujimaru["character_state"]["abilities"]["consumed_resources"]

    snapshots = list((RAG / "character-state" / "snapshots" / "volume-04-chapter-013").glob("*.yaml"))
    assert len(snapshots) == 9
    for path in snapshots:
        assert "status: archived" in read(path)
    world_snapshot = read(RAG / "world-state" / "change-logs" / "volume-04-chapter-013-pre-chapter-014.yaml")
    assert "status: archived" in world_snapshot

    world = json_doc(RAG / "world-state" / "current" / "current.yaml")
    assert world["metadata"]["document_id"] == "world-state-current-v1.3"
    assert world["metadata"]["supersedes"] == "world-state-current-v1.2"
    assert "天照命的太阳权能分散为普通日光" in world["world_state"]["global_events"]

    stories = read(LIBRARY / "registry" / "stories.yaml")
    assert "current_chapter: 14" in stories
    variants = read(RAG / "registry" / "character-variants.yaml")
    assert variants.count("  variant_id: li-zhouwei-main\n") == 1
    aliases = read(RAG / "registry" / "aliases.yaml")
    assert aliases.count("- canonical_id: li-zhouwei\n") == 1
    assert "  - 至命天下明阳御世真君" in aliases

    version_map = read(RAG / "registry" / "version-map.yaml")
    assert "current: world-state-current-v1.3" in version_map
    assert "current: state-current-fujimaru-ritsuka-v1.3" in version_map
    assert "current: state-current-qihuang-v1.2" in version_map
    families = ("canon-character-li-zhouwei",) + tuple(f"canon-ability-li-zhouwei-{slug}" for slug in ABILITY_SLUGS)
    for family in families:
        assert version_map.count(f"- document_family: {family}\n") == 1

    retrieval = read(RAG / "retrieval-tests.yaml")
    for case_id in (
        "history-volume-04-chapter-014-defeat",
        "state-amaterasu-after-chapter-014",
        "state-muramasa-creation-misogi",
        "canon-li-zhouwei-profile",
        "canon-li-zhouwei-zhimingchu",
        "canon-li-zhouwei-king-halberd",
    ):
        assert retrieval.count(f"- id: {case_id}\n") == 1
    assert "- state-current-fujimaru-ritsuka-v1.3" in retrieval
    assert "- state-current-qihuang-v1.2" in retrieval

    ids: dict[str, Path] = {}
    count = 0
    for dirname in DOCUMENT_DIRS:
        for path in (RAG / dirname).rglob("*.yaml"):
            text = read(path)
            current_id = document_id(path, text)
            assert current_id not in ids, f"duplicate document_id {current_id}: {ids[current_id]} and {path}"
            ids[current_id] = path
            count += 1
    assert count == 584, f"expected 584 RAG documents, got {count}"
    print(f"chapter14_import=ok scenes={len(history_docs)} li_zhouwei_abilities={len(ability_paths)} documents={count}")


if __name__ == "__main__":
    main()
