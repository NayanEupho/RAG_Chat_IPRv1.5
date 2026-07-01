"use client";

import { useState } from "react";
import { adminApi } from "@/lib/api";
import { compactStatus, formatDate, statusTone } from "@/lib/format";
import { setAdminDataCache, useAdminData } from "@/components/use-admin-data";
import { useAdminEvents } from "@/components/use-admin-events";
import { SkeletonRows } from "@/components/loading-state";
import { RefreshIconButton } from "@/components/refresh-icon-button";
import { BatchConfigDetails } from "@/components/batch-config-details";
import type { AdminDocument, Batch } from "@/lib/types";

const terminalStatuses = new Set(["COMPLETE", "PARTIALLY_COMPLETE", "FAILED", "CANCELLED"]);
const terminalStatusQuery = "&status=COMPLETE,PARTIALLY_COMPLETE,FAILED,CANCELLED&include_documents=true";
const parsedStatuses = new Set(["PARSE_COMPLETE", "NORMALIZE_PENDING", "NORMALIZE_RUNNING", "NORMALIZE_COMPLETE", "REVIEW_PENDING", "REVIEW_IN_PROGRESS", "REVIEW_APPROVED", "CHUNK_PENDING", "CHUNK_RUNNING", "INDEXED", "REVIEW_REJECTED"]);
const normalizedStatuses = new Set(["NORMALIZE_COMPLETE", "REVIEW_PENDING", "REVIEW_IN_PROGRESS", "REVIEW_APPROVED", "CHUNK_PENDING", "CHUNK_RUNNING", "INDEXED"]);
const reviewedStatuses = new Set(["REVIEW_PENDING", "REVIEW_IN_PROGRESS", "REVIEW_APPROVED", "CHUNK_PENDING", "CHUNK_RUNNING", "INDEXED", "REVIEW_REJECTED"]);

function typeLabel(value?: string | null): string {
  return value === "qna" ? "QnA" : "General";
}

function batchTypeLabel(value?: string | null): string {
  if (value === "mix") return "Mix";
  if (value === "qna_docs") return "QnA";
  return "General";
}

function ReviewAudit({ document }: { document: AdminDocument }) {
  if (!document.effective_config?.review_required && !document.review) {
    return <div className="row-meta">Review not required.</div>;
  }
  const action = document.review?.review_action;
  const reviewedAt = action?.timestamp || document.review?.approved_at;
  const actionLabel = document.status === "REVIEW_REJECTED"
    ? "Rejected and deleted"
    : document.review?.status === "APPROVED"
      ? "Approved for indexing"
      : document.effective_config?.review_required
        ? "Review required"
        : "Review not required";
  return (
    <div className="inline" style={{ marginTop: 6 }}>
      <span className="badge neutral">Review {document.effective_config?.review_required ? "True" : "False"}</span>
      <span className={`badge ${document.status === "REVIEW_REJECTED" ? "warning" : document.review?.status === "APPROVED" ? "success" : "neutral"}`}>{actionLabel}</span>
      {action?.edited ? <span className="badge info">Edited</span> : null}
      {action?.replaced ? <span className="badge info">Replaced</span> : null}
      {document.status === "REVIEW_REJECTED" ? <span className={action?.cleanup_completed === false ? "badge danger" : "badge success"}>{action?.cleanup_completed === false ? "Cleanup issue" : "Artifacts deleted"}</span> : null}
      {reviewedAt ? <span className="badge neutral">{formatDate(reviewedAt)}</span> : null}
    </div>
  );
}

function StageCounts({ batch }: { batch: Batch }) {
  const docs = batch.documents || [];
  const parsed = docs.filter((doc) => parsedStatuses.has(doc.status)).length;
  const normalizationDocs = docs.filter((doc) => doc.effective_config?.normalization_enabled);
  const normalized = normalizationDocs.filter((doc) => normalizedStatuses.has(doc.status)).length;
  const reviewDocs = docs.filter((doc) => doc.effective_config?.review_required);
  const reviewed = reviewDocs.filter((doc) => reviewedStatuses.has(doc.status)).length;
  const indexed = docs.filter((doc) => doc.status === "INDEXED").length;
  return (
    <div className="inline">
      <span className="badge neutral">{parsed}/{batch.total_documents} parsed</span>
      <span className="badge neutral">{normalized}/{normalizationDocs.length} normalized</span>
      <span className="badge warning">{reviewed}/{reviewDocs.length} reviewed</span>
      <span className="badge success">{indexed}/{batch.total_documents} indexed</span>
    </div>
  );
}

