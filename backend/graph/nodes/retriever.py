from backend.graph.state import AgentState
from backend.rag.store import get_vector_store
from backend.llm.client import OllamaClientWrapper
from functools import lru_cache
import hashlib
import logging
import asyncio

logger = logging.getLogger(__name__)

# In-memory cache for query embeddings (avoids repeated Ollama calls)
_embedding_cache = {}

async def get_cached_embedding(query: str, model: str) -> list:
    """Get embedding from cache or compute it."""
    cache_key = hashlib.md5(f"{query}:{model}".encode()).hexdigest()
    
    if cache_key in _embedding_cache:
        logger.debug(f"Embedding cache HIT for query: {query[:30]}...")
        return _embedding_cache[cache_key]
    
    client = OllamaClientWrapper.get_embedding_client()
    try:
        response = await client.embed(model=model, input=query)
        embedding = response.get('embeddings', [])
        
        if embedding:
            # Store in cache (limit cache size to prevent memory bloat)
            if len(_embedding_cache) > 1000:
                # Simple eviction: clear half the cache
                keys_to_remove = list(_embedding_cache.keys())[:500]
                for k in keys_to_remove:
                    del _embedding_cache[k]
            _embedding_cache[cache_key] = embedding
            logger.debug(f"Embedding cache MISS, cached for query: {query[:30]}...")
        
        return embedding
    except Exception as e:
        logger.error(f"[RETRIEVER] Embedding failed for '{query}': {e}")
        return []

async def generate_sub_queries(query: str) -> list[str]:
    """Use LLM to expand the query into 3 distinct search terms."""
    try:
        client = OllamaClientWrapper.get_chat_model()
        system_prompt = (
            "You are a search query optimizer. "
            "Generate 3 distinct versions of the user's query to maximize retrieval recall.\n"
            "1. Focus on synonyms (e.g., 'tech stack' -> 'libraries and frameworks').\n"
            "2. Focus on specific components if the query is broad.\n"
            "3. Keep queries short and searchable.\n\n"
            "Output ONLY the 3 queries separated by newlines. Do not verify, do not talk."
        )
        
        response = await client.ainvoke([
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": query}
        ])
        
        content = response.content.strip()
        sub_queries = [line.strip().replace("- ", "") for line in content.split("\n") if line.strip()]
        
        # Fallback if LLM outputs nothing valid
        if not sub_queries:
             sub_queries = [query]
        
        # Always include original query
        if query not in sub_queries:
            sub_queries.insert(0, query)
            
        logger.info(f"[RETRIEVER] Generated sub-queries: {sub_queries}")
        return sub_queries[:4] # Max 4 variations
        
    except Exception as e:
        logger.warning(f"[RETRIEVER] Query expansion failed: {e}. using original query only.")
        return [query]

