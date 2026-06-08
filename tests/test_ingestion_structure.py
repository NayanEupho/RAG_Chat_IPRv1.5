import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from backend.ingestion.processor import DocumentProcessor
from backend.ingestion.chunkers.general import GeneralChunker, extract_markdown_tables, stable_doc_id
from backend.ingestion.chunkers.qna import QnAChunker
from backend.ingestion.quality.gates import analyze_markdown, should_fallback


def test_hierarchical_chunking_preserves_section_paths():
    processor = DocumentProcessor()
    markdown = """
# Policy Manual

Intro paragraph.

## Eligibility

Applicants must meet service criteria.

### Exceptions

Special cases are reviewed separately.

## Benefits

| Item | Value |
|---|---|
| LTC | Allowed |
"""

    chunks = processor._build_hierarchical_chunks(
        markdown,
        file_path="upload_docs/General/policy.pdf",
        filename="policy.pdf",
        chunk_size=500,
        chunk_overlap=80,
    )

    paths = [c["metadata"]["section_path"] for c in chunks]
    assert "Policy Manual" in paths
    assert "Policy Manual > Eligibility" in paths
    assert "Policy Manual > Eligibility > Exceptions" in paths
    assert "Policy Manual > Benefits" in paths
    assert any(c["metadata"]["has_table"] for c in chunks)
    assert all(c["metadata"]["doc_id"] for c in chunks)


def test_heading_inference_repairs_pdf_like_headings():
    processor = DocumentProcessor()
    markdown = """
GENERAL PENSION RULES

The pension policy applies to eligible employees.

1.1 Eligibility Criteria

Service period requirements are defined here.
"""
    normalized = processor._normalize_markdown_structure(markdown)

    assert "## GENERAL PENSION RULES" in normalized
    assert "### 1.1 Eligibility Criteria" in normalized


def test_table_chunker_preserves_leave_table_rows():
    markdown = """
_**IPR Leave rules at glance**_

|**11.**<br>_Casual Leave (CL):-_<br>_a) Maximum of 08 days of casual leave is granted during a calendar year._<br>_f) Combination of CL with EL is not permitted._<br>|**11.**<br>_Casual Leave (CL):-_<br>_a) Maximum of 08 days of casual leave is granted during a calendar year._<br>_f) Combination of CL with EL is not permitted._<br>|
|---|---|
|**13.** Extra Ordinary Leave (EOL):-<br>d) EOL with medical certificate or for prosecuting higher studies will count for increment/pension.<br>e) EOL without medical certificate will not count for pension/increment/ net qualifying service.|Col2|
"""
    chunks = GeneralChunker(chunk_size=1200).chunk(
        markdown,
        file_path="upload_docs/General/LeaveAtaGlance.pdf",
        filename="LeaveAtaGlance.pdf",
        source_type="pymupdf4llm",
    )

    table_chunks = [c for c in chunks if c["metadata"]["chunk_kind"] == "table_row"]

    assert len(table_chunks) == 2
    assert all(c["metadata"]["has_table"] for c in table_chunks)
    assert any("Casual Leave" in c["text"] and "08 days" in c["text"] for c in table_chunks)
    assert any("Extra Ordinary Leave" in c["text"] and "pension" in c["text"] for c in table_chunks)
    assert not any("Col2" in c["text"] for c in table_chunks)


def test_general_chunker_keeps_narrative_sections_when_doc_has_tables():
    markdown = """
# ADG-1

## 1. Introduction

### 1.1 Purpose

This Software Requirements Specification document defines what the IPR website will do and how it will work.

Objective & Value to IPR:

1. Acts as a single source of truth for design, development, deployment, testing, and acceptance.

### 1.3 Definitions

| Term | Description |
| :--- | :--- |
| IPR | Institute for Plasma Research |
| GIGW | Guidelines for Indian Government Websites |
"""
    chunks = GeneralChunker(chunk_size=1200).chunk(
        markdown,
        file_path="upload_docs/General/ADG-1.pdf",
        filename="ADG-1.pdf",
        source_type="vision_llm",
    )

    assert not any(c["metadata"]["chunk_kind"] == "table_row" for c in chunks)
    assert any(c["metadata"]["section_title"] == "1.1 Purpose" for c in chunks)
    assert any("single source of truth" in c["text"] for c in chunks)
    assert any("Term: IPR; Description: Institute for Plasma Research" in c["text"] for c in chunks)


def test_markdown_table_diagnostics_flags_broken_tables():
    markdown = """
|A|Col2|
|---|---|
|same|same|
|valid|value|
"""
    diagnostics = analyze_markdown(markdown, parser="docling")

    assert diagnostics.table_count == 1
    assert diagnostics.table_row_count == 4
    assert "table_structure_suspect" in diagnostics.warnings


def test_markdown_diagnostics_flags_numbered_row_gaps():
    markdown = """
| No | Type | Rule |
|---|---|---|
| 1 | A | Rule |
| 2 | B | Rule |
| 3 | C | Rule |
| 5 | E | Rule |
| 6 | F | Rule |
| 8 | H | Rule |
"""

    diagnostics = analyze_markdown(markdown, parser="pymupdf4llm")

    assert "numbered_row_gaps" in diagnostics.warnings
    assert should_fallback(diagnostics, doc_type="general")
    assert should_fallback(diagnostics, doc_type="general")


def test_qna_chunker_keeps_pairs_atomic():
    markdown = """
Q1: What is LTDP?
A: It is a training programme.

Q2: Who is eligible?
A: Group A officers are eligible.
"""
    chunks = QnAChunker().chunk(markdown, "upload_docs/QnA/faq.pdf")

    assert len(chunks) == 2
    assert all(c["metadata"]["doc_type"] == "qna" for c in chunks)
    assert chunks[0]["metadata"]["qa_pair_id"] == "faq_q1"
    assert "Who is eligible" in chunks[1]["text"]


def test_doc_id_is_stable_for_absolute_and_relative_paths():
    rel = "upload_docs/General/LeaveAtaGlance.pdf"
    abs_path = os.path.abspath(rel)

    assert stable_doc_id(rel) == stable_doc_id(abs_path)
