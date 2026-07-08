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
from backend.llm.health import ModelUnavailableError, ensure_rag_ready
from collections import OrderedDict, defaultdict
import hashlib
import logging
import asyncio
import time
import os
import re
from backend.config import get_config

logger = logging.getLogger(__name__)

# Global LRU-style cache for embeddings to reduce Ollama API load
_embedding_cache: OrderedDict[str, list] = OrderedDict()
_embedding_inflight: dict[str, asyncio.Task] = {}
_embedding_inflight_lock = asyncio.Lock()
_EMBEDDING_CACHE_MAX_SIZE = 1024


def _embedding_cache_key(query: str, model: str) -> str:
    return hashlib.md5(f"{query}:{model}".encode()).hexdigest()


def _get_cached_embedding_value(cache_key: str) -> list | None:
    cached = _embedding_cache.get(cache_key)
    if cached is not None:
        _embedding_cache.move_to_end(cache_key)
    return cached


def _set_cached_embedding_value(cache_key: str, embedding: list) -> None:
    _embedding_cache[cache_key] = embedding
    _embedding_cache.move_to_end(cache_key)
    while len(_embedding_cache) > _EMBEDDING_CACHE_MAX_SIZE:
        _embedding_cache.popitem(last=False)

def _normalize_filename(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (value or "").lower())


def _resolve_target_filename(target: str, available_files: list[str]) -> str:
    """Resolve GUI/LLM target strings to the exact filename stored in Chroma."""
    if not target:
        return target
    target_norm = _normalize_filename(target)
    for filename in available_files:
        if filename == target:
            return filename
    for filename in available_files:
        if _normalize_filename(filename) == target_norm:
            return filename
    for filename in available_files:
        norm = _normalize_filename(filename)
        if target_norm and (target_norm in norm or norm in target_norm):
            return filename
    return target

async def get_cached_embedding(query: str, model: str) -> list:
    """Get embedding from cache or compute it."""
    normalized = re.sub(r"\s+", " ", query or "").strip()
    embeddings = await get_cached_embeddings([normalized], model)
    return embeddings.get(normalized, [])


async def get_cached_embeddings(queries: list[str], model: str) -> dict[str, list]:
    """Get embeddings for multiple queries with one Ollama call for cache misses."""
    unique_queries = []
    seen_queries = set()
    for query in queries:
        normalized = re.sub(r"\s+", " ", query or "").strip()
        if normalized and normalized not in seen_queries:
            unique_queries.append(normalized)
            seen_queries.add(normalized)

    results: dict[str, list] = {}
    tasks_to_await: list[asyncio.Task] = []
    cache_misses: list[str] = []
    for query in unique_queries:
        cache_key = _embedding_cache_key(query, model)
        cached = _get_cached_embedding_value(cache_key)
        if cached is not None:
            logger.debug(f"Embedding cache HIT for query: {query[:30]}...")
            results[query] = cached
        else:
            cache_misses.append(query)

    async with _embedding_inflight_lock:
        queries_to_fetch: list[str] = []
        for query in cache_misses:
            cache_key = _embedding_cache_key(query, model)
            cached = _get_cached_embedding_value(cache_key)
            if cached is not None:
                logger.debug(f"Embedding cache HIT for query: {query[:30]}...")
                results[query] = cached
            elif cache_key in _embedding_inflight:
                tasks_to_await.append(_embedding_inflight[cache_key])
            else:
                queries_to_fetch.append(query)

        if queries_to_fetch:
            fetch_task = asyncio.create_task(_fetch_and_cache_embeddings(queries_to_fetch, model))
            for query in queries_to_fetch:
                _embedding_inflight[_embedding_cache_key(query, model)] = fetch_task
            tasks_to_await.append(fetch_task)

    for task in tasks_to_await:
        results.update(await task)

    return {query: results[query] for query in unique_queries if query in results}


async def _fetch_and_cache_embeddings(missing_queries: list[str], model: str) -> dict[str, list]:
    client = OllamaClientWrapper.get_embedding_client()
    results: dict[str, list] = {}
    try:
        input_value = missing_queries[0] if len(missing_queries) == 1 else missing_queries
        response = await client.embed(
            model=model,
            input=input_value,
            keep_alive=OllamaClientWrapper.get_embedding_keep_alive(),
        )
        embeddings = response.get('embeddings', [])
        if not embeddings:
            raise ModelUnavailableError("Embedding model returned no vector")

        if len(missing_queries) == 1 and embeddings and isinstance(embeddings[0], (int, float)):
            embeddings = [embeddings]
        if len(embeddings) != len(missing_queries):
            raise ModelUnavailableError("Embedding model returned an unexpected vector count")

        for query, embedding in zip(missing_queries, embeddings):
            if not embedding:
                raise ModelUnavailableError("Embedding model returned no vector")
            cached_embedding = embedding if isinstance(embedding[0], list) else [embedding]
            _set_cached_embedding_value(_embedding_cache_key(query, model), cached_embedding)
            results[query] = cached_embedding
            logger.debug(f"Embedding cache MISS, cached for query: {query[:30]}...")

        return results
    except Exception as e:
        logger.error(f"[RETRIEVER] Embedding failed for {len(missing_queries)} queries: {e}")
        raise ModelUnavailableError(f"Embedding model failed during retrieval: {e}") from e
    finally:
        async with _embedding_inflight_lock:
            for query in missing_queries:
                cache_key = _embedding_cache_key(query, model)
                task = _embedding_inflight.get(cache_key)
                if task is asyncio.current_task():
                    del _embedding_inflight[cache_key]

