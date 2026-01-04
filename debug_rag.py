import asyncio
import sys
import os

# Add project root to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from backend.rag.store import get_vector_store
from backend.llm.client import OllamaClientWrapper
from backend.rag.reranker import Reranker
from backend.config import set_embedding_model, set_main_model

async def debug_retrieval(query: str):
    # Setup Config (Hardcoded for debug)
    set_embedding_model("http://localhost:11434", "nomic-embed-text") # Guessing model, or I should check user settings. 
    # Actually I should probably check what the user selected. 
    # But for debugging now, let's assume localhost.
    
    print(f"\n--- Debugging Retrieval for: '{query}' ---\n")
    
    # 1. Embed
    print("1. Generating Embedding...")
    client = OllamaClientWrapper.get_embedding_client()
    model = OllamaClientWrapper.get_embedding_model_name()
    response = await client.embed(model=model, input=query)
    embedding = response.get('embeddings', [])
    
    if not embedding:
        print("ERROR: No embedding generated")
        return

    # 2. Query Store
    print("2. Querying Vector Store...")
    store = get_vector_store()
    results = store.query(query_embeddings=embedding, n_results=10)
    
    raw_docs = []
    if results['documents']:
        for i, doc_list in enumerate(results['documents']):
            metas = results['metadatas'][i]
            for j, doc in enumerate(doc_list):
                 raw_docs.append({
                     "page_content": doc,
                     "metadata": metas[j]
                 })
    
    print(f"Found {len(raw_docs)} raw documents.")
    for i, d in enumerate(raw_docs[:3]):
        print(f"  [Raw {i}] {d['metadata']['filename']} (Size: {len(d['page_content'])})")
        print(f"    Preview: {d['page_content'][:100]}...\n")

    # 3. Rerank
    print("3. Reranking...")
    reranker = Reranker()
    ranked_docs = reranker.rank(query, raw_docs, top_k=5)
    
    print(f"\n--- Top 5 Reranked Results ---")
    for i, d in enumerate(ranked_docs):
        print(f"\n[Rank {i+1}] Score: {d.get('score', 'N/A')}")
        print(f"Source: {d['metadata']['filename']}")
        print(f"Content:\n{d['page_content']}")
        print("-" * 50)

if __name__ == "__main__":
    if len(sys.argv) > 1:
        query = sys.argv[1]
    else:
        query = "what is the tech stack"
        
    asyncio.run(debug_retrieval(query))
