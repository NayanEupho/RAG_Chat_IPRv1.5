"""
Retrieval Node
--------------
The retrieval engine orchestrates multi-stage search operations:
1. Multi-query expansion (Recall maximization).
2. Parallel vector search (ChromaDB).
3. Cross-encoder reranking (Precision optimization).
4. Fragment Reconstruction (Stitching adjacent chunks).
5. Q&A Atomic preservation.
"""

from backend.graph.state import AgentState
from backend.rag.store import get_vector_store
from backend.llm.client import OllamaClientWrapper
from functools import lru_cache
import hashlib
import logging
import asyncio
from backend.config import get_config

logger = logging.getLogger(__name__)

# Global LRU-style cache for embeddings to reduce Ollama API load
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


from collections import defaultdict

def smart_merge(text_a: str, text_b: str, max_overlap: int = 500) -> str:
    """
    Expert implementation of Overlap De-duplication.
    Detects if the end of text_a matches the start of text_b and joins them cleanly.
    """
    # 1. Exact match tail optimization
    # Ingestion uses ~400 char overlap. Let's look for common text.
    a_tail = text_a[-max_overlap:]
    
    # We look for the first 100 characters of the tail in the start of text_b
    search_str = a_tail[:100].strip()
    if not search_str: return text_a + "\n" + text_b
    
    start_pos = text_b.find(search_str)
    if start_pos != -1:
        # Check if the remaining tail matches text_b starting from start_pos
        potential_overlap = text_b[start_pos:len(a_tail)]
        # Use a similarity threshold or exact match
        if text_a.endswith(potential_overlap):
             # Success: Strip the overlap from text_b
             return text_a + text_b[len(potential_overlap):]
             
    # Fallback to newline join if no clear overlap detected
    return text_a + "\n" + text_b

def stitch_fragments(docs: list[dict]) -> list[dict]:
    """
    Fragment Reconstruction Engine (FRE) v2.
    Uses part counts (fragment_index/total) for deterministic stitching.
    """
    if not docs: return []
    
    # Sort docs by filename and then by chunk_index to ensure order
    docs_sorted = sorted(docs, key=lambda x: (x['metadata'].get('filename', ''), x['metadata'].get('chunk_index', -1)))
    
    grouped = defaultdict(list)
    for d in docs_sorted:
        fname = d['metadata'].get('filename', 'unknown')
        grouped[fname].append(d)
        
    stitched = []
    for fname, group in grouped.items():
        i = 0
        while i < len(group):
            current = group[i]
            combined_content = current['page_content']
            combined_meta = current['metadata'].copy()
            
            # Metadata for FRE
            f_idx = combined_meta.get('fragment_index', 0)
            f_total = combined_meta.get('total_fragments', 1)
            
            j = i + 1
            while j < len(group):
                next_doc = group[j]
                
                # FRE Deterministic Condition
                curr_idx = group[j-1]['metadata'].get('chunk_index', -1)
                next_idx = next_doc['metadata'].get('chunk_index', -100)
                
                is_adj = (next_idx == curr_idx + 1)
                is_frag = next_doc['metadata'].get('is_fragment', False)
                
                # Gap Detection
                if is_adj:
                    # Merge with Smart Join
                    combined_content = smart_merge(combined_content, next_doc['page_content'])
                    j += 1
                else:
                    # Potential Gap! 
                    # If we have fragment info, check if we missed something in the sequence
                    if is_frag and f_total > 1:
                        logger.warning(f"[FRE] Gap detected in {fname} between index {curr_idx} and {next_idx}")
                    break
                    
                # Break if we hit a size limit for the prompt
                if len(combined_content) > 12000: 
                    break
                    
            stitched.append({"page_content": combined_content, "metadata": combined_meta})
            i = j
            
    return stitched


