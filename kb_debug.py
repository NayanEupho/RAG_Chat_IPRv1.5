import os
import argparse
import asyncio
import logging
from typing import List, Dict, Any

# Suppress common connection logs for cleaner report
logging.getLogger("httpx").setLevel(logging.WARNING)

def print_header(title: str):
    print("\n" + "="*60)
    print(f"🔍 {title}")
    print("="*60)

async def run_inventory():
    from backend.rag.store import get_vector_store
    store = get_vector_store()
    
    print_header("KNOWLEDGE BASE INVENTORY")
    
    try:
        count = store.collection.count()
        print(f"📊 Total Embeddings in DB: {count}")
        
        if count == 0:
            print("   ⚠️  Knowledge Base is empty. Run 'rebuild_knowledge_base.py' first.")
            return

        # List files by metadata
        # We fetch all metadatas to unique filenames
        results = store.collection.get(include=['metadatas'])
        files_stats = {} # filename -> chunk_count
        
        for meta in results['metadatas']:
            if meta and 'filename' in meta:
                fname = meta['filename']
                files_stats[fname] = files_stats.get(fname, 0) + 1

        print(f"📂 Unique Files Indexed: {len(files_stats)}")
        print("\n" + f"{'FILENAME':<35} | {'CHUNKS':<10}")
        print("-" * 50)
        for fname, chunks in files_stats.items():
            print(f"{fname[:35]:<35} | {chunks:<10}")
            
    except Exception as e:
        print(f"❌ Error during inventory: {e}")

async def run_probe(query: str):
    from backend.rag.store import get_vector_store
    from backend.llm.client import OllamaClientWrapper
    
    store = get_vector_store()
    embed_client = OllamaClientWrapper.get_embedding_client()
    embed_model = OllamaClientWrapper.get_embedding_model_name()
    
    print_header(f"SEMANTIC PROBE: '{query}'")
    print(f"   Model: {embed_model}")
    
    try:
        # 1. Embed Query
        resp = await embed_client.embed(model=embed_model, input=[query])
        emb = resp['embeddings'][0]
        
        # 2. Query Store
        results = store.collection.query(
            query_embeddings=[emb],
            n_results=3,
            include=['documents', 'metadatas', 'distances']
        )
        
        docs = results.get('documents', [[]])[0]
        metas = results.get('metadatas', [[]])[0]
        dists = results.get('distances', [[]])[0]
        
        if not docs:
            print("   ⚠️  No matches found in vector space.")
            return

        for i, (doc, meta, dist) in enumerate(zip(docs, metas, dists)):
            print(f"\n📍 MATCH #{i+1} (Distance: {dist:.4f})")
            print(f"   📄 Source: {meta.get('filename')} [Chunk {meta.get('chunk_index')}]")
            print(f"   🏷️  Section: {meta.get('section', 'N/A')}")
            print("-" * 40)
            # Preview first 200 chars
            preview = doc.strip().replace('\n', ' ')[:200]
            print(f"   \"{preview}...\"")
            
    except Exception as e:
        print(f"❌ Error during probe: {e}")

async def main():
    parser = argparse.ArgumentParser(description="Knowledge Base Debugging Suite")
    parser.add_argument("--inventory", action="store_true", help="Show all indexed files and metrics")
    parser.add_argument("--probe", type=str, help="Run a manual semantic search to inspect raw results")
    
    args = parser.parse_args()
    
    if args.inventory:
        await run_inventory()
    elif args.probe:
        await run_probe(args.probe)
    else:
        parser.print_help()

if __name__ == "__main__":
    asyncio.run(main())
