# CLI Usage Guide (Platinum Edition)

For developers and power users, the **IPR RAG Chat CLI** provides a direct, low-latency interface to the system's brain.

---

## 🛠 Operation

### 1. Launch the Interface
Ensure the Backend is already running (`uv run main.py`). 
> [!TIP]
> With the new **Hybrid Configuration System**, if you have a `.env` file configured, the backend starts instantly without interactive prompts, making CLI access even faster.

```bash
uv run cli.py
```

### 2. Interaction Syntax
- **Pure Chat**: Type naturally. The "Auto" router will manage the intent.
- **Targeted RAG**: Type `@filename <your query>` to force search on a specific file.
- **Commands**:
    - `/exit`: Close the session.
    - `/history`: (Upcoming) View past interaction logs.

---

## 🚀 Native Features

- **Rich Terminal UI**: Automatically detects dark/light themes and applies syntax highlighting to code blocks.
- **Session Persistence**: Even if you close the terminal, your session is saved in `rag_chat_sessions.db`. The CLI will automatically resume your last active session by default.
- **Auto-Routing**: By default, the CLI uses the `auto` mode, leveraging the intelligent LangGraph router to decide between chat and document search.

---

## 📡 Remote Connectivity

The CLI can connect to any IPR RAG instance on your network:

```bash
uv run cli.py --url http://192.168.1.50:8000
```
*   **Latency**: The CLI uses advanced HTTP/2 streaming via `httpx`, ensuring tokens appear as fast as the LLM generates them.
