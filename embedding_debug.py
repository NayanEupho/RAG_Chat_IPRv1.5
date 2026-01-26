import os
import argparse
import asyncio
import logging
import time
import httpx
import sys
import glob
from typing import List, Dict, Any, Optional
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass # Best effort loading, might fail if running in raw shell

# --- Configuration & Logging ---
logging.basicConfig(
    level=logging.ERROR, # Default to ERROR to keep menu clean. We enable INFO for specific ops.
    format='%(message)s' 
)
logger = logging.getLogger("embedding_debug")

# Suppress noisy logs
logging.getLogger("httpx").setLevel(logging.WARNING)

# --- UI Helpers ---

def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')

def print_header():
    clear_screen()
    print("="*70)
    print("🚀 IPR PLATINUM DEBUG SUITE (v1.7)")
    print("   Status: Interactive Mode")
    print("="*70 + "\n")

def print_banner(title: str, subtitle: Optional[str] = None):
    print("\n" + "-"*70)
    print(f"🔸 {title.upper()}")
    if subtitle:
        print(f"   {subtitle}")
    print("-"*70 + "\n")

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
    
    # Final Fallback: Environment Variables
    config = {
        "RAG_MAIN_HOST": os.getenv("RAG_MAIN_HOST"),
        "RAG_MAIN_MODEL": os.getenv("RAG_MAIN_MODEL"),
        "RAG_EMBED_HOST": os.getenv("RAG_EMBED_HOST"),
        "RAG_EMBED_MODEL": os.getenv("RAG_EMBED_MODEL")
    }

    # Validation
    missing = [k for k, v in config.items() if not v]
    if missing:
        print("\n❌ CONFIGURATION ERROR: Missing required environment variables.")
        print(f"   Missing: {', '.join(missing)}")
        sys.exit(1)

    return config

async def process_and_store_file(file_path: str, store, processor, embed_client, model):
    """
    Robust 'from scratch' processing for a single file.
    Includes VLM generation (which saves .md output) and Embedding.
    """
    filename = os.path.basename(file_path)
    print(f"   ⚙️  Processing: {filename}...")
    
    # 1. Parsing & Chunking (High-Fidelity)
    # This automatically writes debug .md to VLM_generated_md_docs/ via processor.py hooks
    chunks = processor.process_file(file_path)
    if not chunks:
        print(f"   ⚠️  Skipped {filename}: No content extracted.")
        return 0
    
    # 2. Embedding
    texts = [c['text'] for c in chunks]
    metadatas = [c['metadata'] for c in chunks]
    ids = [f"{m['filename']}_{m['chunk_index']}" for m in metadatas]
    
    # Batch embedding
    all_embeddings = []
    BATCH_SIZE = 50
    print(f"   🧠 Embedding {len(texts)} chunks...")
    
    for i in range(0, len(texts), BATCH_SIZE):
        batch_texts = texts[i:i + BATCH_SIZE]
        response = await embed_client.embed(model=model, input=batch_texts)
        all_embeddings.extend(response.get('embeddings', []))
    
    if len(all_embeddings) != len(texts):
        raise ValueError(f"Embedding mismatch for {filename}")

    # 3. Storage
    store.add_documents(texts, metadatas, ids, all_embeddings)
    return len(chunks)

# --- Core Commands ---

async def cmd_rebuild():
    print_banner("System-Wide Knowledge Base Rebuild", "Clearing database and re-indexing all documents.")
    
    # Env Setup
    config_vars = await get_system_config()
    for k, v in config_vars.items(): os.environ[k] = v
        
    from backend.rag.store import get_vector_store
    from backend.ingestion.processor import DocumentProcessor
    from backend.llm.client import OllamaClientWrapper
    
    store = get_vector_store()
    processor = DocumentProcessor()
    embed_client = OllamaClientWrapper.get_embedding_client()
    embed_model = os.environ["RAG_EMBED_MODEL"]
    
    # 1. Wipe
    print("🧹 [1/3] Clearing Vector Store...")
    store.clear_all()
    
    # 2. Discovery
    upload_dir = "upload_docs"
    files = [os.path.join(upload_dir, f) for f in os.listdir(upload_dir) 
             if not f.startswith(".") and os.path.isfile(os.path.join(upload_dir, f))]
            
    if not files:
        print(f"   ℹ️  No files found in '{upload_dir}'.")
        return

    print(f"📂 [2/3] Re-indexing {len(files)} documents...")
    print("-" * 65)
    
    start_time = time.time()
    total_chunks = 0
    for f_path in files:
        try:
            count = await process_and_store_file(f_path, store, processor, embed_client, embed_model)
            print(f"   ✅ Done: {os.path.basename(f_path)} ({count} chunks)")
            total_chunks += count
        except Exception as e:
            print(f"   ❌ Error: {os.path.basename(f_path)} - {e}")
            logger.error(f"Error processing {f_path}: {e}")

    # 3. Stats
    duration = round(time.time() - start_time, 2)
    print_banner("Rebuild Complete")
    print(f"   ⏱️  Time: {duration}s")
    print(f"   📚 Chunks: {total_chunks}")
    print(f"   💾 DB Count: {store.count()}")
    input("\nPress Enter to return...")

