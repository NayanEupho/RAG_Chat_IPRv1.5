from backend.graph.state import AgentState
from backend.llm.client import OllamaClientWrapper
from backend.graph.nodes.constants import CHAT_KEYWORDS, RAG_KEYWORDS
from backend.config import get_config
from langchain_core.messages import HumanMessage
import logging
import json
import re
import asyncio
import time

logger = logging.getLogger(__name__)

_ACRONYM_CACHE = {"loaded_at": 0.0, "terms": set()}
_ACRONYM_STOPWORDS = {
    "A", "AN", "AND", "ARE", "AS", "AT", "BY", "DO", "DID", "DOES", "FOR",
    "FROM", "GO", "HAS", "HAVE", "IF", "IN", "IS", "IT", "NO", "OF", "ON",
    "OR", "THE", "THIS", "THAT", "TO", "UP", "US", "WAS", "WERE", "WHAT",
    "WHO", "WITH",
}

_QUERY_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "based", "be", "by", "can", "could",
    "describe", "details", "does", "explain", "find", "for", "from", "give",
    "how", "in", "is", "it", "me", "of", "on", "please", "show", "summarize",
    "summary", "tell", "that", "the", "this", "to", "what", "when", "where",
    "which", "who", "why", "with"
}

_DOC_DETAIL_TERMS = {
    "author", "authors", "affiliation", "affiliations", "title", "abstract",
    "summary", "summarize", "summarise", "overview", "details", "more",
    "eligibility", "eligible", "criteria", "benefit", "benefits", "limitation",
    "limitations", "conclusion", "conclusions", "methodology", "results",
    "future", "work", "gotcha", "gotchas", "catch", "catches", "caveat",
    "caveats", "important", "points", "keep", "mind",
}

_LOW_INFORMATION_FOLLOWUP_RE = re.compile(
    r"\b(tell me more|more details|explain more|elaborate|expand|"
    r"what about|summari[sz]e everything|summary|key points|important points|"
    r"gotchas?|catches|caveats?)\b",
    re.IGNORECASE,
)


def _extract_mentions(query: str, filenames: list[str] | None = None) -> list[str]:
    """
    Resolve @mentions against indexed filenames first.

    The old regex stopped at dots, so @file.pdf could become "file". Matching
    against the vector-store inventory preserves exact filenames, including
    spaces and extensions.
    """
    mentions = []
    query_lower = query.lower()
    try:
        if filenames is None:
            from backend.rag.store import get_vector_store
            filenames = get_vector_store().get_all_files()
        for filename in sorted(filenames, key=len, reverse=True):
            if f"@{filename.lower()}" in query_lower:
                mentions.append(filename)
    except Exception as e:
        logger.debug(f"[PLANNER] Indexed mention resolution failed: {e}")

    if mentions:
        return mentions

    fallback = re.findall(r"@([^\s@,;:!?]+(?:\s+[^\s@,;:!?]+)*?)(?=\s|[,;:!?]|$)", query)
    return [m.strip().rstrip(".,") for m in fallback if m.strip() and ('.' in m or len(m) > 3)]


def _extract_named_doc_references(query: str, filenames: list[str] | None = None) -> list[str]:
    """Resolve plain-language document references like 'the FAQ document'."""
    query_lower = query.lower()
    matches = []
    try:
        if filenames is None:
            from backend.rag.store import get_vector_store
            filenames = get_vector_store().get_all_files()
    except Exception as e:
        logger.debug(f"[PLANNER] Named doc resolution failed: {e}")
        return []

    for filename in sorted(filenames, key=len, reverse=True):
        lower_name = filename.lower()
        stem = re.sub(r"\.[a-z0-9]+$", "", lower_name)
        parts = [p for p in re.split(r"[^a-z0-9]+", stem) if len(p) >= 3]
        if lower_name in query_lower or stem in query_lower:
            matches.append(filename)
            continue
        # High-signal shorthand: FAQ, report, policy etc. Avoid matching
        # generic words unless they identify a single indexed file.
        strong_parts = [
            p for p in parts
            if p not in {"pdf", "doc", "document", "general", "upload", "docs"}
            and (len(p) >= 4 or p in {"faq", "qna"})
        ]
        if any(re.search(rf"\b{re.escape(part)}\b", query_lower) for part in strong_parts):
            matches.append(filename)

    # If a shorthand matched multiple files, keep only exact/stem references.
    if len(matches) > 1:
        exact = [f for f in matches if f.lower() in query_lower or re.sub(r"\.[a-z0-9]+$", "", f.lower()) in query_lower]
        return exact
    return matches


