# Document Processing & Ingestion Pipeline (Platinum Edition)

This document provides a technical deep-dive into how RAG Chat IPR v1.7 transforms raw files into a "Smart Knowledge Base."

## 1. Multi-Stage Ingestion Flow

The ingestion process is triggered by the `WatchdogService` (in `watcher.py`) or manually via the `Unified Debug Manager` (`embedding_debug.py`).

### Step A: OCR Engine Selection

| Engine | When Used | Features |
| :--- | :--- | :--- |
| **Docling (Default)** | `RAG_VLM_MODEL="False"` | Fast, good for digital PDFs |
| **DeepSeek VLM** | `RAG_VLM_MODEL="deepseek-ocr:3b"` | High-fidelity for scanned docs |

### Step B: High-Fidelity Conversion

1. **Platinum Fast-Path (.txt, .md)**: Simple text and markdown files are read directly using native IO. This skips heavy layout analysis, resulting in **10x faster ingestion**.

2. **Docling Pipeline (PDF, DOCX, etc.)**: Uses IBM Docling engine with OCR and table preservation.

3. **DeepSeek VLM Pipeline (PDFs)**: Two-pass vision extraction:
   - **Pass 1 (Grounding)**: Extracts document structure, tables, headers
   - **Pass 2 (Describe)**: Auto-detects unlabeled visuals and adds descriptions

### Step C: Visual-Aware Hierarchical Chunking

1. **Header Tracking**: The parser identifies headers (`#` to `######`).
2. **Breadcrumb Generation**: Maintains a stack of headers for path generation.
   - Example: `Networking > Security > Port Rules`.
3. **Visual Boundary Protection**: Tables and figures are kept intact during chunking.
4. **Recursive Splitting**: Large sections split with 400-character overlap.
5. **Contextual Prefix**: Every chunk is prefixed with identity:
   ```text
   [Doc: manual.pdf | Path: Maintenance > Recovery]
   The following steps reset the server...
   ```

## 2. Visual Element Detection

DeepSeek OCR detects and extracts visual elements:

| Type | Pattern | Stored As |
| :--- | :--- | :--- |
| `diagram` | `Figure X:`, `Fig. X:` | `visual_type: "diagram"` |
| `table` | Markdown tables, `Table X:` | `visual_type: "table"` |
| `chart` | `Diagram X:`, `Chart X:` | `visual_type: "chart"` |
| `image` | DeepSeek `> [Image: ...]` | `visual_type: "image"` |

## 3. ChromaDB Metadata Schema

| Key | Type | Description |
| :--- | :--- | :--- |
| `filename` | String | Base name of the file |
| `source` | String | Full absolute path |
| `chunk_index` | Integer | Sequential ID for neighbor retrieval |
| `section_path` | String | Recursive breadcrumb (`A > B > C`) |
| `header_level` | Integer | Depth of section (1-6) |
| `is_fragment` | Boolean | True if continuation of larger section |
| `has_visual` | Boolean | True if chunk contains visual elements |
| `visual_type` | String | `diagram`, `table`, `chart`, `image`, or null |
| `visual_title` | String | Caption/description of visual |
| `visual_count` | Integer | Number of visuals in chunk |

## 4. Platinum Retrieval & Prompt Engineering

### A. Semantic Search + Sliding Window
1. Top matches by cosine similarity
2. Preceding (-1) and Succeeding (+1) chunks fetched for context

### B. Super-Structured Prompting (Platinum Envelope)

```markdown
--- DOCUMENT SEGMENT ---
Source: Security_Policy.pdf
Section: Setup > Firewall > Port Rules
Visual: [DIAGRAM] Fig. 3 - Network Topology
Content:
The following diagram shows the network architecture...
```

> **Note**: The `Visual:` field is dynamic. It only appears if the chunk contains a `visual_type` (e.g., Diagram, Table). The UI uses this tag to display special badges (e.g., `[DIAGRAM]`) in the source strip.

### C. LLM Integration
Segments are injected into `<knowledge_base>` tags. The LLM generates citations like:
> "According to Security_Policy.pdf (Section: Setup > Firewall), port 8080 must be open."

---
*Last Updated: January 2026 for RAG Chat IPR v1.7*
