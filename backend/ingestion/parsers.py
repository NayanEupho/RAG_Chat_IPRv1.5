import logging
import os
import re
from dataclasses import dataclass, field
from typing import Callable, Dict, List

from backend.config import get_config
from backend.ingestion.quality.gates import analyze_markdown, should_fallback
from backend.ingestion.vision_parser import VisionMarkdownParser, clean_page_markdown
from backend.ingestion.vision_prompts import prompt_for_doc_type

logger = logging.getLogger("rag_chat_ipr.ingestion.parsers")

PARSER_ALIASES = {
    "llm": "auto",
    "vision": "vision_llm",
    "vlm": "vision_llm",
    "vision_llm": "vision_llm",
    "docling": "docling",
    "docling_ocr": "docling_vision",
    "docling_vision": "docling_vision",
    "pymupdf": "pymupdf",
    "fitz": "pymupdf",
    "pymupdf4llm": "pymupdf4llm",
    "pymu": "pymupdf4llm",
    "auto": "auto",
    "markdown": "markdown",
    "md": "markdown",
    "text": "text",
    "fastpath": "text",
}

PDF_PARSERS = {"auto", "vision_llm", "docling", "docling_vision", "pymupdf", "pymupdf4llm"}


def _vlm_configured() -> bool:
    cfg = get_config()
    return bool(cfg.vlm_model and str(cfg.vlm_model).lower() != "false")


@dataclass
class MarkdownParseResult:
    markdown: str
    selected_parser: str
    parser_outputs: Dict[str, str] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)
    fallback_chain: List[str] = field(default_factory=list)


def normalize_parser_mode(mode: str | None) -> str:
    value = (mode or "auto").strip().lower().replace("-", "_")
    return PARSER_ALIASES.get(value, value)


def is_supported_parser(mode: str | None) -> bool:
    return normalize_parser_mode(mode) in set(PARSER_ALIASES.values()) | PDF_PARSERS


def parse_to_markdown(
    file_path: str,
    mode: str,
    doc_type: str,
    converter_factory: Callable[..., object],
    scanned_detector: Callable[[str], bool],
    clean_markdown: Callable[[str], str],
    fix_header_hierarchy: Callable[[str], str],
) -> MarkdownParseResult:
    filename = os.path.basename(file_path)
    ext = os.path.splitext(filename)[1].lower()
    mode = normalize_parser_mode(mode)

    if ext in {".md", ".markdown"}:
        markdown = _read_text(file_path)
        return MarkdownParseResult(markdown=markdown, selected_parser="markdown", parser_outputs={"markdown": markdown})

    if ext == ".txt":
        markdown = _read_text(file_path)
        return MarkdownParseResult(markdown=markdown, selected_parser="text", parser_outputs={"text": markdown})

    if ext != ".pdf":
        markdown = _parse_docling_non_pdf(file_path, converter_factory)
        markdown = _cleanup(markdown, clean_markdown, fix_header_hierarchy)
        return MarkdownParseResult(markdown=markdown, selected_parser="docling", parser_outputs={"docling": markdown})

    if mode not in PDF_PARSERS:
        raise ValueError(f"Unsupported parser mode for PDF: {mode}")

    if mode == "auto":
        return _parse_pdf_auto(file_path, doc_type, converter_factory, scanned_detector, clean_markdown, fix_header_hierarchy)

    parser_outputs: Dict[str, str] = {}
    markdown = _parse_pdf_with_mode(
        file_path=file_path,
        mode=mode,
        doc_type=doc_type,
        converter_factory=converter_factory,
        clean_markdown=clean_markdown,
        fix_header_hierarchy=fix_header_hierarchy,
        parser_outputs=parser_outputs,
    )
    return MarkdownParseResult(markdown=markdown, selected_parser=mode, parser_outputs=parser_outputs)


