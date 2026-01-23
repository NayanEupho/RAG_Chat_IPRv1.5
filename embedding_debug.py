import os
import argparse
import asyncio
import logging
import time
import httpx
import sys
import glob
from typing import List, Dict, Any, Optional
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()

# --- Configuration & Logging ---
logging.basicConfig(
    level=logging.INFO,
    format='%(message)s' # Clean terminal output
)
logger = logging.getLogger("embedding_debug")

# Suppress noisy logs
logging.getLogger("httpx").setLevel(logging.WARNING)

def print_banner(title: str, subtitle: Optional[str] = None):
    print("\n" + "="*70)
    print(f"🚀 {title.upper()}")
    if subtitle:
        print(f"   {subtitle}")
    print("="*70 + "\n")

# --- Helper Logic ---

async def get_system_config():
    """Detects configuration from the API server or environment."""
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get("http://localhost:8000/api/status", timeout=2)
            if resp.status_code == 200:
                config_data = resp.json().get("config", {})
                main = config_data.get("main_model", {})
                embed = config_data.get("embedding_model", {})
                return {
                    "RAG_MAIN_HOST": main.get("host"),
                    "RAG_MAIN_MODEL": main.get("model_name"),
                    "RAG_EMBED_HOST": embed.get("host"),
                    "RAG_EMBED_MODEL": embed.get("model_name")
                }
    except Exception:
        pass
    
    # Final Fallback: Environment Variables (e.g. from .env)
    config = {
        "RAG_MAIN_HOST": os.getenv("RAG_MAIN_HOST"),
        "RAG_MAIN_MODEL": os.getenv("RAG_MAIN_MODEL"),
        "RAG_EMBED_HOST": os.getenv("RAG_EMBED_HOST"),
        "RAG_EMBED_MODEL": os.getenv("RAG_EMBED_MODEL")
    }

    # Strict Validation: Root Cause Fix
    # We never want to "guess" the model/host. Failure is better than wrong data.
    missing = [k for k, v in config.items() if not v]
    if missing:
        print("\n" + "!"*70)
        print("❌ CONFIGURATION ERROR: Missing required environment variables.")
        print(f"   Missing: {', '.join(missing)}")
        print("\n   ACTION REQUIRED:")
        print("   1. Check your .env file.")
        print("   2. Ensure the variables above are defined.")
        print("   3. Or manually export them: export RAG_EMBED_HOST=...")
        print("!"*70 + "\n")
        sys.exit(1)

    return config

async def process_and_store_file(file_path: str, store, processor, embed_client, model):
    """Robust 'from scratch' processing for a single file."""
    filename = os.path.basename(file_path)
    
    # 1. Parsing & Chunking (High-Fidelity)
    chunks = processor.process_file(file_path)
    if not chunks:
        print(f"   ⚠️  Skipped {filename}: No content extracted.")
        return 0
    
    # 2. Embedding
    texts = [c['text'] for c in chunks]
    metadatas = [c['metadata'] for c in chunks]
    # Standardized ID: filename_chunkIndex (Matches watcher.py)
    ids = [f"{m['filename']}_{m['chunk_index']}" for m in metadatas]
    
    # Batch embedding (handle large files)
    all_embeddings = []
    BATCH_SIZE = 50
    for i in range(0, len(texts), BATCH_SIZE):
        batch_texts = texts[i:i + BATCH_SIZE]
        response = await embed_client.embed(model=model, input=batch_texts)
        all_embeddings.extend(response.get('embeddings', []))
    
    if len(all_embeddings) != len(texts):
        raise ValueError(f"Embedding mismatch for {filename}")

    # 3. Storage
    store.add_documents(texts, metadatas, ids, all_embeddings)
    return len(chunks)

# --- CLI Command Implementations ---

