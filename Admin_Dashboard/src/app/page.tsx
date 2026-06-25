"use client";

import { useMemo } from "react";
import { EmptyState } from "@/components/empty-state";
import { StatusBadge } from "@/components/status-badge";
import { useAdminEvents } from "@/components/use-admin-events";
import { useAdminData } from "@/components/use-admin-data";
import { adminApi } from "@/lib/api";

export default function MonitoringPage() {
  const stats = useAdminData(() => adminApi.stats(), 7000);
  const batches = useAdminData(() => adminApi.batches(), 7000);
  const documents = useAdminData(() => adminApi.documents(), 7000);
  useAdminEvents((event) => {
    if (["batch_progress", "document_update", "job_update", "job_error", "notification"].includes(event.type)) {
      void stats.refresh();
      void batches.refresh();
      void documents.refresh();
    }
  });

  const activeBatches = useMemo(
    () => (batches.data?.items || []).filter((batch) => !["DRAFT", "COMPLETE", "FAILED"].includes(batch.status)),
    [batches.data]
  );
  const failures = useMemo(
    () => (documents.data?.items || []).filter((document) => document.status.endsWith("_FAILED")).slice(0, 8),
    [documents.data]
  );
  const completed = useMemo(
    () => (documents.data?.items || []).filter((document) => document.status === "INDEXED").slice(0, 8),
    [documents.data]
  );

  return (
    <section className="page">
      <div className="page-header">
        <div>
          <h1>Monitoring</h1>
          <p>Live operational view of batch progress, failures, and indexed output.</p>
        </div>
        <button className="button" type="button" onClick={() => { void stats.refresh(); void batches.refresh(); void documents.refresh(); }}>
          Refresh
        </button>
      </div>

      <div className="grid cols-4">
        <div className="stat"><span className="muted">Source Files</span><strong>{stats.data?.filesystem?.source_files ?? "-"}</strong></div>
        <div className="stat"><span className="muted">Artifact Runs</span><strong>{stats.data?.filesystem?.artifact_runs ?? "-"}</strong></div>
        <div className="stat"><span className="muted">Dashboard Docs</span><strong>{stats.data?.documents ?? "-"}</strong></div>
        <div className="stat"><span className="muted">Failed Jobs</span><strong>{stats.data?.failed_jobs ?? "-"}</strong></div>
      </div>

      <div className="grid cols-2" style={{ marginTop: 16 }}>
        <div className="panel">
          <h2>Active Processing</h2>
          {activeBatches.length === 0 ? (
            <EmptyState title="No active batches" detail="Submitted batches will appear here as parsing, normalization, and chunking progress." />
          ) : (
            <table className="table">
              <thead><tr><th>Batch</th><th>Status</th><th>Progress</th></tr></thead>
              <tbody>
                {activeBatches.map((batch) => {
                  const progress = batch.total_documents > 0 ? Math.round((batch.documents_indexed / batch.total_documents) * 100) : 0;
                  return (
                    <tr key={batch.batch_id}>
                      <td>{batch.name}</td>
                      <td><StatusBadge status={batch.status} /></td>
                      <td><div className="progress"><span style={{ width: `${progress}%` }} /></div></td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>

        <div className="panel">
          <h2>Recent Failures</h2>
          {failures.length === 0 ? (
            <EmptyState title="No failed documents" detail="Failed parse, normalization, or chunking jobs will be listed with retry actions." />
          ) : (
            <table className="table">
              <tbody>
                {failures.map((document) => (
                  <tr key={document.document_id}>
                    <td>{document.original_filename}<br /><span className="muted">{document.error_summary}</span></td>
                    <td><StatusBadge status={document.status} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>

      <div className="panel" style={{ marginTop: 16 }}>
        <h2>Completed Today</h2>
        {completed.length === 0 ? (
          <EmptyState title="No indexed documents yet" detail="Approved and indexed documents will appear with their chunk counts." />
        ) : (
          <table className="table">
            <thead><tr><th>Document</th><th>Chunks</th><th>Indexed At</th></tr></thead>
            <tbody>
              {completed.map((document) => (
                <tr key={document.document_id}>
                  <td>{document.original_filename}</td>
                  <td>{document.chunk_count ?? 0}</td>
                  <td>{document.indexed_at}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </section>
  );
}
