import os
import queue
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from backend.ingestion.watcher import IngestionWorker


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
async def test_watcher_defaults_auto_mode_to_docling_with_normalization(tmp_path):
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
        mode="docling",
        llm_normalize=True,
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
