"use client";

import Link from "next/link";
import { Suspense, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { adminApi } from "@/lib/api";
import { compactStatus, formatDate, statusTone } from "@/lib/format";
import { useAdminData } from "@/components/use-admin-data";
import { useAdminEvents } from "@/components/use-admin-events";
import { SkeletonRows } from "@/components/loading-state";
import { useAdminLiveLogs } from "@/components/use-admin-live-logs";
import type { Batch } from "@/lib/types";

const activeStatuses = new Set(["SUBMITTED", "PARSING", "NORMALIZING", "REVIEWING", "CHUNKING"]);
const parsedStatuses = new Set(["PARSE_COMPLETE", "NORMALIZE_PENDING", "NORMALIZE_RUNNING", "NORMALIZE_COMPLETE", "REVIEW_PENDING", "REVIEW_IN_PROGRESS", "REVIEW_APPROVED", "CHUNK_PENDING", "CHUNK_RUNNING", "INDEXED"]);
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

function BatchRow({ batch, onlyReviewPending = false, onCancel }: { batch: Batch; onlyReviewPending?: boolean; onCancel?: (batch: Batch) => void }) {
  const documents = onlyReviewPending
    ? (batch.documents || []).filter((document) => document.status === "REVIEW_PENDING" || document.status === "REVIEW_IN_PROGRESS")
    : batch.documents || [];
  return (
    <details className="stack-row">
      <summary>
        <span>
          <span className="row-title"><strong>{batch.name}</strong><span className={`badge ${statusTone(batch.status)}`}>{compactStatus(batch.status)}</span><span className="badge info">{batchTypeLabel(batch.ingestion_label)}</span></span>
          <div className="row-meta">Created {formatDate(batch.created_at)} - triggered {formatDate(batch.submitted_at)} - completed {formatDate(batch.completed_at)}</div>
        </span>
        <span className="actions">
          <StageCounts batch={batch} />
          {onCancel ? (
            <button
              className="button danger"
              type="button"
              title={`Cancel ${batch.name}`}
              onClick={(event) => {
                event.preventDefault();
                event.stopPropagation();
                onCancel(batch);
              }}
            >
              X
            </button>
          ) : null}
        </span>
      </summary>
      <div className="row-detail">
        {documents.map((document) => (
          <div className="doc-line" key={document.document_id}>
            <span><strong>{document.original_filename}</strong><div className="row-meta">{document.document_id} - {typeLabel(document.ingestion_type || document.effective_config?.ingestion_type)}</div></span>
            <span className={`badge ${statusTone(document.status)}`}>{document.status === "REVIEW_REJECTED" ? "Rejected in review" : compactStatus(document.status)}</span>
          </div>
        ))}
      </div>
    </details>
  );
}

function MonitoringContent() {
  const params = useSearchParams();
  const highlightedBatchId = params.get("batchId");
  const batches = useAdminData(() => adminApi.batches("&include_documents=true"), 0, "batchesWithDocuments");
  const liveLogs = useAdminLiveLogs();
  const terminalRef = useRef<HTMLPreElement | null>(null);
  const [cancelBusy, setCancelBusy] = useState<string | null>(null);
  const [cancelMessage, setCancelMessage] = useState<string | null>(null);
  useAdminEvents((event) => {
    if (event.type !== "ping") void batches.refresh();
  });

  useEffect(() => {
    if (terminalRef.current) terminalRef.current.scrollTop = terminalRef.current.scrollHeight;
  }, [liveLogs.logs.length]);

  const sorted = batches.data?.items || [];
  const active = sorted.filter((batch) => activeStatuses.has(batch.status));
  const reviewQueue = sorted.filter((batch) => (batch.documents || []).some((document) => document.status === "REVIEW_PENDING" || document.status === "REVIEW_IN_PROGRESS"));
  const highlighted = useMemo(() => sorted.find((batch) => batch.batch_id === highlightedBatchId), [highlightedBatchId, sorted]);

  async function copyLogs() {
    await navigator.clipboard.writeText(liveLogs.logs.join("\n"));
  }

  async function cancelBatch(batch: Batch) {
    const confirmed = window.confirm(
      `Cancel "${batch.name}"?\n\nThis will stop queued/running ingestion work and safely remove this batch's uploaded source files, generated markdown, normalization artifacts, and any vector entries for its documents.`
    );
    if (!confirmed) return;
    setCancelBusy(batch.batch_id);
    setCancelMessage(null);
    try {
      const result = await adminApi.cancelBatch(batch.batch_id);
      const cleanup = result.cleanup_errors.length ? ` ${result.cleanup_errors.length} cleanup issue(s) recorded.` : "";
      setCancelMessage(`Cancelled ${batch.name}.${cleanup}`);
      await batches.refresh();
    } catch (caught) {
      setCancelMessage(caught instanceof Error ? `Cancel failed: ${caught.message}` : "Cancel failed");
    } finally {
      setCancelBusy(null);
      window.setTimeout(() => setCancelMessage(null), 4200);
    }
  }

  async function cancelAll() {
    const confirmed = window.confirm(
      `Cancel all ${active.length} currently processing batch${active.length === 1 ? "" : "es"}?\n\nThis will stop queued/running ingestion work and safely remove uploaded source files, generated markdown, normalization artifacts, and any vector entries for the active batches.`
    );
    if (!confirmed) return;
    setCancelBusy("all");
    setCancelMessage(null);
    try {
      const result = await adminApi.cancelActiveBatches();
      setCancelMessage(`Cancelled ${result.total} batch${result.total === 1 ? "" : "es"}${result.errors.length ? `; ${result.errors.length} failed` : ""}.`);
      await batches.refresh();
    } catch (caught) {
      setCancelMessage(caught instanceof Error ? `Cancel all failed: ${caught.message}` : "Cancel all failed");
    } finally {
      setCancelBusy(null);
      window.setTimeout(() => setCancelMessage(null), 4200);
    }
  }

  return (
    <section className="page">
      <div className="page-header">
        <div>
          <h1>Monitoring</h1>
          <p>Track active admin ingestion batches, review queues, document stages, and live job events.</p>
        </div>
        <div className="actions">
          <Link className="button" href="/monitoring/live-logs" target="_blank">Open console</Link>
          <Link className="button" href="/past-jobs">Past jobs</Link>
          <button className="button" type="button" onClick={() => void batches.refresh()}>Refresh</button>
        </div>
      </div>

      {highlighted ? (
        <div className="panel">
          <h2>Selected Batch</h2>
          <BatchRow batch={highlighted} />
        </div>
      ) : null}

      <div className="panel">
        <div className="section-heading">
          <h2>Currently Processing Batches</h2>
          <div className="actions">
            {cancelMessage ? <span className={cancelMessage.toLowerCase().includes("failed") ? "inline-refresh-status error" : "inline-refresh-status neutral"}>{cancelMessage}</span> : null}
            <button className="button danger" type="button" disabled={active.length === 0 || cancelBusy !== null} onClick={() => void cancelAll()}>{cancelBusy === "all" ? "Cancelling..." : "Cancel all"}</button>
          </div>
        </div>
        <div className="stack scroll-stack">
          {batches.loading && !batches.data ? <SkeletonRows count={4} /> : null}
          {active.map((batch) => <BatchRow batch={batch} onCancel={(item) => void cancelBatch(item)} key={batch.batch_id} />)}
          {!batches.loading && !active.length ? <div className="empty-state"><strong>No active batches</strong><span>Submitted ingestion jobs will appear here.</span></div> : null}
        </div>
      </div>

      <div className="panel">
        <h2>To Be Reviewed</h2>
        <div className="stack scroll-stack">
          {batches.loading && !batches.data ? <SkeletonRows count={4} /> : null}
          {reviewQueue.map((batch) => <BatchRow batch={batch} onlyReviewPending key={batch.batch_id} />)}
          {!batches.loading && !reviewQueue.length ? <div className="empty-state"><strong>No review queue</strong><span>Batches with documents awaiting audit will appear here.</span></div> : null}
        </div>
      </div>

      <div className="panel">
        <div className="page-header">
          <div>
            <h2>Live Logs Console</h2>
            <p>Streaming admin events from the backend.</p>
          </div>
          <div className="actions">
            <button className="button" type="button" onClick={() => liveLogs.clear()}>Clear</button>
            <button className="button" type="button" onClick={() => void copyLogs()}>Copy</button>
          </div>
        </div>
        <pre className="terminal" ref={terminalRef}>{liveLogs.logs.length ? liveLogs.logs.join("\n") : "Waiting for live ingestion events..."}</pre>
      </div>
    </section>
  );
}

export default function MonitoringPage() {
  return (
    <Suspense fallback={<section className="page"><div className="panel"><SkeletonRows count={6} /></div></section>}>
      <MonitoringContent />
    </Suspense>
  );
}
