import { getAdminCsrfHeaders } from './auth';

export interface Artifact {
  artifact_id: string;
  document_id: string;
  variant_id?: string | null;
  normalization_id?: string | null;
  artifact_type: 'source' | 'raw' | 'parsed' | 'normalized' | 'approved' | string;
  path: string;
  checksum: string;
  size_bytes: number;
  surviving: boolean;
  created_at: string;
  metadata?: Record<string, unknown>;
}

export interface ParserVariant {
  variant_id: string;
  document_id: string;
  parser_name: string;
  status: string;
  raw_artifact_id?: string;
  parsed_artifact_id?: string;
  diagnostics?: Record<string, unknown>;
  duration_ms: number;
  completed_at?: string;
  error?: string;
  pruned: boolean;
}

export interface NormalizationRun {
  normalization_id: string;
  variant_id: string;
  document_id: string;
  status: string;
  normalized_artifact_id?: string;
  model: string;
  endpoint: string;
  duration_ms: number;
  manifest?: Record<string, unknown>;
  error?: string;
  pruned: boolean;
}

export interface AdminDocument {
  document_id: string;
  batch_id: string;
  filename: string;
  rel_path: string;
  folder: string;
  state: string;
  selected_variant_id?: string | null;
  approved_artifact_id?: string | null;
  parser_modes: string[];
  llm_normalize: boolean | number;
  size_bytes: number;
  created_at: string;
  updated_at: string;
  indexed_at?: string | null;
  last_error: string;
  artifacts: Artifact[];
  parser_variants: ParserVariant[];
  normalization_runs: NormalizationRun[];
}

export interface Batch {
  batch_id: string;
  status: string;
  folder: string;
  parser_modes: string[];
  llm_normalize: boolean;
  auto_accept: boolean;
  review_required: boolean;
  created_at: string;
  updated_at: string;
  completed_at?: string | null;
  total_duration_ms: number;
  last_error: string;
  config?: Record<string, unknown>;
  documents?: AdminDocument[];
}

export interface Job {
  job_id: string;
  batch_id?: string | null;
  document_id?: string | null;
  job_type: string;
  status: string;
  stage: string;
  detail: string;
  progress: number;
  error: string;
  created_at: string;
  started_at?: string | null;
  completed_at?: string | null;
  duration_ms: number;
  cancellable: boolean;
  cancel_requested: boolean;
  requested?: Record<string, unknown>;
  result?: Record<string, unknown>;
}

export interface NotificationItem {
  notification_id: string;
  batch_id?: string | null;
  document_id?: string | null;
  job_id?: string | null;
  tone: string;
  title: string;
  detail: string;
  progress: number;
  created_at: string;
  dismissed: number;
}

export interface ChunkItem {
  chunk_id: string;
  index: number;
  text: string;
  metadata: Record<string, unknown>;
  parser: string;
  section_path: string;
  page_range: string;
}

async function requestJson<T>(path: string, init: RequestInit = {}): Promise<T> {
  const method = init.method || 'GET';
  const headers = new Headers(init.headers);
  if (!headers.has('Content-Type') && init.body && typeof init.body === 'string') {
    headers.set('Content-Type', 'application/json');
  }
  if (!['GET', 'HEAD'].includes(method.toUpperCase())) {
    Object.entries(getAdminCsrfHeaders()).forEach(([key, value]) => headers.set(key, String(value)));
  }

  const res = await fetch(`/api/admin${path}`, {
    ...init,
    headers,
    credentials: 'include',
    cache: 'no-store',
  });
  const contentType = res.headers.get('content-type') || '';
  const data = contentType.includes('application/json') ? await res.json() : await res.text();
  if (!res.ok) {
    const message = typeof data === 'object' && data && 'detail' in data ? String((data as { detail: unknown }).detail) : 'Request failed';
    throw new Error(message);
  }
  return data as T;
}

