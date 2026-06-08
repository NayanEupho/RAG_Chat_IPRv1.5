from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from backend.ingestion.chunkers.vision import VisionChunker
from backend.ingestion.processor import DocumentProcessor
from backend.ingestion.vision_parser import VisionPage, clean_page_markdown, merge_page_markdown, remove_model_commentary, response_content
from backend.ingestion.vision_prompts import prompt_for_doc_type


def test_clean_page_markdown_removes_fences():
    assert clean_page_markdown("```markdown\n# Title\n\nText\n```") == "# Title\n\nText"


def test_clean_page_markdown_normalizes_common_ocr_mojibake():
    text = "The â€˜official passportâ€™ fee â€” if any â€“ is listed as Â Rs. 0â€¦"
    assert clean_page_markdown(text) == "The 'official passport' fee - if any - is listed as Rs. 0..."


def test_clean_page_markdown_normalizes_smart_punctuation():
    text = "The ‘official passport’ fee — if any – is listed as Rs. 0…"
    assert clean_page_markdown(text) == "The 'official passport' fee - if any - is listed as Rs. 0..."


def test_clean_page_markdown_normalizes_ui_symbols():
    text = "🔍 Connecting\n🚀 Agent Mode\n🛠 Tool\n🤖 Agent\n💭 Thought\n💡 Hint\n🔴 CrashLoopBackOff\n🌐 Web"
    assert clean_page_markdown(text) == (
        "[search] Connecting\n"
        "[rocket] Agent Mode\n"
        "[tool] Tool\n"
        "[agent] Agent\n"
        "[thought] Thought\n"
        "[idea] Hint\n"
        "[red] CrashLoopBackOff\n"
        "[web] Web"
    )


def test_clean_page_markdown_removes_model_commentary():
    text = """Here is your data in a clean table format:

| Term | Description |
| --- | --- |
| IPR | Institute for Plasma Research |

Page number: 1

If you want, I can also format it for Word.
This should not remain.
"""
    cleaned = clean_page_markdown(text)

    assert "Here is your data" not in cleaned
    assert "Page number:" not in cleaned
    assert "If you want" not in cleaned
    assert "This should not remain" not in cleaned
    assert "| IPR | Institute for Plasma Research |" in cleaned


def test_merge_page_markdown_preserves_page_anchors():
    merged = merge_page_markdown(
        [
            VisionPage(page_number=1, markdown="# A\nText", image_b64="x"),
            VisionPage(page_number=2, markdown="| Col |\n|---|\n| V |", image_b64="y"),
        ],
        title="Doc",
    )

    assert "# Doc" in merged
    assert "<!-- page:1 -->" in merged
    assert "## Page 2" in merged
    assert "| Col |" in merged


def test_response_content_supports_typed_ollama_response():
    response = SimpleNamespace(message=SimpleNamespace(content="# Page\nText"))
    assert response_content(response) == "# Page\nText"


def test_prompt_profiles_select_qna_and_visual_rules():
    qna_prompt = prompt_for_doc_type("qna", "auto", page_number=2)
    general_prompt = prompt_for_doc_type("general", "auto", page_number=3)

    assert "Q: <question>" in qna_prompt
    assert "Separate Q&A pairs" in qna_prompt
    assert "[Visual:" in qna_prompt
    assert "Preserve tables as Markdown tables" in general_prompt
    assert "page {page_number}" in general_prompt


def test_processor_vision_llm_mode_reuses_table_chunker(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    pdf_path = tmp_path / "LeaveAtaGlance.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")

    cfg = SimpleNamespace(
        parsing_mode="vision_llm",
        vlm_host="http://localhost:11434",
        vlm_model="gemma4:latest",
        vlm_prompt="auto",
        vlm_dpi=180,
        vlm_timeout_seconds=60,
        vlm_concurrency=1,
        vlm_retries=1,
        ingest_force_cpu=True,
    )
    markdown = """# Leave Rules

| No | Leave Type | Rule |
|---|---|---|
| 11 | Casual Leave (CL) | Maximum 08 days. CL with EL is not permitted. |
| 13 | Extra Ordinary Leave (EOL) | EOL with medical certificate counts for pension. |
"""
    parser_instance = MagicMock()
    parser_instance.parse_pdf.return_value = (
        markdown,
        [VisionPage(page_number=1, markdown=markdown, image_b64="abc")],
    )

    with patch("backend.ingestion.processor.get_config", return_value=cfg), patch(
        "backend.ingestion.processor.VisionMarkdownParser", return_value=parser_instance
    ):
        chunks = DocumentProcessor().process_file(str(pdf_path))

    assert chunks
    assert chunks[0]["metadata"]["parser"] == "vision_llm"
    assert any(chunk["metadata"].get("chunk_kind") == "table_row" for chunk in chunks)
    assert any("Casual Leave" in chunk["text"] for chunk in chunks)
    assert any("Maximum 08 days" in chunk["text"] for chunk in chunks)

    run_dirs = list((tmp_path / "generated_doc_md" / "LeaveAtaGlance" / "vision_llm").iterdir())
    assert run_dirs
    assert (run_dirs[0] / "selected.md").exists()
    assert (run_dirs[0] / "vision_parsed_pages" / "page_001.md").exists()


