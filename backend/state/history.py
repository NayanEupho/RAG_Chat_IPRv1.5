import sqlite3
import json
import logging
import threading
import re
from datetime import datetime

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
        if 'summary' not in session_columns:
            conn.execute("ALTER TABLE sessions ADD COLUMN summary TEXT DEFAULT ''")
            logger.info("Migrated sessions table: added summary column")
        if 'auto_title_eligible' not in session_columns:
            conn.execute("ALTER TABLE sessions ADD COLUMN auto_title_eligible INTEGER DEFAULT 0")
            logger.info("Migrated sessions table: added auto_title_eligible column")

        # Now safe to create indices
        conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id)")
            
        conn.commit()
        _db_initialized = True
    except Exception as e:
        logger.error(f"Failed to init history DB: {e}")

def create_session(session_id: str, title: str = None, user_id: str = "anonymous", auto_title_eligible: bool = False):
    init_history_db()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT session_id FROM sessions WHERE session_id = ?", (session_id,))
    if not cursor.fetchone():
        final_title = title or f"Session {session_id[:8]}"
        conn.execute(
            "INSERT INTO sessions (session_id, title, user_id, auto_title_eligible) VALUES (?, ?, ?, ?)",
            (session_id, final_title, user_id, 1 if auto_title_eligible else 0)
        )
        conn.commit()
        return True
    return False

def create_new_session(title: str = None, user_id: str = "anonymous", session_id: str = None, auto_title_eligible: bool = False):
    """Generates a new session ID and creates the session."""
    import uuid
    session_id = session_id or f"web_{uuid.uuid4().hex[:8]}"
    create_session(session_id, title, user_id, auto_title_eligible=auto_title_eligible)
    return {"session_id": session_id, "title": title or f"Session {session_id[:8]}", "user_id": user_id}

def update_session_title(session_id: str, title: str, user_id: str = None):
    """Update a session title, optionally enforcing ownership."""
    init_history_db()
    cleaned = re.sub(r"\s+", " ", title or "").strip()
    if not cleaned:
        raise ValueError("Title cannot be empty")
    cleaned = cleaned[:80]
    conn = get_connection()
    if user_id:
        cursor = conn.execute("SELECT user_id FROM sessions WHERE session_id = ?", (session_id,))
        row = cursor.fetchone()
        if not row:
            raise ValueError("Session not found")
        if row["user_id"] != user_id:
            raise PermissionError("Not authorized to update this session")
    conn.execute(
        "UPDATE sessions SET title = ?, auto_title_eligible = 0, updated_at = ? WHERE session_id = ?",
        (cleaned, datetime.utcnow().isoformat(), session_id),
    )
    conn.commit()
    return {"session_id": session_id, "title": cleaned}

def get_session(session_id: str):
    init_history_db()
    conn = get_connection()
    cursor = conn.execute("SELECT * FROM sessions WHERE session_id = ?", (session_id,))
    row = cursor.fetchone()
    return dict(row) if row else None

def is_default_session_title(title: str) -> bool:
    if not title:
        return True
    cleaned = title.strip()
    return bool(
        re.match(r"^Session\s*-\s*\d{1,2}:\d{2}\s*(AM|PM)?$", cleaned, re.IGNORECASE)
        or re.match(r"^Session\s+web_[a-z0-9]+$", cleaned, re.IGNORECASE)
        or cleaned == "New Conversation"
    )

def concise_title_from_exchange(user_message: str, bot_response: str) -> str:
    """Create a deterministic, low-latency title without an LLM call."""
    normalized_user = re.sub(r"[^a-z0-9\s]", " ", (user_message or "").lower()).strip()
    normalized_user = re.sub(r"\s+", " ", normalized_user)
    if normalized_user in {"hi", "hello", "hey", "hii", "hiii", "good morning", "good afternoon", "good evening"}:
        return "New Chat"

    text = f"{user_message or ''} {bot_response or ''}"
    text = re.sub(r"@\S+", lambda m: m.group(0)[1:].rsplit(".", 1)[0], text)
    words = re.findall(r"[A-Za-z0-9][A-Za-z0-9&/-]*", text)
    stop = {
        "the", "and", "for", "with", "from", "what", "does", "about", "tell",
        "more", "please", "paper", "document", "file", "this", "that", "into",
        "are", "is", "was", "were", "who", "how", "why", "can", "you", "your",
        "based", "provided", "retrieved", "chunk", "chunks",
    }
    picked = []
    seen = set()
    for word in words:
        key = word.lower().strip("-_/")
        if len(key) < 3 or key in stop or key in seen:
            continue
        seen.add(key)
        picked.append(word.strip("-_/"))
        if len(picked) == 5:
            break
    if not picked:
        return "New Chat"
    return " ".join(w[:1].upper() + w[1:] for w in picked)[:60]

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
            except Exception:
                d['thoughts'] = []
        else:
             d['thoughts'] = []
             
        rows.append(d)
    return rows

def get_recent_targeted_docs(session_id: str, limit: int = 8) -> list[str]:
    """Return the most recent targeted document context persisted for a session."""
    init_history_db()
    conn = get_connection()
    cursor = conn.execute(
        "SELECT metadata FROM messages WHERE session_id = ? ORDER BY id DESC LIMIT ?",
        (session_id, limit),
    )
    for row in cursor.fetchall():
        raw_metadata = row["metadata"] if row["metadata"] else "{}"
        try:
            metadata = json.loads(raw_metadata)
        except Exception:
            metadata = {}
        targeted_docs = metadata.get("targeted_docs") or []
        if targeted_docs:
            return [str(doc) for doc in targeted_docs if doc]
    return []

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

