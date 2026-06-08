import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from backend.ingestion.chunkers.normalized import NormalizedMarkdownChunker


def test_normalized_chunker_skips_toc_and_preserves_section_paths():
    markdown = """
# Technical Report

## Table of Contents
- [1. Overview](#1-overview)
- [2. Details](#2-details)

## 1. Overview

This report explains the system.

### 1.1 Scope

The scope includes Docker and Kubernetes.
"""
    chunks = NormalizedMarkdownChunker(chunk_size=800).chunk(
        markdown,
        file_path="upload_docs/General/report.pdf",
        filename="report.pdf",
        source_type="docling_llm_normalized",
    )

    assert not any(c["metadata"]["section_title"] == "Table of Contents" for c in chunks)
    assert not any("[Source:" in c["text"] for c in chunks)
    assert any(c["metadata"]["normalized"] for c in chunks)
    assert any("Technical Report > 1. Overview > 1.1 Scope" in c["metadata"]["section_path"] for c in chunks)


def test_normalized_chunker_keeps_code_fence_together():
    markdown = """
# Report

## 1. Command

Before running the command:

```bash
kubectl get pods
kubectl describe pod frontend
```

After running it, inspect events.
"""
    chunks = NormalizedMarkdownChunker(chunk_size=260).chunk(
        markdown,
        file_path="upload_docs/General/report.pdf",
        filename="report.pdf",
        source_type="docling_llm_normalized",
    )

    code_chunks = [c for c in chunks if "kubectl get pods" in c["text"]]
    assert len(code_chunks) == 1
    assert code_chunks[0]["text"].count("```") == 2
    assert code_chunks[0]["metadata"]["has_code"]


def test_normalized_chunker_uses_row_chunks_for_table_heavy_docs():
    markdown = """
# IPR Leave rules at glance

| No | Leave Type | Rule |
| :--- | :--- | :--- |
| 11 | Casual Leave (CL) | Maximum of 08 days. Combination of CL with EL is not permitted. |
| 13 | Extra Ordinary Leave (EOL) | EOL with medical certificate or higher studies will count for increment/pension. |
"""
    chunks = NormalizedMarkdownChunker(chunk_size=900).chunk(
        markdown,
        file_path="upload_docs/General/LeaveAtaGlance.pdf",
        filename="LeaveAtaGlance.pdf",
        source_type="docling_llm_normalized",
    )

    table_rows = [c for c in chunks if c["metadata"]["chunk_kind"] == "table_row"]
    assert len(table_rows) == 2
    assert any("Casual Leave" in c["text"] and "not permitted" in c["text"] for c in table_rows)
    assert all(c["metadata"]["table_title"] == "IPR Leave rules at glance" for c in table_rows)