def test_processor_vision_llm_qna_uses_qna_prompt_and_chunker(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    qna_dir = tmp_path / "upload_docs" / "QnA"
    qna_dir.mkdir(parents=True)
    pdf_path = qna_dir / "FAQ.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")

    cfg = SimpleNamespace(
        parsing_mode="vision_llm",
        vlm_host="http://localhost:11434",
        vlm_model="gemma4:latest",
        vlm_prompt="auto",
        vlm_dpi=180,
        vlm_timeout_seconds=60,
        vlm_concurrency=1,
        vlm_retries=1,
        ingest_force_cpu=True,
    )
    markdown = """Q: Who is eligible?

A: Group A officers are eligible.

---

Q: How many seats are available?

A: 30 seats are available.
"""
    parser_instance = MagicMock()
    parser_instance.parse_pdf.return_value = (
        markdown,
        [VisionPage(page_number=1, markdown=markdown, image_b64="abc")],
    )

    with patch("backend.ingestion.processor.get_config", return_value=cfg), patch(
        "backend.ingestion.processor.VisionMarkdownParser", return_value=parser_instance
    ) as parser_cls:
        chunks = DocumentProcessor().process_file(str(pdf_path))

    prompt = parser_cls.call_args.kwargs["prompt"]
    assert "Q: <question>" in prompt
    assert chunks
    assert all(chunk["metadata"].get("doc_type") == "qna" for chunk in chunks)
    assert any("Who is eligible" in chunk["text"] for chunk in chunks)


def test_vision_chunker_extracts_numbered_rows_without_tables(tmp_path):
    markdown = """# LeaveAtaGlance

<!-- page:2 -->

## Page 2

11. Casual Leave (CL):-
    a) Maximum of 08 days of casual leave is granted during a calendar year.
    f) Combination of CL with EL is not permitted.

12. Restricted Holiday (RH):
    a) Maximum of 02 days of RH is sanctioned.

<!-- page:3 -->

## Page 3

13. Extra Ordinary Leave (EOL):-
    d) EOL with medical certificate or for prosecuting higher studies will count for increment/pension.
    e) EOL without medical certificate will not count for increment/ pension/ net qualifying service.
"""

    chunks = VisionChunker().chunk(markdown, str(tmp_path / "LeaveAtaGlance.pdf"), "LeaveAtaGlance.pdf")

    row_chunks = [chunk for chunk in chunks if chunk["metadata"].get("chunk_kind") == "table_row"]
    assert len(row_chunks) == 3
    assert any("Casual Leave" in chunk["text"] and "CL with EL is not permitted" in chunk["text"] for chunk in row_chunks)
    assert any(chunk["metadata"]["section_path"].startswith("Page 3") and "Extra Ordinary Leave" in chunk["text"] for chunk in row_chunks)


def test_vision_chunker_removes_markdown_emphasis_from_row_terms(tmp_path):
    markdown = """# Leave

<!-- page:4 -->

## Page 4

19. _Study Leave:-_
    _a) An employee who has completed probation and five years of service is eligible._
"""

    chunks = VisionChunker().chunk(markdown, str(tmp_path / "LeaveAtaGlance.pdf"), "LeaveAtaGlance.pdf", source_type="pymupdf4llm")

    assert any("Study Leave" in chunk["text"] for chunk in chunks)
    assert not any("_Study Leave" in chunk["text"] for chunk in chunks)


def test_vision_chunker_uses_general_chunks_for_short_numbered_lists(tmp_path):
    markdown = """# SRS

<!-- page:1 -->

## Page 1

### 1.1 Purpose

Objective:

1. Acts as a single source of truth.
2. Reduces ambiguity.
3. Enables audit readiness.
4. Supports future maintenance.

### 1.2 Scope

The scope includes design, development, testing, and deployment.
"""

    chunks = VisionChunker().chunk(markdown, str(tmp_path / "ADG-1.pdf"), "ADG-1.pdf")

    assert chunks
    assert not any(chunk["metadata"].get("chunk_kind") == "table_row" for chunk in chunks)
    assert any("1.1 Purpose" in chunk["text"] for chunk in chunks)


