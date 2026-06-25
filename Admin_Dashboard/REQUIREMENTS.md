# RAG Admin Dashboard — AGENTS.md
## Complete Feature Specification for AI Coding Agent
### System: RAG_Chat_IPRv1.5 | Institute for Plasma Research

> **This is the authoritative specification.** When in doubt, check here first.
> Do not infer requirements not stated here. Do not skip error handling.
> Implement every feature exactly as specified including all edge cases.

---

## §0 Purpose & Scope

This document specifies the RAG Admin Dashboard — a Next.js 15 web application for
administrators to manage the full document ingestion pipeline for RAG_Chat_IPRv1.5 at IPR.

### What this system does
Admins upload PDFs/DOCX files → configure parsing and LLM normalization → review and
approve output → trigger chunking and indexing into Qdrant for RAG retrieval.

### What the AI coding agent must do
1. Implement all 15 features exactly as specified with examples
2. Maintain all state machine invariants at all times
3. Never let one pipeline step's failure corrupt another step's data
4. Implement every error recovery path explicitly — no silent failures
5. Use the tech stack below exclusively — no substitutions

---

## §1 Tech Stack

### 1.1 Frontend (Strict — No Substitutions)

```
Framework:       Next.js 15 (App Router — no Pages Router)
Language:        TypeScript 5+ (strict: true — no `any` anywhere)
Styling:         Tailwind CSS v4
Client State:    Zustand (notification store + active batch cache)
Server State:    TanStack Query v5 (React Query)
Real-Time:       SSE via native EventSource (not WebSocket)
MD Editor:       CodeMirror 6 with @codemirror/lang-markdown
File Downloads:  Native browser anchor download API
Form Handling:   React Hook Form v7 + Zod v3 validation
Icons:           Lucide React
UI Base:         shadcn/ui (extend, do not replace)
```

### 1.2 Backend (Reference — Implement as Needed)

```
Framework:       FastAPI (Python 3.11+)
Job Queue:       Celery + Redis
Metadata DB:     PostgreSQL (SQLAlchemy ORM)
File Storage:    Local filesystem (BASE_FILE_PATH env var)
Vector Store:    Qdrant
LLM Inference:   vLLM / LiteLLM (endpoint per model, configured at runtime)
Parsers:         pymupdf4llm, docling
Real-Time:       Redis pub/sub → FastAPI SSE endpoint
```

### 1.3 Integration Points

| External System | Role in Pipeline | How Connected |
|----------------|-----------------|---------------|
| pymupdf4llm | Parser option A | Python lib, server-side |
| docling | Parser option B | Python lib, server-side |
| vLLM endpoint | LLM normalization inference | HTTP (configurable per model) |
| LiteLLM | LLM routing layer | HTTP, sits in front of vLLM |
| Qdrant | Vector index for chunks | Backend SDK |
| PostgreSQL | All metadata + job state | SQLAlchemy |
| Redis | Job queue + SSE pub/sub | Celery + aioredis |

---

## §2 Core Data Models (TypeScript — Authoritative)

> These types are used in both frontend and as the shape of all API responses.
> Backend must match these shapes exactly.

### 2.1 Enumerations

```typescript
// All parsers supported
type ParserType = 'pymupdf4llm' | 'docling';

// Full lifecycle status of a single document
type DocumentStatus =
  | 'UPLOADED'           // File stored, no parse job yet
  | 'PARSE_PENDING'      // Job queued, worker not started
  | 'PARSE_RUNNING'      // Worker actively parsing
  | 'PARSE_FAILED'       // Parser threw error
  | 'PARSE_COMPLETE'     // All requested parsers finished (with or without errors on some variants)
  | 'NORMALIZE_PENDING'  // Queued for LLM normalization
  | 'NORMALIZE_RUNNING'  // LLM normalization in progress
  | 'NORMALIZE_FAILED'   // Normalization error (partial or complete)
  | 'NORMALIZE_COMPLETE' // All requested normalizations finished
  | 'REVIEW_PENDING'     // Awaiting admin review
  | 'REVIEW_IN_PROGRESS' // Admin has opened review page
  | 'REVIEW_APPROVED'    // Admin approved — chunking can start
  | 'CHUNK_PENDING'      // Chunking job queued
  | 'CHUNK_RUNNING'      // Chunking in progress
  | 'CHUNK_FAILED'       // Chunking error
  | 'INDEXED';           // Successfully indexed in Qdrant

// Lifecycle status of a batch
type BatchStatus =
  | 'DRAFT'              // Created, not submitted
  | 'SUBMITTED'          // Jobs queued, not started
  | 'PARSING'            // At least one document parsing
  | 'NORMALIZING'        // At least one document normalizing
  | 'REVIEW_PENDING'     // All pipeline steps done, awaiting review
  | 'REVIEWING'          // At least one document in review
  | 'CHUNKING'           // At least one document chunking
  | 'PARTIALLY_COMPLETE' // Some indexed, some failed
  | 'COMPLETE'           // All documents indexed
  | 'FAILED';            // Unrecoverable — all documents failed

// Status of a single ParseVariant or NormVariant job
type VariantStatus = 'PENDING' | 'RUNNING' | 'COMPLETE' | 'FAILED';

// How normalization failed — determines cleanup behavior
type NormFailureMode = 'COMPLETE_FAILURE' | 'PARTIAL_FAILURE';

// Pipeline stages (used in logs and notifications)
type PipelineStage = 'UPLOAD' | 'PARSE' | 'NORMALIZE' | 'REVIEW' | 'CHUNK' | 'INDEX' | 'CLEANUP' | 'SYSTEM';

// Notification severity
type NotificationType = 'STAGE_UPDATE' | 'ERROR' | 'SUCCESS' | 'WARNING';

// Log levels
type LogLevel = 'DEBUG' | 'INFO' | 'WARN' | 'ERROR';
```

### 2.2 Configuration Types

```typescript
// Config for a single LLM normalization model
interface NormModelConfig {
  model_id: string;        // e.g. "qwen3-70b"
  endpoint: string;        // e.g. "http://10.100.0.5:8000/v1" — network-accessible
  display_name: string;    // e.g. "Qwen3 70B (DGX Node 1)"
}

// Per-document configuration (overrides batch defaults when set)
interface PerDocConfig {
  parsers: ParserType[];                   // Which parsers to run (1 or 2)
  normalization_enabled: boolean;
  normalization_models: NormModelConfig[]; // Which LLMs to normalize with
  // Produces parsers.length × normalization_models.length variants total
}

// Batch-level defaults + per-document overrides
interface BatchConfig {
  default_parsers: ParserType[];
  default_normalization_enabled: boolean;
  default_normalization_models: NormModelConfig[];
  // Per-document overrides — key is document_id
  // If a document has no entry here, it uses batch defaults
  per_document_overrides: Record<string, Partial<PerDocConfig>>;
}

// Effective config for a document (batch defaults merged with per-doc override)
// Computed server-side, stored on document record
interface EffectiveDocConfig extends PerDocConfig {}
```

### 2.3 ParseVariant

```typescript
// One (document × parser) combination
interface ParseVariant {
  variant_id: string;
  document_id: string;
  parser_type: ParserType;
  status: VariantStatus;

  // File paths — null until that step completes
  raw_md_path: string | null;     // Direct parser output
  parsed_md_path: string | null;  // Post-processed/cleaned output

  // Timing
  started_at: string | null;      // ISO 8601
  completed_at: string | null;
  duration_ms: number | null;

  // Error info
  error_message: string | null;   // Short user-facing message
  error_detail: string | null;    // Full stack trace / log

  // Children — one per normalization model configured
  norm_variants: NormVariant[];

  // Set during review stage — only one ParseVariant per document can be true
  is_selected_for_review: boolean;
}
```

### 2.4 NormVariant

```typescript
// One (ParseVariant × NormModel) combination
interface NormVariant {
  norm_variant_id: string;
  parse_variant_id: string;
  document_id: string;

  // Which model was used
  model_config: NormModelConfig;

  status: VariantStatus;
  failure_mode: NormFailureMode | null;

  // File path — null until complete
  normalized_md_path: string | null;

  // UI display metadata (Requirement 4)
  time_taken_ms: number | null;    // Wall clock time for normalization

  // Timing
  started_at: string | null;
  completed_at: string | null;

  // Error
  error_message: string | null;
  error_detail: string | null;

  // Set during review stage
  is_selected_for_review: boolean;
}
```

### 2.5 ReviewRecord

```typescript
// Review state for a document
interface ReviewRecord {
  review_id: string;
  document_id: string;

  // Which variants the admin selected as review input
  selected_parse_variant_id: string;
  selected_norm_variant_id: string | null; // null = no normalization

  // The starting file for review
  // = norm_variant.normalized_md_path  if norm selected
  // = parse_variant.parsed_md_path     if no norm selected
  base_md_path: string;

  // Optional override files (set during review stage)
  edited_md_path: string | null;    // In-browser edits saved to server
  uploaded_md_path: string | null;  // Admin-uploaded replacement file

  // Final approved file (used for chunking)
  // Priority: edited_md > uploaded_md > base_md
  // This file is what gets chunked and indexed.
  review_approved_md_path: string | null;

  status: 'PENDING' | 'IN_PROGRESS' | 'APPROVED';
  opened_at: string | null;
  approved_at: string | null;
  notes: string | null;
}
```

### 2.6 CanonicalFiles

```typescript
// The 5 surviving files after review approval (Requirement 4)
// Populated server-side after REVIEW_APPROVED + cleanup completes
interface CanonicalFiles {
  source_file_path: string;          // Always present — original PDF/DOCX
  raw_md_path: string;               // Selected parse variant's raw output
  parsed_md_path: string;            // Selected parse variant's cleaned output
  normalized_md_path: string | null; // null if normalization was not used
  review_approved_md_path: string;   // Final approved file used for indexing

  // Populated only if normalization was used (shown in UI — Requirement 4)
  normalization_metadata: {
    model_display_name: string;
    model_endpoint: string;        // Network-accessible IP/URL
    time_taken_ms: number;
    completed_at: string;
  } | null;
}
```

### 2.7 Document

```typescript
interface Document {
  document_id: string;
  batch_id: string;
  original_filename: string;
  source_file_path: string;
  file_type: 'pdf' | 'docx';
  file_size_bytes: number;

  // Resolved config (batch defaults merged with per-doc override)
  effective_config: EffectiveDocConfig;

  status: DocumentStatus;

  // Parse tree
  parse_variants: ParseVariant[];

  // Set after review approval
  review: ReviewRecord | null;

  // Set after cleanup completes post-approval
  canonical_files: CanonicalFiles | null;

  // Set after indexing
  chunk_count: number | null;
  indexed_at: string | null;

  uploaded_at: string;
  error_summary: string | null; // Latest error, if any
}
```

### 2.8 Batch

```typescript
interface Batch {
  batch_id: string;
  name: string;
  description: string | null;
  status: BatchStatus;
  config: BatchConfig;
  documents: Document[];

  // Aggregate counts
  total_documents: number;
  documents_indexed: number;
  documents_failed: number;
  documents_in_progress: number;
  documents_pending_review: number;

  // Full timeline (Requirement 13)
  created_at: string;
  submitted_at: string | null;
  parsing_started_at: string | null;
  parsing_completed_at: string | null;
  normalization_started_at: string | null;
  normalization_completed_at: string | null;
  review_started_at: string | null;
  review_completed_at: string | null;
  chunking_started_at: string | null;
  completed_at: string | null;

  // Wall-clock time from submitted_at to completed_at
  total_duration_ms: number | null;
}
```

### 2.9 JobLog

```typescript
interface JobLog {
  log_id: string;
  batch_id: string;
  document_id: string | null;        // null for batch-level events
  parse_variant_id: string | null;
  norm_variant_id: string | null;
  stage: PipelineStage;
  level: LogLevel;
  message: string;                   // Short human-readable message
  detail: string | null;             // Full stack trace or verbose output
  timestamp: string;
}
```

