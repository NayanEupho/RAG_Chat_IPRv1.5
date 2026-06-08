# Agentic RAG Ingestion, Chunking, Retrieval, and Response-Depth Plan

## Goal

Build a production-ready ingestion and retrieval pipeline where new uploaded documents are parsed with Docling plus LLM Markdown normalization by default, then chunked with hierarchical structure awareness, retrieved surgically, and passed to the agent in a stable platinum evidence envelope without breaking prompt/prefix caching.

Primary success targets:

- New server-side uploads default to `docling + llm_normalize`.
- General documents use normalized-Markdown-aware hierarchical chunking.
- QnA documents continue to use strict Q/A pair chunking.
- Final model-visible evidence is dense, structured, and grounded.
- Follow-up questions dynamically choose between existing context, fresh retrieval, or hybrid retrieval.
- Responses are concise but complete, not artificially capped to very short answers.
- Prompt/prefix caching remains stable by keeping static instructions in the system prompt and dynamic evidence in the user message.

## Phase 1 - Server Default Ingestion: Docling + LLM Normalization

### Objective

When `main.py` server is running and files are added under `upload_docs`, ingestion must default to:

```text
parser = docling
llm_normalize = true
```

This must apply to watcher/API/server ingestion paths, not only the CLI.

### Steps

1. Add explicit config support for LLM normalization.
   - Add config field like `ingest_llm_normalize: bool`.
   - Read env:
     ```env
     INGEST_LLM_NORMALIZE=true
     RAG_PARSING_MODE=docling
     ```
   - Update `.env.example`.

2. Update `DocumentProcessor.process_file`.
   - If no explicit `mode` is provided, use configured parsing mode.
   - If no explicit `llm_normalize` is provided, use configured normalization flag.
   - Preserve CLI override behavior.

3. Update watcher/server ingestion.
   - Verify `backend/ingestion/watcher.py`.
   - Verify API upload/reindex paths in `backend/api/routes.py`.
   - Ensure they pass either no parser mode or the configured parser mode, but normalization remains enabled by default.

4. Keep explicit parser triggers intact.
   - CLI:
     ```powershell
     .\.venv\Scripts\python.exe embedding_debug.py parse "upload_docs\General\file.pdf" --parser pymupdf4llm
     ```
   - CLI with normalization:
     ```powershell
     .\.venv\Scripts\python.exe embedding_debug.py parse "upload_docs\General\file.pdf" --parser docling --llm-normalize
     ```

### Tests

Unit tests:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_parser_backends.py tests\test_llm_normalizer.py -q
```

Add tests:

- `DocumentProcessor.process_file(..., mode=None, llm_normalize=None)` resolves to configured `docling`.
- Watcher/API ingestion uses config normalization by default.
- Explicit parser override wins over config.
- Explicit `llm_normalize=False` wins over config when called intentionally.

Manual smoke:

```powershell
.\.venv\Scripts\python.exe embedding_debug.py parse "upload_docs\General\LeaveAtaGlance.pdf" --parser docling --llm-normalize --output-dir generated_doc_md\smoke_default
```

Acceptance criteria:

- New upload ingestion emits artifact path under `generated_doc_md/<file>/docling_llm_normalized/<timestamp>/`.
- `selected.md`, `raw.md`, `normalized.md`, `normalization_manifest.json`, and diagnostics are written.
- Normalization manifest status is `accepted` or falls back safely with a clear reason.

## Phase 2 - Normalized Markdown Contract

### Objective

Define the Markdown shape that downstream chunking can rely on.

### General Document Contract

Expected normalized Markdown:

```markdown
# Document Title

> Optional subtitle/callout

**Author:** Name
**Date:** Date