async def cmd_rebuild(args):
    print_banner("System-Wide Knowledge Base Rebuild", "Clearing database and re-indexing all documents from scratch.")
    
    # Detect Config First
    config_vars = await get_system_config()
    for k, v in config_vars.items():
        os.environ[k] = v
        
    # Deferred Imports for Singletons
    from backend.rag.store import get_vector_store
    from backend.ingestion.processor import DocumentProcessor
    from backend.llm.client import OllamaClientWrapper
    
    store = get_vector_store()
    processor = DocumentProcessor()
    embed_client = OllamaClientWrapper.get_embedding_client()
    embed_model = os.environ["RAG_EMBED_MODEL"]
    
    # 1. Total Wipe
    print("🧹 [1/3] Clearing Vector Store...")
    store.clear_all()
    print("   ✅ Slate cleaned.")
    
    # 2. Discovery
    upload_dir = "upload_docs"
    files = []
    for f in os.listdir(upload_dir):
        # Ignore hidden files (.gitkeep, .DS_Store, etc.) and temp files
        if f.startswith(".") or f.startswith("~$"):
            continue
        full_path = os.path.join(upload_dir, f)
        if os.path.isfile(full_path):
            files.append(full_path)
            
    if not files:
        print(f"   ℹ️  No files found in '{upload_dir}'.")
        return

    print(f"📂 [2/3] Re-indexing {len(files)} documents from scratch...")
    print(f"{'FILE':<40} | {'CHUNKS':<8} | {'STATUS':<10}")
    print("-" * 65)
    
    start_time = time.time()
    total_chunks = 0
    for f_path in files:
        fname = os.path.basename(f_path)
        try:
            count = await process_and_store_file(f_path, store, processor, embed_client, embed_model)
            print(f"{fname[:40]:<40} | {count:<8} | ✅ Done")
            total_chunks += count
        except Exception as e:
            print(f"{fname[:40]:<40} | {'-':<8} | ❌ Error")
            logger.error(f"Error processing {fname}: {e}")

    # 3. Finalization
    duration = round(time.time() - start_time, 2)
    print("\n✨ [3/3] REBUILD COMPLETE!")
    print(f"   ⏱️  Time Taken:  {duration}s")
    print(f"   📚 Total Chunks: {total_chunks}")
    print(f"   🏠 Final Count:  {store.count()} in DB")

async def cmd_reindex(args):
    if not args.files:
        print("❌ Error: Please specify one or more files to re-index.")
        return

    print_banner("Selective Document Re-indexing", f"Refreshing {len(args.files)} document(s) from scratch.")
    
    # Detect Config
    config_vars = await get_system_config()
    for k, v in config_vars.items():
        os.environ[k] = v
        
    from backend.rag.store import get_vector_store
    from backend.ingestion.processor import DocumentProcessor
    from backend.llm.client import OllamaClientWrapper
    
    store = get_vector_store()
    processor = DocumentProcessor()
    embed_client = OllamaClientWrapper.get_embedding_client()
    embed_model = os.environ["RAG_EMBED_MODEL"]
    
    # Expand globs/paths
    target_files = []
    for f_arg in args.files:
        # Strip potential '@' used in CLI queries
        clean_path = f_arg.lstrip('@')
        # Check in upload_docs if relative
        if not os.path.exists(clean_path):
            alt_path = os.path.join("upload_docs", clean_path)
            if os.path.exists(alt_path):
                clean_path = alt_path
        
        matches = glob.glob(clean_path)
        if matches:
            target_files.extend(matches)
        else:
            print(f"   ⚠️  Warning: File not found: {f_arg}")

    if not target_files:
        print("❌ Error: No valid files found to re-index.")
        return

    print(f"{'FILE':<40} | {'CHUNKS':<8} | {'STATUS':<10}")
    print("-" * 65)
    
    total_reindexed = 0
    for f_path in target_files:
        fname = os.path.basename(f_path)
        try:
            # Atomic Deletion
            store.delete_file(fname)
            
            # Fresh Re-construction
            count = await process_and_store_file(f_path, store, processor, embed_client, embed_model)
            print(f"{fname[:40]:<40} | {count:<8} | ✅ Refreshed")
            total_reindexed += count
        except Exception as e:
            print(f"{fname[:40]:<40} | {'-':<8} | ❌ Error")
            logger.error(f"Error re-indexing {fname}: {e}")

    print(f"\n✅ Selective re-indexing complete. {len(target_files)} files processed.")

