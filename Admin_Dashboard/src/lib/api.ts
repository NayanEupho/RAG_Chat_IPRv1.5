import type {
  AdminDocument,
  AdminStats,
  Batch,
  ChunkRecord,
  JobLog,
  LlmEndpoint,
  NotificationItem,
  PageResult
} from "./types";

interface ApiEnvelope<T> {
  data: T;
  error: string | null;
  detail?: string;
}

const API_BASE = process.env.NEXT_PUBLIC_ADMIN_API_BASE || "http://localhost:8000/api/v1";

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    cache: "no-store"
  });
  const contentType = response.headers.get("content-type") || "";
  const payload = contentType.includes("application/json")
    ? ((await response.json()) as ApiEnvelope<T>)
    : ({ data: (await response.text()) as T, error: null } satisfies ApiEnvelope<T>);

  if (!response.ok || payload.error) {
    throw new Error(payload.detail || payload.error || "Request failed");
  }
  return payload.data;
}

export const adminApi = {
  stats: () => request<AdminStats>("/stats"),
  vectorStats: () => request<AdminStats>("/vector/stats"),
  batches: () => request<PageResult<Batch>>("/batches?limit=50"),
  batch: (batchId: string) => request<Batch>(`/batches/${encodeURIComponent(batchId)}`),
  submitBatch: (batchId: string) =>
    request<Batch>(`/batches/${encodeURIComponent(batchId)}/submit`, { method: "POST" }),
  documents: (query = "") => request<PageResult<AdminDocument>>(`/documents?limit=100${query}`),
  chunks: (query = "") => request<PageResult<ChunkRecord>>(`/chunks?limit=50${query}`),
  logs: (query = "") => request<PageResult<JobLog>>(`/logs?limit=100${query}`),
  notifications: () => request<PageResult<NotificationItem>>("/notifications?limit=100"),
  llmEndpoints: () => request<PageResult<LlmEndpoint>>("/settings/llm-endpoints"),
  saveLlmEndpoint: (payload: { model_id: string; endpoint: string; display_name: string; enabled: boolean }) =>
    request<LlmEndpoint>("/settings/llm-endpoints", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    }),
  markAllNotificationsRead: () => request<{ updated: number }>("/notifications/mark-all-read", { method: "POST" }),
  createBatch: (form: FormData) => request<Batch>("/batches", { method: "POST", body: form }),
  selectVariant: (documentId: string, parseVariantId: string, normVariantId: string | null) =>
    request<Record<string, unknown>>(`/documents/${encodeURIComponent(documentId)}/select-variant`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ parse_variant_id: parseVariantId, norm_variant_id: normVariantId })
    }),
  approve: (documentId: string, parseVariantId: string, normVariantId: string | null) =>
    request<Record<string, unknown>>(`/documents/${encodeURIComponent(documentId)}/review/approve`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ selected_parse_variant_id: parseVariantId, selected_norm_variant_id: normVariantId })
    }),
  retryParse: (documentId: string, parseVariantId: string) =>
    request<Record<string, unknown>>(`/documents/${encodeURIComponent(documentId)}/retry-parse`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ parse_variant_id: parseVariantId })
    }),
  retryChunking: (documentId: string) =>
    request<Record<string, unknown>>(`/documents/${encodeURIComponent(documentId)}/retry-chunking`, { method: "POST" })
};

export function adminEventsUrl(): string {
  return `${API_BASE}/events`;
}
