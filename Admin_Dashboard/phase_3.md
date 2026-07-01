# Phase 3 - Dashboard Responsiveness, Vector Probe, and Chunk Inspection

## Goals

- Make section switching feel immediate without showing stale cached data after ingestion, review, delete, cancel, or warehouse updates.
- Make dashboard data loading faster by prefetching route data and avoiding duplicated in-flight requests.
- Keep SSE as the source of truth for state invalidation so hidden pages do not reuse stale cache when revisited.
- Make Vector Stats warnings actionable for retrieval/debugging.
- Fix Vector Probe so it returns chunk cards and model context instead of Chroma embedding-shape errors.
- Extend Chunk Viewer to inspect both admin-ingested chunks and legacy filesystem-ingested Chroma chunks.

## Implemented Fixes

### Frontend Data Freshness and Navigation

- Added stale-aware shared admin data cache in `src/components/use-admin-data.ts`.
- Added global cache invalidation from SSE events, including wildcard keys such as `chunks:*`.
- Added request de-duping so multiple pages/prefetches do not issue the same request concurrently.
- Added route data prefetch in `src/components/app-shell.tsx` on sidebar hover, focus, and pointer-down.
- Narrowed SSE invalidation by event type so unrelated heavy pages are not refetched after every event.

### Vector Warnings

- `mirror_mismatch` now includes:
  - What the mismatch means.
  - Impact on retrieval/final answer generation.
  - Recommended remediation.
- Meaning:
  - Chroma is the retrieval source of truth.
  - The admin mirror is the dashboard-side SQLite copy for admin-ingested chunks.
  - Legacy watcher ingestions and older documents may exist in Chroma without matching rows in `admin_chunks`.
- Retrieval impact:
  - Retrieval and answer generation can still use Chroma chunks.
  - The mismatch mainly affects admin inspection/statistics if the admin mirror is incomplete.
- Recommended action:
  - Keep Chroma as retrieval truth.
  - Backfill or rebuild the admin chunk mirror only when complete dashboard-side inspection is required.

### Vector Probe

- Fixed the embedding shape passed into Chroma.
- Root cause:
  - The shared retriever embedding helper returns Chroma-ready nested embeddings for most callers.
  - Vector Probe wrapped that result again, producing `[[[...]]]`.
  - Chroma expects `[[...]]`, so it returned the long "Expected embeddings..." error.
- Fix:
  - Added local probe embedding normalization in `backend/admin/vector_inspector.py`.
  - Kept the shared retriever embedding helper unchanged to avoid affecting retrieval latency or behavior.

### Chunk Viewer

- Chunk Viewer now includes both admin and legacy indexed documents.
- Admin documents still use the SQLite admin chunk mirror.
- Legacy documents now use Chroma-backed chunk reads filtered by source/filename/doc type.
- This makes legacy filesystem-ingested documents inspectable without requiring them to have admin dashboard document IDs.

### Admin Chunk Source Labels

- Fixed admin review-approved chunk labels from `approved.md` to the original source markdown name.
- Example:
  - Before: `[Doc: approved.md | Section: ...]`
  - After: `[Doc: Lora Paper.md | Section: ...]`
- This improves chunk context passed to the agent without changing the source PDF filename metadata.

### Router Type Warning

- Fixed static type warnings in `backend/admin/router.py`.
- `BatchConfig.default_parsers` now receives `ParserType(parser)`.
- `BatchConfig.default_ingestion_type` now receives `IngestionType(default_ingestion_type)`.
- Runtime behavior is unchanged because `model_dump(mode="json")` still stores JSON strings.

## Tests Added or Updated

- Vector probe test now verifies nested embedding output is passed to Chroma without an extra wrapper.
- Vector stats warning test now verifies the warning includes retrieval impact text.
- Chroma chunk inventory test verifies legacy chunks are returned as chunk-card-ready records.
- Admin chunk label test verifies `approved.md` is rewritten to the original source markdown filename.

## Remaining Backend Efficiency Work

Ranked by impact and ease:

1. Defer backend model/reranker warmup until after `/health` is available.
2. Materialize warehouse inventory instead of rebuilding from Chroma plus filesystem scans on cold loads.
3. Replace repeated filesystem inventory scans with persisted counters and event-driven invalidation.
4. Add lightweight batch summary endpoints and fetch full document/variant trees only on row expansion.
5. Avoid refreshing Chroma collection handles on every read unless the collection was reset.
6. Add a shared ingestion resource scheduler for admin worker and legacy watcher contention.
