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
from backend.config import get_config
from backend.ingestion.processor import DocumentProcessor
from backend.rag.store import get_vector_store
from backend.llm.client import OllamaClientWrapper
from backend.admin.events import event_hub
import asyncio

# Logger for tracking file system events and worker status
logger = logging.getLogger("rag_chat_ipr.watcher")

class NewDocumentHandler(FileSystemEventHandler):
    """Event handler that detects file creation/moves and adds paths to the processing queue."""
    def __init__(self, task_queue: queue.Queue):
        self.task_queue = task_queue
        self._pending: dict[str, float] = {}
        self._pending_lock = threading.Lock()
        self._debounce_seconds = 2.0
        
    def _should_process(self, path: str) -> bool:
        """Filter out directories, temporary files, and hidden files."""
        if os.path.isdir(path):
            return False

        try:
            relative = os.path.relpath(os.path.abspath(path), os.path.abspath("upload_docs"))
            if relative.split(os.sep, 1)[0].lower() == "admin_dashboard":
                return False
        except ValueError:
            pass
            
        filename = os.path.basename(path)
        # Skip hidden files, MS Office temp files, and common temp extensions
        if (filename.startswith(".") or 
            filename.startswith("~$") or 
            filename.endswith(".tmp") or 
            filename.endswith(".crdownload")):
            return False
            
        # Extension Whitelist (matched with processor.py)
        ext = os.path.splitext(filename)[1].lower()
        # [Docling + Fallbacks]
        allowed = [".pdf", ".md", ".txt", ".docx", ".pptx", ".xlsx", ".html"]
        return ext in allowed

    def _enqueue(self, path: str, reason: str) -> None:
        normalized = os.path.abspath(path)
        now = time.monotonic()
        with self._pending_lock:
            last_seen = self._pending.get(normalized, 0.0)
            if now - last_seen < self._debounce_seconds:
                logger.debug("Debounced duplicate %s event for %s", reason, os.path.basename(path))
                return
            self._pending[normalized] = now
        self.task_queue.put(normalized)

    def on_created(self, event):
        if self._should_process(event.src_path):
            logger.info(f"New file detected: {os.path.basename(event.src_path)}")
            self._enqueue(event.src_path, "created")

    def on_modified(self, event):
        if self._should_process(event.src_path):
            logger.info(f"File modification detected: {os.path.basename(event.src_path)}")
            self._enqueue(event.src_path, "modified")

    def on_moved(self, event):
        if self._should_process(event.dest_path):
            logger.info(f"File move/rename detected: {os.path.basename(event.dest_path)}")
            self._enqueue(event.dest_path, "moved")

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
        self._active_paths: set[str] = set()
        self._active_lock = threading.Lock()
        self.semaphore: asyncio.Semaphore | None = None

    def run(self):
        """Worker thread entry point: Starts an async loop."""
        logger.info("Ingestion Worker thread started (Async Mode).")
        asyncio.run(self.worker_loop())

    async def worker_loop(self):
        """Async loop that pulls tasks from the sync queue."""
        # Bind the semaphore to the event loop created by asyncio.run().
        self.semaphore = asyncio.Semaphore(4)
        while self.running:
            try:
                # Try to get a task without blocking the loop forever
                file_path = await asyncio.to_thread(self.task_queue.get, timeout=1)
                file_path = os.path.abspath(file_path)
                with self._active_lock:
                    if file_path in self._active_paths:
                        logger.debug("Skipping duplicate queued ingestion event for %s", file_path)
                        self.task_queue.task_done()
                        continue
                    self._active_paths.add(file_path)
                
                # Start processing as a nested task (not blocking other files)
                asyncio.create_task(self.guarded_process_file(file_path, self.semaphore))
            except queue.Empty:
                await asyncio.sleep(0.5) 
                continue
            except Exception as e:
                logger.error(f"Worker loop error: {e}")

    async def _wait_until_file_stable(self, file_path: str, attempts: int = 7, interval: float = 0.75) -> bool:
        last_size = -1
        stable_count = 0
        for _ in range(attempts):
            try:
                current_size = os.path.getsize(file_path)
            except OSError:
                await asyncio.sleep(interval)
                continue
            if current_size > 0 and current_size == last_size:
                stable_count += 1
                if stable_count >= 2:
                    return True
            else:
                stable_count = 0
            last_size = current_size
            await asyncio.sleep(interval)
        return False

    async def guarded_process_file(self, file_path: str, semaphore: asyncio.Semaphore):
        """Throttled file processing using a semaphore."""
        async with semaphore:
            try:
                ready = await self._wait_until_file_stable(file_path)
                if not ready:
                    logger.warning(f"File {file_path} did not reach a stable size. Proceeding with caution.")
                
                # 2. Process & Ingest
                await self.async_process_new_file(file_path)
            except Exception as e:
                logger.error(f"Failed to process {file_path}: {e}")
            finally:
                with self._active_lock:
                    self._active_paths.discard(os.path.abspath(file_path))
                self.task_queue.task_done()

    async def async_process_new_file(self, file_path: str):
        """Async wrapper for the document processor."""
        filename = os.path.basename(file_path)
        logger.info(f"Worker processing file in parallel: {filename}")
        
        try:
            cfg = get_config()
            mode = cfg.parsing_mode
            llm_normalize = cfg.ingest_llm_normalize

            # Sync extraction call run in a thread pool. Legacy uploads now use
            # the same parser mode and normalization flag configured for ingest.
            chunks = await asyncio.to_thread(
                self.processor.process_file,
                file_path,
                mode=mode,
                llm_normalize=llm_normalize,
            )
            
            if not chunks:
                logger.warning(f"No chunks extracted from {filename}")
                return
            
            # Async Embedding & Storing
            await self._embed_and_store(chunks)
            event_hub.publish({"type": "warehouse_update", "action": "index", "origin": "legacy", "filename": filename, "source": file_path})
            event_hub.publish({"type": "stats_update", "action": "index"})
            logger.info(f"✅ Parallel ingestion complete for {filename}")
            
        except Exception as e:
            logger.error(f"Async ingestion failed for {filename}: {e}")

    async def _embed_and_store(self, chunks):
        client = OllamaClientWrapper.get_embedding_client()
        model = OllamaClientWrapper.get_embedding_model_name()
        
        texts = [c['text'] for c in chunks]
        metadatas = [c['metadata'] for c in chunks]
        ids = [
            f"{c['metadata'].get('doc_id') or c['metadata']['source']}_{c['metadata']['chunk_index']}"
            for c in chunks
        ]
        
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
            raise RuntimeError(f"Mismatch in embedding count: expected {len(texts)}, got {len(all_embeddings)}")

        first_metadata = metadatas[0] if metadatas else {}
        source = first_metadata.get("source")
        filename = first_metadata.get("filename")
        if hasattr(self.vector_store, "delete_legacy_document") and (source or filename):
            self.vector_store.delete_legacy_document(filename=filename or os.path.basename(str(source)), source=source)
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
