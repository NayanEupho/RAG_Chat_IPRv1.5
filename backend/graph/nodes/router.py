"""
Intent Routing Node
-------------------
The 'Air Traffic Control' of the graph. It uses a hierarchy of decision layers:
1. Hard-coded mode overrides (Forced Chat/RAG).
2. Regex-based @mention detection.
3. Keyword fast-paths.
4. Vector-based confidence guardrails.
5. Semantic LLM classification.
"""

from backend.graph.state import AgentState
from backend.graph.nodes.constants import CHAT_KEYWORDS, RAG_KEYWORDS
from langchain_core.messages import HumanMessage, AIMessage
import re
import json
import logging

logger = logging.getLogger(__name__)

def extract_mentions(query: str) -> list[str]:
    """Resolve @mentions against indexed filenames, with a regex fallback."""
    mentions = []
    query_lower = query.lower()
    try:
        from backend.rag.store import get_vector_store
        for filename in sorted(get_vector_store().get_all_files(), key=len, reverse=True):
            if f"@{filename.lower()}" in query_lower:
                mentions.append(filename)
    except Exception as e:
        logger.debug(f"[ROUTER] Indexed mention resolution failed: {e}")

    if mentions:
        return mentions

    fallback = re.findall(r"@([^\s@,;:!?]+(?:\s+[^\s@,;:!?]+)*?)(?=\s|[,;:!?]|$)", query)
    return [m.strip().rstrip(".,") for m in fallback if m.strip() and ('.' in m or len(m) > 3)]


def extract_named_doc_references(query: str) -> list[str]:
    """Resolve plain-language document references like 'the FAQ document'."""
    query_lower = query.lower()
    matches = []
    try:
        from backend.rag.store import get_vector_store
        filenames = get_vector_store().get_all_files()
    except Exception as e:
        logger.debug(f"[ROUTER] Named doc resolution failed: {e}")
        return []

    for filename in sorted(filenames, key=len, reverse=True):
        lower_name = filename.lower()
        stem = re.sub(r"\.[a-z0-9]+$", "", lower_name)
        parts = [p for p in re.split(r"[^a-z0-9]+", stem) if len(p) >= 3]
        if lower_name in query_lower or stem in query_lower:
            matches.append(filename)
            continue
        strong_parts = [
            p for p in parts
            if p not in {"pdf", "doc", "document", "general", "upload", "docs"}
            and (len(p) >= 4 or p in {"faq", "qna"})
        ]
        if any(re.search(rf"\b{re.escape(part)}\b", query_lower) for part in strong_parts):
            matches.append(filename)

    if len(matches) > 1:
        exact = [f for f in matches if f.lower() in query_lower or re.sub(r"\.[a-z0-9]+$", "", f.lower()) in query_lower]
        return exact
    return matches


def _chat_result(query: str, documents: list | None = None, query_embedding=None) -> dict:
    return {
        "intent": "chat",
        "query": query,
        "targeted_docs": [],
        "documents": documents or [],
        "semantic_queries": [],
        "query_embedding": query_embedding,
        "retrieval_metrics": {},
    }


def _contains_keyword(query: str, keyword: str) -> bool:
    return bool(re.search(rf"(?<![A-Za-z0-9]){re.escape(keyword.lower())}(?![A-Za-z0-9])", query.lower()))


