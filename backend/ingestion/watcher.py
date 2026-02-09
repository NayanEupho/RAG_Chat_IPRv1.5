"""
File System Watchdog and Ingestion Orchestrator
-----------------------------------------------
Monitors the 'upload_docs' directory for new files and manages a multi-threaded
ingestion worker pool to process them asynchronously.
"""

import os
import time
import threading
import logging
import queue
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from backend.ingestion.processor import DocumentProcessor
from backend.rag.store import get_vector_store
from backend.llm.client import OllamaClientWrapper
import asyncio

# Logger for tracking file system events and worker status
logger = logging.getLogger("rag_chat_ipr.watcher")

class NewDocumentHandler(FileSystemEventHandler):
    """Event handler that detects file creation and adds paths to the processing queue."""
    def __init__(self, task_queue: queue.Queue):
        self.task_queue = task_queue
        
    def on_created(self, event):
        if event.is_directory:
            return
        
        filename = os.path.basename(event.src_path)
        if filename.startswith("~$") or filename.startswith("."):
            return

        logger.info(f"File queued for ingestion: {filename}")
        self.task_queue.put(event.src_path)

class IngestionWorker:
    """
    Background worker that monitors a task queue and processes files in parallel.
    Utilizes an internal async loop for throttled, non-blocking ingestion.
    """
    def __init__(self, task_queue: queue.Queue):
        self.task_queue = task_queue
        self.processor = DocumentProcessor()
        self.vector_store = get_vector_store()
        self.running = True
        # Allow 4 documents to be processed in parallel
        self.semaphore = asyncio.Semaphore(4)

    def run(self):
        """Worker thread entry point: Starts an async loop."""
        logger.info("Ingestion Worker thread started (Async Mode).")
        asyncio.run(self.worker_loop())

    async def worker_loop(self):
        """Async loop that pulls tasks from the sync queue."""
        while self.running:
            try:
                # Try to get a task without blocking the loop forever
                file_path = await asyncio.to_thread(self.task_queue.get, timeout=1)
                
                # Start processing as a nested task (not blocking other files)
                asyncio.create_task(self.guarded_process_file(file_path))
            except queue.Empty:
                await asyncio.sleep(0.5) 
                continue
            except Exception as e:
                logger.error(f"Worker loop error: {e}")

    async def guarded_process_file(self, file_path: str):
        """Throttled file processing using a semaphore."""
        async with self.semaphore:
            try:
                # 1. Debounce / Readiness Check
                max_retries = 7
                ready = False
                for _ in range(max_retries):
                    try:
                        with open(file_path, "ab"):
                            ready = True
                            break
                    except IOError:
                        await asyncio.sleep(1.0)
                
                if not ready:
                    logger.warning(f"File {file_path} still locked. Proceeding with caution.")
                
                # 2. Process & Ingest
                await self.async_process_new_file(file_path)
            except Exception as e:
                logger.error(f"Failed to process {file_path}: {e}")
            finally:
                self.task_queue.task_done()

    async def async_process_new_file(self, file_path: str):
        """Async wrapper for the document processor."""
        filename = os.path.basename(file_path)
        logger.info(f"Worker processing file in parallel: {filename}")
        
        try:
            # Sync extraction call run in thread pool
            chunks = await asyncio.to_thread(self.processor.process_file, file_path)
            
            if not chunks:
                logger.warning(f"No chunks extracted from {filename}")
                return
            
            # Async Embedding & Storing
            await self._embed_and_store(chunks)
            logger.info(f"✅ Parallel ingestion complete for {filename}")
            
        except Exception as e:
            logger.error(f"Async ingestion failed for {filename}: {e}")

    async def _embed_and_store(self, chunks):
        client = OllamaClientWrapper.get_embedding_client()
        model = OllamaClientWrapper.get_embedding_model_name()
        
        texts = [c['text'] for c in chunks]
        metadatas = [c['metadata'] for c in chunks]
        ids = [f"{c['metadata']['filename']}_{c['metadata']['chunk_index']}" for c in chunks]
        
        # Batch embedding
        BATCH_SIZE = 50
        all_embeddings = []
        
        for i in range(0, len(texts), BATCH_SIZE):
            batch_texts = texts[i:i + BATCH_SIZE]
            response = await client.embed(model=model, input=batch_texts)
            batch_embeddings = response.get('embeddings', [])
            all_embeddings.extend(batch_embeddings)
        
        if len(all_embeddings) != len(texts):
            logger.error(f"Mismatch in embedding count: expected {len(texts)}, got {len(all_embeddings)}")
            return

        self.vector_store.add_documents(texts, metadatas, ids, all_embeddings)


class WatchdogService:
    """
    High-level service that manages the lifecycle of the directory observer
    and its associated ingestion worker thread.
    """
    def __init__(self, watch_dir: str = "upload_docs"):
        self.watch_dir = os.path.abspath(watch_dir)
        if not os.path.exists(self.watch_dir):
            os.makedirs(self.watch_dir)
            
        self.task_queue = queue.Queue()
        self.observer = Observer()
        self.handler = NewDocumentHandler(self.task_queue)
        self.worker = IngestionWorker(self.task_queue)

    def start(self):
        logger.info(f"Starting Watchdog on {self.watch_dir}")
        self.observer.schedule(self.handler, self.watch_dir, recursive=True)
        
        # Start Observer Thread
        self.observer_thread = threading.Thread(target=self.observer.start)
        self.observer_thread.daemon = True
        self.observer_thread.start()

        # Start Worker Thread
        self.worker_thread = threading.Thread(target=self.worker.run)
        self.worker_thread.daemon = True
        self.worker_thread.start()

    def stop(self):
        self.worker.running = False
        self.observer.stop()
        self.observer.join()
        self.worker_thread.join(timeout=5)
