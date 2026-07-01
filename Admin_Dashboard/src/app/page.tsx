"use client";

import Link from "next/link";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { adminApi } from "@/lib/api";
import { compactStatus, formatBytes, formatDate, statusTone } from "@/lib/format";
import { useAdminData } from "@/components/use-admin-data";
import { useAdminEvents } from "@/components/use-admin-events";
import { SkeletonRows, SkeletonStats } from "@/components/loading-state";

const DISMISSED_OVERVIEW_ERRORS_KEY = "rag-admin-overview-dismissed-errors";
const DISMISSED_OVERVIEW_BATCHES_KEY = "rag-admin-overview-dismissed-batches";

function batchTypeLabel(value?: string | null): string {
  if (value === "mix") return "Mix";
  if (value === "qna_docs") return "QnA";
  return "General";
}

function readDismissedSet(key: string): Set<string> {
  if (typeof window === "undefined") return new Set();
  try {
    const parsed = JSON.parse(window.localStorage.getItem(key) || "[]");
    return new Set(Array.isArray(parsed) ? parsed.map(String) : []);
  } catch {
    return new Set();
  }
}

function InfoPopover({ title, children }: { title: string; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  return (
    <span className="info-popover">
      <button
        className="info-button"
        type="button"
        aria-label={title}
        aria-expanded={open}
        onClick={() => setOpen((current) => !current)}
      >
        i
      </button>
      <span className={`info-panel ${open ? "open" : ""}`} role="tooltip">
        <strong>{title}</strong>
        <span>{children}</span>
      </span>
    </span>
  );
}

function MetricLabel({ label, title, children }: { label: string; title: string; children: ReactNode }) {
  return (
    <span className="metric-label">
      {label}
      <InfoPopover title={title}>{children}</InfoPopover>
    </span>
  );
}

function BackendStatusPanel({ status, error, since }: { status: string; error: string | null; since: string | null }) {
  return (
    <div className={`panel backend-state ${status === "down" ? "danger" : "warning"}`}>
      <h2>{status === "down" ? "Backend connection unavailable" : "Reconnecting to backend"}</h2>
      <p>
        {status === "down"
          ? "Overview data is hidden because the dashboard cannot maintain the backend event stream."
          : "Overview data is temporarily hidden while the dashboard reconnects, so stale counts are not shown."}
      </p>
      <pre>{[
        `Status: ${status}`,
        `API events: ${process.env.NEXT_PUBLIC_ADMIN_API_BASE || "http://localhost:8000/api/v1"}/events`,
        since ? `Disconnected since: ${formatDate(since)}` : null,
        error ? `Error: ${error}` : null
      ].filter(Boolean).join("\n")}</pre>
    </div>
  );
}

function modelTone(status?: string): "success" | "danger" | "warning" {
  if (status === "online") return "success";
  if (status === "offline") return "danger";
  return "warning";
}

function modelStatusLabel(status?: string): string {
  if (status === "online") return "Online";
  if (status === "offline") return "Offline";
  return "Checking";
}

export default function OverviewPage() {
  const [dismissedErrorIds, setDismissedErrorIds] = useState<Set<string>>(new Set());
  const [dismissedBatchIds, setDismissedBatchIds] = useState<Set<string>>(new Set());
  const events = useAdminEvents();
  const stats = useAdminData(() => adminApi.stats(), 0, "stats");
  const batches = useAdminData(() => adminApi.batches(), 0, "batches");
  const indexed = useAdminData(() => adminApi.indexedDocuments(), 0, "indexedDocuments");
  const review = useAdminData(() => adminApi.documents("&status=REVIEW_PENDING"), 0, "reviewPending");
  const logs = useAdminData(() => adminApi.logs("&level=ERROR"), 0, "logs");
  const runtime = useAdminData(() => adminApi.runtimeConfig(), 0, "runtimeConfig");

  const activeBatches = (batches.data?.items || []).filter((batch) =>
    ["SUBMITTED", "PARSING", "NORMALIZING", "REVIEW_PENDING", "REVIEWING", "CHUNKING"].includes(batch.status)
  );
  const legacyCount = (indexed.data?.items || []).filter((item) => item.origin === "legacy").length;
  const visibleErrors = useMemo(
    () => (logs.data?.items || []).filter((log) => !dismissedErrorIds.has(log.log_id)),
    [logs.data?.items, dismissedErrorIds]
  );
  const visibleBatches = useMemo(
    () => (batches.data?.items || []).filter((batch) => !dismissedBatchIds.has(batch.batch_id)),
    [batches.data?.items, dismissedBatchIds]
  );
  const backendLoading = events.status === "connecting" || events.status === "reconnecting";
  const backendDown = events.status === "down";

  useEffect(() => {
    setDismissedErrorIds(readDismissedSet(DISMISSED_OVERVIEW_ERRORS_KEY));
    setDismissedBatchIds(readDismissedSet(DISMISSED_OVERVIEW_BATCHES_KEY));
  }, []);

  function clearOverviewErrors() {
    const ids = new Set([...(logs.data?.items || []).map((log) => log.log_id), ...dismissedErrorIds]);
    setDismissedErrorIds(ids);
    window.localStorage.setItem(DISMISSED_OVERVIEW_ERRORS_KEY, JSON.stringify(Array.from(ids)));
  }

  function clearOverviewBatches() {
    const ids = new Set([...(batches.data?.items || []).map((batch) => batch.batch_id), ...dismissedBatchIds]);
    setDismissedBatchIds(ids);
    window.localStorage.setItem(DISMISSED_OVERVIEW_BATCHES_KEY, JSON.stringify(Array.from(ids)));
  }

  return (
    <section className="page">
      <div className="page-header">
        <div>
          <h1>Overview</h1>
          <p>Operational snapshot for ingestion, review, indexed retrieval documents, and recent failures.</p>
        </div>
        <div className="actions">
          <Link className="button primary" href="/ingestion">New batch</Link>
          <Link className="button" href="/monitoring">Open monitoring</Link>
        </div>
      </div>

      {backendDown ? <BackendStatusPanel status={events.status} error={events.lastError} since={events.disconnectedSince} /> : null}

      <div className="grid cols-4">
        {backendLoading || ((stats.loading || indexed.loading || batches.loading || review.loading) && !stats.data && !indexed.data) ? (
          <SkeletonStats count={4} />
        ) : backendDown ? null : (
          <>
            <div className="stat">
              <MetricLabel label="Active batches" title="Active batches">Batches currently submitted, parsing, normalizing, waiting for review, reviewing, chunking, or indexing.</MetricLabel>
              <strong>{activeBatches.length}</strong>
            </div>
            <div className="stat">
              <MetricLabel label="Pending review" title="Pending review">Documents currently waiting for an admin to approve or reject generated markdown before indexing.</MetricLabel>
              <strong>{review.data?.total || 0}</strong>
            </div>
            <div className="stat">
              <MetricLabel label="Indexed documents" title="Indexed documents">Documents currently available in the retrieval layer. This includes admin-ingested and legacy indexed documents.</MetricLabel>
              <strong>{indexed.data?.total || stats.data?.indexed_documents || 0}</strong>
            </div>
            <div className="stat">
              <MetricLabel label="Legacy indexed" title="Legacy indexed">Indexed retrieval documents discovered from the legacy file-watcher path rather than created through this admin dashboard.</MetricLabel>
              <strong>{legacyCount}</strong>
            </div>
          </>
        )}
      </div>

      <div className="grid cols-2">
        <div className="panel">
          <h2>Retrieval Footprint</h2>
          <div className="grid cols-3">
            {backendLoading || (stats.loading && !stats.data) ? (
              <SkeletonStats count={3} />
            ) : backendDown ? (
              <div className="empty-state"><strong>Backend unavailable</strong><span>Retrieval footprint is hidden until the backend reconnects.</span></div>
            ) : (
              <>
                <div className="stat">
                  <MetricLabel label="Chunks" title="Chunks">Vector-store chunk count used by retrieval. This is the closest number to the searchable retrieval footprint.</MetricLabel>
                  <strong>{stats.data?.retrieval_chunks ?? stats.data?.chroma_count ?? stats.data?.chunks ?? 0}</strong>
                </div>
                <div className="stat">
                  <MetricLabel label="Source files" title="Source files">Filesystem count of uploaded source documents under configured source roots. It can be higher or lower than indexed documents because drafts, rejected history, legacy files, and non-indexed files may exist.</MetricLabel>
                  <strong>{stats.data?.filesystem?.source_files || 0}</strong>
                </div>
                <div className="stat">
                  <MetricLabel label="Generated files" title="Generated files">Filesystem count of generated artifacts such as raw markdown, parsed markdown, normalized markdown, approved markdown, manifests, and chunk files. This is not expected to match chunk count.</MetricLabel>
                  <strong>{stats.data?.filesystem?.generated_files || 0}</strong>
                </div>
              </>
            )}
          </div>
        </div>
        <div className="panel">
          <h2>Quick Actions</h2>
          <div className="stack">
            <Link className="stack-row row-main" href="/ingestion"><span><strong>Trigger ingestion</strong><div className="row-meta">Upload documents, create a batch, save draft, or submit.</div></span><span className="badge success">Primary</span></Link>
            <Link className="stack-row row-main" href="/control-center"><span><strong>Remove indexed documents</strong><div className="row-meta">Delete admin and legacy retrieval documents safely.</div></span><span className="badge warning">Guarded</span></Link>
            <Link className="stack-row row-main" href="/warehouse"><span><strong>Open warehouse</strong><div className="row-meta">View all indexed admin and legacy documents.</div></span><span className="badge info">Inventory</span></Link>
          </div>
        </div>
      </div>

      <div className="grid cols-2">
        <div className="panel">
          <div className="page-header compact">
            <h2>Recent Batches</h2>
            <button className="button" type="button" disabled={!visibleBatches.length || backendLoading || backendDown} onClick={clearOverviewBatches}>Clear</button>
          </div>
          <div className="stack overview-scroll">
            {backendLoading || (batches.loading && !batches.data) ? <SkeletonRows count={4} /> : null}
            {!backendLoading && !backendDown ? visibleBatches.slice(0, 12).map((batch) => (
              <Link className="stack-row row-main" href={`/monitoring?batchId=${encodeURIComponent(batch.batch_id)}`} key={batch.batch_id}>
                <span>
                  <span className="row-title"><strong>{batch.name}</strong><span className={`badge ${statusTone(batch.status)}`}>{compactStatus(batch.status)}</span><span className="badge info">{batchTypeLabel(batch.ingestion_label)}</span></span>
                  <div className="row-meta">{batch.total_documents} docs - created {formatDate(batch.created_at)}</div>
                </span>
                <span className="muted">{batch.documents_indexed}/{batch.total_documents} indexed</span>
              </Link>
            )) : null}
            {backendDown ? <div className="empty-state"><strong>Backend unavailable</strong><span>Recent batches are hidden until the backend reconnects.</span></div> : null}
            {!backendLoading && !backendDown && !visibleBatches.length ? <div className="empty-state"><strong>No batches shown</strong><span>Create a batch from Ingestion or refresh the full Past Jobs page.</span></div> : null}
          </div>
        </div>

        <div className="panel">
          <div className="page-header compact">
            <h2>Recent Errors</h2>
            <button className="button" type="button" disabled={!visibleErrors.length || backendLoading || backendDown} onClick={clearOverviewErrors}>Clear</button>
          </div>
          <div className="stack overview-scroll">
            {backendLoading || (logs.loading && !logs.data) ? <SkeletonRows count={4} /> : null}
            {!backendLoading && !backendDown ? visibleErrors.slice(0, 12).map((log) => (
              <Link className="stack-row row-main" href="/errors" key={log.log_id}>
                <span>
                  <span className="row-title"><strong>{log.stage}</strong><span className="badge danger">{log.level}</span></span>
                  <div className="row-meta">{log.message}</div>
                </span>
                <span className="muted">{formatDate(log.timestamp)}</span>
              </Link>
            )) : null}
            {backendDown ? <div className="empty-state"><strong>Backend unavailable</strong><span>Recent errors are hidden until the backend reconnects.</span></div> : null}
            {!backendLoading && !backendDown && !visibleErrors.length ? <div className="empty-state"><strong>No recent errors</strong><span>Failures will remain available in Error Logs even after clearing this overview.</span></div> : null}
          </div>
        </div>
      </div>

      <div className="panel">
        <h2>System Configuration</h2>
        <div className="stack">
          {backendLoading || (runtime.loading && !runtime.data) ? <SkeletonRows count={4} /> : null}
          {backendDown ? <div className="empty-state"><strong>Backend unavailable</strong><span>Model health is hidden until runtime config can be fetched.</span></div> : null}
          {!backendLoading && !backendDown ? (runtime.data?.models || []).map((model) => (
            <div className="doc-line" key={model.role}>
              <span>
                <strong>{model.role}</strong>
                <div className="row-meta">Hosted at {model.endpoint || "not configured"}</div>
                {model.health_error ? <div className="row-meta danger-text">{model.health_error}</div> : null}
              </span>
              <span className="inline">
                <span className={`badge ${model.configured ? modelTone(model.health_status) : "danger"}`}>{model.configured ? model.model_id : "Not configured"}</span>
                <span className={`badge ${modelTone(model.health_status)}`}>{modelStatusLabel(model.health_status)}{model.health_latency_ms != null ? ` ${model.health_latency_ms}ms` : ""}</span>
                <span className="badge neutral">{model.engine || "ollama"}</span>
              </span>
            </div>
          )) : null}
        </div>
      </div>

      <div className="panel">
        <h2>Storage Snapshot</h2>
        <p className="muted">Storage totals are filesystem counts from the admin source-document and generated-markdown folders. Per-document source size is shown in Document Warehouse.</p>
        {backendLoading ? <SkeletonRows count={1} /> : backendDown ? (
          <div className="empty-state"><strong>Backend unavailable</strong><span>Storage totals are hidden until the backend reconnects.</span></div>
        ) : (
          <div className="inline">
            <span className="badge neutral">Source files {stats.data?.filesystem?.source_files ?? 0}</span>
            <span className="badge neutral">Generated files {stats.data?.filesystem?.generated_files ?? 0}</span>
            <span className="badge neutral">Indexed text {formatBytes(stats.data?.total_chars || 0)}</span>
          </div>
        )}
      </div>
    </section>
  );
}
