import os
import sys
import pytest
import shutil
import time
from unittest.mock import MagicMock

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from backend.ingestion.processor import DocumentProcessor
from backend.rag.store import get_vector_store, VectorStore

TEST_DOC_DIR = "tests/test_docs"
TEST_DB_DIR = "tests/test_chroma"

def setup_module():
    os.makedirs(TEST_DOC_DIR, exist_ok=True)
    # Create a dummy PDF or text file logic
    # Since Docling needs real PDF, we might assume a dummy text for processor if we mock it, 
    # OR we create a simple text file and see if Docling handles it (it handles many formats).
    # For this test, we might verify VectorStore functionality primarily.
    
    if os.path.exists(TEST_DB_DIR):
        shutil.rmtree(TEST_DB_DIR)

def teardown_module():
    if os.path.exists(TEST_DOC_DIR):
        shutil.rmtree(TEST_DOC_DIR, ignore_errors=True)
    if os.path.exists(TEST_DB_DIR):
        # Retry logic or ignore errors for Windows file locking
        try:
            shutil.rmtree(TEST_DB_DIR)
        except PermissionError:
            time.sleep(0.5)
            shutil.rmtree(TEST_DB_DIR, ignore_errors=True)

def test_vector_store():
    """Verify ChromaDB wrapper operations."""
    store = VectorStore(persist_dir=TEST_DB_DIR)
    
    texts = ["Snippet one about apples", "Snippet two about oranges"]
    metadatas = [{"filename": "fruit.txt"}, {"filename": "fruit.txt"}]
    ids = ["1", "2"]
    embeddings = [[0.1, 0.2, 0.3], [0.9, 0.8, 0.3]]
    
    store.add_documents(texts, metadatas, ids, embeddings)
    
    assert store.count() == 2
    
    # Query
    res = store.query(query_embeddings=[[0.1, 0.2, 0.35]], n_results=1)
    assert len(res['documents'][0]) == 1
    assert "apples" in res['documents'][0][0]

    # Filter
    res_filter = store.query(query_embeddings=[[0.1, 0.2, 0.3]], where={"filename": "fruit.txt"})
    assert len(res_filter['documents'][0]) >= 1
    
    print("Phase 2: Vector Store Tests PASSED")

if __name__ == "__main__":
    setup_module()
    try:
        test_vector_store()
    finally:
        teardown_module()
