from __future__ import annotations

import os
import sqlite3
from pathlib import Path


def admin_data_dir() -> Path:
    return Path(os.getenv("ADMIN_DASHBOARD_DATA_DIR", "admin_data")).resolve()


def admin_db_path() -> Path:
    return admin_data_dir() / "admin.db"


def get_connection() -> sqlite3.Connection:
    admin_data_dir().mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(admin_db_path(), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_admin_db() -> None:
    conn = get_connection()
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS admin_batches (
                batch_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT,
                status TEXT NOT NULL,
                config_json TEXT NOT NULL,
                total_documents INTEGER NOT NULL DEFAULT 0,
                documents_indexed INTEGER NOT NULL DEFAULT 0,
                documents_failed INTEGER NOT NULL DEFAULT 0,
                documents_in_progress INTEGER NOT NULL DEFAULT 0,
                documents_pending_review INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                submitted_at TEXT,
                parsing_started_at TEXT,
                parsing_completed_at TEXT,
                normalization_started_at TEXT,
                normalization_completed_at TEXT,
                review_started_at TEXT,
                review_completed_at TEXT,
                chunking_started_at TEXT,
                completed_at TEXT,
                total_duration_ms INTEGER,
                last_error TEXT
            );

            CREATE TABLE IF NOT EXISTS admin_documents (
                document_id TEXT PRIMARY KEY,
                batch_id TEXT NOT NULL REFERENCES admin_batches(batch_id) ON DELETE CASCADE,
                original_filename TEXT NOT NULL,
                source_file_path TEXT NOT NULL,
                file_type TEXT NOT NULL,
                file_size_bytes INTEGER NOT NULL,
                effective_config_json TEXT NOT NULL,
                status TEXT NOT NULL,
                chunk_count INTEGER,
                indexed_at TEXT,
                uploaded_at TEXT NOT NULL,
                error_summary TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_admin_documents_batch
                ON admin_documents(batch_id);
            CREATE INDEX IF NOT EXISTS idx_admin_documents_status
                ON admin_documents(status);

            CREATE TABLE IF NOT EXISTS admin_parse_variants (
                variant_id TEXT PRIMARY KEY,
                document_id TEXT NOT NULL REFERENCES admin_documents(document_id) ON DELETE CASCADE,
                parser_type TEXT NOT NULL,
                status TEXT NOT NULL,
                raw_md_path TEXT,
                parsed_md_path TEXT,
                started_at TEXT,
                completed_at TEXT,
                duration_ms INTEGER,
                error_message TEXT,
                error_detail TEXT,
                is_selected_for_review INTEGER NOT NULL DEFAULT 0
            );

            CREATE INDEX IF NOT EXISTS idx_admin_parse_variants_document
                ON admin_parse_variants(document_id);

            CREATE TABLE IF NOT EXISTS admin_norm_variants (
                norm_variant_id TEXT PRIMARY KEY,
                parse_variant_id TEXT NOT NULL REFERENCES admin_parse_variants(variant_id) ON DELETE CASCADE,
                document_id TEXT NOT NULL REFERENCES admin_documents(document_id) ON DELETE CASCADE,
                model_id TEXT NOT NULL,
                model_endpoint TEXT NOT NULL,
                model_display_name TEXT NOT NULL,
                status TEXT NOT NULL,
                failure_mode TEXT,
                normalized_md_path TEXT,
                time_taken_ms INTEGER,
                started_at TEXT,
                completed_at TEXT,
                error_message TEXT,
                error_detail TEXT,
                is_selected_for_review INTEGER NOT NULL DEFAULT 0
            );

            CREATE INDEX IF NOT EXISTS idx_admin_norm_variants_document
                ON admin_norm_variants(document_id);

            CREATE TABLE IF NOT EXISTS admin_reviews (
                review_id TEXT PRIMARY KEY,
                document_id TEXT NOT NULL UNIQUE REFERENCES admin_documents(document_id) ON DELETE CASCADE,
                selected_parse_variant_id TEXT NOT NULL,
                selected_norm_variant_id TEXT,
                base_md_path TEXT NOT NULL,
                edited_md_path TEXT,
                uploaded_md_path TEXT,
                review_approved_md_path TEXT,
                status TEXT NOT NULL,
                opened_at TEXT,
                approved_at TEXT,
                notes TEXT,
                review_action_json TEXT
            );

            CREATE TABLE IF NOT EXISTS admin_canonical_files (
                document_id TEXT PRIMARY KEY REFERENCES admin_documents(document_id) ON DELETE CASCADE,
                source_file_path TEXT NOT NULL,
                raw_md_path TEXT NOT NULL,
                parsed_md_path TEXT NOT NULL,
                normalized_md_path TEXT,
                review_approved_md_path TEXT NOT NULL,
                normalization_metadata_json TEXT
            );

            CREATE TABLE IF NOT EXISTS admin_jobs (
                job_id TEXT PRIMARY KEY,
                batch_id TEXT REFERENCES admin_batches(batch_id) ON DELETE CASCADE,
                document_id TEXT REFERENCES admin_documents(document_id) ON DELETE CASCADE,
                parse_variant_id TEXT,
                norm_variant_id TEXT,
                job_type TEXT NOT NULL,
                stage TEXT NOT NULL,
                status TEXT NOT NULL,
                progress INTEGER NOT NULL DEFAULT 0,
                detail TEXT,
                error_message TEXT,
                error_detail TEXT,
                created_at TEXT NOT NULL,
                started_at TEXT,
                completed_at TEXT,
                duration_ms INTEGER,
                attempt INTEGER NOT NULL DEFAULT 1,
                cancel_requested INTEGER NOT NULL DEFAULT 0,
                payload_json TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_admin_jobs_status ON admin_jobs(status);
            CREATE INDEX IF NOT EXISTS idx_admin_jobs_batch ON admin_jobs(batch_id);
            CREATE INDEX IF NOT EXISTS idx_admin_jobs_document ON admin_jobs(document_id);

            CREATE TABLE IF NOT EXISTS admin_job_logs (
                log_id TEXT PRIMARY KEY,
                batch_id TEXT,
                document_id TEXT,
                parse_variant_id TEXT,
                norm_variant_id TEXT,
                job_id TEXT,
                stage TEXT NOT NULL,
                level TEXT NOT NULL,
                message TEXT NOT NULL,
                detail TEXT,
                timestamp TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_admin_job_logs_timestamp
                ON admin_job_logs(timestamp);
            CREATE INDEX IF NOT EXISTS idx_admin_job_logs_level
                ON admin_job_logs(level);

            CREATE TABLE IF NOT EXISTS admin_notifications (
                notification_id TEXT PRIMARY KEY,
                type TEXT NOT NULL,
                batch_id TEXT,
                document_id TEXT,
                job_id TEXT,
                title TEXT NOT NULL,
                message TEXT NOT NULL,
                detail TEXT,
                read INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_admin_notifications_created
                ON admin_notifications(created_at);

            CREATE TABLE IF NOT EXISTS admin_chunks (
                chunk_id TEXT PRIMARY KEY,
                document_id TEXT NOT NULL REFERENCES admin_documents(document_id) ON DELETE CASCADE,
                batch_id TEXT NOT NULL REFERENCES admin_batches(batch_id) ON DELETE CASCADE,
                content TEXT NOT NULL,
                chunk_index INTEGER NOT NULL,
                section_path TEXT,
                page_numbers_json TEXT NOT NULL,
                token_count INTEGER NOT NULL,
                char_count INTEGER NOT NULL,
                embedding_model TEXT NOT NULL,
                indexed_at TEXT NOT NULL,
                chroma_id TEXT NOT NULL UNIQUE
            );

            CREATE INDEX IF NOT EXISTS idx_admin_chunks_document
                ON admin_chunks(document_id);
            CREATE INDEX IF NOT EXISTS idx_admin_chunks_batch
                ON admin_chunks(batch_id);

            CREATE TABLE IF NOT EXISTS admin_llm_endpoints (
                endpoint_id TEXT PRIMARY KEY,
                model_id TEXT NOT NULL,
                endpoint TEXT NOT NULL,
                display_name TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS admin_settings (
                key TEXT PRIMARY KEY,
                value_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(admin_reviews)").fetchall()}
        if "review_action_json" not in columns:
            conn.execute("ALTER TABLE admin_reviews ADD COLUMN review_action_json TEXT")
        conn.commit()
    finally:
        conn.close()
