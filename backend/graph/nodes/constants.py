"""
Shared constants for Intent Classification.
Used by both Planner (fused mode) and Router (modular mode).
"""

# Keywords suggesting casual conversation (Intent: chat)
CHAT_KEYWORDS = [
    "hello", "hi", "hey", "good morning", "good evening", "how are you",
    "write me", "compose", "create a", "tell me a joke", "story about",
    "your opinion", "translate", "code for", "script that"
]

# Keywords suggesting document search (Intent: rag)
RAG_KEYWORDS = [
    "document", "file", "report", "policy", "according to", "what is",
    "what does", "summarize", "about", "describe", "find", "search",
    "look up", "check", "verify", "based on", "compliance", "regulation",
    "guideline", "procedure", "in the", "from the"
]