async def cmd_list(args):
    from backend.rag.store import get_vector_store
    store = get_vector_store()
    
    print_banner("Knowledge Base Inventory")
    
    try:
        total = store.count()
        print(f"📊 Total Embeddings in DB: {total}\n")
        
        if total == 0:
            print("   ⚠️  Knowledge Base is currently empty.")
            return

        # Fetch unique stats
        results = store.collection.get(include=['metadatas'])
        stats = {}
        for m in results['metadatas']:
            fname = m.get('filename', 'Unknown')
            stats[fname] = stats.get(fname, 0) + 1
            
        print(f"{'FILENAME':<45} | {'CHUNKS':<8}")
        print("-" * 55)
        for fname, count in sorted(stats.items()):
            print(f"{fname[:45]:<45} | {count:<8}")
            
    except Exception as e:
        print(f"❌ Error fetching inventory: {e}")

async def cmd_probe(args):
    if not args.query:
        print("❌ Error: Please provide a search query.")
        return

    from backend.rag.store import get_vector_store
    from backend.llm.client import OllamaClientWrapper
    
    # Detect Config for prompt model name
    config_vars = await get_system_config()
    for k, v in config_vars.items():
        os.environ[k] = v

    store = get_vector_store()
    embed_client = OllamaClientWrapper.get_embedding_client()
    embed_model = os.environ["RAG_EMBED_MODEL"]
    
    print_banner(f"Semantic Probe: '{args.query}'", f"Testing search results using {embed_model}")

    try:
        # 1. Embed Query
        resp = await embed_client.embed(model=embed_model, input=[args.query])
        emb = resp['embeddings'][0]
        
        # 2. Query
        res = store.query(query_embeddings=[emb], n_results=5)
        
        docs = res.get('documents', [[]])[0]
        metas = res.get('metadatas', [[]])[0]
        dists = res.get('distances', [[]])[0]
        
        if not docs:
            print("   ⚠️  No semantic matches found.")
            return

        for i, (doc, meta, dist) in enumerate(zip(docs, metas, dists)):
            print(f"📍 MATCH #{i+1} (D: {dist:.4f})")
            print(f"   📄 Source: {meta.get('filename')} [Chunk {meta.get('chunk_index')}]")
            if 'section_path' in meta:
                print(f"   🗺️  Path:   {meta['section_path']}")
            print("-" * 40)
            preview = doc.strip().replace('\n', ' ')[:150]
            print(f"   \"{preview}...\"\n")
            
    except Exception as e:
        print(f"❌ Error during probe: {e}")

# --- Main Entry Point ---

def main():
    parser = argparse.ArgumentParser(description="Unified IPR RAG Embedding Manager & Debugger")
    subparsers = parser.add_subparsers(dest="command", help="Command to execute")
    
    # Command: rebuild
    subparsers.add_parser("rebuild", help="Wipe database and re-index all documents from scratch")
    
    # Command: reindex
    reindex_parser = subparsers.add_parser("reindex", help="Selective re-indexing for specific files")
    reindex_parser.add_argument("files", nargs="+", help="One or more filenames or patterns (e.g. '@file.pdf')")
    
    # Command: list
    subparsers.add_parser("list", help="List all indexed files and metrics")
    
    # Command: probe
    probe_parser = subparsers.add_parser("probe", help="Perform a raw semantic search to test retrieval")
    probe_parser.add_argument("query", type=str, help="The search query to test")
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return

    # Dispatch to async handlers
    try:
        if args.command == "rebuild":
            asyncio.run(cmd_rebuild(args))
        elif args.command == "reindex":
            asyncio.run(cmd_reindex(args))
        elif args.command == "list":
            asyncio.run(cmd_list(args))
        elif args.command == "probe":
            asyncio.run(cmd_probe(args))
    except KeyboardInterrupt:
        print("\n\nOperation cancelled by user.")
    except Exception as e:
        print(f"\n❌ FATAL ERROR: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