## Table of Contents
- [1. Section](#1-section)

## 1. Top-Level Section

### 1.1 Subsection

Paragraph text.

```bash
command example
```

| Column | Column |
| :--- | :--- |
| Value | Value |

[Figure 1: image content not available in extracted text]
```

General rules:

- No PDF page-number noise.
- No TOC dot leaders.
- No duplicate TOC.
- No broken headings like `## Command` and `## Description` caused by parser table artifacts.
- Code blocks must remain fenced.
- Tables must remain valid Markdown tables when possible.
- Figure placeholders should be honest and retrieval-safe.

### QnA Document Contract

Expected normalized Markdown:

```markdown
Q: What is the question?

A: Answer text.

---
```

Rules:

- Preserve every Q/A pair.
- Do not merge separate questions.
- Keep lists/tables inside the relevant answer.
- Preserve question numbers when visible.

### Tests

Add contract tests:

- General normalizer produces stable headings and TOC links.
- QnA normalizer preserves Q/A pair count.
- Normalizer rejects outputs with too-low word retention.
- Normalizer rejects unbalanced code fences.

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_llm_normalizer.py -q
```

Acceptance criteria:

- `TECHNICAL_REPORT_V8.pdf` normalized output has no known parser artifacts.
- `LeaveAtaGlance.pdf` normalized output preserves leave table semantics.
- `FAQ_LTDP_28Dec11.pdf` normalized output preserves Q/A pairs.

## Phase 3 - Hierarchical Structure-Aware Chunking For General Docs

### Objective

Replace brittle sparse chunking with a normalized-Markdown-aware chunker for general documents.

This should be implemented as a dedicated `NormalizedMarkdownChunker`, not by routing normalized Docling output through `VisionChunker`. Vision-specific heuristics are still useful for VLM page output, but normalized Docling Markdown now has cleaner structural signals and should be chunked as a semantic Markdown document.

### Key Design Correction

Do not embed the full platinum prompt envelope into Chroma document text. Store rich structure in metadata and render the final platinum envelope only after retrieval.

Use two representations:

```text
embedding_text:
Technical Report: DevOps Agent > 4. Technology Stack Overview > 4.2 Component Breakdown

## 4.2 Component Breakdown

actual evidence content...

metadata:
source, parser, normalized, section_path, chunk_kind, parent_section, prev_index, next_index, etc.

final_agent_envelope:
rendered by retriever from metadata + retrieved text after reranking
```

Reason:

- Embeddings should focus on semantic content and useful section path terms.
- Labels like `Parser`, `ChunkKind`, `Normalized`, and `Neighbors` are useful for the agent but noisy for vector similarity.
- Rendering the platinum envelope late keeps retrieval clean and prompt evidence rich.

### Chunk Types

The chunker should emit:

```text
doc_summary
section
section_fragment
table
table_row
code
figure
```

### Metadata Contract

Every chunk should include:

```json
{
  "source": "upload_docs/General/file.pdf",
  "doc_id": "stable_id",
  "filename": "file.pdf",
  "doc_type": "general",
  "parser": "docling_llm_normalized",
  "normalized": true,
  "chunk_index": 12,
  "prev_index": 11,
  "next_index": 13,
  "chunk_kind": "section",
  "section_title": "4.2 Component Breakdown",
  "section_path": "Technical Report > 4. Technology Stack Overview > 4.2 Component Breakdown",
  "parent_section": "4. Technology Stack Overview",
  "heading_level": 3,
  "has_table": true,
  "has_code": false,
  "has_figure": false,
  "start_line": 120,
  "end_line": 148
}
```

### Chunking Rules

1. Tokenize normalized Markdown into typed blocks:
   - heading
   - paragraph
   - list
   - table
   - code fence
   - blockquote
   - figure placeholder/description
2. Parse the typed blocks into a heading tree.
3. Skip TOC sections for retrieval chunks.
4. Keep short sections whole.
5. Split long sections at paragraph/list boundaries.
6. Never split inside fenced code blocks.
7. Never split inside Markdown tables.
8. Keep table title, table headers, and surrounding section path.
9. For table-heavy documents:
   - emit row-level chunks when rows are semantically independent;
   - preserve table-level chunk when row context depends on headers/neighbor rows.
10. For code-heavy sections:
    - keep explanatory paragraph plus code together when possible.
11. For figures:
    - emit figure chunk if figure placeholder/description carries useful content.
12. Attach section breadcrumbs to embedding text, but keep non-semantic metadata out of embedding text.
13. Write both `chunks.jsonl` and a chunk diagnostics summary with chunk counts by kind, average chunk size, oversized chunks, and skipped TOC count.

### Embedding Text Format

This is the text stored as the Chroma document and embedded:

```text
Technical Report: DevOps Agent > 4. Technology Stack Overview > 4.2 Component Breakdown

## 4.2 Component Breakdown

| Component | Purpose | Why We Chose It |
| :--- | :--- | :--- |
| Python 3.11+ | Core Language | Type hints, asyncio, and a massive ecosystem. |
| Typer | CLI Framework | Clean, type-safe command-line interfaces with minimal boilerplate. |
```

For table rows:

```text
IPR Leave rules at glance > 11. Casual Leave (CL)

### 11. Casual Leave (CL)

a) Maximum of 08 days of casual leave is granted during a calendar year.
f) Combination of CL with EL is not permitted.
```

The final rendered envelope is handled in Phase 5.

### Platinum Chunk Text Format

Deprecated for embedding text. Use this only as the final model-visible envelope after retrieval.

General section envelope:

```text
[Source: TECHNICAL_REPORT_V8.pdf]
[DocType: general]
[Parser: docling_llm_normalized]
[ChunkKind: section]
[SectionPath: Technical Report: DevOps Agent > 4. Technology Stack Overview > 4.2 Component Breakdown]
[HeadingLevel: 3]
[ChunkIndex: 18]
[Neighbors: prev=17 next=19]
[Normalized: true]

