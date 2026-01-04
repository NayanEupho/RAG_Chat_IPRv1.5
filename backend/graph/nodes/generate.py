from backend.graph.state import AgentState
from backend.llm.client import OllamaClientWrapper
from langchain_core.messages import HumanMessage, AIMessage
import logging

logger = logging.getLogger(__name__)

async def generate_answer(state: AgentState):
    messages = state['messages']
    docs = state.get('documents', [])
    intent = state['intent']
    mode = state.get('mode', 'auto')
    
    logger.info(f"[GENERATE] Intent: {intent}, Mode: {mode}, Docs count: {len(docs)}")
    
    client = OllamaClientWrapper.get_chat_model()
    
    # 1. SLIDING WINDOW (Trimming)
    # We keep the last 10 turns (20 messages) to maintain balance between memory and speed
    MAX_HISTORY = 10
    trimmed_messages = messages[-(MAX_HISTORY * 2):] if len(messages) > (MAX_HISTORY * 2) else messages
    
    # 2. CONTEXT PREPARATION
    context_block = ""
    if docs:
        context_block = "\n\n".join(docs)
        
    system_instruction = (
        "You are a helpful and intelligent AI assistant with access to a Knowledge Base.\n"
        "Session Awareness: You have access to the conversation history. Maintain continuity.\n"
        "Adaptive Knowledge Usage:\n"
        "1. If a <knowledge_base> is provided, use it ONLY if it is relevant to the user's latest query.\n"
        "2. If the user is just saying 'thanks', 'hello', or asking a general question unrelated to the documents, ignore the Knowledge Base and answer naturally.\n"
        "3. Always prioritize a natural conversational flow."
    )
    
    # 3. PROMPT CONSTRUCTION
    if intent in ["direct_rag", "specific_doc_rag"]:
        targeting_context = ""
        semantic_maps = state.get('semantic_queries', [])
        
        if semantic_maps:
            map_str = "\n".join([f"- Querying '{s['query']}' against '{s['target'] if s['target'] else 'Global Knowledge'}'" for s in semantic_maps])
            targeting_context = f"\n[SEARCH STRATEGY] I have segmented your request as follows:\n{map_str}\n"
        elif intent == "specific_doc_rag" and state.get('targeted_docs'):
            targeting_list = ", ".join(state['targeted_docs'])
            targeting_context = f"\n[IMPORTANT] The user specifically requested info from: {targeting_list}."

        rag_prompt = f"""{targeting_context}
ADAPTIVE KNOWLEDGE BASE:
<knowledge_base>
{context_block}
</knowledge_base>

Citations: If you use the knowledge base, cite sections like [Section: Name].
Question: {state.get('query', messages[-1].content)}
"""
        # Replace the last user message's content with the RAG-augmented prompt
        # but keep it in the sequence for history consistency
        final_messages = []
        for m in trimmed_messages[:-1]:
            role = "user" if isinstance(m, HumanMessage) else "assistant"
            final_messages.append({"role": role, "content": m.content})
            
        final_messages.append({"role": "system", "content": system_instruction})
        final_messages.append({"role": "user", "content": rag_prompt})
    else:
        # PURE CHAT MODE
        final_messages = [{"role": "system", "content": system_instruction}]
        for m in trimmed_messages:
            role = "user" if isinstance(m, HumanMessage) else "assistant"
            final_messages.append({"role": role, "content": m.content})
    
    # Using model.ainvoke will be intercepted by streaming logic in routes.py
    response = await client.ainvoke(final_messages)
    
    return {"messages": [response]}
