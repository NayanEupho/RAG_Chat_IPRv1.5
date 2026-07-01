"use client";

import { useState } from "react";
import { adminApi } from "@/lib/api";
import { formatDate } from "@/lib/format";
import { setAdminDataCache, useAdminData } from "@/components/use-admin-data";
import { SkeletonRows } from "@/components/loading-state";
import { RefreshIconButton } from "@/components/refresh-icon-button";

function yamlValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "null";
  return String(value).replaceAll("\n", "\n    ");
}

export default function ErrorLogsPage() {
  const [refreshing, setRefreshing] = useState(false);
  const [refreshMessage, setRefreshMessage] = useState<string | null>(null);
  const [highlightedIds, setHighlightedIds] = useState<Set<string>>(new Set());
  const logs = useAdminData(() => adminApi.logs("&level=ERROR"), 0, "logs");
  const errorLogs = logs.data?.items || [];

  async function refreshLogs() {
    setRefreshing(true);
    setRefreshMessage(null);
    try {
      const previousIds = new Set(errorLogs.map((log) => log.log_id));
      const next = await adminApi.logs("&level=ERROR");
      const newIds = next.items.filter((log) => !previousIds.has(log.log_id)).map((log) => log.log_id);
      setAdminDataCache("logs", next);
      if (newIds.length > 0) {
        setHighlightedIds(new Set(newIds));
        setRefreshMessage(`${newIds.length} new error${newIds.length === 1 ? "" : "s"}`);
        window.setTimeout(() => setHighlightedIds(new Set()), 5200);
      } else {
        setRefreshMessage("Nothing new");
      }
    } catch (caught) {
      setRefreshMessage(caught instanceof Error ? `Refresh failed: ${caught.message}` : "Refresh failed");
    } finally {
      setRefreshing(false);
      window.setTimeout(() => setRefreshMessage(null), 2600);
    }
  }

  return (
    <section className="page">
      <div className="page-header">
        <div>
          <h1>Error Logs</h1>
          <p>Failure records grouped as expandable log rows with timestamps, batch/document ids, stage, and raw details.</p>
        </div>
        <div className="actions">
          <RefreshIconButton refreshing={refreshing} label="Refresh error logs" onRefresh={() => void refreshLogs()} />
          {refreshMessage ? <span className={`inline-refresh-status ${refreshMessage.startsWith("Refresh failed") ? "error" : refreshMessage === "Nothing new" ? "neutral" : "success"}`}>{refreshMessage}</span> : null}
        </div>
      </div>

      <div className="panel">
        <h2>Errors</h2>
        <div className="stack">
          {logs.loading && !logs.data ? <SkeletonRows count={6} /> : null}
          {errorLogs.map((log) => (
            <details className={`stack-row ${highlightedIds.has(log.log_id) ? "row-highlight-error" : ""}`} key={log.log_id}>
              <summary>
                <span>
                  <span className="row-title"><strong>{log.message}</strong><span className="badge danger">{log.stage}</span></span>
                  <div className="row-meta">{formatDate(log.timestamp)} - batch {log.batch_id || "n/a"} - document {log.document_id || "n/a"}</div>
                </span>
                <span className="badge danger">{log.level}</span>
              </summary>
              <div className="row-detail">
                <pre className="terminal">{`log_id: ${yamlValue(log.log_id)}
timestamp: ${yamlValue(log.timestamp)}
level: ${yamlValue(log.level)}
stage: ${yamlValue(log.stage)}
batch_id: ${yamlValue(log.batch_id)}
document_id: ${yamlValue(log.document_id)}
job_id: ${yamlValue(log.job_id)}
message: ${yamlValue(log.message)}
detail: |
    ${yamlValue(log.detail)}`}</pre>
              </div>
            </details>
          ))}
          {!logs.loading && !errorLogs.length ? <div className="empty-state"><strong>No error logs</strong><span>Pipeline failures will appear here with captured details.</span></div> : null}
        </div>
      </div>
    </section>
  );
}
