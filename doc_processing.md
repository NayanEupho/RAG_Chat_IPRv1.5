# Document Processing & Ingestion Pipeline (Platinum Edition)

This document provides a technical deep-dive into how RAG Chat IPR v1.6 transforms raw files into a "Smart Knowledge Base."

## 1. Multi-Stage Ingestion Flow
The ingestion process is triggered by the `WatchdogService` (in `watcher.py`) or manually via the `Unified Debug Manager` (`embedding_debug.py`).

### Step A: High-Fidelity Conversion (Docling & Fast-Path)
We use a dual-pipeline approach to ensure maximum speed and accuracy:
1. **Platinum Fast-Path (.txt, .md)**: Simple text and markdown files are read directly using native IO. This skips heavy layout analysis, resulting in **10x faster ingestion** for knowledge-dense text files.
2. **Structural Conversion (Docling)**: Complex formats (PDF, DOCX, PPTX, etc.) use the **IBM Docling** engine in `processor.py`.
   - **OCR Integration**: If a PDF contains images of text, Docling uses OCR to extract it.
   - **Table Preservation**: Tables are converted into standard Markdown tables (`| Col 1 | Col 2 |`) to ensure the LLM maintains structural awareness of tabular data.

### Step B: Recursive Hierarchical Chunking (Platinum)
Unlike static chunking, our system uses a **Recursive Header Stack** to track the document's structure during processing.

1. **Header Tracking**: The parser identifies headers (`#` to `######`).
2. **Breadcrumb Generation**: It maintains a stack of headers to create a "path" for every chunk.
   - Example: `Networking > Security > Port Rules`.
3. **Recursive Splitting**: If a section is larger than 2000 characters, it is recursively split into sub-chunks with a 400-character overlap.
4. **Contextual Prefix (Injunction)**: Every chunk is physically prefixed with its document and section identity *before* embedding.
   ```text
   [Doc: manual.pdf | Path: Maintenance > Recovery]
   The following steps reset the server...
   ```

## 2. Batch Embedding & Storage
Once chunks are generated, they are vectorized in batches (size: 50) using the configured Ollama embedding model (e.g., `embeddinggemma:300m`).

### ChromaDB Data Structure
Each embedding is stored in ChromaDB alongside a rich metadata payload:
| Key | Type | Description |
| :--- | :--- | :--- |
| `filename` | String | Base name of the file. |
| `source` | String | Full absolute path for traceability. |
| `chunk_index` | Integer | Sequential ID used for neighbor retrieval (Sliding Window). |
| `section_path` | String | The recursive breadcrumb (e.g., `A > B > C`). |
| `header_level` | Integer | Depth of the section (1 for H1, 6 for H6). |
| `is_fragment` | Boolean | True if the chunk is a continuation of a larger section. |

## 3. Platinum Retrieval & Prompt Engineering
When a user asks a query, the **Retriever Node** performs three specific actions to maximize the "Intelligence" of the result:

### A. Semantic Search + Sliding Window
1. The system finds the top matches based on cosine similarity.
2. For every match, it automatically fetches the **Preceding (-1)** and **Succeeding (+1)** chunks using the `chunk_index` metadata. This prevents "Choppy" answers.

### B. Super-Structured Prompting
The retrieved chunks are formatted into a "Platinum Envelope" before being appended to the `AgentState`. This structure ensures the LLM understands exactly where each piece of info originates.

**The prompt-block data structure:**
```markdown
--- DOCUMENT SEGMENT ---
Source: Security_Policy.pdf
Section: Setup > Firewall > Port Rules
Content:
The following ports must be opened for the DevOps agent...
```

### C. LLM Integration
These segments are injected into the `<knowledge_base>` tag in the final prompt. The LLM then uses this structured data to generate an answer with precise citations like: 
> "According to the Security_Policy.pdf (Section: Setup > Firewall), port 8080 must be open."

---
*Last Updated: January 2026 for RAG Chat IPR v1.6*