async def retrieve_documents(state: AgentState):
    """
    Retrieves documents based on intent.
    - direct_rag: Search all unique docs.
    - specific_doc_rag: Filter by list of filenames.
    """
    query = state['query']
    intent = state['intent']
    targeted_docs = state.get('targeted_docs', [])
    
    store = get_vector_store()
    model = OllamaClientWrapper.get_embedding_model_name()
    
    # Decide on queries
    queries_to_run = [query]
    
    # Use multi-query for BOTH general RAG and specific file targeting
    # CHECK: If we already have semantic_queries (from Planner or Rewriter), we SKIP generation
    semantic_maps = state.get('semantic_queries', [])
    
    if semantic_maps:
        logger.info(f"[RETRIEVER] Using {len(semantic_maps)} pre-planned semantic queries.")
        # We don't need to run generate_sub_queries here because we will iterate over semantic_maps later
        # However, for the "Global Fallback" (Safety Net) below, we might still want a base list of strings.
        queries_to_run = [s['query'] for s in semantic_maps]
        
    elif intent in ["direct_rag", "specific_doc_rag"]:
        logger.info("[RETRIEVER] Generating sub-queries for better recall...")
        expanded_queries = await generate_sub_queries(query)
        queries_to_run = expanded_queries
    
    # Run Searches in Parallel
    all_raw_docs = []
    
    # Run Searches in Parallel (Segmented & Hybrid)
    semantic_maps = state.get('semantic_queries', [])
    all_raw_docs = []
    
    # 1. ALWAYS fetch Introduction/Abstract for targeted docs (Chunks 0, 1, 2)
    if targeted_docs:
        try:
            for doc_name in targeted_docs:
                intro_where = {"$and": [{"filename": {"$eq": doc_name}}, {"chunk_index": {"$lt": 3}}]}
                intro_results = store.get_by_metadata(where=intro_where, limit=3)
                if intro_results and intro_results.get('documents'):
                    for i, content in enumerate(intro_results['documents']):
                        meta = intro_results['metadatas'][i]
                        all_raw_docs.append({"page_content": content, "metadata": meta})
        except Exception as e:
            logger.warning(f"[RETRIEVER] Failed to fetch intro chunks: {e}")

    # 2. SEGMENTED VECTOR SEARCH
    # If we have a semantic map, use it. Otherwise, use simple queries.
    scenarios = []
    if semantic_maps:
        for entry in semantic_maps:
            q = entry.get('query')
            t = entry.get('target')
            scenarios.append((q, t))
    else:
        # Fallback to simple multi-query if rewriter didn't map
        for q in queries_to_run:
            scenarios.append((q, targeted_docs[0] if targeted_docs else None))

    for q, target_file in scenarios:
        q_embed = await get_cached_embedding(q, model)
        if not q_embed: continue
        
        # Determine filter
        filters = None
        if target_file:
            filters = {"filename": target_file}
        
        # A) Perform the specific search
        # If target_file is set, this is Segmented. If None, it's Global.
        # Increased n_results to 20 for targeted file searches for better recall
        res = store.query(query_embeddings=q_embed, n_results=20 if target_file else 7, where=filters)
        if res['documents']:
            for i, doc_list in enumerate(res['documents']):
                metas = res['metadatas'][i]
                for j, doc in enumerate(doc_list):
                    meta = metas[j]
                    
                    # 1. Structural Penalty: De-prioritize "Empty" or "Structural" chunks
                    # Simple heuristic: If it's mostly whitespace or very short and looks like a TOC
                    if len(doc.strip()) < 100 or doc.count('\n') > len(doc) / 20: 
                        # We still keep them but they might be filtered by reranker
                        pass

                    all_raw_docs.append({"page_content": doc, "metadata": meta})

                    # 2. CONTEXT WINDOW: Fetch immediate neighbors (+/- 1 chunk)
                    # This ensures body text is pulled in if a heading chunk is matched
                    try:
                        chunk_idx = meta.get('chunk_index')
                        filename = meta.get('filename')
                        if chunk_idx is not None and filename is not None:
                            neighbor_where = {
                                "$and": [
                                    {"filename": {"$eq": filename}},
                                    {"chunk_index": {"$in": [chunk_idx - 1, chunk_idx + 1]}}
                                ]
                            }
                            # Get neighbors without embeddings
                            neighbor_results = store.get_by_metadata(where=neighbor_where, limit=2)
                            if neighbor_results and neighbor_results.get('documents'):
                                for n_idx, n_content in enumerate(neighbor_results['documents']):
                                    n_meta = neighbor_results['metadatas'][n_idx]
                                    all_raw_docs.append({"page_content": n_content, "metadata": n_meta})
                    except Exception as neighbor_err:
                        logger.debug(f"[RETRIEVER] Failed to fetch neighbors: {neighbor_err}")

    # B) Global Fallback Search (Safety Net)
    # Even in segmented mode, we do 1 small global search to maintain "cross-file" intelligence.
    if semantic_maps:
        base_q = queries_to_run[0] if queries_to_run else state.get('query', '')
        q_embed = await get_cached_embedding(base_q, model)
        if q_embed:
            g_results = store.query(query_embeddings=q_embed, n_results=5)
            if g_results['documents']:
                for i, doc_list in enumerate(g_results['documents']):
                    metas = g_results['metadatas'][i]
                    for j, doc in enumerate(doc_list):
                        all_raw_docs.append({"page_content": doc, "metadata": metas[j]})
    
    # Deduplicate by Content
    unique_docs_map = {}
    for d in all_raw_docs:
        # Use content hash or just content string as key
        # Use source+content to align with how 'routes.py' splits them later?
        # Actually routes.py splits by "Source: ... \nContent: ..."
        # So we just need unique content.
        key = d['page_content']
        if key not in unique_docs_map:
            unique_docs_map[key] = d
            
    unique_docs = list(unique_docs_map.values())
    logger.info(f"[RETRIEVER] Found {len(unique_docs)} unique documents across {len(queries_to_run)} queries.")

    # 3. Rerank (now async - offloaded to ThreadPoolExecutor)
    from backend.rag.reranker import Reranker
    reranker = Reranker()
    # Reduced from 15 to 7 for better performance while maintaining accuracy
    ranked_docs = await reranker.rank(query, unique_docs, top_k=7)
    
    logger.info(f"[RETRIEVER] Reranked to top {len(ranked_docs)} documents.")

    # Format Final Results for the LLM context
    final_retrieved = []
    for d in ranked_docs:
        source = d['metadata'].get('filename', 'Unknown')
        final_retrieved.append(f"Source: {source}\nContent: {d['page_content']}")
                 
    return {"documents": final_retrieved}
