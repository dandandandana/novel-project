"""Story registry alias loading shared by validation and graph projection.

``stories/<story_id>/{common,registry,timelines/*/registry}/aliases.yaml`` is
the canonical identity-alias source.  This module is its only loader; the
graph builder consumes the returned rows as an explicit projection input, so
no second YAML-parsing path may appear elsewhere.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from ..documents import read_yaml_mapping
from .paths import story_registry_roots


def load_story_aliases(
    library_root: str | Path,
    story_id: str,
) -> tuple[dict[str, str], ...]:
    """Load canonical alias rows from every registered registry root.

    Each ``aliases.yaml`` entry declares ``canonical_id``, an optional
    ``timeline_id`` and a list of ``names``.  The loader returns
    deterministic, de-duplicated rows of ``{"entity_id", "alias",
    "timeline_id"}``; an empty ``timeline_id`` means the alias applies to the
    whole story.  Malformed structure raises so a build never projects partial
    identity data.
    """

    rows: dict[tuple[str, str, str], dict[str, str]] = {}
    for registry_root in story_registry_roots(library_root, story_id):
        aliases_path = registry_root / "aliases.yaml"
        if not aliases_path.is_file():
            continue
        data = read_yaml_mapping(aliases_path)
        entries = data.get("aliases", [])
        if not isinstance(entries, list):
            raise ValueError(f"aliases 必须是列表: {aliases_path}")
        for index, entry in enumerate(entries):
            if not isinstance(entry, Mapping):
                raise ValueError(f"aliases[{index}] 必须是映射: {aliases_path}")
            entity_id = str(entry.get("canonical_id", "")).strip()
            if not entity_id:
                raise ValueError(f"aliases[{index}] 缺少 canonical_id: {aliases_path}")
            timeline_id = str(entry.get("timeline_id", "")).strip()
            names = entry.get("names", ())
            if isinstance(names, str):
                names = (names,)
            if not isinstance(names, (list, tuple, set)):
                raise ValueError(f"aliases[{index}].names 必须是列表: {aliases_path}")
            for name in names:
                text = str(name).strip()
                if not text:
                    continue
                key = (text.casefold(), entity_id, timeline_id)
                rows.setdefault(
                    key,
                    {"entity_id": entity_id, "alias": text, "timeline_id": timeline_id},
                )
    return tuple(rows[key] for key in sorted(rows))