## 4.2 Component Breakdown

...
```

Table row chunk:

```text
[Source: LeaveAtaGlance.pdf]
[DocType: general]
[Parser: docling_llm_normalized]
[ChunkKind: table_row]
[SectionPath: IPR Leave rules at glance > 11. Casual Leave (CL)]
[TableTitle: IPR Leave rules at glance]
[RowTitle: 11. Casual Leave (CL)]
[ChunkIndex: 6]
[Normalized: true]

### 11. Casual Leave (CL)

a) Maximum of 08 days of casual leave is granted during a calendar year.
f) Combination of CL with EL is not permitted.
```

### Tests

Add tests:

- Heading tree preserves section path.
- TOC is not emitted as a retrieval chunk.
- Fenced code block is not split.
- Markdown table is not split.
- Table-heavy leave document emits useful table chunks.
- Technical report emits section chunks, not sparse sentence fragments.
- Chroma document text does not contain noisy platinum metadata labels.
- Chunk metadata contains fields needed to render the platinum envelope.
- Final retrieved docs contain platinum envelope metadata.

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_ingestion_structure.py tests\test_vision_ingestion.py -q
```

Manual chunk inspection:

```powershell
.\.venv\Scripts\python.exe embedding_debug.py reindex "upload_docs\General\TECHNICAL_REPORT_V8.pdf" --parser docling --llm-normalize --dry-run
.\.venv\Scripts\python.exe embedding_debug.py reindex "upload_docs\General\LeaveAtaGlance.pdf" --parser docling --llm-normalize --dry-run
```

Acceptance criteria:

- No mid-sentence chunk boundaries except unavoidable long-section splits.
- Chunks are dense enough to answer specific questions.
- Tables preserve row labels and parent table context.
- Embedding text is semantic and does not over-index metadata labels.
- `chunks.jsonl` is human-inspectable and retrieval-ready.

## Phase 4 - Keep QnA Chunking Separate And Strict

### Objective

QnA documents should not use general hierarchical chunking. They should preserve each Q/A pair atomically.

### QnA Envelope

```text
[Q&A: FAQ_LTDP_28Dec11.pdf]
[DocType: qna]
[Parser: docling_llm_normalized]
[ChunkKind: qna]
[SectionPath: LTDP FAQ > Eligibility]
[QAPairID: faq_ltdp_28dec11_q12]
[ChunkIndex: 31]
[Normalized: true]

Q: Who is eligible for LTDP?

A: Group A officers are eligible...
```

### Rules

- One Q/A pair per chunk when possible.
- Long answers may fragment, but every fragment must carry question context.
- Fragment metadata must include:
  ```text
  qa_pair_id
  fragment_index
  total_fragments
  is_atomic
  ```

### Tests

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_qna_robustness.py tests\test_ingestion_structure.py -q
```

Acceptance criteria:

- Q/A pair count is preserved.
- Specific FAQ retrieval returns the correct pair.
- No QnA content is converted into generic prose chunks.

## Phase 5 - Final Evidence Envelope Passed To Agent

### Objective

Make the final retrieved documents visible to the generator consistently structured and grounded.

### Current State

The generator currently receives:

```text
<docs>
[Source: file.pdf | Section: title | Path: path]
content
</docs>

Q: user query
```

### Target State

The retriever should preserve rich metadata in each final envelope:

```text
<docs>
[Source: file.pdf]
[DocType: general]
[Parser: docling_llm_normalized]
[ChunkKind: section]
[SectionPath: Parent > Child]
[HeadingLevel: 3]
[ChunkIndex: 18]
[Neighbors: prev=17 next=19]
[Normalized: true]

## Section Heading

Evidence text.
</docs>

