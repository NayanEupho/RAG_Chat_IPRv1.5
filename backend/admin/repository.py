from __future__ import annotations

import json
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

from backend.admin.db import get_connection, init_admin_db
from backend.admin.schemas import BatchStatus, DocumentStatus, JobStatus, PipelineStage


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def dump_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def load_json(value: Optional[str], fallback: Any = None) -> Any:
    if value is None or value == "":
        return fallback
    return json.loads(value)


def row_to_dict(row: Any) -> dict[str, Any]:
    result = dict(row)
    for key in list(result.keys()):
        if key.endswith("_json"):
            plain_key = key[:-5]
            result[plain_key] = load_json(result.pop(key), {} if plain_key != "page_numbers" else [])
    return result


def normalize_ingestion_type(value: Any) -> str:
    return "qna" if str(value or "").lower() == "qna" else "general"


def batch_ingestion_label(config: dict[str, Any], documents: Optional[list[dict[str, Any]]] = None) -> str:
    if documents:
        values = {normalize_ingestion_type((doc.get("effective_config") or {}).get("ingestion_type")) for doc in documents}
    else:
        overrides = config.get("per_document_overrides") or {}
        values = {
            normalize_ingestion_type(override.get("ingestion_type"))
            for override in overrides.values()
            if isinstance(override, dict) and override.get("ingestion_type") is not None
        }
        values.add(normalize_ingestion_type(config.get("default_ingestion_type")))
    if len(values) > 1:
        return "mix"
    return f"{next(iter(values), 'general')}_docs"


