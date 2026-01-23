# Master Usage Guide (v1.5)

This guide is the definitive source for **Setting Up**, **Configuring**, and **Operating** the **IPR RAG Chat v1.5** system.

---

## 🛠 1. Fresh Installation & Setup

### Prerequisites
- **Python 3.13+**: Optimized for the latest asynchronous patterns in LangGraph.
- **uv**: A high-performance Python package manager. Install via `pip install uv`.
- **Bun**: A fast JavaScript runtime and package manager.
- **Ollama**: Ensure the Ollama server is running and accessible.

### Step-by-Step Installation

1. **Synchronize Python Environment**
   ```bash
   uv sync
   ```
   *   **What it does**: Creates a `.venv` and installs all locked dependencies (`langgraph`, `docling`, `chromadb`, etc.).

2. **Install Frontend Dependencies**
   ```bash
   cd frontend
   bun install
   cd ..
   ```

---

## 🚀 2. Operational Workflow

### Starting the Backend (The Brain)
```bash
uv run main.py
```
The startup process uses a **Hybrid Configuration System**:

1.  **Automated (.env)**: If a `.env` file exists (copy `.env.example` to create one), the system will verify the hosts and models. If valid, it skips the wizard for instant startup.
2.  **Interactive Wizard**: If no `.env` is found (or if validation fails), the script launches a guided setup to select your Ollama host and specific models for **Chat** and **Embeddings**.
3.  **Background Services**: Once configured, the system automatically starts the `Watchdog` and `Ingestion Worker` for real-time document indexing.

---

## ⚡ 3. Performance Optimization

### Dynamic Step Fusion (The Speed Switch)
You can choose your graph architecture in your `.env` file:
- **`RAG_WORKFLOW="fused"`**: (Recommended for 70B+ models). Combines planning and retrieval into one step. Reduces latency significantly.
- **`RAG_WORKFLOW="modular"`**: (Recommended for 7B/14B models). Uses a sequential chain (Router → Rewriter → Retriever) for maximum stability on smaller models.

---

## 🖥 4. Interface & Intelligence Modes

### Modern Web GUI (Recommended)
Navigate to `http://localhost:3000` after running `bun dev` in the frontend folder.

#### 🛑 Full-Stack Stop Control
If the AI starts a long generation you don't need, click the **Red Stop Button** (replaces the Send arrow). This kills both the UI stream and the backend LLM task immediately.

#### ✂️ Brevity Control
By default, the AI ignores "fluff" and provides concise (< 4 sentence) answers.
- **To see more**: Ask *"Explain in detail"* to unlock comprehensive mode.

#### 🕹️ Intelligence Mode Selector:
- **Auto (Smart)**: Automatically detects if you need document search or casual chat.
- **RAG (Knowledge)**: Forces the AI to strictly search your uploaded documents.
- **Chat (Assistant)**: Bypasses the knowledge base for pure LLM brainstorming.

#### 📍 Semantic @Mentions:
Type `@` followed by a filename (e.g., `@Policy_v2.pdf`) to pin a specific document to your query. You can mention multiple files for comparisons.

#### 🧠 Thinking Process Viewer:
Watch the AI's step-by-step reasoning (Analyzing → Searching → Generating) in real-time.

---

## 🛡 5. Professional Maintenance Suite

The `embedding_debug.py` tool is your unified "Swiss Army Knife" for vector database management. It replaces all legacy maintenance scripts with a single robust interface.

### Standard Commands:
```bash
# A. Show current inventory and chunk counts
uv run python embedding_debug.py list

# B. Selective Re-index (From scratch re-processing for specific files)
uv run python embedding_debug.py reindex "@MyDocument.pdf"

# C. Semantic Probing (Test raw retrieval scores for a query)
uv run python embedding_debug.py probe "system architecture"

# D. Total Rebuild (Hard reset and fresh index of all documents)
uv run python embedding_debug.py rebuild
```

### 💡 Why use `reindex`?
Unlike a full rebuild, `reindex` allows you to refresh a single document (fixing typos or updating content) without stopping the system or wiping the entire library. It performs a **from-scratch re-construction** (Docling Parsing → Hierarchical Chunking → Embedding) to ensure 100% system consistency.

---

## ❓ Troubleshooting
- **Network Error**: Ensure Ollama is running and the host selected in the wizard is reachable.
- **Red Status Indicators**: A red dot in the sidebar ("AI Model Config") means the specific model is either offline or its name is not found on the host. Run `ollama list` on the host to verify.
- **Session Reset**: Use the **Trash Icon** in the sidebar to permanently delete a session and reset the agent's memory.
