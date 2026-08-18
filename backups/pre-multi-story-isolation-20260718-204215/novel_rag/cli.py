from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .config import INDEX_PATH, LIBRARY_ROOT
from .index import SqliteIndex
from .service import load_valid_documents


def _paths(args: argparse.Namespace) -> tuple[Path, Path]:
    library = Path(args.library).resolve()
    index = Path(args.index).resolve() if args.index else library / "index" / "rag.db"
    return library, index


def command_validate(args: argparse.Namespace) -> int:
    documents, issues = load_valid_documents(Path(args.library).resolve())
    for issue in issues:
        print(f"ERROR {issue.path}: {issue.message}")
    print(f"校验完成: {len(documents)} 个有效文档, {len(issues)} 个问题")
    return 1 if issues else 0


def command_index(args: argparse.Namespace) -> int:
    library, index_path = _paths(args)
    documents, issues = load_valid_documents(library)
    if issues:
        for issue in issues:
            print(f"ERROR {issue.path}: {issue.message}")
        print("存在校验错误，索引未更新。")
        return 1
    document_count, chunk_count = SqliteIndex(index_path).rebuild(documents)
    print(f"索引完成: {document_count} 个文档, {chunk_count} 个分块 -> {index_path}")
    return 0


def command_search(args: argparse.Namespace) -> int:
    _, index_path = _paths(args)
    results = SqliteIndex(index_path).search(
        args.query, args.story, args.timeline, document_types=args.type, statuses=args.status, limit=args.limit
    )
    output = [{
        "document_id": item.document_id, "title": item.title, "document_type": item.document_type,
        "status": item.status, "score": item.score, "source_file": item.source_file,
        "content": item.content, "metadata": item.metadata,
    } for item in results]
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="小说生成 RAG 管理工具")
    parser.add_argument("--library", default=str(LIBRARY_ROOT), help="知识库根目录")
    parser.add_argument("--index", default=None, help=f"SQLite 索引路径（默认 {INDEX_PATH}）")
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser("validate", help="校验注册表、元数据和引用")
    validate.set_defaults(func=command_validate)
    index = subparsers.add_parser("index", help="校验并重建检索索引")
    index.set_defaults(func=command_index)
    search = subparsers.add_parser("search", help="在指定作品和世界线中检索")
    search.add_argument("query")
    search.add_argument("--story", required=True)
    search.add_argument("--timeline", required=True)
    search.add_argument("--type", action="append", choices=sorted(__import__('novel_rag.config', fromlist=['DOCUMENT_TYPES']).DOCUMENT_TYPES))
    search.add_argument("--status", action="append", help="默认仅 active/canon；显式指定才检索其他状态")
    search.add_argument("--limit", type=int, default=6)
    search.set_defaults(func=command_search)
    return parser


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    args = build_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
