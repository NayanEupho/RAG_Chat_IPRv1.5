"use client";

import { FormEvent, useState } from "react";
import { EmptyState } from "@/components/empty-state";
import { adminApi } from "@/lib/api";
import { useAdminData } from "@/components/use-admin-data";

export default function ControlPanelPage() {
  const stats = useAdminData(() => adminApi.vectorStats(), 10000);
  const endpoints = useAdminData(() => adminApi.llmEndpoints(), 12000);
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setMessage(null);
    try {
      const form = new FormData(event.currentTarget);
      await adminApi.saveLlmEndpoint({
        model_id: String(form.get("model_id") || ""),
        endpoint: String(form.get("endpoint") || ""),
        display_name: String(form.get("display_name") || ""),
        enabled: true
      });
      event.currentTarget.reset();
      await endpoints.refresh();
      setMessage("Endpoint saved.");
    } catch (caught: unknown) {
      setMessage(caught instanceof Error ? caught.message : "Failed to save endpoint");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="page">
      <div className="page-header">
        <div>
          <h1>Control Panel</h1>
          <p>Global parser defaults, LLM endpoints, worker status, and Chroma health.</p>
        </div>
      </div>
      <div className="grid cols-2">
        <div className="panel">
          <h2>System Status</h2>
          <table className="table">
            <tbody>
              <tr><td>Admin API</td><td>{stats.error ? "Degraded" : "Online"}</td></tr>
              <tr><td>ChromaDB</td><td>{stats.data?.healthy ? "Online" : "Unknown"}</td></tr>
              <tr><td>Chroma chunks</td><td>{stats.data?.chroma_count ?? "-"}</td></tr>
              <tr><td>SQLite chunks</td><td>{stats.data?.chunks ?? "-"}</td></tr>
              <tr><td>Registered endpoints</td><td>{endpoints.data?.total ?? "-"}</td></tr>
            </tbody>
          </table>
        </div>
        <form className="panel form" onSubmit={submit}>
          <h2>Register LLM Endpoint</h2>
          <div className="field">
            <label htmlFor="model_id">Model ID</label>
            <input id="model_id" name="model_id" required placeholder="qwen3-70b" />
          </div>
          <div className="field">
            <label htmlFor="endpoint">Endpoint</label>
            <input id="endpoint" name="endpoint" required placeholder="http://10.100.0.5:8000/v1" />
          </div>
          <div className="field">
            <label htmlFor="display_name">Display name</label>
            <input id="display_name" name="display_name" required placeholder="Qwen3 70B" />
          </div>
          <button className="button primary" type="submit" disabled={busy}>{busy ? "Saving..." : "Save Endpoint"}</button>
          {message ? <span className={message.includes("Failed") ? "error" : "muted"}>{message}</span> : null}
        </form>
      </div>

      <div className="panel" style={{ marginTop: 16 }}>
        <h2>LLM Endpoints</h2>
        {!endpoints.data?.items.length ? (
          <EmptyState title="No endpoints registered" detail="Add normalization endpoints here before enabling LLM normalization for batches." />
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

