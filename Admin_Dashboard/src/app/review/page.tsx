"use client";

import { EmptyState } from "@/components/empty-state";
import { StatusBadge } from "@/components/status-badge";
import { useAdminData } from "@/components/use-admin-data";
import { adminApi } from "@/lib/api";

export default function ReviewPage() {
  const documents = useAdminData(() => adminApi.documents(), 8000);
  const reviewable = (documents.data?.items || []).filter((document) =>
    ["REVIEW_PENDING", "REVIEW_IN_PROGRESS", "PARSE_COMPLETE", "NORMALIZE_COMPLETE"].includes(document.status)
  );

  async function approve(documentId: string, parseVariantId: string, normVariantId: string | null) {
    await adminApi.selectVariant(documentId, parseVariantId, normVariantId);
    await adminApi.approve(documentId, parseVariantId, normVariantId);
    await documents.refresh();
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
                const completeParse = document.parse_variants.find((variant) => variant.status === "COMPLETE");
                const completeNorm = completeParse?.norm_variants.find((variant) => variant.status === "COMPLETE") || null;
                return (
                  <tr key={document.document_id}>
                    <td>{document.original_filename}</td>
                    <td><StatusBadge status={document.status} /></td>
                    <td>
                      {document.parse_variants.map((variant) => (
                        <div key={variant.variant_id}>
                          {variant.parser_type}: <StatusBadge status={variant.status} />
                        </div>
                      ))}
                    </td>
                    <td>
                      <button
                        className="button primary"
                        type="button"
                        disabled={!completeParse}
                        onClick={() => completeParse ? void approve(document.document_id, completeParse.variant_id, completeNorm?.norm_variant_id || null) : undefined}
                      >
                        Approve & Index
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

