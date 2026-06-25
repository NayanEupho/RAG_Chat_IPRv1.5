"use client";

import { useAdminData } from "@/components/use-admin-data";
import { adminApi } from "@/lib/api";

export default function VectorStatsPage() {
  const stats = useAdminData(() => adminApi.vectorStats(), 10000);

  return (
    <section className="page">
      <div className="page-header">
        <div>
          <h1>Vector Stats</h1>
          <p>High-level telemetry for the Chroma collection and admin chunk mirror.</p>
        </div>
        <button className="button" type="button" onClick={() => void stats.refresh()}>Refresh</button>
      </div>
      <div className="grid cols-4">
        <div className="stat"><span className="muted">Chroma Count</span><strong>{stats.data?.chroma_count ?? "-"}</strong></div>
        <div className="stat"><span className="muted">Admin Chunks</span><strong>{stats.data?.chunks ?? "-"}</strong></div>
        <div className="stat"><span className="muted">Generated Chunk Files</span><strong>{stats.data?.filesystem?.chunk_files ?? "-"}</strong></div>
        <div className="stat"><span className="muted">Markdown Files</span><strong>{stats.data?.filesystem?.markdown_files ?? "-"}</strong></div>
      </div>
      <div className="grid cols-2" style={{ marginTop: 16 }}>
        <div className="panel">
          <h2>SQLite Footprint</h2>
          <table className="table">
            <tbody>
              <tr><td>Mirrored tokens</td><td>{stats.data?.total_tokens ?? "-"}</td></tr>
              <tr><td>Mirrored characters</td><td>{stats.data?.total_chars ?? "-"}</td></tr>
              <tr><td>Dashboard documents</td><td>{stats.data?.documents ?? "-"}</td></tr>
            </tbody>
          </table>
        </div>
        <div className="panel">
          <h2>Filesystem Corpus</h2>
          <table className="table">
            <tbody>
              <tr><td>Source files</td><td>{stats.data?.filesystem?.source_files ?? "-"}</td></tr>
              <tr><td>Generated files</td><td>{stats.data?.filesystem?.generated_files ?? "-"}</td></tr>
              <tr><td>Artifact runs</td><td>{stats.data?.filesystem?.artifact_runs ?? "-"}</td></tr>
            </tbody>
          </table>
        </div>
      </div>
      {stats.data?.error ? <p className="error">{stats.data.error}</p> : null}
    </section>
  );
}
