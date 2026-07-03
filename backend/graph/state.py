"""
Graph State Definition
----------------------
Defines the schema for the shared state object used by LangGraph nodes.
This object encapsulates the conversation history, user query, and retrieval context.
"""

from typing import List, Dict, Any, Annotated, TypedDict, Optional
from langgraph.graph.message import add_messages
from langchain_core.messages import BaseMessage

def update_summary(current: str, new: str) -> str:
    if new:
        return new
    return current

class AgentState(TypedDict):
    """
    Standard schema for the multi-agent graph state.
    
    Attributes:
        messages: Chronological list of conversation messages.
        query: The refined/original user query.
        intent: Classified goal (chat, rag, specific_doc).
        documents: List of retrieved text chunks for contextual generation.
        targeted_docs: Specific files referenced by the user (@mentioning).
        semantic_queries: Planned search operations (query + target).
        mode: Operation mode (auto, rag, chat).
        query_embedding: Cached vector representation of the query.
        summary: Running conversation summary for context preservation.
        retrieval_metrics: Diagnostics for the latest retrieval pass.
        context_action: How to handle previous retrieval context.
        last_targeted_docs: Most recent explicit document targets persisted
            for the session, used only to resolve short follow-ups.
    """
    messages: Annotated[List[BaseMessage], add_messages]
    query: str
    intent: str
    documents: List[str]
    targeted_docs: List[str]
    semantic_queries: List[Dict[str, Any]]
    mode: str
    query_embedding: Optional[List[float]]
    summary: Annotated[str, update_summary]
    retrieval_metrics: Dict[str, Any]
    context_action: str
    last_targeted_docs: List[str]