def smart_merge(text_a: str, text_b: str, max_overlap: int = 500) -> str:
    """
    Expert implementation of Overlap De-duplication.
    Detects if the end of text_a matches the start of text_b and joins them cleanly.
    """
    if "|" in text_a and "|" in text_b:
        a_lines = text_a.splitlines()
        b_lines = text_b.splitlines()
        if len(a_lines) >= 2 and len(b_lines) >= 2:
            header = "\n".join(a_lines[:2])
            if "\n".join(b_lines[:2]) == header:
                text_b = "\n".join(b_lines[2:]).lstrip()

    # 1. Exact match tail optimization
    # Ingestion uses ~400 char overlap. Let's look for common text.
    a_tail = text_a[-max_overlap:]
    
    # We look for the first 100 characters of the tail in the start of text_b
    search_str = a_tail[:100].strip()
    if not search_str:
        return text_a + "\n" + text_b
    
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
    if not docs:
        return []

    # Table-aware ingestion already emits atomic row chunks. Merging adjacent
    # rows here can put an unrelated row at the front of the evidence envelope
    # and degrade both grounding and TTFT.
    table_docs = [
        d for d in docs
        if str(d.get("metadata", {}).get("chunk_kind", "")).startswith("table_row")
    ]
    if table_docs:
        return docs
     
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


_TOKEN_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "how",
    "in", "is", "it", "me", "of", "on", "or", "that", "the", "this", "to",
    "what", "when", "where", "which", "who", "why", "with", "about", "does",
    "explain", "give", "show", "tell", "summarize", "summary",
}


def _query_variants(query: str, semantic_maps: list[dict], targeted_docs: list[str]) -> list[dict]:
    """Deterministic query plan: no pre-retrieval LLM call."""
    if semantic_maps:
        return [
            {"query": (item.get("query") or query).strip(), "target": item.get("target")}
            for item in semantic_maps
            if (item.get("query") or query)
        ]

    base = re.sub(r"\s+", " ", query).strip()
    words = _tokenize(base)
    keyword = " ".join(words[:10])
    variants = [base]

    lower = base.lower()
    if any(t in lower for t in ["summary", "summarize", "overview", "about"]):
        variants.append(f"{keyword or base} purpose scope overview conclusion")
    elif any(t in lower for t in ["author", "authors", "affiliation", "affiliations", "title", "abstract"]):
        variants.append(f"{keyword or base} authors affiliations title abstract paper")
    elif any(t in lower for t in ["technology", "technologies", "stack", "component", "framework", "tool"]):
        variants.append(f"{keyword or base} technology stack component breakdown tools frameworks runtime language")
    elif any(t in lower for t in ["eligibility", "eligible", "criteria", "who can"]):
        variants.append(f"{keyword or base} eligibility criteria conditions requirements")
    elif any(t in lower for t in ["benefit", "allowance", "entitlement"]):
        variants.append(f"{keyword or base} benefit entitlement allowance")
    if keyword and keyword.lower() != base.lower():
        variants.append(keyword)

    deduped = []
    seen = set()
    for variant in variants:
        key = variant.lower().strip()
        if key and key not in seen:
            seen.add(key)
            deduped.append(variant.strip())

    targets = targeted_docs or [None]
    # Keep the hot path bounded: max 2 variants per target.
    return [{"query": v, "target": target} for target in targets for v in deduped[:2]]


def _effective_top_k(query: str, context_action: str, cfg) -> int:
    lower = (query or "").lower()
    if context_action == "hybrid" or re.search(r"\b(full details|everything|compare|detailed lifecycle|all sections|deep)\b", lower):
        return max(cfg.retrieval_top_k, getattr(cfg, "retrieval_deep_top_k", 10))
    if re.search(r"\b(details|detail|explain|elaborate|why|how|exact)\b", lower):
        return max(cfg.retrieval_top_k, getattr(cfg, "retrieval_detail_top_k", 8))
    return max(1, cfg.retrieval_top_k)


def _tokenize(text: str) -> list[str]:
    return [
        token for token in re.findall(r"[a-z0-9][a-z0-9&./-]*", text.lower())
        if len(token) > 2 and token not in _TOKEN_STOPWORDS
    ]


