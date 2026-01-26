# 🧙‍♂️ Debug Suite Guide (v2.1)

The **RAG Chat IPR** system includes a powerful, interactive terminal-based debugging suite. This "Debug Wizard" allows you to inspect the system's brain, test retrievals, and verify document ingestion without starting the full backend server.

## 🚀 Launching the Wizard

Run the following command in your terminal:

```bash
uv run embedding_debug.py
```

You will be greeted by the Interactive Wizard menu:

```text
==================================================
   🧙‍♂️ RAG Chat IPR - Interactive Debug Wizard
==================================================
1.  🔄 Rebuild Knowledge Base (Clear & Re-ingest)
2.  👁️  Inspect VLM Output (Markdown Dumps)
3.  🔍 Semantic Probe (Test Search Quality)
4.  📂 List Indexed Documents
5.  ❌ Delete Specific Document
6.  👋 Exit
==================================================
```

---

## 🛠️ Feature Breakdown

### 1. 🔄 Rebuild Knowledge Base
*   **What it does**: Completely wipes the ChromaDB vector store and re-processes ALL files in `upload_docs/`.
*   **When to use**: 
    *   After changing the embedding model.
    *   If you suspect data corruption.
    *   To apply new chunking logic to existing files.
*   **Safety**: Prompts for confirmation before deletion.

### 2. 👁️ Inspect VLM Output (**NEW in v2.1**)
*   **What it does**: Browses the `VLM_generated_md_docs/` directory where the DeepSeek OCR dumps raw markdown.
*   **Features**:
    *   Displays file sizes and modification times.
    *   **Visual Density Score**: Calculates the ratio of images/tables to text.
    *   Allows you to read the first 500 lines of any dump directly in the terminal.
*   **Use Case**: Verify if the OCR is correctly detecting tables and diagrams in your PDFs.

### 3. 🔍 Semantic Probe
*   **What it does**: Simulates a user query against the vector database.
*   **Advanced Features**:
    *   **Targeted Search**: Prefix your query with `@filename.pdf` to search ONLY that do.
        *   Example: `@manual.pdf how to reset?`
    *   **Graph Routing Simulation**: Shows you exactly how the Router would classify the query.
    *   **Results**: specific chunks with their **Distance Score** (lower is better).

### 4. 📂 List Documents
*   **What it does**: Shows a clean table of all files currently indexed in ChromaDB.
*   **Details**: Shows chunk counts per file to help identify partial ingestions.

### 5. ❌ Delete Specific Document
*   **What it does**: Removes all vectors associated with a specific filename.
*   **Use Case**: Removing a sensitive or incorrect document without rebuilding the entire database.

---

## 🏗️ Architecture

The Debug Wizard is built on the same core libraries as the Backend:
*   **Core**: `backend.rag.store` (ChromaDB interface)
*   **Config**: `backend.config` (Loads your `.env`)
*   **UI**: `rich` (For beautiful terminal tables and spinners)

It respects ensuring that what you see in the Wizard is EXACTLY what the RAG engine sees at runtime.