async def cmd_reindex_interactive():
    print_banner("Selective Re-indexing")
    
    # Discovery
    upload_dir = "upload_docs"
    files = [f for f in os.listdir(upload_dir) 
             if not f.startswith(".") and os.path.isfile(os.path.join(upload_dir, f))]
    
    if not files:
        print("   ❌ No files found in upload_docs/")
        input("Press Enter...")
        return

    print("Available Files:")
    for i, f in enumerate(files):
        print(f"   [{i+1}] {f}")
        
    choice = input("\nEnter file number (or 'all'): ")
    if choice.strip().lower() == 'all':
        await cmd_rebuild()
        return
        
    try:
        idx = int(choice) - 1
        if 0 <= idx < len(files):
            target_file = files[idx]
        else:
            print("❌ Invalid selection.")
            time.sleep(1)
            return
    except:
        return

    # Execute Single File Reindex
    print(f"\n🔄 Refreshing: {target_file}")
    
    config_vars = await get_system_config()
    for k, v in config_vars.items(): os.environ[k] = v
    
    from backend.rag.store import get_vector_store
    from backend.ingestion.processor import DocumentProcessor
    from backend.llm.client import OllamaClientWrapper
    
    store = get_vector_store()
    processor = DocumentProcessor()
    embed_client = OllamaClientWrapper.get_embedding_client()
    embed_model = os.environ["RAG_EMBED_MODEL"]
    
    f_path = os.path.join(upload_dir, target_file)
    store.delete_file(target_file)
    await process_and_store_file(f_path, store, processor, embed_client, embed_model)
    
    print("\n✅ File refreshed!")
    time.sleep(1.5)

async def cmd_inspect_vlm():
    """Start VLM Inspection Browser"""
    print_banner("VLM Output Inspector", "View generated Markdown from VLM processing.")
    
    debug_dir = "VLM_generated_md_docs"
    if not os.path.exists(debug_dir):
        print("   ❌ No VLM outputs found. Run a Rebuild/Reindex first.")
        input("Press Enter...")
        return
        
    files = [f for f in os.listdir(debug_dir) if f.endswith(".md")]
    if not files:
        print("   ℹ️  Directory is empty.")
        input("Press Enter...")
        return
        
    print("Generated Markdown Files:")
    for i, f in enumerate(files):
        print(f"   [{i+1}] {f}")
        
    choice = input("\nSelect file to inspect: ")
    try:
        idx = int(choice) - 1
        if 0 <= idx < len(files):
            target = files[idx]
            path = os.path.join(debug_dir, target)
            
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            
            # Stat Analysis
            visuals = content.count("[Image:") + content.count("Figure") + content.count("| --- |")
            print("\n" + "-"*50)
            print(f"📄 Analysis: {target}")
            print(f"   • Size: {len(content)} chars")
            print(f"   • Tables/Figures Detected: ~{visuals}")
            print("-"*50)
            print("CONTENT PREVIEW (First 1000 chars):\n")
            print(content[:1000] + "\n...\n")
            print("-"*50)
            input("Press Enter to return...")
            
    except:
        pass

