from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Chunk:
    ordinal: int
    text: str


def chunk_text(text: str, target_chars: int = 1200, max_chars: int = 2500) -> list[Chunk]:
    """Split at paragraph boundaries; never split a short paragraph mechanically."""
    paragraphs = [part.strip() for part in text.replace("\r\n", "\n").split("\n\n") if part.strip()]
    if not paragraphs:
        return []
    chunks: list[str] = []
    current: list[str] = []
    size = 0
    for paragraph in paragraphs:
        addition = len(paragraph) + (2 if current else 0)
        if current and size + addition > target_chars:
            chunks.append("\n\n".join(current))
            current, size = [], 0
        if len(paragraph) > max_chars:
            # Long structured fields are retained as one unit. Scene-aware importers
            # should create smaller source documents before indexing.
            if current:
                chunks.append("\n\n".join(current))
                current, size = [], 0
            chunks.append(paragraph)
            continue
        current.append(paragraph)
        size += addition
    if current:
        chunks.append("\n\n".join(current))
    return [Chunk(ordinal=index, text=value) for index, value in enumerate(chunks)]

