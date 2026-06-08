import os
import queue
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from backend.ingestion.watcher import IngestionWorker


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
