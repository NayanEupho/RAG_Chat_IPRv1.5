from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from backend.ingestion.parsers import normalize_parser_mode
from backend.ingestion.processor import DocumentProcessor


def test_parser_mode_aliases():
    assert normalize_parser_mode("vision") == "vision_llm"
    assert normalize_parser_mode("docling-vision") == "docling_vision"
    assert normalize_parser_mode("fitz") == "pymupdf"


def test_general_markdown_upload_uses_direct_markdown_and_section_chunks(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    doc_dir = tmp_path / "upload_docs" / "General"
    doc_dir.mkdir(parents=True)
    md_path = doc_dir / "policy.md"
    md_path.write_text("# Policy\n\n## Scope\n\nThis applies to all users.\n", encoding="utf-8")

    chunks = DocumentProcessor().process_file(str(md_path))

    assert chunks
    assert chunks[0]["metadata"]["parser"] == "markdown"
    assert any("Scope" in chunk["text"] for chunk in chunks)
    run_dirs = list((tmp_path / "generated_doc_md" / "policy" / "markdown").iterdir())
    assert run_dirs
    assert (run_dirs[0] / "selected.md").exists()
    assert (run_dirs[0] / "diagnostics.json").exists()
    assert (run_dirs[0] / "chunks.jsonl").exists()


def test_qna_markdown_upload_uses_direct_markdown_and_qna_chunker(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    qna_dir = tmp_path / "upload_docs" / "QnA"
    qna_dir.mkdir(parents=True)
    md_path = qna_dir / "faq.md"
    md_path.write_text("Q: Who is eligible?\n\nA: Group A officers.\n\n---\n", encoding="utf-8")

    chunks = DocumentProcessor().process_file(str(md_path))

    assert len(chunks) == 1
    assert chunks[0]["metadata"]["doc_type"] == "qna"
    assert chunks[0]["metadata"]["parser"] == "markdown"
    assert "Who is eligible" in chunks[0]["text"]


def test_pymupdf_parser_backend_can_feed_chunking_strategy(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    pdf_path = tmp_path / "upload_docs" / "General" / "table.pdf"
    pdf_path.parent.mkdir(parents=True)
    pdf_path.write_bytes(b"%PDF-1.4\n")

    parsed = SimpleNamespace(
        markdown="# Table\n\n| No | Name | Rule |\n|---|---|---|\n| 1 | CL | Max 8 days |\n| 2 | EL | Earned leave |\n",
        selected_parser="pymupdf",
        parser_outputs={
            "pymupdf": "# Table\n\n| No | Name | Rule |\n|---|---|---|\n| 1 | CL | Max 8 days |\n| 2 | EL | Earned leave |\n"
        },
    )

    with patch("backend.ingestion.processor.parse_to_markdown", return_value=parsed):
        chunks = DocumentProcessor().process_file(str(pdf_path), mode="pymupdf")

    assert chunks
    assert chunks[0]["metadata"]["parser"] == "pymupdf"
    assert any(chunk["metadata"].get("chunk_kind") == "table_row" for chunk in chunks)
    assert any("Max 8 days" in chunk["text"] for chunk in chunks)


def test_pymupdf_table_parser_uses_structure_aware_chunker_not_sparse_general_rows(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    pdf_path = tmp_path / "upload_docs" / "General" / "leave.pdf"
    pdf_path.parent.mkdir(parents=True)
    pdf_path.write_bytes(b"%PDF-1.4\n")
    rows = "\n".join(
        f"| {idx} | Leave Type {idx} | a) Rule text for row {idx}. b) More context. |"
        for idx in range(1, 8)
    )
    markdown = f"# Leave\n\n| No | Leave Type | Rule |\n|---|---|---|\n{rows}\n"
    parsed = SimpleNamespace(markdown=markdown, selected_parser="pymupdf", parser_outputs={"pymupdf": markdown})

    with patch("backend.ingestion.processor.parse_to_markdown", return_value=parsed):
        chunks = DocumentProcessor().process_file(str(pdf_path), mode="pymupdf")

    row_chunks = [chunk for chunk in chunks if chunk["metadata"].get("chunk_kind") == "table_row"]
    assert len(row_chunks) == 7
    assert len(chunks) <= 9


def test_docling_parser_backend_can_feed_section_chunking(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    pdf_path = tmp_path / "upload_docs" / "General" / "report.pdf"
    pdf_path.parent.mkdir(parents=True)
    pdf_path.write_bytes(b"%PDF-1.4\n")

    converter = MagicMock()
    result = MagicMock()
    result.document.export_to_markdown.return_value = "# Report\n\n## Method\n\nThe method is section based.\n"
    converter.convert.return_value = result

    processor = DocumentProcessor()
    processor._get_converter = MagicMock(return_value=converter)

    chunks = processor.process_file(str(pdf_path), mode="docling")

    assert chunks
    assert chunks[0]["metadata"]["parser"] == "docling"
    assert any("Method" in chunk["text"] for chunk in chunks)
