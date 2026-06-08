from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ParseDiagnostics:
    parser: str
    source_type: str
    fallback_reason: Optional[str] = None
    page_count: int = 0
    char_count: int = 0
    word_count: int = 0
    table_count: int = 0
    table_row_count: int = 0
    broken_table_score: float = 0.0
    empty: bool = False
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ParsedDocument:
    file_path: str
    filename: str
    doc_type: str
    markdown: str
    selected_parser: str
    diagnostics: ParseDiagnostics
    parser_outputs: Dict[str, str] = field(default_factory=dict)
    raw_markdown: Optional[str] = None
    normalization_manifest: Optional[Dict[str, Any]] = None


@dataclass
class ChunkingResult:
    chunks: List[Dict[str, Any]]
    diagnostics: Dict[str, Any] = field(default_factory=dict)
