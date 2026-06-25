"use client";

import { useState } from "react";
import { EmptyState } from "@/components/empty-state";
import { StatusBadge } from "@/components/status-badge";
import { useAdminData } from "@/components/use-admin-data";
import { adminApi } from "@/lib/api";
import type { AdminDocument, ParseVariant } from "@/lib/types";

function firstCompleteParse(document: AdminDocument): ParseVariant | undefined {
  return document.parse_variants.find((variant) => variant.status === "COMPLETE");
}

export default function ReviewPage() {
  const documents = useAdminData(() => adminApi.documents(), 8000);
  const [busyId, setBusyId] = useState<string | null>(null);
  const reviewable = (documents.data?.items || []).filter((document) =>
    ["REVIEW_PENDING", "REVIEW_IN_PROGRESS", "PARSE_COMPLETE", "NORMALIZE_COMPLETE", "CHUNK_FAILED"].includes(document.status)
    || document.parse_variants.some((variant) => variant.status === "FAILED")
  );

  async function approve(document: AdminDocument) {
    const completeParse = firstCompleteParse(document);
    if (!completeParse) return;
    const completeNorm = completeParse.norm_variants.find((variant) => variant.status === "COMPLETE") || null;
    setBusyId(document.document_id);
    try {
      await adminApi.selectVariant(document.document_id, completeParse.variant_id, completeNorm?.norm_variant_id || null);
      await adminApi.approve(document.document_id, completeParse.variant_id, completeNorm?.norm_variant_id || null);
      await documents.refresh();
    } finally {
      setBusyId(null);
    }
  }

  async function retryParse(documentId: string, variantId: string) {
    setBusyId(variantId);
    try {
      await adminApi.retryParse(documentId, variantId);
      await documents.refresh();
    } finally {
      setBusyId(null);
    }
  }

  async function retryChunking(documentId: string) {
    setBusyId(documentId);
    try {
      await adminApi.retryChunking(documentId);
      await documents.refresh();
    } finally {
      setBusyId(null);
    }
  }

  return (
    <section className="page">
      <div className="page-header">
        <div>
          <h1>Review</h1>
          <p>Compare parser and normalization variants before approving the markdown for indexing.</p>
        </div>
        <button className="button" type="button" onClick={() => void documents.refresh()}>Refresh</button>
      </div>
      <div className="panel">
        <h2>Documents Awaiting Review</h2>
        {reviewable.length === 0 ? (
          <EmptyState title="No documents ready for review" detail="Completed parse and normalization outputs will appear here." />
        ) : (
          <table className="table">
            <thead><tr><th>Document</th><th>Status</th><th>Variants</th><th>Action</th></tr></thead>
            <tbody>
              {reviewable.map((document) => {
                const completeParse = firstCompleteParse(document);
                return (
                  <tr key={document.document_id}>
                    <td>
                      {document.original_filename}
                      {document.error_summary ? <><br /><span className="error">{document.error_summary}</span></> : null}
                    </td>
                    <td><StatusBadge status={document.status} /></td>
                    <td>
                      <div className="variant-list">
                        {document.parse_variants.map((variant) => (
                          <div className="variant-row" key={variant.variant_id}>
                            <span>{variant.parser_type}</span>
                            <StatusBadge status={variant.status} />
                            {variant.status === "FAILED" ? (
                              <button
                                className="button"
                                type="button"
                                disabled={busyId === variant.variant_id}
                                onClick={() => void retryParse(document.document_id, variant.variant_id)}
                              >
                                Retry Parse
                              </button>
                            ) : null}
                            {variant.norm_variants.map((norm) => (
                              <span className="muted" key={norm.norm_variant_id}>
                                {norm.model_config.display_name}: {norm.status}
                              </span>
                            ))}
                          </div>
                        ))}
                      </div>
                    </td>
                    <td className="actions">
                      {document.status === "CHUNK_FAILED" ? (
                        <button className="button" type="button" disabled={busyId === document.document_id} onClick={() => void retryChunking(document.document_id)}>
                          Retry Chunking
                        </button>
                      ) : null}
                      <button
                        className="button primary"
                        type="button"
                        disabled={!completeParse || busyId === document.document_id}
                        onClick={() => void approve(document)}
                      >
                        {busyId === document.document_id ? "Working..." : "Approve & Index"}
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </section>
  );
}

