import sqlite3
import json
import logging
import threading
from datetime import datetime
from functools import lru_cache

DB_PATH = "rag_chat_sessions.db"
logger = logging.getLogger(__name__)

# Thread-local storage for SQLite connections (connection pooling)
_local = threading.local()

def get_connection() -> sqlite3.Connection:
    """Get a thread-local SQLite connection (pseudo connection pooling)."""
    if not hasattr(_local, 'connection') or _local.connection is None:
        _local.connection = sqlite3.connect(DB_PATH, check_same_thread=False)
        # Enable WAL mode for better concurrency (Zero-copy, high-speed)
        _local.connection.execute("PRAGMA journal_mode=WAL")
        _local.connection.execute("PRAGMA synchronous=NORMAL")
        _local.connection.row_factory = sqlite3.Row
        logger.debug("Created new SQLite connection with WAL mode enabled")
    return _local.connection

_db_initialized = False

def init_history_db():
    global _db_initialized
    if _db_initialized:
        return
    try:
        conn = get_connection()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                title TEXT,
                user_id TEXT DEFAULT 'anonymous',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                role TEXT,
                content TEXT,
                intent TEXT,
                sources TEXT,
                thoughts TEXT,
                metadata TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(session_id) REFERENCES sessions(session_id)
            )
        """)
        
        # Migration for existing tables - MUST RUN BEFORE INDICES
        cursor = conn.execute("PRAGMA table_info(messages)")
        columns = [row['name'] for row in cursor.fetchall()]
        if 'metadata' not in columns:
            conn.execute("ALTER TABLE messages ADD COLUMN metadata TEXT")
        if 'thoughts' not in columns:
            conn.execute("ALTER TABLE messages ADD COLUMN thoughts TEXT")

        cursor = conn.execute("PRAGMA table_info(sessions)")
        session_columns = [row['name'] for row in cursor.fetchall()]
        if 'user_id' not in session_columns:
            conn.execute("ALTER TABLE sessions ADD COLUMN user_id TEXT DEFAULT 'legacy_user'")
            logger.info("Migrated sessions table: added user_id column")

        # Now safe to create indices
        conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id)")
            
        conn.commit()
        _db_initialized = True
    except Exception as e:
        logger.error(f"Failed to init history DB: {e}")

def create_session(session_id: str, title: str = None, user_id: str = "anonymous"):
    init_history_db()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT session_id FROM sessions WHERE session_id = ?", (session_id,))
    if not cursor.fetchone():
        final_title = title or f"Session {session_id[:8]}"
        conn.execute(
            "INSERT INTO sessions (session_id, title, user_id) VALUES (?, ?, ?)",
            (session_id, final_title, user_id)
        )
        conn.commit()
        return True
    return False

def create_new_session(title: str = None, user_id: str = "anonymous"):
    """Generates a new session ID and creates the session."""
    import uuid
    session_id = f"web_{uuid.uuid4().hex[:8]}"
    create_session(session_id, title, user_id)
    return {"session_id": session_id, "title": title or f"Session {session_id[:8]}", "user_id": user_id}

def add_message(session_id: str, role: str, content: str, intent: str = None, sources: list = None, metadata: dict = None, thoughts: list = None):
    # Ensure session exists (Note: this auto-creation defaults to 'anonymous' if not exists, 
    # but normally create_session is called with user_id by the route first)
    # If the session already exists, create_session does nothing, so user_id isn't overwritten.
    create_session(session_id)
    
    sources_json = json.dumps(sources) if sources else "[]"
    metadata_json = json.dumps(metadata) if metadata else "{}"
    thoughts_json = json.dumps(thoughts) if thoughts else "[]"
    
    conn = get_connection()
    conn.execute(
        """INSERT INTO messages (session_id, role, content, intent, sources, metadata, thoughts) 
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (session_id, role, content, intent, sources_json, metadata_json, thoughts_json)
    )
    # Update session timestamp (Normalized UTC ISO String)
    conn.execute(
        "UPDATE sessions SET updated_at = ? WHERE session_id = ?", 
        (datetime.utcnow().isoformat(), session_id)
    )
    conn.commit()

def get_all_sessions(user_id: str = None):
    init_history_db()
    conn = get_connection()
    if user_id:
        cursor = conn.execute("SELECT * FROM sessions WHERE user_id = ? ORDER BY updated_at DESC", (user_id,))
    else:
        cursor = conn.execute("SELECT * FROM sessions ORDER BY updated_at DESC")
    return [dict(row) for row in cursor.fetchall()]

def delete_session(session_id: str, user_id: str = None):
    init_history_db()
    conn = get_connection()
    
    if user_id:
        cursor = conn.execute("SELECT user_id FROM sessions WHERE session_id = ?", (session_id,))
        row = cursor.fetchone()
        if not row:
            raise ValueError("Session not found")
        if row['user_id'] != user_id:
            raise PermissionError("Not authorized to delete this session")
            
    conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
    conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
    conn.commit()

def get_session_history(session_id: str):
    init_history_db()
    conn = get_connection()
    cursor = conn.execute(
        "SELECT * FROM messages WHERE session_id = ? ORDER BY id ASC", 
        (session_id,)
    )
    rows = []
    for row in cursor.fetchall():
        d = dict(row)
        if d['sources']:
            d['sources'] = json.loads(d['sources'])
        if d['metadata']:
            try:
                d['metadata'] = json.loads(d['metadata']) if d['metadata'] else {}
            except Exception:
                d['metadata'] = {}
        else:
            d['metadata'] = {}
            
        if 'thoughts' in d and d['thoughts']:
            try:
                d['thoughts'] = json.loads(d['thoughts'])
            except:
                d['thoughts'] = []
        else:
             d['thoughts'] = []
             
        rows.append(d)
    return rows

def get_session_owner(session_id: str) -> str:
    """Get the user_id that owns a session."""
    init_history_db()
    conn = get_connection()
    cursor = conn.execute("SELECT user_id FROM sessions WHERE session_id = ?", (session_id,))
    row = cursor.fetchone()
    return row['user_id'] if row else None

def is_session_owner(session_id: str, user_id: str) -> bool:
    """Check if the given user_id owns the session."""
    owner = get_session_owner(session_id)
    return owner == user_id


def delete_all_sessions():
    """Delete all sessions and messages for clean start."""
    init_history_db()
    conn = get_connection()
    conn.execute("DELETE FROM messages")
    conn.execute("DELETE FROM sessions")
    conn.commit()
    logger.info("Deleted all sessions and messages")

