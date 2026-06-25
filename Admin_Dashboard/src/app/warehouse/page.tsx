"use client";

import { EmptyState } from "@/components/empty-state";
import { StatusBadge } from "@/components/status-badge";
import { useAdminData } from "@/components/use-admin-data";
import { adminApi } from "@/lib/api";

function formatModified(value: number): string {
  return new Date(value * 1000).toLocaleString();
}

export default function WarehousePage() {
  const documents = useAdminData(() => adminApi.documents(), 10000);
  const inventory = useAdminData(() => adminApi.warehouseInventory(), 15000);

  return (
    <section className="page">
      <div className="page-header">
        <div>
          <h1>Document Warehouse</h1>
          <p>Project-wide inventory from SQLite, upload_docs, and generated_doc_md.</p>
        </div>
      </div>

      <div className="grid cols-4">
        <div className="stat"><span className="muted">Source Files</span><strong>{inventory.data?.summary.source_files ?? "-"}</strong></div>
        <div className="stat"><span className="muted">PDFs</span><strong>{inventory.data?.summary.pdf_files ?? "-"}</strong></div>
        <div className="stat"><span className="muted">Generated Files</span><strong>{inventory.data?.summary.generated_files ?? "-"}</strong></div>
        <div className="stat"><span className="muted">Artifact Runs</span><strong>{inventory.data?.summary.artifact_runs ?? "-"}</strong></div>
      </div>

      <div className="panel" style={{ marginTop: 16 }}>
        <h2>Dashboard Managed Documents</h2>
        {!documents.data?.items.length ? (
          <EmptyState title="No dashboard-managed documents yet" detail="New dashboard uploads will appear here and write files into the project upload/generated folders." />
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

      <div className="grid cols-2" style={{ marginTop: 16 }}>
        <div className="panel">
          <h2>Existing Source Files</h2>
          {!inventory.data?.source_files.length ? (
            <EmptyState title="No source files found" />
          ) : (
            <table className="table">
              <thead><tr><th>File</th><th>Type</th><th>Modified</th></tr></thead>
              <tbody>
                {inventory.data.source_files.slice(0, 25).map((file) => (
                  <tr key={file.id}>
                    <td>{file.filename}<br /><span className="muted">{file.relative_path}</span></td>
                    <td>{file.extension}</td>
                    <td>{formatModified(file.modified_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        <div className="panel">
          <h2>Generated Artifact Runs</h2>
          {!inventory.data?.artifact_runs.length ? (
            <EmptyState title="No generated artifacts found" />
          ) : (
            <table className="table">
              <thead><tr><th>Document</th><th>Parser</th><th>Files</th></tr></thead>
              <tbody>
                {inventory.data.artifact_runs.slice(0, 25).map((run) => (
                  <tr key={run.id}>
                    <td>{run.document_name}<br /><span className="muted">{run.relative_path}</span></td>
                    <td>{run.parser}</td>
                    <td className="actions">
                      {run.has_selected ? <span className="badge success">selected.md</span> : null}
                      {run.has_normalized ? <span className="badge info">normalized.md</span> : null}
                      {run.has_chunks ? <span className="badge neutral">chunks.jsonl</span> : null}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </section>
  );
}

