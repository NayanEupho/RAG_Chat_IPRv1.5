from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import os
import queue
import threading
import time
from pathlib import Path
from typing import Any, Optional

import httpx
from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, StreamingResponse

from backend.admin.db import get_connection
from backend.admin import files
from backend.admin.auth import authenticate_admin, normalize_email
from backend.admin.events import event_hub
from backend.admin.inventory import inventory_summary, iter_generated_chunks, list_artifact_runs, list_generated_files, list_source_files
from backend.admin.repository import new_id, repo
from backend.admin import warehouse
from backend.admin.chunk_inventory import list_chroma_chunks
from backend.admin.schemas import (
    ApproveReviewRequest,
    AdminLoginRequest,
    BatchConfig,
    BatchConfigPatch,
    BatchStatus,
    BulkDeleteRequest,
    BulkReviewRequest,
    DocumentStatus,
    IngestionType,
    LlmEndpointRequest,
    ParserType,
    RejectReviewRequest,
    RetryNormalizeRequest,
    RetryParseRequest,
    SaveReviewRequest,
    SelectVariantRequest,
    TriggerNormalizeRequest,
    VectorProbeRequest,
    VariantStatus,
)
from backend.admin.worker import admin_worker
from backend.admin import vector_inspector
from backend.ingestion.parsers import normalize_parser_mode, is_supported_parser


router = APIRouter()
_MODEL_HEALTH_CACHE: dict[tuple[str, str], tuple[float, dict[str, Any]]] = {}
_MODEL_HEALTH_LOCK = threading.Lock()


def ok(data):
    return {"data": data, "error": None}


def model_dict(model) -> dict:
    return model.model_dump(mode="json")


def _model_health_ttl_seconds() -> float:
    try:
        return max(5.0, float(os.getenv("ADMIN_MODEL_HEALTH_TTL_SECONDS", "45")))
    except ValueError:
        return 45.0


def _model_health_timeout_seconds() -> float:
    try:
        return max(0.2, float(os.getenv("ADMIN_MODEL_HEALTH_TIMEOUT_SECONDS", "0.75")))
    except ValueError:
        return 0.75