### 2.10 Notification

```typescript
interface Notification {
  notification_id: string;
  type: NotificationType;
  batch_id: string | null;
  document_id: string | null;
  title: string;     // e.g. "Batch #8 — Parse Complete"
  message: string;   // e.g. "3/3 documents parsed successfully"
  detail: string | null; // e.g. full error message
  read: boolean;
  created_at: string;
}
```

### 2.11 ChunkRecord

```typescript
interface ChunkRecord {
  chunk_id: string;          // Qdrant point ID
  document_id: string;
  batch_id: string;
  content: string;           // Chunk text content
  chunk_index: number;       // Position in document
  section_path: string | null; // e.g. "Chapter 2 > Section 3.1 > Safety"
  page_numbers: number[];    // Source pages this chunk covers
  token_count: number;
  char_count: number;
  embedding_model: string;
  indexed_at: string;
}
```

### 2.12 SSE Event Types

```typescript
// Events pushed from server to frontend via SSE

interface BatchProgressEvent {
  type: 'batch_progress';
  batch_id: string;
  status: BatchStatus;
  counts: {
    total: number;
    indexed: number;
    failed: number;
    in_progress: number;
    pending_review: number;
  };
}

interface DocumentUpdateEvent {
  type: 'document_update';
  document_id: string;
  batch_id: string;
  status: DocumentStatus;
  parse_variant_id?: string;
  norm_variant_id?: string;
}

interface JobErrorEvent {
  type: 'job_error';
  document_id: string;
  batch_id: string;
  stage: PipelineStage;
  message: string;
  detail: string;
}

type SSEEvent = BatchProgressEvent | DocumentUpdateEvent | JobErrorEvent | { type: 'notification'; data: Notification };
```

---

## §3 Processing State Machine

### 3.1 Document Status Transitions (Complete)

```
UPLOADED
  │
  ├──[Batch submitted]──────────────────────────► PARSE_PENDING
  │                                                     │
  │                                              PARSE_RUNNING
  │                                               ┌────┴────┐
  │                                         PARSE_FAILED  PARSE_COMPLETE
  │                                              │              │
  │                                         [Retry]      [norm disabled?]─────────────► REVIEW_PENDING
  │                                              │              │
  │                                          PARSE_PENDING  [norm enabled]
  │                                                           NORMALIZE_PENDING
  │                                                                │
  │                                                         NORMALIZE_RUNNING
  │                                                          ┌────┴────┐
  │                                                 NORMALIZE_FAILED  NORMALIZE_COMPLETE
  │                                                        │                 │
  │                                                 [Clean rollback]   REVIEW_PENDING
  │                                                 → PARSE_COMPLETE         │
  │                                                                    REVIEW_IN_PROGRESS
  │                                                                          │
  │                                                                   REVIEW_APPROVED
  │                                                                          │
  │                                                                    CHUNK_PENDING
  │                                                                          │
  │                                                                    CHUNK_RUNNING
  │                                                                    ┌────┴────┐
  │                                                               CHUNK_FAILED  INDEXED
  │                                                                    │
  │                                                               [Retry] → CHUNK_PENDING
  │
  └──[No submit yet]────────────────────────────► stays UPLOADED (deferred — Requirement 1)
```

### 3.2 State Machine Invariants

These are hard constraints. The backend must enforce them. The frontend must never
allow actions that violate them.

```
INVARIANT 1 (Deferred Submission):
  A document MAY remain in UPLOADED status indefinitely.
  Batch submission is NOT required at upload time.
  Admin can upload today and submit next week.

INVARIANT 2 (Parse Retry Isolation):
  Retrying a failed ParseVariant NEVER deletes or modifies other ParseVariants
  of the same document. Retry only re-queues the specific failed variant.

INVARIANT 3 (Norm Failure Rollback):
  When any NormVariant transitions to FAILED:
    a) The normalized_md file (if partially written) is deleted
    b) norm_variant.normalized_md_path is set to null
    c) Document status returns to PARSE_COMPLETE
    d) ParseVariant data and files are COMPLETELY UNTOUCHED
  This invariant must hold for both COMPLETE_FAILURE and PARTIAL_FAILURE modes.

INVARIANT 4 (No Cross-Variant Contamination):
  One document's pipeline failure NEVER affects any other document.
  One ParseVariant failure NEVER affects sibling ParseVariants.
  One NormVariant failure NEVER affects sibling NormVariants.

INVARIANT 5 (Review Exclusivity):
  Exactly one (ParseVariant, NormVariant|null) pair is selected per document
  before approval. No document may be approved without a selection.

INVARIANT 6 (File Cleanup After Approval):
  After REVIEW_APPROVED and variant selection is confirmed:
    KEEP: source file + selected parse variant files + selected norm variant file + approved.md
    DELETE: all other parse variant directories + all other norm variant directories
  Cleanup is async but must complete within 60 seconds.
  Every deletion is logged at INFO level.

INVARIANT 7 (Chunking Input):
  Chunking ONLY reads review_approved_md_path. It never reads any parse variant or
  norm variant file directly.

INVARIANT 8 (Chunk Retry Idempotency):
  Retrying chunking first deletes all existing Qdrant points for that document_id,
  then re-runs chunking from review_approved_md (which is untouched).

INVARIANT 9 (Late Norm Trigger):
  Normalization CAN be triggered from the review stage even if no normalization
  was configured in the batch. Document transitions:
    REVIEW_PENDING → NORMALIZE_PENDING → ... → NORMALIZE_COMPLETE → REVIEW_PENDING
  After normalization completes, review stage resumes normally.
```

### 3.3 Batch Status Derivation

```
Batch status is DERIVED from document statuses — not stored independently.
Backend recomputes after every document status change.

DRAFT             : batch.submitted_at is null
SUBMITTED         : submitted_at set, no document has started yet
PARSING           : any document is in PARSE_PENDING or PARSE_RUNNING
NORMALIZING       : all parse done, any document in NORMALIZE_*
REVIEW_PENDING    : all pipeline steps done, any document in REVIEW_PENDING
REVIEWING         : any document in REVIEW_IN_PROGRESS
CHUNKING          : any document in CHUNK_PENDING or CHUNK_RUNNING
COMPLETE          : all documents INDEXED
PARTIALLY_COMPLETE: some INDEXED, some FAILED (no more in-progress)
FAILED            : all documents failed
```

---

## §4 File Lifecycle

### 4.1 The 5 Canonical Files (Requirement 4)

Each document produces exactly these 5 files, accessible from the UI at all times
after each respective step completes.

| # | Name | Description | Available After | Always Present? |
|---|------|-------------|-----------------|-----------------|
| 1 | source_file | Original uploaded PDF/DOCX | Upload | Yes |
| 2 | raw_md | Direct unprocessed parser output | Parse complete | Only selected variant |
| 3 | parsed_md | Post-processed/cleaned parse output | Parse complete | Only selected variant |
| 4 | normalized_md | LLM-normalized version | Norm complete | No — only if normalization run and selected |
| 5 | review_approved_md | Admin-approved final file for indexing | Review approved | Yes (after approval) |

When `normalized_md` is present, the UI MUST also show (Requirement 4):
- Model used (e.g. "Qwen3 70B")
- Network-accessible endpoint (e.g. "http://10.100.0.5:8000/v1")
- Time taken to normalize (e.g. "4m 22s")

### 4.2 File Path Convention on Disk

```
{BASE_FILE_PATH}/
└── batches/
    └── {batch_id}/
        └── {document_id}/
            ├── source/
            │   └── {original_filename}                  ← File #1 (source_file)
            ├── variants/
            │   └── {parse_variant_id}/
            │       ├── raw.md                           ← File #2 (raw_md)
            │       ├── parsed.md                        ← File #3 (parsed_md)
            │       └── norm/
            │           └── {norm_variant_id}/
            │               └── normalized.md            ← File #4 (normalized_md)
            └── review/
                ├── base.md        (reference copy — not served to user directly)
                ├── edited.md      (saved editor content — may not exist)
                ├── uploaded.md    (admin-uploaded replacement — may not exist)
                └── approved.md    ← File #5 (review_approved_md)
```

### 4.3 File Priority Chain for approved.md

When admin clicks [Approve] in review stage:

```
IF editor content has been modified AND saved:
  → approved.md = current editor content
ELIF admin uploaded a replacement file:
  → approved.md = uploaded.md content
ELSE:
  → approved.md = base_md content (normalized or parsed)

approved.md is written at the moment of approval click.
approved.md is NEVER modified after that point.
```

### 4.4 File Cleanup Rules After Review Approval

```
TRIGGERED: When document transitions to REVIEW_APPROVED

ASYNC TASK: Run within 60 seconds, log all operations

Step 1: Identify selected variants from review record
  selected_pv = review.selected_parse_variant_id
  selected_nv = review.selected_norm_variant_id (may be null)

Step 2: For each ParseVariant where variant_id != selected_pv:
  DELETE entire directory: variants/{variant_id}/
  SET parse_variant.raw_md_path = null
  SET parse_variant.parsed_md_path = null
  LOG: "Deleted non-selected parse variant {variant_id} ({parser_type})"

Step 3: For selected ParseVariant, delete non-selected NormVariants:
  For each NormVariant where norm_variant_id != selected_nv:
    DELETE directory: variants/{selected_pv}/norm/{norm_variant_id}/
    SET norm_variant.normalized_md_path = null
    LOG: "Deleted non-selected norm variant {norm_variant_id} ({model_id})"

Step 4: Delete intermediate review files:
  DELETE review/base.md
  DELETE review/edited.md (if exists)
  DELETE review/uploaded.md (if exists)
  KEEP: review/approved.md

Step 5: Populate document.canonical_files from surviving paths
  LOG: "File cleanup complete for document {document_id}"
```

### 4.5 Normalization Failure Cleanup

```
TRIGGERED: When any NormVariant transitions to FAILED

Backend MUST execute ALL of these synchronously before returning:

1. If normalized.md was partially written:
   DELETE variants/{parse_variant_id}/norm/{norm_variant_id}/normalized.md
   
2. SET norm_variant.normalized_md_path = null
3. SET norm_variant.status = FAILED
4. SET norm_variant.failure_mode = (COMPLETE_FAILURE | PARTIAL_FAILURE)
5. SET norm_variant.error_message = <short description>
6. SET norm_variant.error_detail = <full traceback>
7. SET document.status = PARSE_COMPLETE  ← REVERT to working state
8. SET document.error_summary = "Normalization failed: {error_message}"
9. WRITE JobLog at ERROR level with full detail
10. EMIT SSE event type='job_error' with stage='NORMALIZE'
11. CREATE Notification (ERROR type)

VERIFY AFTER: parse_variant files MUST still exist and be accessible.
```

---

## §5 Feature Specifications

> Each feature includes: Goal, Trigger, UI wireframe, Example walkthrough,
> Isolation boundaries, Shared concerns, and Error handling.

---

### F01 — Document Upload & Batch Initiation (Requirement 1)

**Goal:** Admin uploads one or more documents to create a new batch. Upload does NOT
require pipeline configuration or immediate submission. Batch stays in DRAFT.

**Trigger:** Admin navigates to `/upload`

**UI Wireframe:**

```
┌──────────────────────────────────────────────────────────────────────────┐
│  Upload Documents                                                        │
│                                                                          │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │              Drag & drop PDF or DOCX files here                  │   │
│  │                    or click to browse                            │   │
│  │         Max 50 files per batch · 500 MB per file                │   │
│  └──────────────────────────────────────────────────────────────────┘   │
│                                                                          │
│  Queued Files (3)                                                        │
│  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  │
│  ✓  TOKAMAK_MANUAL_2024.pdf          12.4 MB     Uploaded               │
│  ✓  IPR_SAFETY_POLICY_v3.pdf          2.1 MB     Uploaded               │
│  ✗  CORRUPTED_FILE.pdf                2.0 MB     Failed  [Retry] [Remove]│
│                                                                          │
│  Batch Name *    [ IPR Ingestion — June 2025                         ]   │
│  Description     [ Optional description...                           ]   │
│                                                                          │
│  ─────────────────────────────────────────────────────────────────────  │
│  [Cancel]                           [Save Draft]   [Configure & Submit →]│
└──────────────────────────────────────────────────────────────────────────┘
```

