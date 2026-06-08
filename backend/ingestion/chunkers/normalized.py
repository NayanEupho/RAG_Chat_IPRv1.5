import html
import re
from dataclasses import dataclass
from typing import Any, Dict, List

from backend.ingestion.chunkers.general import extract_markdown_tables, stable_doc_id


@dataclass
class MarkdownBlock:
    kind: str
    text: str
    start_line: int
    end_line: int


def _plain(text: str) -> str:
    text = html.unescape(text or "")
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"</?[^>]+>", "", text)
    text = re.sub(r"\*\*", "", text)
    text = re.sub(r"~~", "", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return re.sub(r"[ \t]{2,}", " ", text).strip()


def _truncate(text: str, limit: int = 120) -> str:
    text = re.sub(r"\s+", " ", _plain(text)).strip(" .:-")
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].strip(" .:-")


def _split_table_cells(row: str) -> List[str]:
    return [_plain(cell) for cell in row.strip().strip("|").split("|")]


def _is_separator(cells: List[str]) -> bool:
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", c.replace(" ", "")) for c in cells if c)


def _table_rows(table: str) -> List[List[str]]:
    rows = []
    for raw in table.splitlines():
        cells = [cell for cell in _split_table_cells(raw) if cell]
        if cells and not _is_separator(cells):
            rows.append(cells)
    return rows


def _row_title(row: List[str], fallback: str) -> str:
    joined = " ".join(row)
    match = re.search(r"\b(\d{1,2})[.)]?\s+([A-Z][A-Za-z ]{2,120}(?:\([A-Z]+\))?)", joined)
    if match:
        return _truncate(f"{match.group(1)}. {match.group(2)}")
    return _truncate(joined or fallback)