def _hybrid_score(query: str, doc: dict) -> float:
    """Cheap lexical and structural scoring layered on Chroma distance rank."""
    text = doc.get("page_content", "")
    meta = doc.get("metadata", {})
    q_tokens = set(_tokenize(query))
    if not q_tokens:
        return doc.get("_vector_score", 0.0)

    haystack = " ".join([
        text,
        str(meta.get("section_title", "")),
        str(meta.get("section_path", "")),
        str(meta.get("filename", "")),
        str(meta.get("question_text", "")),
    ]).lower()
    matched = sum(1 for token in q_tokens if token in haystack)
    coverage = matched / max(len(q_tokens), 1)
    title_text = f"{meta.get('section_title', '')} {meta.get('section_path', '')}".lower()
    title_hits = sum(1 for token in q_tokens if token in title_text)
    query_acronyms = {
        token.lower()
        for token in re.findall(r"\b[A-Z][A-Z0-9&/-]{1,7}\b", query)
    }
    exact_acronym_hits = sum(
        1
        for token in query_acronyms
        if re.search(rf"(?<![a-z0-9]){re.escape(token)}(?![a-z0-9])", title_text)
    )
    qna_boost = 0.08 if meta.get("doc_type") == "qna" and matched else 0.0
    table_kind = str(meta.get("chunk_kind", ""))
    table_boost = 0.18 if table_kind.startswith("table_row") and matched else 0.0
    table_penalty = -0.04 if meta.get("has_table") and matched == 0 else 0.0
    technology_boost = 0.0
    if any(token in q_tokens for token in {"technology", "technologies", "stack", "component", "framework", "tool"}):
        if "component breakdown" in title_text or re.search(r"\bcomponent:\s+", haystack):
            technology_boost = 0.42
    intro_boost = 0.0
    if re.search(r"\b(about|overview|summary|summari[sz]e|purpose|scope)\b", query.lower()):
        chunk_kind = str(meta.get("chunk_kind", "")).lower()
        chunk_index = meta.get("chunk_index")
        if chunk_kind == "doc_summary" or (isinstance(chunk_index, int) and chunk_index < 2):
            intro_boost = 0.55
    targeted_lexical_boost = min(float(doc.get("_lexical_score", 0.0)) * 0.45, 0.95)
    return (
        doc.get("_vector_score", 0.0)
        + (coverage * 0.45)
        + (title_hits * 0.06)
        + (exact_acronym_hits * 0.22)
        + qna_boost
        + table_boost
        + table_penalty
        + technology_boost
        + intro_boost
        + targeted_lexical_boost
    )


def _target_lexical_score(query: str, doc: dict) -> float:
    """Score exact lexical matches inside an explicitly targeted document."""
    q_tokens = _tokenize(query)
    if not q_tokens:
        return 0.0

    meta = doc.get("metadata", {})
    title_text = f"{meta.get('section_title', '')} {meta.get('section_path', '')} {meta.get('question_text', '')}".lower()
    body_text = (doc.get("page_content") or "").lower()
    haystack = f"{title_text}\n{body_text}"

    def token_forms(token: str) -> set[str]:
        forms = {token}
        if token == "eligibility":
            forms.add("eligible")
        elif token == "eligible":
            forms.add("eligibility")
        if token.endswith("ies") and len(token) > 4:
            forms.add(token[:-3] + "y")
        if token.endswith("s") and len(token) > 4:
            forms.add(token[:-1])
        return forms

    def has_token(token: str, text: str) -> bool:
        return any(
            re.search(rf"(?<![a-z0-9]){re.escape(form)}(?![a-z0-9])", text)
            for form in token_forms(token)
        )

    score = 0.0
    token_hits = sum(1 for token in q_tokens if has_token(token, haystack))
    if token_hits:
        score += token_hits / max(len(q_tokens), 1)

    for first, second in zip(q_tokens, q_tokens[1:]):
        phrase = f"{first} {second}"
        if phrase in title_text:
            score += 1.3
        elif phrase in body_text:
            score += 0.7

    # Boost content-bearing query terms without encoding domain- or document-specific vocabulary.
    for token in q_tokens:
        if len(token) >= 5 and has_token(token, haystack):
            score += 0.55

    query_acronyms = {
        token.lower()
        for token in re.findall(r"\b[A-Z][A-Z0-9&/-]{1,7}\b", query)
    }
    for acronym in query_acronyms:
        if re.search(rf"(?<![a-z0-9]){re.escape(acronym)}(?![a-z0-9])", title_text):
            score += 1.0
        elif re.search(rf"(?<![a-z0-9]){re.escape(acronym)}(?![a-z0-9])", body_text):
            score += 0.5
    return score


def _query_coverage(query: str, docs: list[dict], limit: int = 5) -> float:
    """Return how much content-bearing query vocabulary appears in the top docs."""
    tokens = [token for token in _tokenize(query) if len(token) >= 5]
    if not tokens:
        return 1.0

    haystack = "\n".join(
        f"{doc.get('metadata', {}).get('section_title', '')} "
        f"{doc.get('metadata', {}).get('section_path', '')} "
        f"{doc.get('metadata', {}).get('question_text', '')} "
        f"{doc.get('page_content', '')}"
        for doc in docs[:limit]
    ).lower()
    if not haystack:
        return 0.0
    hits = sum(1 for token in tokens if token in haystack)
    return hits / max(len(tokens), 1)