**Actions:**

| Button | Behavior |
|--------|----------|
| `Save Draft` | POST /api/v1/batches (multipart) → creates Batch (DRAFT) + Documents (UPLOADED) → navigates to /batches/{batchId} |
| `Configure & Submit →` | Same as Save Draft, then opens /batches/{batchId}/config |
| Per-file `Retry` | Re-uploads that specific file only |
| Per-file `Remove` | Removes file from upload queue (does not affect already-uploaded files) |

**Example — Deferred Submission (Requirement 1):**

```
Monday:  Admin uploads 3 PDFs → clicks "Save Draft"
         → Batch #7 created (DRAFT), 3 Documents (UPLOADED)
         → Admin is busy, does nothing else

Thursday: Admin opens /batches/7
          → Sees 3 docs in UPLOADED state
          → Clicks "Configure & Submit"
          → F02 Advanced Config opens
          → Admin configures parsers + normalization
          → Submits batch → DRAFT → SUBMITTED → PARSING
```

**Isolation:**
- File drop zone state is component-local (useState)
- Upload progress per file is component-local
- On navigation away: state is discarded
- Batch creation is a single atomic API call

**Shared with:**
- F14 (Notification): fires "Batch #{id} created" notification
- F15 (History): new batch appears in list

**Error Handling:**
- Invalid file type (not PDF/DOCX): reject immediately with inline message, do not upload
- File > 500 MB: reject immediately with inline size message
- Per-file upload failure: show error on that row, other files unaffected
- Partial success (2 of 3 files upload): create batch with successful files, show summary
- All files fail: do not create batch, show error, allow retry
- Batch name empty: Zod validation error before submit

---

### F02 — Batch Advanced Configuration (Requirement 11)

**Goal:** Pre-configure the full pipeline for the batch at two levels:
(a) batch-level defaults for all documents, (b) per-document overrides.
Configuration can be saved without submitting.

**Trigger:** Admin clicks "Configure" on any DRAFT batch, OR uses "Configure & Submit →" in F01.

**Route:** `/batches/{batchId}/config`

**UI Wireframe:**

```
┌───────────────────────────────────────────────────────────────────────────────┐
│  Advanced Configuration — Batch #7 "IPR Ingestion June 2025"                 │
│  ─────────────────────────────────────────────────────────────────────────── │
│                                                                               │
│  BATCH-LEVEL DEFAULTS  (applied to all documents unless overridden below)    │
│                                                                               │
│  Parsers                                                                      │
│    ☑  pymupdf4llm        ☑  docling                                          │
│    (checking both runs both parsers on every document in parallel)            │
│                                                                               │
│  LLM Normalization                                                            │
│    ○ Disabled     ●  Enabled                                                 │
│                                                                               │
│    Models  (each selected model produces one NormVariant per ParseVariant)   │
│    ┌──────────────────────────────────────────────────────────────────────┐  │
│    │  ☑  Qwen3 70B      Endpoint: [ http://10.100.0.5:8000/v1          ] │  │
│    │  ☑  Qwen3 14B      Endpoint: [ http://10.100.0.5:8001/v1          ] │  │
│    │  [+ Add model]                                                       │  │
│    └──────────────────────────────────────────────────────────────────────┘  │
│                                                                               │
│  ─────────────────────────────────────────────────────────────────────────── │
│  PER-DOCUMENT OVERRIDES                                                       │
│                                                                               │
│  TOKAMAK_MANUAL_2024.pdf              [Use batch defaults  ▼]                │
│                                                                               │
│  IPR_SAFETY_POLICY_v3.pdf             [Custom config       ▼]                │
│    └── Parsers:           ☑ docling only   ☐ pymupdf4llm                    │
│        Normalization:     ○ Disabled  ● Enabled                              │
│        Models:            ☐ Qwen3 70B   ☑ Qwen3 14B only                   │
│                                                                               │
│  ─────────────────────────────────────────────────────────────────────────── │
│  [Cancel]                                   [Save Config]  [Save & Submit]   │
└───────────────────────────────────────────────────────────────────────────────┘
```

**Variant Count Preview (shown live as admin configures):**

```
Estimated variants:
  TOKAMAK_MANUAL:     2 parsers × 2 models = 4 variants
  IPR_SAFETY_POLICY:  1 parser  × 1 model  = 1 variant
  ─────────────────────────────────────────────────────
  Total jobs to run:  5 parse + 5 normalization = 10 jobs
```

**Example:**

```
Admin configures:
  Batch default: parsers=[pymupdf4llm, docling], norm=[qwen3-70b, qwen3-14b]
  Override for IPR_SAFETY: parsers=[docling only], norm=[qwen3-14b only]

When submitted:
  TOKAMAK_MANUAL → 4 variants:
    ParseVariant(pymupdf4llm) → NormVariant(qwen3-70b) + NormVariant(qwen3-14b)
    ParseVariant(docling)     → NormVariant(qwen3-70b) + NormVariant(qwen3-14b)

  IPR_SAFETY → 1 variant:
    ParseVariant(docling) → NormVariant(qwen3-14b)
```

**Actions:**

| Button | Behavior |
|--------|----------|
| `Save Config` | PATCH /api/v1/batches/{batchId}/config → saves config, batch stays DRAFT |
| `Save & Submit` | Save config + POST /api/v1/batches/{batchId}/submit → DRAFT → SUBMITTED |

**Isolation:**
- Form state is local (React Hook Form)
- "Add model" rows are local state until saved
- Unsaved changes trigger browser unload warning

**Shared with:**
- F03 (Parse): reads `effective_config.parsers` to spawn variants
- F05 (Norm): reads `effective_config.normalization_models` to spawn NormVariants
- F15 (History): config is displayed in batch detail history

---

### F03 — Parse Pipeline Job Execution (Requirement 11)

**Goal:** Execute parsing jobs for all documents in a batch. Each (document × parser)
pair runs as an isolated `ParseVariant` job. All jobs run in parallel.

**Trigger:** Batch transitions from DRAFT/SUBMITTED → workers pick up queued jobs

**Backend Job Logic:**

```python
# Pseudocode — backend must implement exactly this

for document in batch.documents:
    for parser in document.effective_config.parsers:
        variant = create_parse_variant(document_id, parser_type=parser)
        enqueue_parse_job(variant.variant_id)

# Worker handles one variant:
def run_parse_job(variant_id):
    variant.status = RUNNING
    variant.started_at = now()
    log(INFO, f"Started parsing {document.filename} with {variant.parser_type}")
    try:
        if variant.parser_type == 'pymupdf4llm':
            raw_output = pymupdf4llm.to_markdown(source_path)
        elif variant.parser_type == 'docling':
            raw_output = docling.convert(source_path).export_to_markdown()

        write_file(variant.raw_md_path, raw_output)
        log(INFO, f"raw.md written: {len(raw_output)} chars")

        cleaned = post_process_markdown(raw_output)  # TOC anchoring, cleanup
        write_file(variant.parsed_md_path, cleaned)
        log(INFO, f"parsed.md written: {len(cleaned)} chars")

        variant.status = COMPLETE
        variant.completed_at = now()
        variant.duration_ms = elapsed()
        log(INFO, f"Parse complete in {variant.duration_ms}ms")

    except Exception as e:
        variant.status = FAILED
        variant.error_message = str(e)[:200]
        variant.error_detail = traceback.format_exc()
        document.error_summary = f"Parse failed ({variant.parser_type}): {str(e)[:100]}"
        log(ERROR, f"Parse failed: {e}", detail=traceback)
        emit_sse(job_error_event(...))
        create_notification(ERROR, f"{document.filename} — Parse Failed", ...)

    emit_sse(document_update_event(...))
    check_and_advance_document_status(document_id)
```

**UI — Batch Detail Parsing Section:**

```
Batch #8 — IPR Ingestion June 2025                            [ PARSING ]
──────────────────────────────────────────────────────────────────────────
Documents (3)

  TOKAMAK_MANUAL_2024.pdf                           [PARSE_COMPLETE]
  ├── pymupdf4llm  ████████████████████ COMPLETE  1m 12s
  └── docling      ████████████████████ COMPLETE  2m 30s
      [View parsed.md preview]  [Proceed to Normalization]

  IPR_SAFETY_POLICY_v3.pdf                          [PARSE_RUNNING]
  ├── pymupdf4llm  ░░░░░░░░░░░░░░░░░░░░  PENDING
  └── docling      █████████████░░░░░░░  RUNNING   Est. 30s remaining

  PLASMA_OPS.pdf                                    [PARSE_FAILED]
  ├── pymupdf4llm  ████████████████████  COMPLETE  58s
  └── docling      ████████████████████  FAILED    [View Error]  [Retry]
```

**Retry UI — Failed Variant:**

```
PLASMA_OPS.pdf → docling → FAILED
  Error: "DocumentProcessingError: Cannot decode page 47 — corrupted xref table"
  [View Full Error Log]
  [Retry Parse (docling)]   ← re-queues only this specific variant
```

**Isolation:**
- Each ParseVariant is a completely independent Celery task
- A variant failure emits an SSE event but does not cancel other variants
- ParseVariant owns its own file paths — no sharing with siblings

**Shared with:**
- F12 (Logs): every log statement goes to JobLog table
- F11 (Monitoring): document status changes propagate to batch progress bar via SSE
- F14 (Notifications): stage completion and failures fire notifications

---

### F04 — Multiple Parser Variants (Requirement 3)

**Goal:** When multiple parsers are configured, both run and produce independent
`ParseVariant` records. Admin can compare outputs and select one for review.

**When active:** `document.effective_config.parsers.length > 1`

**UI — Variant Comparison Panel (on Document Detail page):**

```
TOKAMAK_MANUAL_2024.pdf                         [ PARSE_COMPLETE ]
────────────────────────────────────────────────────────────────────
Parse Variants

  ┌───────────────────────────────────┐  ┌───────────────────────────────────┐
  │  Parser:  pymupdf4llm             │  │  Parser:  docling                 │
  │  Status:  COMPLETE (1m 12s)       │  │  Status:  COMPLETE (2m 30s)       │
  │                                   │  │                                   │
  │  Files:                           │  │  Files:                           │
  │  · raw.md     [Preview] [Download]│  │  · raw.md     [Preview] [Download]│
  │  · parsed.md  [Preview] [Download]│  │  · parsed.md  [Preview] [Download]│
  │                                   │  │                                   │
  │  Normalization Variants:          │  │  Normalization Variants:          │
  │  · qwen3-70b  COMPLETE  4m 22s   │  │  · qwen3-70b  COMPLETE  4m 18s   │
  │    [Preview normalized]           │  │    [Preview normalized]           │
  │  · qwen3-14b  COMPLETE  1m 45s   │  │  · qwen3-14b  COMPLETE  1m 40s   │
  │    [Preview normalized]           │  │    [Preview normalized]           │
  │                                   │  │                                   │
  │  [Select for Review]              │  │  [Select for Review]              │
  └───────────────────────────────────┘  └───────────────────────────────────┘
```

**[Preview] behaviour:**
- Opens a right-side drawer with the MD file rendered as formatted text
- Shows raw character count and line count in drawer header
- [Download] triggers browser file download

**[Select for Review] behaviour:**
- Marks this ParseVariant as `is_selected_for_review = true`
- Opens F06 (norm variant selection) if multiple norm variants exist
- Or proceeds directly to review if only one norm variant