class NormalizedMarkdownChunker:
    """Structure-aware chunker for LLM-normalized Markdown."""

    def __init__(self, chunk_size: int = 2200):
        self.chunk_size = chunk_size

    def chunk(self, markdown: str, file_path: str, filename: str, source_type: str = "docling_llm_normalized") -> List[Dict[str, Any]]:
        doc_id = stable_doc_id(file_path)
        blocks = self._blocks(markdown)
        title = self._document_title(blocks) or filename

        chunks: List[Dict[str, Any]] = []
        summary = self._summary_chunk(blocks, file_path, filename, doc_id, source_type, title)
        if summary:
            chunks.append(summary)

        if self._should_use_table_rows(markdown):
            chunks.extend(self._table_row_chunks(markdown, file_path, filename, doc_id, source_type, start_index=len(chunks), title=title))
            self._link_indices(chunks)
            return chunks

        chunks.extend(self._section_chunks(blocks, file_path, filename, doc_id, source_type, start_index=len(chunks), title=title))
        self._link_indices(chunks)
        return chunks

    def _blocks(self, markdown: str) -> List[MarkdownBlock]:
        lines = (markdown or "").splitlines()
        blocks: List[MarkdownBlock] = []
        current: List[str] = []
        current_start = 1
        in_code = False
        in_table = False
        current_kind = "paragraph"

        def flush(end_line: int) -> None:
            nonlocal current, current_start, current_kind, in_table
            if current:
                blocks.append(MarkdownBlock(current_kind, "\n".join(current).strip(), current_start, end_line))
                current = []
            in_table = False

        for idx, line in enumerate(lines, start=1):
            stripped = line.strip()
            if stripped.startswith("```"):
                if not current:
                    current_start = idx
                    current_kind = "code"
                current.append(line)
                in_code = not in_code
                if not in_code:
                    flush(idx)
                continue

            if in_code:
                current.append(line)
                continue

            heading = re.match(r"^(#{1,6})\s+(.+)$", stripped)
            if heading:
                flush(idx - 1)
                blocks.append(MarkdownBlock("heading", stripped, idx, idx))
                current_start = idx + 1
                current_kind = "paragraph"
                continue

            is_table = stripped.startswith("|")
            if is_table:
                if current and not in_table:
                    flush(idx - 1)
                if not current:
                    current_start = idx
                    current_kind = "table"
                in_table = True
                current.append(line)
                continue

            if in_table:
                flush(idx - 1)

            if not stripped:
                flush(idx - 1)
                current_start = idx + 1
                current_kind = "paragraph"
                continue

            kind = "figure" if re.match(r"^\[(?:Figure|Visual|Image description)\b", stripped, re.I) else "paragraph"
            if current and current_kind != kind:
                flush(idx - 1)
            if not current:
                current_start = idx
                current_kind = kind
            current.append(line)

        flush(len(lines))
        return [block for block in blocks if block.text]

    def _document_title(self, blocks: List[MarkdownBlock]) -> str:
        for block in blocks:
            if block.kind == "heading":
                match = re.match(r"^#\s+(.+)$", block.text)
                if match:
                    return _truncate(match.group(1), 160)
        return ""

    def _summary_chunk(self, blocks: List[MarkdownBlock], file_path: str, filename: str, doc_id: str, source_type: str, title: str) -> Dict[str, Any] | None:
        headings = []
        intro = []
        in_toc = False
        for block in blocks:
            if block.kind == "heading":
                heading_text = re.sub(r"^#{1,6}\s+", "", block.text).strip()
                if heading_text.lower() in {"table of contents", "contents"}:
                    in_toc = True
                    continue
                in_toc = False
                if re.match(r"^\d+(?:\.\d+)*\.?\s+", heading_text):
                    headings.append(heading_text)
                continue
            if in_toc:
                continue
            if block.kind in {"paragraph", "figure"} and len(intro) < 3:
                intro.append(_plain(block.text))
        summary = f"{title}\n\n"
        if headings:
            summary += "Key sections: " + "; ".join(headings[:16]) + "\n\n"
        if intro:
            summary += "\n\n".join(intro)
        summary = summary.strip()
        if not summary:
            return None
        return self._make_chunk(
            text=summary[:1800],
            file_path=file_path,
            filename=filename,
            doc_id=doc_id,
            source_type=source_type,
            chunk_index=0,
            chunk_kind="doc_summary",
            section_title="Document Summary",
            section_path="Document Summary",
            parent_section="",
            heading_level=0,
            blocks=[],
            start_line=0,
            end_line=0,
            normalized=source_type.endswith("_llm_normalized"),
        )

    def _section_chunks(self, blocks: List[MarkdownBlock], file_path: str, filename: str, doc_id: str, source_type: str, start_index: int, title: str) -> List[Dict[str, Any]]:
        chunks: List[Dict[str, Any]] = []
        heading_stack: Dict[int, str] = {}
        current_blocks: List[MarkdownBlock] = []
        section_title = title
        section_path = title
        parent_section = ""
        heading_level = 1
        in_toc = False

        def flush() -> None:
            nonlocal current_blocks
            if not current_blocks:
                return
            for text, part_blocks in self._pack_blocks(section_path, section_title, current_blocks):
                chunks.append(self._make_chunk(
                    text=text,
                    file_path=file_path,
                    filename=filename,
                    doc_id=doc_id,
                    source_type=source_type,
                    chunk_index=start_index + len(chunks),
                    chunk_kind="section_fragment" if len(text) > self.chunk_size else self._chunk_kind(part_blocks),
                    section_title=section_title,
                    section_path=section_path,
                    parent_section=parent_section,
                    heading_level=heading_level,
                    blocks=part_blocks,
                    start_line=min(b.start_line for b in part_blocks),
                    end_line=max(b.end_line for b in part_blocks),
                    normalized=source_type.endswith("_llm_normalized"),
                ))
            current_blocks = []

        for block in blocks:
            if block.kind == "heading":
                heading_match = re.match(r"^(#{1,6})\s+(.+)$", block.text)
                if not heading_match:
                    continue
                level = len(heading_match.group(1))
                text = _truncate(heading_match.group(2), 160)
                if text.lower() in {"table of contents", "contents"}:
                    flush()
                    in_toc = True
                    continue
                in_toc = False
                flush()
                heading_stack[level] = text
                for existing in list(heading_stack):
                    if existing > level:
                        del heading_stack[existing]
                section_title = text
                section_path = " > ".join(heading_stack[k] for k in sorted(heading_stack))
                parent_keys = [k for k in sorted(heading_stack) if k < level]
                parent_section = heading_stack[parent_keys[-1]] if parent_keys else ""
                heading_level = level
                continue
            if in_toc:
                continue
            current_blocks.append(block)

        flush()
        return chunks

    def _pack_blocks(self, section_path: str, section_title: str, blocks: List[MarkdownBlock]) -> List[tuple[str, List[MarkdownBlock]]]:
        packed: List[tuple[str, List[MarkdownBlock]]] = []
        current: List[MarkdownBlock] = []
        current_len = len(section_path) + len(section_title) + 8

        def render(items: List[MarkdownBlock]) -> str:
            body = "\n\n".join(item.text for item in items).strip()
            return f"{section_path}\n\n## {section_title}\n\n{body}".strip()

        def flush() -> None:
            nonlocal current, current_len
            if current:
                packed.append((render(current), current))
                current = []
                current_len = len(section_path) + len(section_title) + 8

        for block in blocks:
            block_len = len(block.text) + 2
            if current and current_len + block_len > self.chunk_size:
                flush()
            current.append(block)
            current_len += block_len
        flush()
        return packed

    def _chunk_kind(self, blocks: List[MarkdownBlock]) -> str:
        kinds = {block.kind for block in blocks}
        if kinds == {"table"}:
            return "table"
        if kinds == {"code"}:
            return "code"
        if "figure" in kinds and len(kinds) == 1:
            return "figure"
        return "section"

    def _should_use_table_rows(self, markdown: str) -> bool:
        tables = extract_markdown_tables(markdown)
        if not tables:
            return False
        non_empty = [line for line in markdown.splitlines() if line.strip()]
        table_lines = [line for line in non_empty if line.strip().startswith("|")]
        ratio = len(table_lines) / max(len(non_empty), 1)
        heading_count = sum(1 for line in non_empty if line.lstrip().startswith("#"))
        row_count = sum(len(table["rows"]) for table in tables)
        return row_count >= 2 and ratio >= 0.45 and heading_count <= 8

    def _table_row_chunks(self, markdown: str, file_path: str, filename: str, doc_id: str, source_type: str, start_index: int, title: str) -> List[Dict[str, Any]]:
        chunks: List[Dict[str, Any]] = []
        tables = extract_markdown_tables(markdown)
        for table_idx, table in enumerate(tables):
            rows = table["rows"]
            table_title = title
            for row_idx, row in enumerate(rows):
                if row_idx == 0 and len(row) > 1:
                    continue
                row_title = _row_title(row, f"Table {table_idx + 1} Row {row_idx + 1}")
                body = "\n".join(row) if len(row) == 1 else "\n".join(f"Column {idx}: {cell}" for idx, cell in enumerate(row, start=1))
                text = f"{table_title} > {row_title}\n\n### {row_title}\n\n{body}"
                chunks.append(self._make_chunk(
                    text=text,
                    file_path=file_path,
                    filename=filename,
                    doc_id=doc_id,
                    source_type=source_type,
                    chunk_index=start_index + len(chunks),
                    chunk_kind="table_row",
                    section_title=row_title,
                    section_path=f"{table_title} > {row_title}",
                    parent_section=table_title,
                    heading_level=2,
                    blocks=[],
                    start_line=table["start_line"],
                    end_line=table["end_line"],
                    normalized=source_type.endswith("_llm_normalized"),
                    extra={"table_index": table_idx, "table_row_index": row_idx, "table_title": table_title, "row_title": row_title},
                ))
        return chunks

    def _make_chunk(
        self,
        *,
        text: str,
        file_path: str,
        filename: str,
        doc_id: str,
        source_type: str,
        chunk_index: int,
        chunk_kind: str,
        section_title: str,
        section_path: str,
        parent_section: str,
        heading_level: int,
        blocks: List[MarkdownBlock],
        start_line: int,
        end_line: int,
        normalized: bool,
        extra: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        block_kinds = {block.kind for block in blocks}
        metadata = {
            "source": file_path,
            "doc_id": doc_id,
            "filename": filename,
            "doc_type": "general",
            "parser": source_type,
            "normalized": normalized,
            "chunk_index": chunk_index,
            "prev_index": chunk_index - 1 if chunk_index > 0 else -1,
            "next_index": -1,
            "chunk_kind": chunk_kind,
            "section_title": section_title,
            "section_path": section_path,
            "parent_section": parent_section,
            "heading_level": heading_level,
            "header_level": heading_level,
            "has_table": "table" in block_kinds or chunk_kind.startswith("table"),
            "has_code": "code" in block_kinds,
            "has_figure": "figure" in block_kinds,
            "is_fragment": chunk_kind.endswith("_fragment"),
            "fragment_index": 0,
            "total_fragments": 1,
            "start_line": start_line,
            "end_line": end_line,
        }
        if extra:
            metadata.update(extra)
        return {"text": text.strip(), "metadata": metadata}

    def _link_indices(self, chunks: List[Dict[str, Any]]) -> None:
        for idx, chunk in enumerate(chunks):
            meta = chunk["metadata"]
            meta["chunk_index"] = idx
            meta["prev_index"] = idx - 1 if idx > 0 else -1
            meta["next_index"] = idx + 1 if idx < len(chunks) - 1 else -1
