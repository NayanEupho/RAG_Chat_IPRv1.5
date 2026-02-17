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
    print(f"[RUN] {title.upper()}")
    if subtitle:
        print(f"      {subtitle}")
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
                    "RAG_EMBED_MODEL": embed.get("model_name"),
                    "RAG_WORKFLOW": config_data.get("rag_workflow", "fused"),
                    "INGEST_FORCE_CPU": config_data.get("ingest_force_cpu", False)
                }
    except Exception:
        pass
    
    # Final Fallback: Environment Variables (e.g. from .env)
    config = {
        "RAG_MAIN_HOST": os.getenv("RAG_MAIN_HOST"),
        "RAG_MAIN_MODEL": os.getenv("RAG_MAIN_MODEL"),
        "RAG_EMBED_HOST": os.getenv("RAG_EMBED_HOST"),
        "RAG_EMBED_MODEL": os.getenv("RAG_EMBED_MODEL"),
        "RAG_WORKFLOW": os.getenv("RAG_WORKFLOW", "fused"),
        "INGEST_FORCE_CPU": os.getenv("INGEST_FORCE_CPU", "false").lower() == "true"
    }

    # Strict Validation: Root Cause Fix
    # Only check for required string configurations
    required_keys = ["RAG_MAIN_HOST", "RAG_MAIN_MODEL", "RAG_EMBED_HOST", "RAG_EMBED_MODEL"]
    missing = [k for k in required_keys if not config.get(k)]
    if missing:
        print("\n" + "!"*70)
        print("ERROR: Missing required environment variables.")
        print(f"       Missing: {', '.join(missing)}")
        print(f"       Current Config State: {config}")
        print("\n   ACTION REQUIRED:")
        print("   1. Check your .env file.")
        print("   2. Ensure the variables above are defined.")
        print("   3. Or manually export them: export RAG_EMBED_HOST=...")
        print("!"*70 + "\n")
        sys.exit(1)

    return config

async def process_and_store_file(file_path: str, store, processor, embed_client, model, dry_run=False, mode="auto"):
    """Robust 'from scratch' processing for a single file."""
    filename = os.path.basename(file_path)
    
    # 1. Detect doc_type based on path
    normalized_path = file_path.replace('\\', '/')
    is_qna = '/QnA/' in normalized_path or '\\QnA\\' in file_path
    
    # 2. Parsing & Chunking (High-Fidelity)
    # The DocumentProcessor now handles:
    # 1. Extraction (Docling/PyMuPDF)
    # 2. Debug MD saving (Fixes missing QnA MD issue)
    # 3. Strategy routing (QnA vs Hierarchical based on folder)
    try:
        chunks = processor.process_file(file_path, mode=mode)
    except Exception as e:
        logger.error(f"   [ERR] Error processing {filename}: {e}")
        return 0

    if not chunks:
        print(f"   [WARN] Skipped {filename}: No content extracted.")
        return 0
    
    if dry_run:
        print(f"\n   [SCAN] DRY RUN: Prepared {len(chunks)} chunks for {filename}")
        return len(chunks)

    # ... (Embedding logic unchanged) ...
    texts = [c['text'] for c in chunks]
    metadatas = [c['metadata'] for c in chunks]
    ids = [f"{m['filename']}_{m['chunk_index']}" for m in metadatas]
    
    all_embeddings = []
    BATCH_SIZE = 50
    for i in range(0, len(texts), BATCH_SIZE):
        batch_texts = texts[i:i + BATCH_SIZE]
        response = await embed_client.embed(model=model, input=batch_texts)
        all_embeddings.extend(response.get('embeddings', []))
    
    store.add_documents(texts, metadatas, ids, all_embeddings)
    return len(chunks)

# --- CLI Command Implementations ---

def determine_mode(args):
    """Parses CLI flags to strict mode string."""
    if hasattr(args, 'pymupdf4llm') and args.pymupdf4llm:
        return "pymupdf4llm"
    if hasattr(args, 'docling_vision') and args.docling_vision:
        return "docling_vision"
    return "auto"

