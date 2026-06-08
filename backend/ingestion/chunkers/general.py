import html
import os
import re
from typing import Any, Dict, List


def stable_doc_id(file_path: str) -> str:
    abs_path = os.path.abspath(file_path)
    try:
        normalized = os.path.relpath(abs_path, os.getcwd())
    except ValueError:
        normalized = abs_path
    normalized = os.path.normpath(normalized).replace("\\", "/").lower()
    return re.sub(r"[^a-z0-9]+", "_", normalized).strip("_")


def _plain_cell(text: str) -> str:
    text = html.unescape(text or "")
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"</?[^>]+>", "", text)
    text = text.replace("_", " ")
    text = re.sub(r"\*\*", "", text)
    text = re.sub(r"~~", "", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return re.sub(r"[ \t]{2,}", " ", text).strip(" \n\t|")


def _split_markdown_row(row: str) -> List[str]:
    return [_plain_cell(c) for c in row.strip().strip("|").split("|")]


def _is_separator_row(cells: List[str]) -> bool:
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", c.replace(" ", "")) for c in cells if c)


def _dedupe_cells(cells: List[str]) -> List[str]:
    cleaned = [c for c in cells if c and c.lower() not in {"col2", "col3", "col4"}]
    if len(cleaned) >= 2 and cleaned[0] == cleaned[1]:
        return [cleaned[0]]
    return cleaned


def extract_markdown_tables(markdown: str) -> List[Dict[str, Any]]:
    lines = markdown.splitlines()
    tables = []
    current = []
    start_line = 0

    def flush(end_line: int):
        nonlocal current, start_line
        if len(current) >= 2:
            rows = []
            for raw in current:
                cells = _split_markdown_row(raw)
                if _is_separator_row(cells):
                    continue
                cells = _dedupe_cells(cells)
                if cells:
                    rows.append(cells)
            if rows:
                tables.append({"rows": rows, "start_line": start_line, "end_line": end_line})
        current = []

    for idx, line in enumerate(lines, start=1):
        if line.strip().startswith("|"):
            if not current:
                start_line = idx
            current.append(line)
        else:
            flush(idx - 1)
    flush(len(lines))
    return tables


def _table_line_ratio(markdown: str) -> float:
    lines = [line for line in markdown.splitlines() if line.strip()]
    if not lines:
        return 0.0
    table_lines = [line for line in lines if line.strip().startswith("|")]
    return len(table_lines) / len(lines)


def _row_title(row: List[str], fallback: str) -> str:
    joined = " ".join(row)
    match = re.search(r"\b(\d{1,2})[.)]?\s+([A-Z][A-Za-z ]{2,120}(?:\([A-Z]+\))?)", joined)
    if match:
        return _truncate_title(f"{match.group(1)}. {match.group(2).strip()}")
    short = re.sub(r"\s+", " ", joined).strip()
    return _truncate_title(short or fallback)


def _truncate_title(text: str, limit: int = 80) -> str:
    text = re.sub(r"\s+", " ", text).strip(" .:-")
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].strip(" .:-")


