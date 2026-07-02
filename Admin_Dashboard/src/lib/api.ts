import type {
  AdminDocument,
  AdminStats,
  IndexedWarehouseDocument,
  Batch,
  ChunkRecord,
  JobLog,
  LlmEndpoint,
  NotificationItem,
  PageResult,
  RuntimeConfig,
  VectorProbeResult,
  VectorStatsDetail,
  WarehouseInventory
} from "./types";

interface ApiEnvelope<T> {
  data: T;
  error: string | null;
  detail?: string;
}

const CONFIGURED_API_BASE = process.env.NEXT_PUBLIC_ADMIN_API_BASE || "";
const FALLBACK_API_BASE = "/api/admin-backend";
const LOOPBACK_HOSTS = new Set(["localhost", "127.0.0.1", "0.0.0.0", "::1", "[::1]"]);

function isLoopbackHost(hostname: string): boolean {
  return LOOPBACK_HOSTS.has(hostname.toLowerCase());
}

function resolveAdminApiBase(): string {
  const configured = CONFIGURED_API_BASE || FALLBACK_API_BASE;
  if (typeof window === "undefined") return configured.replace(/\/$/, "");
  try {
    const url = new URL(configured, window.location.origin);
    const frontendHost = window.location.hostname;
    const apiHostIsListenAddress = url.hostname === "0.0.0.0";
    const apiHostIsLocalOnly = isLoopbackHost(url.hostname);
    const frontendIsRemote = !isLoopbackHost(frontendHost);
    if (apiHostIsListenAddress || (apiHostIsLocalOnly && frontendIsRemote)) {
      url.hostname = frontendHost;
    }
    return url.toString().replace(/\/$/, "");
  } catch {
    return configured.replace(/\/$/, "");
  }
}

export interface AdminHealth {
  healthy: boolean;
  service: string;
  database: string;
  latency_ms: number;
  checked_at: string;
  error?: string;
}

export interface AdminLoginResult {
  authenticated: boolean;
  email: string;
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${resolveAdminApiBase()}${path}`, {
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
  login: (payload: { email: string; password: string }) =>
    request<AdminLoginResult>("/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    }),
  health: (signal?: AbortSignal) => request<AdminHealth>("/health", { signal }),
  stats: () => request<AdminStats>("/stats"),
  runtimeConfig: () => request<RuntimeConfig>("/runtime-config"),
  vectorStats: () => request<AdminStats>("/vector/stats"),
  vectorStatsDetail: () => request<VectorStatsDetail>("/vector/stats/detail"),
  vectorProbe: (payload: { query: string; top_k: number; candidate_k: number; rerank: boolean; document_id?: string | null; filename?: string | null; doc_type?: string | null }) =>
    request<VectorProbeResult>("/vector/probe", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    }),
  warehouseInventory: () => request<WarehouseInventory>("/warehouse/inventory?limit=500"),
  indexedDocuments: (query = "") => request<PageResult<IndexedWarehouseDocument>>(`/warehouse/indexed-documents?limit=500${query}`),
  batches: (query = "") => request<PageResult<Batch>>(`/batches?limit=50${query}`),
  batch: (batchId: string) => request<Batch>(`/batches/${encodeURIComponent(batchId)}`),
  submitBatch: (batchId: string) =>
    request<Batch>(`/batches/${encodeURIComponent(batchId)}/submit`, { method: "POST" }),
  cancelBatch: (batchId: string) =>
    request<{ cancelled: boolean; batch: Batch; cleanup_errors: string[] }>(`/batches/${encodeURIComponent(batchId)}/cancel`, { method: "POST" }),
  cancelActiveBatches: () =>
    request<{ cancelled: Array<{ cancelled: boolean; batch: Batch; cleanup_errors: string[] }>; errors: Array<{ batch_id: string; error: string }>; total: number }>("/batches/cancel-active", { method: "POST" }),
  updateBatchConfig: (batchId: string, payload: object) =>
    request<Batch>(`/batches/${encodeURIComponent(batchId)}/config`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    }),
  deleteBatch: (batchId: string) =>
    request<{ deleted: boolean }>(`/batches/${encodeURIComponent(batchId)}`, { method: "DELETE" }),
  documents: (query = "") => request<PageResult<AdminDocument>>(`/documents?limit=100${query}`),
  document: (documentId: string) => request<AdminDocument>(`/documents/${encodeURIComponent(documentId)}`),
  reviewContent: (documentId: string, kind: "review" | "parsed" | "normalized" = "review") =>
    request<{ content: string; path: string; kind: "parsed" | "normalized"; editable: boolean }>(
      `/documents/${encodeURIComponent(documentId)}/review/content?kind=${encodeURIComponent(kind)}`
    ),
  saveReview: (documentId: string, content: string) =>
    request<Record<string, unknown>>(`/documents/${encodeURIComponent(documentId)}/review/save`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content })
    }),
  uploadReviewMarkdown: (documentId: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<Record<string, unknown>>(`/documents/${encodeURIComponent(documentId)}/review/upload`, { method: "POST", body: form });
  },
  chunks: (query = "") => request<PageResult<ChunkRecord>>(`/chunks?${query.includes("limit=") ? query.replace(/^[&?]/, "") : `limit=50${query}`}`),
  logs: (query = "") => request<PageResult<JobLog>>(`/logs?limit=100${query}`),
  notifications: () => request<PageResult<NotificationItem>>("/notifications?limit=100"),
  markNotificationRead: (notificationId: string) =>
    request<NotificationItem>(`/notifications/${encodeURIComponent(notificationId)}/read`, { method: "PATCH" }),
  deleteNotification: (notificationId: string) =>
    request<Record<string, unknown>>(`/notifications/${encodeURIComponent(notificationId)}`, { method: "DELETE" }),
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
  reject: (documentId: string, reason: string | null = null) =>
    request<Record<string, unknown>>(`/documents/${encodeURIComponent(documentId)}/review/reject`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reason })
    }),
  bulkApprove: (documentIds: string[], notes: string | null = null) =>
    request<Record<string, unknown>>("/review/bulk/approve", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ document_ids: documentIds, notes })
    }),
  bulkReject: (documentIds: string[], notes: string | null = null) =>
    request<Record<string, unknown>>("/review/bulk/reject", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ document_ids: documentIds, notes })
    }),
  deleteIndexedDocument: (item: { id: string; origin: "admin" | "legacy"; document_id?: string | null }) => {
    const identifier = item.origin === "legacy" ? item.id : item.document_id || item.id;
    const path = item.origin === "legacy" ? `/legacy-documents/${encodeURIComponent(identifier)}` : `/documents/${encodeURIComponent(identifier)}`;
    return request<Record<string, unknown>>(path, { method: "DELETE" });
  },
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
  return `${resolveAdminApiBase()}/events`;
}

export function adminApiBaseUrl(): string {
  return resolveAdminApiBase();
}
