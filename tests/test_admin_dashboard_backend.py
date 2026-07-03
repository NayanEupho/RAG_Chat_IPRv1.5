from __future__ import annotations

import os
import sys
import json
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.admin.db import init_admin_db
from backend.admin.repository import repo
from backend.admin.schemas import BatchStatus, DocumentStatus, JobStatus, PipelineStage, VariantStatus


@pytest.fixture()
def isolated_admin(tmp_path, monkeypatch):
    monkeypatch.setenv("ADMIN_DASHBOARD_DATA_DIR", str(tmp_path / "admin_data"))
    init_admin_db()
    return tmp_path


def test_model_health_reuses_cached_probe_within_ttl(monkeypatch):
    from backend.admin import router as admin_router

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"models": [{"name": "llama3.1:8b"}, {"name": "nomic-embed-text"}]}

    calls = []

    def fake_get(url, timeout):
        calls.append((url, timeout))
        return FakeResponse()

    admin_router._MODEL_HEALTH_CACHE.clear()
    monkeypatch.setenv("ADMIN_MODEL_HEALTH_TTL_SECONDS", "60")
    monkeypatch.setattr(admin_router.httpx, "get", fake_get)
    model = SimpleNamespace(host="http://127.0.0.1:11434", model_name="llama3.1:8b")
    embedding_model = SimpleNamespace(host="http://127.0.0.1:11434", model_name="nomic-embed-text")

    first = admin_router._model_health(model, "ollama", True)
    second = admin_router._model_health(model, "ollama", True)
    third = admin_router._model_health(embedding_model, "ollama", True)

    assert first["status"] == "online"
    assert first["cached"] is False
    assert second["status"] == "online"
    assert second["cached"] is True
    assert third["status"] == "online"
    assert third["cached"] is True
    assert calls == [("http://127.0.0.1:11434/api/tags", 0.75)]


def test_admin_health_endpoint_is_lightweight_and_reports_ready_database(isolated_admin):
    from backend.admin.router import router

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    client = TestClient(app)

    response = client.get("/api/v1/health")

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["healthy"] is True
    assert payload["service"] == "admin-dashboard"
    assert payload["database"] == "ready"
    assert isinstance(payload["latency_ms"], int)


def test_admin_data_dir_default_is_project_root_stable(monkeypatch):
    from backend.admin import db as db_module

    monkeypatch.delenv("ADMIN_DASHBOARD_DATA_DIR", raising=False)
    monkeypatch.chdir(db_module.PROJECT_ROOT / "Admin_Dashboard")

    assert db_module.admin_data_dir() == (db_module.PROJECT_ROOT / "admin_data").resolve()


