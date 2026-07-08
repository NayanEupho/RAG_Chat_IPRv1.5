from __future__ import annotations

import os
import queue
import shutil
import threading
import time
import traceback
from pathlib import Path
from typing import Any, Optional

from backend.admin import files
from backend.admin.events import event_hub
from backend.admin.repository import now_iso, repo
from backend.admin.schemas import BatchStatus, DocumentStatus, JobStatus, PipelineStage, VariantStatus


_EMBED_CLIENTS: dict[str, Any] = {}
_EMBED_CLIENT_LOCK = threading.Lock()


def get_embed_client(host: str) -> Any:
    import httpx
    import ollama

    with _EMBED_CLIENT_LOCK:
        client = _EMBED_CLIENTS.get(host)
        if client is None:
            client = ollama.Client(
                host=host,
                timeout=httpx.Timeout(connect=10.0, read=float(os.getenv("ADMIN_EMBED_READ_TIMEOUT_SECONDS", "120")), write=30.0, pool=5.0),
            )
            _EMBED_CLIENTS[host] = client
        return client


def embed_text_batches(client: Any, model: str, texts: list[str], batch_size: int = 50) -> list[list[float]]:
    embeddings: list[list[float]] = []
    for index in range(0, len(texts), batch_size):
        response = client.embed(model=model, input=texts[index:index + batch_size])
        embeddings.extend(response.get("embeddings", []))
    return embeddings


def source_markdown_name(filename: str) -> str:
    return f"{Path(filename).stem}.md"


def rewrite_chunk_doc_label(text: str, *, current_filename: str, source_filename: str) -> str:
    current_label = source_markdown_name(current_filename)
    source_label = source_markdown_name(source_filename)
    for label in {current_filename, current_label}:
        prefix = f"[Doc: {label} |"
        if text.startswith(prefix):
            return f"[Doc: {source_label} |{text[len(prefix):]}"
    return text


