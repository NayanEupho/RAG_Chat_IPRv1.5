from __future__ import annotations

from typing import Any, Optional


def _build_where(*, filename: Optional[str] = None, source: Optional[str] = None, doc_type: Optional[str] = None) -> Optional[dict[str, Any]]:
    clauses: list[dict[str, Any]] = []
    if source:
        clauses.append({"source": source})
    elif filename:
        clauses.append({"filename": filename})
    if doc_type:
        clauses.append({"doc_type": "qna" if str(doc_type).lower() == "qna" else "general"})
    if not clauses:
        return None
    if len(clauses) == 1:
        return clauses[0]
    return {"$and": clauses}


def _metadata_value(metadata: dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        value = metadata.get(key)
        if value not in (None, ""):
            return value
    return default


def _chunk_from_chroma(index: int, chunk_id: str, content: str, metadata: dict[str, Any]) -> dict[str, Any]:
    page_numbers = metadata.get("page_numbers") or metadata.get("page_number") or []
    if isinstance(page_numbers, (str, int)):
        page_numbers = [page_numbers]
    return {
        "chunk_id": chunk_id,
        "document_id": metadata.get("document_id") or metadata.get("doc_id") or None,
        "batch_id": metadata.get("batch_id") or None,
        "content": content or "",
        "chunk_index": int(metadata.get("chunk_index") or index),
        "section_path": _metadata_value(metadata, "section_path", "section"),
        "page_numbers": page_numbers,
        "token_count": int(metadata.get("token_count") or len((content or "").split())),
        "char_count": int(metadata.get("char_count") or len(content or "")),
        "embedding_model": str(metadata.get("embedding_model") or "chroma"),
        "indexed_at": str(metadata.get("indexed_at") or ""),
        "chroma_id": chunk_id,
        "filename": metadata.get("filename"),
        "source_path": metadata.get("source"),
        "doc_type": metadata.get("doc_type") or metadata.get("ingestion_type") or "general",
        "origin": "admin" if metadata.get("document_id") else "legacy",
        "metadata": metadata,
    }


def list_chroma_chunks(
    *,
    filename: Optional[str] = None,
    source: Optional[str] = None,
    doc_type: Optional[str] = None,
    search: Optional[str] = None,
    page: int = 1,
    limit: int = 50,
) -> dict[str, Any]:
    try:
        from backend.rag.store import get_vector_store

        store = get_vector_store()
        where = _build_where(filename=filename, source=source, doc_type=doc_type)
        offset = max(page - 1, 0) * limit
        fetch_limit = limit
        if search:
            offset = 0
            fetch_limit = 5000
        with store.lock:
            result = store.collection.get(
                where=where,
                include=["documents", "metadatas"],
                limit=fetch_limit,
                offset=offset,
            )
    except Exception:
        return {"items": [], "total": 0, "page": page}

    ids = result.get("ids") or []
    documents = result.get("documents") or []
    metadatas = result.get("metadatas") or []
    items = [
        _chunk_from_chroma(index, str(ids[index] if index < len(ids) else f"chroma_{index}"), str(content or ""), metadatas[index] if index < len(metadatas) and isinstance(metadatas[index], dict) else {})
        for index, content in enumerate(documents)
    ]
    if search:
        needle = search.lower()
        items = [
            item for item in items
            if needle in item["content"].lower()
            or needle in str(item.get("filename") or "").lower()
            or needle in str(item.get("section_path") or "").lower()
        ]
        start = max(page - 1, 0) * limit
        return {"items": items[start:start + limit], "total": len(items), "page": page}
    return {"items": items, "total": len(items), "page": page}
