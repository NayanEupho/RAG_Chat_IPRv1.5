import chromadb
from chromadb.config import Settings
import os
import threading
from typing import List, Dict, Any, Optional
import logging

logger = logging.getLogger("rag_chat_ipr.store")

class VectorStore:
    def __init__(self, persist_dir: str = "chroma_db"):
        self.persist_dir = persist_dir
        self.lock = threading.Lock()
        
        # Initialize ChromaDB Client
        self.client = chromadb.PersistentClient(path=persist_dir)
        
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
        """Returns unique filenames currently indexed."""
        try:
            with self.lock:
                results = self.collection.get(include=['metadatas'])
            filenames = set()
            for meta in results['metadatas']:
                if meta and 'filename' in meta:
                    filenames.add(meta['filename'])
            return list(filenames)
        except Exception:
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
            # We delete by empty filter or just delete all IDs if needed, 
            # but PersistentClient.delete_collection is cleaner if we want a total wipe.
            # However, keeping the collection object is better for active sessions.
            # We get all IDs and delete them.
            results = self.collection.get()
            ids = results.get('ids', [])
            if ids:
                self.collection.delete(ids=ids)
        logger.info("[STORE] Collection cleared. Vector database is now empty.")

# Singleton
_store = None

def get_vector_store() -> VectorStore:
    global _store
    if _store is None:
        _store = VectorStore()
    return _store