export const adminApi = {
  stats: () => requestJson('/stats'),
  batches: () => requestJson<{ batches: Batch[]; total: number }>('/batches'),
  batch: (batchId: string) => requestJson<{ batch: Batch }>(`/batches/${encodeURIComponent(batchId)}`),
  saveBatchConfig: (
    batchId: string,
    payload: {
      parser_modes: string[];
      llm_normalize: boolean;
      auto_accept?: boolean;
      review_required?: boolean;
      document_overrides?: Record<string, { parser_modes?: string[]; llm_normalize?: boolean }>;
    },
  ) =>
    requestJson<{ success: boolean; batch: Batch }>(`/batches/${encodeURIComponent(batchId)}/config`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  documents: () => requestJson<{ documents: AdminDocument[]; total: number }>('/documents'),
  document: (documentId: string) => requestJson<{ document: AdminDocument }>(`/documents/${encodeURIComponent(documentId)}`),
  saveDocumentConfig: (documentId: string, parserModes: string[], llmNormalize: boolean) =>
    requestJson<{ success: boolean; document: AdminDocument }>(`/documents/${encodeURIComponent(documentId)}/config`, {
      method: 'POST',
      body: JSON.stringify({ parser_modes: parserModes, llm_normalize: llmNormalize }),
    }),
  jobs: () => requestJson<{ jobs: Job[] }>('/jobs'),
  notifications: () => requestJson<{ notifications: NotificationItem[] }>('/notifications'),
  dismissNotification: (id: string) => requestJson(`/notifications/${encodeURIComponent(id)}/dismiss`, { method: 'POST' }),
  parseDocument: (documentId: string, parserModes?: string[]) =>
    requestJson<{ success: boolean; job_id: string }>(`/documents/${encodeURIComponent(documentId)}/parse`, {
      method: 'POST',
      body: JSON.stringify(parserModes ? { parser_modes: parserModes } : {}),
    }),
  parseBatch: (batchId: string, parserModes?: string[], documentIds?: string[]) =>
    requestJson<{ success: boolean; job_id: string }>(`/batches/${encodeURIComponent(batchId)}/parse`, {
      method: 'POST',
      body: JSON.stringify({ parser_modes: parserModes, document_ids: documentIds }),
    }),
  normalize: (documentId: string, variantId: string) =>
    requestJson<{ success: boolean; job_id: string }>(`/documents/${encodeURIComponent(documentId)}/normalize`, {
      method: 'POST',
      body: JSON.stringify({ variant_id: variantId }),
    }),
  approve: (documentId: string, variantId: string, artifactId?: string, content?: string) =>
    requestJson<{ success: boolean; job_id?: string }>(`/documents/${encodeURIComponent(documentId)}/approve`, {
      method: 'POST',
      body: JSON.stringify({ variant_id: variantId, artifact_id: artifactId, content, index_immediately: true }),
    }),
  updateArtifact: (artifactId: string, content: string) =>
    requestJson(`/artifacts/${encodeURIComponent(artifactId)}/content`, {
      method: 'PUT',
      body: JSON.stringify({ content }),
    }),
  artifactText: async (artifactId: string) => {
    const res = await fetch(`/api/admin/artifacts/${encodeURIComponent(artifactId)}`, {
      credentials: 'include',
      cache: 'no-store',
    });
    if (!res.ok) throw new Error('Failed to load artifact');
    return res.text();
  },
  uploadReviewFile: (documentId: string, variantId: string, file: File) => {
    const form = new FormData();
    form.append('variant_id', variantId);
    form.append('file', file);
    return requestJson<{ artifact: Artifact }>(`/documents/${encodeURIComponent(documentId)}/review-upload`, {
      method: 'POST',
      body: form,
      headers: getAdminCsrfHeaders(),
    });
  },
  chunks: (documentId: string, page = 1, limit = 20) =>
    requestJson<{ chunks: ChunkItem[]; total: number; page: number; limit: number }>(
      `/documents/${encodeURIComponent(documentId)}/chunks?page=${page}&limit=${limit}`,
    ),
  vectorStats: () => requestJson('/vector/stats'),
  probe: (query: string, topK: number, documentId?: string) =>
    requestJson('/retrieval/probe', {
      method: 'POST',
      body: JSON.stringify({ query, top_k: topK, document_id: documentId || undefined }),
    }),
};

export const parserModes = ['auto', 'docling', 'pymupdf', 'pymupdf4llm', 'docling_vision', 'vision_llm'];
