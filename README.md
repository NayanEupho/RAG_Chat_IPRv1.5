# IPR RAG Chat v1.6.1

A production-grade, modular, and agentic RAG (Retrieval-Augmented Generation) system. Built with **FastAPI**, **LangGraph**, **Ollama**, **Docling**, and **Next.js**.

```mermaid
graph TD
    User([User]) --> UI[Modern Web UI]
    UI -- "Mode (Auto/RAG/Chat)" --> API[FastAPI Gateway]
    
    subgraph "Intelligent Orchestration (LangGraph)"
        API --> Config{Fused or Modular?}
        
        Config -- "Fused (Speed)" --> Planner[One-Shot Planner]
        Planner -->|RAG| Retriever[Context Retriever]
        Planner -->|Chat| Gen
        
        Config -- "Modular (7B/14B)" --> Router{Intent Router}
        Router -- "@mentions" --> Segmenter[Semantic Segmenter]
        Router -- "Auto Routing" --> Decision[Heuristic Matcher]
        
        Segmenter --> Retriever
        Decision -- "Context needed" --> Rewriter[Query Rewriter]
        Rewriter --> Retriever
        
        Retriever --> Rerank[FlashRank Filter]
        Rerank --> Gen[Adaptive Generator]
        Decision -- "Casual Chat" --> Gen
    end

    subgraph "Core Engines"
        Files[(upload_docs/)] --> Watcher[Watchdog]
        Watcher --> Proc[Docling Processor]
        Proc --> DB[(ChromaDB)]
        Gen -- "Local LLM" --> Ollama[Ollama]
    end

    Gen --> UI
```

---

## 🌟 New Features (v1.5)

*   **🕹️ Intelligence Mode Selector**: Seamlessly switch between **Auto** (Smart Intent Detection), **RAG** (Strict Knowledge Base), and **Chat** (Pure LLM) modes.
*   **🧠 Unified Session Context**: 10-turn sliding memory window ensures the AI never loses context, even when switching interaction modes.
*   **⚡ Adaptive Knowledge Injection**: The system intelligently decides *when* to inject documents into the prompt, reducing token noise and hallucinations.
*   **📍 Semantic @Mentions**: Pinpoint exactly which files the AI should read by typing `@filename` directly in the chat.
*   **🛡️ Unified Maintenance Suite**: Single-command `embedding_debug.py` for total rebuilds, selective re-indexing, and semantic probing. Replacing all legacy scripts.
*   **⚡ Dynamic Step Fusion**: Switchable architecture (`fused`/`modular`) that reduces latency by 60% using a single-shot "Planner" node for large models.
*   **✂️ Brevity-First Strategy**: Default concise responses (< 4 sentences) for maximum efficiency, with automatic "Deep Dive" mode for detailed queries.
*   **🛑 Master Stop Toggle**: A "Hard Stop" mechanism that halts both the UI stream and backend LLM processing instantly, preventing resource waste.
*   **📑 Hierarchical RAG**: Section-aware chunking preserves the relationship between headers and body text for surgical accuracy.
*   **🩺 Proactive Health Probing**: Real-time monitoring of Ollama hosts and model availability ensures zero-latency failure detection.
*   **💎 Premium Glassmorphic UI**: High-speed interface featuring live thinking states, source-strip transparency, and buttery animations.

## 🛠 Tech Stack

*   **Orchestration**: LangGraph (Stateful Agentic Workflow)
*   **LLM & Embeddings**: Ollama (Split-host and Batch-embedding support)
*   **Ingestion Engine**: IBM Docling (Resilient multi-stage parsing with Section-Awareness)
*   **Vector Engine**: ChromaDB (hnsw:cosine)
*   **Re-ranking**: FlashRank (ms-marco-TinyBERT-L-2-v2)
*   **Frontend**: Next.js 15, Vanilla CSS, Lucide Icons

---

## 📦 Quick Start

### 1. Prerequisites
- **Python 3.13+** & **uv**
- **Ollama** (Running & Host accessible)
- **Bun** or **Node.js**

### 2. Installation & Launch
```bash
# 1. Start Backend (Interactive Configuration Wizard)
# Hint: Copy .env.example to .env for zero-click setup!
# Note: Set RAG_WORKFLOW="fused" in .env for maximum speed (requires 70B+ model)
uv run main.py

# 2. Start Frontend
cd frontend
bun install && bun dev

# 💡 Production info
# Never use 'bun dev' for long-term deployment.
# Run 'bun run build' followed by 'bun run start' for SOTA performance.
bun run build
bun run start
```

Visit **http://localhost:3000** to enter the Command Center.

---

## 📖 Component Deep-Dives
- [**Architecture & Orchestration**](./Architecture_Guide.md): Detailed logic mapping of the LangGraph nodes.
- [**API Server Encyclopedia**](./API_Server_Guide.md): Deep dive into FastAPI, SSE, and Request Lifecycles.
- [**Database Encyclopedia Suite**](./Unified_Database_Guide.md): 
    - [Vector Database (ChromaDB)](./Vector_Database_Encyclopedia.md)
    - [Session History (SQLite)](./Session_History_Encyclopedia.md)
- [**Debugging & Monitoring**](./DEBUG_SUITE_GUIDE.md): Guide to the maintenance and probing utilities.
- [**Embedding Manager Guide**](./Embedding_Manager_Guide.md): Specialized documentation for `embedding_debug.py`.
- [**RAG Strategies**](./RAG%20Strategies.md): Technical breakdown of the ingestion and retrieval chain.
- [**Usage Guides**](./Master_Usage.md): Setup and feature documentation for end-users.

---

*Note: This codebase has undergone a comprehensive documentation overhaul (v1.6.1), including module-level docstrings, enhanced internal comments, and Git maintenance (gitignore/gitkeep).*
