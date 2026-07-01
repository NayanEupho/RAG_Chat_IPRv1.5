export type DocumentStatus =
  | "UPLOADED"
  | "PARSE_PENDING"
  | "PARSE_RUNNING"
  | "PARSE_FAILED"
  | "PARSE_COMPLETE"
  | "NORMALIZE_PENDING"
  | "NORMALIZE_RUNNING"
  | "NORMALIZE_FAILED"
  | "NORMALIZE_COMPLETE"
  | "REVIEW_PENDING"
  | "REVIEW_IN_PROGRESS"
  | "REVIEW_APPROVED"
  | "REVIEW_REJECTED"
  | "CHUNK_PENDING"
  | "CHUNK_RUNNING"
  | "CHUNK_FAILED"
  | "CANCELLED"
  | "INDEXED";

export type BatchStatus =
  | "DRAFT"
  | "SUBMITTED"
  | "PARSING"
  | "NORMALIZING"
  | "REVIEW_PENDING"
  | "REVIEWING"
  | "CHUNKING"
  | "PARTIALLY_COMPLETE"
  | "COMPLETE"
  | "FAILED"
  | "CANCELLED";

export type VariantStatus = "PENDING" | "RUNNING" | "COMPLETE" | "FAILED";
export type IngestionType = "general" | "qna";

export interface NormModelConfig {
  model_id: string;
  endpoint: string;
  display_name: string;
}

export interface EffectiveDocConfig {
  parsers: string[];
  normalization_enabled: boolean;
  normalization_models: NormModelConfig[];
  ingestion_type: IngestionType;
  review_required?: boolean;
}

export interface NormVariant {
  norm_variant_id: string;
  parse_variant_id: string;
  document_id: string;
  model_config: NormModelConfig;
  status: VariantStatus;
  failure_mode: string | null;
  normalized_md_path: string | null;
  time_taken_ms: number | null;
  started_at: string | null;
  completed_at: string | null;
  error_message: string | null;
  error_detail: string | null;
  is_selected_for_review: boolean;
}

export interface ParseVariant {
  variant_id: string;
  document_id: string;
  parser_type: string;
  status: VariantStatus;
  raw_md_path: string | null;
  parsed_md_path: string | null;
  started_at: string | null;
  completed_at: string | null;
  duration_ms: number | null;
  error_message: string | null;
  error_detail: string | null;
  norm_variants: NormVariant[];
  is_selected_for_review: boolean;
}

export interface ReviewRecord {
  review_id: string;
  document_id: string;
  selected_parse_variant_id: string;
  selected_norm_variant_id: string | null;
  base_md_path: string;
  edited_md_path: string | null;
  uploaded_md_path: string | null;
  review_approved_md_path: string | null;
  status: "PENDING" | "IN_PROGRESS" | "APPROVED" | "REJECTED";
  opened_at: string | null;
  approved_at: string | null;
  notes: string | null;
  review_action?: {
    action?: string;
    reason?: string | null;
    timestamp?: string;
    review_required?: boolean;
    llm_normalized?: boolean;
    edited?: boolean;
    replaced?: boolean;
    cleanup_completed?: boolean;
    cleanup_errors?: string[];
    deleted_artifacts?: Record<string, string | null>;
    review_approved_md_path?: string;
    final_review_target_path?: string;
  } | null;
}

export interface CanonicalFiles {
  source_file_path: string;
  raw_md_path: string;
  parsed_md_path: string;
  normalized_md_path: string | null;
  review_approved_md_path: string;
  normalization_metadata: Record<string, unknown> | null;
}

export interface AdminDocument {
  document_id: string;
  batch_id: string;
  original_filename: string;
  source_file_path: string;
  file_type: "pdf" | "docx";
  file_size_bytes: number;
  effective_config: EffectiveDocConfig;
  ingestion_type: IngestionType;
  status: DocumentStatus;
  parse_variants: ParseVariant[];
  review: ReviewRecord | null;
  canonical_files: CanonicalFiles | null;
  chunk_count: number | null;
  indexed_at: string | null;
  uploaded_at: string;
  error_summary: string | null;
}

export interface Batch {
  batch_id: string;
  name: string;
  description: string | null;
  status: BatchStatus;
  config: Record<string, unknown>;
  ingestion_label: "general_docs" | "qna_docs" | "mix";
  documents?: AdminDocument[];
  total_documents: number;
  documents_indexed: number;
  documents_failed: number;
  documents_in_progress: number;
  documents_pending_review: number;
  created_at: string;
  submitted_at: string | null;
  completed_at: string | null;
  total_duration_ms: number | null;
  last_error: string | null;
}

export interface JobLog {
  log_id: string;
  batch_id: string | null;
  document_id: string | null;
  stage: string;
  level: "DEBUG" | "INFO" | "WARN" | "ERROR";
  message: string;
  detail: string | null;
  timestamp: string;
  job_id?: string | null;
  parse_variant_id?: string | null;
  norm_variant_id?: string | null;
}

export interface NotificationItem {
  notification_id: string;
  type: string;
  batch_id?: string | null;
  document_id?: string | null;
  job_id?: string | null;
  title: string;
  message: string;
  detail: string | null;
  read: boolean;
  created_at: string;
}

