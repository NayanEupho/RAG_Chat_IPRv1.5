import os
import queue
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from backend.ingestion.watcher import IngestionWorker, NewDocumentHandler


class _FakeVectorStore:
    def __init__(self):
        self.calls = []

    def delete_legacy_document(self, *, filename, source):
        self.calls.append(("delete", filename, source))

    def add_documents(self, texts, metadatas, ids, embeddings):
        self.calls.append(("add", texts, metadatas, ids, embeddings))


class _FakeEmbeddingClient:
    def __init__(self, embeddings):
        self.embeddings = embeddings

    async def embed(self, *, model, input):
        return {"embeddings": self.embeddings[: len(input)]}


@pytest.mark.asyncio
async def test_watcher_respects_auto_mode_and_normalization_config(tmp_path):
    doc = tmp_path / "upload_docs" / "General" / "sample.pdf"
    doc.parent.mkdir(parents=True)
    doc.write_text("placeholder", encoding="utf-8")

    with patch("backend.ingestion.watcher.get_vector_store", return_value=MagicMock()):
        worker = IngestionWorker(queue.Queue())
    worker.processor.process_file = MagicMock(return_value=[
        {"text": "chunk", "metadata": {"doc_id": "doc", "source": str(doc), "chunk_index": 0}}
    ])
    worker._embed_and_store = AsyncMock()

    with patch(
        "backend.ingestion.watcher.get_config",
        return_value=SimpleNamespace(parsing_mode="auto", ingest_llm_normalize=False),
    ):
        await worker.async_process_new_file(str(doc))

    worker.processor.process_file.assert_called_once_with(
        str(doc),
        mode="auto",
        llm_normalize=False,
    )


@pytest.mark.asyncio
async def test_watcher_preserves_explicit_configured_parser_mode(tmp_path):
    doc = tmp_path / "upload_docs" / "General" / "sample.pdf"
    doc.parent.mkdir(parents=True)
    doc.write_text("placeholder", encoding="utf-8")

    with patch("backend.ingestion.watcher.get_vector_store", return_value=MagicMock()):
        worker = IngestionWorker(queue.Queue())
    worker.processor.process_file = MagicMock(return_value=[
        {"text": "chunk", "metadata": {"doc_id": "doc", "source": str(doc), "chunk_index": 0}}
    ])
    worker._embed_and_store = AsyncMock()

    with patch(
        "backend.ingestion.watcher.get_config",
        return_value=SimpleNamespace(parsing_mode="pymupdf4llm", ingest_llm_normalize=False),
    ):
        await worker.async_process_new_file(str(doc))

    worker.processor.process_file.assert_called_once_with(
        str(doc),
        mode="pymupdf4llm",
        llm_normalize=False,
    )


@pytest.mark.asyncio
async def test_watcher_replaces_existing_legacy_chunks_before_add(tmp_path):
    doc = tmp_path / "upload_docs" / "General" / "sample.pdf"
    doc.parent.mkdir(parents=True)
    doc.write_text("placeholder", encoding="utf-8")
    store = _FakeVectorStore()

    with patch("backend.ingestion.watcher.get_vector_store", return_value=store):
        worker = IngestionWorker(queue.Queue())

    chunks = [
        {
            "text": "chunk one",
            "metadata": {"filename": "sample.pdf", "source": str(doc), "chunk_index": 0},
        },
        {
            "text": "chunk two",
            "metadata": {"filename": "sample.pdf", "source": str(doc), "chunk_index": 1},
        },
    ]
    client = _FakeEmbeddingClient([[0.1, 0.2], [0.3, 0.4]])

    with patch("backend.ingestion.watcher.OllamaClientWrapper.get_embedding_client", return_value=client), patch(
        "backend.ingestion.watcher.OllamaClientWrapper.get_embedding_model_name",
        return_value="embed-model",
    ):
        await worker._embed_and_store(chunks)

    assert store.calls[0] == ("delete", "sample.pdf", str(doc))
    assert store.calls[1][0] == "add"
    assert store.calls[1][1] == ["chunk one", "chunk two"]


@pytest.mark.asyncio
async def test_watcher_fails_when_embedding_count_mismatches(tmp_path):
    doc = tmp_path / "upload_docs" / "General" / "sample.pdf"
    doc.parent.mkdir(parents=True)
    doc.write_text("placeholder", encoding="utf-8")
    store = _FakeVectorStore()

    with patch("backend.ingestion.watcher.get_vector_store", return_value=store):
        worker = IngestionWorker(queue.Queue())

    chunks = [
        {
            "text": "chunk one",
            "metadata": {"filename": "sample.pdf", "source": str(doc), "chunk_index": 0},
        },
        {
            "text": "chunk two",
            "metadata": {"filename": "sample.pdf", "source": str(doc), "chunk_index": 1},
        },
    ]
    client = _FakeEmbeddingClient([[0.1, 0.2]])

    with patch("backend.ingestion.watcher.OllamaClientWrapper.get_embedding_client", return_value=client), patch(
        "backend.ingestion.watcher.OllamaClientWrapper.get_embedding_model_name",
        return_value="embed-model",
    ):
        with pytest.raises(RuntimeError, match="Mismatch in embedding count"):
            await worker._embed_and_store(chunks)

    assert store.calls == []


def test_watcher_handler_debounces_duplicate_modified_events(tmp_path):
    task_queue = queue.Queue()
    handler = NewDocumentHandler(task_queue)
    doc = tmp_path / "upload_docs" / "General" / "sample.pdf"
    doc.parent.mkdir(parents=True)
    doc.write_bytes(b"%PDF-1.4\n")
    event = SimpleNamespace(src_path=str(doc))

    handler.on_modified(event)
    handler.on_modified(event)
    handler.on_modified(event)

    assert task_queue.qsize() == 1


@pytest.mark.asyncio
async def test_watcher_waits_for_stable_non_empty_file(tmp_path, monkeypatch):
    doc = tmp_path / "sample.pdf"
    doc.write_bytes(b"%PDF-1.4\n")
    with patch("backend.ingestion.watcher.get_vector_store", return_value=MagicMock()):
        worker = IngestionWorker(queue.Queue())

    async def fake_sleep(_seconds):
        return None

    monkeypatch.setattr("backend.ingestion.watcher.asyncio.sleep", fake_sleep)

    assert await worker._wait_until_file_stable(str(doc), attempts=4, interval=0) is True