Q: user query
```

This rendering should happen after vector search/reranking, using Chroma metadata plus the stored semantic document text. The Chroma document text itself should remain optimized for embedding and should not include every bracketed metadata line.

### Rendering Rules

1. `_format_retrieved_docs()` is responsible for platinum envelope rendering.
2. The renderer must be deterministic so prompt cache behavior is predictable.
3. Render only fields useful to the answering model:
   - source
   - doc type
   - chunk kind
   - section path
   - heading level
   - chunk index
   - neighbor indices
   - normalized flag
4. Keep operational fields out of the final prompt unless needed:
   - raw file path
   - internal doc ID
   - parser diagnostics
   - embedding/reranker scores
5. For QnA, render `QAPairID` only if useful for debugging or citations.
6. For table rows, include `TableTitle` and `RowTitle`.
7. For code chunks, include `CodeLanguage` when detected.
8. For figure chunks, include `FigureLabel` and surrounding section path.

### Prompt/Prefix Cache Rule

Do not move dynamic metadata into the system prompt.

Stable:

```text
SYSTEM: fixed generator behavior
```

Dynamic:

```text
USER: retrieved docs + query
```

### Tests

Add tests:

- `_format_retrieved_docs` includes platinum metadata.
- Chroma document text remains clean semantic content, not full envelope text.
- Final docs are inside `<docs>`.
- System prompt remains byte-stable across RAG queries.
- Cache signature changes only when the dynamic user payload changes.

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_prompt_cache_and_routing.py tests\test_retriever_stitching.py -q
```

Acceptance criteria:

- Agent sees source, section path, chunk kind, parser, normalization flag, and content.
- Prompt caching is not broken by dynamic system prompts.

## Phase 6 - Adaptive Planner Context Action

### Objective

Upgrade fused planner behavior so follow-up questions can decide whether to reuse context, retrieve fresh chunks, or do both.

### Current State

Current workflow in `.env`:

```env
RAG_WORKFLOW=fused
```

Active flow:

```text
planner -> retriever -> generator
```

The modular `rewriter` node exists but is inactive in fused mode.

### Target Planner Output

Extend planner output:

```json
{
  "intent": "rag",
  "rewritten_query": "standalone query",
  "semantic_queries": [
    {"query": "specific search query", "target": null}
  ],
  "context_action": "answer_from_existing"
}
```

Allowed `context_action`:

```text
answer_from_existing
retrieve
hybrid
```

### Decision Rules

Use `answer_from_existing` for:

```text
explain more
give more details
elaborate
what does that mean
explain this
```

Use `retrieve` for:

```text
what about eligibility
give exact rule for EOL
what does the FAQ say
```

Use `hybrid` for:

```text
compare this with FAQ
expand the previous answer with exceptions
give full details including edge cases
```

### Tests

Add planner tests:

- `tell me more` after a RAG answer returns `answer_from_existing`.
- `what about eligibility criteria` returns `retrieve`.
- `compare this with FAQ` returns `hybrid` and targeted docs.
- Casual chat still returns `chat`.

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_prompt_cache_and_routing.py -q
```

Acceptance criteria:

- Follow-up behavior is explicit and testable.
- Existing context is not thrown away unnecessarily.

## Phase 7 - Context Reuse And Hybrid Retrieval

### Objective

Retriever should support three modes:

```text
answer_from_existing: skip retrieval, use previous docs
retrieve: fresh retrieval only
hybrid: previous docs + fresh retrieval, deduped
```

### Steps

1. Add `context_action` to `AgentState`.
2. If `answer_from_existing`:
   - skip retriever;
   - route directly to generator with previous documents.
3. If `retrieve`:
   - clear stale docs;
   - retrieve fresh evidence.
4. If `hybrid`:
   - preserve previous docs;
   - retrieve fresh evidence;
   - dedupe by `(doc_id, chunk_index)`.

### Retrieval Expansion Rules

Use chunk metadata to surgically expand:

- If hit is too short, fetch parent/neighbor.
- If query asks for overview, include `doc_summary`.
- If query asks for details, include siblings under same parent section.
- If query asks for table row, avoid merging unrelated rows.
- If query asks for comparison, retrieve from each target independently.

### Tests

Add retriever tests:

- `answer_from_existing` does not call vector search.
- `hybrid` keeps previous docs and adds fresh docs.
- Duplicate chunks are removed.
- Neighbor expansion is bounded.

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_retriever_stitching.py tests\test_prompt_cache_and_routing.py -q
```

Acceptance criteria:

