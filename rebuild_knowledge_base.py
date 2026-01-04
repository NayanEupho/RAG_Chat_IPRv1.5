import os
import shutil
import logging
import asyncio
import httpx
import time
from typing import List, Dict, Any

# Configure structured logging for the "Command Center" feel
logging.basicConfig(
    level=logging.INFO,
    format='%(message)s' # Clean output for terminal wizard
)
logger = logging.getLogger("rebuild_kb")

async def get_ollama_config():
    """Attempts to auto-detect Ollama config from the running API server."""
    print("🔍 [1/4] Detecting active system configuration...")
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get("http://localhost:8000/api/status", timeout=2)
            if resp.status_code == 200:
                config = resp.json().get("config")
                main = config.get("main_model", {})
                embed = config.get("embedding_model", {})
                print(f"   ✅ Auto-detected: {main.get('model_name')} (Chat) & {embed.get('model_name')} (Embed)")
                return {
                    "RAG_MAIN_HOST": main.get("host"),
                    "RAG_MAIN_MODEL": main.get("model_name"),
                    "RAG_EMBED_HOST": embed.get("host"),
                    "RAG_EMBED_MODEL": embed.get("model_name")
                }
    except Exception:
        print("   ⚠️  API server not reached. Falling back to environment variables or defaults.")
    
    return {
        "RAG_MAIN_HOST": os.getenv("RAG_MAIN_HOST", "http://localhost:11434"),
        "RAG_MAIN_MODEL": os.getenv("RAG_MAIN_MODEL", "llama3"),
        "RAG_EMBED_HOST": os.getenv("RAG_EMBED_HOST", "http://localhost:11434"),
        "RAG_EMBED_MODEL": os.getenv("RAG_EMBED_MODEL", "nomic-embed-text")
    }

def hard_reset_db(db_path: str = "chroma_db"):
    """Physically deletes the database directory for a fresh start."""
    print(f"🧹 [2/4] Initializing Hard Reset on '{db_path}'...")
    if os.path.exists(db_path):
        try:
            shutil.rmtree(db_path)
            print(f"   ✅ Database directory purged. System is now in 'Clean Slate' mode.")
        except Exception as e:
            print(f"   ❌ Error during purge: {e}. Please ensure no other process is using the DB.")
            return False
    else:
        print(f"   ℹ️  Database directory not found. Starting fresh.")
    return True

async def rebuild():
    start_time = time.time()
    print("\n" + "="*60)
    print("🚀 PRODUCTION-GRADE KNOWLEDGE BASE REBUILD WIZARD")
    print("="*60 + "\n")

    # 1. Config Detection
    config = await get_ollama_config()
    for k, v in config.items():
        os.environ[k] = v

    # 2. Hard Reset
    if not hard_reset_db():
        return

    # 3. Deferred Imports (to ensure singleton picks up new env/clean state)
    print("📄 [3/4] Preparing Ingestion Pipeline...")
    from backend.rag.store import get_vector_store
    from backend.ingestion.processor import DocumentProcessor
    from backend.llm.client import OllamaClientWrapper

    store = get_vector_store()
    processor = DocumentProcessor()
    embed_client = OllamaClientWrapper.get_embedding_client()
    embed_model = os.environ["RAG_EMBED_MODEL"]

    upload_dir = "upload_docs"
    if not os.path.exists(upload_dir):
        print(f"   ❌ Error: Upload directory '{upload_dir}' missing.")
        return

    files = [f for f in os.listdir(upload_dir) if os.path.isfile(os.path.join(upload_dir, f))]
    if not files:
        print(f"   ℹ️  Nothing to index. Add files to '{upload_dir}' first.")
        return

    print(f"   ✅ Found {len(files)} documents. Starting Batch Ingestion...\n")

    # 4. Processing Loop
    print(f"{'FILE':<30} | {'CHUNKS':<8} | {'STATUS':<15}")
    print("-" * 60)

    total_chunks = 0
    for filename in files:
        file_path = os.path.join(upload_dir, filename)
        
        try:
            # Step A: Parse
            chunks = processor.process_file(file_path)
            if not chunks:
                 print(f"{filename[:30]:<30} | {'0':<8} | ⚠️  Skipped")
                 continue
            
            # Step B: Embed & Store
            texts = [c['text'] for c in chunks]
            metadatas = [c['metadata'] for c in chunks]
            # Use original_filename if available in metadata to handle spaces correctly
            display_name = chunks[0]['metadata'].get('filename', filename)
            ids = [f"{display_name}_{i}" for i in range(len(chunks))]
            
            response = await embed_client.embed(model=embed_model, input=texts)
            embeddings = response['embeddings']
            
            store.add_documents(texts, metadatas, ids, embeddings)
            
            print(f"{filename[:30]:<30} | {len(chunks):<8} | ✅ Indexed")
            total_chunks += len(chunks)
            
        except Exception as e:
            print(f"{filename[:30]:<30} | {'-':<8} | ❌ Error: {str(e)[:10]}...")

    duration = round(time.time() - start_time, 2)
    print("\n" + "="*60)
    print(f"✅ [4/4] REBUILD COMPLETE!")
    print(f"   ⏱️  Total Duration: {duration}s")
    print(f"   📚 Total Chunks:   {total_chunks}")
    print(f"   🏠 Final Count:    {store.count()} embeddings in DB")
    print("="*60 + "\n")

if __name__ == "__main__":
    asyncio.run(rebuild())
