"""
State Checkpointing and Persistence
-----------------------------------
Provides mechanisms for saving and restoring the conversation state (LangGraph checkpoints).
Uses an in-memory saver for async compatibility while maintaining session references 
in a local SQLite database.
"""

from langgraph.checkpoint.memory import MemorySaver
import sqlite3
import os

# Physical DB used for session metadata, not the actual checkpoints
DB_PATH = "rag_chat_sessions.db"

# Cache for the checkpointer instance
_memory_saver = None

def get_checkpointer():
    """
    Use MemorySaver for async compatibility with FastAPI.
    
    Note: SqliteSaver uses synchronous operations which can deadlock
    when used with astream_events() in async FastAPI routes.
    MemorySaver is fully async-compatible.
    
    Trade-off: Session state won't persist across server restarts.
    For persistent async checkpointing, consider PostgreSQL saver.
    """
    global _memory_saver
    if _memory_saver is None:
        _memory_saver = MemorySaver()
    return _memory_saver

def init_db():
    """Initializes the session metadata database."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("VACUUM")

def list_sessions():
    """List all unique thread_ids from commits table."""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            # LangGraph stores checkpoints with thread_id in 'checkpoints' table usually, 
            # or 'commits' depending on version. 
            # SqliteSaver uses a table named 'checkpoints'.
            # Let's check table schema or just query distinct thread_id.
            cursor = conn.cursor()
            # Check for table existence first
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='checkpoints'")
            if not cursor.fetchone():
                return []
            
            cursor.execute("SELECT DISTINCT thread_id FROM checkpoints ORDER BY thread_id DESC")
            return [row[0] for row in cursor.fetchall()]
    except Exception as e:
        print(f"Error listing sessions: {e}")
        return []
