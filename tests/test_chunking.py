from novel_rag.chunking import chunk_text


def test_chunking_keeps_paragraphs_intact():
    chunks = chunk_text("第一段。\n\n第二段比较长。\n\n第三段。", target_chars=10)
    assert [chunk.text for chunk in chunks] == ["第一段。", "第二段比较长。", "第三段。"]


def test_empty_text_has_no_chunks():
    assert chunk_text("  \n\n ") == []

