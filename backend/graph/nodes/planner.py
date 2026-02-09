from backend.graph.state import AgentState
from backend.llm.client import OllamaClientWrapper
from backend.graph.nodes.constants import CHAT_KEYWORDS, RAG_KEYWORDS
from backend.config import get_config
from langchain_core.messages import HumanMessage
import logging
import json
import re

logger = logging.getLogger(__name__)

async def planner_node(state: AgentState):
    """
    The Planner Node (Fused Mode).
    
    ARCHITECTURE NOTE:
    ------------------
    In 'Fused' mode, this single node replaces the sequential chain of:
    1. Router (Intent Classification)
    2. Rewriter (Query Expansion/Rewriting)
    3. Retriever (Sub-Query Generation)
    
    By doing all three in one "Mega-Prompt", we save 2 full HTTP round-trips 
    and Queueing times to the LLM, reducing pre-retrieval latency by ~60%.
    
    INPUT:
    - User Query + Chat History
    
    OUTPUT (AgentState):
    - intent: "chat" | "direct_rag" | "specific_doc_rag"
    - query: The standalone rewritten query
    - semantic_queries: A list of dicts [{"query": "...", "target": "..."}] 
      used by the Retriever to execute searches immediately.
    """
    original_query = state['messages'][-1].content
    mode = state.get('mode', 'auto').lower()
    
    # ---------------------------------------------------------
    # 1. FAST PATHS (Zero LLM Latency)
    # ---------------------------------------------------------
    # We mirror the logic from 'router.py' here to ensure the "Planner" 
    # honors user UI selections (Forced Chat, Forced RAG) instantly.
    
    # A) Forced Chat Mode
    if mode == 'chat':
        logger.info("[PLANNER] Mode: Forced Chat (Bypassing LLM)")
        return {"intent": "chat", "query": original_query, "targeted_docs": [], "documents": [], "semantic_queries": [], "query_embedding": None}

    # B) Regex for @mentions (Used for specific_doc_rag)
    mentions = re.findall(r"@([\w\-\. ]+?)(?=[,.;:!?\s]|$)", original_query)
    mentions = [m.strip() for m in mentions if m.strip() and ('.' in m or len(m) > 3)]
    
    cleaned_query = original_query
    for m in mentions:
        cleaned_query = cleaned_query.replace(f"@{m}", "")
    cleaned_query = cleaned_query.strip()

    # C) Forced RAG Mode Check
    # We still go to the LLM to generate sub-queries, but we force the final intent decision.
    forced_intent = None
    if mode == 'rag' or mentions:
        forced_intent = "specific_doc_rag" if mentions else "direct_rag"
        logger.info(f"[PLANNER] Mode: Forced RAG / Mentions: {mentions}. Will enforce intent: {forced_intent}")
        
    # D) Fast-Path Keywords (Auto Mode only)
    elif mode == 'auto':
        query_lower = original_query.lower()
        # If user says "Hello", just chat. No need to plan a search.
        for k in CHAT_KEYWORDS:
            if k in query_lower:
                logger.info(f"[PLANNER] Fast-Path: Chat (Keyword: '{k}')")
                return {"intent": "chat", "query": original_query, "targeted_docs": [], "documents": [], "semantic_queries": [], "query_embedding": None}
    
    # ---------------------------------------------------------
    # 1D. SPECULATIVE PRE-EMBEDDING & VECTOR GUARDRAIL
    # ---------------------------------------------------------
    try:
        from backend.graph.nodes.retriever import get_cached_embedding
        from backend.llm.client import OllamaClientWrapper
        from backend.rag.store import get_vector_store
        
        embed_model = OllamaClientWrapper.get_embedding_model_name()
        
        # 1. Start Embedding (Speculative)
        # We AWAIT here for the guardrail if we are in AUTO mode.
        # Since embedding is ~800ms and LLM is ~3s, this is a safe trade-off for "Fast Abort".
        q_emb = await get_cached_embedding(cleaned_query, embed_model)
        
        if mode == 'auto' and not mentions and q_emb:
            store = get_vector_store()
            results = store.query(query_embeddings=[q_emb], n_results=1)
            distances = results.get('distances', [[1.0]])[0]
            
            # GUARDRAIL: Vector-based retrieval confidence check
            # Uses centralized threshold to decide between RAG and Chat fallback
            config = get_config()
            threshold = config.rag_confidence_threshold
            
            if len(distances) > 0 and distances[0] > threshold:
                logger.info(f"[PLANNER] Vector Guardrail: Nearest doc at {distances[0]} > {threshold}. Aborting RAG -> Chat.")
                return {"intent": "chat", "query": original_query, "targeted_docs": [], "documents": [], "semantic_queries": [], "query_embedding": q_emb}
        
    except Exception as e:
        logger.debug(f"[PLANNER] Guardrail/Speculative failed: {e}")

    # ---------------------------------------------------------
    # 2. THE MEGA-PROMPT (One LLM Call)
    # ---------------------------------------------------------
    
    # Prepare History (Last 2 human/ai turns context)
    history_summary = ""
    for m in state['messages'][-3:-1]:
        role = "User" if isinstance(m, HumanMessage) else "Assistant"
        history_summary += f"{role}: {m.content[:200]}...\n"

    target_hint = f"Explicit Targets: {', '.join(mentions)}" if mentions else "No explicit targets."
    forced_mode_hint = f"USER FORCE-MODE: {mode.upper()}" if mode != 'auto' else "Mode: Auto"

    system_prompt = (
        "You are the RAG Planner. Analyze the query and generate a comprehensive execution plan.\n"
        "Your goal: Determine Intent, Revise the Query, and Generate Search Sub-queries.\n\n"
        "STEPS:\n"
        "1. **Intent**: 'chat' (casual/creative) OR 'rag' (requires factual document search).\n"
        "2. **Rewrite**: Resolve pronouns (it, that) using history. Make the query standalone.\n"
        "3. **Plan**: If rag, generate 3 specific search queries + targets.\n\n"
        "OUTPUT FORMAT (Strict JSON):\n"
        "{\n"
        "  \"intent\": \"rag\" | \"chat\",\n"
        "  \"rewritten_query\": \"string\",\n"
        "  \"semantic_queries\": [{\"query\": \"sub-query 1\", \"target\": \"filename.pdf\" | null}, ...]\n"
        "}\n\n"
        "RULES:\n"
        f"- {forced_mode_hint}\n"
        "- If intent is 'chat', semantic_queries must be empty [].\n"
        "- If intent is 'rag', semantic_queries must have 1-4 items.\n"
        f"- {target_hint}\n"
    )
    
    client = OllamaClientWrapper.get_chat_model()
    
    try:
        response = await client.ainvoke([
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"History:\n{history_summary}\nLatest: {original_query}"}
        ], format="json")
        
        plan = json.loads(response.content)
        
        # ---------------------------------------------------------
        # 3. POST-PROCESSING & VALIDATION
        # ---------------------------------------------------------
        
        intent = plan.get("intent", "rag").lower()
        
        # Override Intent if Forced by UI
        if forced_intent:
            intent = "rag" # We map internal 'rag' to specific/direct subtypes below
            
        # Refine Intent tag for Graph Edge Routing
        final_intent = "chat"
        if intent == "rag":
            final_intent = "specific_doc_rag" if mentions else "direct_rag"
        
        # Extract Semantic Queries
        semantic_queries = plan.get("semantic_queries", [])
        
        # Fallback: If model says "rag" but failed to generate queries, use the rewritten query
        if final_intent != "chat" and not semantic_queries:
             rewritten = plan.get("rewritten_query", original_query)
             semantic_queries = [{"query": rewritten, "target": m} for m in (mentions if mentions else [None])]

        logger.info(f"[PLANNER] Plan: {final_intent} | Rewritten: {plan.get('rewritten_query')} | {len(semantic_queries)} sub-queries")
        
        return {
            "intent": final_intent,
            "query": plan.get("rewritten_query", cleaned_query),
            "targeted_docs": mentions,
            "semantic_queries": semantic_queries,
            "documents": [],
            "query_embedding": None # Will be computed by retriever if needed
        }

    except Exception as e:
        logger.error(f"[PLANNER] Planning failed: {e}. Fallback to Safe RAG.")
        # Safety Fallback: Assume Direct RAG with original query
        # This prevents the graph from crashing if the LLM outputs bad JSON.
        return {
            "intent": "direct_rag",
            "query": original_query,
            "targeted_docs": mentions,
            "semantic_queries": [{"query": original_query, "target": m} for m in (mentions if mentions else [None])],
            "documents": [],
            "query_embedding": None
        }
