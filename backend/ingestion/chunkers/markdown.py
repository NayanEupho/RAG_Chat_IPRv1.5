from __future__ import annotations

import os
from typing import Any, Dict, List

from backend.ingestion.chunkers.general import GeneralChunker
from backend.ingestion.chunkers.normalized import NormalizedMarkdownChunker
from backend.ingestion.chunkers.qna import QnAChunker
from backend.ingestion.chunkers.vision import VisionChunker


def chunk_markdown_content(
    markdown: str,
    *,
    file_path: str,
    filename: str | None = None,
    doc_type: str = "general",
    source_type: str = "markdown",
    chunk_size: int = 2200,
) -> List[Dict[str, Any]]:
    filename = filename or os.path.basename(file_path)
    effective_doc_type = "qna" if str(doc_type or "").lower() == "qna" else "general"
    content = markdown or ""

    if effective_doc_type == "qna":
        qna_chunks = QnAChunker().chunk(content, file_path)
        if qna_chunks:
            for chunk in qna_chunks:
                chunk["metadata"].setdefault("parser", source_type)
                chunk["metadata"]["doc_type"] = "qna"
                chunk["metadata"]["ingestion_type"] = "qna"
                chunk["metadata"]["chunk_strategy"] = "qna"
            return qna_chunks

    if source_type.endswith("_llm_normalized"):
        chunks = NormalizedMarkdownChunker(chunk_size=chunk_size).chunk(content, file_path, filename, source_type)
    else:
        chunks = VisionChunker(chunk_size=chunk_size).chunk(content, file_path, filename, source_type)
        if not chunks:
            chunks = GeneralChunker(chunk_size=chunk_size).chunk(content, file_path, filename, source_type)

    for chunk in chunks:
        chunk["metadata"].setdefault("parser", source_type)
        chunk["metadata"]["doc_type"] = effective_doc_type
        chunk["metadata"]["ingestion_type"] = effective_doc_type
        chunk["metadata"].setdefault("chunk_strategy", "general")
    return chunks


def chunk_markdown_file(
    file_path: str,
    *,
    filename: str | None = None,
    doc_type: str = "general",
    source_type: str = "markdown",
    chunk_size: int = 2200,
) -> List[Dict[str, Any]]:
    with open(file_path, "r", encoding="utf-8", errors="ignore") as handle:
        return chunk_markdown_content(
            handle.read(),
            file_path=file_path,
            filename=filename,
            doc_type=doc_type,
            source_type=source_type,
            chunk_size=chunk_size,
        )
