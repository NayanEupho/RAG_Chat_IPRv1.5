# Master Usage Guide (Platinum Sync)

This guide is the definitive source for **Setting Up**, **Configuring**, and **Operating** the **IPR RAG Chat v1.7** system.

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
1.  **Interactive Wizard**: Select your Ollama host and specific models for **Chat** and **Embeddings**.
2.  **Background Services**: Automatically starts the `Watchdog` and `Ingestion Worker` for real-time document indexing.

---

## 🖥 3. Interface & Intelligence Modes

### Modern Web GUI (Recommended)
Navigate to `http://localhost:3000` after running `bun dev` in the frontend folder.

#### 🕹️ Intelligence Mode Selector:
- **Auto (Smart)**: Automatically detects if you need document search or casual chat.
- **RAG (Knowledge)**: Forces the AI to strictly search your uploaded documents.
- **Chat (Assistant)**: Bypasses the knowledge base for pure LLM brainstorming.

#### 📍 Semantic @Mentions:
Type `@` followed by a filename (e.g., `@Policy_v2.pdf`) to pin a specific document to your query. You can mention multiple files for comparisons.

#### 🧠 Thinking Process Viewer:
Watch the AI's step-by-step reasoning (Analyzing → Searching → Generating) in real-time.

---

## 🛡 4. Professional Maintenance Suite

Instead of manual folder deletion, use these high-fidelity utilities for system integrity:

### A. Total Reset (Fresh Start)
If you switch embedding models or need a clean slate:
```bash
python rebuild_knowledge_base.py
```
*   **Purge**: Physically wipes the vector DB.
*   **Re-sync**: Automatically detects server settings and re-indexes `upload_docs/`.

### B. Semantic Probing & Inventory
To peek into the "mind" of the vector store:
```bash
# See all indexed files and chunk counts
python kb_debug.py --inventory

# Test raw retrieval scores for a specific query
python kb_debug.py --probe "your search query"
```

---

## ❓ Troubleshooting
- **Network Error**: Ensure Ollama is running and the host selected in the wizard is reachable.
- **Low Accuracy**: Use the `--probe` command in `kb_debug.py` to verify if your documents are being retrieved correctly.
- **Session Reset**: Use the **Trash Icon** in the sidebar to permanently delete a session and reset the agent's memory.
