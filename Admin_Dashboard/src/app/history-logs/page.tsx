"use client";

import { EmptyState } from "@/components/empty-state";
import { StatusBadge } from "@/components/status-badge";
import { useAdminData } from "@/components/use-admin-data";
import { adminApi } from "@/lib/api";

export default function HistoryLogsPage() {
  const batches = useAdminData(() => adminApi.batches(), 12000);
  const logs = useAdminData(() => adminApi.logs(), 8000);

  return (
    <section className="page">
      <div className="page-header">
        <div>
          <h1>History & Logs</h1>
          <p>Batch timelines and append-only job telemetry for audits and failure analysis.</p>
        </div>
      </div>
      <div className="grid cols-2">
        <div className="panel">
          <h2>Batch History</h2>
          {!batches.data?.items.length ? (
            <EmptyState title="No batch history" />
          ) : (
            <table className="table">
              <tbody>
                {batches.data.items.map((batch) => (
                  <tr key={batch.batch_id}>
                    <td>{batch.name}<br /><span className="muted">{batch.created_at}</span></td>
                    <td><StatusBadge status={batch.status} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
        <div className="panel">
          <h2>Recent Logs</h2>
          {!logs.data?.items.length ? (
            <EmptyState title="No logs yet" />
          ) : (
            <table className="table">
              <tbody>
                {logs.data.items.map((log) => (
                  <tr key={log.log_id}>
                    <td>{log.message}<br /><span className="muted">{log.stage} · {log.timestamp}</span></td>
                    <td><StatusBadge status={log.level} /></td>
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