**Isolation:**
- Variant comparison panel state (which preview is open) is component-local
- Selecting a variant does not delete others — deletion only happens post-approval (§4.4)

---

### F05 — LLM Normalization Pipeline (Requirements 2, 7)

**Goal:** Run LLM normalization on parsed MD files. Optional step that can be
triggered at config time or manually later from review stage. Normalization failure
MUST cleanly roll back to PARSE_COMPLETE state.

**Three Trigger Paths:**

```
PATH A — Auto-trigger (normalization_enabled=true in config):
  Document reaches PARSE_COMPLETE
  → Backend auto-queues normalization jobs for all ParseVariants
  → Document: PARSE_COMPLETE → NORMALIZE_PENDING → NORMALIZE_RUNNING

PATH B — Manual trigger from Batch Detail page:
  Admin sees document in PARSE_COMPLETE
  Admin clicks [Trigger Normalization] on document card
  → Same flow as PATH A

PATH C — Late trigger from Review Stage (Requirement 2):
  Admin opens review for a document in REVIEW_PENDING (parsed, no normalization run)
  Admin sees "No normalization has been run" notice in review page
  Admin clicks [Trigger LLM Normalization] button
  Admin selects model(s) from dropdown
  Admin clicks [Start Normalization]
  → Document: REVIEW_PENDING → NORMALIZE_PENDING → NORMALIZE_RUNNING → NORMALIZE_COMPLETE → REVIEW_PENDING
  → Progress shown inline on review page (not a page navigation)
  → After completion, normalized.md option appears in variant selector
  → Review proceeds normally — admin can now compare parsed vs normalized
```

**Backend Job Logic:**

```python
def run_normalization_job(norm_variant_id):
    norm_variant.status = RUNNING
    norm_variant.started_at = now()
    log(INFO, f"Starting normalization with {norm_variant.model_config.model_id}")

    try:
        parsed_content = read_file(parse_variant.parsed_md_path)
        start_time = time.monotonic()

        response = call_llm_endpoint(
            endpoint=norm_variant.model_config.endpoint,
            model=norm_variant.model_config.model_id,
            prompt=NORMALIZATION_SYSTEM_PROMPT,
            content=parsed_content
        )

        elapsed_ms = int((time.monotonic() - start_time) * 1000)

        write_file(norm_variant.normalized_md_path, response.text)
        norm_variant.normalized_md_path = <path>
        norm_variant.time_taken_ms = elapsed_ms
        norm_variant.status = COMPLETE
        norm_variant.completed_at = now()
        log(INFO, f"Normalization complete in {elapsed_ms}ms")

    except ConnectionError as e:
        handle_norm_failure(norm_variant, COMPLETE_FAILURE, e)
    except IncompleteResponseError as e:
        handle_norm_failure(norm_variant, PARTIAL_FAILURE, e)

def handle_norm_failure(norm_variant, failure_mode, exception):
    # INVARIANT 3 — must execute ALL steps
    if file_exists(norm_variant.normalized_md_path):
        delete_file(norm_variant.normalized_md_path)
    norm_variant.normalized_md_path = None
    norm_variant.status = FAILED
    norm_variant.failure_mode = failure_mode
    norm_variant.error_message = str(exception)[:200]
    norm_variant.error_detail = traceback.format_exc()
    document.status = PARSE_COMPLETE        # REVERT
    document.error_summary = f"Normalization failed: {str(exception)[:100]}"
    log(ERROR, "Normalization failed", detail=traceback)
    emit_sse(job_error_event(...))
    create_notification(ERROR, f"{document.filename} — Normalization Failed", ...)
```

**UI — Normalization Metadata Display (Requirement 4):**

```
Normalization Variant: Qwen3 70B
  Status:      COMPLETE
  Model ID:    qwen3-70b
  Endpoint:    http://10.100.0.5:8000/v1        ← network IP shown
  Time Taken:  4m 22s (262,140 ms)              ← precise time shown
  Output:      normalized.md  [Preview] [Download]
```

**UI — Normalization Failure State:**

```
Normalization Variant: Qwen3 70B
  Status:      FAILED (Complete Failure)
  Error:       Connection timeout to http://10.100.0.5:8000/v1 after 30s
  [View Full Error Log]
  [Retry Normalization]    ← re-queues only this NormVariant
  [Proceed to Review without normalization]   ← skips normalization entirely
```

**Retry after failure:**
- Admin clicks [Retry Normalization]
- Backend: re-queues norm job for FAILED NormVariant only
- ParseVariant data is untouched — not re-parsed
- Document: PARSE_COMPLETE → NORMALIZE_PENDING → NORMALIZE_RUNNING

**Isolation:**
- Each NormVariant is an independent Celery task
- NormVariant failure NEVER touches ParseVariant files
- NormVariant failure of qwen3-70b NEVER affects qwen3-14b NormVariant

---

### F06 — Multiple Normalization Variants (Requirement 3)

**Goal:** When multiple normalization models are configured, each produces an
independent `NormVariant`. Admin compares them and selects one for review.

**Structure Example:**

```
Document: TOKAMAK_MANUAL
└── ParseVariant: docling (COMPLETE)
    ├── NormVariant: qwen3-70b (COMPLETE, 4m 22s)
    └── NormVariant: qwen3-14b (COMPLETE, 1m 45s)
└── ParseVariant: pymupdf4llm (COMPLETE)
    ├── NormVariant: qwen3-70b (COMPLETE, 4m 18s)
    └── NormVariant: qwen3-14b (COMPLETE, 1m 40s)
```

**UI — Norm Variant Comparison (within ParseVariant card):**

```
ParseVariant: docling (COMPLETE)
  parsed.md  [Preview] [Download]

  Normalization Variants:
  ┌────────────────────────────────────┐  ┌────────────────────────────────────┐
  │  Qwen3 70B                         │  │  Qwen3 14B                         │
  │  Endpoint: 10.100.0.5:8000        │  │  Endpoint: 10.100.0.5:8001        │
  │  Time: 4m 22s                      │  │  Time: 1m 45s                      │
  │  Status: COMPLETE                  │  │  Status: COMPLETE                  │
  │  [Preview normalized.md]           │  │  [Preview normalized.md]           │
  │  [Download]                        │  │  [Download]                        │
  │  [Select this for Review]          │  │  [Select this for Review]          │
  └────────────────────────────────────┘  └────────────────────────────────────┘

  ○ Use parsed.md directly (skip normalization for review)
```

**Selection and File Survival (Requirement 3):**

```
Admin selects: docling ParseVariant + qwen3-70b NormVariant

After review approval, file cleanup (§4.4) leaves ONLY:
  source/TOKAMAK_MANUAL_2024.pdf
  variants/{docling_pv_id}/raw.md
  variants/{docling_pv_id}/parsed.md
  variants/{docling_pv_id}/norm/{qwen3_70b_nv_id}/normalized.md
  review/approved.md

DELETED:
  variants/{pymupdf4llm_pv_id}/  (entire directory)
  variants/{docling_pv_id}/norm/{qwen3_14b_nv_id}/  (non-selected norm)
```

---

### F07 — Review Stage (Requirements 2, 5)

**Goal:** Admin reviews final MD content before indexing. Actions available:
- Select which (ParseVariant × NormVariant) pair to review
- Trigger normalization if not yet run (Req 2)
- Edit content inline in browser (Req 5)
- Download any of the available MD files (Req 5)
- Upload a replacement MD file — that file gets indexed (Req 5)
- Approve for chunking

**Route:** `/review/{documentId}`

**Trigger:** Document reaches REVIEW_PENDING; admin clicks [Go to Review]

**UI Wireframe:**

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│ Review — TOKAMAK_MANUAL_2024.pdf                                                │
│ Status: REVIEW_PENDING                                                           │
│ ─────────────────────────────────────────────────────────────────────────────── │
│                                                                                  │
│ STEP 1: SELECT REVIEW INPUT                                                      │
│                                                                                  │
│  Parse Variant:       ● docling (2m 30s)    ○ pymupdf4llm (1m 12s)             │
│                                                                                  │
│  Normalization:       ● Qwen3 70B (4m 22s)  ○ Qwen3 14B (1m 45s)              │
│                       ○ None — use parsed.md directly                           │
│                                                                                  │
│  ┌──────────────────────────────────────────────────────────────────────────┐   │
│  │  No normalization has been run yet.                                      │   │  ← shown if no norm run
│  │  [Trigger LLM Normalization]  Select model: [Qwen3 70B ▼]  [Start]     │   │  ← Requirement 2
│  └──────────────────────────────────────────────────────────────────────────┘   │
│                                                                                  │
│  → Currently reviewing: docling/normalized_qwen3-70b.md                         │
│                                                                                  │
│ ─────────────────────────────────────────────────────────────────────────────── │
│                                                                                  │
│ STEP 2: FILES                                                                    │
│                                                                                  │
│  Download:  [raw.md ↓]  [parsed.md ↓]  [normalized.md ↓]    ← Requirement 5   │
│  Upload replacement:  [Choose .md file to upload]             ← Requirement 5   │
│  (Uploaded file will replace current review content and be indexed)             │
│                                                                                  │
│ ─────────────────────────────────────────────────────────────────────────────── │
│                                                                                  │
│ STEP 3: REVIEW & EDIT                                                            │
│                                                                                  │
│  ┌── MD Editor (CodeMirror 6) ────────────────────────────────────────────────┐ │
│  │  # TOKAMAK MANUAL                                                          │ │
│  │                                                                             │ │
│  │  ## Chapter 1: Introduction                                                 │ │
│  │  The tokamak is a magnetic confinement device designed to...               │ │
│  │  [admin can edit this content directly — Requirement 5]                    │ │
│  └─────────────────────────────────────────────────────────────────────────── ┘ │
│                                                                                  │
│  [Save Draft]       (saves editor content to server as edited.md, no approval)  │
│                                                     [Approve & Index ✓]          │
│                                                                                  │
└──────────────────────────────────────────────────────────────────────────────────┘
```

**File Download Implementation (Requirement 5):**

```
[raw.md ↓]          → GET /api/v1/documents/{docId}/files/raw
                       Content-Disposition: attachment; filename="TOKAMAK_raw.md"

[parsed.md ↓]       → GET /api/v1/documents/{docId}/files/parsed
                       Content-Disposition: attachment; filename="TOKAMAK_parsed.md"

[normalized.md ↓]   → GET /api/v1/documents/{docId}/files/normalized
                       404 if normalization was not run or not selected
                       Content-Disposition: attachment; filename="TOKAMAK_normalized.md"
```

**File Upload Flow (Requirement 5):**

```
1. Admin clicks [Choose .md file to upload]
2. File picker opens (accept=".md" only)
3. Admin selects locally-edited file
4. POST /api/v1/documents/{docId}/review/upload (FormData: { file })
5. Backend saves to review/uploaded.md
6. Editor reloads with uploaded file content
7. Notice shown: "Reviewing your uploaded file. This will be indexed on approval."
8. Admin can still make further edits in browser
9. On [Approve]: browser editor content is used (if modified after upload)
      OR uploaded.md content (if editor unchanged)
```

**Late Normalization Flow in Review (Requirement 2):**

```
Admin opens review for a document with no normalization run.
Admin sees: "No normalization has been run yet."
Admin clicks [Trigger LLM Normalization]
Admin selects model from dropdown
Admin clicks [Start]

Backend:
  1. Creates NormVariant for selected ParseVariant + model
  2. Queues normalization job
  3. Document: REVIEW_PENDING → NORMALIZE_PENDING

Frontend:
  SSE event received → inline progress indicator in review page
  "Normalizing with Qwen3 70B... (0s)"
  SSE event: NORMALIZE_RUNNING → show elapsed time counter
  SSE event: NORMALIZE_COMPLETE → progress disappears
  → "normalized.md" option appears in STEP 1 variant selector
  → Editor reloads with normalized content