def stitch_qna_fragments(docs: list[dict]) -> list[dict]:
    """
    Merges Q&A fragments by qa_pair_id.
    Preserves question context across all fragments.
    """
    if not docs:
        return []
    
    # Separate Q&A docs from general docs
    qna_docs = [d for d in docs if d['metadata'].get('doc_type') == 'qna']
    general_docs = [d for d in docs if d['metadata'].get('doc_type') != 'qna']
    
    if not qna_docs:
        return docs  # No Q&A docs to stitch
    
    # Group Q&A docs by qa_pair_id
    grouped = defaultdict(list)
    for d in qna_docs:
        pair_id = d['metadata'].get('qa_pair_id', 'unknown')
        grouped[pair_id].append(d)
    
    stitched_qna = []
    for pair_id, fragments in grouped.items():
        if len(fragments) == 1:
            # Already atomic, no stitching needed
            stitched_qna.append(fragments[0])
            continue
        
        # Sort by fragment_index
        fragments.sort(key=lambda x: x['metadata'].get('fragment_index', 0))
        
        # Check if all fragments are present
        total_expected = fragments[0]['metadata'].get('total_fragments', 1)
        if len(fragments) != total_expected:
            logger.warning(f"[QNA STITCH] Incomplete Q&A pair {pair_id}: got {len(fragments)}/{total_expected} fragments")
        
        # Merge content
        merged_content = '\n\n'.join([f['page_content'] for f in fragments])
        
        # Use first fragment's metadata, mark as stitched
        merged_meta = fragments[0]['metadata'].copy()
        merged_meta['is_fragment'] = False
        merged_meta['is_atomic'] = True
        merged_meta['stitched_from'] = len(fragments)
        
        stitched_qna.append({
            "page_content": merged_content,
            "metadata": merged_meta
        })
        
        logger.debug(f"[QNA STITCH] Merged {len(fragments)} fragments for {pair_id}")
    
    # Combine with general docs
    return stitched_qna + general_docs

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
    
    # 1. ALWAYS fetch Introduction/Abstract for targeted docs (Chunks 0, 1, 2)
    async def fetch_intro(doc_name):
        try:
            intro_where = {"$and": [{"filename": {"$eq": doc_name}}, {"chunk_index": {"$lt": 3}}]}
            intro_results = store.get_by_metadata(where=intro_where, limit=3)
            if intro_results and intro_results.get('documents'):
                return [{"page_content": c, "metadata": intro_results['metadatas'][i]} 
                        for i, c in enumerate(intro_results['documents'])]
        except Exception as e:
            logger.warning(f"[RETRIEVER] Failed to fetch intro chunks: {e}")
        return []

    # 2. SEGMENTED/GLOBAL SEARCH TASKS
    async def run_scenario(q, target_file):
        q_embed = await get_cached_embedding(q, model)
        if not q_embed: return []
        
        filters = {"filename": target_file} if target_file else None
        res = store.query(query_embeddings=q_embed, n_results=20 if target_file else 7, where=filters)
        
        results = []
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

                    results.append({"page_content": doc, "metadata": meta})
        return results
    
    # EXECUTE ALL IN PARALLEL
    tasks = [fetch_intro(d) for d in targeted_docs]
    if semantic_maps:
        for entry in semantic_maps:
            tasks.append(run_scenario(entry.get('query'), entry.get('target')))
        base_q = queries_to_run[0] if queries_to_run else state.get('query', '')
        tasks.append(run_scenario(base_q, None)) # Global Fallback
    else:
        for q in queries_to_run:
            tasks.append(run_scenario(q, targeted_docs[0] if targeted_docs else None))

    results = await asyncio.gather(*tasks)
    for batch in results:
        all_raw_docs.extend(batch)
    
    # Deduplicate by Content
    unique_docs_map = {}
    for d in all_raw_docs:
        key = d['page_content']
        if key not in unique_docs_map:
            unique_docs_map[key] = d
            
    unique_docs = list(unique_docs_map.values())
    logger.info(f"[RETRIEVER] Found {len(unique_docs)} unique documents. Processing for rerank...")

    # 3. Rerank (now async - offloaded to ThreadPoolExecutor)
    from backend.rag.reranker import Reranker
    reranker = Reranker()
    cfg = get_config()
    ranked_docs = await reranker.rank(query, unique_docs, top_k=cfg.retrieval_top_k)
    
    logger.info(f"[RETRIEVER] Reranked to top {len(ranked_docs)} documents.")

    # 4. [AUDIT REFINEMENT] Post-Rerank Neighbor Fetching (Optimization for Latency)
    # We only fetch neighbors for the high-confidence results to save reranker time.
    final_with_neighbors = []
    for d in ranked_docs:
        final_with_neighbors.append(d)
        try:
            meta = d['metadata']
            chunk_idx = meta.get('chunk_index')
            filename = meta.get('filename')
            if chunk_idx is not None and filename is not None:
                neighbor_where = {
                    "$and": [
                        {"filename": {"$eq": filename}},
                        {"chunk_index": {"$in": [chunk_idx - 1, chunk_idx + 1]}}
                    ]
                }
                neighbor_results = store.get_by_metadata(where=neighbor_where, limit=2)
                if neighbor_results and neighbor_results.get('documents'):
                    for n_idx, n_content in enumerate(neighbor_results['documents']):
                        n_meta = neighbor_results['metadatas'][n_idx]
                        final_with_neighbors.append({"page_content": n_content, "metadata": n_meta})
        except Exception as neighbor_err:
            logger.debug(f"[RETRIEVER] Failed to fetch neighbors: {neighbor_err}")

    # Re-deduplicate after neighbor injection (neighbors might already be in list)
    unique_final = {}
    for d in final_with_neighbors:
        unique_final[d['page_content']] = d
    final_docs = list(unique_final.values())

    # Stitch hierarchical fragments (for general docs)
    # Note: We stitch FROM the unique_final list which includes neighbors
    final_docs = stitch_fragments(list(unique_final.values()))
    
    # Stitch Q&A fragments (groups by qa_pair_id)
    final_docs = stitch_qna_fragments(final_docs)

    # Format Final Results (ULTRA-MINIFIED ENVELOPE)
    import re
    final_retrieved = []
    
    for d in final_docs:
        meta = d['metadata']
        filename = meta.get('filename', 'Unknown')
        path = meta.get('section_path', 'Root')
        raw_content = d['page_content']
        doc_type = meta.get('doc_type', 'general')
        
        # Minify path for prompt space
        short_path = path.split(" > ")[-1] if " > " in path else path
        
        # Clean the "glued" prefix added during ingestion
        content = re.sub(r'^\[Doc: .*? \| (?:Path|Section): .*?\](?:\n| \| Q&A: .*?\](?:\n| \| Part \d+/\d+\]))', '', raw_content)
        
        if doc_type == "qna":
            header = f"[Q&A | Source: {filename} | Section: {short_path}]"
            structured_segment = f"{header}\n{content}"
        else:
            header = f"[Source: {filename} | Section: {short_path}]"
            structured_segment = f"{header}\n{content}"
        
        final_retrieved.append(structured_segment)
                  
    return {"documents": final_retrieved}