@router.post("/auth/login")
def admin_login(payload: AdminLoginRequest):
    user = authenticate_admin(payload.email, payload.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid admin email or password")
    return ok({"authenticated": True, "email": normalize_email(payload.email)})


def _model_health_cache_key(model, engine: str) -> tuple[str, str]:
    return (
        (engine or "ollama").lower(),
        str(getattr(model, "host", "")).rstrip("/"),
    )


def _probe_ollama_tags(model) -> dict[str, Any]:
    started = time.monotonic()
    try:
        response = httpx.get(f"{str(model.host).rstrip('/')}/api/tags", timeout=_model_health_timeout_seconds())
        response.raise_for_status()
        payload = response.json()
        names = {item.get("name") for item in payload.get("models", []) if isinstance(item, dict)}
        latency_ms = int((time.monotonic() - started) * 1000)
        return {"error": None, "latency_ms": latency_ms, "names": names}
    except Exception as exc:
        return {"error": str(exc), "latency_ms": int((time.monotonic() - started) * 1000), "names": set()}


def _model_health(model, engine: str, configured: bool) -> dict[str, Any]:
    if not configured or not model:
        return {"status": "offline", "error": "Model is not configured.", "latency_ms": None, "cached": False, "checked_at": None}
    if (engine or "ollama").lower() != "ollama":
        return {"status": "unknown", "error": f"Health check for {engine} is not implemented.", "latency_ms": None, "cached": False, "checked_at": None}

    key = _model_health_cache_key(model, engine)
    ttl = _model_health_ttl_seconds()
    now = time.monotonic()

    with _MODEL_HEALTH_LOCK:
        cached = _MODEL_HEALTH_CACHE.get(key)
        if cached and now - cached[0] < ttl:
            tag_result = {**cached[1], "cached": True}
        else:
            tag_result = {}

    if not tag_result:
        checked_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        tag_result = {**_probe_ollama_tags(model), "cached": False, "checked_at": checked_at}
        with _MODEL_HEALTH_LOCK:
            _MODEL_HEALTH_CACHE[key] = (now, tag_result)

    if tag_result["error"]:
        return {
            "status": "offline",
            "error": tag_result["error"],
            "latency_ms": tag_result["latency_ms"],
            "cached": tag_result["cached"],
            "checked_at": tag_result["checked_at"],
        }
    if model.model_name in tag_result["names"]:
        return {
            "status": "online",
            "error": None,
            "latency_ms": tag_result["latency_ms"],
            "cached": tag_result["cached"],
            "checked_at": tag_result["checked_at"],
        }
    return {
        "status": "offline",
        "error": f"Host is reachable, but model '{model.model_name}' was not found in Ollama tags.",
        "latency_ms": tag_result["latency_ms"],
        "cached": tag_result["cached"],
        "checked_at": tag_result["checked_at"],
    }


def _coerce_bool(value, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    lowered = str(value).strip().lower()
    if lowered in {"true", "1", "yes", "on"}:
        return True
    if lowered in {"false", "0", "no", "off"}:
        return False
    return default


def _normalization_models_from_config(
    *,
    model_id: Optional[str] = None,
    endpoint: Optional[str] = None,
    display_name: Optional[str] = None,
) -> list[dict[str, str]]:
    if model_id and endpoint:
        return [
            {
                "model_id": model_id,
                "endpoint": endpoint,
                "display_name": display_name or model_id,
            }
        ]

    from backend.config import get_config

    cfg = get_config()
    model = cfg.normalization_model or cfg.main_model
    if not model:
        return []
    return [
        {
            "model_id": model.model_name,
            "endpoint": model.host,
            "display_name": model.model_name,
        }
    ]


def _complete_normalization_config(config: dict[str, Any]) -> dict[str, Any]:
    completed = {**config}
    default_models = completed.get("default_normalization_models") or []
    if completed.get("default_normalization_enabled"):
        default_models = default_models or _normalization_models_from_config()
        if not default_models:
            raise ValueError("LLM normalization requires a configured normalization model endpoint")
        completed["default_normalization_models"] = default_models
    else:
        completed["default_normalization_models"] = []

    overrides = dict(completed.get("per_document_overrides") or {})
    for document_id, override in list(overrides.items()):
        if not isinstance(override, dict):
            continue
        doc_config = {**override}
        doc_normalization = _coerce_bool(doc_config.get("normalization_enabled"), bool(completed.get("default_normalization_enabled")))
        if doc_normalization:
            doc_models = doc_config.get("normalization_models") or default_models or _normalization_models_from_config()
            if not doc_models:
                raise ValueError("LLM normalization requires a configured normalization model endpoint")
            doc_config["normalization_models"] = doc_models
        else:
            doc_config["normalization_models"] = []
        overrides[document_id] = doc_config
    completed["per_document_overrides"] = overrides
    return completed


@router.get("/stats")
def stats():
    payload = {**repo.get_stats(), "filesystem": inventory_summary()}
    try:
        from backend.rag.store import get_vector_store

        chroma_count = get_vector_store().count()
        payload["chroma_count"] = chroma_count
        payload["retrieval_chunks"] = chroma_count
        payload["chunks"] = max(int(payload.get("chunks") or 0), chroma_count)
    except Exception as exc:
        payload["chroma_count"] = None
        payload["retrieval_chunks"] = payload.get("chunks", 0)
        payload["vector_error"] = str(exc)
    return ok(payload)


@router.get("/health")
def health():
    started = time.monotonic()
    try:
        conn = get_connection()
        try:
            conn.execute("SELECT 1").fetchone()
        finally:
            conn.close()
        latency_ms = int((time.monotonic() - started) * 1000)
        return ok({"healthy": True, "service": "admin-dashboard", "database": "ready", "latency_ms": latency_ms, "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
    except Exception as exc:
        latency_ms = int((time.monotonic() - started) * 1000)
        return ok({"healthy": False, "service": "admin-dashboard", "database": "unavailable", "latency_ms": latency_ms, "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "error": str(exc)})


@router.get("/runtime-config")
def runtime_config():
    from backend.config import get_config

    cfg = get_config()
    def model_row(role: str, model, engine: str, configured: Optional[bool] = None):
        is_configured = bool(model and model.model_name and str(model.model_name).lower() != "false") if configured is None else configured
        health = _model_health(model, engine, is_configured)
        return {
            "role": role,
            "model_id": model.model_name if model else None,
            "endpoint": model.host if model else None,
            "display_name": model.model_name if model else "Not configured",
            "engine": engine or "ollama",
            "configured": is_configured,
            "health_status": health["status"],
            "health_error": health["error"],
            "health_latency_ms": health["latency_ms"],
            "health_cached": health.get("cached", False),
            "health_checked_at": health.get("checked_at"),
        }

    normalization_model = cfg.normalization_model or cfg.main_model
    vlm_model = None
    if cfg.vlm_model and str(cfg.vlm_model).lower() != "false":
        from backend.config import OllamaConfig

        vlm_model = OllamaConfig(host=cfg.vlm_host, model_name=cfg.vlm_model)
    parser_options = [
        {
            "value": "auto",
            "label": "Auto",
            "description": "Quality-gated fallback chain: Docling/OCR, PyMuPDF4LLM, PyMuPDF, then VLM.",
            "available": True,
        },
        {
            "value": "docling",
            "label": "Docling",
            "description": "Standard Docling PDF/DOCX parser without forced OCR.",
            "available": True,
        },
        {
            "value": "docling_vision",
            "label": "Docling OCR",
            "description": "Docling with forced OCR for scanned or image-heavy PDFs.",
            "available": True,
        },
        {
            "value": "pymupdf4llm",
            "label": "PyMuPDF4LLM",
            "description": "Fast digital-text parser for PDFs.",
            "available": True,
        },
        {
            "value": "pymupdf",
            "label": "PyMuPDF",
            "description": "Local PyMuPDF parser with table-aware extraction.",
            "available": True,
        },
        {
            "value": "vision_llm",
            "label": "VLM",
            "description": "Page image transcription using RAG_VLM_MODEL and RAG_VLM_HOST from .env.",
            "available": bool(cfg.vlm_model and str(cfg.vlm_model).lower() != "false"),
        },
    ]
    model_specs = [
        ("Main model (retriever)", cfg.main_model, cfg.main_engine, None),
        ("Embedding model (vectorizer)", cfg.embedding_model, cfg.embedding_engine, None),
        ("VLM model (vision/OCR)", vlm_model, cfg.vlm_engine, bool(vlm_model)),
        ("LLM normalization model", normalization_model, cfg.normalization_engine, None),
    ]
    with ThreadPoolExecutor(max_workers=len(model_specs)) as executor:
        models = list(executor.map(lambda item: model_row(*item), model_specs))

    return ok(
        {
            "normalization": {
                "enabled": cfg.ingest_llm_normalize,
                "model_id": normalization_model.model_name if normalization_model else None,
                "endpoint": normalization_model.host if normalization_model else None,
                "display_name": normalization_model.model_name if normalization_model else "Not configured",
                "engine": cfg.normalization_engine,
                "configured": bool(normalization_model),
            },
            "embedding": {
                "model_id": cfg.embedding_model.model_name if cfg.embedding_model else None,
                "endpoint": cfg.embedding_model.host if cfg.embedding_model else None,
                "display_name": cfg.embedding_model.model_name if cfg.embedding_model else "Not configured",
                "engine": cfg.embedding_engine,
                "configured": bool(cfg.embedding_model),
            },
            "models": models,
            "parsing_mode": cfg.parsing_mode,
            "parser_options": parser_options,
            "vision": {
                "model_id": cfg.vlm_model,
                "endpoint": cfg.vlm_host,
                "engine": cfg.vlm_engine,
                "configured": bool(vlm_model),
            },
        }
    )


@router.post("/batches")
async def create_batch(
    files_upload: list[UploadFile] = File(alias="files"),
    batch_name: str = Form(...),
    batch_description: Optional[str] = Form(default=None),
    parser: str = Form(default="docling"),
    ingestion_type: str = Form(default="general"),
    document_types_json: Optional[str] = Form(default=None),
    document_configs_json: Optional[str] = Form(default=None),
    normalization_enabled: bool = Form(default=False),
    review_required: bool = Form(default=True),
    normalization_model_id: Optional[str] = Form(default=None),
    normalization_endpoint: Optional[str] = Form(default=None),
    normalization_display_name: Optional[str] = Form(default=None),
):
    batch_id = new_id("batch")
    parser = normalize_parser_mode(parser)
    default_ingestion_type = "qna" if str(ingestion_type).lower() == "qna" else "general"
    if not is_supported_parser(parser) or parser not in {"auto", "docling", "docling_vision", "pymupdf", "pymupdf4llm", "vision_llm"}:
        raise HTTPException(status_code=400, detail=f"Unsupported parser mode: {parser}")
    if parser == "vision_llm":
        from backend.config import get_config

        cfg = get_config()
        if not cfg.vlm_model or str(cfg.vlm_model).lower() == "false":
            raise HTTPException(status_code=400, detail="VLM parser requires RAG_VLM_MODEL to be configured")
    normalization_models = _normalization_models_from_config(
        model_id=normalization_model_id,
        endpoint=normalization_endpoint,
        display_name=normalization_display_name,
    )
    if normalization_enabled and not normalization_models:
        raise HTTPException(status_code=400, detail="LLM normalization requires a configured normalization model endpoint")
    config = model_dict(
        BatchConfig(
            default_parsers=[ParserType(parser)],
            default_normalization_enabled=normalization_enabled,
            default_normalization_models=normalization_models if normalization_enabled else [],
            default_ingestion_type=IngestionType(default_ingestion_type),
            review_required=review_required,
        )
    )
    per_file_types: list[str] = []
    if document_types_json:
        try:
            parsed_types = json.loads(document_types_json)
            if not isinstance(parsed_types, list):
                raise ValueError("document_types_json must be a list")
            per_file_types = ["qna" if str(value).lower() == "qna" else "general" for value in parsed_types]
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"Invalid document type mapping: {exc}")
    if per_file_types and len(per_file_types) != len(files_upload):
        raise HTTPException(status_code=400, detail="Document type mapping must match uploaded file count")
    per_file_configs: list[dict] = []
    if document_configs_json:
        try:
            parsed_configs = json.loads(document_configs_json)
            if not isinstance(parsed_configs, list):
                raise ValueError("document_configs_json must be a list")
            if len(parsed_configs) != len(files_upload):
                raise ValueError("Document config mapping must match uploaded file count")
            for item in parsed_configs:
                if not isinstance(item, dict):
                    raise ValueError("Each document config must be an object")
                doc_parser = normalize_parser_mode(str(item.get("parser") or parser))
                if not is_supported_parser(doc_parser) or doc_parser not in {"auto", "docling", "docling_vision", "pymupdf", "pymupdf4llm", "vision_llm"}:
                    raise ValueError(f"Unsupported parser mode: {doc_parser}")
                if doc_parser == "vision_llm":
                    from backend.config import get_config

                    cfg = get_config()
                    if not cfg.vlm_model or str(cfg.vlm_model).lower() == "false":
                        raise ValueError("VLM parser requires RAG_VLM_MODEL to be configured")
                doc_normalization = _coerce_bool(item.get("normalization_enabled"), normalization_enabled)
                doc_models = normalization_models if doc_normalization else []
                if doc_normalization and not doc_models:
                    raise ValueError("LLM normalization requires a configured normalization model endpoint")
                per_file_configs.append(
                    {
                        "parsers": [doc_parser],
                        "normalization_enabled": doc_normalization,
                        "normalization_models": doc_models,
                        "ingestion_type": "qna" if str(item.get("ingestion_type") or default_ingestion_type).lower() == "qna" else "general",
                        "review_required": _coerce_bool(item.get("review_required"), review_required),
                    }
                )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"Invalid document config mapping: {exc}")
    documents = []
    for index, upload in enumerate(files_upload):
        if per_file_configs:
            doc_config = per_file_configs[index]
        else:
            doc_ingestion_type = per_file_types[index] if per_file_types else default_ingestion_type
            doc_config = {
                "parsers": config["default_parsers"],
                "normalization_enabled": config["default_normalization_enabled"],
                "normalization_models": config["default_normalization_models"],
                "ingestion_type": doc_ingestion_type,
                "review_required": review_required,
            }
        documents.append(await files.save_source_upload(batch_id, upload, doc_config, ingestion_type=doc_config["ingestion_type"]))
    config["per_document_overrides"] = {
        document["document_id"]: document["effective_config"]
        for document in documents
        if document["effective_config"] != repo.effective_config(config, document["document_id"])
    }
    batch = repo.create_batch(batch_id=batch_id, name=batch_name, description=batch_description, config=config, documents=documents)
    return ok(batch)


@router.get("/batches")
def list_batches(status: Optional[str] = None, page: int = 1, limit: int = 25, search: Optional[str] = None, include_documents: bool = False):
    return ok(repo.list_batches(status=status, search=search, page=page, limit=limit, include_documents=include_documents))


@router.get("/batches/{batch_id}")
def get_batch(batch_id: str):
    try:
        return ok(repo.get_batch(batch_id, include_documents=True))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.patch("/batches/{batch_id}/config")
def update_batch_config(batch_id: str, payload: BatchConfigPatch):
    try:
        return ok(repo.update_batch_config(batch_id, _complete_normalization_config(model_dict(payload))))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/batches/{batch_id}/submit")
def submit_batch(batch_id: str):
    try:
        batch = repo.submit_batch(batch_id)
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    for document in batch["documents"]:
        for parser_type in document["effective_config"].get("parsers", ["docling"]):
            variant = repo.create_parse_variant(document_id=document["document_id"], parser_type=parser_type)
            admin_worker.enqueue_parse(batch_id=batch_id, document_id=document["document_id"], parse_variant_id=variant["variant_id"])
    note = repo.notify(type_="INGESTION_INITIATED", title="Ingestion initiated", message=f"{batch['total_documents']} documents queued for batch {batch['name']}", batch_id=batch_id)
    event_hub.publish({"type": "notification", "data": note})
    return ok(repo.get_batch(batch_id, include_documents=True))


@router.post("/batches/{batch_id}/cancel")
def cancel_batch(batch_id: str):
    try:
        result = repo.cancel_batch(batch_id)
        event_hub.publish({"type": "batch_progress", "batch_id": batch_id, "status": BatchStatus.CANCELLED.value})
        event_hub.publish({"type": "notification_update", "batch_id": batch_id})
        event_hub.publish({"type": "stats_update", "action": "cancel"})
        event_hub.publish({"type": "warehouse_update", "action": "cancel", "batch_id": batch_id})
        return ok(result)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/batches/cancel-active")
def cancel_active_batches():
    result = repo.cancel_active_batches()
    event_hub.publish({"type": "batch_progress", "status": BatchStatus.CANCELLED.value, "message": f"Cancelled {result['total']} active batches"})
    event_hub.publish({"type": "notification_update", "action": "cancel"})
    event_hub.publish({"type": "stats_update", "action": "cancel"})
    event_hub.publish({"type": "warehouse_update", "action": "cancel"})
    return ok(result)


@router.delete("/batches/{batch_id}")
def delete_batch(batch_id: str):
    try:
        batch = repo.get_batch(batch_id, include_documents=True)
        result = repo.delete_draft_batch(batch_id)
        if batch["status"] == "DRAFT":
            for document in batch.get("documents", []):
                files.delete_document_source_tree(document["source_file_path"])
        return ok(result)
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/documents")
def list_documents(status: Optional[str] = None, page: int = 1, limit: int = 100, search: Optional[str] = None):
    return ok(repo.list_documents(status=status, search=search, page=page, limit=limit))


@router.get("/warehouse/inventory")
def warehouse_inventory(limit: int = 500):
    return ok(
        {
            "source_files": list_source_files(limit=limit),
            "generated_files": list_generated_files(limit=limit),
            "artifact_runs": list_artifact_runs(limit=limit),
            "summary": inventory_summary(),
        }
    )


@router.get("/warehouse/indexed-documents")
def indexed_warehouse_documents(search: Optional[str] = None, page: int = 1, limit: int = 500):
    return ok(warehouse.indexed_documents(search=search, page=page, limit=limit))


@router.get("/documents/{document_id}")
def get_document(document_id: str):
    try:
        return ok(repo.get_document(document_id))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


def _file_media_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return "application/pdf"
    if suffix in {".md", ".markdown"}:
        return "text/markdown; charset=utf-8"
    if suffix == ".txt":
        return "text/plain; charset=utf-8"
    if suffix == ".docx":
        return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    return "application/octet-stream"


@router.get("/documents/{document_id}/files/{file_type}")
def download_document_file(document_id: str, file_type: str, download: bool = False):
    document = repo.get_document(document_id)
    canonical = document.get("canonical_files") or {}
    path_map = {
        "source": document.get("source_file_path"),
        "raw": canonical.get("raw_md_path"),
        "parsed": canonical.get("parsed_md_path"),
        "normalized": canonical.get("normalized_md_path"),
        "approved": canonical.get("review_approved_md_path"),
    }
    path = path_map.get(file_type)
    if not path:
        raise HTTPException(status_code=404, detail="File is not available")
    target = files.ensure_inside_admin_data(path)
    if not target.exists():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(
        target,
        filename=target.name,
        media_type=_file_media_type(target),
        content_disposition_type="attachment" if download else "inline",
    )


@router.delete("/documents/{document_id}")
def delete_indexed_document(document_id: str):
    try:
        document = repo.get_document(document_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    if document["status"] != DocumentStatus.INDEXED.value:
        raise HTTPException(status_code=400, detail="Only indexed documents can be deleted")
    try:
        from backend.rag.store import get_vector_store

        get_vector_store().delete_document(document_id)
        result = repo.delete_indexed_document_record(document_id)
        files.delete_document_source_tree(document["source_file_path"])
        files.delete_tree(files.generated_root() / "batches" / document["batch_id"] / "documents" / document_id)
        repo.log(stage="CLEANUP", level="INFO", message="Indexed admin document deleted", batch_id=document["batch_id"], document_id=document_id)
        event_hub.publish({"type": "warehouse_update", "action": "delete", "origin": "admin", "document_id": document_id})
        event_hub.publish({"type": "stats_update", "action": "delete"})
        return ok(result)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.delete("/legacy-documents/{legacy_id}")
def delete_legacy_document(legacy_id: str):
    try:
        result = warehouse.delete_legacy_document(legacy_id)
        repo.log(stage="CLEANUP", level="INFO", message=f"Legacy document deleted: {result['document']['filename']}", detail=result["document"].get("source_path"))
        event_hub.publish({"type": "warehouse_update", "action": "delete", "origin": "legacy", "legacy_id": legacy_id})
        event_hub.publish({"type": "stats_update", "action": "delete"})
        return ok(result)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/legacy-documents/{legacy_id}/files/{file_type}")
def download_legacy_document_file(legacy_id: str, file_type: str, download: bool = False):
    try:
        target = warehouse.legacy_file_path(legacy_id, file_type)
        return FileResponse(
            target,
            filename=target.name,
            media_type=_file_media_type(target),
            content_disposition_type="attachment" if download else "inline",
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))


@router.post("/documents/bulk-delete")
def bulk_delete_documents(payload: BulkDeleteRequest):
    deleted = []
    errors = []
    deleted_legacy = False
    deleted_admin = False
    for item in payload.items:
        origin = item.get("origin")
        identifier = item.get("id") or item.get("document_id")
        try:
            if origin == "legacy":
                result = warehouse.delete_legacy_document(str(identifier))
                deleted.append(result)
                deleted_legacy = True
                repo.log(stage="CLEANUP", level="INFO", message=f"Legacy document deleted: {result['document']['filename']}", detail=result["document"].get("source_path"))
            else:
                deleted.append(delete_indexed_document(str(identifier))["data"])
                deleted_admin = True
        except Exception as exc:
            errors.append({"id": identifier, "origin": origin, "error": str(exc)})
    if deleted_legacy:
        event_hub.publish({"type": "warehouse_update", "action": "bulk_delete", "origin": "legacy"})
        event_hub.publish({"type": "stats_update", "action": "bulk_delete"})
    elif deleted_admin:
        event_hub.publish({"type": "stats_update", "action": "bulk_delete"})
    return ok({"deleted": deleted, "errors": errors})


@router.post("/documents/{document_id}/select-variant")
def select_variant(document_id: str, payload: SelectVariantRequest):
    document = repo.get_document(document_id)
    parse_variant = repo.get_parse_variant(payload.parse_variant_id)
    if parse_variant["document_id"] != document_id or parse_variant["status"] != VariantStatus.COMPLETE.value:
        raise HTTPException(status_code=400, detail="Parse variant is not complete")
    norm_variant = repo.get_norm_variant(payload.norm_variant_id) if payload.norm_variant_id else None
    if norm_variant and (norm_variant["document_id"] != document_id or norm_variant["status"] != VariantStatus.COMPLETE.value):
        raise HTTPException(status_code=400, detail="Normalization variant is not complete")
    base_path = norm_variant["normalized_md_path"] if norm_variant else parse_variant["parsed_md_path"]
    review = repo.create_or_update_review(
        document_id=document_id,
        selected_parse_variant_id=payload.parse_variant_id,
        selected_norm_variant_id=payload.norm_variant_id,
        base_md_path=base_path,
        status="IN_PROGRESS",
    )
    repo.set_document_status(document_id, DocumentStatus.REVIEW_IN_PROGRESS.value)
    return ok(review)


@router.post("/documents/{document_id}/review/upload")
async def upload_review_file(document_id: str, file: UploadFile = File(...)):
    document = repo.get_document(document_id)
    path, preview = await files.save_review_markdown(document["batch_id"], document_id, file)
    review = repo.get_review(document_id)
    if not review:
        raise HTTPException(status_code=400, detail="Select a variant before uploading review markdown")
    repo.update_review(document_id, uploaded_md_path=path)
    return ok({"uploaded_md_path": path, "content_preview": preview})


@router.post("/documents/{document_id}/review/save")
def save_review(document_id: str, payload: SaveReviewRequest):
    document = repo.get_document(document_id)
    review = repo.get_review(document_id)
    if not review:
        raise HTTPException(status_code=400, detail="Select a variant before saving review edits")
    path = files.write_text(files.review_dir(document["batch_id"], document_id) / "edited.md", payload.content)
    repo.update_review(document_id, edited_md_path=path)
    return ok({"edited_md_path": path})


def _selected_parse_variant(document: dict) -> dict | None:
    review = document.get("review")
    if review:
        selected_id = review.get("selected_parse_variant_id")
        for variant in document.get("parse_variants", []):
            if variant.get("variant_id") == selected_id:
                return variant
    for variant in document.get("parse_variants", []):
        if variant.get("is_selected_for_review") and variant.get("parsed_md_path"):
            return variant
    for variant in document.get("parse_variants", []):
        if variant.get("status") == VariantStatus.COMPLETE.value and variant.get("parsed_md_path"):
            return variant
    return None


def _selected_norm_variant(document: dict, parse_variant: dict | None) -> dict | None:
    review = document.get("review")
    selected_id = review.get("selected_norm_variant_id") if review else None
    variants = (parse_variant or {}).get("norm_variants", [])
    if selected_id:
        for variant in variants:
            if variant.get("norm_variant_id") == selected_id:
                return variant
    for variant in variants:
        if variant.get("is_selected_for_review") and variant.get("normalized_md_path"):
            return variant
    for variant in variants:
        if variant.get("status") == VariantStatus.COMPLETE.value and variant.get("normalized_md_path"):
            return variant
    return None


@router.get("/documents/{document_id}/review/content")
def get_review_content(document_id: str, kind: str = Query(default="review", pattern="^(review|parsed|normalized)$")):
    document = repo.get_document(document_id)
    review = document.get("review")
    parse_variant = _selected_parse_variant(document)
    norm_variant = _selected_norm_variant(document, parse_variant)

    if kind == "parsed":
        path = parse_variant.get("parsed_md_path") if parse_variant else None
        if not path:
            raise HTTPException(status_code=404, detail="Parsed markdown is not available")
        return ok({"content": files.read_text(path), "path": path, "kind": "parsed", "editable": False})

    if kind == "normalized":
        path = norm_variant.get("normalized_md_path") if norm_variant else None
        if not path:
            raise HTTPException(status_code=404, detail="Normalized markdown is not available")
        return ok({"content": files.read_text(path), "path": path, "kind": "normalized", "editable": False})

    if not review:
        raise HTTPException(status_code=404, detail="Review has not started")
    path = review.get("edited_md_path") or review.get("uploaded_md_path") or review.get("base_md_path")
    source_kind = "normalized" if norm_variant else "parsed"
    return ok({"content": files.read_text(path), "path": path, "kind": source_kind, "editable": True})


@router.post("/documents/{document_id}/review/approve")
def approve_review(document_id: str, payload: ApproveReviewRequest):
    try:
        job = admin_worker.approve_and_enqueue_chunk(
            document_id=document_id,
            selected_parse_variant_id=payload.selected_parse_variant_id,
            selected_norm_variant_id=payload.selected_norm_variant_id,
            notes=payload.notes,
        )
        document = repo.get_document(document_id)
        event_hub.publish({"type": "review_update", "document_id": document_id, "batch_id": document["batch_id"], "status": document["status"]})
        event_hub.publish({"type": "notification_update", "document_id": document_id, "batch_id": document["batch_id"]})
        return ok({"document": document, "job": job})
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/documents/{document_id}/review/reject")
def reject_review(document_id: str, payload: RejectReviewRequest):
    try:
        document = repo.get_document(document_id)
        if document["status"] not in {DocumentStatus.REVIEW_PENDING.value, DocumentStatus.REVIEW_IN_PROGRESS.value}:
            raise ValueError("Only documents awaiting review can be rejected")
        cleanup_errors: list[str] = []
        repo.mark_document_notifications_read(document_id)
        try:
            files.delete_document_source_tree(document["source_file_path"])
        except Exception as exc:
            cleanup_errors.append(f"source cleanup failed: {exc}")
        try:
            files.delete_tree(files.generated_root() / "batches" / document["batch_id"] / "documents" / document_id)
        except Exception as exc:
            cleanup_errors.append(f"generated cleanup failed: {exc}")
        log = repo.reject_review(document_id, payload.reason, cleanup_errors=cleanup_errors)
        event_hub.publish({"type": "document_update", "document_id": document_id, "batch_id": document["batch_id"], "status": DocumentStatus.REVIEW_REJECTED.value})
        event_hub.publish({"type": "review_update", "document_id": document_id, "batch_id": document["batch_id"], "status": DocumentStatus.REVIEW_REJECTED.value})
        event_hub.publish({"type": "notification_update", "document_id": document_id, "batch_id": document["batch_id"]})
        return ok({"document": repo.get_document(document_id), "log": log})
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/review/bulk/approve")
def bulk_approve_review(payload: BulkReviewRequest):
    approved = []
    errors = []
    for document_id in payload.document_ids:
        try:
            document = repo.get_document(document_id)
            complete_parse = next((variant for variant in document["parse_variants"] if variant["status"] == VariantStatus.COMPLETE.value), None)
            if not complete_parse:
                raise ValueError("No completed parse variant is available")
            complete_norm = next((norm for variant in document["parse_variants"] for norm in variant.get("norm_variants", []) if norm["status"] == VariantStatus.COMPLETE.value), None)
            job = admin_worker.approve_and_enqueue_chunk(
                document_id=document_id,
                selected_parse_variant_id=complete_parse["variant_id"],
                selected_norm_variant_id=complete_norm["norm_variant_id"] if complete_norm else None,
                notes=payload.notes,
            )
            approved.append({"document_id": document_id, "job": job})
        except Exception as exc:
            errors.append({"document_id": document_id, "error": str(exc)})
    return ok({"approved": approved, "errors": errors})


@router.post("/review/bulk/reject")
def bulk_reject_review(payload: BulkReviewRequest):
    rejected = []
    errors = []
    for document_id in payload.document_ids:
        try:
            result = reject_review(document_id, RejectReviewRequest(reason=payload.notes))
            rejected.append(result["data"])
        except Exception as exc:
            errors.append({"document_id": document_id, "error": str(exc)})
    return ok({"rejected": rejected, "errors": errors})


@router.post("/documents/{document_id}/trigger-normalize")
def trigger_normalize(document_id: str, payload: TriggerNormalizeRequest):
    document = repo.get_document(document_id)
    complete_parse = next((variant for variant in document["parse_variants"] if variant["status"] == VariantStatus.COMPLETE.value), None)
    if not complete_parse:
        raise HTTPException(status_code=400, detail="No completed parse variant is available")
    repo.set_document_status(document_id, DocumentStatus.NORMALIZE_PENDING.value)
    jobs = []
    for model in payload.models:
        norm = repo.create_norm_variant(parse_variant_id=complete_parse["variant_id"], document_id=document_id, model=model_dict(model))
        jobs.append(admin_worker.enqueue_normalize(batch_id=document["batch_id"], document_id=document_id, parse_variant_id=complete_parse["variant_id"], norm_variant_id=norm["norm_variant_id"]))
    return ok({"document": repo.get_document(document_id), "jobs": jobs})


@router.post("/documents/{document_id}/retry-parse")
def retry_parse(document_id: str, payload: RetryParseRequest):
    document = repo.get_document(document_id)
    variant = repo.get_parse_variant(payload.parse_variant_id)
    if variant["document_id"] != document_id or variant["status"] != VariantStatus.FAILED.value:
        raise HTTPException(status_code=400, detail="Only failed parse variants can be retried")
    repo.update_parse_variant(payload.parse_variant_id, status=VariantStatus.PENDING.value, error_message=None, error_detail=None)
    repo.set_document_status(document_id, DocumentStatus.PARSE_PENDING.value)
    job = admin_worker.enqueue_parse(batch_id=document["batch_id"], document_id=document_id, parse_variant_id=payload.parse_variant_id)
    return ok({"parse_variant": repo.get_parse_variant(payload.parse_variant_id), "job": job})


@router.post("/documents/{document_id}/retry-normalize")
def retry_normalize(document_id: str, payload: RetryNormalizeRequest):
    document = repo.get_document(document_id)
    norm = repo.get_norm_variant(payload.norm_variant_id)
    if norm["document_id"] != document_id or norm["status"] != VariantStatus.FAILED.value:
        raise HTTPException(status_code=400, detail="Only failed normalization variants can be retried")
    repo.update_norm_variant(payload.norm_variant_id, status=VariantStatus.PENDING.value, failure_mode=None, error_message=None, error_detail=None)
    repo.set_document_status(document_id, DocumentStatus.NORMALIZE_PENDING.value)
    job = admin_worker.enqueue_normalize(batch_id=document["batch_id"], document_id=document_id, parse_variant_id=norm["parse_variant_id"], norm_variant_id=payload.norm_variant_id)
    return ok({"norm_variant": repo.get_norm_variant(payload.norm_variant_id), "job": job})


@router.post("/documents/{document_id}/retry-chunking")
def retry_chunking(document_id: str):
    document = repo.get_document(document_id)
    if document["status"] not in {DocumentStatus.CHUNK_FAILED.value, DocumentStatus.INDEXED.value, DocumentStatus.REVIEW_APPROVED.value}:
        raise HTTPException(status_code=400, detail="Document is not ready for chunking retry")
    repo.set_document_status(document_id, DocumentStatus.CHUNK_PENDING.value)
    job = admin_worker.enqueue_chunk(batch_id=document["batch_id"], document_id=document_id)
    return ok({"document": repo.get_document(document_id), "job": job})


@router.get("/chunks")
def list_chunks(document_id: Optional[str] = None, batch_id: Optional[str] = None, filename: Optional[str] = None, source: Optional[str] = None, doc_type: Optional[str] = None, search: Optional[str] = None, page: int = 1, limit: int = 25):
    if filename or source:
        return ok(list_chroma_chunks(filename=filename, source=source, doc_type=doc_type, search=search, page=page, limit=limit))
    sqlite_page = repo.list_chunks(document_id=document_id, batch_id=batch_id, search=search, page=page, limit=limit)
    if page == 1 and not document_id and not batch_id:
        generated = iter_generated_chunks(limit=limit)
        if search:
            generated = [item for item in generated if search.lower() in item["content"].lower()]
        combined = sqlite_page["items"] + generated[: max(limit - len(sqlite_page["items"]), 0)]
        return ok({"items": combined, "total": sqlite_page["total"] + len(generated), "page": page})
    return ok(sqlite_page)


@router.get("/chunks/{chunk_id}")
def get_chunk(chunk_id: str):
    try:
        return ok(repo.get_chunk(chunk_id))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/logs")
def list_logs(level: Optional[str] = None, stage: Optional[str] = None, search: Optional[str] = None, page: int = 1, limit: int = 50):
    return ok(repo.list_logs(level=level, stage=stage, search=search, page=page, limit=limit))


@router.get("/logs/failed-jobs")
def failed_jobs(page: int = 1, limit: int = 25):
    jobs = repo.list_jobs(status="FAILED", limit=limit)
    return ok({"items": jobs["items"], "total": jobs["total"], "page": page})


@router.get("/jobs")
def list_jobs(status: Optional[str] = None, limit: int = 100):
    return ok(repo.list_jobs(status=status, limit=limit))


@router.get("/notifications")
def list_notifications(unread_only: bool = False, page: int = 1, limit: int = 100):
    return ok(repo.list_notifications(unread_only=unread_only, page=page, limit=limit))


@router.patch("/notifications/{notification_id}/read")
def mark_notification_read(notification_id: str):
    return ok(repo.mark_notification_read(notification_id))


@router.post("/notifications/mark-all-read")
def mark_all_notifications_read():
    return ok(repo.mark_all_notifications_read())


@router.delete("/notifications/{notification_id}")
def delete_notification(notification_id: str):
    return ok(repo.delete_notification(notification_id))


@router.get("/settings/llm-endpoints")
def list_llm_endpoints():
    return ok(repo.list_llm_endpoints())


@router.post("/settings/llm-endpoints")
def upsert_llm_endpoint(payload: LlmEndpointRequest):
    return ok(repo.upsert_llm_endpoint(endpoint_id=None, **model_dict(payload)))


@router.get("/vector/stats")
def vector_stats():
    try:
        from backend.rag.store import get_vector_store

        chroma_count = get_vector_store().count()
    except Exception as exc:
        chroma_count = None
        return ok({"healthy": False, "error": str(exc), **repo.get_stats(), "filesystem": inventory_summary()})
    return ok({"healthy": True, "chroma_count": chroma_count, **repo.get_stats(), "filesystem": inventory_summary()})


@router.get("/vector/stats/detail")
def vector_stats_detail():
    return ok(vector_inspector.vector_stats_detail())


@router.post("/vector/probe")
async def vector_probe(payload: VectorProbeRequest):
    try:
        result = await vector_inspector.vector_probe(**model_dict(payload))
        return ok(result)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/events")
async def events():
    subscriber = event_hub.subscribe()

    async def generator():
        try:
            yield ": admin events connected\n\n"
            while True:
                try:
                    event = await asyncio.to_thread(subscriber.get, True, 30)
                    yield event_hub.sse_frame(event)
                except queue.Empty:
                    yield event_hub.sse_frame({"type": "ping"})
        finally:
            event_hub.unsubscribe(subscriber)

    return StreamingResponse(generator(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
