from __future__ import annotations

import hashlib
import os
import shutil
import time
from pathlib import Path
from typing import Any, Optional

from backend.admin.inventory import GENERATED_ROOT, SOURCE_ROOT, list_artifact_runs
from backend.admin.repository import repo


_CACHE_TTL_SECONDS = 5.0
_legacy_cache: dict[str, Any] = {"expires_at": 0.0, "items": []}


def _legacy_id(filename: str, source: str) -> str:
    digest = hashlib.sha1(f"{filename}\0{source}".encode("utf-8", errors="ignore")).hexdigest()[:16]
    return f"legacy_{digest}"


def _safe_source_path(source: str | None) -> Optional[str]:
    if not source:
        return None
    try:
        path = Path(source).resolve()
        root = SOURCE_ROOT.resolve()
        if root == path or root in path.parents:
            return str(path)
    except Exception:
        return None
    return None


def _source_size(source: str | None) -> int:
    safe = _safe_source_path(source)
    if not safe:
        return 0
    path = Path(safe)
    return path.stat().st_size if path.exists() and path.is_file() else 0


def _path_key(path: str | None) -> str:
    if not path:
        return ""
    try:
        resolved = Path(path).resolve()
        try:
            return resolved.relative_to(Path.cwd().resolve()).as_posix().lower()
        except ValueError:
            return resolved.as_posix().lower()
    except Exception:
        return str(path).replace("\\", "/").lower()


def _doc_type_from_source(source: str | None) -> str:
    normalized = str(source or "").replace("\\", "/").lower()
    return "qna" if "/qna/" in normalized else "general"


def _artifact_downloads(run: dict[str, Any]) -> dict[str, str]:
    files = run.get("files") if isinstance(run.get("files"), dict) else {}
    parser = str(run.get("parser") or "")
    parsed_candidates = [
        f"parse_{parser.replace('_llm_normalized', '')}.md",
        "parse_docling.md",
        "parse_pymupdf4llm.md",
        "raw.md",
    ]
    normalized_candidates = ["normalized.md", "parse_llm_normalized.md"]
    return {
        "raw": files.get("raw.md") or "",
        "parsed": next((files[name] for name in parsed_candidates if files.get(name)), ""),
        "normalized": next((files[name] for name in normalized_candidates if files.get(name)), ""),
        "final": files.get("selected.md") or files.get("normalized.md") or "",
    }


def _legacy_artifact_index() -> dict[tuple[str, str], dict[str, Any]]:
    indexed: dict[tuple[str, str], dict[str, Any]] = {}
    fallback_by_filename: dict[str, dict[str, Any]] = {}
    for run in list_artifact_runs(limit=10000):
        manifest = run.get("manifest") if isinstance(run.get("manifest"), dict) else {}
        filename = str(manifest.get("filename") or run.get("document_name") or "")
        source = str(manifest.get("file_path") or "")
        if not filename:
            continue
        item = {**run, "downloads": _artifact_downloads(run)}
        indexed[(filename.lower(), _path_key(source))] = item
        current = fallback_by_filename.get(filename.lower())
        if not current or float(item.get("modified_at") or 0) > float(current.get("modified_at") or 0):
            fallback_by_filename[filename.lower()] = item
    for filename, item in fallback_by_filename.items():
        indexed.setdefault((filename, ""), item)
    return indexed


def _safe_generated_dir(path: str | None) -> Optional[Path]:
    if not path:
        return None
    try:
        target = Path(path).resolve()
        root = GENERATED_ROOT.resolve()
        if target.is_dir() and target != root and root in target.parents:
            return target
    except Exception:
        return None
    return None


def _prune_empty_generated_parents(start: Path) -> None:
    root = GENERATED_ROOT.resolve()
    current = start.resolve()
    while current != root and root in current.parents:
        try:
            current.rmdir()
        except OSError:
            break
        current = current.parent


def _delete_legacy_artifacts(match: dict[str, Any]) -> list[str]:
    deleted: list[str] = []
    candidates: set[Path] = set()
    artifact_dir = _safe_generated_dir(str(match.get("artifact_path") or ""))
    if artifact_dir:
        candidates.add(artifact_dir)

    artifact_files = match.get("artifact_files") if isinstance(match.get("artifact_files"), dict) else {}
    for path in artifact_files.values():
        try:
            parent = Path(str(path)).resolve().parent
        except Exception:
            continue
        safe_parent = _safe_generated_dir(str(parent))
        if safe_parent:
            candidates.add(safe_parent)

    for target in sorted(candidates, key=lambda item: len(item.parts), reverse=True):
        if not target.exists():
            continue
        shutil.rmtree(target)
        deleted.append(str(target))
        _prune_empty_generated_parents(target.parent)
    return deleted


