from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def write_yaml(path: Path, value: Any) -> Path:
    """依赖：PyYAML 与本地文件系统。输入：目标路径和 YAML 值。输出：已写入路径。实现：建立父目录并以 UTF-8 保存规范 YAML。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(value, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return path


def make_library(tmp_path: Path) -> Path:
    """依赖：write_yaml。输入：pytest 临时目录。输出：含 demo/other 注册的 v2 库根。实现：写布局、作品清单及两本书的 main 时间线注册。"""

    root = tmp_path / "library"
    write_yaml(root / "registry" / "layout.yaml", {"layout_version": "2.0"})
    write_yaml(
        root / "registry" / "stories.yaml",
        {
            "stories": [
                {"story_id": "demo", "title": "Demo"},
                {"story_id": "other", "title": "Other"},
            ]
        },
    )
    for story_id in ("demo", "other"):
        story = root / "stories" / story_id
        write_yaml(
            story / "common" / "registry" / "timelines.yaml",
            {
                "timelines": [
                    {
                        "story_id": story_id,
                        "timeline_id": "main",
                        "parent_timeline_id": None,
                        "divergence_at": None,
                        "divergence_snapshot": None,
                        "status": "active",
                    }
                ]
            },
        )
        (story / "common" / "canon").mkdir(parents=True, exist_ok=True)
        (story / "timelines" / "main" / "history").mkdir(parents=True, exist_ok=True)
    return root


def put_document(
    root: Path,
    document_id: str,
    text: str,
    *,
    story: str = "demo",
    timeline: str = "main",
    category: str = "history",
    volume: int = 1,
    chapter: int = 1,
    scene: int = 1,
    extra_metadata: dict[str, Any] | None = None,
) -> Path:
    """依赖：write_yaml。输入：文档身份、正文、scope、类别和坐标。输出：规范布局中的 YAML 路径。实现：选 common canon 或 timeline 类别并写完整 metadata。"""

    if category == "canon":
        document_type = "canon"
        directory = root / "stories" / story / "common" / "canon"
    elif category in {"summary", "summaries"}:
        document_type = "summary"
        directory = root / "stories" / story / "timelines" / timeline / "summaries"
    else:
        document_type = category.replace("-", "_")
        directory = root / "stories" / story / "timelines" / timeline / category

    metadata: dict[str, Any] = {
        "document_id": document_id,
        "story_id": story,
        "timeline_id": timeline,
        "document_type": document_type,
        "title": document_id,
        "status": "canon",
        "version": "1",
        "source_revision": 1,
        "volume": volume,
        "chapter": chapter,
        "scene": scene,
    }
    if document_type == "summary":
        metadata["ownership"] = "auto"
    if extra_metadata:
        metadata.update(extra_metadata)
    return write_yaml(
        directory / f"{document_id}.yaml",
        {"metadata": metadata, "text": text},
    )
