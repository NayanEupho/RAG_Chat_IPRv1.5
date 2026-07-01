from __future__ import annotations

import time
from typing import Any, Optional

from backend.admin.repository import repo
from backend.admin import warehouse


def _is_number(value: Any) -> bool:
    return isinstance(value, (float, int)) and not isinstance(value, bool)


def _query_embeddings(value: list[Any]) -> list[list[float]]:
    """Normalize embedding client output to Chroma's query_embeddings shape."""
    if not value:
        return []
    first = value[0]
    if _is_number(first):
        return [[float(item) for item in value if _is_number(item)]]
    if isinstance(first, list) and first and _is_number(first[0]):
        return [[float(item) for item in row if _is_number(item)] for row in value if isinstance(row, list)]
    raise ValueError("Embedding model returned an unsupported vector shape")


def _build_where(*, document_id: Optional[str] = None, filename: Optional[str] = None, doc_type: Optional[str] = None) -> Optional[dict[str, Any]]:
    clauses: list[dict[str, Any]] = []
    if document_id:
        clauses.append({"document_id": document_id})
    if filename:
        clauses.append({"filename": filename})
    if doc_type:
        clauses.append({"doc_type": "qna" if str(doc_type).lower() == "qna" else "general"})
    if not clauses:
        return None
    if len(clauses) == 1:
        return clauses[0]
    return {"$and": clauses}


def _first_page(result: dict[str, Any], key: str) -> list[Any]:
    value = result.get(key) or []
    if value and isinstance(value[0], list):
        return value[0]
    return value


def _normalize_probe_results(result: dict[str, Any]) -> list[dict[str, Any]]:
    ids = _first_page(result, "ids")
    documents = _first_page(result, "documents")
    metadatas = _first_page(result, "metadatas")
    distances = _first_page(result, "distances")
    items: list[dict[str, Any]] = []
    for index, content in enumerate(documents):
        metadata = metadatas[index] if index < len(metadatas) and isinstance(metadatas[index], dict) else {}
        distance = distances[index] if index < len(distances) else None
        similarity = None if distance is None else max(0.0, 1.0 - float(distance))
        items.append(
            {
                "rank": index + 1,
                "chunk_id": ids[index] if index < len(ids) else metadata.get("chunk_id") or f"candidate_{index}",
                "content": content or "",
                "metadata": metadata,
                "distance": distance,
                "similarity": similarity,
                "filename": metadata.get("filename"),
                "document_id": metadata.get("document_id"),
                "batch_id": metadata.get("batch_id"),
                "chunk_index": metadata.get("chunk_index"),
                "doc_type": metadata.get("doc_type") or metadata.get("ingestion_type") or "general",
            }
        )
    return items


def _context_view(chunks: list[dict[str, Any]]) -> str:
    blocks = []
    for item in chunks:
        label = f"{item.get('filename') or 'unknown'} / chunk {item.get('chunk_index') if item.get('chunk_index') is not None else item.get('rank')}"
        blocks.append(f"[{label}]\n{item.get('content') or ''}".strip())
    return "\n\n---\n\n".join(blocks)


def vector_stats_detail() -> dict[str, Any]:
    started = time.monotonic()
    indexed = warehouse.indexed_documents(limit=10000)["items"]
    admin_docs = [item for item in indexed if item["origin"] == "admin"]
    legacy_docs = [item for item in indexed if item["origin"] == "legacy"]
    doc_type_counts: dict[str, int] = {}
    for item in indexed:
        doc_type = item.get("doc_type") or item.get("ingestion_type") or "unknown"
        doc_type_counts[doc_type] = doc_type_counts.get(doc_type, 0) + 1

    chunk_stats = repo.chunk_stats()
    vector_error = None
    chroma_count = None
    try:
        from backend.rag.store import get_vector_store

        chroma_count = get_vector_store().count()
    except Exception as exc:
        vector_error = str(exc)

    total_docs = len(indexed)
    mirrored_chunks = int(chunk_stats.get("total_chunks") or 0)
    avg_chunks_per_document = (chroma_count or mirrored_chunks) / total_docs if total_docs else 0
    warnings = []
    if chroma_count is not None and mirrored_chunks and chroma_count != mirrored_chunks:
        warnings.append(
            {
                "type": "mirror_mismatch",
                "message": f"Chroma has {chroma_count} chunks while admin mirror has {mirrored_chunks}. Legacy chunks or older ingestions can cause this.",
                "impact": "Retrieval uses Chroma, so final answer generation can still retrieve these chunks. The mismatch mainly means admin-only mirror statistics and admin chunk browsing do not cover every retrieval chunk.",
                "recommendation": "Keep Chroma as the retrieval source of truth. Rebuild or backfill the admin chunk mirror when you need complete dashboard inspection for older legacy ingestions.",
            }
        )
    if vector_error:
        warnings.append({"type": "vector_error", "message": vector_error})

    return {
        "healthy": vector_error is None,
        "error": vector_error,
        "latency_ms": int((time.monotonic() - started) * 1000),
        "indexed_documents": total_docs,
        "admin_documents": len(admin_docs),
        "legacy_documents": len(legacy_docs),
        "chroma_chunks": chroma_count,
        "mirrored_admin_chunks": mirrored_chunks,
        "avg_chunks_per_document": avg_chunks_per_document,
        "avg_tokens_per_chunk": float(chunk_stats.get("avg_tokens_per_chunk") or 0),
        "avg_chars_per_chunk": float(chunk_stats.get("avg_chars_per_chunk") or 0),
        "total_tokens": int(chunk_stats.get("total_tokens") or 0),
        "total_chars": int(chunk_stats.get("total_chars") or 0),
        "doc_type_breakdown": doc_type_counts,
        "embedding_models": chunk_stats.get("embedding_models") or [],
        "warnings": warnings,
    }


