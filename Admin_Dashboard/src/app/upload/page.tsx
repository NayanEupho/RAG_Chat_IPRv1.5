"use client";

import { FormEvent, useState } from "react";
import { EmptyState } from "@/components/empty-state";
import { StatusBadge } from "@/components/status-badge";
import { useAdminData } from "@/components/use-admin-data";
import { adminApi } from "@/lib/api";

export default function UploadPage() {
  const batches = useAdminData(() => adminApi.batches(), 10000);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setMessage(null);
    try {
      const form = new FormData(event.currentTarget);
      const batch = await adminApi.createBatch(form);
      await adminApi.submitBatch(batch.batch_id);
      setMessage("Batch saved and submitted.");
      event.currentTarget.reset();
      await batches.refresh();
    } catch (caught: unknown) {
      setMessage(caught instanceof Error ? caught.message : "Upload failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="page">
      <div className="page-header">
        <div>
          <h1>Upload</h1>
          <p>Stage source files, create a batch, and submit it into the admin ingestion queue.</p>
        </div>
      </div>
      <div className="grid cols-2">
        <form className="panel form" onSubmit={submit}>
          <h2>New Batch</h2>
          <div className="field">
            <label htmlFor="batch_name">Batch name</label>
            <input id="batch_name" name="batch_name" required placeholder="June safety manuals" />
          </div>
          <div className="field">
            <label htmlFor="batch_description">Description</label>
            <textarea id="batch_description" name="batch_description" rows={3} placeholder="Optional context for this ingestion run" />
          </div>
          <div className="field">
            <label htmlFor="files">PDF or DOCX files</label>
            <input id="files" name="files" type="file" multiple accept=".pdf,.docx" required />
          </div>
          <button className="button primary" type="submit" disabled={busy}>{busy ? "Submitting..." : "Save & Submit"}</button>
          {message ? <span className={message.includes("failed") ? "error" : "muted"}>{message}</span> : null}
        </form>

        <div className="panel">
          <h2>Recent Batches</h2>
          {!batches.data?.items.length ? (
            <EmptyState title="No batches yet" detail="Create a batch to start controlled ingestion." />
          ) : (
            <table className="table">
              <tbody>
                {batches.data.items.slice(0, 8).map((batch) => (
                  <tr key={batch.batch_id}>
                    <td>{batch.name}<br /><span className="muted">{batch.total_documents} documents</span></td>
                    <td><StatusBadge status={batch.status} /></td>
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

