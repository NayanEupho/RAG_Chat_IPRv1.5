from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional


SOURCE_ROOT = Path("upload_docs")
GENERATED_ROOT = Path("generated_doc_md")
ADMIN_FOLDER = "Admin_Dashboard"


def _safe_rel(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _file_item(path: Path, root: Path, kind: str) -> dict[str, Any]:
    stat = path.stat()
    return {
        "id": f"{kind}:{_safe_rel(path, root)}",
        "kind": kind,
        "filename": path.name,
        "relative_path": _safe_rel(path, root),
        "path": str(path.resolve()),
        "extension": path.suffix.lower().lstrip("."),
        "size_bytes": stat.st_size,
        "modified_at": stat.st_mtime,
    }


def list_source_files(limit: int = 500) -> list[dict[str, Any]]:
    if not SOURCE_ROOT.exists():
        return []
    allowed = {".pdf", ".docx", ".md", ".markdown", ".txt"}
    items = [
        _file_item(path, SOURCE_ROOT, "source")
        for path in SOURCE_ROOT.rglob("*")
        if path.is_file() and path.suffix.lower() in allowed and path.name != ".gitkeep"
    ]
    items.sort(key=lambda item: item["modified_at"], reverse=True)
    return items[:limit]


def list_generated_files(limit: int = 1000) -> list[dict[str, Any]]:
    if not GENERATED_ROOT.exists():
        return []
    allowed = {".md", ".json", ".jsonl"}
    items = [
        _file_item(path, GENERATED_ROOT, "generated")
        for path in GENERATED_ROOT.rglob("*")
        if path.is_file() and path.suffix.lower() in allowed and path.name != ".gitkeep"
    ]
    items.sort(key=lambda item: item["modified_at"], reverse=True)
    return items[:limit]


def _load_json(path: Path) -> Optional[dict[str, Any]]:
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        return None


def list_artifact_runs(limit: int = 300) -> list[dict[str, Any]]:
    if not GENERATED_ROOT.exists():
        return []
    runs: list[dict[str, Any]] = []
    for manifest in GENERATED_ROOT.rglob("manifest.json"):
        run_dir = manifest.parent
        data = _load_json(manifest) or {}
        files = {path.name: str(path.resolve()) for path in run_dir.iterdir() if path.is_file()}
        stat = manifest.stat()
        runs.append(
            {
                "id": f"run:{_safe_rel(run_dir, GENERATED_ROOT)}",
                "kind": "artifact_run",
                "document_name": run_dir.parents[1].name if len(run_dir.parents) > 1 else run_dir.name,
                "parser": data.get("selected_parser") or run_dir.parent.name,
                "relative_path": _safe_rel(run_dir, GENERATED_ROOT),
                "path": str(run_dir.resolve()),
                "modified_at": stat.st_mtime,
                "files": files,
                "manifest": data,
                "has_chunks": (run_dir / "chunks.jsonl").exists(),
                "has_normalized": (run_dir / "normalized.md").exists(),
                "has_selected": (run_dir / "selected.md").exists(),
            }
        )
    runs.sort(key=lambda item: item["modified_at"], reverse=True)
    return runs[:limit]


def iter_generated_chunks(limit: int = 500) -> list[dict[str, Any]]:
    if not GENERATED_ROOT.exists():
        return []
    chunks: list[dict[str, Any]] = []
    for chunks_file in GENERATED_ROOT.rglob("chunks.jsonl"):
        run_dir = chunks_file.parent
        try:
            lines = chunks_file.read_text(encoding="utf-8", errors="ignore").splitlines()
        except Exception:
            continue
        for index, line in enumerate(lines):
            if len(chunks) >= limit:
                return chunks
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            text = str(payload.get("text") or payload.get("content") or "")
            metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
            doc_id = metadata.get("doc_id")
            if not doc_id:
                try:
                    doc_id = run_dir.relative_to(GENERATED_ROOT).parts[0]
                except ValueError:
                    doc_id = run_dir.name
            chunks.append(
                {
                    "chunk_id": f"generated:{_safe_rel(chunks_file, GENERATED_ROOT)}:{index}",
                    "document_id": str(doc_id),
                    "batch_id": "legacy-generated",
                    "content": text,
                    "chunk_index": int(metadata.get("chunk_index") or index),
                    "section_path": metadata.get("section_path") or metadata.get("section"),
                    "page_numbers": metadata.get("page_numbers") or [],
                    "token_count": len(text.split()),
                    "char_count": len(text),
                    "embedding_model": "existing-artifact",
                    "indexed_at": "",
                    "chroma_id": "",
                    "source": "generated_doc_md",
                    "relative_path": _safe_rel(chunks_file, GENERATED_ROOT),
                }
            )
    return chunks


def inventory_summary() -> dict[str, Any]:
    source_files = list_source_files(limit=10000)
    generated_files = list_generated_files(limit=10000)
    runs = list_artifact_runs(limit=10000)
    return {
        "source_files": len(source_files),
        "generated_files": len(generated_files),
        "artifact_runs": len(runs),
        "pdf_files": sum(1 for item in source_files if item["extension"] == "pdf"),
        "markdown_files": sum(1 for item in generated_files if item["extension"] in {"md", "markdown"}),
        "chunk_files": sum(1 for item in generated_files if item["filename"] == "chunks.jsonl"),
    }