async def cmd_probe_interactive():
    import re
    config_vars = await get_system_config()
    for k, v in config_vars.items(): os.environ[k] = v
        
    from backend.rag.store import get_vector_store
    from backend.llm.client import OllamaClientWrapper
    
    print_banner("Semantic Probe", "Test your embeddings with natural queries. Supports @filename for targeting.")
    
    while True:
        raw_input = input("\n🔍 Enter query (or 'exit'): ").strip()
        if raw_input.lower() in ['exit', 'quit', '']:
            break
            
        # Parse Mentions (@filename)
        mentions = re.findall(r"@([\w\-\. ]+?)(?=[,.;:!?\s]|$)", raw_input)
        mentions = [m.strip() for m in mentions if m.strip() and ('.' in m or len(m) > 3)]
        
        # Clean query for embedding (remove @tags)
        query = raw_input
        for m in mentions:
            query = query.replace(f"@{m}", "")
        query = query.strip()
        
        # Determine Filter
        filters = None
        filter_desc = "Global Search"
        if mentions:
            target = mentions[0] # Probe handles one target for simplicity
            filters = {"filename": target}
            filter_desc = f"Targeted Search: {target}"

        print(f"   📡 {filter_desc}...")
        embed_client = OllamaClientWrapper.get_embedding_client()
        embed_model = os.environ["RAG_EMBED_MODEL"]
        store = get_vector_store()
        
        try:
            resp = await embed_client.embed(model=embed_model, input=[query])
            emb = resp['embeddings'][0]
            
            # Query with potential filters
            res = store.query(query_embeddings=[emb], n_results=5, where=filters)
            
            docs = res.get('documents', [[]])[0]
            metas = res.get('metadatas', [[]])[0]
            dists = res.get('distances', [[]])[0]
            
            if not docs:
                print(f"   ⚠️  No matches found in {filter_desc}.")
                continue
                
            for i, (doc, meta, dist) in enumerate(zip(docs, metas, dists)):
                # Platinum Badge Display
                badge = ""
                if meta.get('has_visual'):
                    v_type = meta.get('visual_type', 'VISUAL').upper()
                    badge = f" [🖼️ {v_type}]"
                    
                path = meta.get('section_path', '').replace(' > ', ' → ')
                print(f"\n   📍 MATCH #{i+1} (Sim: {1-dist:.2f}){badge}")
                print(f"      📄 {meta.get('filename')} (Chunk {meta.get('chunk_index')})")
                if path:
                    print(f"      🗺️  {path}")
                if meta.get('visual_title'):
                    print(f"      🏷️  Title: {meta.get('visual_title')}")
                
                print(f"      📝 {doc[:150].replace(chr(10), ' ')}...")
                
        except Exception as e:
            print(f"❌ Error: {e}")

# --- Main Menu Loop ---

async def interactive_wizard():
    while True:
        print_header()
        print("   [1] 🔍 Semantic Probe (Test Retrieval)")
        print("   [2] 👁️  Inspect VLM Output (.md files)")
        print("   [3] 🧹 Rebuild Knowledge Base (Full Wipe)")
        print("   [4] ⚡ Re-index Specific File")
        print("   [5] 🚪 Exit")
        
        choice = input("\n   Select Command: ")
        
        if choice == '1':
            await cmd_probe_interactive()
        elif choice == '2':
            await cmd_inspect_vlm()
        elif choice == '3':
            confirm = input("Are you sure you want to wipe everything? (y/n): ")
            if confirm.lower() == 'y':
                await cmd_rebuild()
        elif choice == '4':
            await cmd_reindex_interactive()
        elif choice == '5':
            print("\n👋 Exiting...")
            break
        else:
            pass

# --- Entry Point ---

def main():
    parser = argparse.ArgumentParser(description="IPR Platinum Debug Suite")
    subparsers = parser.add_subparsers(dest="command")
    
    # Legacy args for automation
    subparsers.add_parser("rebuild")
    p_probe = subparsers.add_parser("probe")
    p_probe.add_argument("query", type=str)
    
    try:
        # Check if args provided
        if len(sys.argv) > 1:
            # Run in headless mode (legacy)
            args = parser.parse_args()
            if args.command == "rebuild":
                asyncio.run(cmd_rebuild())
            elif args.command == "probe":
                # Need to adapt logic for headless probe if needed, 
                # but for now legacy users usually use 'rebuild'.
                pass
        else:
            # Run Interactive Wizard
            asyncio.run(interactive_wizard())
            
    except KeyboardInterrupt:
        print("\nCancelled.")
    except Exception as e:
        print(f"\n❌ FATAL: {e}")

if __name__ == "__main__":
    main()