def _fetch_chroma_metadatas(limit: int = 5000) -> list[dict[str, Any]] | None:
    try:
        from backend.rag.store import get_vector_store

        store = get_vector_store()
        store.refresh_collection()
        offset = 0
        page_size = 500
        metadatas: list[dict[str, Any]] = []
        while len(metadatas) < limit:
            with store.lock:
                result = store.collection.get(include=["metadatas"], limit=page_size, offset=offset)
            page = [meta for meta in result.get("metadatas", []) if isinstance(meta, dict)]
            if not page:
                break
            metadatas.extend(page)
            if len(page) < page_size:
                break
            offset += page_size
        return metadatas[:limit]
    except Exception:
        return None


def legacy_indexed_documents(*, force_refresh: bool = False) -> list[dict[str, Any]]:
    now = time.monotonic()
    if not force_refresh and _legacy_cache["expires_at"] > now:
        return list(_legacy_cache["items"])

    admin_ids = {item["document_id"] for item in repo.list_indexed_document_summaries(limit=10000)}
    artifact_index = _legacy_artifact_index()
    metadatas = _fetch_chroma_metadatas()
    if metadatas is None:
        return list(_legacy_cache["items"])

    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for meta in metadatas:
        if meta.get("document_id") in admin_ids:
            continue
        filename = str(meta.get("filename") or os.path.basename(str(meta.get("source") or "")) or "Unknown")
        source = str(meta.get("source") or "")
        source_key = _path_key(source)
        key = (filename, source_key)
        artifact = artifact_index.get((filename.lower(), _path_key(source))) or artifact_index.get((filename.lower(), ""))
        artifact_downloads = artifact.get("downloads") if artifact else {}
        safe_source = _safe_source_path(source)
        item = grouped.setdefault(
            key,
            {
                "id": _legacy_id(filename, source_key),
                "origin": "legacy",
                "document_id": None,
                "filename": filename,
                "source_path": source,
                "source_aliases": [],
                "safe_source_path": safe_source,
                "status": "INDEXED",
                "chunk_count": 0,
                "parser": meta.get("parser"),
                "doc_type": meta.get("doc_type") or meta.get("ingestion_type") or _doc_type_from_source(source),
                "ingestion_type": meta.get("ingestion_type") or meta.get("doc_type") or _doc_type_from_source(source),
                "batch_id": None,
                "indexed_at": meta.get("indexed_at") or "",
                "file_size_bytes": _source_size(source),
                "downloads": {
                    "source": bool(_safe_source_path(source)),
                    "raw": bool(artifact_downloads.get("raw")),
                    "parsed": bool(artifact_downloads.get("parsed")),
                    "normalized": bool(artifact_downloads.get("normalized")),
                    "final": bool(artifact_downloads.get("final")),
                },
                "artifact_files": artifact_downloads,
                "artifact_path": artifact.get("path") if artifact else "",
                "artifact_relative_path": artifact.get("relative_path") if artifact else "",
            },
        )
        if source and source not in item["source_aliases"]:
            item["source_aliases"].append(source)
        if not item.get("safe_source_path") and safe_source:
            item["safe_source_path"] = safe_source
        if len(str(source)) < len(str(item.get("source_path") or "")):
            item["source_path"] = source
        item["chunk_count"] += 1
        if not item.get("indexed_at") and meta.get("indexed_at"):
            item["indexed_at"] = meta["indexed_at"]
        if not item.get("parser") and meta.get("parser"):
            item["parser"] = meta["parser"]
        if item.get("doc_type") == "general" and (meta.get("doc_type") or meta.get("ingestion_type")):
            item["doc_type"] = meta.get("doc_type") or meta.get("ingestion_type")
            item["ingestion_type"] = item["doc_type"]

    items = sorted(grouped.values(), key=lambda item: (item.get("indexed_at") or "", item["filename"]), reverse=True)
    _legacy_cache["items"] = items
    _legacy_cache["expires_at"] = now + _CACHE_TTL_SECONDS
    return list(items)