class AdminWorker:
    def __init__(self) -> None:
        self._queue: queue.Queue[str] = queue.Queue()
        self._threads: list[threading.Thread] = []
        self._running = False
        self._concurrency = max(1, int(os.getenv("ADMIN_DASHBOARD_WORKERS", "2")))

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._threads = []
        for index in range(self._concurrency):
            thread = threading.Thread(target=self._run, name=f"admin-dashboard-worker-{index + 1}", daemon=True)
            thread.start()
            self._threads.append(thread)

    def stop(self) -> None:
        self._running = False
        for _ in self._threads:
            self._queue.put("")
        for thread in self._threads:
            thread.join(timeout=5)
        self._threads = []

    def enqueue(self, job_id: str) -> None:
        self.start()
        self._queue.put(job_id)

    def recover_incomplete_jobs(self) -> dict[str, Any]:
        self.start()
        requeued: list[str] = []
        skipped: list[dict[str, str]] = []
        for job in repo.list_recoverable_jobs():
            action, reason = self._prepare_recovery(job)
            if action == "requeue":
                self.enqueue(job["job_id"])
                requeued.append(job["job_id"])
                self._publish_job(job["job_id"])
            else:
                skipped.append({"job_id": job["job_id"], "reason": reason})
        if requeued or skipped:
            repo.log(
                stage=PipelineStage.SYSTEM.value,
                level="INFO",
                message=f"Recovered {len(requeued)} admin ingestion job(s)",
                detail=f"requeued={requeued}; skipped={skipped}",
            )
            event_hub.publish({"type": "stats_update", "action": "job_recovery", "requeued": len(requeued), "skipped": len(skipped)})
        return {"requeued": requeued, "skipped": skipped}

    def _prepare_recovery(self, job: dict[str, Any]) -> tuple[str, str]:
        if job.get("cancel_requested") or self._is_cancelled(job):
            repo.update_job(job["job_id"], status=JobStatus.CANCELLED.value, progress=100, detail="Skipped recovery because job is cancelled")
            return "skip", "cancelled"
        try:
            if job["job_type"] == "parse":
                return self._prepare_parse_recovery(job)
            if job["job_type"] == "normalize":
                return self._prepare_normalize_recovery(job)
            if job["job_type"] == "chunk":
                return self._prepare_chunk_recovery(job)
            repo.update_job(job["job_id"], status=JobStatus.FAILED.value, progress=100, detail="Skipped recovery for unknown job type", error_message=f"Unknown job type: {job['job_type']}")
            return "skip", "unknown_job_type"
        except KeyError as exc:
            repo.update_job(job["job_id"], status=JobStatus.FAILED.value, progress=100, detail="Skipped recovery because linked record is missing", error_message=str(exc))
            return "skip", "missing_linked_record"

    def _prepare_parse_recovery(self, job: dict[str, Any]) -> tuple[str, str]:
        document = repo.get_document(job["document_id"])
        variant = repo.get_parse_variant(job["parse_variant_id"])
        if variant["status"] == VariantStatus.COMPLETE.value or document["status"] not in {DocumentStatus.PARSE_PENDING.value, DocumentStatus.PARSE_RUNNING.value}:
            repo.update_job(job["job_id"], status=JobStatus.COMPLETE.value, progress=100, detail="Recovered as complete; parse stage already advanced")
            return "skip", "stage_already_advanced"
        if variant["status"] == VariantStatus.FAILED.value or document["status"] == DocumentStatus.PARSE_FAILED.value:
            repo.update_job(job["job_id"], status=JobStatus.FAILED.value, progress=100, detail="Recovered as failed; parse variant already failed", error_message=document.get("error_summary"))
            return "skip", "stage_failed"
        needs_reset = job["status"] == JobStatus.RUNNING.value or document["status"] == DocumentStatus.PARSE_RUNNING.value or variant["status"] == VariantStatus.RUNNING.value
        if needs_reset:
            repo.set_document_status(document["document_id"], DocumentStatus.PARSE_PENDING.value)
            repo.update_parse_variant(variant["variant_id"], status=VariantStatus.PENDING.value, started_at=None, completed_at=None, duration_ms=None, error_message=None, error_detail=None)
        if job["status"] == JobStatus.RUNNING.value:
            repo.reset_job_for_recovery(job["job_id"])
        return "requeue", "parse_requeued"

    def _prepare_normalize_recovery(self, job: dict[str, Any]) -> tuple[str, str]:
        document = repo.get_document(job["document_id"])
        norm = repo.get_norm_variant(job["norm_variant_id"])
        if norm["status"] == VariantStatus.COMPLETE.value or document["status"] not in {DocumentStatus.NORMALIZE_PENDING.value, DocumentStatus.NORMALIZE_RUNNING.value}:
            repo.update_job(job["job_id"], status=JobStatus.COMPLETE.value, progress=100, detail="Recovered as complete; normalization stage already advanced")
            return "skip", "stage_already_advanced"
        if norm["status"] == VariantStatus.FAILED.value or document["status"] == DocumentStatus.NORMALIZE_FAILED.value:
            repo.update_job(job["job_id"], status=JobStatus.FAILED.value, progress=100, detail="Recovered as failed; normalization variant already failed", error_message=document.get("error_summary"))
            return "skip", "stage_failed"
        needs_reset = job["status"] == JobStatus.RUNNING.value or document["status"] == DocumentStatus.NORMALIZE_RUNNING.value or norm["status"] == VariantStatus.RUNNING.value
        if needs_reset:
            repo.set_document_status(document["document_id"], DocumentStatus.NORMALIZE_PENDING.value)
            repo.update_norm_variant(norm["norm_variant_id"], status=VariantStatus.PENDING.value, started_at=None, completed_at=None, time_taken_ms=None, error_message=None, error_detail=None)
        if job["status"] == JobStatus.RUNNING.value:
            repo.reset_job_for_recovery(job["job_id"])
        return "requeue", "normalize_requeued"

    def _prepare_chunk_recovery(self, job: dict[str, Any]) -> tuple[str, str]:
        document = repo.get_document(job["document_id"])
        if document["status"] == DocumentStatus.INDEXED.value:
            repo.update_job(job["job_id"], status=JobStatus.COMPLETE.value, progress=100, detail="Recovered as complete; document is already indexed")
            return "skip", "stage_already_advanced"
        if document["status"] == DocumentStatus.CHUNK_FAILED.value:
            repo.update_job(job["job_id"], status=JobStatus.FAILED.value, progress=100, detail="Recovered as failed; chunking already failed", error_message=document.get("error_summary"))
            return "skip", "stage_failed"
        if document["status"] not in {DocumentStatus.CHUNK_PENDING.value, DocumentStatus.CHUNK_RUNNING.value, DocumentStatus.REVIEW_APPROVED.value}:
            repo.update_job(job["job_id"], status=JobStatus.COMPLETE.value, progress=100, detail="Skipped recovery; document is not waiting for chunking")
            return "skip", "stage_not_requeueable"
        needs_reset = job["status"] == JobStatus.RUNNING.value or document["status"] == DocumentStatus.CHUNK_RUNNING.value
        if needs_reset:
            repo.set_document_status(document["document_id"], DocumentStatus.CHUNK_PENDING.value)
        if job["status"] == JobStatus.RUNNING.value:
            repo.reset_job_for_recovery(job["job_id"])
        return "requeue", "chunk_requeued"

    def enqueue_parse(self, *, batch_id: str, document_id: str, parse_variant_id: str) -> dict[str, Any]:
        job = repo.create_job(
            job_type="parse",
            stage=PipelineStage.PARSE.value,
            batch_id=batch_id,
            document_id=document_id,
            parse_variant_id=parse_variant_id,
            payload={"parse_variant_id": parse_variant_id},
        )
        self.enqueue(job["job_id"])
        return job

    def enqueue_normalize(self, *, batch_id: str, document_id: str, parse_variant_id: str, norm_variant_id: str) -> dict[str, Any]:
        job = repo.create_job(
            job_type="normalize",
            stage=PipelineStage.NORMALIZE.value,
            batch_id=batch_id,
            document_id=document_id,
            parse_variant_id=parse_variant_id,
            norm_variant_id=norm_variant_id,
            payload={"norm_variant_id": norm_variant_id},
        )
        self.enqueue(job["job_id"])
        return job

    def enqueue_chunk(self, *, batch_id: str, document_id: str) -> dict[str, Any]:
        job = repo.create_job(
            job_type="chunk",
            stage=PipelineStage.CHUNK.value,
            batch_id=batch_id,
            document_id=document_id,
            payload={"document_id": document_id},
        )
        self.enqueue(job["job_id"])
        return job

    def _run(self) -> None:
        while True:
            job_id = self._queue.get()
            try:
                if not job_id:
                    if not self._running:
                        return
                    continue
                self._run_job(job_id)
            finally:
                self._queue.task_done()

    def _run_job(self, job_id: str) -> None:
        job = repo.get_job(job_id)
        if job.get("cancel_requested") or self._is_cancelled(job):
            repo.update_job(job_id, status=JobStatus.CANCELLED.value, progress=100, detail="Job cancelled before start")
            self._publish_job(job_id)
            return
        repo.update_job(job_id, status=JobStatus.RUNNING.value, progress=1, detail="Job started")
        self._publish_job(job_id)
        try:
            if job["job_type"] == "parse":
                self._parse(job_id, job)
            elif job["job_type"] == "normalize":
                self._normalize(job_id, job)
            elif job["job_type"] == "chunk":
                self._chunk(job_id, job)
            else:
                raise ValueError(f"Unknown job type: {job['job_type']}")
            if self._is_cancelled(job):
                repo.update_job(job_id, status=JobStatus.CANCELLED.value, progress=100, detail="Job cancelled")
                self._publish_job(job_id)
                return
            repo.update_job(job_id, status=JobStatus.COMPLETE.value, progress=100, detail="Job complete")
            self._publish_job(job_id)
        except Exception as exc:
            if self._is_cancelled(job):
                repo.update_job(job_id, status=JobStatus.CANCELLED.value, progress=100, detail="Job cancelled during execution")
                repo.log(
                    stage=job["stage"],
                    level="INFO",
                    message="Job cancelled during execution",
                    batch_id=job.get("batch_id"),
                    document_id=job.get("document_id"),
                    parse_variant_id=job.get("parse_variant_id"),
                    norm_variant_id=job.get("norm_variant_id"),
                    job_id=job_id,
                )
                self._publish_job(job_id)
                return
            detail = traceback.format_exc()
            repo.update_job(
                job_id,
                status=JobStatus.FAILED.value,
                progress=100,
                detail="Job failed",
                error_message=str(exc),
                error_detail=detail,
            )
            repo.log(
                stage=job["stage"],
                level="ERROR",
                message=str(exc),
                detail=detail,
                batch_id=job.get("batch_id"),
                document_id=job.get("document_id"),
                parse_variant_id=job.get("parse_variant_id"),
                norm_variant_id=job.get("norm_variant_id"),
                job_id=job_id,
            )
            note = repo.notify(
                type_="ERROR",
                title=f"{job['stage']} failed",
                message=str(exc),
                detail=detail,
                batch_id=job.get("batch_id"),
                document_id=job.get("document_id"),
                job_id=job_id,
            )
            event_hub.publish({"type": "job_error", "batch_id": job.get("batch_id"), "document_id": job.get("document_id"), "stage": job["stage"], "message": str(exc), "detail": detail})
            event_hub.publish({"type": "notification", "data": note})
            self._publish_job(job_id)

    def _is_cancelled(self, job: dict[str, Any]) -> bool:
        if job.get("cancel_requested"):
            return True
        batch_id = job.get("batch_id")
        if batch_id:
            try:
                if repo.get_batch(batch_id, include_documents=False)["status"] == BatchStatus.CANCELLED.value:
                    return True
            except KeyError:
                return True
        document_id = job.get("document_id")
        if document_id:
            try:
                if repo.get_document(document_id)["status"] == DocumentStatus.CANCELLED.value:
                    return True
            except KeyError:
                return True
        return False

    def _parse(self, job_id: str, job: dict[str, Any]) -> None:
        from backend.ingestion.models import ParsedDocument
        from backend.ingestion.parsers import parse_to_markdown
        from backend.ingestion.processor import DocumentProcessor
        from backend.ingestion.quality.gates import analyze_markdown

        document = repo.get_document(job["document_id"])
        variant = repo.get_parse_variant(job["parse_variant_id"])
        batch_id = document["batch_id"]
        parser_type = variant["parser_type"]
        doc_type = document["effective_config"].get("ingestion_type", "general")
        started_at = now_iso()
        start = time.monotonic()
        repo.set_document_status(document["document_id"], DocumentStatus.PARSE_RUNNING.value)
        repo.update_parse_variant(variant["variant_id"], status=VariantStatus.RUNNING.value, started_at=started_at, error_message=None, error_detail=None)
        repo.log(stage=PipelineStage.PARSE.value, level="INFO", message=f"Started {parser_type} parse", batch_id=batch_id, document_id=document["document_id"], parse_variant_id=variant["variant_id"], job_id=job_id)
        self._publish_document(document["document_id"])

        try:
            processor = DocumentProcessor()
            parsed = parse_to_markdown(
                file_path=document["source_file_path"],
                mode=parser_type,
                doc_type=doc_type,
                converter_factory=processor._get_converter,
                scanned_detector=processor._is_scanned_pdf,
                clean_markdown=processor._clean_markdown_artifacts,
                fix_header_hierarchy=processor._fix_header_hierarchy,
            )
            selected_parser = parsed.selected_parser or parser_type
            raw = parsed.parser_outputs.get(selected_parser) or parsed.parser_outputs.get(parser_type) or parsed.markdown
            diagnostics = analyze_markdown(parsed.markdown, parser=selected_parser, source_type=selected_parser)
            parsed_doc = ParsedDocument(
                file_path=document["source_file_path"],
                filename=document["original_filename"],
                doc_type=doc_type,
                markdown=parsed.markdown,
                selected_parser=selected_parser,
                diagnostics=diagnostics,
                parser_outputs=parsed.parser_outputs or {selected_parser: parsed.markdown},
                raw_markdown=raw,
            )
            target_dir = files.variant_dir(batch_id, document["document_id"], variant["variant_id"])
            raw_path = files.write_text(target_dir / "raw.md", parsed_doc.raw_markdown or "")
            parsed_path = files.write_text(target_dir / "parsed.md", parsed_doc.markdown)
            completed_at = now_iso()
            repo.update_parse_variant(
                variant["variant_id"],
                status=VariantStatus.COMPLETE.value,
                raw_md_path=raw_path,
                parsed_md_path=parsed_path,
                completed_at=completed_at,
                duration_ms=int((time.monotonic() - start) * 1000),
            )
            repo.log(stage=PipelineStage.PARSE.value, level="INFO", message=f"Completed {parser_type} parse using {selected_parser}", batch_id=batch_id, document_id=document["document_id"], parse_variant_id=variant["variant_id"], job_id=job_id)
            if self._is_cancelled(job):
                return
            self._after_parse(document["document_id"], variant["variant_id"])
        except Exception as exc:
            detail = traceback.format_exc()
            repo.update_parse_variant(
                variant["variant_id"],
                status=VariantStatus.FAILED.value,
                completed_at=now_iso(),
                duration_ms=int((time.monotonic() - start) * 1000),
                error_message=str(exc),
                error_detail=detail,
            )
            repo.set_document_status(document["document_id"], DocumentStatus.PARSE_FAILED.value, error_summary=f"Parse failed ({parser_type}): {exc}")
            raise
        finally:
            self._publish_document(document["document_id"])

    def _after_parse(self, document_id: str, parse_variant_id: str) -> None:
        document = repo.get_document(document_id)
        if document["status"] == DocumentStatus.CANCELLED.value or repo.get_batch(document["batch_id"], include_documents=False)["status"] == BatchStatus.CANCELLED.value:
            return
        config = document["effective_config"]
        if config.get("normalization_enabled") and config.get("normalization_models"):
            repo.set_document_status(document_id, DocumentStatus.NORMALIZE_PENDING.value)
            for model in config["normalization_models"]:
                norm = repo.create_norm_variant(parse_variant_id=parse_variant_id, document_id=document_id, model=model)
                self.enqueue_normalize(batch_id=document["batch_id"], document_id=document_id, parse_variant_id=parse_variant_id, norm_variant_id=norm["norm_variant_id"])
            return

        if self._all_parse_variants_terminal(document_id):
            if document["effective_config"].get("review_required", True):
                repo.set_document_status(document_id, DocumentStatus.REVIEW_PENDING.value)
                repo.log(stage=PipelineStage.REVIEW.value, level="INFO", message="Document ready for review", batch_id=document["batch_id"], document_id=document_id)
                note = repo.notify(type_="STAGE_UPDATE", title="Document ready for review", message=document["original_filename"], batch_id=document["batch_id"], document_id=document_id)
                event_hub.publish({"type": "notification", "data": note})
            else:
                self.approve_and_enqueue_chunk(
                    document_id=document_id,
                    selected_parse_variant_id=parse_variant_id,
                    selected_norm_variant_id=None,
                    notes="Auto-approved because review is disabled for this batch.",
                )

    def _normalize(self, job_id: str, job: dict[str, Any]) -> None:
        from backend.ingestion.normalizers import LlmMarkdownNormalizer

        document = repo.get_document(job["document_id"])
        variant = repo.get_parse_variant(job["parse_variant_id"])
        norm = repo.get_norm_variant(job["norm_variant_id"])
        doc_type = document["effective_config"].get("ingestion_type", "general")
        if not variant.get("parsed_md_path"):
            raise ValueError("Cannot normalize before parsing completes")

        started_at = now_iso()
        start = time.monotonic()
        repo.set_document_status(document["document_id"], DocumentStatus.NORMALIZE_RUNNING.value)
        repo.update_norm_variant(norm["norm_variant_id"], status=VariantStatus.RUNNING.value, started_at=started_at, error_message=None, error_detail=None)
        repo.log(stage=PipelineStage.NORMALIZE.value, level="INFO", message=f"Started normalization with {norm['model_config']['display_name']}", batch_id=document["batch_id"], document_id=document["document_id"], parse_variant_id=variant["variant_id"], norm_variant_id=norm["norm_variant_id"], job_id=job_id)
        self._publish_document(document["document_id"])

        try:
            source = files.read_text(variant["parsed_md_path"])
            normalizer = LlmMarkdownNormalizer()
            result = normalizer.normalize(
                source,
                filename=document["original_filename"],
                doc_type=doc_type,
                parser=variant["parser_type"],
                model_config=norm["model_config"],
            )
            target_dir = files.normalization_dir(document["batch_id"], document["document_id"], norm["norm_variant_id"])
            normalized_path = files.write_text(target_dir / "normalized.md", result.markdown)
            completed_at = now_iso()
            repo.update_norm_variant(
                norm["norm_variant_id"],
                status=VariantStatus.COMPLETE.value,
                normalized_md_path=normalized_path,
                time_taken_ms=int((time.monotonic() - start) * 1000),
                completed_at=completed_at,
            )
            repo.log(stage=PipelineStage.NORMALIZE.value, level="INFO", message="Normalization complete", batch_id=document["batch_id"], document_id=document["document_id"], parse_variant_id=variant["variant_id"], norm_variant_id=norm["norm_variant_id"], job_id=job_id)
            if self._is_cancelled(job):
                return
            if self._all_norm_variants_terminal(document["document_id"]):
                if document["effective_config"].get("review_required", True):
                    repo.set_document_status(document["document_id"], DocumentStatus.REVIEW_PENDING.value)
                    note = repo.notify(type_="STAGE_UPDATE", title="Document ready for review", message=document["original_filename"], batch_id=document["batch_id"], document_id=document["document_id"])
                    event_hub.publish({"type": "notification", "data": note})
                else:
                    self.approve_and_enqueue_chunk(
                        document_id=document["document_id"],
                        selected_parse_variant_id=variant["variant_id"],
                        selected_norm_variant_id=norm["norm_variant_id"],
                        notes="Auto-approved because review is disabled for this batch.",
                    )
        except Exception as exc:
            detail = traceback.format_exc()
            target_dir = files.normalization_dir(document["batch_id"], document["document_id"], norm["norm_variant_id"])
            partial = target_dir / "normalized.md"
            partial.unlink(missing_ok=True)
            repo.update_norm_variant(
                norm["norm_variant_id"],
                status=VariantStatus.FAILED.value,
                failure_mode="COMPLETE_FAILURE",
                normalized_md_path=None,
                time_taken_ms=int((time.monotonic() - start) * 1000),
                completed_at=now_iso(),
                error_message=str(exc),
                error_detail=detail,
            )
            repo.set_document_status(document["document_id"], DocumentStatus.PARSE_COMPLETE.value, error_summary=f"Normalization failed: {exc}")
            raise
        finally:
            self._publish_document(document["document_id"])

    def _chunk(self, job_id: str, job: dict[str, Any]) -> None:
        from backend.config import get_config
        from backend.ingestion.chunkers.markdown import chunk_markdown_file
        from backend.rag.store import get_vector_store

        document = repo.get_document(job["document_id"])
        review = document.get("review")
        if document["status"] == DocumentStatus.CANCELLED.value or repo.get_batch(document["batch_id"], include_documents=False)["status"] == BatchStatus.CANCELLED.value:
            raise ValueError("Cannot chunk a cancelled document")
        if not review or not review.get("review_approved_md_path"):
            raise ValueError("Cannot chunk before review approval")

        repo.set_document_status(document["document_id"], DocumentStatus.CHUNK_RUNNING.value)
        repo.log(stage=PipelineStage.CHUNK.value, level="INFO", message="Chunking approved markdown", batch_id=document["batch_id"], document_id=document["document_id"], job_id=job_id)
        self._publish_document(document["document_id"])
        try:
            store = get_vector_store()
            if hasattr(store, "delete_document"):
                store.delete_document(document["document_id"])
            doc_type = document["effective_config"].get("ingestion_type", "general")
            chunks = chunk_markdown_file(
                review["review_approved_md_path"],
                filename=document["original_filename"],
                doc_type=doc_type,
                source_type="markdown",
            )
            if not chunks:
                raise ValueError("Chunking produced zero chunks; document was not indexed")
            reviewed_md_name = Path(review["review_approved_md_path"]).name
            for chunk in chunks:
                chunk["text"] = rewrite_chunk_doc_label(
                    chunk.get("text") or "",
                    current_filename=reviewed_md_name,
                    source_filename=document["original_filename"],
                )
                chunk.setdefault("metadata", {})["source_markdown_filename"] = source_markdown_name(document["original_filename"])
            texts = [chunk["text"] for chunk in chunks]
            config = get_config()
            if not config.embedding_model:
                raise ValueError("Embedding Model not configured")
            client = get_embed_client(config.embedding_model.host)
            embedding_model = config.embedding_model.model_name
            embeddings = embed_text_batches(client, embedding_model, texts)
            if len(embeddings) != len(texts):
                raise RuntimeError("Embedding count mismatch")

            indexed_at = now_iso()
            ids = [f"{document['document_id']}_{idx}" for idx in range(len(chunks))]
            metadatas = []
            mirror = []
            for idx, chunk in enumerate(chunks):
                metadata = dict(chunk.get("metadata") or {})
                metadata.update(
                    {
                        "document_id": document["document_id"],
                        "batch_id": document["batch_id"],
                        "filename": document["original_filename"],
                        "doc_type": doc_type,
                        "ingestion_type": doc_type,
                        "chunk_index": idx,
                        "indexed_at": indexed_at,
                    }
                )
                text = chunk["text"]
                section_path = metadata.get("section_path") or metadata.get("section") or None
                metadatas.append(metadata)
                mirror.append(
                    {
                        "chunk_id": ids[idx],
                        "content": text,
                        "chunk_index": idx,
                        "section_path": section_path,
                        "page_numbers": metadata.get("page_numbers") or [],
                        "token_count": len(text.split()),
                        "char_count": len(text),
                        "embedding_model": embedding_model,
                        "indexed_at": indexed_at,
                        "chroma_id": ids[idx],
                    }
                )
            if texts:
                store.add_documents(texts, metadatas, ids, embeddings)
            repo.replace_document_chunks(document_id=document["document_id"], batch_id=document["batch_id"], chunks=mirror)
            repo.set_document_status(document["document_id"], DocumentStatus.INDEXED.value, chunk_count=len(chunks), indexed_at=indexed_at)
            repo.log(stage=PipelineStage.INDEX.value, level="INFO", message=f"Indexed {len(chunks)} chunks", batch_id=document["batch_id"], document_id=document["document_id"], job_id=job_id)
            batch = repo.get_batch(document["batch_id"], include_documents=False)
            if batch["status"] == BatchStatus.COMPLETE.value and not repo.notification_exists(title="Ingestion completed", batch_id=document["batch_id"], type_="INGESTION_COMPLETED"):
                note = repo.notify(type_="INGESTION_COMPLETED", title="Ingestion completed", message=f"Batch {batch['name']} indexed successfully", batch_id=document["batch_id"], job_id=job_id)
                event_hub.publish({"type": "notification", "data": note})
            event_hub.publish({"type": "warehouse_update", "action": "index", "origin": "admin", "document_id": document["document_id"], "batch_id": document["batch_id"]})
            event_hub.publish({"type": "stats_update", "action": "index"})
        except Exception as exc:
            detail = traceback.format_exc()
            repo.set_document_status(document["document_id"], DocumentStatus.CHUNK_FAILED.value, error_summary=f"Chunking failed: {exc}")
            repo.log(stage=PipelineStage.CHUNK.value, level="ERROR", message=str(exc), detail=detail, batch_id=document["batch_id"], document_id=document["document_id"], job_id=job_id)
            raise
        finally:
            self._publish_document(document["document_id"])

    def approve_and_enqueue_chunk(self, *, document_id: str, selected_parse_variant_id: str, selected_norm_variant_id: Optional[str], notes: Optional[str]) -> dict[str, Any]:
        document = repo.get_document(document_id)
        parse_variant = repo.get_parse_variant(selected_parse_variant_id)
        if parse_variant["document_id"] != document_id or parse_variant["status"] != VariantStatus.COMPLETE.value:
            raise ValueError("Selected parse variant is not complete")

        norm_variant = repo.get_norm_variant(selected_norm_variant_id) if selected_norm_variant_id else None
        if norm_variant and (norm_variant["document_id"] != document_id or norm_variant["status"] != VariantStatus.COMPLETE.value):
            raise ValueError("Selected normalization variant is not complete")

        review = repo.get_review(document_id)
        base_path = norm_variant["normalized_md_path"] if norm_variant else parse_variant["parsed_md_path"]
        if not base_path:
            raise ValueError("Selected variant has no markdown output")
        if not review:
            review = repo.create_or_update_review(
                document_id=document_id,
                selected_parse_variant_id=selected_parse_variant_id,
                selected_norm_variant_id=selected_norm_variant_id,
                base_md_path=base_path,
                status="IN_PROGRESS",
            )
        source_path = review.get("edited_md_path") or review.get("uploaded_md_path") or base_path
        approved_path = files.copy_to_review_approved(document["batch_id"], document_id, source_path)
        review_action = repo.build_review_action({**document, "review": review}, action="approved_indexed", reason=notes)
        review_action["review_approved_md_path"] = approved_path
        repo.update_review(
            document_id,
            selected_parse_variant_id=selected_parse_variant_id,
            selected_norm_variant_id=selected_norm_variant_id,
            base_md_path=base_path,
            review_approved_md_path=approved_path,
            status="APPROVED",
            approved_at=now_iso(),
            notes=notes,
            review_action_json=review_action,
        )
        repo.create_canonical_files(
            document_id=document_id,
            files={
                "source_file_path": document["source_file_path"],
                "raw_md_path": parse_variant["raw_md_path"],
                "parsed_md_path": parse_variant["parsed_md_path"],
                "normalized_md_path": norm_variant["normalized_md_path"] if norm_variant else None,
                "review_approved_md_path": approved_path,
                "normalization_metadata": self._normalization_metadata(norm_variant),
            },
        )
        repo.set_document_status(document_id, DocumentStatus.CHUNK_PENDING.value)
        repo.mark_document_notifications_read(document_id)
        self._cleanup_unselected(document_id, selected_parse_variant_id, selected_norm_variant_id)
        job = self.enqueue_chunk(batch_id=document["batch_id"], document_id=document_id)
        self._publish_document(document_id)
        return job

    def _cleanup_unselected(self, document_id: str, selected_parse_variant_id: str, selected_norm_variant_id: Optional[str]) -> None:
        document = repo.get_document(document_id)
        root = files.generated_root() / "batches" / document["batch_id"] / "documents" / document_id
        for variant in document["parse_variants"]:
            if variant["variant_id"] == selected_parse_variant_id:
                continue
            target = root / "variants" / variant["variant_id"]
            if target.exists():
                shutil.rmtree(target)
                repo.log(stage=PipelineStage.CLEANUP.value, level="INFO", message=f"Deleted unselected parse variant {variant['variant_id']}", batch_id=document["batch_id"], document_id=document_id, parse_variant_id=variant["variant_id"])
        for variant in document["parse_variants"]:
            for norm in variant.get("norm_variants", []):
                if selected_norm_variant_id and norm["norm_variant_id"] == selected_norm_variant_id:
                    continue
                target = root / "normalizations" / norm["norm_variant_id"]
                if target.exists():
                    shutil.rmtree(target)
                    repo.log(stage=PipelineStage.CLEANUP.value, level="INFO", message=f"Deleted unselected normalization {norm['norm_variant_id']}", batch_id=document["batch_id"], document_id=document_id, norm_variant_id=norm["norm_variant_id"])

    def _normalization_metadata(self, norm_variant: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
        if not norm_variant:
            return None
        model = norm_variant["model_config"]
        return {
            "model_display_name": model["display_name"],
            "model_endpoint": model["endpoint"],
            "time_taken_ms": norm_variant.get("time_taken_ms") or 0,
            "completed_at": norm_variant.get("completed_at"),
        }

    def _all_parse_variants_terminal(self, document_id: str) -> bool:
        document = repo.get_document(document_id)
        statuses = [variant["status"] for variant in document["parse_variants"]]
        return bool(statuses) and all(status in {VariantStatus.COMPLETE.value, VariantStatus.FAILED.value} for status in statuses)

    def _all_norm_variants_terminal(self, document_id: str) -> bool:
        document = repo.get_document(document_id)
        statuses = [norm["status"] for variant in document["parse_variants"] for norm in variant.get("norm_variants", [])]
        return bool(statuses) and all(status in {VariantStatus.COMPLETE.value, VariantStatus.FAILED.value} for status in statuses)

    def _publish_document(self, document_id: str) -> None:
        document = repo.get_document(document_id)
        event_hub.publish({"type": "document_update", "document_id": document_id, "batch_id": document["batch_id"], "status": document["status"]})
        event_hub.publish({"type": "batch_progress", "batch_id": document["batch_id"], "status": repo.get_batch(document["batch_id"], include_documents=False)["status"]})

    def _publish_job(self, job_id: str) -> None:
        job = repo.get_job(job_id)
        event_hub.publish({"type": "job_update", "data": job})


admin_worker = AdminWorker()
