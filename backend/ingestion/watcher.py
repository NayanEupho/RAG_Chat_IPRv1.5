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

logger = logging.getLogger("rag_chat_ipr.watcher")

class NewDocumentHandler(FileSystemEventHandler):
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
    def __init__(self, task_queue: queue.Queue):
        self.task_queue = task_queue
        self.processor = DocumentProcessor()
        self.vector_store = get_vector_store()
        self.running = True

    def run(self):
        logger.info("Ingestion Worker thread started.")
        while self.running:
            try:
                file_path = self.task_queue.get(timeout=1)
                
                # Debounce: Wait for file to be fully written
                time.sleep(1.5) 
                
                self.process_new_file(file_path)
                self.task_queue.task_done()
            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"Worker error: {e}")

    def process_new_file(self, file_path: str):
        filename = os.path.basename(file_path)
        logger.info(f"Worker processing file: {filename}")
        
        # 1. Processing (Docling)
        chunks = self.processor.process_file(file_path)
        if not chunks:
            logger.warning(f"No chunks extracted from {filename}")
            return

        # 2. Embedding & Indexing
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(self._embed_and_store(chunks))
                logger.info(f"Finished ingesting {filename}")
            finally:
                loop.close()
        except Exception as e:
            logger.error(f"Error ingesting {filename}: {e}")

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
        self.observer.schedule(self.handler, self.watch_dir, recursive=False)
        
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
