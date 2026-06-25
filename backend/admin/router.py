from __future__ import annotations

import asyncio
import queue
import shutil
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, StreamingResponse

from backend.admin import files
from backend.admin.events import event_hub
from backend.admin.repository import new_id, repo
from backend.admin.schemas import (
    ApproveReviewRequest,
    BatchConfig,
    BatchConfigPatch,
    DocumentStatus,
    LlmEndpointRequest,
    RetryNormalizeRequest,
    RetryParseRequest,
    SaveReviewRequest,
    SelectVariantRequest,
    TriggerNormalizeRequest,
    VariantStatus,
)
from backend.admin.worker import admin_worker


router = APIRouter()


def ok(data):
    return {"data": data, "error": None}


def model_dict(model) -> dict:
    return model.model_dump(mode="json")


@router.get("/stats")
def stats():
    return ok(repo.get_stats())


@router.post("/batches")
async def create_batch(
    files_upload: list[UploadFile] = File(alias="files"),
    batch_name: str = Form(...),
    batch_description: Optional[str] = Form(default=None),
):
    batch_id = new_id("batch")
    config = model_dict(BatchConfig())
    documents = []
    for upload in files_upload:
        documents.append(await files.save_source_upload(batch_id, upload, {
            "parsers": config["default_parsers"],
            "normalization_enabled": config["default_normalization_enabled"],
            "normalization_models": config["default_normalization_models"],
        }))
    batch = repo.create_batch(batch_id=batch_id, name=batch_name, description=batch_description, config=config, documents=documents)
    note = repo.notify(type_="SUCCESS", title="Batch created", message=f"{len(documents)} documents uploaded", batch_id=batch["batch_id"])
    event_hub.publish({"type": "notification", "data": note})
    return ok(batch)


@router.get("/batches")
def list_batches(status: Optional[str] = None, page: int = 1, limit: int = 25, search: Optional[str] = None):
    return ok(repo.list_batches(status=status, search=search, page=page, limit=limit))


@router.get("/batches/{batch_id}")
def get_batch(batch_id: str):
    try:
        return ok(repo.get_batch(batch_id, include_documents=True))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.patch("/batches/{batch_id}/config")
def update_batch_config(batch_id: str, payload: BatchConfigPatch):
    try:
        return ok(repo.update_batch_config(batch_id, model_dict(payload)))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


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
    note = repo.notify(type_="STAGE_UPDATE", title="Batch submitted", message=f"{batch['total_documents']} documents queued", batch_id=batch_id)
    event_hub.publish({"type": "notification", "data": note})
    return ok(repo.get_batch(batch_id, include_documents=True))


@router.delete("/batches/{batch_id}")
def delete_batch(batch_id: str):
    try:
        batch = repo.get_batch(batch_id, include_documents=False)
        result = repo.delete_draft_batch(batch_id)
        batch_path = files.files_root() / "batches" / batch_id
        if batch["status"] == "DRAFT" and batch_path.exists():
            shutil.rmtree(batch_path)
        return ok(result)
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/documents")
def list_documents(status: Optional[str] = None, page: int = 1, limit: int = 100, search: Optional[str] = None):
    return ok(repo.list_documents(status=status, search=search, page=page, limit=limit))


@router.get("/documents/{document_id}")
def get_document(document_id: str):
    try:
        return ok(repo.get_document(document_id))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/documents/{document_id}/files/{file_type}")
def download_document_file(document_id: str, file_type: str):
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
    return FileResponse(target, filename=target.name, media_type="application/octet-stream")


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


@router.get("/documents/{document_id}/review/content")
def get_review_content(document_id: str):
    document = repo.get_document(document_id)
    review = document.get("review")
    if not review:
        raise HTTPException(status_code=404, detail="Review has not started")
    path = review.get("edited_md_path") or review.get("uploaded_md_path") or review.get("base_md_path")
    return ok({"content": files.read_text(path), "path": path})


@router.post("/documents/{document_id}/review/approve")
def approve_review(document_id: str, payload: ApproveReviewRequest):
    try:
        job = admin_worker.approve_and_enqueue_chunk(
            document_id=document_id,
            selected_parse_variant_id=payload.selected_parse_variant_id,
            selected_norm_variant_id=payload.selected_norm_variant_id,
            notes=payload.notes,
        )
        return ok({"document": repo.get_document(document_id), "job": job})
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


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
def list_chunks(document_id: Optional[str] = None, batch_id: Optional[str] = None, search: Optional[str] = None, page: int = 1, limit: int = 25):
    return ok(repo.list_chunks(document_id=document_id, batch_id=batch_id, search=search, page=page, limit=limit))


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
        return ok({"healthy": False, "error": str(exc), **repo.get_stats()})
    return ok({"healthy": True, "chroma_count": chroma_count, **repo.get_stats()})


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
                    yield "event: ping\ndata: {}\n\n"
        finally:
            event_hub.unsubscribe(subscriber)

    return StreamingResponse(generator(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