def _parse_pdf_auto(
    file_path: str,
    doc_type: str,
    converter_factory: Callable[..., object],
    scanned_detector: Callable[[str], bool],
    clean_markdown: Callable[[str], str],
    fix_header_hierarchy: Callable[[str], str],
) -> MarkdownParseResult:
    parser_outputs: Dict[str, str] = {}
    warnings: List[str] = []
    chain: List[str] = []

    needs_ocr = scanned_detector(file_path)
    primary = "docling_vision" if needs_ocr else "docling"

    fallback_modes = [primary, "pymupdf4llm", "pymupdf"]
    if _vlm_configured():
        fallback_modes.append("vision_llm")

    for mode in fallback_modes:
        if mode in chain:
            continue
        chain.append(mode)
        try:
            markdown = _parse_pdf_with_mode(
                file_path=file_path,
                mode=mode,
                doc_type=doc_type,
                converter_factory=converter_factory,
                clean_markdown=clean_markdown,
                fix_header_hierarchy=fix_header_hierarchy,
                parser_outputs=parser_outputs,
            )
            diagnostics = analyze_markdown(markdown, parser=mode, source_type=mode)
            if should_fallback(diagnostics, doc_type=doc_type):
                warnings.append(f"{mode}:quality_gate_failed:{','.join(diagnostics.warnings)}")
                continue
            if _looks_like_failed_table_parse(markdown, diagnostics):
                warnings.append(f"{mode}:table_structure_suspect")
                continue
            return MarkdownParseResult(
                markdown=markdown,
                selected_parser=mode,
                parser_outputs=parser_outputs,
                warnings=warnings,
                fallback_chain=chain,
            )
        except Exception as exc:
            logger.warning("Parser %s failed for %s: %r", mode, file_path, exc)
            warnings.append(f"{mode}:exception:{exc!r}")

    raise RuntimeError(f"All parser backends failed for {file_path}: {warnings}")


def _parse_pdf_with_mode(
    file_path: str,
    mode: str,
    doc_type: str,
    converter_factory: Callable[..., object],
    clean_markdown: Callable[[str], str],
    fix_header_hierarchy: Callable[[str], str],
    parser_outputs: Dict[str, str],
) -> str:
    mode = normalize_parser_mode(mode)
    if mode == "vision_llm":
        markdown, page_outputs = _parse_vision(file_path, doc_type)
        parser_outputs["vision_llm"] = markdown
        parser_outputs.update(page_outputs)
        return markdown

    if mode == "docling":
        markdown = _parse_docling_pdf(file_path, converter_factory, enable_ocr=False, force_ocr=False)
    elif mode == "docling_vision":
        markdown = _parse_docling_pdf(file_path, converter_factory, enable_ocr=True, force_ocr=True)
    elif mode == "pymupdf4llm":
        markdown = _parse_pymupdf4llm(file_path)
    elif mode == "pymupdf":
        markdown = _parse_pymupdf(file_path)
    else:
        raise ValueError(f"Unsupported PDF parser mode: {mode}")

    markdown = _cleanup(markdown, clean_markdown, fix_header_hierarchy)
    if not markdown.strip():
        raise ValueError(f"{mode} produced empty Markdown")
    parser_outputs[mode] = markdown
    return markdown


def _parse_vision(file_path: str, doc_type: str) -> tuple[str, Dict[str, str]]:
    cfg = get_config()
    if not cfg.vlm_model or str(cfg.vlm_model).lower() == "false":
        raise ValueError("VLM parser requires RAG_VLM_MODEL to be configured")
    filename = os.path.basename(file_path)
    logger.info("[VISION_LLM] Parsing %s page-by-page with %s at %s", filename, cfg.vlm_model, cfg.vlm_host)
    parser = VisionMarkdownParser(
        host=cfg.vlm_host,
        model=cfg.vlm_model,
        prompt=prompt_for_doc_type(doc_type, cfg.vlm_prompt),
        dpi=cfg.vlm_dpi,
        timeout_seconds=cfg.vlm_timeout_seconds,
        concurrency=cfg.vlm_concurrency,
        retries=cfg.vlm_retries,
    )
    markdown, pages = parser.parse_pdf(file_path, title=os.path.splitext(filename)[0])
    outputs = {f"vision_page_{page.page_number:03d}": page.markdown for page in pages}
    return markdown, outputs


