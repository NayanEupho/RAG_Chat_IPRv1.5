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
  | "CHUNK_PENDING"
  | "CHUNK_RUNNING"
  | "CHUNK_FAILED"
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
  | "FAILED";

export type VariantStatus = "PENDING" | "RUNNING" | "COMPLETE" | "FAILED";

export interface NormModelConfig {
  model_id: string;
  endpoint: string;
  display_name: string;
}

export interface EffectiveDocConfig {
  parsers: string[];
  normalization_enabled: boolean;
  normalization_models: NormModelConfig[];
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
  status: "PENDING" | "IN_PROGRESS" | "APPROVED";
  opened_at: string | null;
  approved_at: string | null;
  notes: string | null;
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
}

export interface NotificationItem {
  notification_id: string;
  type: string;
  title: string;
  message: string;
  detail: string | null;
  read: boolean;
  created_at: string;
}

export interface ChunkRecord {
  chunk_id: string;
  document_id: string;
  batch_id: string;
  content: string;
  chunk_index: number;
  section_path: string | null;
  page_numbers: number[];
  token_count: number;
  char_count: number;
  embedding_model: string;
  indexed_at: string;
  chroma_id: string;
}

export interface PageResult<T> {
  items: T[];
  total: number;
  page?: number;
  unread_count?: number;
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
  error?: string;
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
  };
  embedding: {
    model_id: string | null;
    endpoint: string | null;
    display_name: string;
  };
  parsing_mode: string;
  vision: {
    model_id: string | null;
    endpoint: string | null;
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
