"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { adminApi } from "@/lib/api";
import { compactStatus, formatDate, statusTone } from "@/lib/format";
import { useAdminData } from "@/components/use-admin-data";
import { SkeletonRows } from "@/components/loading-state";
import type { AdminDocument } from "@/lib/types";

function typeLabel(value?: string | null): string {
  return value === "qna" ? "QnA" : "General";
}

function bestCompleteVariant(document: AdminDocument) {
  const parse = document.parse_variants.find((variant) => variant.status === "COMPLETE");
  const norm = document.parse_variants.flatMap((variant) => variant.norm_variants).find((variant) => variant.status === "COMPLETE");
  return { parse, norm };
}

export default function ReviewPage() {
  const documents = useAdminData(() => adminApi.documents(), 0, "documents");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const pending = useMemo(
    () => (documents.data?.items || []).filter((doc) => doc.status === "REVIEW_PENDING" || doc.status === "REVIEW_IN_PROGRESS"),
    [documents.data]
  );
  const allSelected = pending.length > 0 && pending.every((doc) => selected.has(doc.document_id));

  function toggle(documentId: string) {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(documentId)) next.delete(documentId);
      else next.add(documentId);
      return next;
    });
  }

  async function approveOne(document: AdminDocument) {
    const { parse, norm } = bestCompleteVariant(document);
    if (!parse) throw new Error(`${document.original_filename} has no completed parser output`);
    await adminApi.selectVariant(document.document_id, parse.variant_id, norm?.norm_variant_id || null);
    await adminApi.approve(document.document_id, parse.variant_id, norm?.norm_variant_id || null);
  }

  async function bulkApprove() {
    setBusy(true);
    setError(null);
    try {
      await adminApi.bulkApprove(Array.from(selected));
      setSelected(new Set());
      await documents.refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Bulk approve failed.");
    } finally {
      setBusy(false);
    }
  }

  async function bulkReject() {
    const count = selected.size;
    const confirmed = window.confirm(
      `Reject ${count} selected document${count === 1 ? "" : "s"}?\n\nRejected documents will not be indexed. Their source files, generated markdown, metadata artifacts, and intermediate outputs will be deleted automatically. The batch history will keep an audit record of the rejection.`
    );
    if (!confirmed) return;
    setBusy(true);
    setError(null);
    try {
      await adminApi.bulkReject(Array.from(selected), "Rejected from review queue.");
      setSelected(new Set());
      await documents.refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Bulk reject failed.");
    } finally {
      setBusy(false);
    }
  }

  async function quickApprove(document: AdminDocument) {
    setBusy(true);
    setError(null);
    try {
      await approveOne(document);
      await documents.refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Approve failed.");
    } finally {
      setBusy(false);
    }
  }

  async function quickReject(documentId: string) {
    const document = pending.find((item) => item.document_id === documentId);
    const confirmed = window.confirm(
      `Reject "${document?.original_filename || documentId}"?\n\nThis document will not be indexed. Its source file, generated markdown, metadata artifacts, and intermediate outputs will be deleted automatically. The batch history will keep an audit record.`
    );
    if (!confirmed) return;
    setBusy(true);
    setError(null);
    try {
      await adminApi.reject(documentId, "Rejected from review queue.");
      await documents.refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Reject failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="page">
      <div className="page-header">
        <div>
          <h1>Review</h1>
          <p>Approve final markdown for indexing, or reject documents and remove their artifacts before they enter retrieval.</p>
        </div>
        <div className="actions">
          <button className="button" type="button" onClick={() => setSelected(allSelected ? new Set() : new Set(pending.map((doc) => doc.document_id)))}>Select all</button>
          <button className="button primary" type="button" disabled={busy || selected.size === 0} onClick={() => void bulkApprove()}>Approve selected</button>
          <button className="button danger" type="button" disabled={busy || selected.size === 0} onClick={() => void bulkReject()}>Reject selected</button>
        </div>
      </div>
      {error ? <p className="error">{error}</p> : null}

      <div className="panel">
        <h2>Awaiting Review</h2>
        <div className="stack">
          {documents.loading && !documents.data ? <SkeletonRows count={6} /> : null}
          {pending.map((document) => {
            const { parse, norm } = bestCompleteVariant(document);
            return (
              <div className="stack-row row-main" key={document.document_id}>
                <span>
                  <span className="row-title">
                    <input type="checkbox" checked={selected.has(document.document_id)} onChange={() => toggle(document.document_id)} aria-label={`Select ${document.original_filename}`} />
                    <strong>{document.original_filename}</strong>
                    <span className="badge info">Batch {document.batch_id.slice(0, 10)}</span>
                    <span className="badge neutral">{typeLabel(document.ingestion_type || document.effective_config.ingestion_type)}</span>
                    <span className={`badge ${statusTone(document.status)}`}>{compactStatus(document.status)}</span>
                  </span>
                  <div className="row-meta">
                    Parser {parse?.parser_type || "unknown"} {norm ? `- normalized by ${norm.model_config.display_name}` : "- parsed markdown only"} - uploaded {formatDate(document.uploaded_at)}
                  </div>
                </span>
                <span className="actions">
                  <Link className="button" href={`/review/${encodeURIComponent(document.document_id)}`} target="_blank">Open</Link>
                  <button className="button primary" type="button" disabled={busy} onClick={() => void quickApprove(document)}>Approve</button>
                  <button className="button danger" type="button" disabled={busy} onClick={() => void quickReject(document.document_id)}>Reject</button>
                </span>
              </div>
            );
          })}
          {!documents.loading && !pending.length ? <div className="empty-state"><strong>No documents awaiting review</strong><span>Documents will arrive here when a batch requires audit before indexing.</span></div> : null}
        </div>
      </div>
    </section>
  );
}