Admin now reviews the normalized content and approves.
```

**[Approve & Index ✓] flow:**

```
1. Current editor content saved to review/approved.md (server-side)
2. POST /api/v1/documents/{docId}/review/approve
   Body: { selected_parse_variant_id, selected_norm_variant_id, notes? }
3. Backend:
   a. Writes editor content to review/approved.md
   b. ReviewRecord.status = APPROVED, approved_at = now()
   c. Document.status = REVIEW_APPROVED
   d. Schedules async file cleanup (§4.4)
   e. Queues chunking job → CHUNK_PENDING
   f. Creates notification: "TOKAMAK_MANUAL approved for indexing"
4. Frontend: navigates to /batches/{batchId}
```

**Isolation:**
- Editor content lives in browser state until [Save Draft] or [Approve]
- Uploaded file is stored on server but not committed to canonical_files until approval
- Review page does not modify any ParseVariant or NormVariant data

---

### F08 — Chunking & Indexing

**Goal:** Take review_approved_md, chunk it, embed each chunk, index into Qdrant.

**Trigger:** Document transitions to REVIEW_APPROVED → auto-queues CHUNK_PENDING

**Backend Job Logic:**

```python
def run_chunking_job(document_id):
    document.status = CHUNK_RUNNING
    log(INFO, "Starting chunking")

    try:
        content = read_file(document.review.review_approved_md_path)
        chunks = hierarchical_chunk(content)  # doc → section → subsection → leaf

        # Delete existing Qdrant points for this document (idempotency)
        qdrant_client.delete(
            collection_name=COLLECTION,
            points_selector=FilterSelector(
                filter=Filter(must=[FieldCondition(key="document_id", match=MatchValue(value=document_id))])
            )
        )

        for i, chunk in enumerate(chunks):
            embedding = embed(chunk.text)
            qdrant_client.upsert(
                collection_name=COLLECTION,
                points=[PointStruct(
                    id=generate_uuid(),
                    vector=embedding,
                    payload={
                        "document_id": document_id,
                        "batch_id": document.batch_id,
                        "content": chunk.text,
                        "chunk_index": i,
                        "section_path": chunk.section_path,
                        "page_numbers": chunk.page_numbers,
                        "token_count": count_tokens(chunk.text),
                        "char_count": len(chunk.text),
                        "indexed_at": now()
                    }
                )]
            )
            log(INFO, f"Indexed chunk {i+1}/{len(chunks)}")

        document.chunk_count = len(chunks)
        document.indexed_at = now()
        document.status = INDEXED
        create_notification(SUCCESS, f"{document.filename} — Indexed", f"{len(chunks)} chunks indexed")

    except Exception as e:
        document.status = CHUNK_FAILED
        log(ERROR, f"Chunking failed: {e}", detail=traceback)
        create_notification(ERROR, f"{document.filename} — Indexing Failed", str(e))
```

**Retry from CHUNK_FAILED:**

```
Admin clicks [Retry Chunking]
→ POST /api/v1/documents/{docId}/retry-chunking
→ Backend:
    1. Delete all Qdrant points for this document_id (cleanup partial index)
    2. Re-queue chunking job from review_approved_md (file untouched)
    3. Document: CHUNK_FAILED → CHUNK_PENDING