- Follow-up detail questions are faster when existing context is sufficient.
- New specific details trigger retrieval only when needed.
- No duplicate evidence envelopes are passed to generator.

## Phase 8 - Adaptive Final Chunk Count

### Objective

Move from a fixed final `top_k=5` to adaptive model-visible evidence count while protecting TTFT.

### Current Limits

With current `.env`:

```env
RAG_RETRIEVAL_TOP_K=5
```

The final model-visible cap is:

```text
max 5 final evidence envelopes
```

Candidate behavior:

```text
non-targeted per-query candidates: up to 15
targeted per-query candidates: up to 10
pool limit: 36-56
reranker input: up to RAG_RERANK_CAP, default 12 if enabled
final docs: top_k, default 5
```

### Target Behavior

Adaptive final docs:

```text
simple factual query: 3-5 chunks
detailed/explain query: 6-8 chunks
deep multi-section query: 8-10 chunks
```

Hard caps:

```env
RAG_RETRIEVAL_TOP_K=5
RAG_RETRIEVAL_DETAIL_TOP_K=8
RAG_RETRIEVAL_DEEP_TOP_K=10
```

The generator token budget remains the final guardrail.

### Tests

Add tests:

- Simple query uses default cap.
- Detail query uses detail cap.
- Deep query uses deep cap.
- Generator still truncates within context budget.
- Table-heavy answers still compact table docs.

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_prompt_cache_and_routing.py tests\test_retriever_stitching.py -q
```

Acceptance criteria:

- Detail queries receive more evidence when needed.
- TTFT remains controlled.
- No unbounded context growth.

## Phase 9 - Chunking A/B Evaluation Against Current Strategy

### Objective

Prove the new normalized hierarchical chunking strategy is better than the current chunking strategy before making it the permanent default.

### Compared Strategies

Evaluate at least:

```text
A. current GeneralChunker/VisionChunker behavior
B. new NormalizedMarkdownChunker
C. new NormalizedMarkdownChunker + adaptive section expansion
```

Use the same parsed normalized Markdown for B and C so the comparison isolates chunking/retrieval behavior rather than parser quality.

### Evaluation Documents

Minimum corpus:

```text
TECHNICAL_REPORT_V8.pdf       technical report, headings, code, tables
LeaveAtaGlance.pdf            table-heavy policy document
FAQ_LTDP_28Dec11.pdf          QnA document
ADG-1.pdf                     structured requirements/spec document
Design and Development.pdf    mixed narrative/technical document
```

### Metrics

Chunk quality:

```text
chunk_count
average_chars
p95_chars
mid_sentence_split_count
toc_chunk_count
table_split_count
code_fence_split_count
missing_section_path_count
orphan_chunk_count
```

Retrieval quality:

```text
top_1_relevance
top_3_recall
top_5_recall
source_precision
section_path_precision
answerable_from_retrieved_context
```

Generation quality:

```text
groundedness
completeness
unsupported_claim_count
missed_fact_count
response_depth_match
```

Performance:

```text
parse_time
normalization_time
chunk_time
embedding_time
retrieval_time
TTFT
final_context_tokens
```

### Test Query Set

Technical report:

```text
What technology stack is used?
Explain the split-brain system.
What are the Docker, local K8s, and remote K8s server responsibilities?
What commands are supported for session management?
Give the detailed lifecycle of a remote Kubernetes command.
```

Leave table:

```text
Can CL be combined with EL?
How many casual leave days are allowed?
Does EOL count for pension?
Which leave rules mention increment or pension?
```

QnA:

```text
Who is eligible for LTDP?
What is the duration or scope of LTDP?
Give the exact FAQ answer for eligibility.
```

### Tests

Add or extend tests:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_ingestion_structure.py tests\test_retriever_stitching.py tests\test_e2e.py -q
```

Add an evaluation script if needed:

```powershell
.\.venv\Scripts\python.exe tests\eval_chunking_strategy.py --parser docling --llm-normalize
```

### Acceptance Criteria

The new strategy becomes default only if:

- It reduces TOC/noise chunks to zero for normalized docs.
- It avoids splitting code fences and Markdown tables.
- It improves or matches top-5 recall on all manual eval queries.
- It improves source/section precision for specific questions.
- It does not increase average TTFT beyond target.
- It gives the generator enough evidence for detailed follow-ups.

## Phase 10 - Generator Response Depth Tuning

### Objective

Fix overly terse answers without allowing rambling.

### Current Problem

The generator currently says:

```text
Answer in < 4 sentences if possible.
```

