"""
Query Rewriting & Semantic Mapping Node
---------------------------------------
This node transforms the user query into a structured 'Semantic Map'.
It resolves ambiguous references (pronouns) using conversation history and 
breaks down multi-intent requests into targeted file searches.
"""

from backend.graph.state import AgentState
from backend.llm.client import OllamaClientWrapper
from langchain_core.messages import HumanMessage, AIMessage
import logging

logger = logging.getLogger(__name__)

async def rewrite_query(state: AgentState):
    """
    Transforms the current query into a Semantic Search Map.
    This maps specific sub-questions to specific files mentioned by the user.
    """
    messages = state['messages']
    query = state.get('query', messages[-1].content)
    intent = state.get('intent', 'unknown')
    targeted_docs = state.get('targeted_docs', [])
    
    # Even if no history, we want to segment the current query if it has multiple @tags
    if intent == 'chat':
        return {"semantic_queries": []}

    # BYPASS LOGIC (Priority: High, Latency: Instant)
    # If there's no history AND only 0-1 targeted docs, we don't need the LLM to "rewrite" or "segment"
    if len(messages) < 3 and len(targeted_docs) <= 1:
        logger.info(f"[REWRITER] Fast-Path Bypass: Single document/No-history context")
        return {"semantic_queries": [{"query": query, "target": targeted_docs[0] if targeted_docs else None}]}

    logger.info(f"[REWRITER] Analyzing semantic mapping for: '{query}'")
    
    try:
        client = OllamaClientWrapper.get_chat_model()
        
        target_hint = f"Targeted Files: {', '.join(targeted_docs)}" if targeted_docs else "No specific files targeted."
        
        system_prompt = (
            "You are a search query orchestrator. Your job is to break down a user query into specific search segments.\n"
            "For each segment, identify the search query and which file (from the provided list) it should target.\n\n"
            "Context Awareness:\n"
            "- The documents are indexed with section headers (e.g., [Section: Intro]).\n"
            "- If the user asks for a specific topic, tailor the query to match potential section names.\n\n"
            "Rules:\n"
            "1. If a segment doesn't target a specific file, set 'target' to null.\n"
            "2. Use the provided conversation history to resolve pronouns (it, that, etc.).\n"
            "3. Output ONLY valid JSON: [{\"query\": \"exact search terms\", \"target\": \"filename.pdf\" | null}].\n"
            f"Allowed Targets: {targeted_docs + [None]}\n"
        )
        
        history_str = ""
        for m in messages[:-1]:
            role = "User" if isinstance(m, HumanMessage) else "Assistant"
            history_str += f"{role}: {m.content}\n"
            
        prompt = f"History:\n{history_str}\n{target_hint}\nLatest Query: {query}\n\nSearch Map (JSON):"
        
        response = await client.ainvoke([
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt}
        ], format="json")
        
        import json
        semantic_map = json.loads(response.content)
        
        # Ensure it's a list
        if not isinstance(semantic_map, list):
            semantic_map = [{"query": query, "target": targeted_docs[0] if targeted_docs else None}]
            
        logger.info(f"[REWRITER] Semantic Map: {semantic_map}")
        return {"semantic_queries": semantic_map}
        
    except Exception as e:
        logger.warning(f"[REWRITER] Semantic mapping failed: {e}. Falling back to flat query.")
        return {"semantic_queries": [{"query": query, "target": targeted_docs[0] if targeted_docs else None}]}