def _parse_docling_pdf(file_path: str, converter_factory: Callable[..., object], enable_ocr: bool, force_ocr: bool) -> str:
    converter = converter_factory(enable_ocr=enable_ocr, force_ocr=force_ocr, ocr_scale=3.0 if force_ocr else 2.0)
    result = converter.convert(file_path)
    return result.document.export_to_markdown()


def _parse_docling_non_pdf(file_path: str, converter_factory: Callable[..., object]) -> str:
    converter = converter_factory(enable_ocr=True)
    result = converter.convert(file_path)
    return result.document.export_to_markdown()


def _parse_pymupdf4llm(file_path: str) -> str:
    import pymupdf4llm

    return pymupdf4llm.to_markdown(file_path)


def _parse_pymupdf(file_path: str) -> str:
    import fitz

    doc = fitz.open(file_path)
    try:
        pages = []
        for page_number, page in enumerate(doc, start=1):
            page_parts = [f"<!-- page:{page_number} -->", f"## Page {page_number}"]
            table_md = _pymupdf_tables_to_markdown(page)
            text_md = _pymupdf_text_to_markdown(page)
            if text_md:
                page_parts.append(text_md)
            if table_md:
                page_parts.append(table_md)
            pages.append("\n\n".join(page_parts))
        return "\n\n".join(pages).strip() + "\n"
    finally:
        doc.close()


def _pymupdf_text_to_markdown(page) -> str:
    blocks = page.get_text("blocks") or []
    lines = []
    for block in sorted(blocks, key=lambda item: (round(item[1], 1), round(item[0], 1))):
        text = clean_page_markdown(block[4] if len(block) > 4 else "")
        if not text:
            continue
        lines.append(text)
    return "\n\n".join(lines)


def _pymupdf_tables_to_markdown(page) -> str:
    try:
        finder = page.find_tables()
    except Exception:
        return ""
    tables = []
    for table in getattr(finder, "tables", []) or []:
        try:
            rows = table.extract()
        except Exception:
            continue
        md = _rows_to_markdown(rows)
        if md:
            tables.append(md)
    return "\n\n".join(tables)


def _rows_to_markdown(rows) -> str:
    cleaned = []
    for row in rows or []:
        cells = [re.sub(r"\s+", " ", str(cell or "")).strip() for cell in row]
        if any(cells):
            cleaned.append(cells)
    if not cleaned:
        return ""
    width = max(len(row) for row in cleaned)
    padded = [row + [""] * (width - len(row)) for row in cleaned]
    header = padded[0]
    body = padded[1:] if len(padded) > 1 else []
    lines = [
        "| " + " | ".join(_escape_table_cell(cell) for cell in header) + " |",
        "| " + " | ".join("---" for _ in header) + " |",
    ]
    for row in body:
        lines.append("| " + " | ".join(_escape_table_cell(cell) for cell in row) + " |")
    return "\n".join(lines)


def _escape_table_cell(value: str) -> str:
    return (value or "").replace("|", "\\|").replace("\n", "<br>")


def _cleanup(markdown: str, clean_markdown: Callable[[str], str], fix_header_hierarchy: Callable[[str], str]) -> str:
    text = clean_page_markdown(markdown or "")
    text = clean_markdown(text)
    text = fix_header_hierarchy(text)
    return text.strip() + "\n" if text.strip() else ""


def _read_text(file_path: str) -> str:
    return clean_page_markdown(open(file_path, "r", encoding="utf-8", errors="ignore").read())


def _looks_like_failed_table_parse(markdown: str, diagnostics) -> bool:
    if diagnostics.table_row_count >= 5 and diagnostics.broken_table_score > 0.35:
        return True
    short_lines = [line.strip() for line in markdown.splitlines() if line.strip()]
    if len(short_lines) < 8:
        return False
    numeric_only = sum(1 for line in short_lines if re.fullmatch(r"\d{1,3}[.)]?", line))
    return numeric_only / len(short_lines) > 0.25
