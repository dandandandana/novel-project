from __future__ import annotations

import json
from pathlib import Path

import pytest

import novel_rag.mutations.coordinator as coordinator_module
from novel_rag.mutations import atomic_write_bytes, atomic_write_json


def test_atomic_write_json_preserves_unicode_and_legacy_format(tmp_path: Path) -> None:
    """验证 JSON 公共入口保留 Unicode 与既有字节格式。

    依赖：pytest 临时目录和 mutations 公共导出。
    输入：含 Unicode 的映射与临时目标路径。
    输出：文件可往返解析且字节符合既有格式。
    实现：真实写入临时文件并检查内容。
    """
    target = tmp_path / "manifest.json"
    payload = {"z": "雪", "a": "值"}

    atomic_write_json(target, payload)

    assert target.read_bytes() == '{\n  "a": "值",\n  "z": "雪"\n}\n'.encode("utf-8")
    assert json.loads(target.read_text(encoding="utf-8")) == payload


def test_atomic_write_bytes_keeps_existing_target_and_cleans_temp_on_replace_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证替换失败会保留旧目标并清理本次临时文件。

    依赖：pytest monkeypatch 与真实临时文件系统。
    输入：已有目标字节、新字节和模拟失败的替换操作。
    输出：原异常传播，目标不变且临时文件已清理。
    实现：只替换 coordinator 使用的 os.replace 并调用公共入口。
    """
    target = tmp_path / "target.bin"
    target.write_bytes(b"old")

    def fail_replace(_source: str | Path, _destination: str | Path) -> None:
        raise OSError("replace failed")

    monkeypatch.setattr(coordinator_module.os, "replace", fail_replace)

    with pytest.raises(OSError, match="replace failed"):
        atomic_write_bytes(target, b"new")

    assert target.read_bytes() == b"old"
    assert list(tmp_path.glob(".target.bin.*.write")) == []


def test_atomic_write_bytes_uses_independent_temp_names(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证连续写入使用不同的真实同目录临时文件。

    依赖：pytest monkeypatch、Path 和真实 os.replace。
    输入：同一目标的两组字节。
    输出：两次替换来源名称不同且最终目标包含第二组字节。
    实现：记录真实替换的临时来源，再检查目标和名称。
    """
    target = tmp_path / "target.bin"
    source_names: list[str] = []
    real_replace = coordinator_module.os.replace

    def record_replace(source: str | Path, destination: str | Path) -> None:
        source_path = Path(source)
        assert source_path.exists()
        source_names.append(source_path.name)
        real_replace(source, destination)

    monkeypatch.setattr(coordinator_module.os, "replace", record_replace)

    atomic_write_bytes(target, b"first")
    atomic_write_bytes(target, b"second")

    assert len(source_names) == 2
    assert source_names[0] != source_names[1]
    assert target.read_bytes() == b"second"