def test_admin_db_migrates_users_from_dashboard_local_db(tmp_path, monkeypatch):
    import sqlite3

    from backend.admin import db as db_module
    from backend.admin.auth import authenticate_admin, hash_password

    monkeypatch.delenv("ADMIN_DASHBOARD_DATA_DIR", raising=False)
    monkeypatch.setattr(db_module, "PROJECT_ROOT", tmp_path)
    legacy = tmp_path / "Admin_Dashboard" / "admin_data" / "admin.db"
    legacy.parent.mkdir(parents=True)
    conn = sqlite3.connect(legacy)
    try:
        conn.execute(
            """
            CREATE TABLE admin_users (
                email TEXT PRIMARY KEY,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "INSERT INTO admin_users VALUES (?, ?, ?, ?)",
            ("migrated@example.com", hash_password("pw"), "created", "updated"),
        )
        conn.commit()
    finally:
        conn.close()

    db_module.init_admin_db()

    assert authenticate_admin("migrated@example.com", "pw") is not None


def test_admin_user_store_hashes_and_authenticates_password(isolated_admin):
    from backend.admin.auth import add_admin_user, authenticate_admin, list_admin_users, remove_admin_user
    from backend.admin.db import get_connection

    add_admin_user("Admin@Example.COM ", "correct-password")

    conn = get_connection()
    try:
        row = conn.execute("SELECT email, password_hash FROM admin_users WHERE email = ?", ("admin@example.com",)).fetchone()
    finally:
        conn.close()

    assert row["email"] == "admin@example.com"
    assert row["password_hash"] != "correct-password"
    assert authenticate_admin("admin@example.com", "correct-password")["email"] == "admin@example.com"
    assert authenticate_admin("admin@example.com", "wrong-password") is None
    assert [user["email"] for user in list_admin_users()] == ["admin@example.com"]
    assert remove_admin_user("admin@example.com") is True
    assert authenticate_admin("admin@example.com", "correct-password") is None


def test_admin_login_endpoint_accepts_correct_password(isolated_admin):
    from backend.admin.auth import add_admin_user
    from backend.admin.router import router

    add_admin_user("admin@example.com", "pw123")
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    client = TestClient(app)

    ok_response = client.post("/api/v1/auth/login", json={"email": "admin@example.com", "password": "pw123"})
    bad_response = client.post("/api/v1/auth/login", json={"email": "admin@example.com", "password": "bad"})

    assert ok_response.status_code == 200
    assert ok_response.json()["data"] == {"authenticated": True, "email": "admin@example.com"}
    assert bad_response.status_code == 401


def test_admin_login_sees_user_added_after_app_is_running(isolated_admin):
    from backend.admin.auth import add_admin_user
    from backend.admin.router import router

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    client = TestClient(app)

    before = client.post("/api/v1/auth/login", json={"email": "late@example.com", "password": "pw"})
    add_admin_user("late@example.com", "pw")
    after = client.post("/api/v1/auth/login", json={"email": "late@example.com", "password": "pw"})

    assert before.status_code == 401
    assert after.status_code == 200
    assert after.json()["data"]["authenticated"] is True


def test_add_admin_cli_lists_and_removes_users(isolated_admin, capsys):
    from Admin_Dashboard import add_admin

    assert add_admin.main(["add", "cli@example.com", "pw"]) == 0
    assert "Admin saved: cli@example.com" in capsys.readouterr().out

    assert add_admin.main(["list"]) == 0
    assert "cli@example.com" in capsys.readouterr().out

    assert add_admin.main(["remove", "cli@example.com"]) == 0
    assert "Removed: cli@example.com" in capsys.readouterr().out


def test_add_admin_cli_defaults_to_interactive_shell(isolated_admin, monkeypatch, capsys):
    from Admin_Dashboard import add_admin
    from backend.admin.auth import authenticate_admin

    answers = iter(["add", "interactive@example.com", "list", "quit"])
    passwords = iter(["pw", "pw"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    monkeypatch.setattr(add_admin.getpass, "getpass", lambda prompt="": next(passwords))

    assert add_admin.main([]) == 0

    output = capsys.readouterr().out
    assert "RAG Admin user manager" in output
    assert "Admin saved: interactive@example.com" in output
    assert authenticate_admin("interactive@example.com", "pw") is not None


def _create_document(tmp_path: Path, *, batch_id: str = "batch_test", document_id: str = "doc_test"):
    source = tmp_path / "upload_docs" / "Admin_Dashboard" / "sample.pdf"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(b"%PDF-1.4\n")
    return repo.create_batch(
        batch_id=batch_id,
        name="Batch",
        description=None,
        config={
            "default_parsers": ["docling"],
            "default_normalization_enabled": False,
            "default_normalization_models": [],
            "review_required": True,
            "per_document_overrides": {},
        },
        documents=[
            {
                "document_id": document_id,
                "original_filename": "sample.pdf",
                "source_file_path": str(source),
                "file_type": "pdf",
                "file_size_bytes": source.stat().st_size,
                "effective_config": {
                    "parsers": ["docling"],
                    "normalization_enabled": False,
                    "normalization_models": [],
                    "review_required": True,
                },
            }
        ],
    )["documents"][0]


def test_effective_config_carries_review_required(isolated_admin):
    effective = repo.effective_config(
        {
            "default_parsers": ["pymupdf4llm"],
            "default_normalization_enabled": True,
            "default_normalization_models": [{"model_id": "m", "endpoint": "e", "display_name": "M"}],
            "review_required": False,
            "per_document_overrides": {},
        },
        "doc_1",
    )

    assert effective["parsers"] == ["pymupdf4llm"]
    assert effective["normalization_enabled"] is True
    assert effective["review_required"] is False
    assert effective["ingestion_type"] == "general"


def test_effective_config_applies_per_document_ingestion_type(isolated_admin):
    effective = repo.effective_config(
        {
            "default_parsers": ["docling"],
            "default_normalization_enabled": False,
            "default_normalization_models": [],
            "default_ingestion_type": "general",
            "review_required": True,
            "per_document_overrides": {"doc_1": {"ingestion_type": "qna"}},
        },
        "doc_1",
    )

    assert effective["ingestion_type"] == "qna"


def test_list_batches_accepts_comma_separated_statuses(isolated_admin):
    first = _create_document(isolated_admin, batch_id="batch_complete", document_id="doc_complete")
    second = _create_document(isolated_admin, batch_id="batch_failed", document_id="doc_failed")
    _create_document(isolated_admin, batch_id="batch_draft", document_id="doc_draft")
    repo.set_document_status(first["document_id"], DocumentStatus.INDEXED.value, chunk_count=1, indexed_at="2026-06-26T00:00:00Z")
    repo.set_document_status(second["document_id"], DocumentStatus.PARSE_FAILED.value, error_summary="Parse failed")

    page = repo.list_batches(status="COMPLETE,FAILED,CANCELLED", limit=10)
    ids = {item["batch_id"] for item in page["items"]}

    assert "batch_complete" in ids
    assert "batch_failed" in ids
    assert "batch_draft" not in ids


def test_indexed_document_summaries_include_canonical_files_without_variant_tree(isolated_admin):
    document = _create_document(isolated_admin)
    repo.set_document_status(document["document_id"], DocumentStatus.INDEXED.value, chunk_count=2, indexed_at="2026-06-26T00:00:00Z")
    repo.create_canonical_files(
        document_id=document["document_id"],
        files={
            "source_file_path": document["source_file_path"],
            "raw_md_path": str(isolated_admin / "raw.md"),
            "parsed_md_path": str(isolated_admin / "parsed.md"),
            "normalized_md_path": None,
            "review_approved_md_path": str(isolated_admin / "final.md"),
            "normalization_metadata": None,
        },
    )

    summaries = repo.list_indexed_document_summaries(limit=10)
    summary = next(item for item in summaries if item["document_id"] == document["document_id"])

    assert summary["chunk_count"] == 2
    assert summary["canonical_files"]["parsed_md_path"].endswith("parsed.md")
    assert "parse_variants" not in summary


def _recovery_worker(monkeypatch):
    from backend.admin.worker import AdminWorker

    worker = AdminWorker()
    queued = []
    monkeypatch.setattr(worker, "start", lambda: None)
    monkeypatch.setattr(worker, "enqueue", lambda job_id: queued.append(job_id))
    return worker, queued


def test_worker_recovers_queued_parse_job_without_incrementing_attempt(isolated_admin, monkeypatch):
    document = _create_document(isolated_admin, batch_id="batch_recover_queued", document_id="doc_recover_queued")
    repo.submit_batch(document["batch_id"])
    variant = repo.create_parse_variant(document_id=document["document_id"], parser_type="docling")
    job = repo.create_job(
        job_type="parse",
        stage=PipelineStage.PARSE.value,
        batch_id=document["batch_id"],
        document_id=document["document_id"],
        parse_variant_id=variant["variant_id"],
        payload={"parse_variant_id": variant["variant_id"]},
    )
    worker, queued = _recovery_worker(monkeypatch)

    result = worker.recover_incomplete_jobs()

    assert result["requeued"] == [job["job_id"]]
    assert queued == [job["job_id"]]
    recovered_job = repo.get_job(job["job_id"])
    assert recovered_job["status"] == JobStatus.QUEUED.value
    assert recovered_job["attempt"] == 1
    assert repo.get_document(document["document_id"])["status"] == DocumentStatus.PARSE_PENDING.value


def test_worker_resets_stale_running_parse_job_for_restart_recovery(isolated_admin, monkeypatch):
    document = _create_document(isolated_admin, batch_id="batch_recover_running", document_id="doc_recover_running")
    repo.submit_batch(document["batch_id"])
    variant = repo.create_parse_variant(document_id=document["document_id"], parser_type="docling")
    job = repo.create_job(
        job_type="parse",
        stage=PipelineStage.PARSE.value,
        batch_id=document["batch_id"],
        document_id=document["document_id"],
        parse_variant_id=variant["variant_id"],
        payload={"parse_variant_id": variant["variant_id"]},
    )
    repo.set_document_status(document["document_id"], DocumentStatus.PARSE_RUNNING.value)
    repo.update_parse_variant(variant["variant_id"], status=VariantStatus.RUNNING.value, started_at="2026-06-30T00:00:00+00:00")
    repo.update_job(job["job_id"], status=JobStatus.RUNNING.value, progress=50, detail="Parsing")
    worker, queued = _recovery_worker(monkeypatch)

    result = worker.recover_incomplete_jobs()

    assert result["requeued"] == [job["job_id"]]
    assert queued == [job["job_id"]]
    recovered_job = repo.get_job(job["job_id"])
    assert recovered_job["status"] == JobStatus.QUEUED.value
    assert recovered_job["attempt"] == 2
    assert recovered_job["started_at"] is None
    assert repo.get_document(document["document_id"])["status"] == DocumentStatus.PARSE_PENDING.value
    assert repo.get_parse_variant(variant["variant_id"])["status"] == VariantStatus.PENDING.value


def test_review_pending_document_survives_recovery_without_requeue(isolated_admin, monkeypatch):
    document = _create_document(isolated_admin, batch_id="batch_review_wait", document_id="doc_review_wait")
    repo.submit_batch(document["batch_id"])
    repo.set_document_status(document["document_id"], DocumentStatus.REVIEW_PENDING.value)
    worker, queued = _recovery_worker(monkeypatch)

    result = worker.recover_incomplete_jobs()

    assert result["requeued"] == []
    assert queued == []
    assert repo.get_document(document["document_id"])["status"] == DocumentStatus.REVIEW_PENDING.value


def test_worker_does_not_rerun_stale_chunk_job_for_already_indexed_document(isolated_admin, monkeypatch):
    document = _create_document(isolated_admin, batch_id="batch_chunk_done", document_id="doc_chunk_done")
    repo.submit_batch(document["batch_id"])
    repo.set_document_status(document["document_id"], DocumentStatus.INDEXED.value, chunk_count=2, indexed_at="2026-06-30T00:00:00+00:00")
    job = repo.create_job(
        job_type="chunk",
        stage=PipelineStage.CHUNK.value,
        batch_id=document["batch_id"],
        document_id=document["document_id"],
        payload={"document_id": document["document_id"]},
    )
    repo.update_job(job["job_id"], status=JobStatus.RUNNING.value, progress=80, detail="Indexing")
    worker, queued = _recovery_worker(monkeypatch)

    result = worker.recover_incomplete_jobs()

    assert result["requeued"] == []
    assert queued == []
    assert result["skipped"][0]["reason"] == "stage_already_advanced"
    assert repo.get_job(job["job_id"])["status"] == JobStatus.COMPLETE.value
    assert repo.get_document(document["document_id"])["status"] == DocumentStatus.INDEXED.value


def test_worker_fails_chunk_job_when_no_chunks_are_produced(isolated_admin, monkeypatch):
    from backend.admin.worker import AdminWorker
    from backend.ingestion.processor import DocumentProcessor
    from backend.rag import store as store_module

    class FakeStore:
        def delete_document(self, document_id):
            return None

    document = _create_document(isolated_admin, batch_id="batch_zero_chunks", document_id="doc_zero_chunks")
    repo.submit_batch(document["batch_id"])
    variant = repo.create_parse_variant(document_id=document["document_id"], parser_type="docling")
    parsed_path = isolated_admin / "generated_doc_md" / "parsed.md"
    approved_path = isolated_admin / "generated_doc_md" / "approved.md"
    parsed_path.parent.mkdir(parents=True, exist_ok=True)
    parsed_path.write_text("# Parsed", encoding="utf-8")
    approved_path.write_text("", encoding="utf-8")
    repo.update_parse_variant(variant["variant_id"], status=VariantStatus.COMPLETE.value, parsed_md_path=str(parsed_path), raw_md_path=str(parsed_path))
    repo.create_or_update_review(
        document_id=document["document_id"],
        selected_parse_variant_id=variant["variant_id"],
        selected_norm_variant_id=None,
        base_md_path=str(parsed_path),
        status="APPROVED",
    )
    repo.update_review(document["document_id"], review_approved_md_path=str(approved_path))
    repo.set_document_status(document["document_id"], DocumentStatus.CHUNK_PENDING.value)
    job = repo.create_job(
        job_type="chunk",
        stage=PipelineStage.CHUNK.value,
        batch_id=document["batch_id"],
        document_id=document["document_id"],
        payload={"document_id": document["document_id"]},
    )
    monkeypatch.setattr(store_module, "get_vector_store", lambda: FakeStore())
    monkeypatch.setattr(DocumentProcessor, "process_file", lambda self, *args, **kwargs: [])

    with pytest.raises(ValueError, match="zero chunks"):
        AdminWorker()._chunk(job["job_id"], job)

    failed = repo.get_document(document["document_id"])
    assert failed["status"] == DocumentStatus.CHUNK_FAILED.value
    assert "zero chunks" in failed["error_summary"]
    assert repo.list_chunks(document_id=document["document_id"])["total"] == 0


def test_vector_stats_detail_reports_mirror_and_chroma_counts(monkeypatch):
    from backend.admin import vector_inspector
    from backend.rag import store as store_module

    monkeypatch.setattr(
        vector_inspector.warehouse,
        "indexed_documents",
        lambda limit=10000: {
            "items": [
                {"origin": "admin", "doc_type": "general"},
                {"origin": "legacy", "doc_type": "qna"},
            ]
        },
    )
    monkeypatch.setattr(
        vector_inspector.repo,
        "chunk_stats",
        lambda: {
            "total_chunks": 3,
            "avg_tokens_per_chunk": 12.5,
            "avg_chars_per_chunk": 90,
            "total_tokens": 38,
            "total_chars": 270,
            "embedding_models": [{"embedding_model": "embed-a", "chunks": 3}],
        },
    )

    class FakeStore:
        def count(self):
            return 4

    monkeypatch.setattr(store_module, "get_vector_store", lambda: FakeStore())

    stats = vector_inspector.vector_stats_detail()

    assert stats["indexed_documents"] == 2
    assert stats["admin_documents"] == 1
    assert stats["legacy_documents"] == 1
    assert stats["chroma_chunks"] == 4
    assert stats["mirrored_admin_chunks"] == 3
    assert stats["doc_type_breakdown"] == {"general": 1, "qna": 1}
    assert stats["warnings"][0]["type"] == "mirror_mismatch"
    assert "Retrieval uses Chroma" in stats["warnings"][0]["impact"]


@pytest.mark.asyncio
async def test_vector_probe_returns_candidates_and_reranked_context(monkeypatch):
    from backend.admin import vector_inspector
    from backend.config import OllamaConfig
    from backend.graph.nodes import retriever as retriever_module
    from backend.rag import reranker as reranker_module
    from backend.rag import store as store_module

    monkeypatch.setattr(
        "backend.config.get_config",
        lambda: SimpleNamespace(embedding_model=OllamaConfig(host="http://localhost:11434", model_name="embed-a")),
    )

    async def fake_embedding(query, model):
        return [[0.1, 0.2, 0.3]]

    monkeypatch.setattr(retriever_module, "get_cached_embedding", fake_embedding)

    class FakeStore:
        seen_query_embeddings = None

        def query(self, query_embeddings, n_results=5, where=None):
            self.seen_query_embeddings = query_embeddings
            return {
                "ids": [["chunk_1", "chunk_2"]],
                "documents": [["alpha content", "beta content"]],
                "metadatas": [[
                    {"filename": "a.pdf", "chunk_index": 0, "doc_type": "general"},
                    {"filename": "b.pdf", "chunk_index": 1, "doc_type": "qna"},
                ]],
                "distances": [[0.2, 0.4]],
            }

    fake_store = FakeStore()
    monkeypatch.setattr(store_module, "get_vector_store", lambda: fake_store)

    class FakeReranker:
        model_name = "fake-reranker"

        async def rank(self, query, docs, top_k=5):
            return [{"page_content": docs[1]["page_content"], "metadata": docs[1]["metadata"], "score": 0.91}]

    monkeypatch.setattr(reranker_module, "Reranker", FakeReranker)

    result = await vector_inspector.vector_probe(query="alpha", top_k=1, candidate_k=2, rerank=True)

    assert result["embedding_model"] == "embed-a"
    assert fake_store.seen_query_embeddings == [[0.1, 0.2, 0.3]]
    assert result["reranker_model"] == "fake-reranker"
    assert len(result["candidates"]) == 2
    assert result["final_chunks"][0]["chunk_id"] == "chunk_2"
    assert "beta content" in result["model_context"]


def test_chroma_chunk_inventory_returns_legacy_chunks(monkeypatch):
    from backend.admin import chunk_inventory
    from backend.rag import store as store_module

    class FakeCollection:
        def get(self, where=None, include=None, limit=50, offset=0):
            assert where == {"source": "upload_docs/General/legacy.pdf"}
            return {
                "ids": ["legacy_0"],
                "documents": ["[Doc: legacy.pdf | Section: Intro]\nLegacy content"],
                "metadatas": [
                    {
                        "filename": "legacy.pdf",
                        "source": "upload_docs/General/legacy.pdf",
                        "chunk_index": 0,
                        "section_path": "Intro",
                        "doc_type": "general",
                    }
                ],
            }

    class FakeStore:
        lock = threading.Lock()
        collection = FakeCollection()

    monkeypatch.setattr(store_module, "get_vector_store", lambda: FakeStore())

    page = chunk_inventory.list_chroma_chunks(source="upload_docs/General/legacy.pdf")

    assert page["total"] == 1
    assert page["items"][0]["origin"] == "legacy"
    assert page["items"][0]["filename"] == "legacy.pdf"
    assert page["items"][0]["content"].startswith("[Doc: legacy.pdf")


def test_admin_chunk_label_uses_original_source_markdown_name():
    from backend.admin.worker import rewrite_chunk_doc_label

    rewritten = rewrite_chunk_doc_label(
        "[Doc: approved.md | Section: 4 QLoRA vs. Standard Finetuning]\ncontent",
        current_filename="approved.md",
        source_filename="Lora Paper.pdf",
    )

    assert rewritten.startswith("[Doc: Lora Paper.md | Section: 4 QLoRA")


def test_warehouse_returns_admin_and_legacy_indexed_documents(isolated_admin, monkeypatch):
    from backend.admin import warehouse

    document = _create_document(isolated_admin)
    repo.set_document_status(document["document_id"], DocumentStatus.INDEXED.value, chunk_count=2, indexed_at="2026-06-26T00:00:00Z")
    monkeypatch.setattr(
        warehouse,
        "_fetch_chroma_metadatas",
        lambda: [
            {
                "document_id": document["document_id"],
                "filename": "sample.pdf",
                "source": document["source_file_path"],
                "parser": "docling",
            },
            {
                "filename": "legacy.pdf",
                "source": str(isolated_admin / "upload_docs" / "General" / "legacy.pdf"),
                "parser": "docling_llm_normalized",
                "indexed_at": "2026-06-25T00:00:00Z",
            },
            {
                "filename": "legacy.pdf",
                "source": str(isolated_admin / "upload_docs" / "General" / "legacy.pdf"),
                "parser": "docling_llm_normalized",
            },
        ],
    )
    monkeypatch.setattr(warehouse, "SOURCE_ROOT", isolated_admin / "upload_docs")
    warehouse._legacy_cache["expires_at"] = 0.0

    page = warehouse.indexed_documents()

    origins = {item["filename"]: item["origin"] for item in page["items"]}
    assert origins["sample.pdf"] == "admin"
    assert origins["legacy.pdf"] == "legacy"
    legacy = next(item for item in page["items"] if item["filename"] == "legacy.pdf")
    assert legacy["chunk_count"] == 2
    assert legacy["parser"] == "docling_llm_normalized"
    assert legacy["doc_type"] == "general"


def test_reject_review_marks_document_without_failed_status(isolated_admin):
    document = _create_document(isolated_admin)
    repo.set_document_status(document["document_id"], DocumentStatus.REVIEW_PENDING.value)

    log = repo.reject_review(document["document_id"], "bad markdown")
    updated = repo.get_document(document["document_id"])

    assert updated["status"] == DocumentStatus.REVIEW_REJECTED.value
    assert log["level"] == "INFO"
    assert "rejected" in log["message"].lower()


def test_cancel_batch_marks_jobs_read_notifications_and_removes_artifacts(isolated_admin, monkeypatch):
    from backend.admin import files as admin_files
    from backend.admin import inventory
    from backend.rag import store as store_module

    source_root = isolated_admin / "upload_docs"
    generated_root = isolated_admin / "generated_doc_md"
    monkeypatch.setattr(inventory, "SOURCE_ROOT", source_root)
    monkeypatch.setattr(inventory, "GENERATED_ROOT", generated_root)
    monkeypatch.setattr(admin_files, "SOURCE_ROOT", source_root)
    monkeypatch.setattr(admin_files, "GENERATED_ROOT", generated_root)

    source = source_root / "Admin_Dashboard" / "General" / "batches" / "batch_cancel" / "documents" / "doc_cancel" / "source" / "sample.pdf"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"%PDF-1.4\n")
    batch = repo.create_batch(
        batch_id="batch_cancel",
        name="Cancel me",
        description=None,
        config={
            "default_parsers": ["docling"],
            "default_normalization_enabled": False,
            "default_normalization_models": [],
            "default_ingestion_type": "general",
            "review_required": True,
            "per_document_overrides": {},
        },
        documents=[
            {
                "document_id": "doc_cancel",
                "original_filename": "sample.pdf",
                "source_file_path": str(source),
                "file_type": "pdf",
                "file_size_bytes": source.stat().st_size,
                "effective_config": {
                    "parsers": ["docling"],
                    "normalization_enabled": False,
                    "normalization_models": [],
                    "review_required": True,
                    "ingestion_type": "general",
                },
            }
        ],
    )
    repo.submit_batch(batch["batch_id"])
    job = repo.create_job(
        job_type="parse",
        stage=PipelineStage.PARSE.value,
        batch_id=batch["batch_id"],
        document_id="doc_cancel",
        payload={},
    )
    repo.notify(
        type_="STAGE_UPDATE",
        title="Document ready for review",
        message="sample.pdf",
        batch_id=batch["batch_id"],
        document_id="doc_cancel",
    )
    generated_file = admin_files.generated_root() / "batches" / batch["batch_id"] / "documents" / "doc_cancel" / "variants" / "variant_1" / "parsed.md"
    generated_file.parent.mkdir(parents=True)
    generated_file.write_text("# Parsed", encoding="utf-8")
    deleted_documents = []

    class FakeStore:
        def delete_document(self, document_id):
            deleted_documents.append(document_id)

    monkeypatch.setattr(store_module, "get_vector_store", lambda: FakeStore())

    result = repo.cancel_batch(batch["batch_id"])

    assert result["cancelled"] is True
    assert repo.get_batch(batch["batch_id"], include_documents=False)["status"] == BatchStatus.CANCELLED.value
    assert repo.get_document("doc_cancel")["status"] == DocumentStatus.CANCELLED.value
    updated_job = repo.get_job(job["job_id"])
    assert updated_job["status"] == JobStatus.CANCELLED.value
    assert updated_job["cancel_requested"] == 1
    assert deleted_documents == ["doc_cancel"]
    assert not source.parent.parent.exists()
    assert not (admin_files.generated_root() / "batches" / batch["batch_id"]).exists()
    assert repo.list_notifications()["unread_count"] == 0


def test_review_approval_marks_document_notifications_read(isolated_admin, monkeypatch):
    from backend.admin import files as admin_files
    from backend.admin import inventory
    from backend.admin.worker import AdminWorker

    source_root = isolated_admin / "upload_docs"
    generated_root = isolated_admin / "generated_doc_md"
    monkeypatch.setattr(inventory, "SOURCE_ROOT", source_root)
    monkeypatch.setattr(inventory, "GENERATED_ROOT", generated_root)
    monkeypatch.setattr(admin_files, "SOURCE_ROOT", source_root)
    monkeypatch.setattr(admin_files, "GENERATED_ROOT", generated_root)

    source = source_root / "Admin_Dashboard" / "General" / "batches" / "batch_review" / "documents" / "doc_review" / "source" / "sample.pdf"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"%PDF-1.4\n")
    repo.create_batch(
        batch_id="batch_review",
        name="Review batch",
        description=None,
        config={
            "default_parsers": ["docling"],
            "default_normalization_enabled": False,
            "default_normalization_models": [],
            "default_ingestion_type": "general",
            "review_required": True,
            "per_document_overrides": {},
        },
        documents=[
            {
                "document_id": "doc_review",
                "original_filename": "sample.pdf",
                "source_file_path": str(source),
                "file_type": "pdf",
                "file_size_bytes": source.stat().st_size,
                "effective_config": {
                    "parsers": ["docling"],
                    "normalization_enabled": False,
                    "normalization_models": [],
                    "review_required": True,
                    "ingestion_type": "general",
                },
            }
        ],
    )
    variant = repo.create_parse_variant(document_id="doc_review", parser_type="docling")
    parsed_path = admin_files.variant_dir("batch_review", "doc_review", variant["variant_id"]) / "parsed.md"
    raw_path = parsed_path.with_name("raw.md")
    parsed_path.write_text("# Parsed", encoding="utf-8")
    raw_path.write_text("# Raw", encoding="utf-8")
    repo.update_parse_variant(variant["variant_id"], status="COMPLETE", parsed_md_path=str(parsed_path), raw_md_path=str(raw_path))
    repo.set_document_status("doc_review", DocumentStatus.REVIEW_PENDING.value)
    repo.notify(
        type_="STAGE_UPDATE",
        title="Document ready for review",
        message="sample.pdf",
        batch_id="batch_review",
        document_id="doc_review",
    )

    worker = AdminWorker()
    monkeypatch.setattr(
        worker,
        "enqueue_chunk",
        lambda batch_id, document_id: repo.create_job(
            job_type="chunk",
            stage=PipelineStage.CHUNK.value,
            batch_id=batch_id,
            document_id=document_id,
            payload={},
        ),
    )
    job = worker.approve_and_enqueue_chunk(
        document_id="doc_review",
        selected_parse_variant_id=variant["variant_id"],
        selected_norm_variant_id=None,
        notes="approved",
    )

    assert job["status"] == JobStatus.QUEUED.value
    assert repo.get_document("doc_review")["status"] == DocumentStatus.CHUNK_PENDING.value
    assert repo.list_notifications()["unread_count"] == 0


def test_indexed_delete_rejects_intermediate_documents(isolated_admin):
    document = _create_document(isolated_admin)

    with pytest.raises(ValueError):
        repo.delete_indexed_document_record(document["document_id"])


def test_retry_success_clears_document_error_and_refreshes_batch_completion(isolated_admin):
    document = _create_document(isolated_admin)

    repo.set_document_status(document["document_id"], DocumentStatus.CHUNK_FAILED.value, error_summary="Chunking failed")
    failed_batch = repo.get_batch(document["batch_id"], include_documents=False)
    assert failed_batch["status"] == "FAILED"
    assert failed_batch["completed_at"]

    repo.set_document_status(document["document_id"], DocumentStatus.CHUNK_PENDING.value)
    retrying_batch = repo.get_batch(document["batch_id"], include_documents=False)
    retrying_doc = repo.get_document(document["document_id"])
    assert retrying_batch["status"] == "CHUNKING"
    assert retrying_batch["completed_at"] is None
    assert retrying_doc["error_summary"] is None

    repo.set_document_status(document["document_id"], DocumentStatus.INDEXED.value, chunk_count=3, indexed_at="2026-06-28T00:00:00Z")
    indexed_doc = repo.get_document(document["document_id"])
    complete_batch = repo.get_batch(document["batch_id"], include_documents=False)

    assert indexed_doc["error_summary"] is None
    assert indexed_doc["chunk_count"] == 3
    assert complete_batch["status"] == "COMPLETE"
    assert complete_batch["completed_at"]


def test_admin_worker_batches_sync_embedding_requests():
    from backend.admin.worker import embed_text_batches

    calls = []

    class FakeClient:
        def embed(self, *, model, input):
            calls.append({"model": model, "input": list(input)})
            return {"embeddings": [[float(len(calls))] for _ in input]}

    embeddings = embed_text_batches(FakeClient(), "embed-model", ["a", "b", "c"], batch_size=2)

    assert embeddings == [[1.0], [1.0], [2.0]]
    assert calls == [
        {"model": "embed-model", "input": ["a", "b"]},
        {"model": "embed-model", "input": ["c"]},
    ]


def test_admin_router_lists_indexed_admin_and_legacy_documents(isolated_admin, monkeypatch):
    from backend.admin import warehouse
    from backend.admin.router import router

    document = _create_document(isolated_admin)
    repo.set_document_status(document["document_id"], DocumentStatus.INDEXED.value, chunk_count=1, indexed_at="2026-06-26T00:00:00Z")
    monkeypatch.setattr(
        warehouse,
        "_fetch_chroma_metadatas",
        lambda: [
            {"document_id": document["document_id"], "filename": "sample.pdf", "source": document["source_file_path"]},
            {"filename": "legacy.pdf", "source": str(isolated_admin / "upload_docs" / "General" / "legacy.pdf"), "parser": "docling"},
        ],
    )
    monkeypatch.setattr(warehouse, "SOURCE_ROOT", isolated_admin / "upload_docs")
    warehouse._legacy_cache["expires_at"] = 0.0

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    response = TestClient(app).get("/api/v1/warehouse/indexed-documents")

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["total"] == 2
    assert {item["origin"] for item in payload["items"]} == {"admin", "legacy"}


def test_runtime_config_exposes_supported_admin_parser_options(isolated_admin, monkeypatch):
    from backend.admin.router import router
    from backend import config as config_module

    monkeypatch.setenv("RAG_VLM_MODEL", "False")
    config_module._runtime_config.vlm_model = "False"
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    response = TestClient(app).get("/api/v1/runtime-config")

    assert response.status_code == 200
    options = response.json()["data"]["parser_options"]
    values = {option["value"] for option in options}
    assert {"auto", "docling", "docling_vision", "pymupdf4llm", "pymupdf", "vision_llm"} <= values
    assert next(option for option in options if option["value"] == "vision_llm")["available"] is False


def test_runtime_config_exposes_separate_normalization_model(isolated_admin, monkeypatch):
    from backend.admin.router import router
    from backend import config as config_module

    config_module._runtime_config.main_model = None
    config_module._runtime_config.embedding_model = None
    config_module._runtime_config.normalization_model = None
    monkeypatch.setenv("RAG_MAIN_HOST", "http://main-host:11434")
    monkeypatch.setenv("RAG_MAIN_MODEL", "main-model")
    monkeypatch.setenv("RAG_EMBED_HOST", "http://embed-host:11434")
    monkeypatch.setenv("RAG_EMBED_MODEL", "embed-model")
    monkeypatch.setenv("RAG_NORMALIZATION_HOST", "http://norm-host:11434")
    monkeypatch.setenv("RAG_NORMALIZATION_MODEL", "norm-model")

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    response = TestClient(app).get("/api/v1/runtime-config")

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["normalization"]["model_id"] == "norm-model"
    assert payload["normalization"]["endpoint"] == "http://norm-host:11434"
    rows = {row["role"]: row for row in payload["models"]}
    assert rows["Main model (retriever)"]["model_id"] == "main-model"
    assert rows["LLM normalization model"]["model_id"] == "norm-model"


def test_runtime_config_refreshes_normalization_model_from_env(isolated_admin, monkeypatch):
    from backend import config as config_module
    from backend.config import get_config

    config_module._runtime_config.normalization_model = None
    monkeypatch.setenv("RAG_NORMALIZATION_HOST", "http://norm-a:11434")
    monkeypatch.setenv("RAG_NORMALIZATION_MODEL", "norm-a")
    assert get_config().normalization_model.model_name == "norm-a"

    monkeypatch.setenv("RAG_NORMALIZATION_HOST", "http://norm-b:11434")
    monkeypatch.setenv("RAG_NORMALIZATION_MODEL", "norm-b")
    cfg = get_config()

    assert cfg.normalization_model.host == "http://norm-b:11434"
    assert cfg.normalization_model.model_name == "norm-b"


def test_create_batch_rejects_unsupported_parser(isolated_admin):
    from backend.admin.router import router

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    response = TestClient(app).post(
        "/api/v1/batches",
        data={"batch_name": "Bad parser", "parser": "not-a-parser"},
        files=[("files", ("sample.pdf", b"%PDF-1.4\n", "application/pdf"))],
    )

    assert response.status_code == 400
    assert "Unsupported parser" in response.json()["detail"]


def test_create_batch_rejects_unconfigured_vlm_parser(isolated_admin, monkeypatch):
    from backend.admin.router import router
    from backend import config as config_module

    monkeypatch.setenv("RAG_VLM_MODEL", "False")
    config_module._runtime_config.vlm_model = "False"
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    response = TestClient(app).post(
        "/api/v1/batches",
        data={"batch_name": "VLM parser", "parser": "vision_llm"},
        files=[("files", ("sample.pdf", b"%PDF-1.4\n", "application/pdf"))],
    )

    assert response.status_code == 400
    assert "RAG_VLM_MODEL" in response.json()["detail"]


def test_create_batch_rejects_normalization_without_model(isolated_admin, monkeypatch):
    from backend.admin.router import router
    from backend import config as config_module

    config_module._runtime_config.main_model = None
    config_module._runtime_config.normalization_model = None
    monkeypatch.setenv("RAG_MAIN_HOST", "")
    monkeypatch.setenv("RAG_MAIN_MODEL", "")
    monkeypatch.setenv("RAG_NORMALIZATION_HOST", "")
    monkeypatch.setenv("RAG_NORMALIZATION_MODEL", "")

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    response = TestClient(app).post(
        "/api/v1/batches",
        data={"batch_name": "Needs model", "parser": "docling", "normalization_enabled": "true"},
        files=[("files", ("sample.pdf", b"%PDF-1.4\n", "application/pdf"))],
    )

    assert response.status_code == 400
    assert "normalization model" in response.json()["detail"].lower()


def test_create_batch_uses_env_normalization_model_when_form_model_omitted(isolated_admin, monkeypatch):
    from backend.admin.router import router
    from backend import config as config_module

    config_module._runtime_config.main_model = None
    config_module._runtime_config.embedding_model = None
    config_module._runtime_config.normalization_model = None
    monkeypatch.setenv("RAG_MAIN_HOST", "http://main-host:11434")
    monkeypatch.setenv("RAG_MAIN_MODEL", "main-model")
    monkeypatch.setenv("RAG_EMBED_HOST", "http://embed-host:11434")
    monkeypatch.setenv("RAG_EMBED_MODEL", "embed-model")
    monkeypatch.setenv("RAG_NORMALIZATION_HOST", "http://norm-host:11434")
    monkeypatch.setenv("RAG_NORMALIZATION_MODEL", "norm-model")

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    response = TestClient(app).post(
        "/api/v1/batches",
        data={"batch_name": "Needs model", "parser": "docling", "normalization_enabled": "true"},
        files=[("files", ("sample.pdf", b"%PDF-1.4\n", "application/pdf"))],
    )

    assert response.status_code == 200
    batch = response.json()["data"]
    models = batch["config"]["default_normalization_models"]
    assert models == [{"model_id": "norm-model", "endpoint": "http://norm-host:11434", "display_name": "norm-model"}]
    assert batch["documents"][0]["effective_config"]["normalization_models"][0]["model_id"] == "norm-model"


def test_create_batch_accepts_mixed_document_ingestion_types(isolated_admin):
    from backend.admin.router import router

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    response = TestClient(app).post(
        "/api/v1/batches",
        data={
            "batch_name": "Mixed docs",
            "parser": "docling",
            "ingestion_type": "general",
            "document_types_json": '["general","qna"]',
        },
        files=[
            ("files", ("policy.pdf", b"%PDF-1.4\n", "application/pdf")),
            ("files", ("faq.pdf", b"%PDF-1.4\n", "application/pdf")),
        ],
    )

    assert response.status_code == 200
    batch = response.json()["data"]
    assert batch["ingestion_label"] == "mix"
    docs = {doc["original_filename"]: doc for doc in batch["documents"]}
    assert docs["policy.pdf"]["ingestion_type"] == "general"
    assert docs["faq.pdf"]["ingestion_type"] == "qna"
    assert "Admin_Dashboard" in docs["faq.pdf"]["source_file_path"]
    assert "QnA" in docs["faq.pdf"]["source_file_path"]
    assert "General" in docs["policy.pdf"]["source_file_path"]


def test_create_batch_accepts_per_document_parser_normalization_and_review_overrides(isolated_admin, monkeypatch):
    from backend.admin import files as admin_files
    from backend.admin import inventory
    from backend.admin.router import router

    source_root = isolated_admin / "upload_docs"
    generated_root = isolated_admin / "generated_doc_md"
    monkeypatch.setattr(inventory, "SOURCE_ROOT", source_root)
    monkeypatch.setattr(inventory, "GENERATED_ROOT", generated_root)
    monkeypatch.setattr(admin_files, "SOURCE_ROOT", source_root)
    monkeypatch.setattr(admin_files, "GENERATED_ROOT", generated_root)

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    response = TestClient(app).post(
        "/api/v1/batches",
        data={
            "batch_name": "Per doc config",
            "parser": "docling",
            "ingestion_type": "general",
            "normalization_enabled": "false",
            "review_required": "true",
            "normalization_model_id": "llm-a",
            "normalization_endpoint": "http://localhost:11434",
            "normalization_display_name": "LLM A",
            "document_configs_json": json.dumps(
                [
                    {
                        "parser": "pymupdf4llm",
                        "ingestion_type": "general",
                        "normalization_enabled": False,
                        "review_required": True,
                    },
                    {
                        "parser": "docling",
                        "ingestion_type": "qna",
                        "normalization_enabled": True,
                        "review_required": False,
                    },
                ]
            ),
        },
        files=[
            ("files", ("policy.pdf", b"%PDF-1.4\n", "application/pdf")),
            ("files", ("faq.pdf", b"%PDF-1.4\n", "application/pdf")),
        ],
    )

    assert response.status_code == 200
    batch = response.json()["data"]
    assert batch["ingestion_label"] == "mix"
    docs = {doc["original_filename"]: doc for doc in batch["documents"]}
    assert docs["policy.pdf"]["effective_config"]["parsers"] == ["pymupdf4llm"]
    assert docs["policy.pdf"]["effective_config"]["normalization_enabled"] is False
    assert docs["policy.pdf"]["effective_config"]["review_required"] is True
    assert docs["faq.pdf"]["effective_config"]["parsers"] == ["docling"]
    assert docs["faq.pdf"]["effective_config"]["normalization_enabled"] is True
    assert docs["faq.pdf"]["effective_config"]["review_required"] is False
    assert docs["faq.pdf"]["effective_config"]["normalization_models"][0]["model_id"] == "llm-a"
    assert "QnA" in docs["faq.pdf"]["source_file_path"]


def test_update_draft_batch_config_edits_per_document_settings_and_moves_source_tree(isolated_admin, monkeypatch):
    from backend.admin import files as admin_files
    from backend.admin import inventory
    from backend.admin.router import router

    source_root = isolated_admin / "upload_docs"
    generated_root = isolated_admin / "generated_doc_md"
    monkeypatch.setattr(inventory, "SOURCE_ROOT", source_root)
    monkeypatch.setattr(inventory, "GENERATED_ROOT", generated_root)
    monkeypatch.setattr(admin_files, "SOURCE_ROOT", source_root)
    monkeypatch.setattr(admin_files, "GENERATED_ROOT", generated_root)

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    client = TestClient(app)
    created = client.post(
        "/api/v1/batches",
        data={"batch_name": "Editable draft", "parser": "docling", "ingestion_type": "general"},
        files=[("files", ("policy.pdf", b"%PDF-1.4\n", "application/pdf"))],
    )
    assert created.status_code == 200
    batch = created.json()["data"]
    document = batch["documents"][0]
    assert "General" in document["source_file_path"]

    payload = {
        "default_parsers": ["docling"],
        "default_normalization_enabled": False,
        "default_normalization_models": [],
        "default_ingestion_type": "general",
        "review_required": True,
        "per_document_overrides": {
            document["document_id"]: {
                "parsers": ["pymupdf4llm"],
                "normalization_enabled": False,
                "normalization_models": [],
                "ingestion_type": "qna",
                "review_required": False,
            }
        },
    }
    updated = client.patch(f"/api/v1/batches/{batch['batch_id']}/config", json=payload)

    assert updated.status_code == 200
    updated_doc = updated.json()["data"]["documents"][0]
    assert updated_doc["effective_config"]["parsers"] == ["pymupdf4llm"]
    assert updated_doc["effective_config"]["review_required"] is False
    assert updated_doc["ingestion_type"] == "qna"
    assert "QnA" in updated_doc["source_file_path"]
    assert Path(updated_doc["source_file_path"]).exists()
    assert not Path(document["source_file_path"]).exists()


def test_update_batch_config_fills_env_normalization_model(isolated_admin, monkeypatch):
    from backend.admin.router import router
    from backend import config as config_module

    config_module._runtime_config.main_model = None
    config_module._runtime_config.embedding_model = None
    config_module._runtime_config.normalization_model = None
    monkeypatch.setenv("RAG_MAIN_HOST", "http://main-host:11434")
    monkeypatch.setenv("RAG_MAIN_MODEL", "main-model")
    monkeypatch.setenv("RAG_EMBED_HOST", "http://embed-host:11434")
    monkeypatch.setenv("RAG_EMBED_MODEL", "embed-model")
    monkeypatch.setenv("RAG_NORMALIZATION_HOST", "http://norm-host:11434")
    monkeypatch.setenv("RAG_NORMALIZATION_MODEL", "norm-model")

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    client = TestClient(app)
    created = client.post(
        "/api/v1/batches",
        data={"batch_name": "Editable normalization draft", "parser": "docling", "normalization_enabled": "false"},
        files=[("files", ("policy.pdf", b"%PDF-1.4\n", "application/pdf"))],
    )
    assert created.status_code == 200
    batch = created.json()["data"]

    updated = client.patch(
        f"/api/v1/batches/{batch['batch_id']}/config",
        json={
            "default_parsers": ["docling"],
            "default_normalization_enabled": True,
            "default_normalization_models": [],
            "default_ingestion_type": "general",
            "review_required": True,
            "per_document_overrides": {},
        },
    )

    assert updated.status_code == 200
    config = updated.json()["data"]["config"]
    assert config["default_normalization_models"] == [
        {"model_id": "norm-model", "endpoint": "http://norm-host:11434", "display_name": "norm-model"}
    ]
    assert updated.json()["data"]["documents"][0]["effective_config"]["normalization_models"][0]["model_id"] == "norm-model"


def test_update_batch_config_rejects_non_draft_batches(isolated_admin):
    document = _create_document(isolated_admin)
    repo.submit_batch(document["batch_id"])

    with pytest.raises(ValueError):
        repo.update_batch_config(
            document["batch_id"],
            {
                "default_parsers": ["docling"],
                "default_normalization_enabled": False,
                "default_normalization_models": [],
                "default_ingestion_type": "general",
                "review_required": True,
                "per_document_overrides": {},
            },
        )


def test_repository_log_publishes_sse_log_event(isolated_admin):
    from backend.admin.events import event_hub

    subscriber = event_hub.subscribe()
    try:
        log = repo.log(stage="PARSE", level="INFO", message="Started parse")
        event = subscriber.get(timeout=1)
    finally:
        event_hub.unsubscribe(subscriber)

    assert event["type"] == "log"
    assert event["data"]["log_id"] == log["log_id"]
    assert event["data"]["message"] == "Started parse"


def test_review_content_endpoint_returns_parsed_normalized_and_editable_sources(isolated_admin):
    from backend.admin import files as admin_files
    from backend.admin.router import router

    document = _create_document(isolated_admin)
    parse = repo.create_parse_variant(document_id=document["document_id"], parser_type="docling")
    parsed_path = admin_files.write_text(isolated_admin / "admin_data" / "parsed.md", "# Parsed")
    parse = repo.update_parse_variant(parse["variant_id"], status="COMPLETE", parsed_md_path=parsed_path)
    norm = repo.create_norm_variant(
        parse_variant_id=parse["variant_id"],
        document_id=document["document_id"],
        model={"model_id": "llm-a", "endpoint": "http://localhost:11434", "display_name": "LLM A"},
    )
    normalized_path = admin_files.write_text(isolated_admin / "admin_data" / "normalized.md", "# Normalized")
    norm = repo.update_norm_variant(norm["norm_variant_id"], status="COMPLETE", normalized_md_path=normalized_path)
    repo.create_or_update_review(
        document_id=document["document_id"],
        selected_parse_variant_id=parse["variant_id"],
        selected_norm_variant_id=norm["norm_variant_id"],
        base_md_path=normalized_path,
        status="IN_PROGRESS",
    )
    edited_path = admin_files.write_text(isolated_admin / "admin_data" / "edited.md", "# Edited")
    repo.update_review(document["document_id"], edited_md_path=edited_path)

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    client = TestClient(app)

    parsed = client.get(f"/api/v1/documents/{document['document_id']}/review/content?kind=parsed")
    normalized = client.get(f"/api/v1/documents/{document['document_id']}/review/content?kind=normalized")
    review = client.get(f"/api/v1/documents/{document['document_id']}/review/content?kind=review")

    assert parsed.status_code == 200
    assert parsed.json()["data"]["content"] == "# Parsed"
    assert parsed.json()["data"]["editable"] is False
    assert normalized.json()["data"]["content"] == "# Normalized"
    assert normalized.json()["data"]["editable"] is False
    assert review.json()["data"]["content"] == "# Edited"
    assert review.json()["data"]["editable"] is True


def test_admin_worker_starts_configured_worker_pool(monkeypatch):
    from backend.admin.worker import AdminWorker

    monkeypatch.setenv("ADMIN_DASHBOARD_WORKERS", "3")
    worker = AdminWorker()
    worker.start()
    try:
        assert len(worker._threads) == 3
        assert all(thread.is_alive() for thread in worker._threads)
    finally:
        worker.stop()


def test_legacy_warehouse_exposes_source_and_markdown_downloads(isolated_admin, monkeypatch):
    from backend.admin import warehouse

    source = isolated_admin / "upload_docs" / "General" / "legacy.pdf"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"%PDF-1.4\n")
    run_dir = isolated_admin / "generated_doc_md" / "legacy" / "docling_llm_normalized" / "run"
    run_dir.mkdir(parents=True)
    parsed = run_dir / "parse_docling.md"
    normalized = run_dir / "normalized.md"
    final = run_dir / "selected.md"
    parsed.write_text("# Parsed", encoding="utf-8")
    normalized.write_text("# Normalized", encoding="utf-8")
    final.write_text("# Final", encoding="utf-8")

    monkeypatch.setattr(warehouse, "SOURCE_ROOT", isolated_admin / "upload_docs")
    monkeypatch.setattr(warehouse, "GENERATED_ROOT", isolated_admin / "generated_doc_md")
    monkeypatch.setattr(
        warehouse,
        "_fetch_chroma_metadatas",
        lambda: [{"filename": "legacy.pdf", "source": str(source), "parser": "docling_llm_normalized"}],
    )
    monkeypatch.setattr(
        warehouse,
        "list_artifact_runs",
        lambda limit=10000: [
            {
                "parser": "docling_llm_normalized",
                "modified_at": 1,
                "manifest": {"filename": "legacy.pdf", "file_path": str(source)},
                "files": {
                    "parse_docling.md": str(parsed),
                    "normalized.md": str(normalized),
                    "selected.md": str(final),
                },
            }
        ],
    )
    warehouse._legacy_cache["expires_at"] = 0.0

    legacy = warehouse.legacy_indexed_documents(force_refresh=True)[0]

    assert legacy["downloads"]["source"] is True
    assert legacy["downloads"]["parsed"] is True
    assert legacy["downloads"]["normalized"] is True
    assert legacy["downloads"]["final"] is True
    assert warehouse.legacy_file_path(legacy["id"], "source") == source.resolve()
    assert warehouse.legacy_file_path(legacy["id"], "parsed") == parsed.resolve()
    assert warehouse.legacy_file_path(legacy["id"], "normalized") == normalized.resolve()
    assert warehouse.legacy_file_path(legacy["id"], "final") == final.resolve()


def test_delete_legacy_document_removes_source_and_generated_artifact_run(isolated_admin, monkeypatch):
    from backend.admin import warehouse
    from backend.rag import store as store_module

    source = isolated_admin / "upload_docs" / "General" / "legacy.pdf"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"%PDF-1.4\n")
    run_dir = isolated_admin / "generated_doc_md" / "legacy" / "docling" / "run"
    run_dir.mkdir(parents=True)
    parsed = run_dir / "parse_docling.md"
    manifest = run_dir / "manifest.json"
    parsed.write_text("# Parsed", encoding="utf-8")
    manifest.write_text('{"filename":"legacy.pdf"}', encoding="utf-8")
    deleted_filters = []

    class FakeStore:
        def delete_legacy_document(self, *, filename, source):
            deleted_filters.append({"filename": filename, "source": source})

    monkeypatch.setattr(store_module, "get_vector_store", lambda: FakeStore())
    monkeypatch.setattr(warehouse, "SOURCE_ROOT", isolated_admin / "upload_docs")
    monkeypatch.setattr(warehouse, "GENERATED_ROOT", isolated_admin / "generated_doc_md")
    monkeypatch.setattr(
        warehouse,
        "_fetch_chroma_metadatas",
        lambda: [{"filename": "legacy.pdf", "source": str(source), "parser": "docling"}],
    )
    monkeypatch.setattr(
        warehouse,
        "list_artifact_runs",
        lambda limit=10000: [
            {
                "parser": "docling",
                "path": str(run_dir),
                "relative_path": "legacy/docling/run",
                "modified_at": 1,
                "manifest": {"filename": "legacy.pdf", "file_path": str(source)},
                "files": {
                    "parse_docling.md": str(parsed),
                    "manifest.json": str(manifest),
                },
            }
        ],
    )
    warehouse._legacy_cache["expires_at"] = 0.0
    legacy_id = warehouse.legacy_indexed_documents(force_refresh=True)[0]["id"]

    result = warehouse.delete_legacy_document(legacy_id)

    assert result["deleted"] is True
    assert deleted_filters == [{"filename": "legacy.pdf", "source": str(source)}]
    assert not source.exists()
    assert not run_dir.exists()
    assert not (isolated_admin / "generated_doc_md" / "legacy").exists()


def test_bulk_delete_legacy_document_publishes_inventory_events(isolated_admin, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from backend.admin import router as admin_router
    from backend.admin import warehouse
    from backend.rag import store as store_module

    published = []
    source = isolated_admin / "upload_docs" / "General" / "legacy.pdf"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"%PDF-1.4\n")

    class FakeStore:
        def delete_legacy_document(self, *, filename, source):
            return None

    monkeypatch.setattr(store_module, "get_vector_store", lambda: FakeStore())
    monkeypatch.setattr(admin_router.event_hub, "publish", lambda event: published.append(event))
    monkeypatch.setattr(warehouse, "SOURCE_ROOT", isolated_admin / "upload_docs")
    monkeypatch.setattr(warehouse, "GENERATED_ROOT", isolated_admin / "generated_doc_md")
    monkeypatch.setattr(
        warehouse,
        "_fetch_chroma_metadatas",
        lambda: [{"filename": "legacy.pdf", "source": str(source), "parser": "docling"}],
    )
    monkeypatch.setattr(warehouse, "list_artifact_runs", lambda limit=10000: [])
    warehouse._legacy_cache["expires_at"] = 0.0
    legacy_id = warehouse.legacy_indexed_documents(force_refresh=True)[0]["id"]

    app = FastAPI()
    app.include_router(admin_router.router, prefix="/api/v1")
    response = TestClient(app).post(
        "/api/v1/documents/bulk-delete",
        json={"items": [{"id": legacy_id, "origin": "legacy"}]},
    )

    assert response.status_code == 200
    assert response.json()["data"]["errors"] == []
    assert any(event["type"] == "warehouse_update" and event["action"] == "bulk_delete" for event in published)
    assert any(event["type"] == "stats_update" and event["action"] == "bulk_delete" for event in published)


def test_legacy_warehouse_merges_relative_and_absolute_source_duplicates(isolated_admin, monkeypatch):
    from backend.admin import warehouse

    source = isolated_admin / "upload_docs" / "General" / "same.pdf"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"%PDF-1.4\n")
    relative_source = "upload_docs\\General\\same.pdf"
    absolute_source = str(source)
    monkeypatch.chdir(isolated_admin)
    monkeypatch.setattr(warehouse, "SOURCE_ROOT", isolated_admin / "upload_docs")
    monkeypatch.setattr(warehouse, "GENERATED_ROOT", isolated_admin / "generated_doc_md")
    monkeypatch.setattr(
        warehouse,
        "_fetch_chroma_metadatas",
        lambda: [
            {"filename": "same.pdf", "source": relative_source, "parser": "docling"},
            {"filename": "same.pdf", "source": absolute_source, "parser": "docling"},
            {"filename": "same.pdf", "source": absolute_source, "parser": "docling"},
        ],
    )
    monkeypatch.setattr(warehouse, "list_artifact_runs", lambda limit=10000: [])
    warehouse._legacy_cache["expires_at"] = 0.0

    items = warehouse.legacy_indexed_documents(force_refresh=True)

    assert len(items) == 1
    assert items[0]["chunk_count"] == 3
    assert set(items[0]["source_aliases"]) == {relative_source, absolute_source}


def test_legacy_file_endpoint_supports_view_and_download_disposition(isolated_admin, monkeypatch):
    from backend.admin import warehouse
    from backend.admin.router import router

    source = isolated_admin / "upload_docs" / "General" / "legacy.pdf"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"%PDF-1.4\n")
    monkeypatch.setattr(warehouse, "SOURCE_ROOT", isolated_admin / "upload_docs")
    monkeypatch.setattr(warehouse, "GENERATED_ROOT", isolated_admin / "generated_doc_md")
    monkeypatch.setattr(warehouse, "_fetch_chroma_metadatas", lambda: [{"filename": "legacy.pdf", "source": str(source)}])
    monkeypatch.setattr(warehouse, "list_artifact_runs", lambda limit=10000: [])
    warehouse._legacy_cache["expires_at"] = 0.0
    legacy_id = warehouse.legacy_indexed_documents(force_refresh=True)[0]["id"]

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    client = TestClient(app)

    inline = client.get(f"/api/v1/legacy-documents/{legacy_id}/files/source")
    attachment = client.get(f"/api/v1/legacy-documents/{legacy_id}/files/source?download=true")

    assert inline.status_code == 200
    assert "inline" in inline.headers["content-disposition"]
    assert inline.headers["content-type"].startswith("application/pdf")
    assert attachment.status_code == 200
    assert "attachment" in attachment.headers["content-disposition"]


def test_reject_review_endpoint_records_non_error_rejection(isolated_admin):
    from backend.admin.router import router

    document = _create_document(isolated_admin)
    repo.set_document_status(document["document_id"], DocumentStatus.REVIEW_PENDING.value)

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    response = TestClient(app).post(
        f"/api/v1/documents/{document['document_id']}/review/reject",
        json={"reason": "not suitable"},
    )

    assert response.status_code == 200
    updated = response.json()["data"]["document"]
    assert updated["status"] == DocumentStatus.REVIEW_REJECTED.value


def test_reject_review_deletes_only_rejected_document_artifacts_and_keeps_audit(isolated_admin, monkeypatch):
    from backend.admin import files as admin_files
    from backend.admin import inventory
    from backend.admin.router import router

    source_root = isolated_admin / "upload_docs"
    generated_root = isolated_admin / "generated_doc_md"
    monkeypatch.setattr(inventory, "SOURCE_ROOT", source_root)
    monkeypatch.setattr(inventory, "GENERATED_ROOT", generated_root)
    monkeypatch.setattr(admin_files, "SOURCE_ROOT", source_root)
    monkeypatch.setattr(admin_files, "GENERATED_ROOT", generated_root)

    batch = repo.create_batch(
        batch_id="batch_reject_cleanup",
        name="Reject cleanup",
        description=None,
        config={
            "default_parsers": ["docling"],
            "default_normalization_enabled": False,
            "default_normalization_models": [],
            "default_ingestion_type": "general",
            "review_required": True,
            "per_document_overrides": {},
        },
        documents=[],
    )
    docs = []
    for document_id, filename in [("doc_reject", "reject.pdf"), ("doc_keep", "keep.pdf")]:
        source = source_root / "Admin_Dashboard" / "General" / "batches" / batch["batch_id"] / "documents" / document_id / "source" / filename
        source.parent.mkdir(parents=True)
        source.write_bytes(b"%PDF-1.4\n")
        docs.append(
            {
                "document_id": document_id,
                "original_filename": filename,
                "source_file_path": str(source),
                "file_type": "pdf",
                "file_size_bytes": source.stat().st_size,
                "effective_config": {
                    "parsers": ["docling"],
                    "normalization_enabled": False,
                    "normalization_models": [],
                    "review_required": True,
                    "ingestion_type": "general",
                },
            }
        )
    repo.delete_draft_batch(batch["batch_id"])
    repo.create_batch(
        batch_id="batch_reject_cleanup",
        name="Reject cleanup",
        description=None,
        config={
            "default_parsers": ["docling"],
            "default_normalization_enabled": False,
            "default_normalization_models": [],
            "default_ingestion_type": "general",
            "review_required": True,
            "per_document_overrides": {},
        },
        documents=docs,
    )
    for document in docs:
        variant = repo.create_parse_variant(document_id=document["document_id"], parser_type="docling")
        parsed_path = admin_files.variant_dir("batch_reject_cleanup", document["document_id"], variant["variant_id"]) / "parsed.md"
        raw_path = parsed_path.with_name("raw.md")
        parsed_path.write_text(f"# {document['original_filename']}", encoding="utf-8")
        raw_path.write_text("raw", encoding="utf-8")
        repo.update_parse_variant(variant["variant_id"], status="COMPLETE", parsed_md_path=str(parsed_path), raw_md_path=str(raw_path))
        repo.set_document_status(document["document_id"], DocumentStatus.REVIEW_PENDING.value)
    repo.create_or_update_review(
        document_id="doc_reject",
        selected_parse_variant_id=repo.get_document("doc_reject")["parse_variants"][0]["variant_id"],
        selected_norm_variant_id=None,
        base_md_path=repo.get_document("doc_reject")["parse_variants"][0]["parsed_md_path"],
        status="IN_PROGRESS",
    )
    edited_path = admin_files.review_dir("batch_reject_cleanup", "doc_reject") / "edited.md"
    edited_path.write_text("# Edited then rejected", encoding="utf-8")
    repo.update_review("doc_reject", edited_md_path=str(edited_path))

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    response = TestClient(app).post("/api/v1/documents/doc_reject/review/reject", json={"reason": "bad source"})

    assert response.status_code == 200
    rejected = response.json()["data"]["document"]
    assert rejected["status"] == DocumentStatus.REVIEW_REJECTED.value
    assert rejected["review"]["review_action"]["action"] == "rejected_deleted"
    assert rejected["review"]["review_action"]["edited"] is True
    assert rejected["review"]["review_action"]["cleanup_completed"] is True
    assert not (source_root / "Admin_Dashboard" / "General" / "batches" / "batch_reject_cleanup" / "documents" / "doc_reject").exists()
    assert not (generated_root / "Admin_Dashboard" / "batches" / "batch_reject_cleanup" / "documents" / "doc_reject").exists()
    assert (source_root / "Admin_Dashboard" / "General" / "batches" / "batch_reject_cleanup" / "documents" / "doc_keep").exists()
    assert (generated_root / "Admin_Dashboard" / "batches" / "batch_reject_cleanup" / "documents" / "doc_keep").exists()
    history = repo.get_batch("batch_reject_cleanup", include_documents=True)
    rejected_history = next(item for item in history["documents"] if item["document_id"] == "doc_reject")
    assert rejected_history["review"]["review_action"]["reason"] == "bad source"
