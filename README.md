# IPR RAG Chat v1.7

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
        Watcher --> Proc{VLM or Docling?}
        Proc -->|VLM| Vision[DeepSeek OCR]
        Proc -->|Docling| DocProc[Docling Processor]
        Vision --> DB[(ChromaDB)]
        DocProc --> DB
        Gen -- "Local LLM" --> Ollama[Ollama]
    end

    Gen --> UI
```

---

## 🌟 New Features (v1.7)

*   **🔬 DeepSeek VLM OCR**: High-fidelity vision-based extraction for scanned PDFs and complex layouts.
*   **🎯 Two-Pass Extraction**: Auto-detects unlabeled images and adds AI-generated descriptions.
*   **📊 Visual-Aware Chunking**: Tables and diagrams are protected from fragmentation during chunking.
*   **🖼️ Visual Metadata**: Chunks tagged with `has_visual`, `visual_type`, and `visual_title` for smarter retrieval.
*   **⚙️ Configurable VLM Prompts**: Choose between `auto`, `grounding`, `describe`, and `parse_figure` modes.
*   **🕹️ Intelligence Mode Selector**: Seamlessly switch between **Auto**, **RAG**, and **Chat** modes.
*   **🧠 Unified Session Context**: 10-turn sliding memory window ensures the AI never loses context.
*   **⚡ Dynamic Step Fusion**: Switchable architecture (`fused`/`modular`) reduces latency by 60%.
*   **✂️ Brevity-First Strategy**: Default concise responses with automatic "Deep Dive" mode.
*   **🛑 Master Stop Toggle**: Halts both UI stream and backend LLM processing instantly.
*   **📑 Hierarchical RAG**: Section-aware chunking preserves header-body relationships.
*   **💎 Premium Glassmorphic UI**: High-speed interface with live thinking states and buttery animations.


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
- [**VLM OCR Pipeline**](./VL_OCR_Implementation_Plan.md): DeepSeek vision extraction and two-pass processing.
- [**Document Processing**](./doc_processing.md): Chunking strategies, visual metadata, and Platinum Envelope format.
- [**Database Encyclopedia Suite**](./Unified_Database_Guide.md): 
    - [Vector Database (ChromaDB)](./Vector_Database_Encyclopedia.md)
    - [Session History (SQLite)](./Session_History_Encyclopedia.md)
- [**Debugging & Monitoring**](./DEBUG_SUITE_GUIDE.md): Guide to the maintenance and probing utilities.
- [**Embedding Manager Guide**](./Embedding_Manager_Guide.md): Specialized documentation for `embedding_debug.py`.
- [**RAG Strategies**](./RAG%20Strategies.md): Technical breakdown of the ingestion and retrieval chain.
- [**Usage Guides**](./Master_Usage.md): Setup and feature documentation for end-users.