async def cmd_rebuild(args):
    mode = determine_mode(args)
    print_banner("System-Wide Knowledge Base Rebuild", f"Mode: {mode.upper()}. Clearing database and re-indexing...")
    
    # Detect Config
    config_vars = await get_system_config()
    for k, v in config_vars.items():
        if v is not None:
            os.environ[k] = str(v)

    from backend.rag.store import get_vector_store
    from backend.ingestion.processor import DocumentProcessor
    from backend.llm.client import OllamaClientWrapper
    
    store = get_vector_store()
    processor = DocumentProcessor() # Mode is passed to process_file, not init
    embed_client = OllamaClientWrapper.get_embedding_client()
    embed_model = os.environ["RAG_EMBED_MODEL"]

    print("[INFO] Clearing existing vector store...")
    store.clear()
    print("[OK] Vector store cleared.")

    print("[INFO] Discovering documents in 'upload_docs'...")
    
    # Recursively find all files in upload_docs
    all_files = []
    for root, _, files in os.walk("upload_docs"):
        for file in files:
            # Ignore hidden files (.gitkeep, .DS_Store, etc.) and temp files
            if file.startswith(".") or file.startswith("~$"):
                continue
            all_files.append(os.path.join(root, file))

    if not all_files:
        print(f"   ℹ️  No files found in 'upload_docs'.")
        return

    print(f"[INFO] Found {len(all_files)} documents. Starting re-indexing...")
    print(f"{'FILE':<40} | {'CHUNKS':<8} | {'STATUS':<10}")
    print("-" * 65)

    start_time = time.time()
    total_chunks = 0
    for f_path in all_files:
        fname = os.path.basename(f_path)
        try:
            count = await process_and_store_file(f_path, store, processor, embed_client, embed_model, dry_run=args.dry_run, mode=mode)
            print(f"{fname[:40]:<40} | {count:<8} | [OK] {'Indexed' if not args.dry_run else 'Dry Run'}")
            total_chunks += count
        except Exception as e:
            print(f"{fname[:40]:<40} | {'-':<8} | [ERR] Error")
            logger.error(f"Error processing {fname}: {e}")

    duration = round(time.time() - start_time, 2)
    print(f"\n[DONE] REBUILD COMPLETE!")
    print(f"   Time Taken:  {duration}s")
    print(f"   Total Chunks: {total_chunks}")
    print(f"   Final Count:  {store.count()} in DB")

async def cmd_reindex(args):
    mode = determine_mode(args)
    if not args.files:
        print("[ERR] Error: Please specify one or more files to re-index.")
        return

    print_banner("Selective Document Re-indexing", f"Mode: {mode.upper()}. Refreshing {len(args.files)} document(s).")
    
    # Detect Config
    config_vars = await get_system_config()
    for k, v in config_vars.items():
        if v is not None:
            os.environ[k] = str(v)
        
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
            print(f"   [WARN] Warning: File not found: {f_arg}")

    if not target_files:
        print("[ERR] Error: No valid files found to re-index.")
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
            count = await process_and_store_file(f_path, store, processor, embed_client, embed_model, dry_run=args.dry_run, mode=mode)
            print(f"{fname[:40]:<40} | {count:<8} | [OK] {'Refreshed' if not args.dry_run else 'Dry Run'}")
            total_reindexed += count
        except Exception as e:
            print(f"{fname[:40]:<40} | {'-':<8} | [ERR] Error")
            logger.error(f"Error re-indexing {fname}: {e}")

    print(f"\n[OK] Selective re-indexing complete. {len(target_files)} files processed.")

async def cmd_delete(args):
    if not args.files:
        print("[ERR] Error: Please specify one or more files to delete.")
        return

    print_banner("Selective Embedding Deletion", f"Removing entries for {len(args.files)} document patterns.")
    
    from backend.rag.store import get_vector_store
    store = get_vector_store()
    
    # 1. Expand patterns or collect filenames
    target_filenames = set()
    for f_arg in args.files:
        clean_input = f_arg.lstrip('@')
        
        # Check if it's a local glob match
        matches = glob.glob(clean_input)
        if not matches:
            # Check in upload_docs (recursive discovery)
            upload_match = glob.glob(os.path.join("upload_docs", "**", clean_input), recursive=True)
            if upload_match:
                matches = upload_match
        
        if matches:
            for m in matches:
                target_filenames.add(os.path.basename(m))
        else:
            # Fallback: Treat as literal filename (useful for deleting files already removed from disk)
            target_filenames.add(os.path.basename(clean_input))

    if not target_filenames:
        print("[ERR] Error: No valid filenames identified.")
        return

    # 2. Sequential Deletion
    print(f"{'FILENAME':<45} | {'STATUS':<10}")
    print("-" * 60)
    
    deleted_count = 0
    for fname in sorted(list(target_filenames)):
        try:
            # We don't know if it exists in DB until we try, 
            # but Chroma's delete is a no-op if filter doesn't match.
            store.delete_file(fname)
            print(f"{fname[:45]:<45} | [OK] Deleted")
            deleted_count += 1
        except Exception as e:
            print(f"{fname[:45]:<45} | [ERR] Error")
            logger.error(f"Error during deletion of {fname}: {e}")

    print(f"\n[DONE] Deletion process complete. Processed {deleted_count} file entries.")