def remove_mentions(query: str, mentions: list[str]) -> str:
    cleaned = query
    for mention in mentions:
        cleaned = re.sub(rf"@{re.escape(mention)}", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+([?.!,;:])", r"\1", cleaned)
    cleaned = re.sub(r"\b(in|from|of|the)\s*([?.!,;:])", r"\2", cleaned, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", cleaned).strip(" \t\r\n?.!,;:")


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


async def route_query(state: AgentState):
    """
    Analyzes the query and user-selected mode to determine intent.
    """
    original_query = state['messages'][-1].content
    query_lower = original_query.lower()
    mode = state.get('mode', 'auto').lower()
    
    # --- STEP 0: FORCED MODES ---
    if mode == 'chat':
        # Even if they select @file, if they forced 'Chat', we honor the mode for pure LLM interaction
        logger.info("[ROUTER] Mode: Forced Chat")
        # Preserve documents from previous RAG turns for source persistence
        return _chat_result(original_query, documents=state.get('documents', []))

    mentions = extract_mentions(original_query)
    if not mentions:
        mentions = extract_named_doc_references(original_query)
    cleaned_query = remove_mentions(original_query, mentions)

    if mode == 'auto' and not mentions and "@" not in original_query:
        if _is_explicit_chat_shift(original_query) or _is_general_chat_query(original_query):
            logger.info("[ROUTER] Auto Fast-Path: chat (general/chat-shift query)")
            return _chat_result(original_query)
        for keyword in CHAT_KEYWORDS:
            if _contains_keyword(query_lower, keyword):
                logger.info(f"[ROUTER] Auto Fast-Path: chat (Keyword: '{keyword}')")
                return _chat_result(original_query, documents=state.get('documents', []))

    if mode == 'rag':
        logger.info(f"[ROUTER] Mode: Forced RAG (Mentions: {mentions})")
        return {
            "intent": "specific_doc_rag" if mentions else "direct_rag",
            "query": cleaned_query if mentions else original_query,
            "targeted_docs": mentions,
            "documents": [],
            "semantic_queries": [],
            "query_embedding": None
        }

    # --- STEP 1: AUTO MODE (HEURISTICS) ---
    if _is_explicit_chat_shift(original_query) or _is_general_chat_query(original_query):
        logger.info("[ROUTER] Auto Fast-Path: chat (general/chat-shift query)")
        return _chat_result(original_query)

    # Analyze History for follow-up detection
    last_bot_msg = None
    for msg in reversed(state['messages'][:-1]):
        if isinstance(msg, AIMessage):
            last_bot_msg = msg
            break
            
    is_follow_up = False
    if last_bot_msg:
        # If the last bot message was RAG-based and current query is short/vague
        # we treat it as a RAG follow-up
        short_query_threshold = 20
        if (
            len(original_query) < short_query_threshold
            or any(word in query_lower for word in ["why", "how", "tell me more", "explain"])
        ) and not (_is_explicit_chat_shift(original_query) or _is_general_chat_query(original_query)):
              is_follow_up = True
              logger.info("[ROUTER] Context: Potential follow-up detected.")

    # Specific file mentions always trigger RAG in Auto mode
    if mentions:
        logger.info(f"[ROUTER] Auto: specific_doc_rag (Mentions: {mentions})")
        return {
            "intent": "specific_doc_rag", 
            "query": cleaned_query,
            "targeted_docs": mentions,
            "documents": [],
            "semantic_queries": [],
            "query_embedding": None
        }

    # Fast-Path Keyword Heuristics
    for keyword in RAG_KEYWORDS:
        if _contains_keyword(query_lower, keyword):
            logger.info(f"[ROUTER] Auto Fast-Path: direct_rag (Keyword: '{keyword}')")
            return {"intent": "direct_rag", "query": original_query, "targeted_docs": [], "documents": [], "semantic_queries": [], "query_embedding": None}

    for keyword in CHAT_KEYWORDS:
        if not mentions and _contains_keyword(query_lower, keyword):
            logger.info(f"[ROUTER] Auto Fast-Path: chat (Keyword: '{keyword}')")
            # Preserve documents from previous RAG turns for source persistence
            return _chat_result(original_query, documents=state.get('documents', []))

    # --- STEP 2: AUTO MODE (SOTA SEMANTIC + VECTOR CHECK) ---
    # This is the "Smart" part. We check if the Knowledge Base actually contains relevant info.
    try:
        from backend.rag.store import get_vector_store
        store = get_vector_store()
        
        # Vector check...
        from backend.llm.client import OllamaClientWrapper
        embed_client = OllamaClientWrapper.get_embedding_client()
        embed_model = OllamaClientWrapper.get_embedding_model_name()
        
        resp = await embed_client.embed(model=embed_model, input=[original_query])
        emb = resp.get('embeddings', [[]])[0]
        
        results = store.collection.query(query_embeddings=[emb], n_results=1)
        distances = results.get('distances', [[1.0]])[0]
        
        from backend.config import get_config
        cfg = get_config()
        threshold = cfg.rag_confidence_threshold
        
        has_knowledge = len(distances) > 0 and distances[0] < threshold 
        
        if not has_knowledge and not is_follow_up:
            logger.info(f"[ROUTER] Auto: No knowledge found (Nearest: {distances[0]} >= {threshold}) & not a follow-up -> Chat")
            # Preserve documents from previous RAG turns for source persistence
            return _chat_result(original_query, documents=state.get('documents', []), query_embedding=emb)
            
        # Final arbiter: Semantic LLM intent check
        client = OllamaClientWrapper.get_chat_model()
        
        history_summary = ""
        if state['messages'][:-1]:
            # Just last 2 messages for routing context to keep it fast
            for m in state['messages'][-3:-1]:
                role = "User" if isinstance(m, HumanMessage) else "Assistant"
                history_summary += f"{role}: {m.content[:50]}...\n"

        system_prompt = (
            "You are an expert intent classifier for a RAG system.\n"
            "Analyze the LATEST QUERY in context of the HISTORY.\n"
            "Intents:\n"
            "1. 'direct_rag': User asks about indexed/uploaded documents or follow-ups to a previous RAG answer.\n"
            "2. 'chat': Casual talk, general world knowledge, or instructions unrelated to documents.\n\n"
            "Output ONLY valid JSON: {\"intent\": \"direct_rag\" | \"chat\"}"
        )
        
        prompt = f"{history_summary}\nLATEST QUERY: {original_query}"
        
        response = await client.ainvoke(
            [{"role": "system", "content": system_prompt}, {"role": "user", "content": prompt}],
            format="json"
        )
        
        result = json.loads(response.content)
        intent = (result.get("intent") or "chat").lower()
        
        logger.info(f"[ROUTER] Auto Semantic Intent: {intent}")
        # Pass the embedding to retriever to avoid duplicate API call
        # Preserve documents from previous RAG turns for source persistence when intent is chat
        docs_value = state.get('documents', []) if intent == "chat" else []
        return {
            "intent": intent,
            "query": original_query,
            "targeted_docs": [],
            "documents": docs_value,
            "semantic_queries": [],
            "query_embedding": emb,
            "retrieval_metrics": {} if intent == "chat" else state.get("retrieval_metrics", {}),
        }
            
    except Exception as e:
        logger.warning(f"[ROUTER] Smart Routing failed: {e}. Defaulting to RAG for safety.")

    return {"intent": "direct_rag", "query": original_query, "targeted_docs": [], "documents": [], "semantic_queries": [], "query_embedding": None}
