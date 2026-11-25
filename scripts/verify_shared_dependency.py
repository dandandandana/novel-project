from __future__ import annotations

from pathlib import Path


from novel_rag.documents import read_yaml_mapping
from novel_rag.graph.reader import GraphReader, open_read_only
from novel_rag.graph.shared import SharedReader
from novel_rag.graph.types import ModuleGraphIndex
from novel_rag.identity import GraphKey


LIBRARY_ROOT = Path(__file__).resolve().parents[1] / "novel-rag"
INDEX_ROOT = LIBRARY_ROOT / "index"
STORY_TIMELINES = (
    ("overturned-world-fujimaru", "main"),
    ("shirouxcile", "main"),
)


def manifest_source_fingerprint(db_path: Path, table: str) -> str:
    """Read the recorded source_fingerprint via a raw read-only connection."""

    connection = open_read_only(db_path)
    try:
        row = connection.execute(
            f"SELECT source_fingerprint FROM {table} WHERE id = 1"
        ).fetchone()
    finally:
        connection.close()
    if row is None:
        raise AssertionError(f"{db_path} 缺少 {table} id=1")
    fingerprint = str(row["source_fingerprint"])
    if not fingerprint.startswith("sha256:"):
        raise AssertionError(f"{db_path} source_fingerprint 不是 sha256: {fingerprint!r}")
    return fingerprint


def main() -> None:
    layout = read_yaml_mapping(LIBRARY_ROOT / "registry" / "layout.yaml")
    if not layout.get("layout_version"):
        raise AssertionError(f"library layout.yaml 缺少 layout_version: {LIBRARY_ROOT}")
    print(f"library_root={LIBRARY_ROOT}")

    shared_db = INDEX_ROOT / "shared.db"
    expected_shared_fp = manifest_source_fingerprint(shared_db, "shared_manifest")
    print(f"shared_source_fingerprint={expected_shared_fp}")

    manifests = []
    graph_readers = []
    try:
        with SharedReader(
            shared_db,
            expected_key=GraphKey.shared(),
            expected_fingerprint=expected_shared_fp,
        ) as shared_reader:
            for story_id, timeline_id in STORY_TIMELINES:
                graph_path = INDEX_ROOT / "graphs" / story_id / f"{timeline_id}.db"
                expected_fp = manifest_source_fingerprint(graph_path, "graph_manifest")
                reader = GraphReader(
                    graph_path,
                    expected_key=GraphKey(story_id, timeline_id),
                    expected_fingerprint=expected_fp,
                )
                graph_readers.append(reader)
                manifest = reader.manifest()
                if manifest.key != GraphKey(story_id, timeline_id):
                    raise AssertionError(f"{graph_path} manifest 身份不一致: {manifest.key.as_dict()}")
                manifests.append(manifest)
                print(
                    f"graph_manifest story_id={story_id} timeline_id={timeline_id} "
                    f"source_fingerprint={expected_fp} module_references={len(manifest.module_references)}"
                )

            keys_first = shared_reader.dependent_graph_keys(manifests)
            keys_second = shared_reader.dependent_graph_keys(manifests)
            if keys_first != keys_second:
                raise AssertionError(
                    f"dependent_graph_keys 不确定: {keys_first} != {keys_second}"
                )
            if not isinstance(keys_first, tuple):
                raise AssertionError(f"dependent_graph_keys 必须返回 tuple: {type(keys_first)!r}")
            keys = list(keys_first)
            if keys != sorted(keys):
                raise AssertionError(f"dependent_graph_keys 未按确定顺序排序: {keys}")
            unexpected = [key for key in keys if key not in {m.key for m in manifests}]
            if unexpected:
                raise AssertionError(f"dependent_graph_keys 含清单之外的 GraphKey: {unexpected}")
            print(f"dependent_graph_keys={[str(key) for key in keys]}")

            index = ModuleGraphIndex.from_manifests(manifests)
            zero_map_references = 0
            checked_references = 0
            for manifest in manifests:
                for reference in manifest.module_references:
                    module_type = str(reference.get("module_type", ""))
                    document_id = str(reference.get("document_id", ""))
                    mapped = index.graph_keys_for_module(module_type, document_id)
                    checked_references += 1
                    if not mapped:
                        zero_map_references += 1
                        print(
                            "zero_map_reference "
                            f"story_id={manifest.story_id} module_type={module_type} "
                            f"document_id={document_id}"
                        )
                    else:
                        print(
                            "reverse_reference_ok "
                            f"story_id={manifest.story_id} module_type={module_type} "
                            f"document_id={document_id} graph_keys={[str(k) for k in mapped]}"
                        )
            print(f"checked_references={checked_references}")
    finally:
        for reader in graph_readers:
            reader.close()

    print(
        f"shared_dependency=PASS dependent_graph_keys={len(keys)} "
        f"zero_map_references={zero_map_references}"
    )


if __name__ == "__main__":
    main()