class AdminRepository:
    def __init__(self) -> None:
        init_admin_db()

    def create_batch(
        self,
        *,
        batch_id: Optional[str] = None,
        name: str,
        description: Optional[str],
        config: dict[str, Any],
        documents: Iterable[dict[str, Any]],
    ) -> dict[str, Any]:
        batch_id = batch_id or new_id("batch")
        created_at = now_iso()
        docs = list(documents)
        conn = get_connection()
        try:
            conn.execute(
                """
                INSERT INTO admin_batches (
                    batch_id, name, description, status, config_json,
                    total_documents, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    batch_id,
                    name,
                    description,
                    BatchStatus.DRAFT.value,
                    dump_json(config),
                    len(docs),
                    created_at,
                ),
            )
            for doc in docs:
                conn.execute(
                    """
                    INSERT INTO admin_documents (
                        document_id, batch_id, original_filename, source_file_path,
                        file_type, file_size_bytes, effective_config_json, status,
                        uploaded_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        doc["document_id"],
                        batch_id,
                        doc["original_filename"],
                        doc["source_file_path"],
                        doc["file_type"],
                        doc["file_size_bytes"],
                        dump_json(doc["effective_config"]),
                        DocumentStatus.UPLOADED.value,
                        created_at,
                    ),
                )
            conn.commit()
        finally:
            conn.close()
        return self.get_batch(batch_id, include_documents=True)

    def list_batches(self, *, status: Optional[str] = None, search: Optional[str] = None, limit: int = 25, page: int = 1, include_documents: bool = False) -> dict[str, Any]:
        where = []
        params: list[Any] = []
        if status:
            statuses = [item.strip() for item in status.split(",") if item.strip()]
            if len(statuses) == 1:
                where.append("status = ?")
                params.append(statuses[0])
            elif statuses:
                where.append(f"status IN ({','.join('?' for _ in statuses)})")
                params.extend(statuses)
        if search:
            where.append("(name LIKE ? OR description LIKE ?)")
            params.extend([f"%{search}%", f"%{search}%"])
        where_sql = f"WHERE {' AND '.join(where)}" if where else ""
        offset = max(page - 1, 0) * limit
        conn = get_connection()
        try:
            total = conn.execute(f"SELECT COUNT(*) FROM admin_batches {where_sql}", params).fetchone()[0]
            rows = conn.execute(
                f"SELECT * FROM admin_batches {where_sql} ORDER BY created_at DESC LIMIT ? OFFSET ?",
                [*params, limit, offset],
            ).fetchall()
            items = [self._batch_from_row(row, include_documents=False) for row in rows]
            if include_documents:
                items = [self.get_batch(item["batch_id"], include_documents=True) for item in items]
            return {"items": items, "total": total, "page": page}
        finally:
            conn.close()

    def get_batch(self, batch_id: str, *, include_documents: bool = True) -> dict[str, Any]:
        conn = get_connection()
        try:
            row = conn.execute("SELECT * FROM admin_batches WHERE batch_id = ?", (batch_id,)).fetchone()
            if not row:
                raise KeyError("Batch not found")
            batch = self._batch_from_row(row, include_documents=False)
            if include_documents:
                docs = conn.execute(
                    "SELECT document_id FROM admin_documents WHERE batch_id = ? ORDER BY uploaded_at ASC",
                    (batch_id,),
                ).fetchall()
                batch["documents"] = [self.get_document(doc["document_id"]) for doc in docs]
                batch["ingestion_label"] = batch_ingestion_label(batch["config"], batch["documents"])
            return batch
        finally:
            conn.close()

    def update_batch_config(self, batch_id: str, config: dict[str, Any]) -> dict[str, Any]:
        conn = get_connection()
        try:
            batch_row = conn.execute("SELECT status FROM admin_batches WHERE batch_id = ?", (batch_id,)).fetchone()
            if not batch_row:
                raise KeyError("Batch not found")
            if batch_row["status"] != BatchStatus.DRAFT.value:
                raise ValueError("Only DRAFT batches can be edited")
            conn.execute(
                "UPDATE admin_batches SET config_json = ? WHERE batch_id = ?",
                (dump_json(config), batch_id),
            )
            docs = conn.execute("SELECT document_id, source_file_path, effective_config_json FROM admin_documents WHERE batch_id = ?", (batch_id,)).fetchall()
            for doc in docs:
                effective = self.effective_config(config, doc["document_id"])
                previous = load_json(doc["effective_config_json"], {})
                source_path = doc["source_file_path"]
                if normalize_ingestion_type(previous.get("ingestion_type")) != effective["ingestion_type"]:
                    source_path = self._move_draft_source(batch_id, doc["document_id"], source_path, effective["ingestion_type"])
                conn.execute(
                    "UPDATE admin_documents SET effective_config_json = ?, source_file_path = ? WHERE document_id = ?",
                    (dump_json(effective), source_path, doc["document_id"]),
                )
            conn.commit()
        finally:
            conn.close()
        return self.get_batch(batch_id, include_documents=True)

    def _move_draft_source(self, batch_id: str, document_id: str, source_file_path: str, ingestion_type: str) -> str:
        from backend.admin.inventory import ADMIN_FOLDER, SOURCE_ROOT

        source = Path(source_file_path)
        if not source.exists():
            return source_file_path
        type_folder = "QnA" if normalize_ingestion_type(ingestion_type) == "qna" else "General"
        target = SOURCE_ROOT / ADMIN_FOLDER / type_folder / "batches" / batch_id / "documents" / document_id / "source" / source.name
        if source.resolve() == target.resolve():
            return str(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(target))
        doc_root = source.parent.parent
        for path in [source.parent, doc_root, doc_root.parent]:
            try:
                path.rmdir()
            except OSError:
                pass
        return str(target)

    def submit_batch(self, batch_id: str) -> dict[str, Any]:
        submitted_at = now_iso()
        conn = get_connection()
        try:
            conn.execute(
                """
                UPDATE admin_batches
                SET status = ?, submitted_at = ?, parsing_started_at = COALESCE(parsing_started_at, ?)
                WHERE batch_id = ? AND status = ?
                """,
                (BatchStatus.SUBMITTED.value, submitted_at, submitted_at, batch_id, BatchStatus.DRAFT.value),
            )
            if conn.total_changes == 0:
                raise ValueError("Only DRAFT batches can be submitted")
            conn.execute(
                "UPDATE admin_documents SET status = ? WHERE batch_id = ? AND status = ?",
                (DocumentStatus.PARSE_PENDING.value, batch_id, DocumentStatus.UPLOADED.value),
            )
            conn.commit()
        finally:
            conn.close()
        self.recalculate_batch_counts(batch_id)
        return self.get_batch(batch_id, include_documents=True)

    def delete_draft_batch(self, batch_id: str) -> dict[str, Any]:
        conn = get_connection()
        try:
            row = conn.execute("SELECT status FROM admin_batches WHERE batch_id = ?", (batch_id,)).fetchone()
            if not row:
                raise KeyError("Batch not found")
            if row["status"] != BatchStatus.DRAFT.value:
                raise ValueError("Only DRAFT batches can be deleted")
            conn.execute("DELETE FROM admin_batches WHERE batch_id = ?", (batch_id,))
            conn.commit()
            return {"deleted": True}
        finally:
            conn.close()

    def cancel_batch(self, batch_id: str) -> dict[str, Any]:
        from backend.admin import files

        active_statuses = {
            BatchStatus.SUBMITTED.value,
            BatchStatus.PARSING.value,
            BatchStatus.NORMALIZING.value,
            BatchStatus.REVIEW_PENDING.value,
            BatchStatus.REVIEWING.value,
            BatchStatus.CHUNKING.value,
        }
        batch = self.get_batch(batch_id, include_documents=True)
        if batch["status"] not in active_statuses:
            raise ValueError("Only active ingestion batches can be cancelled")

        completed_at = now_iso()
        conn = get_connection()
        try:
            conn.execute(
                """
                UPDATE admin_jobs
                SET cancel_requested = 1,
                    status = CASE WHEN status IN (?, ?) THEN ? ELSE status END,
                    completed_at = CASE WHEN status IN (?, ?) THEN ? ELSE completed_at END,
                    detail = CASE WHEN status IN (?, ?) THEN ? ELSE detail END
                WHERE batch_id = ?
                """,
                (
                    JobStatus.QUEUED.value,
                    JobStatus.RUNNING.value,
                    JobStatus.CANCELLED.value,
                    JobStatus.QUEUED.value,
                    JobStatus.RUNNING.value,
                    completed_at,
                    JobStatus.QUEUED.value,
                    JobStatus.RUNNING.value,
                    "Batch cancelled by user",
                    batch_id,
                ),
            )
            conn.execute(
                "UPDATE admin_documents SET status = ?, error_summary = NULL WHERE batch_id = ?",
                (DocumentStatus.CANCELLED.value, batch_id),
            )
            conn.execute(
                """
                UPDATE admin_batches
                SET status = ?, documents_in_progress = 0, completed_at = COALESCE(completed_at, ?)
                WHERE batch_id = ?
                """,
                (BatchStatus.CANCELLED.value, completed_at, batch_id),
            )
            conn.commit()
        finally:
            conn.close()

        cleanup_errors: list[str] = []
        try:
            from backend.rag.store import get_vector_store

            store = get_vector_store()
            if hasattr(store, "delete_document"):
                for document in batch.get("documents", []):
                    try:
                        store.delete_document(document["document_id"])
                    except Exception as exc:
                        cleanup_errors.append(f"{document['document_id']} vector cleanup: {exc}")
        except Exception as exc:
            cleanup_errors.append(f"{batch_id} vector store cleanup: {exc}")
        for document in batch.get("documents", []):
            try:
                files.delete_document_source_tree(document["source_file_path"])
            except Exception as exc:
                cleanup_errors.append(f"{document['document_id']} source cleanup: {exc}")
        try:
            files.delete_tree(files.generated_root() / "batches" / batch_id)
        except Exception as exc:
            cleanup_errors.append(f"{batch_id} generated cleanup: {exc}")

        self.log(
            stage=PipelineStage.CLEANUP.value,
            level="INFO",
            message="Batch cancelled and ingestion artifacts removed",
            detail="\n".join(cleanup_errors) if cleanup_errors else None,
            batch_id=batch_id,
        )
        self.mark_batch_notifications_read(batch_id)
        cancelled = self.get_batch(batch_id, include_documents=True)
        return {"cancelled": True, "batch": cancelled, "cleanup_errors": cleanup_errors}

    def cancel_active_batches(self) -> dict[str, Any]:
        active_statuses = [
            BatchStatus.SUBMITTED.value,
            BatchStatus.PARSING.value,
            BatchStatus.NORMALIZING.value,
            BatchStatus.REVIEWING.value,
            BatchStatus.CHUNKING.value,
        ]
        conn = get_connection()
        try:
            placeholders = ",".join("?" for _ in active_statuses)
            rows = conn.execute(f"SELECT batch_id FROM admin_batches WHERE status IN ({placeholders})", active_statuses).fetchall()
        finally:
            conn.close()
        cancelled = []
        errors = []
        for row in rows:
            try:
                cancelled.append(self.cancel_batch(row["batch_id"]))
            except Exception as exc:
                errors.append({"batch_id": row["batch_id"], "error": str(exc)})
        return {"cancelled": cancelled, "errors": errors, "total": len(cancelled)}

    def effective_config(self, batch_config: dict[str, Any], document_id: str) -> dict[str, Any]:
        effective = {
            "parsers": batch_config.get("default_parsers") or ["docling"],
            "normalization_enabled": bool(batch_config.get("default_normalization_enabled", False)),
            "normalization_models": batch_config.get("default_normalization_models") or [],
            "ingestion_type": normalize_ingestion_type(batch_config.get("default_ingestion_type")),
            "review_required": bool(batch_config.get("review_required", True)),
        }
        override = (batch_config.get("per_document_overrides") or {}).get(document_id) or {}
        effective.update({k: v for k, v in override.items() if v is not None})
        effective["ingestion_type"] = normalize_ingestion_type(effective.get("ingestion_type"))
        return effective

    def get_document(self, document_id: str) -> dict[str, Any]:
        conn = get_connection()
        try:
            row = conn.execute("SELECT * FROM admin_documents WHERE document_id = ?", (document_id,)).fetchone()
            if not row:
                raise KeyError("Document not found")
            doc = row_to_dict(row)
            doc["effective_config"] = doc.pop("effective_config")
            doc["ingestion_type"] = normalize_ingestion_type(doc["effective_config"].get("ingestion_type"))
            doc["parse_variants"] = [
                self._parse_variant_from_row(v)
                for v in conn.execute(
                    "SELECT * FROM admin_parse_variants WHERE document_id = ? ORDER BY started_at, variant_id",
                    (document_id,),
                ).fetchall()
            ]
            doc["review"] = self.get_review(document_id)
            doc["canonical_files"] = self.get_canonical_files(document_id)
            return doc
        finally:
            conn.close()

    def list_documents(self, *, status: Optional[str] = None, search: Optional[str] = None, limit: int = 100, page: int = 1) -> dict[str, Any]:
        where = []
        params: list[Any] = []
        if status:
            where.append("status = ?")
            params.append(status)
        if search:
            where.append("original_filename LIKE ?")
            params.append(f"%{search}%")
        where_sql = f"WHERE {' AND '.join(where)}" if where else ""
        offset = max(page - 1, 0) * limit
        conn = get_connection()
        try:
            total = conn.execute(f"SELECT COUNT(*) FROM admin_documents {where_sql}", params).fetchone()[0]
            rows = conn.execute(
                f"SELECT document_id FROM admin_documents {where_sql} ORDER BY uploaded_at DESC LIMIT ? OFFSET ?",
                [*params, limit, offset],
            ).fetchall()
            return {"items": [self.get_document(row["document_id"]) for row in rows], "total": total, "page": page}
        finally:
            conn.close()

    def list_indexed_document_summaries(self, *, limit: int = 10000) -> list[dict[str, Any]]:
        conn = get_connection()
        try:
            rows = conn.execute(
                """
                SELECT
                    d.document_id,
                    d.batch_id,
                    d.original_filename,
                    d.source_file_path,
                    d.file_size_bytes,
                    d.effective_config_json,
                    d.status,
                    d.chunk_count,
                    d.indexed_at,
                    c.raw_md_path,
                    c.parsed_md_path,
                    c.normalized_md_path,
                    c.review_approved_md_path
                FROM admin_documents d
                LEFT JOIN admin_canonical_files c ON c.document_id = d.document_id
                WHERE d.status = ?
                ORDER BY d.indexed_at DESC, d.uploaded_at DESC
                LIMIT ?
                """,
                (DocumentStatus.INDEXED.value, limit),
            ).fetchall()
            documents = []
            for row in rows:
                document = row_to_dict(row)
                document["effective_config"] = document.pop("effective_config")
                document["ingestion_type"] = normalize_ingestion_type(document["effective_config"].get("ingestion_type"))
                document["canonical_files"] = {
                    "raw_md_path": document.pop("raw_md_path", None),
                    "parsed_md_path": document.pop("parsed_md_path", None),
                    "normalized_md_path": document.pop("normalized_md_path", None),
                    "review_approved_md_path": document.pop("review_approved_md_path", None),
                }
                documents.append(document)
            return documents
        finally:
            conn.close()

    def delete_indexed_document_record(self, document_id: str) -> dict[str, Any]:
        document = self.get_document(document_id)
        if document["status"] != DocumentStatus.INDEXED.value:
            raise ValueError("Only indexed documents can be deleted from the control center")
        conn = get_connection()
        try:
            conn.execute("DELETE FROM admin_documents WHERE document_id = ?", (document_id,))
            conn.commit()
        finally:
            conn.close()
        self.recalculate_batch_counts(document["batch_id"])
        return {"deleted": True, "document": document}

    def create_parse_variant(self, *, document_id: str, parser_type: str) -> dict[str, Any]:
        variant_id = new_id("parse")
        conn = get_connection()
        try:
            conn.execute(
                """
                INSERT INTO admin_parse_variants (variant_id, document_id, parser_type, status)
                VALUES (?, ?, ?, ?)
                """,
                (variant_id, document_id, parser_type, "PENDING"),
            )
            conn.commit()
        finally:
            conn.close()
        return self.get_parse_variant(variant_id)

    def get_parse_variant(self, variant_id: str) -> dict[str, Any]:
        conn = get_connection()
        try:
            row = conn.execute("SELECT * FROM admin_parse_variants WHERE variant_id = ?", (variant_id,)).fetchone()
            if not row:
                raise KeyError("Parse variant not found")
            return self._parse_variant_from_row(row)
        finally:
            conn.close()

    def update_parse_variant(self, variant_id: str, **fields: Any) -> dict[str, Any]:
        self._update("admin_parse_variants", "variant_id", variant_id, fields)
        return self.get_parse_variant(variant_id)

    def create_norm_variant(self, *, parse_variant_id: str, document_id: str, model: dict[str, Any]) -> dict[str, Any]:
        norm_variant_id = new_id("norm")
        conn = get_connection()
        try:
            conn.execute(
                """
                INSERT INTO admin_norm_variants (
                    norm_variant_id, parse_variant_id, document_id, model_id,
                    model_endpoint, model_display_name, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    norm_variant_id,
                    parse_variant_id,
                    document_id,
                    model["model_id"],
                    model["endpoint"],
                    model["display_name"],
                    "PENDING",
                ),
            )
            conn.commit()
        finally:
            conn.close()
        return self.get_norm_variant(norm_variant_id)

    def get_norm_variant(self, norm_variant_id: str) -> dict[str, Any]:
        conn = get_connection()
        try:
            row = conn.execute("SELECT * FROM admin_norm_variants WHERE norm_variant_id = ?", (norm_variant_id,)).fetchone()
            if not row:
                raise KeyError("Normalization variant not found")
            return self._norm_variant_from_row(row)
        finally:
            conn.close()

    def update_norm_variant(self, norm_variant_id: str, **fields: Any) -> dict[str, Any]:
        self._update("admin_norm_variants", "norm_variant_id", norm_variant_id, fields)
        return self.get_norm_variant(norm_variant_id)

    def set_document_status(self, document_id: str, status: str, *, error_summary: Optional[str] = None, chunk_count: Optional[int] = None, indexed_at: Optional[str] = None) -> None:
        fields: dict[str, Any] = {"status": status}
        if error_summary is not None:
            fields["error_summary"] = error_summary
        elif not status.endswith("_FAILED"):
            fields["error_summary"] = None
        if chunk_count is not None:
            fields["chunk_count"] = chunk_count
        if indexed_at is not None:
            fields["indexed_at"] = indexed_at
        self._update("admin_documents", "document_id", document_id, fields)
        doc = self.get_document(document_id)
        self.recalculate_batch_counts(doc["batch_id"])

    def create_or_update_review(
        self,
        *,
        document_id: str,
        selected_parse_variant_id: str,
        selected_norm_variant_id: Optional[str],
        base_md_path: str,
        status: str,
    ) -> dict[str, Any]:
        review_id = new_id("review")
        opened_at = now_iso()
        conn = get_connection()
        try:
            conn.execute(
                """
                INSERT INTO admin_reviews (
                    review_id, document_id, selected_parse_variant_id,
                    selected_norm_variant_id, base_md_path, status, opened_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(document_id) DO UPDATE SET
                    selected_parse_variant_id = excluded.selected_parse_variant_id,
                    selected_norm_variant_id = excluded.selected_norm_variant_id,
                    base_md_path = excluded.base_md_path,
                    status = excluded.status,
                    opened_at = COALESCE(admin_reviews.opened_at, excluded.opened_at)
                """,
                (review_id, document_id, selected_parse_variant_id, selected_norm_variant_id, base_md_path, status, opened_at),
            )
            conn.execute("UPDATE admin_parse_variants SET is_selected_for_review = 0 WHERE document_id = ?", (document_id,))
            conn.execute("UPDATE admin_norm_variants SET is_selected_for_review = 0 WHERE document_id = ?", (document_id,))
            conn.execute("UPDATE admin_parse_variants SET is_selected_for_review = 1 WHERE variant_id = ?", (selected_parse_variant_id,))
            if selected_norm_variant_id:
                conn.execute("UPDATE admin_norm_variants SET is_selected_for_review = 1 WHERE norm_variant_id = ?", (selected_norm_variant_id,))
            conn.commit()
        finally:
            conn.close()
        return self.get_review(document_id) or {}

    def update_review(self, document_id: str, **fields: Any) -> dict[str, Any]:
        self._update("admin_reviews", "document_id", document_id, fields)
        return self.get_review(document_id) or {}

    def build_review_action(self, document: dict[str, Any], *, action: str, reason: Optional[str] = None, cleanup_errors: Optional[list[str]] = None) -> dict[str, Any]:
        review = document.get("review") or {}
        source_path = document.get("source_file_path")
        generated_document_root = None
        if document.get("batch_id") and document.get("document_id"):
            generated_document_root = str(Path("generated_doc_md") / "Admin_Dashboard" / "batches" / document["batch_id"] / "documents" / document["document_id"])
        target_source = review.get("edited_md_path") or review.get("uploaded_md_path") or review.get("base_md_path")
        return {
            "action": action,
            "reason": reason,
            "timestamp": now_iso(),
            "review_required": bool((document.get("effective_config") or {}).get("review_required", True)),
            "llm_normalized": bool((document.get("effective_config") or {}).get("normalization_enabled")),
            "selected_parse_variant_id": review.get("selected_parse_variant_id"),
            "selected_norm_variant_id": review.get("selected_norm_variant_id"),
            "base_md_path": review.get("base_md_path"),
            "edited": bool(review.get("edited_md_path")),
            "edited_md_path": review.get("edited_md_path"),
            "replaced": bool(review.get("uploaded_md_path")),
            "uploaded_md_path": review.get("uploaded_md_path"),
            "final_review_target_path": target_source,
            "source_file_path": source_path,
            "deleted_artifacts": {
                "source_document_tree": str(Path(source_path).parent.parent) if source_path else None,
                "generated_document_tree": generated_document_root,
            } if action == "rejected_deleted" else {},
            "cleanup_completed": action != "rejected_deleted" or not cleanup_errors,
            "cleanup_errors": cleanup_errors or [],
        }

    def reject_review(self, document_id: str, reason: Optional[str] = None, cleanup_errors: Optional[list[str]] = None) -> dict[str, Any]:
        document = self.get_document(document_id)
        review = document.get("review")
        if not review:
            parse_variant = next((variant for variant in document.get("parse_variants", []) if variant.get("is_selected_for_review")), None)
            parse_variant = parse_variant or next((variant for variant in document.get("parse_variants", []) if variant.get("status") == "COMPLETE"), None)
            norm_variant = None
            if parse_variant:
                norm_variant = next((variant for variant in parse_variant.get("norm_variants", []) if variant.get("is_selected_for_review")), None)
                norm_variant = norm_variant or next((variant for variant in parse_variant.get("norm_variants", []) if variant.get("status") == "COMPLETE"), None)
                base_path = norm_variant.get("normalized_md_path") if norm_variant else parse_variant.get("parsed_md_path")
                if base_path:
                    review = self.create_or_update_review(
                        document_id=document_id,
                        selected_parse_variant_id=parse_variant["variant_id"],
                        selected_norm_variant_id=norm_variant["norm_variant_id"] if norm_variant else None,
                        base_md_path=base_path,
                        status="IN_PROGRESS",
                    )
                    document = {**document, "review": review}
        action = self.build_review_action(document, action="rejected_deleted", reason=reason, cleanup_errors=cleanup_errors)
        if review:
            self.update_review(document_id, status="REJECTED", notes=reason, approved_at=now_iso(), review_action_json=action)
        self.set_document_status(document_id, DocumentStatus.REVIEW_REJECTED.value)
        return self.log(
            stage=PipelineStage.REVIEW.value,
            level="INFO",
            message="Document rejected in review",
            detail=dump_json(action),
            batch_id=document["batch_id"],
            document_id=document_id,
        )

    def get_review(self, document_id: str) -> Optional[dict[str, Any]]:
        conn = get_connection()
        try:
            row = conn.execute("SELECT * FROM admin_reviews WHERE document_id = ?", (document_id,)).fetchone()
            return row_to_dict(row) if row else None
        finally:
            conn.close()

    def create_canonical_files(self, *, document_id: str, files: dict[str, Any]) -> dict[str, Any]:
        conn = get_connection()
        try:
            conn.execute(
                """
                INSERT INTO admin_canonical_files (
                    document_id, source_file_path, raw_md_path, parsed_md_path,
                    normalized_md_path, review_approved_md_path, normalization_metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(document_id) DO UPDATE SET
                    source_file_path = excluded.source_file_path,
                    raw_md_path = excluded.raw_md_path,
                    parsed_md_path = excluded.parsed_md_path,
                    normalized_md_path = excluded.normalized_md_path,
                    review_approved_md_path = excluded.review_approved_md_path,
                    normalization_metadata_json = excluded.normalization_metadata_json
                """,
                (
                    document_id,
                    files["source_file_path"],
                    files["raw_md_path"],
                    files["parsed_md_path"],
                    files.get("normalized_md_path"),
                    files["review_approved_md_path"],
                    dump_json(files.get("normalization_metadata")),
                ),
            )
            conn.commit()
        finally:
            conn.close()
        return self.get_canonical_files(document_id) or {}

    def get_canonical_files(self, document_id: str) -> Optional[dict[str, Any]]:
        conn = get_connection()
        try:
            row = conn.execute("SELECT * FROM admin_canonical_files WHERE document_id = ?", (document_id,)).fetchone()
            if not row:
                return None
            data = row_to_dict(row)
            data["normalization_metadata"] = data.pop("normalization_metadata", None)
            return data
        finally:
            conn.close()

    def create_job(self, *, job_type: str, stage: str, batch_id: Optional[str] = None, document_id: Optional[str] = None, parse_variant_id: Optional[str] = None, norm_variant_id: Optional[str] = None, payload: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        job_id = new_id("job")
        created_at = now_iso()
        conn = get_connection()
        try:
            conn.execute(
                """
                INSERT INTO admin_jobs (
                    job_id, batch_id, document_id, parse_variant_id, norm_variant_id,
                    job_type, stage, status, created_at, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    batch_id,
                    document_id,
                    parse_variant_id,
                    norm_variant_id,
                    job_type,
                    stage,
                    JobStatus.QUEUED.value,
                    created_at,
                    dump_json(payload or {}),
                ),
            )
            conn.commit()
        finally:
            conn.close()
        return self.get_job(job_id)

    def get_job(self, job_id: str) -> dict[str, Any]:
        conn = get_connection()
        try:
            row = conn.execute("SELECT * FROM admin_jobs WHERE job_id = ?", (job_id,)).fetchone()
            if not row:
                raise KeyError("Job not found")
            return row_to_dict(row)
        finally:
            conn.close()

    def update_job(self, job_id: str, **fields: Any) -> dict[str, Any]:
        current = self.get_job(job_id)
        if fields.get("status") == JobStatus.RUNNING.value and not fields.get("started_at"):
            fields["started_at"] = now_iso()
        if fields.get("status") in {JobStatus.COMPLETE.value, JobStatus.FAILED.value, JobStatus.CANCELLED.value}:
            completed_at = fields.get("completed_at") or now_iso()
            fields["completed_at"] = completed_at
            started_at = current.get("started_at")
            if started_at:
                fields["duration_ms"] = int((datetime.fromisoformat(completed_at).timestamp() - datetime.fromisoformat(started_at).timestamp()) * 1000)
        self._update("admin_jobs", "job_id", job_id, fields)
        return self.get_job(job_id)

    def list_jobs(self, *, status: Optional[str] = None, limit: int = 100) -> dict[str, Any]:
        where = "WHERE status = ?" if status else ""
        params = [status] if status else []
        conn = get_connection()
        try:
            rows = conn.execute(
                f"SELECT * FROM admin_jobs {where} ORDER BY created_at DESC LIMIT ?",
                [*params, limit],
            ).fetchall()
            return {"items": [row_to_dict(row) for row in rows], "total": len(rows)}
        finally:
            conn.close()

    def list_recoverable_jobs(self, *, limit: int = 1000) -> list[dict[str, Any]]:
        conn = get_connection()
        try:
            rows = conn.execute(
                """
                SELECT * FROM admin_jobs
                WHERE status IN (?, ?)
                  AND cancel_requested = 0
                ORDER BY created_at ASC
                LIMIT ?
                """,
                (JobStatus.QUEUED.value, JobStatus.RUNNING.value, limit),
            ).fetchall()
            return [row_to_dict(row) for row in rows]
        finally:
            conn.close()

    def reset_job_for_recovery(self, job_id: str) -> dict[str, Any]:
        job = self.get_job(job_id)
        conn = get_connection()
        try:
            conn.execute(
                """
                UPDATE admin_jobs
                SET status = ?,
                    progress = 0,
                    detail = ?,
                    error_message = NULL,
                    error_detail = NULL,
                    started_at = NULL,
                    completed_at = NULL,
                    duration_ms = NULL,
                    attempt = ?
                WHERE job_id = ?
                """,
                (
                    JobStatus.QUEUED.value,
                    "Recovered after backend restart; queued for retry.",
                    int(job.get("attempt") or 1) + 1,
                    job_id,
                ),
            )
            conn.commit()
        finally:
            conn.close()
        return self.get_job(job_id)

    def log(
        self,
        *,
        stage: str,
        level: str,
        message: str,
        detail: Optional[str] = None,
        batch_id: Optional[str] = None,
        document_id: Optional[str] = None,
        parse_variant_id: Optional[str] = None,
        norm_variant_id: Optional[str] = None,
        job_id: Optional[str] = None,
    ) -> dict[str, Any]:
        log_id = new_id("log")
        timestamp = now_iso()
        payload = {
            "log_id": log_id,
            "batch_id": batch_id,
            "document_id": document_id,
            "parse_variant_id": parse_variant_id,
            "norm_variant_id": norm_variant_id,
            "job_id": job_id,
            "stage": stage,
            "level": level,
            "message": message,
            "detail": detail,
            "timestamp": timestamp,
        }
        conn = get_connection()
        try:
            conn.execute(
                """
                INSERT INTO admin_job_logs (
                    log_id, batch_id, document_id, parse_variant_id, norm_variant_id,
                    job_id, stage, level, message, detail, timestamp
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (log_id, batch_id, document_id, parse_variant_id, norm_variant_id, job_id, stage, level, message, detail, timestamp),
            )
            conn.commit()
        finally:
            conn.close()
        try:
            from backend.admin.events import event_hub

            event_hub.publish({"type": "log", "data": payload, "batch_id": batch_id, "document_id": document_id, "message": message})
        except Exception:
            pass
        return payload

    def list_logs(self, *, level: Optional[str] = None, stage: Optional[str] = None, search: Optional[str] = None, limit: int = 50, page: int = 1) -> dict[str, Any]:
        where = []
        params: list[Any] = []
        if level:
            where.append("level = ?")
            params.append(level)
        if stage:
            where.append("stage = ?")
            params.append(stage)
        if search:
            where.append("(message LIKE ? OR detail LIKE ?)")
            params.extend([f"%{search}%", f"%{search}%"])
        where_sql = f"WHERE {' AND '.join(where)}" if where else ""
        offset = max(page - 1, 0) * limit
        conn = get_connection()
        try:
            total = conn.execute(f"SELECT COUNT(*) FROM admin_job_logs {where_sql}", params).fetchone()[0]
            rows = conn.execute(
                f"SELECT * FROM admin_job_logs {where_sql} ORDER BY timestamp DESC LIMIT ? OFFSET ?",
                [*params, limit, offset],
            ).fetchall()
            return {"items": [row_to_dict(row) for row in rows], "total": total, "page": page}
        finally:
            conn.close()

    def notify(self, *, type_: str, title: str, message: str, detail: Optional[str] = None, batch_id: Optional[str] = None, document_id: Optional[str] = None, job_id: Optional[str] = None) -> dict[str, Any]:
        notification_id = new_id("note")
        created_at = now_iso()
        conn = get_connection()
        try:
            conn.execute(
                """
                INSERT INTO admin_notifications (
                    notification_id, type, batch_id, document_id, job_id,
                    title, message, detail, read, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
                """,
                (notification_id, type_, batch_id, document_id, job_id, title, message, detail, created_at),
            )
            conn.commit()
        finally:
            conn.close()
        return {
            "notification_id": notification_id,
            "type": type_,
            "batch_id": batch_id,
            "document_id": document_id,
            "job_id": job_id,
            "title": title,
            "message": message,
            "detail": detail,
            "read": False,
            "created_at": created_at,
        }

    def notification_exists(self, *, title: str, batch_id: Optional[str] = None, type_: Optional[str] = None) -> bool:
        where = ["title = ?"]
        params: list[Any] = [title]
        if batch_id is None:
            where.append("batch_id IS NULL")
        else:
            where.append("batch_id = ?")
            params.append(batch_id)
        if type_ is not None:
            where.append("type = ?")
            params.append(type_)
        conn = get_connection()
        try:
            row = conn.execute(f"SELECT 1 FROM admin_notifications WHERE {' AND '.join(where)} LIMIT 1", params).fetchone()
            return row is not None
        finally:
            conn.close()

    def list_notifications(self, *, unread_only: bool = False, limit: int = 100, page: int = 1) -> dict[str, Any]:
        where = "WHERE read = 0" if unread_only else ""
        offset = max(page - 1, 0) * limit
        conn = get_connection()
        try:
            total = conn.execute(f"SELECT COUNT(*) FROM admin_notifications {where}").fetchone()[0]
            unread_count = conn.execute("SELECT COUNT(*) FROM admin_notifications WHERE read = 0").fetchone()[0]
            rows = conn.execute(
                f"SELECT * FROM admin_notifications {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
            items = [dict(row) for row in rows]
            for item in items:
                item["read"] = bool(item["read"])
            return {"items": items, "total": total, "unread_count": unread_count, "page": page}
        finally:
            conn.close()

    def mark_notification_read(self, notification_id: str) -> dict[str, Any]:
        self._update("admin_notifications", "notification_id", notification_id, {"read": 1})
        conn = get_connection()
        try:
            row = conn.execute("SELECT * FROM admin_notifications WHERE notification_id = ?", (notification_id,)).fetchone()
            if not row:
                raise KeyError("Notification not found")
            item = dict(row)
            item["read"] = bool(item["read"])
            return item
        finally:
            conn.close()

    def mark_all_notifications_read(self) -> dict[str, Any]:
        conn = get_connection()
        try:
            cur = conn.execute("UPDATE admin_notifications SET read = 1 WHERE read = 0")
            conn.commit()
            return {"updated": cur.rowcount}
        finally:
            conn.close()

    def mark_document_notifications_read(self, document_id: str) -> dict[str, Any]:
        conn = get_connection()
        try:
            cur = conn.execute(
                "UPDATE admin_notifications SET read = 1 WHERE document_id = ? AND read = 0",
                (document_id,),
            )
            conn.commit()
            return {"updated": cur.rowcount}
        finally:
            conn.close()

    def mark_batch_notifications_read(self, batch_id: str) -> dict[str, Any]:
        conn = get_connection()
        try:
            cur = conn.execute(
                "UPDATE admin_notifications SET read = 1 WHERE batch_id = ? AND read = 0",
                (batch_id,),
            )
            conn.commit()
            return {"updated": cur.rowcount}
        finally:
            conn.close()

    def delete_notification(self, notification_id: str) -> dict[str, Any]:
        conn = get_connection()
        try:
            conn.execute("DELETE FROM admin_notifications WHERE notification_id = ?", (notification_id,))
            conn.commit()
            return {"deleted": True}
        finally:
            conn.close()

    def replace_document_chunks(self, *, document_id: str, batch_id: str, chunks: list[dict[str, Any]]) -> None:
        conn = get_connection()
        try:
            conn.execute("DELETE FROM admin_chunks WHERE document_id = ?", (document_id,))
            for chunk in chunks:
                conn.execute(
                    """
                    INSERT INTO admin_chunks (
                        chunk_id, document_id, batch_id, content, chunk_index,
                        section_path, page_numbers_json, token_count, char_count,
                        embedding_model, indexed_at, chroma_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        chunk["chunk_id"],
                        document_id,
                        batch_id,
                        chunk["content"],
                        chunk["chunk_index"],
                        chunk.get("section_path"),
                        dump_json(chunk.get("page_numbers") or []),
                        chunk["token_count"],
                        chunk["char_count"],
                        chunk["embedding_model"],
                        chunk["indexed_at"],
                        chunk["chroma_id"],
                    ),
                )
            conn.commit()
        finally:
            conn.close()

    def list_chunks(self, *, document_id: Optional[str] = None, batch_id: Optional[str] = None, search: Optional[str] = None, limit: int = 25, page: int = 1) -> dict[str, Any]:
        where = []
        params: list[Any] = []
        if document_id:
            where.append("document_id = ?")
            params.append(document_id)
        if batch_id:
            where.append("batch_id = ?")
            params.append(batch_id)
        if search:
            where.append("content LIKE ?")
            params.append(f"%{search}%")
        where_sql = f"WHERE {' AND '.join(where)}" if where else ""
        offset = max(page - 1, 0) * limit
        conn = get_connection()
        try:
            total = conn.execute(f"SELECT COUNT(*) FROM admin_chunks {where_sql}", params).fetchone()[0]
            rows = conn.execute(
                f"SELECT * FROM admin_chunks {where_sql} ORDER BY indexed_at DESC, chunk_index ASC LIMIT ? OFFSET ?",
                [*params, limit, offset],
            ).fetchall()
            return {"items": [row_to_dict(row) for row in rows], "total": total, "page": page}
        finally:
            conn.close()

    def get_chunk(self, chunk_id: str) -> dict[str, Any]:
        conn = get_connection()
        try:
            row = conn.execute("SELECT * FROM admin_chunks WHERE chunk_id = ?", (chunk_id,)).fetchone()
            if not row:
                raise KeyError("Chunk not found")
            return row_to_dict(row)
        finally:
            conn.close()

    def chunk_stats(self) -> dict[str, Any]:
        conn = get_connection()
        try:
            totals = conn.execute(
                """
                SELECT
                    COUNT(*) AS total_chunks,
                    COUNT(DISTINCT document_id) AS documents_with_chunks,
                    COALESCE(AVG(token_count), 0) AS avg_tokens_per_chunk,
                    COALESCE(AVG(char_count), 0) AS avg_chars_per_chunk,
                    COALESCE(SUM(token_count), 0) AS total_tokens,
                    COALESCE(SUM(char_count), 0) AS total_chars
                FROM admin_chunks
                """
            ).fetchone()
            model_rows = conn.execute(
                """
                SELECT embedding_model, COUNT(*) AS chunks
                FROM admin_chunks
                GROUP BY embedding_model
                ORDER BY chunks DESC, embedding_model ASC
                """
            ).fetchall()
            return {
                **row_to_dict(totals),
                "embedding_models": [row_to_dict(row) for row in model_rows],
            }
        finally:
            conn.close()

    def upsert_llm_endpoint(self, *, endpoint_id: Optional[str], model_id: str, endpoint: str, display_name: str, enabled: bool) -> dict[str, Any]:
        endpoint_id = endpoint_id or new_id("llm")
        timestamp = now_iso()
        conn = get_connection()
        try:
            conn.execute(
                """
                INSERT INTO admin_llm_endpoints (
                    endpoint_id, model_id, endpoint, display_name, enabled, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(endpoint_id) DO UPDATE SET
                    model_id = excluded.model_id,
                    endpoint = excluded.endpoint,
                    display_name = excluded.display_name,
                    enabled = excluded.enabled,
                    updated_at = excluded.updated_at
                """,
                (endpoint_id, model_id, endpoint, display_name, 1 if enabled else 0, timestamp, timestamp),
            )
            conn.commit()
            row = conn.execute("SELECT * FROM admin_llm_endpoints WHERE endpoint_id = ?", (endpoint_id,)).fetchone()
            item = dict(row)
            item["enabled"] = bool(item["enabled"])
            return item
        finally:
            conn.close()

    def list_llm_endpoints(self) -> dict[str, Any]:
        conn = get_connection()
        try:
            rows = conn.execute("SELECT * FROM admin_llm_endpoints ORDER BY created_at DESC").fetchall()
            items = [dict(row) for row in rows]
            for item in items:
                item["enabled"] = bool(item["enabled"])
            return {"items": items, "total": len(items)}
        finally:
            conn.close()

    def get_stats(self) -> dict[str, Any]:
        conn = get_connection()
        try:
            counts = {
                "batches": conn.execute("SELECT COUNT(*) FROM admin_batches").fetchone()[0],
                "documents": conn.execute("SELECT COUNT(*) FROM admin_documents").fetchone()[0],
                "indexed_documents": conn.execute("SELECT COUNT(*) FROM admin_documents WHERE status = ?", (DocumentStatus.INDEXED.value,)).fetchone()[0],
                "chunks": conn.execute("SELECT COUNT(*) FROM admin_chunks").fetchone()[0],
                "failed_jobs": conn.execute("SELECT COUNT(*) FROM admin_jobs WHERE status = ?", (JobStatus.FAILED.value,)).fetchone()[0],
                "unread_notifications": conn.execute("SELECT COUNT(*) FROM admin_notifications WHERE read = 0").fetchone()[0],
            }
            token_row = conn.execute("SELECT COALESCE(SUM(token_count), 0), COALESCE(SUM(char_count), 0) FROM admin_chunks").fetchone()
            counts["total_tokens"] = token_row[0]
            counts["total_chars"] = token_row[1]
            return counts
        finally:
            conn.close()

    def recalculate_batch_counts(self, batch_id: str) -> None:
        conn = get_connection()
        try:
            docs = conn.execute("SELECT status FROM admin_documents WHERE batch_id = ?", (batch_id,)).fetchall()
            total = len(docs)
            statuses = [row["status"] for row in docs]
            indexed = statuses.count(DocumentStatus.INDEXED.value)
            failed = sum(1 for value in statuses if value.endswith("_FAILED"))
            pending_review = statuses.count(DocumentStatus.REVIEW_PENDING.value) + statuses.count(DocumentStatus.REVIEW_IN_PROGRESS.value)
            in_progress = sum(
                1
                for value in statuses
                if (value.endswith("_RUNNING") or value.endswith("_PENDING")) and value != DocumentStatus.REVIEW_PENDING.value
            )
            batch_status = self._derive_batch_status(statuses)
            completed_at = now_iso() if total > 0 and batch_status in {
                BatchStatus.COMPLETE.value,
                BatchStatus.FAILED.value,
                BatchStatus.PARTIALLY_COMPLETE.value,
                BatchStatus.CANCELLED.value,
            } else None
            conn.execute(
                """
                UPDATE admin_batches
                SET status = ?, total_documents = ?, documents_indexed = ?,
                    documents_failed = ?, documents_in_progress = ?,
                    documents_pending_review = ?,
                    completed_at = CASE
                        WHEN ? IS NULL THEN NULL
                        WHEN status != ? THEN ?
                        ELSE COALESCE(completed_at, ?)
                    END
                WHERE batch_id = ?
                """,
                (
                    batch_status,
                    total,
                    indexed,
                    failed,
                    in_progress,
                    pending_review,
                    completed_at,
                    batch_status,
                    completed_at,
                    completed_at,
                    batch_id,
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def _derive_batch_status(self, statuses: list[str]) -> str:
        if not statuses:
            return BatchStatus.DRAFT.value
        terminal = {
            DocumentStatus.INDEXED.value,
            DocumentStatus.REVIEW_REJECTED.value,
            DocumentStatus.CANCELLED.value,
            DocumentStatus.PARSE_FAILED.value,
            DocumentStatus.NORMALIZE_FAILED.value,
            DocumentStatus.CHUNK_FAILED.value,
        }
        if all(value == DocumentStatus.INDEXED.value for value in statuses):
            return BatchStatus.COMPLETE.value
        if all(value == DocumentStatus.REVIEW_REJECTED.value for value in statuses):
            return BatchStatus.FAILED.value
        if all(value == DocumentStatus.CANCELLED.value for value in statuses):
            return BatchStatus.CANCELLED.value
        if any(value == DocumentStatus.CANCELLED.value for value in statuses) and all(value in terminal for value in statuses):
            return BatchStatus.CANCELLED.value
        if all(value.endswith("_FAILED") for value in statuses):
            return BatchStatus.FAILED.value
        if all(value in terminal for value in statuses) and any(value == DocumentStatus.INDEXED.value for value in statuses):
            return BatchStatus.PARTIALLY_COMPLETE.value
        if any(value == DocumentStatus.INDEXED.value for value in statuses) and any(value.endswith("_FAILED") for value in statuses):
            return BatchStatus.PARTIALLY_COMPLETE.value
        if any(value.startswith("CHUNK") for value in statuses):
            return BatchStatus.CHUNKING.value
        if any(value.startswith("REVIEW") for value in statuses):
            return BatchStatus.REVIEW_PENDING.value
        if any(value.startswith("NORMALIZE") for value in statuses):
            return BatchStatus.NORMALIZING.value
        if any(value.startswith("PARSE") for value in statuses):
            return BatchStatus.PARSING.value
        return BatchStatus.SUBMITTED.value

    def _batch_from_row(self, row: Any, *, include_documents: bool) -> dict[str, Any]:
        batch = row_to_dict(row)
        batch["config"] = batch.pop("config")
        batch["ingestion_label"] = batch_ingestion_label(batch["config"])
        if include_documents:
            batch["documents"] = []
        return batch

    def _parse_variant_from_row(self, row: Any) -> dict[str, Any]:
        variant = row_to_dict(row)
        variant["is_selected_for_review"] = bool(variant["is_selected_for_review"])
        conn = get_connection()
        try:
            norm_rows = conn.execute(
                "SELECT * FROM admin_norm_variants WHERE parse_variant_id = ? ORDER BY started_at, norm_variant_id",
                (variant["variant_id"],),
            ).fetchall()
            variant["norm_variants"] = [self._norm_variant_from_row(norm_row) for norm_row in norm_rows]
            return variant
        finally:
            conn.close()

    def _norm_variant_from_row(self, row: Any) -> dict[str, Any]:
        norm = row_to_dict(row)
        norm["model_config"] = {
            "model_id": norm.pop("model_id"),
            "endpoint": norm.pop("model_endpoint"),
            "display_name": norm.pop("model_display_name"),
        }
        norm["is_selected_for_review"] = bool(norm["is_selected_for_review"])
        return norm

    def _update(self, table: str, key_name: str, key_value: str, fields: dict[str, Any]) -> None:
        if not fields:
            return
        clean: dict[str, Any] = {}
        for key, value in fields.items():
            if key.endswith("_json"):
                clean[key] = dump_json(value)
            else:
                clean[key] = value
        assignments = ", ".join(f"{key} = ?" for key in clean.keys())
        conn = get_connection()
        try:
            conn.execute(
                f"UPDATE {table} SET {assignments} WHERE {key_name} = ?",
                [*clean.values(), key_value],
            )
            conn.commit()
        finally:
            conn.close()


repo = AdminRepository()
