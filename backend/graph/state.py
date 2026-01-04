from typing import List, Dict, Any, Annotated, TypedDict
from langgraph.graph.message import add_messages
from langchain_core.messages import BaseMessage

class AgentState(TypedDict):
    messages: Annotated[List[BaseMessage], add_messages]
    query: str
    intent: str  # 'chat', 'direct_rag', 'specific_doc_rag'
    documents: List[str] # Retrieved context
    targeted_docs: List[str] # If user mentioned @filename1, @filename2
    semantic_queries: List[Dict[str, Any]] # List of {"query": str, "target": str or None}
    mode: str  # 'auto', 'rag', 'chat'
