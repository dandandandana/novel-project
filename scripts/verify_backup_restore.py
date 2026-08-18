from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tempfile
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_snapshot(backup: Path, *, rehearse_restore: bool) -> None:
    manifest_path = backup / "BACKUP-MANIFEST.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    rows = manifest.get("files", [])
    if len(rows) != int(manifest.get("file_count", -1)):
        raise AssertionError("manifest file_count mismatch")

    total_bytes = 0
    for row in rows:
        source = backup / row["path"]
        if not source.is_file():
            raise AssertionError(f"missing backup file: {source}")
        if source.stat().st_size != int(row["bytes"]):
            raise AssertionError(f"backup byte count mismatch: {source}")
        if sha256(source) != row["sha256"]:
            raise AssertionError(f"backup hash mismatch: {source}")
        total_bytes += source.stat().st_size
    if total_bytes != int(manifest["total_bytes"]):
        raise AssertionError("manifest total_bytes mismatch")

    restored_count = 0
    if rehearse_restore:
        with tempfile.TemporaryDirectory(prefix="novel-rag-restore-") as temp_name:
            restore_root = Path(temp_name) / "restored-workspace"
            for row in rows:
                source = backup / row["path"]
                target = restore_root / row["path"]
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
                if sha256(target) != row["sha256"]:
                    raise AssertionError(f"restored hash mismatch: {target}")
                restored_count += 1

    print(
        f"backup_restore=PASS files={len(rows)} bytes={total_bytes} "
        f"restored_files={restored_count} hash_mismatches=0"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify a backup manifest and rehearse restore into a temp directory")
    parser.add_argument("--backup", required=True, type=Path)
    parser.add_argument("--no-restore-rehearsal", action="store_true")
    args = parser.parse_args()
    verify_snapshot(args.backup.resolve(), rehearse_restore=not args.no_restore_rehearsal)


if __name__ == "__main__":
    main()
