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
- **Red Status Indicators**: A red dot in the sidebar ("AI Model Config") means the specific model is either offline or its name is not found on the host. Run `ollama list` on the host to verify.
- **Session Reset**: Use the **Trash Icon** in the sidebar to permanently delete a session and reset the agent's memory.