def _clean_query_text(query: str, mentions: list[str]) -> str:
    cleaned = query
    for mention in mentions:
        cleaned = re.sub(rf"@{re.escape(mention)}", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+([?.!,;:])", r"\1", cleaned)
    cleaned = re.sub(r"\b(in|from|of|the)\s*([?.!,;:])", r"\2", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bwhat does\s+say\b", "what does the document say", cleaned, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", cleaned).strip(" \t\r\n?.!,;:")


def _keyword_query(query: str) -> str:
    words = re.findall(r"[A-Za-z0-9][A-Za-z0-9&./-]*", query.lower())
    keywords = [w for w in words if len(w) > 2 and w not in _QUERY_STOPWORDS]
    return " ".join(keywords[:12])


def _topic_terms(text: str) -> set[str]:
    terms = set()
    for token in re.findall(r"[A-Za-z0-9][A-Za-z0-9&/-]*", (text or "").lower()):
        normalized = token.strip("-_/")
        if len(normalized) >= 3 and normalized not in _QUERY_STOPWORDS:
            terms.add(normalized)
    return terms


def _previous_topic_terms(state: AgentState) -> set[str]:
    terms = _topic_terms(_previous_substantive_user_query(state) or _previous_user_query(state))
    for target in _recent_target_context(state):
        terms.update(_topic_terms(re.sub(r"\.[a-z0-9]+$", "", target.lower())))
    return terms


def _indexed_acronyms(ttl_seconds: float = 300.0) -> set[str]:
    now = time.monotonic()
    if _ACRONYM_CACHE["terms"] and (now - _ACRONYM_CACHE["loaded_at"]) < ttl_seconds:
        return set(_ACRONYM_CACHE["terms"])

    terms = set()
    try:
        from backend.rag.store import get_vector_store
        store = get_vector_store()
        store.refresh_collection(force=False)
        results = store.collection.get(include=["metadatas"], limit=1000)
        for meta in results.get("metadatas") or []:
            if not meta:
                continue
            haystack = " ".join(str(meta.get(k, "")) for k in [
                "filename", "section_title", "section_path", "question_text", "doc_type"
            ])
            for token in re.findall(r"\b[A-Z][A-Z0-9&/-]{1,7}\b", haystack):
                clean = token.strip("-/&")
                if clean and clean not in _ACRONYM_STOPWORDS and not clean.isdigit():
                    terms.add(clean.lower())
    except Exception as e:
        logger.debug(f"[PLANNER] Indexed acronym scan failed: {e}")

    _ACRONYM_CACHE["terms"] = terms
    _ACRONYM_CACHE["loaded_at"] = now
    return set(terms)


def _query_indexed_acronyms(query: str) -> set[str]:
    query_terms = {
        token.lower()
        for token in re.findall(r"\b[A-Za-z][A-Za-z0-9&/-]{1,7}\b", query)
        if token.upper() not in _ACRONYM_STOPWORDS
    }
    if not query_terms:
        return set()
    return query_terms & _indexed_acronyms()


def _contains_keyword(query: str, keyword: str) -> bool:
    return bool(re.search(rf"(?<![A-Za-z0-9]){re.escape(keyword.lower())}(?![A-Za-z0-9])", query.lower()))


def _build_semantic_queries(query: str, targets: list[str] | None = None, max_variants: int = 3) -> list[dict]:
    """
    Build a compact deterministic retrieval plan.

    This avoids an LLM planning call on high-confidence RAG paths while still
    giving the retriever multiple lexical views for recall and reranking.
    """
    base_query = re.sub(r"\s+", " ", query).strip()
    keyword_query = _keyword_query(base_query)
    variants = []

    if base_query:
        variants.append(base_query)
    if keyword_query and keyword_query.lower() != base_query.lower():
        variants.append(keyword_query)

    lower = base_query.lower()
    if any(term in lower for term in ["eligibility", "criteria", "eligible", "who can"]):
        variants.append(f"{keyword_query or base_query} conditions requirements")
    elif any(term in lower for term in ["summary", "summarize", "overview", "about"]):
        variants.append(f"{keyword_query or base_query} overview purpose scope summary")
    elif any(term in lower for term in ["benefit", "allowance", "entitlement"]):
        variants.append(f"{keyword_query or base_query} benefits entitlement allowance")

    deduped = []
    seen = set()
    for variant in variants:
        normalized = variant.strip().lower()
        if normalized and normalized not in seen:
            seen.add(normalized)
            deduped.append(variant.strip())

    deduped = deduped[:max_variants] or [base_query]
    target_list = targets if targets else [None]
    return [{"query": variant, "target": target} for target in target_list for variant in deduped]


def _chat_result(query: str, documents: list | None = None, query_embedding=None) -> dict:
    return {
        "intent": "chat",
        "query": query,
        "targeted_docs": [],
        "documents": documents or [],
        "semantic_queries": [],
        "query_embedding": query_embedding,
        "retrieval_metrics": {},
        "context_action": "none",
    }


def _previous_user_query(state: AgentState) -> str:
    for msg in reversed(state.get("messages", [])[:-1]):
        if isinstance(msg, HumanMessage):
            return msg.content
    return ""


def _previous_substantive_user_query(state: AgentState) -> str:
    vague_patterns = [
        r"^\s*tell me more\s*$",
        r"^\s*more\s*$",
        r"^\s*details\s*$",
        r"^\s*what about\b.*$",
        r"^\s*summarize everything\s*$",
        r"^\s*summarise everything\s*$",
    ]
    for msg in reversed(state.get("messages", [])[:-1]):
        if not isinstance(msg, HumanMessage):
            continue
        content = msg.content.strip()
        lower = content.lower()
        if any(re.match(pattern, lower) for pattern in vague_patterns):
            continue
        return content
    return ""


def _has_reference_pronoun(query: str) -> bool:
    return bool(re.search(r"\b(it|this|that|these|those|them)\b", query.lower()))


def _is_explicit_chat_shift(query: str) -> bool:
    lower = query.lower()
    return any(phrase in lower for phrase in [
        "forget the docs",
        "forget the documents",
        "ignore the docs",
        "ignore the documents",
        "without the docs",
        "not from the docs",
        "answer normally",
        "normal chat",
        "usual chat",
        "for a moment",
    ])


def _is_general_chat_query(query: str) -> bool:
    lower = query.lower().strip()
    return bool(re.search(r"\bcapital of\b", lower)) or any(phrase in lower for phrase in [
        "fun fact",
        "tell me a joke",
        "how are you",
        "weather today",
    ])


def _recent_target_context(state: AgentState) -> list[str]:
    return state.get("targeted_docs") or state.get("last_targeted_docs") or []


def _has_followup_signal(lower: str) -> bool:
    followup_terms = [
        "more", "details", "eligibility", "criteria", "benefit", "benefits",
        "limitations", "conclusions", "methodology", "future work", "compare",
        "summarize", "summarise", "summary", "everything", "author", "authors",
        "affiliation", "affiliations", "title", "abstract", "dataset", "results",
        "gotcha", "gotchas", "catch", "catches", "caveat", "caveats",
    ]
    return _has_reference_pronoun(lower) or any(term in lower for term in followup_terms)


def _is_target_correction(query: str, mentions: list[str]) -> bool:
    if not mentions:
        return False
    return bool(re.search(r"\b(i\s+meant|i\s+ment|meant|actually|rather|instead)\b", query.lower()))


def _is_rag_followup(query: str, state: AgentState) -> bool:
    lower = query.lower().strip()
    if _is_explicit_chat_shift(lower) or _is_general_chat_query(lower):
        return False
    recent_targets = _recent_target_context(state)
    if state.get("intent") not in ["direct_rag", "specific_doc_rag"] and not state.get("documents") and not recent_targets:
        return False
    if len(lower) <= 80:
        return _has_followup_signal(lower)
    return _has_reference_pronoun(lower) or any(term in lower for term in [
        "more", "details", "eligibility", "criteria", "benefit", "limitations",
        "conclusions", "methodology", "future work", "compare", "author",
        "authors", "affiliation", "title", "abstract",
    ])


def _contextual_followup_query(query: str, state: AgentState) -> str:
    lower = query.lower()
    previous = _previous_substantive_user_query(state) or _previous_user_query(state)
    recent_targets = _recent_target_context(state)
    if previous and (
        _has_reference_pronoun(lower)
        or re.search(r"\b(tell me more|more details|summari[sz]e everything|summary|what about)\b", lower)
        or (recent_targets and len(lower) <= 120 and _has_followup_signal(lower))
    ):
        previous_mentions = _extract_mentions(previous)
        previous = _clean_query_text(previous, previous_mentions) or previous
        return f"{previous} {query}"
    return query


def _target_correction_query(query: str, mentions: list[str], state: AgentState) -> str:
    previous = _previous_substantive_user_query(state) or _previous_user_query(state)
    if not previous:
        return query
    previous_mentions = _extract_mentions(previous)
    cleaned_previous = _clean_query_text(previous, previous_mentions) or previous
    cleaned_correction = _clean_query_text(query, mentions)
    if cleaned_correction and not re.search(r"\b(i\s+meant|i\s+ment|meant|actually|rather|instead)\b", cleaned_correction.lower()):
        return f"{cleaned_previous} {cleaned_correction}"
    return cleaned_previous


def _looks_like_new_subject(query: str, state: AgentState) -> bool:
    query_terms = _topic_terms(query) - _DOC_DETAIL_TERMS
    if len(query_terms) < 2:
        return False
    previous_terms = _previous_topic_terms(state)
    if not previous_terms:
        return False
    return len(query_terms & previous_terms) == 0


def _should_reuse_target_context(query: str, state: AgentState) -> bool:
    lower = query.lower().strip()
    if not _recent_target_context(state):
        return False
    if _is_explicit_chat_shift(lower) or _is_general_chat_query(lower):
        return False
    if _has_reference_pronoun(lower) or _LOW_INFORMATION_FOLLOWUP_RE.search(lower):
        return True
    if _looks_like_new_subject(query, state):
        return False
    return _has_followup_signal(lower)


def _is_contextual_summary_request(query: str, state: AgentState) -> bool:
    lower = query.lower().strip()
    if not re.search(r"\b(summari[sz]e everything|summary of everything|sum up everything)\b", lower):
        return False
    previous = _previous_substantive_user_query(state)
    if not previous:
        return bool(state.get("documents"))
    previous_lower = previous.lower()
    return bool(state.get("documents")) or any(_contains_keyword(previous_lower, k) for k in RAG_KEYWORDS)


def _context_action_for_followup(query: str, state: AgentState, mentions: list[str] | None = None) -> str:
    lower = query.lower().strip()
    if not state.get("documents"):
        return "retrieve"
    if re.search(r"\b(compare|versus|vs\.?|including|exceptions|edge cases|full details|everything)\b", lower):
        return "hybrid"
    if re.search(r"\b(exact|rule|faq|eligibility|eligible|criteria|what about|which|where|when|how many|author|authors|affiliation|title|abstract)\b", lower):
        return "retrieve"
    if mentions:
        if re.search(r"\b(technolog(?:y|ies)|methodology|conclusions?|limitations?|future work|benefits?|summary|summari[sz]e)\b", lower):
            return "retrieve"
        if re.search(r"\b(tell me more|more details|explain more|elaborate|expand)\b", lower):
            return "answer_from_existing"
        return "retrieve"
    if re.search(r"\b(tell me more|more details|explain more|elaborate|what does that mean|explain this|expand)\b", lower):
        return "answer_from_existing"
    if _has_reference_pronoun(lower) and len(lower) <= 80:
        return "answer_from_existing"
    return "retrieve"


async def _guardrail_check(query: str, embed_model: str):
    """Vector guardrail: returns (chat_result_or_none, query_embedding)."""
    from backend.graph.nodes.retriever import get_cached_embedding
    from backend.rag.store import get_vector_store
    try:
        q_emb = await get_cached_embedding(query, embed_model)
        if q_emb:
            store = get_vector_store()
            results = store.query(query_embeddings=q_emb, n_results=1)
            distances = results.get('distances', [[1.0]])[0]
            config = get_config()
            threshold = config.rag_confidence_threshold
            if len(distances) > 0 and distances[0] > threshold:
                logger.info(f"[PLANNER] Guardrail: dist {distances[0]} > {threshold}. -> Chat.")
                return _chat_result(query, query_embedding=q_emb), q_emb
    except Exception as e:
        logger.debug(f"[PLANNER] Guardrail failed: {e}")
    return None, None


async def planner_node(state: AgentState):
    """
    The Planner Node (Fused Mode).
    
    In 'Fused' mode, this single node replaces the sequential chain of:
    Router + Rewriter + sub-query generation, saving ~60% pre-retrieval latency.
    """
    original_query = state['messages'][-1].content
    mode = state.get('mode', 'auto').lower()
    
    # ---------------------------------------------------------
    # 1. FAST PATHS (Zero LLM Latency)
    # ---------------------------------------------------------
    if mode == 'chat':
        logger.info("[PLANNER] Mode: Forced Chat")
        return _chat_result(original_query, documents=state.get('documents', []))

    if mode == 'auto' and "@" not in original_query:
        query_lower = original_query.lower()
        if _is_explicit_chat_shift(original_query) or _is_general_chat_query(original_query):
            logger.info("[PLANNER] Fast-Path: Chat (general/chat-shift query)")
            return _chat_result(original_query)
        for k in CHAT_KEYWORDS:
            if _contains_keyword(query_lower, k):
                logger.info(f"[PLANNER] Fast-Path: Chat (Keyword: '{k}')")
                return _chat_result(original_query)

    available_files: list[str] | None = None
    try:
        from backend.rag.store import get_vector_store
        available_files = get_vector_store().get_all_files()
    except Exception as e:
        logger.debug(f"[PLANNER] File inventory lookup failed: {e}")
        available_files = []

    mentions = _extract_mentions(original_query, available_files)
    if not mentions:
        mentions = _extract_named_doc_references(original_query, available_files)

    if mode == 'auto' and not mentions and "@" not in original_query:
        query_lower = original_query.lower()
        if _is_explicit_chat_shift(original_query) or _is_general_chat_query(original_query):
            logger.info("[PLANNER] Fast-Path: Chat (general/chat-shift query)")
            return _chat_result(original_query)
        for k in CHAT_KEYWORDS:
            if _contains_keyword(query_lower, k):
                logger.info(f"[PLANNER] Fast-Path: Chat (Keyword: '{k}')")
                return _chat_result(original_query)

    cleaned_query = _clean_query_text(original_query, mentions)
    previous_targets = _recent_target_context(state)

    forced_intent = None
    if mode == 'rag' or mentions:
        forced_intent = "specific_doc_rag" if mentions else "direct_rag"
        logger.info(f"[PLANNER] Mode: Forced RAG / Mentions: {mentions}")
        retrieval_query = _target_correction_query(original_query, mentions, state) if _is_target_correction(original_query, mentions) else (cleaned_query or original_query)
        semantic_queries = _build_semantic_queries(retrieval_query, mentions, max_variants=2 if len(mentions) > 1 else 3)
        return {
            "intent": forced_intent,
            "query": retrieval_query,
            "targeted_docs": mentions,
            "semantic_queries": semantic_queries,
            "documents": [],
            "query_embedding": None,
            "context_action": "retrieve",
        }

    elif mode == 'auto':
        query_lower = original_query.lower()

        if _is_explicit_chat_shift(original_query) or _is_general_chat_query(original_query):
            logger.info("[PLANNER] Fast-Path: Chat (general/chat-shift query)")
            return _chat_result(original_query)

        for k in CHAT_KEYWORDS:
            if not mentions and _contains_keyword(query_lower, k):
                logger.info(f"[PLANNER] Fast-Path: Chat (Keyword: '{k}')")
                return _chat_result(original_query)

        if not mentions and _is_rag_followup(original_query, state):
            followup_query = _contextual_followup_query(cleaned_query or original_query, state)
            context_action = _context_action_for_followup(original_query, state, previous_targets)
            if previous_targets and _should_reuse_target_context(original_query, state):
                logger.info(f"[PLANNER] Fast-Path: Targeted RAG follow-up ({previous_targets})")
                semantic_queries = _build_semantic_queries(followup_query, previous_targets, max_variants=3)
                return {
                    "intent": "specific_doc_rag",
                    "query": followup_query,
                    "targeted_docs": previous_targets,
                    "semantic_queries": semantic_queries,
                    "documents": state.get("documents", []) if context_action in {"answer_from_existing", "hybrid"} else [],
                    "query_embedding": None,
                    "context_action": context_action,
                }

            logger.info("[PLANNER] Fast-Path: Direct RAG follow-up")
            semantic_queries = _build_semantic_queries(followup_query)
            return {
                "intent": "direct_rag",
                "query": followup_query,
                "targeted_docs": [],
                "semantic_queries": semantic_queries,
                "documents": state.get("documents", []) if context_action in {"answer_from_existing", "hybrid"} else [],
                "query_embedding": None,
                "context_action": context_action,
            }

        indexed_acronyms = _query_indexed_acronyms(original_query)
        if indexed_acronyms:
            logger.info(f"[PLANNER] Fast-Path: Direct RAG (indexed acronym: {sorted(indexed_acronyms)})")
            semantic_queries = _build_semantic_queries(cleaned_query or original_query, max_variants=2)
            return {
                "intent": "direct_rag",
                "query": cleaned_query or original_query,
                "targeted_docs": [],
                "semantic_queries": semantic_queries,
                "documents": [],
                "query_embedding": None,
                "context_action": "retrieve",
            }

        if not mentions and _is_contextual_summary_request(original_query, state):
            followup_query = _contextual_followup_query(cleaned_query or original_query, state)
            logger.info("[PLANNER] Fast-Path: Direct RAG contextual summary")
            semantic_queries = _build_semantic_queries(followup_query)
            return {
                "intent": "direct_rag",
                "query": followup_query,
                "targeted_docs": [],
                "semantic_queries": semantic_queries,
                "documents": state.get("documents", []),
                "query_embedding": None,
                "context_action": "hybrid",
            }

        for k in RAG_KEYWORDS:
            if _contains_keyword(query_lower, k):
                embed_model = OllamaClientWrapper.get_embedding_model_name()
                guardrail_result, query_embedding = await _guardrail_check(cleaned_query or original_query, embed_model)
                if guardrail_result is not None:
                    return guardrail_result

                logger.info(f"[PLANNER] Fast-Path: Direct RAG (Keyword: '{k}')")
                semantic_queries = _build_semantic_queries(cleaned_query or original_query)
                return {
                    "intent": "direct_rag",
                    "query": cleaned_query or original_query,
                    "targeted_docs": [],
                    "semantic_queries": semantic_queries,
                    "documents": [],
                    "query_embedding": query_embedding,
                    "context_action": "retrieve",
                }

    # ---------------------------------------------------------
    # 2. PARALLEL: Embedding (guardrail) + LLM (mega-prompt)
    # ---------------------------------------------------------
    embed_model = OllamaClientWrapper.get_embedding_model_name()

    async def _do_llm():
        history_summary = ""
        for m in state['messages'][-3:-1]:
            role = "User" if isinstance(m, HumanMessage) else "Assistant"
            history_summary += f"{role}: {m.content[:200]}...\n"

        system_prompt = (
            "You are a RAG Planner. Output JSON: intent (rag/chat), rewritten_query, semantic_queries.\n"
            "Intent: 'rag' only for questions about indexed/uploaded documents or follow-ups to a RAG answer.\n"
            "Intent: 'chat' for casual, creative, or general world-knowledge questions unrelated to documents.\n"
            "Rewrite: resolve pronouns, make standalone.\n"
            "Semantic queries: if rag, generate 2-3 specific search queries; if chat, empty list [].\n"
            "Context action: answer_from_existing for simple 'tell me more' follow-ups, retrieve for new specific facts, hybrid for compare/full details.\n"
            "Output valid JSON only: {\"intent\": \"rag\"|\"chat\", \"rewritten_query\": \"...\", \"semantic_queries\": [{\"query\": \"...\", \"target\": null}], \"context_action\": \"answer_from_existing\"|\"retrieve\"|\"hybrid\"}"
        )
        mode_hint = f"Mode: {mode.upper()}" if mode != 'auto' else "Mode: Auto"
        target_hint = f"Targets: {', '.join(mentions)}" if mentions else ""
        user_prompt = f"History:\n{history_summary}\n{mode_hint}\n{target_hint}\nQuery: {original_query}"

        client = OllamaClientWrapper.get_chat_model()
        response = await client.ainvoke([
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ], format="json")
        return json.loads(response.content)

    needs_guardrail = mode == 'auto' and not mentions
    embed_task = asyncio.create_task(_guardrail_check(cleaned_query, embed_model)) if needs_guardrail else None
    llm_task = asyncio.create_task(_do_llm())

    plan = await llm_task

    if embed_task:
        guardrail_result, query_embedding = await embed_task
        if guardrail_result is not None:
            return guardrail_result
    else:
        query_embedding = None

    # ---------------------------------------------------------
    # 3. POST-PROCESSING
    # ---------------------------------------------------------
    try:
        intent = (plan.get("intent") or "rag").lower()
        if forced_intent:
            intent = "rag"

        final_intent = "chat"
        if intent == "rag":
            final_intent = "specific_doc_rag" if mentions else "direct_rag"

        semantic_queries = plan.get("semantic_queries", [])
        if final_intent != "chat" and not semantic_queries:
            rewritten = plan.get("rewritten_query", original_query)
            semantic_queries = [{"query": rewritten, "target": m} for m in (mentions if mentions else [None])]
        context_action = plan.get("context_action") or "retrieve"
        if context_action not in {"answer_from_existing", "retrieve", "hybrid"}:
            context_action = "retrieve"
        if final_intent == "chat":
            context_action = "none"

        logger.info(f"[PLANNER] Plan: {final_intent} | {len(semantic_queries)} sub-queries")

        docs_value = state.get('documents', []) if final_intent == "chat" or context_action in {"answer_from_existing", "hybrid"} else []

        return {
            "intent": final_intent,
            "query": plan.get("rewritten_query", cleaned_query),
            "targeted_docs": mentions,
            "semantic_queries": semantic_queries,
            "documents": docs_value,
            "query_embedding": query_embedding,
            "retrieval_metrics": {} if final_intent == "chat" else state.get("retrieval_metrics", {}),
            "context_action": context_action,
        }
    except Exception as e:
        logger.error(f"[PLANNER] Planning failed: {e}. Fallback to Safe RAG.")
        return {
            "intent": "direct_rag",
            "query": original_query,
            "targeted_docs": mentions,
            "semantic_queries": [{"query": original_query, "target": m} for m in (mentions if mentions else [None])],
            "documents": [],
            "query_embedding": None,
            "context_action": "retrieve",
        }