async def cmd_list(args):
    from backend.rag.store import get_vector_store
    store = get_vector_store()
    
    print_banner("Knowledge Base Inventory")
    
    try:
        total = store.count()
        print(f"[STATS] Total Embeddings in DB: {total}\n")
        
        if total == 0:
            print("   [WARN] Knowledge Base is currently empty.")
            return

        # Fetch unique stats
        results = store.collection.get(include=['metadatas'])
        stats = {}
        for m in results['metadatas']:
            fname = m.get('filename', 'Unknown')
            stats[fname] = stats.get(fname, 0) + 1
            
        print(f"{'FILENAME':<45} | {'CHUNKS':<8} | {'TYPE':<10}")
        print("-" * 65)
        for fname, count in sorted(stats.items()):
            # Detect type from a sample chunk
            doc_type = "unknown"
            for m in results['metadatas']:
                if m.get('filename') == fname:
                    doc_type = m.get('doc_type', 'general')
                    break
            print(f"{fname[:45]:<45} | {count:<8} | {doc_type:<10}")
            
    except Exception as e:
        print(f"[ERR] Error fetching inventory: {e}")

async def cmd_probe(args):
    if not args.query:
        print("[ERR] Error: Please provide a search query.")
        return

    from backend.rag.store import get_vector_store
    from backend.llm.client import OllamaClientWrapper
    
    # Detect Config for prompt model name
    config_vars = await get_system_config()
    for k, v in config_vars.items():
        if v is not None:
            os.environ[k] = str(v)

    store = get_vector_store()
    embed_client = OllamaClientWrapper.get_embedding_client()
    embed_model = os.environ["RAG_EMBED_MODEL"]
    
    print_banner(f"Semantic Probe: '{args.query}'", f"Testing search results using {embed_model}")

    try:
        # 1. Embed Query
        resp = await embed_client.embed(model=embed_model, input=[args.query])
        emb = resp['embeddings'][0]
        
        # 2. Query
        res = store.query(query_embeddings=[emb], n_results=args.top_k)
        
        docs = res.get('documents', [[]])[0]
        metas = res.get('metadatas', [[]])[0]
        dists = res.get('distances', [[]])[0]
        
        if not docs:
            print("   [WARN] No semantic matches found.")
            return

        for i, (doc, meta, dist) in enumerate(zip(docs, metas, dists)):
            print(f"[MATCH #{i+1}] (D: {dist:.4f})")
            print(f"   [SRC] Source: {meta.get('filename')} [Chunk {meta.get('chunk_index')}]")
            if 'section_path' in meta:
                print(f"   [MAP] Path:   {meta['section_path']}")
            print("-" * 40)
            preview = doc.strip().replace('\n', ' ')[:150]
            print(f"   \"{preview}...\"\n")
            
    except Exception as e:
        print(f"[ERR] Error during probe: {e}")

# --- Main Entry Point ---

def main():
    parser = argparse.ArgumentParser(description="Unified IPR RAG Embedding Manager & Debugger")
    subparsers = parser.add_subparsers(dest="command", help="Command to execute")
    
    # Command: rebuild
    rebuild_parser = subparsers.add_parser("rebuild", help="Wipe database and re-index all documents from scratch")
    rebuild_parser.add_argument("--dry-run", action="store_true", help="Prepare chunks without indexing")
    rebuild_parser.add_argument("--pymupdf4llm", action="store_true", help="FORCE override: Use PyMuPDF4LLM for all files")
    rebuild_parser.add_argument("--docling-vision", action="store_true", help="FORCE override: Use Docling Vision (OCR) for all files")
    
    # Command: reindex
    reindex_parser = subparsers.add_parser("reindex", help="Selective re-indexing for specific files")
    reindex_parser.add_argument("files", nargs="+", help="One or more filenames or patterns (e.g. '@file.pdf')")
    reindex_parser.add_argument("--dry-run", action="store_true", help="Prepare chunks without indexing")
    reindex_parser.add_argument("--pymupdf4llm", action="store_true", help="FORCE override: Use PyMuPDF4LLM for all files")
    reindex_parser.add_argument("--docling-vision", action="store_true", help="FORCE override: Use Docling Vision (OCR) for all files")
    
    # Command: list
    subparsers.add_parser("list", help="List all indexed files and metrics")
    
    # Command: probe
    probe_parser = subparsers.add_parser("probe", help="Perform a raw semantic search to test retrieval")
    probe_parser.add_argument("query", type=str, help="The search query to test")
    probe_parser.add_argument("--top_k", type=int, default=5, help="Number of results to show")
    
    # Command: delete
    delete_parser = subparsers.add_parser("delete", help="Remove all embeddings for specific files")
    delete_parser.add_argument("files", nargs="+", help="One or more filenames or patterns (e.g. 'doc.pdf')")
    
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
        elif args.command == "delete":
            asyncio.run(cmd_delete(args))
    except KeyboardInterrupt:
        print("\n\nOperation cancelled by user.")
    except Exception as e:
        print(f"\n[FATAL] ERROR: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