def _should_run_target_lexical_scan(query: str, candidates: list[dict], top_k: int, min_score: float) -> bool:
    """Run the expensive per-file lexical scan only when initial retrieval is weak."""
    if not candidates:
        return True

    best_score = max(float(doc.get("_score", 0.0)) for doc in candidates)
    if best_score < min_score:
        return True

    coverage = _query_coverage(query, candidates, limit=max(top_k, 3))
    detail_terms = {
        "author", "authors", "affiliation", "affiliations", "title", "abstract",
        "eligibility", "eligible", "criteria", "benefit", "benefits", "feature",
        "features", "problem", "problems", "limitation", "limitations", "methodology",
        "results", "conclusion", "conclusions", "future", "caveat", "caveats",
        "gotcha", "gotchas", "catch", "catches",
    }
    asks_for_specific_detail = bool(set(_tokenize(query)) & detail_terms)

    if asks_for_specific_detail and coverage < 0.35:
        return True
    if len(candidates) < min(top_k, 3) and coverage < 0.5:
        return True
    return False


def _should_fetch_intro_context(query: str, candidates: list[dict], min_score: float) -> bool:
    """Fetch intro/summary chunks lazily only when vector results do not already cover the request."""
    if not candidates:
        return True

    best_score = max(float(doc.get("_score", 0.0)) for doc in candidates)
    if best_score < min_score:
        return True

    lower = query.lower()
    asks_intro = bool(re.search(r"\b(about|overview|purpose|scope|summari[sz]e|summary)\b", lower))
    asks_identity = bool(re.search(r"\b(author|authors|affiliation|affiliations|title|abstract)\b", lower))
    if not asks_intro and not asks_identity:
        return False

    has_intro_candidate = any(
        doc.get("metadata", {}).get("chunk_kind") == "doc_summary"
        or (
            isinstance(doc.get("metadata", {}).get("chunk_index"), int)
            and doc.get("metadata", {}).get("chunk_index") < 2
        )
        for doc in candidates[:5]
    )
    coverage = _query_coverage(query, candidates, limit=5)

    if asks_identity and coverage < 0.35:
        return True
    if asks_intro and not has_intro_candidate and coverage < 0.50:
        return True
    return False


def _apply_source_precision(query: str, docs: list[dict], top_k: int) -> list[dict]:
    """
    Reduce source contamination after hybrid ranking.

    If table-row chunks from one file are clearly relevant, prioritize that
    table source envelope. This is intentionally metadata/score driven rather
    than hard-coded to a specific document.
    """
    if not docs:
        return docs
    q_tokens = set(_tokenize(query))
    if not q_tokens:
        return docs

    table_docs = [
        d for d in docs
        if str(d.get("metadata", {}).get("chunk_kind", "")).startswith("table_row")
        and _hybrid_score(query, d) >= 0.65
    ]
    if not table_docs:
        return docs

    by_file: dict[str, list[dict]] = defaultdict(list)
    for doc in table_docs:
        by_file[doc.get("metadata", {}).get("filename", "")].append(doc)

    dominant_file, dominant_docs = max(
        by_file.items(),
        key=lambda item: (len(item[1]), max(d.get("_score", 0.0) for d in item[1])),
    )
    if not dominant_file:
        return docs

    dominant_best = max(d.get("_score", 0.0) for d in dominant_docs)
    dominant_ranked = [d for d in docs if d.get("metadata", {}).get("filename") == dominant_file]
    other_ranked = [
        d for d in docs
        if d.get("metadata", {}).get("filename") != dominant_file
        and d.get("_score", 0.0) >= dominant_best - 0.08
    ]

    if len(dominant_ranked) >= min(2, top_k):
        return (dominant_ranked + other_ranked)[:max(top_k, len(dominant_ranked[:top_k]))]
    return docs