export interface ChunkRecord {
  chunk_id: string;
  document_id: string | null;
  batch_id: string | null;
  content: string;
  chunk_index: number;
  section_path: string | null;
  page_numbers: number[];
  token_count: number;
  char_count: number;
  embedding_model: string;
  indexed_at: string;
  chroma_id: string;
  filename?: string | null;
  source_path?: string | null;
  doc_type?: string | null;
  origin?: "admin" | "legacy";
  metadata?: Record<string, unknown>;
}

export interface VectorStatsDetail {
  healthy: boolean;
  error?: string | null;
  latency_ms: number;
  indexed_documents: number;
  admin_documents: number;
  legacy_documents: number;
  chroma_chunks: number | null;
  mirrored_admin_chunks: number;
  avg_chunks_per_document: number;
  avg_tokens_per_chunk: number;
  avg_chars_per_chunk: number;
  total_tokens: number;
  total_chars: number;
  doc_type_breakdown: Record<string, number>;
  embedding_models: Array<{ embedding_model: string; chunks: number }>;
  warnings: Array<{ type: string; message: string; impact?: string; recommendation?: string }>;
}

export interface VectorProbeChunk {
  rank?: number;
  rerank_rank?: number;
  chunk_id: string;
  content: string;
  metadata: Record<string, unknown>;
  distance?: number | null;
  similarity?: number | null;
  rerank_score?: number | null;
  filename?: string | null;
  document_id?: string | null;
  batch_id?: string | null;
  chunk_index?: number | null;
  doc_type?: string | null;
}

export interface VectorProbeResult {
  query: string;
  filters: { document_id?: string | null; filename?: string | null; doc_type?: string | null };
  top_k: number;
  candidate_k: number;
  embedding_model: string;
  rerank_enabled: boolean;
  reranker_model?: string | null;
  latency_ms: number;
  embedding_ms: number;
  vector_ms: number;
  rerank_ms?: number | null;
  candidates: VectorProbeChunk[];
  final_chunks: VectorProbeChunk[];
  model_context: string;
}

export interface PageResult<T> {
  items: T[];
  total: number;
  page?: number;
  unread_count?: number;
}

export interface IndexedWarehouseDocument {
  id: string;
  origin: "admin" | "legacy";
  document_id: string | null;
  filename: string;
  source_path: string;
  safe_source_path: string | null;
  status: "INDEXED";
  chunk_count: number;
  parser: string | null;
  doc_type: IngestionType;
  ingestion_type: IngestionType;
  batch_id: string | null;
  indexed_at: string;
  file_size_bytes: number;
  downloads?: {
    source: boolean;
    raw?: boolean;
    parsed: boolean;
    normalized: boolean;
    final: boolean;
  };
}

export interface AdminStats {
  batches: number;
  documents: number;
  indexed_documents: number;
  chunks: number;
  failed_jobs: number;
  unread_notifications: number;
  total_tokens: number;
  total_chars: number;
  healthy?: boolean;
  chroma_count?: number | null;
  retrieval_chunks?: number | null;
  error?: string;
  vector_error?: string;
  filesystem?: InventorySummary;
}

export interface LlmEndpoint {
  endpoint_id: string;
  model_id: string;
  endpoint: string;
  display_name: string;
  enabled: boolean;
  created_at: string;
  updated_at: string;
}

export interface AdminEvent {
  type: string;
  data?: unknown;
  batch_id?: string;
  document_id?: string;
  status?: string;
  message?: string;
}

export interface RuntimeConfig {
  normalization: {
    enabled: boolean;
    model_id: string | null;
    endpoint: string | null;
    display_name: string;
    engine?: string;
    configured?: boolean;
  };
  embedding: {
    model_id: string | null;
    endpoint: string | null;
    display_name: string;
    engine?: string;
    configured?: boolean;
  };
  models?: Array<{
    role: string;
    model_id: string | null;
    endpoint: string | null;
    display_name: string;
    engine: string;
    configured: boolean;
    health_status?: "online" | "offline" | "unknown";
    health_error?: string | null;
    health_latency_ms?: number | null;
    health_cached?: boolean;
    health_checked_at?: string | null;
  }>;
  parsing_mode: string;
  parser_options: Array<{
    value: string;
    label: string;
    description: string;
    available: boolean;
  }>;
  vision: {
    model_id: string | null;
    endpoint: string | null;
    engine?: string;
    configured?: boolean;
  };
}

export interface InventorySummary {
  source_files: number;
  generated_files: number;
  artifact_runs: number;
  pdf_files: number;
  markdown_files: number;
  chunk_files: number;
}

export interface InventoryFile {
  id: string;
  kind: "source" | "generated";
  filename: string;
  relative_path: string;
  path: string;
  extension: string;
  size_bytes: number;
  modified_at: number;
}

export interface ArtifactRun {
  id: string;
  kind: "artifact_run";
  document_name: string;
  parser: string;
  relative_path: string;
  path: string;
  modified_at: number;
  files: Record<string, string>;
  manifest: Record<string, unknown>;
  has_chunks: boolean;
  has_normalized: boolean;
  has_selected: boolean;
}

export interface WarehouseInventory {
  source_files: InventoryFile[];
  generated_files: InventoryFile[];
  artifact_runs: ArtifactRun[];
  summary: InventorySummary;
}