def admin_indexed_documents() -> list[dict[str, Any]]:
    documents = repo.list_indexed_document_summaries(limit=10000)
    items: list[dict[str, Any]] = []
    for document in documents:
        canonical = document.get("canonical_files") or {}
        doc_type = (document.get("effective_config") or {}).get("ingestion_type") or document.get("ingestion_type") or "general"
        items.append(
            {
                "id": document["document_id"],
                "origin": "admin",
                "document_id": document["document_id"],
                "filename": document["original_filename"],
                "source_path": document["source_file_path"],
                "safe_source_path": _safe_source_path(document.get("source_file_path")),
                "status": document["status"],
                "chunk_count": document.get("chunk_count") or 0,
                "parser": (document.get("effective_config") or {}).get("parsers", ["docling"])[0],
                "doc_type": doc_type,
                "ingestion_type": doc_type,
                "batch_id": document["batch_id"],
                "indexed_at": document.get("indexed_at") or "",
                "file_size_bytes": document.get("file_size_bytes") or 0,
                "downloads": {
                    "source": bool(document.get("source_file_path")),
                    "parsed": bool(canonical.get("parsed_md_path")),
                    "normalized": bool(canonical.get("normalized_md_path")),
                    "final": bool(canonical.get("review_approved_md_path")),
                },
            }
        )
    return items


def indexed_documents(*, search: Optional[str] = None, limit: int = 500, page: int = 1) -> dict[str, Any]:
    query = (search or "").strip().lower()
    items = admin_indexed_documents() + legacy_indexed_documents()
    if query:
        items = [
            item
            for item in items
            if query in str(item.get("filename") or "").lower()
            or query in str(item.get("source_path") or "").lower()
            or query in str(item.get("batch_id") or "").lower()
            or query in str(item.get("document_id") or "").lower()
            or query in str(item.get("doc_type") or "").lower()
        ]
    items.sort(key=lambda item: (item.get("indexed_at") or "", item.get("filename") or ""), reverse=True)
    total = len(items)
    start = max(page - 1, 0) * limit
    return {"items": items[start : start + limit], "total": total, "page": page}


def legacy_file_path(legacy_id: str, file_type: str) -> Path:
    match = next((item for item in legacy_indexed_documents(force_refresh=True) if item["id"] == legacy_id), None)
    if not match:
        raise KeyError("Legacy document not found")
    if file_type == "source":
        source = match.get("safe_source_path")
        if not source:
            raise FileNotFoundError("Legacy source file is not available")
        target = Path(source).resolve()
        root = SOURCE_ROOT.resolve()
        if root != target and root not in target.parents:
            raise PermissionError("Legacy source path is outside upload_docs")
    else:
        artifact_files = match.get("artifact_files") if isinstance(match.get("artifact_files"), dict) else {}
        key = "final" if file_type in {"final", "approved"} else file_type
        path = artifact_files.get(key)
        if not path:
            raise FileNotFoundError("Legacy markdown artifact is not available")
        target = Path(path).resolve()
        root = GENERATED_ROOT.resolve()
        if root != target and root not in target.parents:
            raise PermissionError("Legacy artifact path is outside generated_doc_md")
    if not target.exists() or not target.is_file():
        raise FileNotFoundError("Legacy file is not available")
    return target


def delete_legacy_document(legacy_id: str) -> dict[str, Any]:
    match = next((item for item in legacy_indexed_documents(force_refresh=True) if item["id"] == legacy_id), None)
    if not match:
        raise KeyError("Legacy document not found")
    from backend.rag.store import get_vector_store

    store = get_vector_store()
    aliases = match.get("source_aliases") if isinstance(match.get("source_aliases"), list) else []
    if hasattr(store, "delete_legacy_document") and aliases:
        for source in aliases:
            store.delete_legacy_document(filename=match["filename"], source=source)
    elif hasattr(store, "delete_legacy_document"):
        store.delete_legacy_document(filename=match["filename"], source=match.get("source_path"))
    else:
        store.delete_file(match["filename"])
    safe_source = match.get("safe_source_path")
    if safe_source:
        path = Path(safe_source)
        if path.exists() and path.is_file():
            path.unlink()
    deleted_artifacts = _delete_legacy_artifacts(match)
    _legacy_cache["expires_at"] = 0.0
    return {"deleted": True, "document": match, "deleted_artifacts": deleted_artifacts}