def _ensure_target_coverage(ranked_docs: list[dict], candidate_pool: list[dict], targeted_docs: list[str], top_k: int) -> list[dict]:
    """Ensure explicit multi-document targets are represented when candidates exist."""
    if len(targeted_docs) <= 1 or not candidate_pool:
        return ranked_docs

    by_target: dict[str, list[dict]] = {}
    for target in targeted_docs:
        target_candidates = [
            doc for doc in candidate_pool
            if doc.get("metadata", {}).get("filename") == target
        ]
        target_candidates.sort(key=lambda doc: doc.get("_score", 0.0), reverse=True)
        if target_candidates:
            by_target[target] = target_candidates

    if not by_target:
        return ranked_docs

    min_per_target = min(2, max(1, top_k // max(len(targeted_docs), 1)))
    protected = []
    for target in targeted_docs:
        protected.extend(by_target.get(target, [])[:min_per_target])

    combined = _dedupe_docs(protected + ranked_docs)
    protected = _dedupe_docs(protected)
    protected_ids = {
        (
            doc.get("metadata", {}).get("filename"),
            doc.get("metadata", {}).get("chunk_index"),
            doc.get("page_content", "")[:80],
        )
        for doc in protected
    }
    rest = [
        doc for doc in combined
        if (
            doc.get("metadata", {}).get("filename"),
            doc.get("metadata", {}).get("chunk_index"),
            doc.get("page_content", "")[:80],
        ) not in protected_ids
    ]
    rest.sort(key=lambda doc: doc.get("_score", 0.0), reverse=True)
    return (protected + rest)[:top_k]


def _dedupe_docs(docs: list[dict]) -> list[dict]:
    best_by_key: dict[tuple, dict] = {}
    order = []
    for doc in docs:
        meta = doc.get("metadata", {})
        key = (
            meta.get("doc_id") or meta.get("source") or meta.get("filename"),
            meta.get("chunk_index"),
            doc.get("page_content", "")[:160],
        )
        if key not in best_by_key:
            best_by_key[key] = doc
            order.append(key)
            continue
        current = best_by_key[key]
        current_rank = (
            current.get("_lexical_score", 0.0),
            current.get("_score", 0.0),
            current.get("_vector_score", 0.0),
        )
        next_rank = (
            doc.get("_lexical_score", 0.0),
            doc.get("_score", 0.0),
            doc.get("_vector_score", 0.0),
        )
        if next_rank > current_rank:
            best_by_key[key] = doc
    return [best_by_key[key] for key in order]


def _format_retrieved_docs(final_docs: list[dict]) -> list[str]:
    final_retrieved = []
    for d in final_docs:
        meta = d['metadata']
        filename = meta.get('filename', 'Unknown')
        path = meta.get('section_path', 'Root')
        title = meta.get('section_title') or path.split(" > ")[-1]
        raw_content = d['page_content']
        doc_type = meta.get('doc_type', 'general')
        content = re.sub(
            r'^\[Doc: .*? \| (?:Path|Section): .*?\](?:\n# .+?\n|\n)?',
            '',
            raw_content,
            count=1,
            flags=re.S,
        ).strip()

        chunk_kind = meta.get("chunk_kind", "qna" if doc_type == "qna" else "section")
        heading_level = meta.get("heading_level", meta.get("header_level", ""))
        chunk_index = meta.get("chunk_index", "")
        prev_index = meta.get("prev_index", -1)
        next_index = meta.get("next_index", -1)
        normalized = str(bool(meta.get("normalized", False))).lower()
        parser = meta.get("parser", "unknown")

        header_lines = [
            f"[Source: {filename}]",
            f"[DocType: {doc_type}]",
            f"[Parser: {parser}]",
            f"[ChunkKind: {chunk_kind}]",
            f"[Section: {title}]",
            f"[SectionPath: {path}]",
            f"[HeadingLevel: {heading_level}]",
            f"[ChunkIndex: {chunk_index}]",
            f"[Neighbors: prev={prev_index} next={next_index}]",
            f"[Normalized: {normalized}]",
        ]
        if meta.get("table_title"):
            header_lines.append(f"[TableTitle: {meta.get('table_title')}]")
        if meta.get("row_title"):
            header_lines.append(f"[RowTitle: {meta.get('row_title')}]")
        if doc_type == "qna" and meta.get("qa_pair_id"):
            header_lines.append(f"[QAPairID: {meta.get('qa_pair_id')}]")
        final_retrieved.append(f"{chr(10).join(header_lines)}\n\n{content}")
    return final_retrieved

async def retrieve_documents(state: AgentState):
    """Low-latency hybrid retrieval with bounded candidate work."""
    query = state['query']
    requested_targets = state.get('targeted_docs', []) or []
    context_action = state.get("context_action", "retrieve")
    previous_docs = state.get("documents", []) if context_action == "hybrid" else []
    retrieval_start = time.monotonic()

    if context_action == "answer_from_existing" and state.get("documents"):
        return {
            "documents": state.get("documents", []),
            "targeted_docs": requested_targets,
            "retrieval_metrics": {
                "skipped": True,
                "reason": "answer_from_existing",
                "total_ms": 0,
            },
        }

    readiness_start = time.monotonic()
    await ensure_rag_ready()
    readiness_ms = int((time.monotonic() - readiness_start) * 1000)

    store = get_vector_store()
    available_files = store.get_all_files() if requested_targets else []
    targeted_docs = [_resolve_target_filename(doc, available_files) for doc in requested_targets]
    model = OllamaClientWrapper.get_embedding_model_name()
    cfg = get_config()
    top_k = _effective_top_k(query, context_action, cfg)
    has_targets = bool(targeted_docs)
    query_plan = _query_variants(query, state.get('semantic_queries', []), targeted_docs)
    if available_files:
        query_plan = [
            {**plan, "target": _resolve_target_filename(plan.get("target"), available_files) if plan.get("target") else None}
            for plan in query_plan
        ]
    metrics = {
        "targeted_docs_requested": requested_targets,
        "targeted_docs_resolved": targeted_docs,
        "query_plan_count": len(query_plan),
        "readiness_ms": readiness_ms,
        "embedding_ms": 0,
        "vector_ms": 0,
        "vector_gather_ms": 0,
        "intro_ms": 0,
        "lexical_ms": 0,
        "lexical_scan_used": False,
        "fallback_ms": 0,
        "postprocess_ms": 0,
        "adjacent_ms": 0,
        "search_ms": 0,
        "fallback_used": False,
        "candidate_count": 0,
        "ranked_count": 0,
        "adjacent_context_count": 0,
        "reason": None,
    }
    vector_durations = []

    per_query = min(12 if has_targets else 18, max(top_k * (2 if has_targets else 3), top_k + 4))
    pool_limit = min(36 if has_targets else 56, per_query * max(1, len(query_plan)))
    embeddings_by_query: dict[str, list] = {}
    queries_to_embed = []
    for plan in query_plan:
        q = re.sub(r"\s+", " ", (plan.get("query") or query)).strip()
        if q == query and state.get("query_embedding"):
            embeddings_by_query[q] = state["query_embedding"]
        elif q:
            queries_to_embed.append(q)

    if queries_to_embed:
        emb_start = time.monotonic()
        embeddings_by_query.update(await get_cached_embeddings(queries_to_embed, model))
        metrics["embedding_ms"] = int((time.monotonic() - emb_start) * 1000)
        metrics["embedding_total_ms"] = metrics["embedding_ms"]

    search_start = time.monotonic()
    intro_terms = ["about", "overview", "purpose", "scope", "summarize", "summary", "author", "authors", "affiliation", "title", "abstract"]
    should_fetch_intro = any(term in query.lower() for term in intro_terms)

    async def fetch_intro(doc_name: str):
        intro_start = time.monotonic()
        try:
            intro_where = {"$and": [{"filename": {"$eq": doc_name}}, {"chunk_index": {"$lt": 2}}]}
            intro_results = await asyncio.to_thread(store.get_by_metadata, where=intro_where, limit=2)
            return [
                {"page_content": c, "metadata": intro_results['metadatas'][i], "_vector_score": 0.35}
                for i, c in enumerate(intro_results.get('documents') or [])
            ]
        except Exception as e:
            logger.debug(f"[RETRIEVER] Intro fetch skipped: {e}")
            return []
        finally:
            metrics["intro_ms"] += int((time.monotonic() - intro_start) * 1000)

    async def fetch_target_fallback(doc_name: str):
        """Guarantee targeted files contribute context when vector scores are weak."""
        fallback_start = time.monotonic()
        docs = []
        try:
            summary_results = await asyncio.to_thread(
                store.get_by_metadata,
                where={"$and": [{"filename": {"$eq": doc_name}}, {"chunk_kind": {"$eq": "doc_summary"}}]},
                limit=1,
            )
            docs.extend([
                {"page_content": c, "metadata": summary_results['metadatas'][i], "_vector_score": 0.30}
                for i, c in enumerate(summary_results.get('documents') or [])
            ])
        except Exception as e:
            logger.debug(f"[RETRIEVER] Summary fallback skipped for {doc_name}: {e}")

        try:
            intro_results = await asyncio.to_thread(
                store.get_by_metadata,
                where={"$and": [{"filename": {"$eq": doc_name}}, {"chunk_index": {"$lt": 3}}]},
                limit=3,
            )
            docs.extend([
                {"page_content": c, "metadata": intro_results['metadatas'][i], "_vector_score": 0.25}
                for i, c in enumerate(intro_results.get('documents') or [])
            ])
        except Exception as e:
            logger.debug(f"[RETRIEVER] Intro fallback skipped for {doc_name}: {e}")

        metrics["fallback_ms"] += int((time.monotonic() - fallback_start) * 1000)
        return docs

    async def fetch_target_lexical(doc_name: str):
        """Recover exact sections in an explicitly targeted file when embedding rank misses them."""
        lexical_start = time.monotonic()
        try:
            scan_limit = int(os.getenv("RAG_TARGET_LEXICAL_SCAN_LIMIT", "256"))
            result = await asyncio.to_thread(
                store.get_by_metadata,
                where={"filename": {"$eq": doc_name}},
                limit=scan_limit,
            )
        except Exception as e:
            logger.debug(f"[RETRIEVER] Target lexical scan skipped for {doc_name}: {e}")
            return []
        finally:
            metrics["lexical_ms"] += int((time.monotonic() - lexical_start) * 1000)

        matched_docs = []
        lexical_queries = [query]
        lexical_queries.extend(
            re.sub(r"\s+", " ", (plan.get("query") or "")).strip()
            for plan in query_plan
            if plan.get("target") == doc_name and plan.get("query")
        )
        lexical_queries = [q for i, q in enumerate(lexical_queries) if q and q not in lexical_queries[:i]]
        for content, meta in zip(result.get("documents") or [], result.get("metadatas") or []):
            if len((content or "").strip()) < 40:
                continue
            candidate = {
                "page_content": content,
                "metadata": meta,
                "_vector_score": 0.42,
                "_query": query,
            }
            lexical_score = max(_target_lexical_score(lexical_query, candidate) for lexical_query in lexical_queries)
            if lexical_score >= 1.0:
                candidate["_vector_score"] = 0.58 if lexical_score >= 1.5 else 0.48
                candidate["_lexical_score"] = lexical_score
                matched_docs.append(candidate)

        matched_docs.sort(key=lambda doc: (doc.get("_lexical_score", 0.0), _hybrid_score(query, doc)), reverse=True)
        return matched_docs[: min(4, top_k)]

    async def run_vector_query(plan: dict):
        q = re.sub(r"\s+", " ", (plan.get("query") or query)).strip()
        target_file = plan.get("target")
        q_embed = embeddings_by_query.get(q)
        if not q_embed:
            return []
        filters = {"filename": target_file} if target_file else None
        vec_start = time.monotonic()
        res = store.query(query_embeddings=q_embed, n_results=per_query, where=filters)
        vector_durations.append(int((time.monotonic() - vec_start) * 1000))
        docs = []
        for doc_list, metas, distances in zip(
            res.get('documents') or [],
            res.get('metadatas') or [],
            res.get('distances') or [],
        ):
            for doc_text, meta, distance in zip(doc_list, metas, distances):
                if len((doc_text or "").strip()) < 40:
                    continue
                docs.append({
                    "page_content": doc_text,
                    "metadata": meta,
                    "_vector_score": max(0.0, 1.0 - float(distance)),
                    "_query": q,
                })
        return docs

    async def fetch_adjacent_context(docs: list[dict]) -> list[dict]:
        """Pull immediate neighbors for strong targeted hits with thin/parent context."""
        if not has_targets or not docs:
            return []
        seen = {
            (
                d.get("metadata", {}).get("filename"),
                d.get("metadata", {}).get("chunk_index"),
            )
            for d in docs
        }
        neighbor_requests = []
        for doc in docs[:top_k]:
            meta = doc.get("metadata", {})
            filename = meta.get("filename")
            if not filename:
                continue
            text = doc.get("page_content", "")
            title_path = f"{meta.get('section_title', '')} {meta.get('section_path', '')}".lower()
            should_expand = (
                len(text) < 1200
                or any(term in title_path for term in ["overview", "stack", "architecture", "introduction"])
            )
            if not should_expand:
                continue
            neighbor_indices = []
            for key in ("prev_index", "next_index"):
                idx = meta.get(key)
                if isinstance(idx, int) and idx >= 0:
                    neighbor_indices.append(idx)
            for idx in neighbor_indices:
                key = (filename, idx)
                if key in seen:
                    continue
                seen.add(key)
                neighbor_requests.append((doc, filename, idx))

        async def fetch_neighbor(doc: dict, filename: str, idx: int):
            try:
                result = await asyncio.to_thread(
                    store.get_by_metadata,
                    where={"$and": [{"filename": {"$eq": filename}}, {"chunk_index": {"$eq": idx}}]},
                    limit=1,
                )
            except Exception as e:
                logger.debug(f"[RETRIEVER] Adjacent context fetch skipped for {filename}#{idx}: {e}")
                return []
            adjacent_docs = []
            docs_found = result.get("documents") or []
            metas_found = result.get("metadatas") or []
            for content, adjacent_meta in zip(docs_found, metas_found):
                if len((content or "").strip()) < 40:
                    continue
                adjacent_docs.append({
                    "page_content": content,
                    "metadata": adjacent_meta,
                    "_vector_score": max(0.0, doc.get("_vector_score", 0.0) - 0.06),
                    "_query": doc.get("_query", query),
                })
            return adjacent_docs

        if not neighbor_requests:
            return []
        batches = await asyncio.gather(*(fetch_neighbor(*request) for request in neighbor_requests))
        adjacent = [doc for batch in batches for doc in batch]
        return adjacent

    tasks = [run_vector_query(plan) for plan in query_plan]

    vector_gather_start = time.monotonic()
    batches = await asyncio.gather(*tasks)
    metrics["vector_gather_ms"] = int((time.monotonic() - vector_gather_start) * 1000)
    metrics["vector_ms"] = max(vector_durations) if vector_durations else 0
    metrics["vector_total_ms"] = sum(vector_durations)
    postprocess_start = time.monotonic()
    candidates = _dedupe_docs([doc for batch in batches for doc in batch])
    for doc in candidates:
        doc["_score"] = _hybrid_score(query, doc)
    candidates.sort(key=lambda d: d.get("_score", 0.0), reverse=True)
    min_score = float(os.getenv("RAG_HYBRID_MIN_SCORE_TARGETED" if has_targets else "RAG_HYBRID_MIN_SCORE", "0.20" if has_targets else "0.42"))

    if targeted_docs and should_fetch_intro and _should_fetch_intro_context(query, candidates, min_score):
        intro_batches = await asyncio.gather(*(fetch_intro(doc) for doc in targeted_docs))
        if intro_batches:
            candidates = _dedupe_docs([*candidates, *(doc for batch in intro_batches for doc in batch)])
            for doc in candidates:
                doc["_score"] = _hybrid_score(query, doc)
            candidates.sort(key=lambda d: d.get("_score", 0.0), reverse=True)

    if targeted_docs and _should_run_target_lexical_scan(query, candidates, top_k, min_score):
        metrics["lexical_scan_used"] = True
        lexical_batches = await asyncio.gather(*(fetch_target_lexical(doc) for doc in targeted_docs))
        if lexical_batches:
            candidates = _dedupe_docs([*candidates, *(doc for batch in lexical_batches for doc in batch)])
            for doc in candidates:
                doc["_score"] = _hybrid_score(query, doc)
            candidates.sort(key=lambda d: d.get("_score", 0.0), reverse=True)

    if candidates and candidates[0].get("_score", 0.0) < min_score:
        logger.info(f"[RETRIEVER] No strong evidence: best hybrid score {candidates[0].get('_score', 0.0):.3f} < {min_score}")
        if has_targets:
            candidates = candidates[:top_k]
            metrics["reason"] = "targeted_low_score_kept"
        else:
            candidates = []
            metrics["reason"] = "low_score_filtered"

    if has_targets and not candidates:
        fallback_batches = await asyncio.gather(*(fetch_target_fallback(doc) for doc in targeted_docs))
        candidates = _dedupe_docs([doc for batch in fallback_batches for doc in batch])
        for doc in candidates:
            doc["_score"] = _hybrid_score(query, doc)
        candidates.sort(key=lambda d: d.get("_score", 0.0), reverse=True)
        metrics["fallback_used"] = True
        metrics["reason"] = "targeted_fallback"

    metrics["candidate_count"] = len(candidates)
    candidates = candidates[:pool_limit]
    metrics["postprocess_ms"] = int((time.monotonic() - postprocess_start) * 1000)

    search_ms = int((time.monotonic() - search_start) * 1000)
    metrics["search_ms"] = search_ms
    logger.info(f"[RETRIEVER] Hybrid search produced {len(candidates)} candidates in {search_ms}ms.")

    if os.getenv("RAG_USE_RERANKER", "false").lower() == "true" and candidates:
        from backend.rag.reranker import Reranker
        rerank_cap = min(int(os.getenv("RAG_RERANK_CAP", "12")), len(candidates))
        rerank_start = time.monotonic()
        ranked_docs = await Reranker().rank(query, candidates[:rerank_cap], top_k=top_k)
        rerank_ms = int((time.monotonic() - rerank_start) * 1000)
        logger.info(f"[RETRIEVER] Cross-encoder reranked {rerank_cap} docs in {rerank_ms}ms.")
    else:
        ranked_docs = candidates[:top_k]
    adjacent_start = time.monotonic()
    adjacent_docs = await fetch_adjacent_context(ranked_docs)
    metrics["adjacent_ms"] = int((time.monotonic() - adjacent_start) * 1000)
    if adjacent_docs:
        for doc in adjacent_docs:
            doc["_score"] = _hybrid_score(query, doc)
        ranked_docs = _dedupe_docs(ranked_docs + adjacent_docs)
        ranked_docs.sort(key=lambda d: d.get("_score", 0.0), reverse=True)
        metrics["adjacent_context_count"] = len(adjacent_docs)
        ranked_docs = ranked_docs[:top_k]
    ranked_docs = _apply_source_precision(query, ranked_docs, top_k)
    before_coverage_files = {
        doc.get("metadata", {}).get("filename")
        for doc in ranked_docs
        if doc.get("metadata", {}).get("filename")
    }
    ranked_docs = _ensure_target_coverage(ranked_docs, candidates, targeted_docs, top_k)
    after_coverage_files = {
        doc.get("metadata", {}).get("filename")
        for doc in ranked_docs
        if doc.get("metadata", {}).get("filename")
    }
    metrics["target_coverage_added"] = max(0, len(after_coverage_files - before_coverage_files))
    metrics["ranked_count"] = len(ranked_docs)

    final_docs = stitch_fragments(ranked_docs)
    final_docs = stitch_qna_fragments(final_docs)
    total_ms = int((time.monotonic() - retrieval_start) * 1000)
    metrics["total_ms"] = total_ms
    logger.info(f"[RETRIEVER] Retrieval complete in {total_ms}ms.")
    formatted_docs = _format_retrieved_docs(final_docs[:top_k])
    if previous_docs:
        combined = []
        seen = set()
        for doc in previous_docs + formatted_docs:
            key = re.sub(r"\s+", " ", doc or "").strip()[:500]
            if key and key not in seen:
                seen.add(key)
                combined.append(doc)
        formatted_docs = combined[: max(top_k, len(previous_docs))]

    return {
        "documents": formatted_docs,
        "targeted_docs": targeted_docs,
        "retrieval_metrics": metrics,
    }