This is too restrictive for RAG.

### Target System Prompt Rule

Replace with stable instruction:

```text
STYLE:
Be concise but complete.
For simple chat, answer briefly.
For RAG answers, include all directly relevant facts from the provided evidence.
If the user asks for more detail, expand with structured bullets and cite the relevant document sections.
Avoid filler, but do not omit useful evidence just to be short.
```

### Prompt Cache Constraint

This rule must be part of the stable system prompt, not a dynamic per-query inserted prompt.

### Tests

Add tests:

- System prompt does not contain fixed `< 4 sentences` cap.
- RAG prompt keeps docs in user message.
- Chat remains concise.
- Detail follow-up produces a longer answer path.

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_prompt_cache_and_routing.py -q
```

Acceptance criteria:

- Responses are concise but no longer under-explained.
- "Tell me more" expands based on previous evidence.
- "Give exact rule" retrieves and answers with specific evidence.

## Phase 11 - End-To-End Rebuild And Evaluation

### Objective

Validate ingestion, chunking, retrieval, generation, TTFT, and grounding together.

### Full Rebuild

After backend restart if needed:

```powershell
.\.venv\Scripts\python.exe embedding_debug.py rebuild --parser docling --llm-normalize
```

### Core Tests

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_llm_normalizer.py tests\test_ingestion_structure.py tests\test_parser_backends.py tests\test_vision_ingestion.py tests\test_qna_robustness.py tests\test_prompt_cache_and_routing.py tests\test_retriever_stitching.py -q
```

Then:

```powershell
.\.venv\Scripts\python.exe tests\test_e2e.py
.\.venv\Scripts\python.exe test_ttft.py
```

### Manual Evaluation Queries

Technical report:

```text
What is the technology stack used in TECHNICAL_REPORT_V8?
Give more details.
Explain the split-brain system.
Now compare that with the MCP architecture.
```

Leave rules:

```text
Can CL be combined with EL?
Does EOL count for pension?
Give exact leave rules for EOL.
Tell me more details.
```

QnA:

```text
Who is eligible for LTDP according to FAQ?
Give more details from the FAQ.
```

### LLM-as-Judge Checklist

For each answer:

- Is every claim grounded in retrieved docs?
- Did the answer include enough details for the query depth?
- Did it avoid unsupported inference?
- Did it cite the right source/section?
- Were retrieved chunks dense and relevant?
- Did follow-up avoid unnecessary retrieval when existing evidence was enough?
- Did targeted retrieval fetch the requested document?

### TTFT Criteria

Target:

```text
average TTFT <= 5 seconds
worst normal RAG <= 10-12 seconds
deep multi-section RAG can be slower but must be justified
```

Record:

```text
chat TTFT
general RAG TTFT
targeted @file RAG TTFT
follow-up from existing context TTFT
hybrid retrieval TTFT
```

Acceptance criteria:

- No major hallucinations in manual eval.
- Retrieved chunks are relevant and dense.
- Follow-up behavior is correct.
- Prompt cache signature remains stable for unchanged static prefix.
- TTFT remains inside target envelope.

## Implementation Order

Recommended order:

```text
1. Server default ingestion: docling + llm_normalize
2. Normalized Markdown contract tests
3. Hierarchical structure-aware chunker
4. QnA strict chunking compatibility
5. Platinum evidence envelope
6. Planner context_action
7. Context reuse / hybrid retrieval
8. Adaptive final chunk count
9. Chunking A/B evaluation
10. Generator response-depth tuning
11. Full rebuild + E2E + TTFT + grounding evaluation
```

## Production Readiness Gate

Do not call the app production-ready until all are true:

- Full vector DB rebuild succeeds from scratch.
- New server-side uploads ingest with Docling + LLM normalization by default.
- General docs produce hierarchical retrieval-ready chunks.
- QnA docs preserve Q/A pairs.
- New chunking strategy beats or matches current strategy in A/B evaluation.
- Chroma document text is semantic and does not embed noisy final-envelope metadata.
- Retrieval pulls correct chunks for untagged and tagged queries.
- Follow-up queries correctly reuse/retrieve/hybridize.
- Generator answers are concise but complete.
- Prompt/prefix caching is not broken by dynamic system prompts.
- `test_ttft.py` meets TTFT targets.
- `tests/test_e2e.py` passes.
- Manual LLM-as-judge evaluation passes on `TECHNICAL_REPORT_V8`, `LeaveAtaGlance`, and `FAQ_LTDP_28Dec11`.
