"use client";

import { useEffect, useMemo, useState } from "react";
import { adminApi } from "@/lib/api";
import { fuzzyFilter } from "@/lib/fuzzy";
import { formatDate } from "@/lib/format";
import { useAdminData } from "@/components/use-admin-data";
import { SkeletonRows } from "@/components/loading-state";
import { ChunkCard } from "@/components/chunk-card";
import type { ChunkRecord, IndexedWarehouseDocument } from "@/lib/types";

function docTypeLabel(value?: string | null) {
  return value === "qna" ? "QnA" : "General";
}

export default function ChunksPage() {
  const [search, setSearch] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [chunkSearch, setChunkSearch] = useState("");
  const [activeIndex, setActiveIndex] = useState(0);
  const documents = useAdminData(() => adminApi.indexedDocuments(), 0, "indexedDocuments");
  const docs = documents.data?.items || [];
  const filteredDocs = useMemo(
    () => fuzzyFilter(docs, search, ["filename", "source_path", "batch_id", "document_id", "parser", "doc_type", "origin"]),
    [docs, search]
  );
  const selected = docs.find((item) => item.id === selectedId) || filteredDocs[0] || null;
  const chunkQuery = useMemo(() => {
    if (!selected) return "";
    const filters = new URLSearchParams();
    filters.set("limit", "1000");
    if (selected.origin === "admin" && selected.document_id) {
      filters.set("document_id", selected.document_id);
    } else {
      filters.set("filename", selected.filename);
      if (selected.source_path) filters.set("source", selected.source_path);
    }
    if (selected.doc_type) filters.set("doc_type", selected.doc_type);
    if (chunkSearch) filters.set("search", chunkSearch);
    return `&${filters.toString()}`;
  }, [chunkSearch, selected]);
  const chunks = useAdminData(
    () => selected ? adminApi.chunks(chunkQuery) : Promise.resolve({ items: [], total: 0, page: 1 }),
    0,
    selected ? `chunks:${selected.id}:${chunkSearch}` : "chunks:none",
    Boolean(selected)
  );
  const chunkItems = chunks.data?.items || [];
  const activeChunk = chunkItems[Math.min(activeIndex, Math.max(chunkItems.length - 1, 0))] as ChunkRecord | undefined;

  useEffect(() => {
    if (!selectedId && filteredDocs[0]?.id) setSelectedId(filteredDocs[0].id);
  }, [filteredDocs, selectedId]);

  useEffect(() => {
    setActiveIndex(0);
  }, [selected?.id, chunkSearch]);

  useEffect(() => {
    function handleKey(event: KeyboardEvent) {
      if (event.target instanceof HTMLInputElement || event.target instanceof HTMLTextAreaElement || event.target instanceof HTMLSelectElement) return;
      if (event.key === "ArrowRight" || event.key.toLowerCase() === "d") {
        setActiveIndex((current) => Math.min(current + 1, Math.max(chunkItems.length - 1, 0)));
      }
      if (event.key === "ArrowLeft" || event.key.toLowerCase() === "a") {
        setActiveIndex((current) => Math.max(current - 1, 0));
      }
    }
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [chunkItems.length]);

  function selectDocument(document: IndexedWarehouseDocument) {
    setSelectedId(document.id);
    setActiveIndex(0);
  }

  return (
    <section className="page">
      <div className="page-header">
        <div>
          <h1>Chunk Viewer</h1>
          <p>Inspect indexed chunks from admin-ingested documents and legacy Chroma-backed filesystem ingestions.</p>
        </div>
        <div className="inline">
          <span className="badge neutral">{chunkItems.length} loaded</span>
          {selected ? <span className="badge info">{docTypeLabel(selected.doc_type)}</span> : null}
        </div>
      </div>

      <div className="inspector-layout">
        <aside className="panel inspector-sidebar">
          <h2>Indexed Documents</h2>
          <div className="field">
            <label htmlFor="chunk-doc-search">Search documents</label>
            <input id="chunk-doc-search" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Fuzzy search documents" />
          </div>
          <div className="stack scroll-stack">
            {documents.loading && !documents.data ? <SkeletonRows count={5} /> : null}
            {filteredDocs.map((document) => (
              <button
                className={`stack-row row-main selectable-row ${selected?.id === document.id ? "selected" : ""}`}
                type="button"
                key={`${document.origin}-${document.id}`}
                onClick={() => selectDocument(document)}
              >
                <span>
                  <strong>{document.filename}</strong>
                  <div className="row-meta">{document.chunk_count} chunks - {document.origin} - indexed {formatDate(document.indexed_at)}</div>
                </span>
                <span className="badge info">{docTypeLabel(document.doc_type)}</span>
              </button>
            ))}
            {!documents.loading && !filteredDocs.length ? <div className="empty-state"><strong>No indexed documents</strong><span>Admin and legacy indexed documents will appear here when available.</span></div> : null}
          </div>
        </aside>

        <div className="panel inspector-main">
          <div className="split-header">
            <div>
              <h2>{selected?.filename || "Select a document"}</h2>
              <p>{selected?.source_path || "Choose an indexed document to inspect its chunks."}</p>
            </div>
            <div className="actions">
              <button className="button" type="button" disabled={!chunkItems.length} onClick={() => setActiveIndex((current) => Math.max(current - 1, 0))}>Prev</button>
              <button className="button" type="button" disabled={!chunkItems.length} onClick={() => setActiveIndex((current) => Math.min(current + 1, chunkItems.length - 1))}>Next</button>
            </div>
          </div>
          <div className="field">
            <label htmlFor="chunk-search">Search within chunks</label>
            <input id="chunk-search" value={chunkSearch} onChange={(event) => setChunkSearch(event.target.value)} placeholder="Search chunk text" />
            <span className="muted">Use left/right arrows or A/D to browse cards.</span>
          </div>
          {chunks.loading && !chunks.data ? <SkeletonRows count={4} /> : null}
          {activeChunk ? <ChunkCard chunk={activeChunk} active label={`${activeIndex + 1} of ${chunkItems.length}`} /> : null}
          {!chunks.loading && selected && !chunkItems.length ? <div className="empty-state"><strong>No chunks found</strong><span>This document may have been indexed before admin chunk mirroring was enabled, or the search has no matches.</span></div> : null}
        </div>
      </div>
    </section>
  );
}