def test_vision_chunker_uses_general_chunks_for_numbered_toc_and_sections(tmp_path):
    markdown = """# Technical Report

<!-- page:3 -->

## Page 3

1. Executive Summary ................................................ 5
2. Technology Stack Overview ........................................ 10
3. Future Enhancements .............................................. 38
4. Conclusion ...................................................... 39

<!-- page:10 -->

## Page 10

# 4. Technology Stack Overview

The system uses a layered architecture with an interface layer, intelligence
layer, communication layer, and execution layer.

[Visual: diagram | page 10]
Title: Stack Overview
Visible text: Interface Layer, Intelligence Layer, Execution Layer
Axes/units: [not applicable]
Legend: [none]
Data/trend: [not applicable]
Relationships: Interface connects to intelligence, which connects to execution.
Short description: Layered architecture diagram.
Unclear: [none]
[/Visual]
"""

    chunks = VisionChunker().chunk(markdown, str(tmp_path / "TECHNICAL_REPORT_V8.pdf"), "TECHNICAL_REPORT_V8.pdf")

    assert not any(chunk["metadata"].get("chunk_kind") == "table_row" for chunk in chunks)
    assert any(chunk["metadata"].get("chunk_kind") == "visual" for chunk in chunks)
    assert any("Technology Stack Overview" in chunk["text"] for chunk in chunks)


def test_vision_chunker_ignores_numbered_toc_tables(tmp_path):
    markdown = """# Technical Report

| Topic | Page No. |
| :--- | :--- |
| 1. Executive Summary & Problem Definition | 2 |
| 2. Architectural Philosophy: The Agentic Approach | 3 |
| 3. Fundamentals: Understanding the Building Blocks | 5 |
| 4. Technology Stack Overview | 7 |

## 4. Technology Stack Overview

The stack uses Typer, DSPy, Ollama, JSON-RPC, Docker, and Kubernetes.
"""

    chunks = VisionChunker().chunk(markdown, str(tmp_path / "TECHNICAL_REPORT_V8.pdf"), "TECHNICAL_REPORT_V8.pdf")

    assert not any(chunk["metadata"].get("chunk_kind") == "table_row" for chunk in chunks)
    assert any("Typer" in chunk["text"] for chunk in chunks)
    assert not any("Executive Summary & Problem Definition | 2" in chunk["text"] for chunk in chunks)


def test_vision_chunker_uses_body_chunks_for_research_paper_with_numeric_tables(tmp_path):
    markdown = """# Attention Is All You Need

## Abstract

The Transformer is based solely on attention mechanisms.

## 1 Introduction

Recurrent neural networks have been used for sequence modeling.

## 3 Model Architecture

The encoder and decoder use self-attention.

Table 1: Maximum path lengths.

| Layer Type | Complexity per Layer | Sequential Operations | Maximum Path Length |
|---|---|---|---|
| Self-Attention | O(n^2 d) | O(1) | O(1) |
| Recurrent | O(n d^2) | O(n) | O(n) |

Table 3: Model variations.

| N | d_model | d_ff | h | P_drop |
|---|---|---|---|---|
| 6 | 512 | 2048 | 8 | 0.1 |
| 2 | 128 | 512 | 4 | 0.1 |

## 7 Conclusion

Attention mechanisms are effective for transduction models.
"""

    chunks = VisionChunker().chunk(markdown, str(tmp_path / "paper.pdf"), "paper.pdf", source_type="docling")

    assert not any(chunk["metadata"].get("chunk_kind") == "table_row" for chunk in chunks)
    assert any("Abstract" in chunk["text"] and "Transformer" in chunk["text"] for chunk in chunks)
    assert any("Conclusion" in chunk["text"] for chunk in chunks)


def test_vision_chunker_linearizes_non_toc_tables_for_narrative_docs(tmp_path):
    markdown = """# CLI Commands

| Command | Description |
| :--- | :--- |
| devops-agent run "<query>" | Execute a single natural language query. |
| devops-agent chat | Start an interactive session. |

The CLI also supports session management.
"""

    chunks = VisionChunker().chunk(markdown, str(tmp_path / "TECHNICAL_REPORT_V8.pdf"), "TECHNICAL_REPORT_V8.pdf")

    assert not any(chunk["metadata"].get("chunk_kind") == "table_row" for chunk in chunks)
    assert any("Command: devops-agent run" in chunk["text"] for chunk in chunks)
    assert any("The CLI also supports session management" in chunk["text"] for chunk in chunks)


def test_vision_chunker_extracts_visual_and_image_blocks(tmp_path):
    markdown = """# Report

<!-- page:4 -->

## Page 4

[Visual: chart | page 4]
Title: Revenue Growth
Visible text: FY2024, FY2025
Axes/units: Y axis in INR crore
Legend: Product A, Product B
Data/trend: upward trend
Relationships: [not applicable]
Short description: Bar chart comparing product revenue.
Unclear: exact values are unclear
[/Visual]

[Image description | page 4]
Short description: Logo in the page footer.
Visible text: IPR
Unclear: [none]
[/Image description]
"""

    chunks = VisionChunker().chunk(markdown, str(tmp_path / "report.pdf"), "report.pdf")
    visuals = [chunk for chunk in chunks if chunk["metadata"].get("chunk_kind") in {"visual", "image"}]

    assert len(visuals) == 2
    assert visuals[0]["metadata"]["visual_type"] == "chart"
    assert visuals[0]["metadata"]["page_number"] == 4
    assert "Revenue Growth" in visuals[0]["text"]
    assert visuals[1]["metadata"]["chunk_kind"] == "image"
