import re
from typing import Optional

from backend.ingestion.models import ParseDiagnostics


def analyze_markdown(markdown: str, parser: str, source_type: Optional[str] = None) -> ParseDiagnostics:
    text = markdown or ""
    rows = [line.strip() for line in text.splitlines() if line.strip().startswith("|")]
    table_count = 0
    in_table = False
    for line in text.splitlines():
        is_table = line.strip().startswith("|")
        if is_table and not in_table:
            table_count += 1
        in_table = is_table

    bad_rows = 0
    for row in rows:
        cells = [c.strip() for c in row.strip("|").split("|")]
        if len(cells) <= 1:
            bad_rows += 1
        if any(c.lower() in {"col2", "col3", "col4"} for c in cells):
            bad_rows += 1
        if len(cells) >= 2 and cells[0] and cells[0] == cells[1]:
            bad_rows += 1

    warnings = []
    broken_table_score = (bad_rows / max(1, len(rows))) if rows else 0.0
    if broken_table_score > 0.25:
        warnings.append("table_structure_suspect")
    if len(text.strip()) < 100:
        warnings.append("very_low_text")
    numbers = _numbered_row_sequence(text)
    if _has_numbered_row_gaps(numbers):
        warnings.append("numbered_row_gaps")

    return ParseDiagnostics(
        parser=parser,
        source_type=source_type or parser,
        char_count=len(text),
        word_count=len(re.findall(r"\w+", text)),
        table_count=table_count,
        table_row_count=len(rows),
        broken_table_score=round(broken_table_score, 3),
        empty=not bool(text.strip()),
        warnings=warnings,
    )


def should_fallback(diagnostics: ParseDiagnostics, doc_type: str) -> bool:
    if diagnostics.empty:
        return True
    if diagnostics.char_count < 100:
        return True
    if doc_type == "general" and diagnostics.table_row_count >= 5 and diagnostics.broken_table_score > 0.45:
        return True
    if doc_type == "general" and diagnostics.table_row_count >= 5 and "numbered_row_gaps" in diagnostics.warnings:
        return True
    return False


def _numbered_row_sequence(markdown: str) -> list[int]:
    numbers = []
    for line in markdown.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("|"):
            cells = [cell.strip(" _*") for cell in stripped.strip("|").split("|") if cell.strip()]
            if cells and re.fullmatch(r"\d{1,2}\.?", cells[0]):
                numbers.append(int(cells[0].rstrip(".")))
                continue
        match = re.match(r"^_?(\d{1,2})[.)]\s+", stripped)
        if match:
            numbers.append(int(match.group(1)))
    return numbers


def _has_numbered_row_gaps(numbers: list[int]) -> bool:
    unique = sorted(set(numbers))
    if len(unique) < 6:
        return False
    start, end = unique[0], unique[-1]
    if start not in {1, 2} or end - start < 5:
        return False
    expected = set(range(start, end + 1))
    missing = expected - set(unique)
    return bool(missing)