async def vector_probe(
    *,
    query: str,
    top_k: int = 5,
    candidate_k: int = 15,
    rerank: bool = True,
    document_id: Optional[str] = None,
    filename: Optional[str] = None,
    doc_type: Optional[str] = None,
) -> dict[str, Any]:
    started = time.monotonic()
    from backend.config import get_config
    from backend.graph.nodes.retriever import get_cached_embedding
    from backend.rag.store import get_vector_store

    cfg = get_config()
    if not cfg.embedding_model:
        raise ValueError("Embedding model is not configured")
    effective_candidate_k = max(candidate_k, top_k)
    embedding_started = time.monotonic()
    embedding = await get_cached_embedding(query, cfg.embedding_model.model_name)
    query_embeddings = _query_embeddings(embedding)
    embedding_ms = int((time.monotonic() - embedding_started) * 1000)
    if not query_embeddings:
        raise ValueError("Embedding model returned no vector for the probe query")

    search_started = time.monotonic()
    where = _build_where(document_id=document_id, filename=filename, doc_type=doc_type)
    result = get_vector_store().query(query_embeddings, n_results=effective_candidate_k, where=where)
    vector_ms = int((time.monotonic() - search_started) * 1000)
    candidates = _normalize_probe_results(result)

    final_chunks = candidates[:top_k]
    reranker_model = None
    rerank_ms = None
    if rerank and candidates:
        rerank_started = time.monotonic()
        from backend.rag.reranker import Reranker

        reranker = Reranker()
        reranker_model = getattr(reranker, "model_name", None)
        docs = [
            {
                "page_content": item["content"],
                "metadata": {**(item.get("metadata") or {}), "__probe_index": index},
            }
            for index, item in enumerate(candidates)
        ]
        ranked = await reranker.rank(query, docs, top_k=top_k)
        rerank_ms = int((time.monotonic() - rerank_started) * 1000)
        reranked_items = []
        for rank, item in enumerate(ranked, start=1):
            metadata = item.get("metadata") or {}
            original_index = metadata.get("__probe_index")
            if isinstance(original_index, int) and 0 <= original_index < len(candidates):
                merged = dict(candidates[original_index])
            else:
                merged = {
                    "chunk_id": metadata.get("chunk_id") or f"reranked_{rank}",
                    "content": item.get("page_content") or "",
                    "metadata": metadata,
                }
            merged["rerank_rank"] = rank
            merged["rerank_score"] = item.get("score")
            reranked_items.append(merged)
        final_chunks = reranked_items

    return {
        "query": query,
        "filters": {"document_id": document_id, "filename": filename, "doc_type": doc_type},
        "top_k": top_k,
        "candidate_k": effective_candidate_k,
        "embedding_model": cfg.embedding_model.model_name,
        "rerank_enabled": rerank,
        "reranker_model": reranker_model,
        "latency_ms": int((time.monotonic() - started) * 1000),
        "embedding_ms": embedding_ms,
        "vector_ms": vector_ms,
        "rerank_ms": rerank_ms,
        "candidates": candidates,
        "final_chunks": final_chunks,
        "model_context": _context_view(final_chunks),
    }
