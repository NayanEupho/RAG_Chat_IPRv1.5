"use client";

import { useMemo, useState } from "react";
import { adminApi } from "@/lib/api";
import { fuzzyFilter } from "@/lib/fuzzy";
import { formatBytes, formatDate } from "@/lib/format";
import { setAdminDataCache, useAdminData } from "@/components/use-admin-data";
import { SkeletonRows } from "@/components/loading-state";
import type { IndexedWarehouseDocument } from "@/lib/types";

function typeLabel(value?: string | null): string {
  return value === "qna" ? "QnA" : "General";
}

export default function ControlCenterPage() {
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const documents = useAdminData(() => adminApi.indexedDocuments(), 0, "indexedDocuments");
  const allItems = documents.data?.items || [];
  const items = useMemo(
    () => fuzzyFilter(allItems, search, ["filename", "source_path", "batch_id", "document_id", "parser", "origin", "doc_type", "ingestion_type"]),
    [allItems, search]
  );
  const selectedItems = useMemo(() => items.filter((item) => selected.has(`${item.origin}:${item.id}`)), [items, selected]);

  function toggle(item: IndexedWarehouseDocument) {
    const key = `${item.origin}:${item.id}`;
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  async function deleteItems(targets: IndexedWarehouseDocument[]) {
    if (!targets.length) return;
    const detail = targets
      .map((item) => {
        const parts = [
          `- ${item.filename} (${item.origin})`,
          `  document type: ${typeLabel(item.doc_type || item.ingestion_type)}`,
          `  vectors/chunks: ${item.chunk_count}`,
          `  source: ${item.source_path || "not recorded"}`,
          item.origin === "admin" ? "  admin metadata: document row, canonical files, mirrored chunks" : "  legacy metadata: Chroma entries and available upload_docs source file",
          "  artifacts: available parsed/normalized/final markdown files when present",
        ];
        return parts.join("\n");
      })
      .join("\n\n");
    if (!window.confirm(`Delete ${targets.length} indexed document(s) from retrieval?\n\n${detail}`)) return;
    if (!window.confirm("Final confirmation: this removes vectors and available stored files for selected documents.")) return;
    setBusy(true);
    setError(null);
    try {
      for (const item of targets) {
        await adminApi.deleteIndexedDocument(item);
      }
      const deleted = new Set(targets.map((item) => `${item.origin}:${item.id}`));
      const nextItems = allItems.filter((item) => !deleted.has(`${item.origin}:${item.id}`));
      setAdminDataCache("indexedDocuments", { ...(documents.data || { total: nextItems.length, page: 1 }), items: nextItems, total: nextItems.length });
      setSelected(new Set());
      await documents.refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Delete failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="page">
      <div className="page-header">
        <div>
          <h1>Control Center</h1>
          <p>Remove indexed documents from retrieval. Intermediate batches, parsing jobs, and review-pending documents are not shown here.</p>
        </div>
        <button className="button danger" type="button" disabled={busy || selectedItems.length === 0} onClick={() => void deleteItems(selectedItems)}>
          Delete selected
        </button>
      </div>
      {error ? <p className="error">{error}</p> : null}

      <div className="panel">
        <div className="field">
          <label htmlFor="control-search">Search indexed documents</label>
          <input
            id="control-search"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") event.preventDefault();
            }}
            placeholder="Fuzzy search like Ctrl+P: filename, batch, parser, source"
          />
          <span className="muted">{search.trim() ? `${items.length} of ${allItems.length} documents matched` : `${allItems.length} documents loaded`}</span>
        </div>
      </div>

      <div className="panel">
        <h2>Retrieval Documents</h2>
        <div className="stack">
          {documents.loading && !documents.data ? <SkeletonRows count={6} /> : null}
          {items.map((item) => {
            const key = `${item.origin}:${item.id}`;
            return (
              <div className="stack-row row-main" key={key}>
                <span>
                  <span className="row-title">
                    <input type="checkbox" checked={selected.has(key)} onChange={() => toggle(item)} aria-label={`Select ${item.filename}`} />
                    <strong>{item.filename}</strong>
                    <span className={item.origin === "legacy" ? "badge warning" : "badge success"}>{item.origin === "legacy" ? "Legacy" : "Admin"}</span>
                    <span className="badge info">{typeLabel(item.doc_type || item.ingestion_type)}</span>
                    <span className="badge neutral">{item.chunk_count} chunks</span>
                  </span>
                  <div className="row-meta truncate-path" title={item.source_path || "Not recorded"}>Indexed {formatDate(item.indexed_at)} - {formatBytes(item.file_size_bytes)} - {item.source_path || "Not recorded"}</div>
                </span>
                <button className="button danger" type="button" disabled={busy} onClick={() => void deleteItems([item])}>Delete</button>
              </div>
            );
          })}
          {!documents.loading && !items.length ? (
            <div className="empty-state">
              <strong>No indexed documents</strong>
              <span>Only documents currently available to retrieval appear here.</span>
            </div>
          ) : null}
        </div>
      </div>
    </section>
  );
}
