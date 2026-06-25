"use client";

import { FormEvent, useState } from "react";
import { adminApi } from "@/lib/api";
import { useAdminData } from "@/components/use-admin-data";

export default function ControlPanelPage() {
  const stats = useAdminData(() => adminApi.vectorStats(), 10000);
  const [message, setMessage] = useState<string | null>(null);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setMessage("Endpoint registry UI is staged. Backend endpoint storage is available for the next wiring pass.");
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
            </tbody>
          </table>
        </div>
        <form className="panel form" onSubmit={submit}>
          <h2>Register LLM Endpoint</h2>
          <div className="field"><label htmlFor="model_id">Model ID</label><input id="model_id" placeholder="qwen3-70b" /></div>
          <div className="field"><label htmlFor="endpoint">Endpoint</label><input id="endpoint" placeholder="http://10.100.0.5:8000/v1" /></div>
          <div className="field"><label htmlFor="display_name">Display name</label><input id="display_name" placeholder="Qwen3 70B" /></div>
          <button className="button primary" type="submit">Save Endpoint</button>
          {message ? <span className="muted">{message}</span> : null}
        </form>
      </div>
    </section>
  );
}

