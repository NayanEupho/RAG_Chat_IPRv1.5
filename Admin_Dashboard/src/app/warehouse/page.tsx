"use client";

import { useMemo, useState } from "react";
import { adminApi, adminEventsUrl } from "@/lib/api";
import { fuzzyFilter } from "@/lib/fuzzy";
import { formatBytes, formatDate } from "@/lib/format";
import { setAdminDataCache, useAdminData } from "@/components/use-admin-data";
import { SkeletonRows, SkeletonStats } from "@/components/loading-state";
import { RefreshIconButton } from "@/components/refresh-icon-button";

function EyeIcon() {
  return (
    <svg aria-hidden="true" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7Z" />
      <circle cx="12" cy="12" r="3" />
    </svg>
  );
}

function DownloadIcon() {
  return (
    <svg aria-hidden="true" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 3v12" />
      <path d="m7 10 5 5 5-5" />
      <path d="M5 21h14" />
    </svg>
  );
}

function FileAction({ label, href }: { label: string; href: string }) {
  return (
    <span className="file-action">
      <a className="icon-button" href={href} target="_blank" title={`View ${label}`} aria-label={`View ${label}`}>
        <EyeIcon />
      </a>
      <span className="file-action-label">{label}</span>
      <a className="icon-button" href={`${href}${href.includes("?") ? "&" : "?"}download=true`} title={`Download ${label}`} aria-label={`Download ${label}`}>
        <DownloadIcon />
      </a>
    </span>
  );
}

function typeLabel(value?: string | null): string {
  return value === "qna" ? "QnA" : "General";
}

