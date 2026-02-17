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
from backend.llm.client import OllamaClientWrapper
from backend.graph.nodes.constants import CHAT_KEYWORDS, RAG_KEYWORDS
from langchain_core.messages import HumanMessage, AIMessage
import re
import json
import logging

logger = logging.getLogger(__name__)

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
        return {"intent": "chat", "query": original_query, "targeted_docs": [], "documents": state.get('documents', []), "semantic_queries": [], "query_embedding": None}
    
    # Check for mentions regardless of mode if RAG is involved
    mentions = re.findall(r"@([\w\-\. ]+?)(?=[,.;:!?\s]|$)", original_query)
    mentions = [m.strip() for m in mentions if m.strip() and ('.' in m or len(m) > 3)]
    cleaned_query = original_query
    for m in mentions:
        cleaned_query = cleaned_query.replace(f"@{m}", "")
    cleaned_query = cleaned_query.strip()

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
        if len(original_query) < short_query_threshold or any(word in query_lower for word in ["why", "how", "tell me more", "explain"]):
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
        if keyword in query_lower:
            logger.info(f"[ROUTER] Auto Fast-Path: direct_rag (Keyword: '{keyword}')")
            return {"intent": "direct_rag", "query": original_query, "targeted_docs": [], "documents": [], "semantic_queries": [], "query_embedding": None}

    for keyword in CHAT_KEYWORDS:
        if keyword in query_lower:
            logger.info(f"[ROUTER] Auto Fast-Path: chat (Keyword: '{keyword}')")
            # Preserve documents from previous RAG turns for source persistence
            return {"intent": "chat", "query": original_query, "targeted_docs": [], "documents": state.get('documents', []), "semantic_queries": [], "query_embedding": None}

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
            return {"intent": "chat", "query": original_query, "targeted_docs": [], "documents": state.get('documents', []), "semantic_queries": [], "query_embedding": emb}
            
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
            "1. 'direct_rag': User asks for facts, technical details, or follow-ups to a previous RAG answer.\n"
            "2. 'chat': Casual talk, general greetings, or instructions unrelated to documents.\n\n"
            "Output ONLY valid JSON: {\"intent\": \"direct_rag\" | \"chat\"}"
        )
        
        prompt = f"{history_summary}\nLATEST QUERY: {original_query}"
        
        response = await client.ainvoke(
            [{"role": "system", "content": system_prompt}, {"role": "user", "content": prompt}],
            format="json"
        )
        
        result = json.loads(response.content)
        intent = result.get("intent", "chat").lower()
        
        logger.info(f"[ROUTER] Auto Semantic Intent: {intent}")
        # Pass the embedding to retriever to avoid duplicate API call
        # Preserve documents from previous RAG turns for source persistence when intent is chat
        docs_value = state.get('documents', []) if intent == "chat" else []
        return {"intent": intent, "query": original_query, "targeted_docs": [], "documents": docs_value, "semantic_queries": [], "query_embedding": emb}
            
    except Exception as e:
        logger.warning(f"[ROUTER] Smart Routing failed: {e}. Defaulting to RAG for safety.")

    return {"intent": "direct_rag", "query": original_query, "targeted_docs": [], "documents": [], "semantic_queries": [], "query_embedding": None}
