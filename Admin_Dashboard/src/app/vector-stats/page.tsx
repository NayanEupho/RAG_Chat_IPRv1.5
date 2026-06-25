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
        <div className="stat"><span className="muted">Tokens</span><strong>{stats.data?.total_tokens ?? "-"}</strong></div>
        <div className="stat"><span className="muted">Characters</span><strong>{stats.data?.total_chars ?? "-"}</strong></div>
      </div>
      {stats.data?.error ? <p className="error">{stats.data.error}</p> : null}
    </section>
  );
}

