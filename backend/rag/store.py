"""
Vector Database Interface (ChromaDB)
------------------------------------
Handles persistence and retrieval of document embeddings using ChromaDB.
Implements a thread-safe singleton pattern for centralized database access.
"""

import chromadb
from chromadb.config import Settings
import os
import threading
from typing import List, Dict, Any, Optional
import logging

# Logger for store operations
logger = logging.getLogger("rag_chat_ipr.store")

class VectorStore:
    """
    Wrapper for ChromaDB operations.
    Manages collection lifecycle, document indexing, and semantic querying.
    """
    def __init__(self, persist_dir: str = "chroma_db"):
        self.persist_dir = persist_dir
        self.lock = threading.Lock()
        
        # Initialize ChromaDB Client
        self.client = chromadb.PersistentClient(
            path=persist_dir,
            settings=Settings(anonymized_telemetry=False)
        )
        
        # Get or create collection
        self.collection = self.client.get_or_create_collection(
            name="rag_documents",
            metadata={"hnsw:space": "cosine"} # Cosine similarity
        )
        logger.info(f"Vector Store initialized at {persist_dir}")

    def add_documents(self, texts: List[str], metadatas: List[Dict[str, Any]], ids: List[str], embeddings: List[List[float]]):
        """Adds processed chunks with embeddings to the store. Lock protects writes."""
        if not texts:
            return
            
        with self.lock:
            self.collection.add(
                documents=texts,
                metadatas=metadatas,
                ids=ids,
                embeddings=embeddings
            )
        logger.info(f"[STORE] Added {len(texts)} documents. Total in collection: {self.collection.count()}")

    def query(self, query_embeddings: List[List[float]], n_results: int = 5, where: Optional[Dict] = None) -> dict:
        """
        Queries the store using embeddings.
        Note: ChromaDB reads are thread-safe, so no lock needed for concurrent queries.
        This removes the read-side bottleneck that was serializing all operations.
        """
        return self.collection.query(
            query_embeddings=query_embeddings,
            n_results=n_results,
            where=where
        )

    def get_by_metadata(self, where: Dict[str, Any], limit: int = 5) -> dict:
        """
        Retrieves documents directly by metadata (filtering without embedding).
        Note: ChromaDB reads are thread-safe, so no lock needed.
        """
        return self.collection.get(
            where=where,
            limit=limit,
            include=['documents', 'metadatas']
        )

    def count(self) -> int:
        with self.lock:
            return self.collection.count()

    def get_all_files(self) -> List[str]:
        """Returns unique filenames currently indexed (Scalable Pagination)."""
        try:
            filenames = set()
            offset = 0
            limit = 500
            
            while True:
                with self.lock:
                    results = self.collection.get(
                        include=['metadatas'],
                        limit=limit,
                        offset=offset
                    )
                
                metas = results.get('metadatas', [])
                if not metas:
                    break
                    
                for meta in metas:
                    if meta and 'filename' in meta:
                        filenames.add(meta['filename'])
                
                if len(metas) < limit:
                    break
                offset += limit
                
            return list(filenames)
        except Exception as e:
            logger.error(f"[STORE] Failed to list documents: {e}")
            return []

    def delete_file(self, filename: str):
        """Selectively removes all chunks associated with a specific filename."""
        with self.lock:
            # ChromaDB supports filtering for deletion
            self.collection.delete(where={"filename": filename})
        logger.info(f"[STORE] Deleted all embeddings for file: {filename}")

    def clear_all(self):
        """Wipes the entire collection for a complete system reset."""
        with self.lock:
            try:
                # 1. Total Wipe: Delete the actual collection
                self.client.delete_collection("rag_documents")
                # 2. Reset: Recreate with same settings
                self.collection = self.client.create_collection(
                    name="rag_documents",
                    metadata={"hnsw:space": "cosine"}
                )
                logger.info("[STORE] Collection wiped and recreated successfully.")
            except Exception as e:
                logger.error(f"[STORE] Targeted wipe failed: {e}. Falling back to ID deletion.")
                # Fallback to slower ID-based deletion
                results = self.collection.get()
                ids = results.get('ids', [])
                if ids:
                    self.collection.delete(ids=ids)
        logger.info("[STORE] Global clear operation finished.")

# Singleton
_store = None

def get_vector_store() -> VectorStore:
    global _store
    if _store is None:
        _store = VectorStore()
    return _store