class GeneralChunker:
    def __init__(self, chunk_size: int = 2200):
        self.chunk_size = chunk_size

    def chunk(self, markdown: str, file_path: str, filename: str, source_type: str = "unknown") -> List[Dict[str, Any]]:
        doc_id = stable_doc_id(file_path)
        chunks: List[Dict[str, Any]] = []
        summary = self._summary_chunk(markdown, file_path, filename, doc_id, source_type)
        if summary:
            chunks.append(summary)

        tables = extract_markdown_tables(markdown)
        if tables and self._should_use_table_row_chunking(markdown, tables):
            for table_idx, table in enumerate(tables):
                for row_idx, row in enumerate(table["rows"]):
                    if not row:
                        continue
                    title = _row_title(row, f"Table {table_idx + 1} Row {row_idx + 1}")
                    text_parts = self._split_table_row_text(self._format_table_row(filename, table_idx, row_idx, row, title))
                    for frag_idx, text in enumerate(text_parts):
                        total_fragments = len(text_parts)
                        chunks.append({
                            "text": text if total_fragments == 1 else f"{text}\n\n[Table row fragment {frag_idx + 1}/{total_fragments}]",
                        "metadata": {
                            "source": file_path,
                            "doc_id": doc_id,
                            "filename": filename,
                            "chunk_index": len(chunks),
                            "next_index": -1,
                            "prev_index": len(chunks) - 1 if chunks else -1,
                            "section_path": f"Table {table_idx + 1} > {title}",
                            "section_title": title,
                            "header_level": 0,
                            "is_fragment": total_fragments > 1,
                            "fragment_index": frag_idx,
                            "total_fragments": total_fragments,
                            "has_table": True,
                            "start_line": table["start_line"],
                            "end_line": table["end_line"],
                            "doc_type": "general",
                            "chunk_kind": "table_row" if total_fragments == 1 else "table_row_fragment",
                            "table_index": table_idx,
                            "table_row_index": row_idx,
                            "parser": source_type,
                        }
                    })
            self._link_indices(chunks)
            return chunks

        body_markdown = self._markdown_with_linearized_tables(markdown) if tables else markdown
        body = self._body_chunks(body_markdown, file_path, filename, doc_id, source_type, start_index=len(chunks))
        chunks.extend(body)
        self._link_indices(chunks)
        return chunks

    def _should_use_table_row_chunking(self, markdown: str, tables: List[Dict[str, Any]]) -> bool:
        heading_count = sum(1 for line in markdown.splitlines() if line.lstrip().startswith("#"))
        row_count = sum(len(table["rows"]) for table in tables)
        ratio = _table_line_ratio(markdown)
        return row_count >= 2 and ratio >= 0.45 and heading_count <= 8

    def _markdown_with_linearized_tables(self, markdown: str) -> str:
        output = []
        current = []

        def flush_table() -> None:
            nonlocal current
            if not current:
                return
            table = extract_markdown_tables("\n".join(current))
            if table:
                rows = table[0]["rows"]
                if rows:
                    headers = rows[0]
                    for row in rows[1:]:
                        if len(headers) == len(row) and len(row) > 1:
                            output.append("- " + "; ".join(f"{headers[idx]}: {cell}" for idx, cell in enumerate(row)))
                        else:
                            output.append("- " + "; ".join(row))
            current = []

        for line in markdown.splitlines():
            if line.strip().startswith("|"):
                current.append(line)
                continue
            flush_table()
            output.append(line)
        flush_table()
        return "\n".join(output)

    def _summary_chunk(self, markdown: str, file_path: str, filename: str, doc_id: str, source_type: str) -> Dict[str, Any] | None:
        tables = extract_markdown_tables(markdown)
        if tables:
            row_titles = []
            for table_idx, table in enumerate(tables):
                for row_idx, row in enumerate(table["rows"]):
                    row_titles.append(_row_title(row, f"Table {table_idx + 1} Row {row_idx + 1}"))
            opening = "Structured table document. Key rows: " + "; ".join(row_titles[:24])
            if len(opening) > 1600:
                opening = opening[:1600].rsplit(" ", 1)[0]
            return {
                "text": f"[Doc: {filename} | Section: Document Summary]\n# Document Summary\n{opening}",
                "metadata": {
                    "source": file_path,
                    "doc_id": doc_id,
                    "filename": filename,
                    "chunk_index": 0,
                    "next_index": -1,
                    "prev_index": -1,
                    "section_path": "Document Summary",
                    "section_title": "Document Summary",
                    "header_level": 0,
                    "is_fragment": False,
                    "fragment_index": 0,
                    "total_fragments": 1,
                    "has_table": True,
                    "start_line": 0,
                    "end_line": 0,
                    "doc_type": "general",
                    "chunk_kind": "doc_summary",
                    "parser": source_type,
                }
            }

        lines = []
        in_toc = False
        for raw_line in markdown.splitlines():
            clean_line = _plain_cell(raw_line)
            if re.match(r"^#{1,6}\s+(Table of Contents|Contents)\s*$", raw_line.strip(), re.I):
                in_toc = True
                continue
            if in_toc:
                if raw_line.lstrip().startswith("#") and not re.match(r"^#{1,6}\s+(Table of Contents|Contents)\s*$", raw_line.strip(), re.I):
                    in_toc = False
                elif not clean_line or re.match(r"^(?:[-*]\s+)?\[[^\]]+\]\(#", raw_line.strip()):
                    continue
            if clean_line:
                lines.append(clean_line)
        if not lines:
            return None
        opening = " ".join(lines[:10])
        if len(opening) > 1600:
            opening = opening[:1600].rsplit(" ", 1)[0]
        return {
            "text": f"[Doc: {filename} | Section: Document Summary]\n# Document Summary\n{opening}",
            "metadata": {
                "source": file_path,
                "doc_id": doc_id,
                "filename": filename,
                "chunk_index": 0,
                "next_index": -1,
                "prev_index": -1,
                "section_path": "Document Summary",
                "section_title": "Document Summary",
                "header_level": 0,
                "is_fragment": False,
                "fragment_index": 0,
                "total_fragments": 1,
                "has_table": False,
                "start_line": 0,
                "end_line": 0,
                "doc_type": "general",
                "chunk_kind": "doc_summary",
                "parser": source_type,
            }
        }

    def _format_table_row(self, filename: str, table_idx: int, row_idx: int, row: List[str], title: str) -> str:
        parts = [
            f"[Doc: {filename} | Section: Table {table_idx + 1} > {title} | Table Row: {row_idx + 1}]",
            f"# {title}",
        ]
        if len(row) == 1:
            parts.append(row[0])
        else:
            for idx, cell in enumerate(row, start=1):
                parts.append(f"Column {idx}: {cell}")
        return "\n".join(parts)

    def _split_table_row_text(self, text: str) -> List[str]:
        if len(text) <= self.chunk_size:
            return [text]
        header, _, body = text.partition("\n")
        title_line, _, remainder = body.partition("\n")
        prefix = f"{header}\n{title_line}".strip()
        lines = [line for line in remainder.splitlines() if line.strip()]
        parts = []
        current = []
        current_len = len(prefix)
        for line in lines:
            line_len = len(line) + 1
            if current and current_len + line_len > self.chunk_size:
                parts.append(prefix + "\n" + "\n".join(current))
                current = []
                current_len = len(prefix)
            current.append(line)
            current_len += line_len
        if current:
            parts.append(prefix + "\n" + "\n".join(current))
        return parts or [text]

    def _body_chunks(self, markdown: str, file_path: str, filename: str, doc_id: str, source_type: str, start_index: int) -> List[Dict[str, Any]]:
        text = re.sub(r"(?ms)^\|.*?\|\s*$", "", markdown)
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
        chunks = []
        current = []
        current_len = 0
        section_title = "Body"
        section_path = "Body"
        header_level = 0
        heading_stack: Dict[int, str] = {}

        def flush_current() -> None:
            nonlocal current, current_len
            if current:
                chunks.append(self._body_chunk(
                    "\n\n".join(current),
                    file_path,
                    filename,
                    doc_id,
                    source_type,
                    start_index + len(chunks),
                    section_title,
                    section_path,
                    header_level,
                ))
                current = []
                current_len = 0

        for paragraph in paragraphs:
            heading_match = re.match(r"^(#{1,6})\s+(.+?)(?:\n(.*))?$", paragraph, flags=re.S)
            if heading_match:
                flush_current()
                header_level = len(heading_match.group(1))
                section_title = _truncate_title(_plain_cell(heading_match.group(2)), limit=120) or "Body"
                heading_stack[header_level] = section_title
                for level in list(heading_stack):
                    if level > header_level:
                        del heading_stack[level]
                section_path = " > ".join(heading_stack[level] for level in sorted(heading_stack))
                paragraph = heading_match.group(3) or ""
                if not paragraph.strip():
                    continue

            clean = _plain_cell(paragraph)
            if not clean:
                continue
            if section_title.lower() in {"table of contents", "contents"}:
                continue
            if current and current_len + len(clean) > self.chunk_size:
                flush_current()
            current.append(clean)
            current_len += len(clean)
        flush_current()
        return chunks

    def _body_chunk(
        self,
        text: str,
        file_path: str,
        filename: str,
        doc_id: str,
        source_type: str,
        idx: int,
        section_title: str,
        section_path: str,
        header_level: int,
    ) -> Dict[str, Any]:
        return {
            "text": f"[Doc: {filename} | Section: {section_path}]\n# {section_title}\n{text}",
            "metadata": {
                "source": file_path,
                "doc_id": doc_id,
                "filename": filename,
                "chunk_index": idx,
                "next_index": -1,
                "prev_index": idx - 1 if idx else -1,
                "section_path": section_path,
                "section_title": section_title,
                "header_level": header_level,
                "is_fragment": False,
                "fragment_index": 0,
                "total_fragments": 1,
                "has_table": False,
                "start_line": 0,
                "end_line": 0,
                "doc_type": "general",
                "chunk_kind": "body",
                "parser": source_type,
            }
        }

    def _link_indices(self, chunks: List[Dict[str, Any]]) -> None:
        for idx, chunk in enumerate(chunks):
            meta = chunk["metadata"]
            meta["chunk_index"] = idx
            meta["prev_index"] = idx - 1 if idx > 0 else -1
            meta["next_index"] = idx + 1 if idx < len(chunks) - 1 else -1