function BatchRow({ batch, highlighted = false }: { batch: Batch; highlighted?: boolean }) {
  return (
    <details className={`stack-row ${highlighted ? "row-highlight-new" : ""}`}>
      <summary>
        <span>
          <span className="row-title">
            <strong>{batch.name}</strong>
            <span className={`badge ${statusTone(batch.status)}`}>{compactStatus(batch.status)}</span>
            <span className="badge info">{batchTypeLabel(batch.ingestion_label)}</span>
          </span>
          <div className="inline timestamp-row">
            <span className="timestamp-pill">Created {formatDate(batch.created_at)}</span>
            <span className="timestamp-pill important">Triggered {formatDate(batch.submitted_at)}</span>
            <span className="timestamp-pill success">Completed {formatDate(batch.completed_at)}</span>
          </div>
        </span>
        <StageCounts batch={batch} />
      </summary>
      <div className="row-detail">
        <BatchConfigDetails batch={batch} />
        {(batch.documents || []).map((document) => (
          <div className="doc-line" key={document.document_id}>
            <span>
              <strong>{document.original_filename}</strong>
              <div className="row-meta">{document.document_id} - {typeLabel(document.ingestion_type || document.effective_config?.ingestion_type)}</div>
              <ReviewAudit document={document} />
            </span>
            <span className={`badge ${statusTone(document.status)}`}>{document.status === "REVIEW_REJECTED" ? "Rejected in review" : compactStatus(document.status)}</span>
          </div>
        ))}
      </div>
    </details>
  );
}

export default function PastJobsPage() {
  const [refreshing, setRefreshing] = useState(false);
  const [refreshMessage, setRefreshMessage] = useState<string | null>(null);
  const [highlightedIds, setHighlightedIds] = useState<Set<string>>(new Set());
  const batches = useAdminData(() => adminApi.batches(terminalStatusQuery), 0, "terminalBatchesWithDocuments");
  useAdminEvents((event) => {
    if (event.type === "batch_progress" || event.type === "document_update" || event.type === "review_update") void batches.refresh();
  });
  const completed = (batches.data?.items || []).filter((batch) => terminalStatuses.has(batch.status));

  async function refreshPastJobs() {
    setRefreshing(true);
    setRefreshMessage(null);
    try {
      const previousIds = new Set(completed.map((batch) => batch.batch_id));
      const next = await adminApi.batches(terminalStatusQuery);
      const nextCompleted = next.items.filter((batch) => terminalStatuses.has(batch.status));
      const newIds = nextCompleted.filter((batch) => !previousIds.has(batch.batch_id)).map((batch) => batch.batch_id);
      setAdminDataCache("terminalBatchesWithDocuments", next);
      if (newIds.length > 0) {
        setHighlightedIds(new Set(newIds));
        setRefreshMessage(`${newIds.length} new job${newIds.length === 1 ? "" : "s"}`);
        window.setTimeout(() => setHighlightedIds(new Set()), 5200);
      } else {
        setRefreshMessage("Nothing new");
      }
    } catch (caught) {
      setRefreshMessage(caught instanceof Error ? `Refresh failed: ${caught.message}` : "Refresh failed");
    } finally {
      setRefreshing(false);
      window.setTimeout(() => setRefreshMessage(null), 2600);
    }
  }

  return (
    <section className="page">
      <div className="page-header">
        <div>
          <h1>Past Jobs</h1>
          <p>Historical ingestion batches with document-level outcomes and timestamps.</p>
        </div>
        <div className="actions">
          <RefreshIconButton refreshing={refreshing} label="Refresh past jobs" onRefresh={() => void refreshPastJobs()} />
          {refreshMessage ? <span className={`inline-refresh-status ${refreshMessage.startsWith("Refresh failed") ? "error" : refreshMessage === "Nothing new" ? "neutral" : "success"}`}>{refreshMessage}</span> : null}
        </div>
      </div>
      <div className="panel">
        <h2>Completed Batches</h2>
        <div className="stack scroll-stack tall">
          {batches.loading && !batches.data ? <SkeletonRows count={6} /> : null}
          {completed.map((batch) => <BatchRow batch={batch} highlighted={highlightedIds.has(batch.batch_id)} key={batch.batch_id} />)}
          {!batches.loading && !completed.length ? <div className="empty-state"><strong>No completed jobs</strong><span>Finished, failed, and partially indexed batches will appear here.</span></div> : null}
        </div>
      </div>
    </section>
  );
}
