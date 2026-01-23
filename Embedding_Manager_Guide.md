# 🛠️ Unified Embedding Debug Manager Guide (`embedding_debug.py`)

The **Unified Embedding Debug Manager** is the single command-line interface designed for professional maintenance of the **RAG Chat IPR** Knowledge Base. It replaces multiple legacy scripts with a robust, fail-fast, and high-fidelity utility.

---

## 🏗️ Technical Implementation

The tool is built as an asynchronous CLI wrapper around core system singletons:
- **`VectorStore`**: Handles atomic deletion and collection resets.
- **`DocumentProcessor`**: Orchestrates the high-fidelity **Docling** pipeline (OCR, Table Extraction, Hierarchical Chunking).
- **`OllamaClient`**: Manages batch-embeddings for high-speed indexing.

### 🛡️ Core Robustness Logic
1.  **Strict Environment Lockdown**: Upon launch, the tool explicitly calls `load_dotenv()`. It performs a **Fail-Fast** check: if required variables like `RAG_EMBED_HOST` are missing, it exits with a diagnostic error instead of defaulting to `localhost`.
2.  **Noise Mitigation**: The tool implements a dual-layer filtering system:
    *   **File Level**: Skips hidden files (`.gitkeep`) and temporary system files (`~$OfficeDoc.docx`).
    *   **Format Level**: Only whitelisted extensions (`.pdf`, `.docx`, `.pptx`, `.html`, `.txt`, `.md`) are permitted.
3.  **Atomic Operations**: Selective re-indexing uses an "Atomic Deletion" pattern—it deletes the old records *before* starting the new parsing, ensuring zero duplication even if the process is interrupted.

---

## 🛰️ Command Encyclopedia

### 1. `rebuild`
**Description**: Performs a total system reset and fresh index of the `upload_docs/` directory.

- **Use case**: Switching embedding models, clearing corrupted metadata, or first-time setup.
- **Execution Workflow**: 
    1.  Clear collection.
    2.  Scan `upload_docs/` (filtering noise).
    3.  Sequential processing of all valid documents.
- **Example**:
    ```bash
    uv run python embedding_debug.py rebuild
    ```

---

### 2. `reindex`
**Description**: Selectively refreshes specific files in the Knowledge Base.

- **Use case**: Content updates to a specific document, fixing extraction errors, or adding a single new file.
- **Execution Workflow**: 
    1.  Atomic deletion of the specific filename.
    2.  From-scratch re-processing (Parsing -> Chunking -> Embedding).
- **Examples**:
    ```bash
    # Single file
    uv run python embedding_debug.py reindex upload_docs/Manual_v2.pdf

    # Multiple files
    uv run python embedding_debug.py reindex upload_docs/Manual_v2.pdf upload_docs/Policy.docx

    # Pattern based (Shell dependent)
    uv run python embedding_debug.py reindex upload_docs/*.pdf
    ```

---

### 3. `list`
**Description**: Provides a real-time inventory of all documents currently indexed in ChromaDB.

- **Output**: Filename and the exact number of hierarchical chunks generated.
- **Example**:
    ```bash
    uv run python embedding_debug.py list
    ```

---

### 4. `probe`
**Description**: Tests the semantic retrieval engine directly.

- **Description**: Displays the raw text chunks, mathematical "Distance" scores, and the **Recursive Section Path** that the database returns for a query.
- **Use case**: Debugging why the AI gave a specific answer or testing retrieval relevance for complex terms.
- **Example**:
    ```bash
    uv run python embedding_debug.py probe "What is the API safety protocol?"
    ```

---

## 🔍 Understanding the Output

### Terminal Icons:
- ✅ **Done / Refreshed**: Operation succeeded perfectly.
- ⚠️ **Skipped**: File was ignored due to being hidden, temporary, or an unsupported format.
- ❌ **Error / Configuration Error**: Critical failure. Check your `.env` or network connection to the LLM host.

### Metric Check:
- **Chunks**: If a large PDF has `< 5` chunks, it may have been unreadable or empty.
- **Distance (Probe mode)**: 
    - `< 0.8`: Excellent match.
    - `0.8 - 1.2`: Moderate relevance.
    - `> 1.2`: Low relevance; likely noise.

---