```

---

### F09 — Document Warehouse (Requirement 9)

**Goal:** Central read-only view of ALL documents across ALL batches. Admin can
browse, search, filter, and access all 5 canonical files per document.

**Route:** `/warehouse`

**UI Wireframe:**

```
┌───────────────────────────────────────────────────────────────────────────────┐
│ Document Warehouse                                              [🔍 Search... ]│
│                                                                               │
│ Filter: [All Batches ▼] [All Statuses ▼] [Date Range ▼] [File Type ▼]      │
│                                                                               │
│ 42 documents total  ·  38 indexed  ·  2 pending review  ·  2 failed          │
│ ─────────────────────────────────────────────────────────────────────────── │
│                                                                               │
│ TOKAMAK_MANUAL_2024.pdf                    Batch #8    INDEXED  Jun 2, 2025  │
│   12.4 MB · docling + qwen3-70b · 342 chunks                                │
│   [Source PDF]  [raw.md]  [parsed.md]  [normalized.md]  [approved.md]       │
│                                                                               │
│ IPR_SAFETY_POLICY_v3.pdf                   Batch #8    REVIEW_PENDING        │
│   2.1 MB · docling only · no normalization                                   │
│   [Source PDF]  [raw.md]  [parsed.md]  [—]  [—]         [Go to Review]      │
│                                                                               │
│ PLASMA_OPS.pdf                             Batch #9    PARSE_FAILED          │
│   5.3 MB · parse error (docling)                                             │
│   [Source PDF]  [—]  [—]  [—]  [—]            [View Error Log]  [Retry]     │
│                                                                               │
│ ─────────────────────────────────────────────────────────────────────────── │
│ [Previous]   Page 1 of 3   [Next]         25 per page [▼]                   │
└───────────────────────────────────────────────────────────────────────────────┘
```

**File Badge Rules:**

| Badge State | Meaning |
|-------------|---------|
| `[Source PDF]` (active) | File exists, click to download |
| `[raw.md]` (active) | Parse completed, variant selected |
| `[normalized.md]` (active) | Normalization run + selected |
| `[—]` (greyed out) | Step not run or not yet selected |
| `[approved.md]` (green) | Review approved, this is what's indexed |

**Action Shortcuts:**
- `[Go to Review]` → navigates to `/review/{documentId}`
- `[Retry]` → fires retry for the appropriate failed stage
- `[View Error Log]` → navigates to `/logs?document_id={id}&level=ERROR`

**Search:** Full-text search on original_filename
**Filter by status:** Any DocumentStatus value
**Filter by batch:** Batch name or ID
**Isolation:** Read-only; no state mutations except navigation shortcuts

---

### F10 — Chunks Viewer (Requirement 10)

**Goal:** View all chunks currently indexed in Qdrant. Admin can browse, search
chunk content, filter by document/batch, and inspect chunk metadata.

**Route:** `/chunks`

**UI Wireframe:**

```
┌───────────────────────────────────────────────────────────────────────────────┐
│ Chunks Viewer                                      [🔍 Search chunk content...]│
│                                                                               │
│ Filter: [All Documents ▼] [All Batches ▼]    4,821 chunks across 38 docs    │
│ ─────────────────────────────────────────────────────────────────────────── │
│                                                                               │
│ Chunk #1    TOKAMAK_MANUAL_2024.pdf                          Batch #8        │
│ Section:    Chapter 1 › Introduction                                         │
│ Pages: 1–2  ·  342 tokens  ·  Indexed: Jun 2, 2025 14:32                   │
│ ─────────────────────────────────────────────────────────────────────────── │
│ The tokamak is a magnetic confinement device designed to facilitate nuclear  │
│ fusion reactions. The plasma is contained within a torus-shaped vacuum...    │
│                                                                [Expand ▼]    │
│ ─────────────────────────────────────────────────────────────────────────── │
│                                                                               │
│ Chunk #2    TOKAMAK_MANUAL_2024.pdf                          Batch #8        │
│ Section:    Chapter 1 › Historical Context                                   │
│ ...                                                                           │
│ ─────────────────────────────────────────────────────────────────────────── │
│                                                                               │
│ [Previous]   Page 1 of 241   [Next]                                          │
└───────────────────────────────────────────────────────────────────────────────┘
```

**[Expand ▼] behaviour:** Shows full chunk content in-place (no modal)

**Backend:** GET /api/v1/chunks queries Qdrant with scroll API (no embeddings needed
for listing — use payload only). Full-text search uses Qdrant's payload text filter.

**Isolation:**
- Entirely read-only — no mutations
- Fetches Qdrant data directly through backend API

---

### F11 — Monitoring Dashboard (Requirement 8)

**Goal:** Real-time view of all active ingestion jobs. Shows batch-level progress
bars, recent failures, and a dedicated failed jobs section. Bell icon shows
unread notification count.

**Route:** `/monitoring`  (default landing page — `/` redirects here)

**UI Wireframe:**

```
┌───────────────────────────────────────────────────────────────────────────────┐
│ Monitoring Dashboard                                          🔔 3   Admin    │
│                                                                               │
│ ACTIVE BATCHES (2)                                                            │
│ ─────────────────────────────────────────────────────────────────────────── │
│                                                                               │
│ Batch #9 — Reactor Docs Q3                                    PARSING        │
│   ████████████░░░░░░░░░░░░░░░░   3 / 5 documents parsed                     │
│   Started: 14:22   Elapsed: 8m 12s   Est. remaining: ~5m                    │
│   [View Details]                                                              │
│                                                                               │
│ Batch #8 — IPR Policy Batch                                   REVIEWING      │
│   ████████████████████████░░░░   Awaiting review: 2 documents                │
│   [View Details]   [Go to Review Queue]                                       │
│                                                                               │
│ ─────────────────────────────────────────────────────────────────────────── │
│ RECENT FAILURES (2)                                                           │
│                                                                               │
│  ✗ PLASMA_OPS.pdf (Batch #9)   Parse failed (docling)    2m ago  [Log] [Retry]│
│  ✗ REPORT_v2.pdf  (Batch #8)   Norm failed (qwen3-70b)  15m ago  [Log] [Retry]│
│                                                                               │
│ ─────────────────────────────────────────────────────────────────────────── │
│ COMPLETED TODAY (5)                                                           │
│                                                                               │
│  ✓ TOKAMAK_MANUAL   Indexed   342 chunks   Jun 2, 14:32                      │
│  ✓ SAFETY_POLICY    Indexed   87 chunks    Jun 2, 14:28                      │
│  ✓ PLASMA_DIAG      Indexed   204 chunks   Jun 2, 14:15                      │
│  ✓ OPS_MANUAL_v2    Indexed   156 chunks   Jun 2, 13:58                      │
│  ✓ ARCHIVE_2023     Indexed   89 chunks    Jun 2, 13:40                      │
│                                                                               │
│ ─────────────────────────────────────────────────────────────────────────── │
│ [View All Failed Jobs]         [View Full History]                            │
└───────────────────────────────────────────────────────────────────────────────┘
```

**Progress Bar Calculation:**

```typescript
function getBatchProgress(batch: Batch): { percent: number; label: string } {
  const { total_documents, documents_indexed, documents_failed, status } = batch;

  const stageWeights = {
    PARSING:     { weight: 0.25, label: `${documents_indexed}/${total_documents} documents parsed` },
    NORMALIZING: { weight: 0.50, label: `Normalizing documents...` },
    REVIEWING:   { weight: 0.75, label: `Awaiting review: ${batch.documents_pending_review} documents` },
    CHUNKING:    { weight: 0.90, label: `Indexing...` },
    COMPLETE:    { weight: 1.00, label: `All ${total_documents} documents indexed` },
  };

  return stageWeights[status] ?? { percent: 0, label: 'Processing...' };
}
```

**Dedicated Failed Jobs Section (`/monitoring?tab=failed`):**

```
All Failed Jobs

Filter: [All Batches ▼] [All Stages ▼] [Date Range ▼]

PLASMA_OPS.pdf  ·  Batch #9  ·  Stage: PARSE  ·  Jun 3 14:22
  Error: docling DocumentProcessingError on page 47
  [View Full Log]  [Retry Parse]

REPORT_v2.pdf  ·  Batch #8  ·  Stage: NORMALIZE  ·  Jun 3 14:07
  Error: Connection timeout to http://10.100.0.5:8001/v1
  [View Full Log]  [Retry Normalization]  [Skip Normalization → Review]
```

**SSE Setup (Frontend):**

```typescript
// hooks/useSSE.ts
export function useSSE() {
  const { addNotification } = useNotificationStore();
  const queryClient = useQueryClient();

  useEffect(() => {
    const es = new EventSource('/api/v1/events');

    es.addEventListener('batch_progress', (e) => {
      const event: BatchProgressEvent = JSON.parse(e.data);
      queryClient.setQueryData(['batch', event.batch_id], (old: Batch) => ({
        ...old,
        status: event.status,
        ...event.counts,
      }));
    });

    es.addEventListener('document_update', (e) => {
      const event: DocumentUpdateEvent = JSON.parse(e.data);
      queryClient.invalidateQueries({ queryKey: ['document', event.document_id] });
    });

    es.addEventListener('job_error', (e) => {
      // handled via notification SSE event
    });

    es.addEventListener('notification', (e) => {
      const notification: Notification = JSON.parse(e.data);
      addNotification(notification);
    });

    es.onerror = () => {
      // Auto-reconnect (EventSource does this automatically)
    };

    return () => es.close();
  }, []);
}
```

---

### F12 — Logs & Error Tracking (Requirement 6)

**Goal:** Complete log viewer showing all pipeline logs. Admin can filter by batch,
document, stage, level, and date. Expandable entries show full stack traces.

**Route:** `/logs`

**UI Wireframe:**

```
┌───────────────────────────────────────────────────────────────────────────────┐
│ Logs                                                                          │
│                                                                               │
│ Filter: [All Batches ▼] [All Docs ▼] [All Levels ▼] [Stage ▼] [Date ▼]    │
│ Search: [ Search log messages...                                           ]  │
│                                                                               │
│ Showing 247 entries (12 errors, 3 warnings, 232 info)                       │
│ ─────────────────────────────────────────────────────────────────────────── │
│                                                                               │
│ [ERROR]  14:42:03  PLASMA_OPS.pdf  /  Batch #9  /  PARSE (docling)          │
│   docling DocumentProcessingError: Cannot decode page 47 — corrupted xref   │
│   [▼ Expand traceback]                                                        │
│     File "docling/backend.py", line 847, in _decode_page                    │
│     XRefError: table corrupted at offset 0x7f3a...                          │
│                                                                               │
│ [ERROR]  14:38:12  REPORT_v2.pdf  /  Batch #8  /  NORMALIZE (qwen3-70b)    │
│   httpx.ConnectTimeout: Failed to connect to http://10.100.0.5:8001/v1      │
│   after 30.0 seconds                                                         │
│   [▼ Expand traceback]                                                        │
│                                                                               │
│ [INFO]   14:35:00  TOKAMAK_MANUAL  /  Batch #8  /  PARSE (docling)          │
│   Parse complete. raw.md: 487 KB, parsed.md: 312 KB, duration: 2m 30s      │
│                                                                               │
│ [WARN]   14:33:01  SAFETY_POLICY  /  Batch #8  /  PARSE (pymupdf4llm)      │
│   Page 3: image-only page detected, text extraction yielded 0 characters    │
│                                                                               │
│ [INFO]   14:33:00  SAFETY_POLICY  /  Batch #8  /  PARSE (pymupdf4llm)      │
│   Started parsing. File size: 2.1 MB                                         │
│ ─────────────────────────────────────────────────────────────────────────── │
│ [Previous]   Page 1 of 13   [Next]                                           │
└───────────────────────────────────────────────────────────────────────────────┘
```

**Failed Jobs Tab (`/logs?tab=failed`):**

```
All Failed Jobs — Complete History

  PLASMA_OPS.pdf    Batch #9    PARSE (docling)      Jun 3 14:42   [View]  [Retry]
  REPORT_v2.pdf     Batch #8    NORMALIZE (qwen3-70b) Jun 3 14:38  [View]  [Retry]
  ARCHIVE_OLD.pdf   Batch #6    CHUNK                 Jun 1 11:22  [View]  [Retry]
  MANUAL_v1.docx    Batch #5    UPLOAD                May 30 09:15 [View]
```

**Log Persistence:**
- Logs written to PostgreSQL JobLog table (append-only)
- No auto-deletion policy
- Backend provides paginated GET /api/v1/logs endpoint with all filter params

---

### F13 — Notification System (Requirements 8, 14)

**Goal:** Real-time, precise, concise notifications for all pipeline events.
Accessible from bell icon on every page. Persisted in DB, survive page refresh.

**Bell Icon Placement:** Top-right of TopBar, visible on all pages

**Bell Icon Behaviour:**
- Shows badge with unread count (max "99+" display)
- Click opens slide-down notification panel
- Panel overlaps page content (not a sidebar)

**UI — Bell + Panel:**

```
TopBar:  [Monitoring] [Upload] [Batches] [Warehouse] [Chunks] [Logs]   🔔 3   Admin
         ─────────────────────────────────────────────────────────────────────────
                                                               ┌───────────────────┐
                                                               │ Notifications     │
                                                               │ [Mark all read]   │
                                                               │ ───────────────── │
                                                               │ 🔴 PLASMA_OPS     │
                                                               │    Parse Failed   │
                                                               │    docling · 2m   │
                                                               │    [Details] [✕]  │
                                                               │ ───────────────── │
                                                               │ 🟢 TOKAMAK_MANUAL │
                                                               │    Indexed        │
                                                               │    342 chunks 14m │
                                                               │    [✕]            │
                                                               │ ───────────────── │
                                                               │ 🔵 Batch #8       │
                                                               │    Parse Complete │
                                                               │    3/3 docs  32m  │
                                                               │    [✕]            │
                                                               └───────────────────┘
```

**Notification Rules — When Each Fires:**

| Event | Type | Title Pattern | Message Pattern |
|-------|------|---------------|-----------------|
| Batch submitted | STAGE_UPDATE | "Batch #{n} — Submitted" | "{N} documents queued for parsing" |
| All docs in batch parsed | STAGE_UPDATE | "Batch #{n} — Parse Complete" | "{N}/{N} documents parsed" |
| Single doc parse failed | ERROR | "{filename} — Parse Failed" | "{parser} error. Retry available." |
| All docs normalized | STAGE_UPDATE | "Batch #{n} — Normalization Complete" | "{N} documents ready for review" |
| Single norm failed | ERROR | "{filename} — Normalization Failed" | "{model} unreachable. Parse data intact." |
| Doc ready for review | STAGE_UPDATE | "{filename} — Ready for Review" | "Awaiting your review and approval" |
| Doc approved | SUCCESS | "{filename} — Approved" | "Indexing will start automatically" |
| Doc indexed | SUCCESS | "{filename} — Indexed" | "{N} chunks indexed in Qdrant" |
| Chunk failed | ERROR | "{filename} — Indexing Failed" | "Chunking error. Retry available." |
| File cleanup done | WARNING | "Files Cleaned Up" | "{N} non-selected variant files removed" |

**Zustand Store:**

```typescript
// stores/notificationStore.ts
interface NotificationStore {
  notifications: Notification[];
  unreadCount: number;
  isOpen: boolean;
  setOpen: (open: boolean) => void;
  addNotification: (n: Notification) => void;
  markRead: (id: string) => void;
  markAllRead: () => void;
  dismiss: (id: string) => void;  // removes from list, marks read on server
}

const useNotificationStore = create<NotificationStore>((set) => ({
  notifications: [],
  unreadCount: 0,
  isOpen: false,
  setOpen: (open) => set({ isOpen: open }),
  addNotification: (n) => set((state) => ({
    notifications: [n, ...state.notifications].slice(0, 100),
    unreadCount: state.unreadCount + (n.read ? 0 : 1),
  })),
  markRead: (id) => set((state) => ({
    notifications: state.notifications.map(n =>
      n.notification_id === id ? { ...n, read: true } : n
    ),
    unreadCount: Math.max(0, state.unreadCount - 1),
  })),
  markAllRead: () => set((state) => ({
    notifications: state.notifications.map(n => ({ ...n, read: true })),
    unreadCount: 0,
  })),
  dismiss: (id) => set((state) => ({
    notifications: state.notifications.filter(n => n.notification_id !== id),
    unreadCount: state.notifications
      .filter(n => n.notification_id !== id && !n.read).length,
  })),
}));
```

**Initialization:** On app load, hydrate store from GET /api/v1/notifications
(backend returns latest 100 notifications for this admin, most recent first).

---

### F14 — Batch & Job History (Requirement 13)

**Goal:** View all past and active batches with full pipeline timeline, configuration
details, and per-document status. Read-only — no mutations.

**Route:** `/batches` (list) and `/batches/{batchId}` (detail)

**UI — Batch List (`/batches`):**

```
┌───────────────────────────────────────────────────────────────────────────────┐
│ Batch History                          [Search batches...]   [+ New Upload]   │
│                                                                               │
│ Filter: [All Statuses ▼] [Date Range ▼]                                      │
│                                                                               │
│ Batch #9   Reactor Docs Q3           PARSING         Jun 3, 2025             │
│   5 docs · 3 indexed · 1 parsing · 1 failed                                  │
│   [View Details]                                                              │
│                                                                               │
│ Batch #8   IPR Policy Batch          COMPLETE        Jun 2, 2025             │
│   3 docs · 3 indexed · Total time: 1h 24m                                    │
│   [View Details]                                                              │
│                                                                               │
│ Batch #7   Archive May 2025          PARTIALLY_COMPLETE   May 30, 2025       │
│   8 docs · 7 indexed · 1 failed                                              │
│   [View Details]                                                              │
└───────────────────────────────────────────────────────────────────────────────┘
```

**UI — Batch Detail (`/batches/{batchId}`):**

```
┌───────────────────────────────────────────────────────────────────────────────┐
│ Batch #8 — IPR Policy Batch                                       COMPLETE   │
│                                                                               │
│ PIPELINE TIMELINE (Requirement 13)                                            │
│ ─────────────────────────────────────────────────────────────────────────── │
│  Created:              Jun 2, 2025  09:15:03                                 │
│  Submitted:            Jun 2, 2025  09:22:17   (+7m 14s)                    │
│  Parsing started:      Jun 2, 2025  09:22:18                                 │
│  Parsing complete:     Jun 2, 2025  09:45:02   (+22m 44s)                   │
│  Normalization start:  Jun 2, 2025  09:45:03                                 │
│  Normalization end:    Jun 2, 2025  10:32:41   (+47m 38s)                   │
│  Review started:       Jun 2, 2025  10:35:10   (+2m 29s wait)               │
│  Review complete:      Jun 2, 2025  10:38:44   (+3m 34s)                    │
│  Indexing complete:    Jun 2, 2025  10:39:12   (+28s)                        │
│  ─────────────────────────────────────────────────────────────                │
│  Total time (submit → index): 1h 16m 55s                                    │
│                                                                               │
│ BATCH CONFIGURATION                                                           │
│ ─────────────────────────────────────────────────────────────────────────── │
│  Default parsers:         docling, pymupdf4llm                               │
│  Default norm models:     Qwen3 70B (10.100.0.5:8000)                       │
│                                                                               │
│ DOCUMENTS                                                                     │
│ ─────────────────────────────────────────────────────────────────────────── │
│                                                                               │
│ ▶ TOKAMAK_MANUAL_2024.pdf                                    INDEXED         │
│   Per-doc config: [Use batch defaults]                                        │
│   Parse:   docling (2m 30s) + pymupdf4llm (1m 12s)                          │
│   Norm:    qwen3-70b (4m 22s) on both parse variants                         │
│   Selected: docling + qwen3-70b                                               │
│   Review:  Approved Jun 2 10:37:02 (3m 14s in review)                       │
│   Indexed: Jun 2 10:38:55 · 342 chunks                                       │
│                                                                               │
│ ▶ IPR_SAFETY_POLICY_v3.pdf                                   INDEXED         │
│   Per-doc config: [Custom — docling only, no normalization]                  │
│   Parse:   docling (42s) only                                                │
│   Norm:    disabled (per-doc override)                                        │
│   Selected: docling (no norm)                                                 │
│   Review:  Approved Jun 2 10:37:18 (2m 08s in review)                       │
│   Indexed: Jun 2 10:38:50 · 87 chunks                                        │
│                                                                               │
│ [Download Batch Report (JSON)]                                                │
└───────────────────────────────────────────────────────────────────────────────┘
```

**[Download Batch Report]:** Returns a JSON file with full batch data matching
the Batch TypeScript interface, downloadable as `batch_{id}_report.json`

---

### F15 — UI Architecture (Requirement 15)

**Goal:** Build the entire UI from scratch with a clean, consistent design.
No legacy code carried over.

**Design Principles:**
- Dark sidebar, light main content area
- Status badges use consistent color system
- All tables are paginated (25 items per page, configurable)
- All file downloads use native browser API (no new tab)
- Loading states on all async operations (skeleton screens, not spinners alone)
- Empty states for all list views ("No documents yet — upload your first batch")
- Optimistic updates where appropriate (notification mark-read)

**Color System (Tailwind CSS v4 custom tokens):**

```css
/* In globals.css */
:root {
  --color-status-uploaded:   theme('colors.slate.500');
  --color-status-running:    theme('colors.blue.500');
  --color-status-complete:   theme('colors.green.500');
  --color-status-failed:     theme('colors.red.500');
  --color-status-pending:    theme('colors.amber.500');
  --color-status-indexed:    theme('colors.emerald.600');
  --color-status-review:     theme('colors.violet.500');
}
```

**Status Badge Component:**

```typescript
// components/ui/StatusBadge.tsx
const STATUS_CONFIG: Record<DocumentStatus | BatchStatus, { label: string; variant: string }> = {
  UPLOADED:           { label: 'Uploaded',          variant: 'slate' },
  PARSE_PENDING:      { label: 'Parse Queued',       variant: 'amber' },
  PARSE_RUNNING:      { label: 'Parsing',            variant: 'blue' },
  PARSE_FAILED:       { label: 'Parse Failed',       variant: 'red' },
  PARSE_COMPLETE:     { label: 'Parsed',             variant: 'green' },
  NORMALIZE_PENDING:  { label: 'Norm Queued',        variant: 'amber' },
  NORMALIZE_RUNNING:  { label: 'Normalizing',        variant: 'blue' },
  NORMALIZE_FAILED:   { label: 'Norm Failed',        variant: 'red' },
  NORMALIZE_COMPLETE: { label: 'Normalized',         variant: 'green' },
  REVIEW_PENDING:     { label: 'Ready for Review',   variant: 'violet' },
  REVIEW_IN_PROGRESS: { label: 'In Review',          variant: 'violet' },
  REVIEW_APPROVED:    { label: 'Approved',           variant: 'green' },
  CHUNK_PENDING:      { label: 'Index Queued',       variant: 'amber' },
  CHUNK_RUNNING:      { label: 'Indexing',           variant: 'blue' },
  CHUNK_FAILED:       { label: 'Index Failed',       variant: 'red' },
  INDEXED:            { label: 'Indexed',            variant: 'emerald' },
  DRAFT:              { label: 'Draft',              variant: 'slate' },
  COMPLETE:           { label: 'Complete',           variant: 'emerald' },
  PARTIALLY_COMPLETE: { label: 'Partial',            variant: 'amber' },
  FAILED:             { label: 'Failed',             variant: 'red' },
};
```

**Route Structure:**

```
/                              → redirect to /monitoring
/monitoring                   → F11: Monitoring Dashboard (default landing)
/monitoring?tab=failed        → F11: Monitoring Dashboard, failed jobs tab
/upload                       → F01: Document Upload
/batches                      → F14: Batch History List
/batches/[batchId]            → F14: Batch Detail
/batches/[batchId]/config     → F02: Advanced Configuration
/batches/[batchId]/[docId]    → Document Detail (variants panel)
/review/[docId]               → F07: Review Stage
/warehouse                    → F09: Document Warehouse
/chunks                       → F10: Chunks Viewer
/logs                         → F12: Logs
/logs?tab=failed              → F12: Failed Jobs Tab
```

**File Structure:**

```
src/
├── app/
│   ├── layout.tsx                          ← Root layout, SSEProvider
│   ├── page.tsx                            ← Redirect to /monitoring
│   └── (dashboard)/
│       ├── layout.tsx                      ← DashboardLayout (sidebar + topbar)
│       ├── monitoring/
│       │   └── page.tsx
│       ├── upload/
│       │   └── page.tsx
│       ├── batches/
│       │   ├── page.tsx
│       │   └── [batchId]/
│       │       ├── page.tsx
│       │       ├── config/
│       │       │   └── page.tsx
│       │       └── [docId]/
│       │           └── page.tsx
│       ├── review/
│       │   └── [docId]/
│       │       └── page.tsx
│       ├── warehouse/
│       │   └── page.tsx
│       ├── chunks/
│       │   └── page.tsx
│       └── logs/
│           └── page.tsx
├── components/
│   ├── layout/
│   │   ├── DashboardLayout.tsx
│   │   ├── Sidebar.tsx
│   │   └── TopBar.tsx
│   ├── notifications/
│   │   ├── BellIcon.tsx
│   │   └── NotificationPanel.tsx
│   ├── upload/
│   │   ├── DropZone.tsx
│   │   ├── FileList.tsx
│   │   └── FileRow.tsx
│   ├── batch/
│   │   ├── BatchCard.tsx
│   │   ├── BatchTimeline.tsx
│   │   ├── BatchProgressBar.tsx
│   │   └── config/
│   │       ├── BatchConfigForm.tsx
│   │       ├── ParserSelector.tsx
│   │       ├── NormModelSelector.tsx
│   │       └── PerDocOverride.tsx
│   ├── document/
│   │   ├── DocumentDetail.tsx
│   │   ├── ParseVariantCard.tsx
│   │   ├── NormVariantCard.tsx
│   │   ├── VariantPreviewDrawer.tsx
│   │   └── VariantCountBadge.tsx
│   ├── review/
│   │   ├── ReviewEditor.tsx           ← CodeMirror 6 wrapper
│   │   ├── VariantSelector.tsx
│   │   ├── FileActions.tsx
│   │   ├── LateNormTrigger.tsx
│   │   └── ApproveButton.tsx
│   ├── monitoring/
│   │   ├── ActiveBatchList.tsx
│   │   ├── FailedJobRow.tsx
│   │   └── CompletedJobList.tsx
│   ├── warehouse/
│   │   ├── WarehouseTable.tsx
│   │   └── FileBadges.tsx
│   ├── chunks/
│   │   ├── ChunkList.tsx
│   │   └── ChunkCard.tsx
│   ├── logs/
│   │   ├── LogViewer.tsx
│   │   └── LogEntry.tsx
│   └── ui/
│       ├── StatusBadge.tsx
│       ├── ProgressBar.tsx
│       ├── SkeletonRow.tsx
│       └── EmptyState.tsx
├── lib/
│   ├── stores/
│   │   ├── notificationStore.ts       ← Zustand
│   │   └── batchStore.ts              ← Zustand (active batches cache)
│   ├── hooks/
│   │   ├── useSSE.ts                  ← SSE subscription
│   │   ├── useBatch.ts                ← TanStack Query
│   │   ├── useDocument.ts             ← TanStack Query
│   │   ├── useChunks.ts               ← TanStack Query
│   │   ├── useLogs.ts                 ← TanStack Query
│   │   └── useNotifications.ts        ← TanStack Query (initial hydration)
│   ├── api/
│   │   ├── client.ts                  ← Base fetch with auth headers
│   │   ├── batches.ts
│   │   ├── documents.ts
│   │   ├── chunks.ts
│   │   ├── logs.ts
│   │   └── notifications.ts
│   └── types/
│       └── index.ts                   ← All TypeScript types from §2
```

---

## §6 Shared vs Isolated Concerns Matrix

### 6.1 Shared Infrastructure (Used by Multiple Features)

| Concern | Features That Use It | Implementation |
|---------|---------------------|----------------|
| SSE connection | F11, F12, F13, F07 (late norm progress) | `useSSE` hook, initialized in root layout |
| Notification store | All pages via bell icon | Zustand `useNotificationStore` |
| Job logging | F03, F05, F08 (all pipeline steps) | Backend shared `Logger` → JobLog table |
| File path service | F03, F05, F07, F08 (all steps writing files) | Backend `FilePathService` singleton |
| Status badge | F09, F11, F14, F03 UI, F05 UI | `StatusBadge` component with config map |
| Error propagation chain | F03, F05, F08 | Each step: log → emit SSE → create notification |
| React Query client | All data-fetching features | Single QueryClient in root layout |
| Batch context | F02, F03, F05, F07, F14 | React Query cache keyed by batch_id |

### 6.2 Isolated Per Feature

| Feature | What It Owns Exclusively |
|---------|--------------------------|
| F01 Upload | Drop zone state, per-file progress, upload queue |
| F02 Batch Config | React Hook Form state, unsaved config draft |
| F03 Parse Jobs | ParseVariant lifecycle, parse worker logic |
| F04 Variant Comparison | Preview drawer open/close state |
| F05 Norm Jobs | NormVariant lifecycle, normalization worker logic |
| F06 Norm Comparison | Side-by-side comparison panel state |
| F07 Review | Editor content (until saved), upload temp state |
| F08 Chunking | Qdrant write operations per document_id |
| F09 Warehouse | Filter state, search query, pagination |
| F10 Chunks | Chunk search query, pagination, expanded rows |
| F11 Monitoring | SSE subscription lifecycle, failed jobs tab |
| F12 Logs | Log filter state, expanded traceback entries |
| F13 Notifications | Zustand store contents (notifications array) |
| F14 History | Batch list pagination, expanded document rows |

### 6.3 Data Isolation Boundaries (Inviolable)

```
ParseVariant ←X→ NormVariant:
  NormVariant failure NEVER touches ParseVariant data or files.

Document ←X→ Document:
  One document's failure NEVER affects sibling documents in the same batch.

Batch ←X→ Batch:
  Completely isolated namespaces in Qdrant and file storage.

Review Stage ←X→ Parse/Norm Data:
  Review page reads files but NEVER writes to variants/{...}/
  Only writes to review/ subdirectory.

Chunking ←X→ Everything Upstream:
  Chunking reads ONLY review_approved_md_path.
  NEVER accesses variants/ directory directly.
  NEVER modifies ReviewRecord.

Logs ←X→ All Pipeline Steps:
  Logs are append-only. No pipeline step reads logs.
  Log viewer is pure read.

Notifications ←X→ All Pipeline Steps:
  Notifications are one-way: pipeline writes, UI reads.
  Dismissing/marking-read does not affect pipeline.
```

---

## §7 API Contracts

> Base URL: `/api/v1/`
> All responses: `{ data: T | null, error: string | null, detail?: string }`
> Authentication: Bearer token in Authorization header (middleware handles all routes)

### 7.1 Batch & Upload

```
POST   /batches                          Create batch + upload files
  Content-Type: multipart/form-data
  Body: { files: File[], batch_name: string, batch_description?: string }
  Response: { data: Batch }

GET    /batches                          List batches (paginated)
  Query: status?, page=1, limit=25, search?
  Response: { data: { items: Batch[], total: number, page: number } }

GET    /batches/{batchId}                Batch detail with all documents
  Response: { data: Batch }             (includes full parse_variants + norm_variants)

PATCH  /batches/{batchId}/config         Save batch configuration
  Body: BatchConfig
  Response: { data: Batch }

POST   /batches/{batchId}/submit         Submit DRAFT batch
  Response: { data: Batch }             (status → SUBMITTED, jobs queued)

DELETE /batches/{batchId}                Delete DRAFT batch (only DRAFT allowed)
  Response: { data: { deleted: true } }
```

### 7.2 Documents

```
GET    /documents/{docId}                Document detail
  Response: { data: Document }

GET    /documents/{docId}/files/{type}   Download file
  type: 'raw' | 'parsed' | 'normalized' | 'approved' | 'source'
  Response: file stream with Content-Disposition header
  Error: 404 if file not available yet

POST   /documents/{docId}/select-variant Set parse + norm variant for review
  Body: { parse_variant_id: string, norm_variant_id: string | null }
  Response: { data: ReviewRecord }

POST   /documents/{docId}/review/upload  Upload replacement MD
  Content-Type: multipart/form-data
  Body: { file: File }  (.md only)
  Response: { data: { uploaded_md_path: string, content_preview: string } }

POST   /documents/{docId}/review/save    Save in-browser edits
  Body: { content: string }
  Response: { data: { edited_md_path: string } }

POST   /documents/{docId}/review/approve Approve document for indexing
  Body: { selected_parse_variant_id: string, selected_norm_variant_id: string | null, notes?: string }
  Response: { data: Document }  (status → REVIEW_APPROVED)

POST   /documents/{docId}/trigger-normalize  Trigger late normalization
  Body: { models: NormModelConfig[] }
  Response: { data: Document }  (status → NORMALIZE_PENDING)

POST   /documents/{docId}/retry-parse        Retry failed parse variant
  Body: { parse_variant_id: string }
  Response: { data: ParseVariant }

POST   /documents/{docId}/retry-normalize    Retry failed norm variant
  Body: { norm_variant_id: string }
  Response: { data: NormVariant }

POST   /documents/{docId}/retry-chunking     Retry failed chunking
  Response: { data: Document }
```

### 7.3 Chunks

```
GET    /chunks                           List chunks (paginated)
  Query: document_id?, batch_id?, search?, page=1, limit=25
  Response: { data: { items: ChunkRecord[], total: number } }

GET    /chunks/{chunkId}                 Single chunk
  Response: { data: ChunkRecord }
```

### 7.4 Logs

```
GET    /logs                             Paginated log viewer
  Query: batch_id?, document_id?, parse_variant_id?, norm_variant_id?,
         level?, stage?, from_ts?, to_ts?, search?, page=1, limit=50
  Response: { data: { items: JobLog[], total: number } }

GET    /logs/failed-jobs                 All failed job summaries
  Query: batch_id?, stage?, from_ts?, to_ts?, page=1, limit=25
  Response: { data: { items: FailedJobSummary[], total: number } }

interface FailedJobSummary {
  document_id: string;
  document_filename: string;
  batch_id: string;
  batch_name: string;
  stage: PipelineStage;
  error_message: string;
  failed_at: string;
  parse_variant_id?: string;
  norm_variant_id?: string;
  retry_endpoint: string;  // URL to POST to retry
}
```

### 7.5 Notifications

```
GET    /notifications                    All notifications (paginated)
  Query: unread_only?, page=1, limit=100
  Response: { data: { items: Notification[], unread_count: number } }

PATCH  /notifications/{id}/read          Mark single notification read
  Response: { data: Notification }

POST   /notifications/mark-all-read      Mark all read
  Response: { data: { updated: number } }

DELETE /notifications/{id}               Dismiss notification
  Response: { data: { deleted: true } }
```

### 7.6 SSE

```
GET    /events                           Server-Sent Events stream
  Headers: Accept: text/event-stream
  Auth: Bearer token (required)

  Event types emitted:
    batch_progress     → BatchProgressEvent
    document_update    → DocumentUpdateEvent
    job_error          → JobErrorEvent
    notification       → Notification

  Heartbeat: ping every 30s to prevent connection timeout
  On reconnect: client automatically reconnects (EventSource behaviour)
  On reconnect: backend sends current state summary for active batches
```

---

## §8 Error Recovery Flows

### Upload Failure

```
Scenario: Admin uploads 3 files, file #2 fails

Detection: Upload API returns per-file status in response

Response:
  file #1: { status: 'uploaded', document_id: '...' }
  file #2: { status: 'failed', error: 'Corrupted file detected' }
  file #3: { status: 'uploaded', document_id: '...' }

UI:
  File #2 row shows red error badge + [Retry] + [Remove] buttons
  "Save Draft" creates batch with files #1 and #3 only
  Notification: "Batch created. 1 file failed to upload."
```

### Parse Failure Recovery

```
Scenario: PLASMA_OPS.pdf, docling parse fails

Backend actions (automatic):
  1. ParseVariant.status = FAILED
  2. ParseVariant.error_message = "Cannot decode page 47"
  3. Document.error_summary = "Parse failed (docling)"
  4. JobLog written at ERROR level
  5. SSE event: document_update (PARSE_FAILED)
  6. Notification: "PLASMA_OPS — Parse Failed"

UI shows:
  Document row: [PARSE_FAILED] badge
  docling variant: FAILED + [View Error] + [Retry Parse (docling)]
  pymupdf4llm variant: COMPLETE (unaffected)

Recovery path:
  Admin clicks [Retry Parse (docling)]
  → POST /api/v1/documents/{id}/retry-parse { parse_variant_id: "..." }
  → Variant re-queued: FAILED → PENDING → RUNNING
  → Other variants untouched
```

### Normalization Failure Recovery (Requirement 7)

```
Scenario: qwen3-70b normalization fails for TOKAMAK_MANUAL

Backend actions (from §4.5 — synchronous):
  1. Partial normalized.md deleted from disk
  2. NormVariant.normalized_md_path = null
  3. NormVariant.status = FAILED, failure_mode = COMPLETE_FAILURE
  4. Document.status = PARSE_COMPLETE (REVERT — parse data safe)
  5. Document.error_summary = "Normalization failed: Connection timeout"
  6. JobLog written at ERROR
  7. SSE event: document_update (PARSE_COMPLETE)
  8. Notification: "TOKAMAK_MANUAL — Normalization Failed, parse data intact"

UI shows:
  Document status: PARSE_COMPLETE (reverted)
  qwen3-70b NormVariant: FAILED
  Error card: "Normalization failed — parse data is preserved"
  Options shown:
    [Retry Normalization (qwen3-70b)]
    [Proceed to Review without normalization]

Recovery Option A (retry):
  Admin clicks [Retry Normalization]
  → Re-queues only the failed NormVariant
  → ParseVariant untouched throughout

Recovery Option B (skip normalization):
  Admin clicks [Proceed to Review without normalization]
  → Document: PARSE_COMPLETE → REVIEW_PENDING
  → Review page loads with parsed.md as base
```

### Chunking Failure Recovery

```
Scenario: TOKAMAK_MANUAL chunking fails mid-way

Backend actions (automatic):
  1. Delete all Qdrant points for this document_id (cleanup partial index)
  2. Document.status = CHUNK_FAILED
  3. Document.chunk_count = null
  4. JobLog at ERROR
  5. Notification: "TOKAMAK_MANUAL — Indexing Failed"

UI shows:
  Document: [CHUNK_FAILED] badge + [Retry Chunking] button
  review_approved_md is untouched

Recovery:
  Admin clicks [Retry Chunking]
  → Qdrant cleanup + re-chunking from same review_approved_md
  → Idempotent
```

---

## §9 Implementation Order

### Phase 1 — Foundation (Days 1–2)

```
1. Initialize Next.js 15 project (strict TypeScript, Tailwind v4, shadcn/ui)
2. Create all TypeScript types in lib/types/index.ts (from §2)
3. Build DashboardLayout: sidebar + topbar shell (no content)
4. Create BellIcon component wired to NotificationStore (no data yet)
5. Implement useSSE hook (connect, parse events, no-op handlers)
6. Set up TanStack Query client in root layout
7. Implement api/client.ts (base fetch with auth headers + error normalization)
```

### Phase 2 — Upload & Config (Days 3–4)

```
8.  Build F01 Upload page (drop zone, file list, batch name input)
9.  Build F02 Advanced Config page (batch defaults form + per-doc overrides)
10. Wire to backend: POST /batches, PATCH /batches/{id}/config, POST /batches/{id}/submit
11. Add Zod validation schemas for both forms
```

### Phase 3 — Parsing UI (Days 5–6)

```
12. Build Batch Detail page with document list
13. Build ParseVariantCard component (status, files, timing)
14. Build VariantPreviewDrawer (MD preview + download button)
15. Wire retry parse endpoint
16. Wire SSE → document status updates → React Query invalidation
17. Build VariantCountBadge (shows "2 parsers × 2 models = 4 variants")
```

### Phase 4 — Normalization UI (Days 7–8)

```
18. Build NormVariantCard (status, model, endpoint, time_taken_ms)
19. Build side-by-side variant comparison layout (F04, F06)
20. Wire retry normalization endpoint
21. Wire normalization failure state (shows "parse data intact" message)
22. Wire normalization success → variant appears in comparison
```

### Phase 5 — Review Stage (Days 9–11)

```
23. Build Review page layout (3-step structure)
24. Build VariantSelector (parse × norm matrix with radio buttons)
25. Build ReviewEditor (CodeMirror 6 + markdown mode)
26. Build FileActions (download buttons per file type)
27. Build file upload flow (replace MD)
28. Build LateNormTrigger component (trigger from review + inline progress)
29. Wire Approve button + post-approval navigation
```

### Phase 6 — Monitoring (Days 12–13)

```
30. Build Monitoring page (active batches, progress bars, recent failures, completed today)
31. Build BatchProgressBar component
32. Wire SSE → live updates on monitoring page
33. Build failed jobs section/tab
34. Wire notification SSE → NotificationStore → bell icon count
35. Build NotificationPanel (slide-down from bell icon)
```

### Phase 7 — Warehouse & Chunks (Days 14–15)

```
36. Build Document Warehouse page (table, filters, file badges, shortcuts)
37. Build Chunks Viewer page (list, search, expand, filters)
38. Wire both to their respective GET endpoints
```

### Phase 8 — Logs & History (Days 16–17)

```
39. Build Logs page (viewer, filters, expandable tracebacks)
40. Build Failed Jobs tab in logs
41. Build Batch History list page
42. Build Batch Detail timeline + per-doc breakdown
43. Download Batch Report button
```

### Phase 9 — Integration & Hardening (Days 18–20)

```
44. Full state machine integration test: upload → parse → norm → review → chunk → index
45. Test all failure modes: each step, partial failures, retries
46. Test file cleanup after review approval (verify invariants in §4.4)
47. Test normalization failure rollback (verify §4.5 invariants)
48. Test late normalization trigger from review stage
49. Test multiple parser variants + multiple norm variants selection flow
50. Test SSE reconnection after server restart
51. Verify notification hydration on page refresh
52. Accessibility pass (keyboard navigation, ARIA labels)
53. Loading and empty states for all pages
```

---

## §10 Non-Negotiable Requirements

These are hard constraints that the coding agent must NEVER violate:

```
1. TypeScript `any` is forbidden. Use `unknown` and type guards instead.

2. Every async operation that can fail MUST have a catch handler.
   No unhandled promise rejections.

3. Every pipeline step that fails MUST:
   a. Write to JobLog at ERROR level
   b. Update document.error_summary
   c. Emit SSE job_error event
   d. Create Notification of ERROR type
   All four — not three out of four.

4. Normalization failure MUST revert document.status to PARSE_COMPLETE.
   The backend MUST verify parse variant files exist before emitting revert.

5. File cleanup after review approval MUST be logged.
   Every deleted file gets a JobLog entry at INFO level.

6. Chunking is always idempotent.
   It MUST delete existing Qdrant points before inserting new ones.

7. The review editor MUST NOT lose content on page refresh.
   Use useEffect + localStorage as a draft autosave (separate from server save).

8. SSE connection MUST auto-reconnect.
   Use EventSource (native) which reconnects automatically.
   Add a visual indicator ("reconnecting...") if connection drops > 5 seconds.

9. All file downloads use Content-Disposition: attachment headers.
   No new tabs. No blob URL memory leaks (revoke after download).

10. Never show raw server error messages to the user.
    Map them through a user-friendly error message layer.
    Log the raw error in the browser console.
```
