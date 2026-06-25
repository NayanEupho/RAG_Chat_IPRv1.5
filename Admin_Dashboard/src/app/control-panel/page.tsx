"use client";

import { EmptyState } from "@/components/empty-state";
import { adminApi } from "@/lib/api";
import { useAdminData } from "@/components/use-admin-data";

export default function ControlPanelPage() {
  const stats = useAdminData(() => adminApi.vectorStats(), 10000);
  const runtime = useAdminData(() => adminApi.runtimeConfig(), 12000);
  const endpoints = useAdminData(() => adminApi.llmEndpoints(), 12000);

  return (
    <section className="page">
      <div className="page-header">
        <div>
          <h1>Control Panel</h1>
          <p>Project runtime configuration, Chroma health, and normalization model visibility.</p>
        </div>
      </div>
      <div className="grid cols-2">
        <div className="panel">
          <h2>Runtime From Root .env</h2>
          <table className="table">
            <tbody>
              <tr><td>Normalization model</td><td>{runtime.data?.normalization.display_name || "Not configured"}</td></tr>
              <tr><td>Normalization endpoint</td><td>{runtime.data?.normalization.endpoint || "Not configured"}</td></tr>
              <tr><td>LLM normalization default</td><td>{runtime.data?.normalization.enabled ? "Enabled" : "Disabled"}</td></tr>
              <tr><td>Embedding model</td><td>{runtime.data?.embedding.display_name || "Not configured"}</td></tr>
              <tr><td>Embedding endpoint</td><td>{runtime.data?.embedding.endpoint || "Not configured"}</td></tr>
              <tr><td>Parser mode</td><td>{runtime.data?.parsing_mode || "-"}</td></tr>
              <tr><td>Vision parser endpoint</td><td>{runtime.data?.vision.endpoint || "Not configured"}</td></tr>
            </tbody>
          </table>
        </div>
        <div className="panel">
          <h2>System Status</h2>
          <table className="table">
            <tbody>
              <tr><td>Admin API</td><td>{stats.error ? "Degraded" : "Online"}</td></tr>
              <tr><td>ChromaDB</td><td>{stats.data?.healthy ? "Online" : "Unknown"}</td></tr>
              <tr><td>Chroma chunks</td><td>{stats.data?.chroma_count ?? "-"}</td></tr>
              <tr><td>SQLite chunks</td><td>{stats.data?.chunks ?? "-"}</td></tr>
              <tr><td>Source files</td><td>{stats.data?.filesystem?.source_files ?? "-"}</td></tr>
              <tr><td>Generated artifacts</td><td>{stats.data?.filesystem?.generated_files ?? "-"}</td></tr>
            </tbody>
          </table>
        </div>
      </div>

      <div className="panel" style={{ marginTop: 16 }}>
        <h2>Saved Endpoint Metadata</h2>
        <p className="muted">
          Active normalization uses the root project .env values above. This table is retained for admin notes and future multi-model selection.
        </p>
        {!endpoints.data?.items.length ? (
          <EmptyState title="No extra endpoint metadata saved" detail="The active endpoint is read from the project environment." />
        ) : (
          <table className="table">
            <thead><tr><th>Model</th><th>Endpoint</th><th>Status</th></tr></thead>
            <tbody>
              {endpoints.data.items.map((endpoint) => (
                <tr key={endpoint.endpoint_id}>
                  <td>{endpoint.display_name}<br /><span className="muted">{endpoint.model_id}</span></td>
                  <td>{endpoint.endpoint}</td>
                  <td>{endpoint.enabled ? "Enabled" : "Disabled"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </section>
  );
}

