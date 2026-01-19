from backend.graph.state import AgentState
from backend.llm.client import OllamaClientWrapper
from langchain_core.messages import HumanMessage, AIMessage
import logging

logger = logging.getLogger(__name__)

# Token budget for context - adjust based on model context window
# qwen2.5:72b-instruct has 128k context, so we can be generous
# 8000 tokens leaves room for chat history + system prompt + generation
MAX_CONTEXT_TOKENS = 8000

def estimate_tokens(text: str) -> int:
    """
    Estimate token count for text. Rule of thumb: ~4 chars per token for English.
    This is a conservative estimate that works across most models.
    """
    return max(1, int(len(text) / 4))

def select_docs_within_budget(docs: list, max_tokens: int) -> list:
    """
    Select documents that fit within the token budget, prioritizing earlier (higher-ranked) docs.
    Returns a subset of docs whose combined estimated tokens <= max_tokens.
    """
    selected = []
    token_count = 0
    
    for doc in docs:
        doc_tokens = estimate_tokens(doc)
        if token_count + doc_tokens > max_tokens:
            # If we've selected at least one doc, stop here
            if selected:
                break
            # If this is the first doc and it exceeds budget, truncate it
            truncate_chars = max_tokens * 4
            selected.append(doc[:truncate_chars] + "\n[...truncated for length...]")
            break
        selected.append(doc)
        token_count += doc_tokens
    
    return selected

async def generate_answer(state: AgentState):
    messages = state['messages']
    docs = state.get('documents', [])
    intent = state['intent']
    mode = state.get('mode', 'auto')
    
    logger.info(f"[GENERATE] Intent: {intent}, Mode: {mode}, Docs count: {len(docs)}")
    
    client = OllamaClientWrapper.get_chat_model()
    
    # 1. SLIDING WINDOW (Trimming)
    # With qwen2.5:72b-instruct's 128k context, we can keep more history
    # 25 turns (50 messages) ≈ 5000-7500 tokens - well within budget
    MAX_HISTORY = 25
    trimmed_messages = messages[-(MAX_HISTORY * 2):] if len(messages) > (MAX_HISTORY * 2) else messages
    
    # 2. CONTEXT PREPARATION with TOKEN BUDGET
    # Select docs that fit within token budget to prevent context overflow
    context_block = ""
    if docs:
        selected_docs = select_docs_within_budget(docs, MAX_CONTEXT_TOKENS)
        if len(selected_docs) < len(docs):
            logger.info(f"[GENERATE] Token budget applied: {len(selected_docs)}/{len(docs)} docs selected")
        context_block = "\n\n".join(selected_docs)
        
    # 3. BREVITY & STYLE CONTROL
    # Detect if the user wants a detailed explanation
    detail_keywords = ["detail", "comprehensive", "step by step", "elaborate", "full", "detailed", "depth"]
    latest_query = state.get('query', messages[-1].content).lower()
    is_detailed = any(k in latest_query for k in detail_keywords)
    
    if is_detailed:
        style_instruction = (
            "STYLE: Provide a comprehensive, step-by-step explanation. "
            "Cover edge cases and technical background context as found in the knowledge base."
        )
    else:
        style_instruction = (
            "STYLE: Be extremely crisp, precise, and to-the-point. "
            "Avoid introductory fluff or restating the question. "
            "Use bullet points for lists. Answer in < 4 sentences if possible."
        )

    system_instruction = (
        "You are a helpful and intelligent AI assistant with access to a Knowledge Base.\n"
        f"{style_instruction}\n"
        "Session Awareness: You have access to the conversation history. Maintain continuity.\n"
        "Adaptive Knowledge Usage:\n"
        "1. If a <knowledge_base> is provided, use it ONLY if it is relevant to the user's latest query.\n"
        "2. If the user is just saying 'thanks', 'hello', or asking a general question unrelated to the documents, ignore the Knowledge Base and answer naturally.\n"
        "3. Always prioritize a natural conversational flow."
    )
    
    # 4. PROMPT CONSTRUCTION
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