export default function WarehousePage() {
  const [search, setSearch] = useState("");
  const [refreshing, setRefreshing] = useState(false);
  const [refreshMessage, setRefreshMessage] = useState<string | null>(null);
  const [highlightedIds, setHighlightedIds] = useState<Set<string>>(new Set());
  const documents = useAdminData(() => adminApi.indexedDocuments(), 0, "indexedDocuments");
  const allItems = documents.data?.items || [];
  const items = useMemo(
    () => fuzzyFilter(allItems, search, ["filename", "source_path", "batch_id", "document_id", "parser", "origin", "doc_type", "ingestion_type"]),
    [allItems, search]
  );
  const totalChunks = allItems.reduce((sum, item) => sum + item.chunk_count, 0);
  const sourceBytes = allItems.reduce((sum, item) => sum + item.file_size_bytes, 0);
  const apiBase = adminEventsUrl().replace(/\/events$/, "");

  async function refreshDocuments() {
    setRefreshing(true);
    setRefreshMessage(null);
    try {
      const previousIds = new Set(allItems.map((item) => `${item.origin}-${item.id}`));
      const next = await adminApi.indexedDocuments();
      const newIds = next.items
        .filter((item) => !previousIds.has(`${item.origin}-${item.id}`))
        .map((item) => `${item.origin}-${item.id}`);
      setAdminDataCache("indexedDocuments", next);
      if (newIds.length > 0) {
        setHighlightedIds(new Set(newIds));
        setRefreshMessage(`${newIds.length} new document${newIds.length === 1 ? "" : "s"}`);
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
          <h1>Document Warehouse</h1>
          <p>All currently indexed documents available for retrieval, including admin batches and legacy file-watcher ingestion.</p>
        </div>
        <div className="actions">
          <RefreshIconButton refreshing={refreshing} label="Refresh documents" onRefresh={() => void refreshDocuments()} />
          {refreshMessage ? <span className={`inline-refresh-status ${refreshMessage.startsWith("Refresh failed") ? "error" : refreshMessage === "Nothing new" ? "neutral" : "success"}`}>{refreshMessage}</span> : null}
        </div>
      </div>

      <div className="grid cols-3">
        {documents.loading && !documents.data ? (
          <SkeletonStats count={3} />
        ) : (
          <>
            <div className="stat"><span>Indexed documents</span><strong>{documents.data?.total || 0}</strong></div>
            <div className="stat"><span>Total chunks</span><strong>{totalChunks}</strong></div>
            <div className="stat"><span>Source volume</span><strong>{formatBytes(sourceBytes)}</strong></div>
          </>
        )}
      </div>

      <div className="panel">
        <div className="field">
          <label htmlFor="warehouse-search">Search documents</label>
          <input
            id="warehouse-search"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") event.preventDefault();
            }}
            placeholder="Fuzzy search like Ctrl+P: try reportv8, leave glance, qna faq"
          />
          <span className="muted">{search.trim() ? `${items.length} of ${allItems.length} documents matched` : `${allItems.length} documents loaded`}</span>
        </div>
      </div>

      <div className="panel">
        <h2>Indexed Documents</h2>
        <div className="stack">
          {documents.loading && !documents.data ? <SkeletonRows count={6} /> : null}
          {items.map((item) => (
            <details className={`stack-row ${highlightedIds.has(`${item.origin}-${item.id}`) ? "row-highlight-new" : ""}`} key={`${item.origin}-${item.id}`}>
              <summary>
                <span>
                  <span className="row-title">
                    <strong>{item.filename}</strong>
                    <span className={item.origin === "legacy" ? "badge warning" : "badge success"}>{item.origin === "legacy" ? "Legacy" : "Admin"}</span>
                    <span className="badge info">{typeLabel(item.doc_type || item.ingestion_type)}</span>
                    <span className="badge neutral">{item.chunk_count} chunks</span>
                  </span>
                  <div className="row-meta">Indexed {formatDate(item.indexed_at)} - parser {item.parser || "unknown"}</div>
                </span>
                <span className="muted">{item.batch_id ? `Batch ${item.batch_id.slice(0, 12)}` : "File watcher"}</span>
              </summary>
              <div className="row-detail">
                <div className="doc-line">
                  <span>Source path</span>
                  <span className="muted truncate-path" title={item.source_path || "Not recorded"}>{item.source_path || "Not recorded"}</span>
                </div>
                <div className="doc-line"><span>Document type</span><strong>{typeLabel(item.doc_type || item.ingestion_type)}</strong></div>
                <div className="doc-line"><span>Volume</span><strong>{formatBytes(item.file_size_bytes)}</strong></div>
                <div className="actions">
                  {item.origin === "admin" && item.document_id ? (
                    <>
                      <FileAction label="Source" href={`${apiBase}/documents/${encodeURIComponent(item.document_id)}/files/source`} />
                      <FileAction label="Parsed MD" href={`${apiBase}/documents/${encodeURIComponent(item.document_id)}/files/parsed`} />
                      {item.downloads?.normalized ? <FileAction label="Normalized MD" href={`${apiBase}/documents/${encodeURIComponent(item.document_id)}/files/normalized`} /> : null}
                      <FileAction label="Final MD" href={`${apiBase}/documents/${encodeURIComponent(item.document_id)}/files/approved`} />
                    </>
                  ) : (
                    <>
                      {item.downloads?.source ? <FileAction label="Source" href={`${apiBase}/legacy-documents/${encodeURIComponent(item.id)}/files/source`} /> : null}
                      {item.downloads?.parsed ? <FileAction label="Parsed MD" href={`${apiBase}/legacy-documents/${encodeURIComponent(item.id)}/files/parsed`} /> : null}
                      {item.downloads?.normalized ? <FileAction label="Normalized MD" href={`${apiBase}/legacy-documents/${encodeURIComponent(item.id)}/files/normalized`} /> : null}
                      {item.downloads?.final ? <FileAction label="Final MD" href={`${apiBase}/legacy-documents/${encodeURIComponent(item.id)}/files/final`} /> : null}
                      {!item.downloads?.source && !item.downloads?.parsed && !item.downloads?.normalized && !item.downloads?.final ? (
                        <span className="badge neutral">No legacy files are resolvable on disk.</span>
                      ) : null}
                    </>
                  )}
                </div>
              </div>
            </details>
          ))}
          {!documents.loading && !items.length ? (
            <div className="empty-state">
              <strong>No indexed documents found</strong>
              <span>Indexed admin and legacy documents will appear here.</span>
            </div>
          ) : null}
        </div>
      </div>
    </section>
  );
}
