"use client";

import { EmptyState } from "@/components/empty-state";
import { StatusBadge } from "@/components/status-badge";
import { useAdminData } from "@/components/use-admin-data";
import { adminApi } from "@/lib/api";

export default function WarehousePage() {
  const documents = useAdminData(() => adminApi.documents(), 10000);

  return (
    <section className="page">
      <div className="page-header">
        <div>
          <h1>Document Warehouse</h1>
          <p>Permanent inventory of admin-ingested documents and their canonical files.</p>
        </div>
      </div>
      <div className="panel">
        {!documents.data?.items.length ? (
          <EmptyState title="No documents in warehouse" detail="Documents uploaded through the admin dashboard will appear here." />
        ) : (
          <table className="table">
            <thead><tr><th>Document</th><th>Status</th><th>Chunks</th><th>Canonical Files</th></tr></thead>
            <tbody>
              {documents.data.items.map((document) => (
                <tr key={document.document_id}>
                  <td>{document.original_filename}<br /><span className="muted">{document.file_size_bytes} bytes</span></td>
                  <td><StatusBadge status={document.status} /></td>
                  <td>{document.chunk_count ?? "-"}</td>
                  <td className="actions">
                    <a className="button" href={`http://localhost:8000/api/v1/documents/${document.document_id}/files/source`}>Source</a>
                    {document.canonical_files ? (
                      <>
                        <a className="button" href={`http://localhost:8000/api/v1/documents/${document.document_id}/files/raw`}>Raw</a>
                        <a className="button" href={`http://localhost:8000/api/v1/documents/${document.document_id}/files/parsed`}>Parsed</a>
                        <a className="button" href={`http://localhost:8000/api/v1/documents/${document.document_id}/files/approved`}>Approved</a>
                      </>
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </section>
  );
}

