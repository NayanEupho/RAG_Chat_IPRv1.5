import sqlite3
import os
from backend.ingestion.processor import viterbi

def check_db():
    db_path = "rag_chat_sessions.db"
    if not os.path.exists(db_path):
        print(f"DB not found at {db_path}")
        return

    conn = sqlite3.connect(db_path)
    # Check Journal Mode
    mode = conn.execute("PRAGMA journal_mode;").fetchone()[0]
    print(f"Journal Mode: {mode}")

    # Check Timestamps
    try:
        row = conn.execute("SELECT updated_at FROM sessions ORDER BY updated_at DESC LIMIT 1").fetchone()
        if row:
            print(f"Latest Session Timestamp: {row[0]}")
        else:
            print("No sessions found.")
    except Exception as e:
        print(f"Error reading timestamps: {e}")
    conn.close()

def check_viterbi():
    # Test mashing recovery for new terms
    tests = [
        "chromaollama",
        "pydanticfastapi",
        "langgraphwatcher"
    ]
    print("\nViterbi Test:")
    for t in tests:
        res = viterbi.segment(t)
        print(f"'{t}' -> '{res}'")

if __name__ == "__main__":
    check_db()
    check_viterbi()
