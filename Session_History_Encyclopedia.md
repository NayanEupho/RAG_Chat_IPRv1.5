# Session & History Encyclopedia: The Heart of Conversational Continuity

This encyclopedia provides a 360-degree technical deep-dive into the **Session and Chat History Database (SQLite)** powering the **RAG Chat IPR**. It covers everything from thread-safe connections to the complex serialization of agentic thought processes.

---

## 🏛️ 1. Why SQLite? (The Choice of Stability)

For session management and chat history, we require **ACID compliance** (Atomicity, Consistency, Isolation, Durability). 

1.  **Lightweight**: SQLite is serverless and lives as a single file (`rag_chat_sessions.db`).
2.  **Relational Power**: It allows us to link millions of messages to thousands of sessions instantly.
3.  **Cross-Platform**: The DB file works anywhere without a database server installation.

---

## 📂 2. Storage & Schema Definition

- **Location**: `rag_chat_sessions.db` (Project Root).
-   **Definition**: The schema is **programmatically defined** in `backend/state/history.py`.

### The Relational Blueprint:

```mermaid
erDiagram
    SESSIONS ||--o{ MESSAGES : "contains"
    SESSIONS {
        string session_id PK
        string title
        timestamp created_at
        timestamp updated_at
    }
    MESSAGES {
        int id PK
        string session_id FK
        string role "user/bot"
        string content "Text Body"
        string intent "detected intent"
        string sources "JSON list of docs"
        string thoughts "JSON thinking process"
        string metadata "JSON extra data"
        timestamp created_at
    }
```

---

## ⚙️ 3. The Thread-Safe Connection Engine

Because the **FastAPI** backend is asynchronous and processes multiple users at once, we use a custom **Thread-Local Connection Pool** in `history.py`:

-   **`_local = threading.local()`**: Ensures that each Python thread has its own private connection to the database.
-   **No "Database Locked" Errors**: This prevents different threads from stepping on each other's toes during high-speed chat interactions.

---

## 🧠 4. Advanced Persistence: Thoughts & Metadata

Your history database doesn't just store "What" was said, but **"How"** it was said.

### Serialization Flow:
1.  **The Generation Phase**: As the LangGraph agent thinks, it adds entries to a `thoughts` list (e.g., "Analyzing Intent", "Searching Docs").
2.  **The Persistence Phase**:
    -   The system converts the Python list of thoughts into a **JSON String**.
    -   This string is saved in the `thoughts` column.
3.  **The Retrieval Phase**: When the frontend asks for history, the backend **Deserializes** (parses) this JSON back into objects so the UI can render the "Thinking Process" timeline.

---

## 🛠️ 5. Related Files & Services

| File | Role | Connection Type |
| :--- | :--- | :--- |
| **`backend/state/history.py`** | The Engine | Contains all SQL queries and schema logic. |
| **`backend/api/routes.py`** | The Orchestrator | Triggers history logging during every chat stream. |
| **`frontend/src/hooks/useChat.ts`**| The Customer | Fetches session history to display on the UI. |
| **`backend/state/checkpoint.py`** | The State Guard | Uses SQLite to save the "Checkpoint" of the Graph. |

---

## 🛰️ 6. The SQLite-LangGraph Bridge (Execution Logic)

This diagram highlights how **SQLite** serves as the persistent anchor for **LangGraph's** volatile execution. It shows the hand-off between session initialization and final message persistence.

```mermaid
flowchart TD
    subgraph "Phase 1: Session Initialization"
        A[API: POST /chat/stream] --> B{history.py: create_session}
        B --> C[(SQLite: sessions table)]
        C --> D[Success: session_id = thread_id]
    end

    subgraph "Phase 2: LangGraph Execution"
        D --> E[graph.ainvoke thread_id]
        E --> F{Nodes: Router / Retriever}
        
        subgraph "Volatile State"
            F --> G[MemorySaver: Snapshot State]
        end
    end

    subgraph "Phase 3: Terminal Persistence"
        F --> H[Node: Generator Complete]
        H --> I{history.py: add_message}
        
        subgraph "Commit to Disk"
            I --> J[(SQLite: messages table)]
            J -.-> J1[Store: Content]
            J -.-> J2[Store: Intent]
            J -.-> J3[Store: Thoughts JSON]
            J -.-> J4[Store: Sources JSON]
        end
    end

    %% Connectivity
    A -.->|thread_id| E
    H -.->|SSE Tokens| K[Frontend UI]

    %% Styling
    style C fill:#dfd,stroke:#333
    style J fill:#dfd,stroke:#333
    style G fill:#fff,stroke-dasharray: 5 5
    style E fill:#e0f2fe,stroke:#0369a1
```

### 🧠 Why the Split?
- **SQLite (sessions/messages)**: Used for "Human-Readable History." This is what allows the user to see their past chats across restarts.
- **Memory (Checkpoints)**: Used for "Machine-Readable Context." This keeps the active "Thinking" process fast and prevents IO-wait deadlocks during streaming.

