import html
import re
from typing import Any, Dict, List

from backend.ingestion.chunkers.general import GeneralChunker, stable_doc_id


def _plain(text: str) -> str:
    text = html.unescape(text or "")
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"</?[^>]+>", "", text)
    text = re.sub(r"\*\*", "", text)
    text = re.sub(r"(?<!\w)_([^_\n]+?)_(?!\w)", r"\1", text)
    text = re.sub(r"(?m)(^|\s)_([A-Za-z][^_\n]{1,120})(?=[:\s]|$)", r"\1\2", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip(" \t\n|")


def _table_row_to_numbered(line: str) -> str | None:
    if not line.strip().startswith("|"):
        return None
    cells = [_plain(cell) for cell in line.strip().strip("|").split("|")]
    cells = [cell for cell in cells if cell and not re.fullmatch(r":?-{3,}:?", cell)]
    if not cells:
        return None
    if len(cells) >= 2 and re.fullmatch(r"\d{1,2}\.?", cells[0]):
        number = cells[0].rstrip(".")
        title = cells[1]
        rest = " ".join(cells[2:]).strip()
        return f"{number}. {title}: {rest}" if rest else f"{number}. {title}"
    joined = " ".join(cells)
    if re.match(r"^\d{1,2}\.", joined):
        return joined
    return None


def _is_numbered_table_data_row(line: str) -> bool:
    if not line.strip().startswith("|"):
        return False
    cells = [_plain(cell) for cell in line.strip().strip("|").split("|")]
    cells = [cell for cell in cells if cell and not re.fullmatch(r":?-{3,}:?", cell)]
    return len(cells) >= 2 and bool(re.fullmatch(r"\d{1,2}\.?", cells[0]))


def _row_title(text: str, fallback: str) -> str:
    first = re.sub(r"\s+", " ", text).strip()
    match = re.match(r"^(\d{1,2})\s*[.)]?\s*(.+?)(?::|\n|$)", first)
    if match:
        title = f"{match.group(1)}. {match.group(2).strip()}"
    else:
        title = fallback
    title = re.sub(r"\s+", " ", title).strip(" .:-")
    return title[:100].rsplit(" ", 1)[0] if len(title) > 100 else title


class VisionChunker:
    """Chunk page-level VLM Markdown without depending on Markdown table syntax."""

    def __init__(self, chunk_size: int = 2200):
        self.chunk_size = chunk_size

    def chunk(self, markdown: str, file_path: str, filename: str, source_type: str = "vision_llm") -> List[Dict[str, Any]]:
        visual_chunks = self._visual_chunks(markdown, file_path, filename, source_type)
        rows = self._extract_numbered_rows(markdown)
        if not self._should_use_row_chunking(markdown, rows):
            general_markdown = self._markdown_for_general_chunks(markdown)
            chunks = GeneralChunker(chunk_size=self.chunk_size).chunk(general_markdown, file_path, filename, source_type)
            chunks.extend(visual_chunks)
            self._link_indices(chunks)
            return chunks

        doc_id = stable_doc_id(file_path)
        chunks: List[Dict[str, Any]] = []
        summary = self._summary(rows, file_path, filename, doc_id, source_type)
        chunks.append(summary)

        for row_idx, row in enumerate(rows):
            parts = self._split_row(row["text"], filename, row["title"], row["page"])
            for frag_idx, text in enumerate(parts):
                total = len(parts)
                chunks.append({
                    "text": text if total == 1 else f"{text}\n\n[Vision row fragment {frag_idx + 1}/{total}]",
                    "metadata": {
                        "source": file_path,
                        "doc_id": doc_id,
                        "filename": filename,
                        "chunk_index": len(chunks),
                        "next_index": -1,
                        "prev_index": len(chunks) - 1 if chunks else -1,
                        "section_path": f"Page {row['page']} > {row['title']}",
                        "section_title": row["title"],
                        "header_level": 0,
                        "is_fragment": total > 1,
                        "fragment_index": frag_idx,
                        "total_fragments": total,
                        "has_table": True,
                        "start_line": row["start_line"],
                        "end_line": row["end_line"],
                        "doc_type": "general",
                        "chunk_kind": "table_row" if total == 1 else "table_row_fragment",
                        "table_index": row["page"] - 1,
                        "table_row_index": row_idx,
                        "parser": source_type,
                    },
                })

        chunks.extend(visual_chunks)
        self._link_indices(chunks)
        return chunks

    def _visual_chunks(self, markdown: str, file_path: str, filename: str, source_type: str) -> List[Dict[str, Any]]:
        doc_id = stable_doc_id(file_path)
        chunks = []
        pattern = re.compile(
            r"(?ms)^\[(Visual):\s*([^\]|]+)\s*\|\s*page\s*(\d+)\]\s*(.*?)^\[/Visual\]\s*"
            r"|^\[(Image description)\s*\|\s*page\s*(\d+)\]\s*(.*?)^\[/Image description\]\s*"
        )
        for match in pattern.finditer(markdown):
            if match.group(1):
                block_kind = "visual"
                visual_type = _plain(match.group(2)).lower() or "unknown"
                page = int(match.group(3))
                body = match.group(4).strip()
                title = self._field_value(body, "Title") or f"{visual_type.title()} on page {page}"
                raw_block = f"[Visual: {visual_type} | page {page}]\n{body}\n[/Visual]"
            else:
                block_kind = "image"
                visual_type = "image"
                page = int(match.group(6))
                body = match.group(7).strip()
                title = f"Image description on page {page}"
                raw_block = f"[Image description | page {page}]\n{body}\n[/Image description]"

            chunks.append({
                "text": f"[Doc: {filename} | Section: Page {page} > {title} | Visual]\n# {title}\n{raw_block}",
                "metadata": {
                    "source": file_path,
                    "doc_id": doc_id,
                    "filename": filename,
                    "chunk_index": 0,
                    "next_index": -1,
                    "prev_index": -1,
                    "section_path": f"Page {page} > {title}",
                    "section_title": title,
                    "header_level": 0,
                    "is_fragment": False,
                    "fragment_index": 0,
                    "total_fragments": 1,
                    "has_table": False,
                    "start_line": markdown[:match.start()].count("\n") + 1,
                    "end_line": markdown[:match.end()].count("\n") + 1,
                    "doc_type": "general",
                    "chunk_kind": block_kind,
                    "visual_type": visual_type,
                    "page_number": page,
                    "parser": source_type,
                },
            })
        return chunks

    def _field_value(self, body: str, field: str) -> str:
        match = re.search(rf"(?im)^{re.escape(field)}:\s*(.+)$", body)
        value = _plain(match.group(1)) if match else ""
        return "" if value.lower() in {"[none]", "none", "[unclear]"} else value

    def _extract_numbered_rows(self, markdown: str) -> List[Dict[str, Any]]:
        rows = []
        current = None
        page = 1

        def flush(end_line: int):
            nonlocal current
            if not current:
                return
            current["end_line"] = end_line
            current["text"] = "\n".join(current["lines"]).strip()
            current["title"] = _row_title(current["text"], f"Row {len(rows) + 1}")
            rows.append(current)
            current = None

        for line_no, raw in enumerate(markdown.splitlines(), start=1):
            stripped = raw.strip()
            page_match = re.search(r"<!--\s*page:(\d+)\s*-->", stripped) or re.match(r"##\s+Page\s+(\d+)\b", stripped, re.I)
            if page_match:
                flush(line_no - 1)
                page = int(page_match.group(1))
                continue
            if not stripped or stripped.startswith("#"):
                continue

            converted = _table_row_to_numbered(stripped)
            line = converted or stripped
            if re.match(r"^\d{1,2}\s*[.)]\s+\S", line):
                flush(line_no - 1)
                current = {"page": page, "start_line": line_no, "lines": [_plain(line)]}
            elif current:
                current["lines"].append(_plain(line))

        flush(len(markdown.splitlines()))
        return rows

    def _should_use_row_chunking(self, markdown: str, rows: List[Dict[str, Any]]) -> bool:
        if len(rows) < 2:
            return False
        numbered_table_lines = [
            line for line in markdown.splitlines()
            if (
                line.strip().startswith("|")
                and _is_numbered_table_data_row(line.strip())
                and not re.search(r"\.{5,}", line)
            )
        ]
        non_empty_lines = [line for line in markdown.splitlines() if line.strip()]
        table_lines = [line for line in non_empty_lines if line.strip().startswith("|")]
        heading_lines = [line for line in non_empty_lines if line.lstrip().startswith("#")]
        table_line_ratio = len(table_lines) / max(1, len(non_empty_lines))
        if len(numbered_table_lines) >= 2 and table_line_ratio >= 0.45:
            return True

        structured_rows = 0
        for row in rows:
            first_line = row["lines"][0] if row.get("lines") else ""
            has_alpha_subclauses = bool(re.search(r"(?m)^\s*[a-z]\)", row["text"]))
            if ":-" in first_line or has_alpha_subclauses:
                structured_rows += 1

        # At-a-glance/table-like pages usually have row labels with subclauses.
        # Technical reports and SRS docs often contain many numbered sections
        # and TOC lines; those should stay section/paragraph chunks.
        return (structured_rows / len(rows)) >= 0.3

    def _markdown_for_general_chunks(self, markdown: str) -> str:
        lines = markdown.splitlines()
        output = []
        table = []

        def flush_table():
            nonlocal table
            if not table:
                return
            rendered = self._linearize_table(table)
            if rendered:
                output.extend(rendered)
            table = []

        for line in lines:
            if line.strip().startswith("|"):
                table.append(line)
                continue
            flush_table()
            output.append(line)
        flush_table()
        return "\n".join(output)

    def _linearize_table(self, table_lines: List[str]) -> List[str]:
        rows = []
        for raw in table_lines:
            cells = [_plain(cell) for cell in raw.strip().strip("|").split("|")]
            cells = [cell for cell in cells if cell and not re.fullmatch(r":?-{3,}:?", cell)]
            if cells:
                rows.append(cells)
        if not rows:
            return []

        header = rows[0]
        body = rows[1:]
        if self._is_toc_table(header, body):
            return []

        rendered = [""]
        for row in body:
            if len(header) == len(row) and len(row) > 1:
                fields = [f"{header[idx]}: {cell}" for idx, cell in enumerate(row)]
                rendered.append("- " + "; ".join(fields))
            else:
                rendered.append("- " + "; ".join(row))
        rendered.append("")
        return rendered

    def _is_toc_table(self, header: List[str], body: List[List[str]]) -> bool:
        header_text = " ".join(header).lower()
        if "page" not in header_text:
            return False
        topicish = any(token in header_text for token in ("topic", "section", "contents", "title"))
        numbered_rows = sum(1 for row in body if row and re.match(r"^\d{1,2}\.", row[0]))
        page_number_rows = sum(1 for row in body if len(row) >= 2 and re.fullmatch(r"\d{1,3}", row[-1]))
        return topicish and numbered_rows >= 2 and page_number_rows >= 2

    def _summary(self, rows: List[Dict[str, Any]], file_path: str, filename: str, doc_id: str, source_type: str) -> Dict[str, Any]:
        titles = "; ".join(row["title"] for row in rows[:24])
        opening = f"Vision-parsed structured document. Key rows: {titles}"
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
            },
        }

    def _split_row(self, text: str, filename: str, title: str, page: int) -> List[str]:
        prefix = f"[Doc: {filename} | Section: Page {page} > {title} | Table Row]\n# {title}\n"
        full = prefix + text
        if len(full) <= self.chunk_size:
            return [full]

        paragraphs = [p.strip() for p in re.split(r"\n\s*", text) if p.strip()]
        parts = []
        current = []
        current_len = len(prefix)
        for para in paragraphs:
            if current and current_len + len(para) + 1 > self.chunk_size:
                parts.append(prefix + "\n".join(current))
                current = []
                current_len = len(prefix)
            current.append(para)
            current_len += len(para) + 1
        if current:
            parts.append(prefix + "\n".join(current))
        return parts or [full]

    def _link_indices(self, chunks: List[Dict[str, Any]]) -> None:
        for idx, chunk in enumerate(chunks):
            chunk["metadata"]["chunk_index"] = idx
            chunk["metadata"]["prev_index"] = idx - 1 if idx > 0 else -1
            chunk["metadata"]["next_index"] = idx + 1 if idx < len(chunks) - 1 else -1