---

## ⌨️ 6. Common Queries & Manual Management

If you ever need to manually inspect the history, you can open the file with any SQLite viewer (like DB Browser for SQLite) or use these SQL snippets:

### Find the last 10 messages:
```sql
SELECT role, content FROM messages ORDER BY id DESC LIMIT 10;
```

### Delete a specific session:
```sql
DELETE FROM sessions WHERE session_id = 'your_id_here';
-- (Note: Messages will automatically stop appearing as they are FK linked)
```

### Force Rename a Session Title:
```sql
UPDATE sessions SET title = 'New Title' WHERE session_id = 'id';
```

---

## 🛡️ 7. Reliability & Production Standards

- **WAL Mode (Write-Ahead Logging)**: Enabled by default in modern SQLite wrappers for better performance.
-   **Automatic Migrations**: `history.py` includes "Lazy Migration" logic that checks if columns like `thoughts` or `metadata` exist and adds them automatically if missing. This means your data is **future-proof**.
- **UI-Sync Stability**: The frontend uses **Atomic State Logic** during message submission, ensuring that the chronological record in the UI always matches the primary key sequence (ID) in the `messages` table, preventing "state drift" during high-concurrency streaming.

---
---

## 🔐 7. ACID Compliance: The Guardrails of Integrity

To ensure that chat data is never corrupted, IPR RAG uses SQLite's transactional engine to enforce **ACID** properties.

1.  **Atomicity**: Every database operation (e.g., `add_message`) is "All or Nothing." If the system crashes mid-update while saving a message, SQLite rolls back to the previous state, ensuring no partial or corrupted messages exist.
    - *Implementation*: Managed via `conn.commit()` in `backend/state/history.py`.
2.  **Consistency**: The database strictly follows the rules defined in our schema. 
    - *Implementation*: Fields like `session_id` must match their primary key constraints, and timestamps are auto-generated by the engine to ensure chronological accuracy.
3.  **Isolation**: Even with multiple threads (FastAPI async workers) accessing the DB, transactions are isolated.
    - *Implementation*: We use `threading.local()` for thread-private connections, preventing race conditions where two threads try to use the same handle simultaneously.
4.  **Durability**: Once a message is "Committed," it is written to the physical storage (`rag_chat_sessions.db`). Even if the power goes out, your chat history is safe on the disk.

---

## 📊 8. Database Normalization Analysis

The IPR RAG schema is designed for **High Efficiency** and **Zero Redundancy**.

### Does it follow BCNF?
Yes, the schema strictly adheres to **3rd Normal Form (3NF)** and **Boyce-Codd Normal Form (BCNF)**.

| Level | Status | Why? |
| :--- | :--- | :--- |
| **1NF** | ✅ | No repeating groups. All entries are atomic. Even JSON columns are stored as single text blobs to maintain atomic record units. |
| **2NF** | ✅ | All non-key attributes (`title`, `content`, `role`) are fully functionally dependent on their Primary Keys (`session_id` or `id`). |
| **3NF** | ✅ | No transitive dependencies. A message's `content` doesn't depend on the `session_id`'s `title`. Attributes only depend on the Primary Key. |
| **BCNF** | ✅ | For every non-trivial functional dependency, the determinant is a superkey. There are no overlapping candidate keys complicating the dependency structure. |

> [!NOTE]
> **Why use JSON columns if we are normalized?**
> We store `metadata`, `sources`, and `thoughts` as JSON-encoded strings. While this technically puts semi-structured data in a relational column, it avoids "Joins Overload" and keeps retrieval latency sub-millisecond while maintaining professional 3NF structure for the core relationships.

---

## 🗃️ 9. Table-by-Table Attribute Breakdown

### Table: `sessions`
The "Parent" table that tracks unique conversation threads.
- `session_id` (TEXT, PK): The unique UUID or reference for the chat.
- `title` (TEXT): A human-readable name (e.g., "Session 8f2b64cd").
- `created_at` (TIMESTAMP): Time of first interaction.
- `updated_at` (TIMESTAMP): Updated every time a new message is added to keep recent chats at the top.

### Table: `messages`
The "Child" table that stores every turn of the conversation.
- `id` (INTEGER, PK): Auto-incrementing unique ID.
- `session_id` (TEXT, FK): Links the message to its parent session.
- `role` (TEXT): Identifies the speaker (`user` or `assistant`).
- `content` (TEXT): The actual markdown text of the message.
- `intent` (TEXT): The AI-detected intent (e.g., `direct_rag`).
- `sources` (TEXT/JSON): A list of file names used as citations.
- `thoughts` (TEXT/JSON): The "Thinking Process" steps seen in the UI.
- `metadata` (TEXT/JSON): Reserved for future tracing/telemetry markers.
- `created_at` (TIMESTAMP): Precise time of the message.

---

*End of Document • v1.6.1 Platinum History Standard*

