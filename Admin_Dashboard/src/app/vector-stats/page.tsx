"use client";

import { useMemo, useState } from "react";
import { adminApi } from "@/lib/api";
import { fuzzyFilter } from "@/lib/fuzzy";
import { formatBytes } from "@/lib/format";
import { setAdminDataCache, useAdminData } from "@/components/use-admin-data";
import { SkeletonRows, SkeletonStats } from "@/components/loading-state";
import { RefreshIconButton } from "@/components/refresh-icon-button";
import { ChunkCard } from "@/components/chunk-card";
import type { IndexedWarehouseDocument, VectorProbeResult } from "@/lib/types";

function number(value?: number | null, digits = 1) {
  if (value == null || Number.isNaN(Number(value))) return "0";
  return Number(value).toFixed(digits);
}

export default function VectorStatsPage() {
  const [refreshing, setRefreshing] = useState(false);
  const [query, setQuery] = useState("");
  const [topK, setTopK] = useState(5);
  const [candidateK, setCandidateK] = useState(15);
  const [rerank, setRerank] = useState(true);
  const [docSearch, setDocSearch] = useState("");
  const [selectedDocId, setSelectedDocId] = useState<string>("");
  const [probe, setProbe] = useState<VectorProbeResult | null>(null);
  const [probeTab, setProbeTab] = useState<"final" | "candidates" | "context">("final");
  const [probing, setProbing] = useState(false);
  const [probeError, setProbeError] = useState<string | null>(null);
  const stats = useAdminData(() => adminApi.vectorStatsDetail(), 0, "vectorStatsDetail");
  const documents = useAdminData(() => adminApi.indexedDocuments(), 0, "indexedDocuments");
  const indexedDocs = documents.data?.items || [];
  const filteredDocs = useMemo(
    () => fuzzyFilter(indexedDocs, docSearch, ["filename", "source_path", "batch_id", "document_id", "doc_type"]),
    [indexedDocs, docSearch]
  );
  const selectedDoc = indexedDocs.find((item) => item.id === selectedDocId) || null;

  async function refreshStats() {
    setRefreshing(true);
    try {
      const next = await adminApi.vectorStatsDetail();
      setAdminDataCache("vectorStatsDetail", next);
    } finally {
      setRefreshing(false);
    }
  }

  async function runProbe() {
    if (!query.trim()) return;
    setProbing(true);
    setProbeError(null);
    try {
      const payload = {
        query: query.trim(),
        top_k: topK,
        candidate_k: Math.max(candidateK, topK),
        rerank,
        document_id: selectedDoc?.origin === "admin" ? selectedDoc.document_id : null,
        filename: selectedDoc?.origin === "legacy" ? selectedDoc.filename : null,
        doc_type: selectedDoc?.doc_type || null
      };
      const result = await adminApi.vectorProbe(payload);
      setProbe(result);
      setProbeTab(result.rerank_enabled ? "final" : "candidates");
    } catch (caught) {
      setProbeError(caught instanceof Error ? caught.message : "Vector probe failed");
    } finally {
      setProbing(false);
    }
  }

  function clearProbe() {
    setProbe(null);
    setProbeError(null);
    setQuery("");
  }

  const shownChunks = probeTab === "candidates" ? probe?.candidates || [] : probe?.final_chunks || [];

  return (
    <section className="page">
      <div className="page-header">
        <div>
          <h1>Vector Stats</h1>
          <p>Inspect Chroma retrieval footprint, admin chunk mirrors, and probe the vector database with reranker visibility.</p>
        </div>
        <div className="actions">
          <RefreshIconButton refreshing={refreshing} label="Refresh vector stats" onRefresh={() => void refreshStats()} />
          {stats.data?.healthy === false ? <span className="badge danger">Vector issue</span> : <span className="badge success">Vector ready</span>}
        </div>
      </div>

      <div className="grid cols-4">
        {stats.loading && !stats.data ? <SkeletonStats count={4} /> : (
          <>
            <div className="stat"><span>Indexed documents</span><strong>{stats.data?.indexed_documents || 0}</strong></div>
            <div className="stat"><span>Chroma chunks</span><strong>{stats.data?.chroma_chunks ?? 0}</strong></div>
            <div className="stat"><span>Avg chunks/doc</span><strong>{number(stats.data?.avg_chunks_per_document)}</strong></div>
            <div className="stat"><span>Avg tokens/chunk</span><strong>{number(stats.data?.avg_tokens_per_chunk)}</strong></div>
          </>
        )}
      </div>

      <div className="grid cols-2">
        <div className="panel">
          <h2>Vector Breakdown</h2>
          <div className="stack">
            <div className="doc-line"><span>Admin documents</span><strong>{stats.data?.admin_documents || 0}</strong></div>
            <div className="doc-line"><span>Legacy documents</span><strong>{stats.data?.legacy_documents || 0}</strong></div>
            <div className="doc-line"><span>Admin mirrored chunks</span><strong>{stats.data?.mirrored_admin_chunks || 0}</strong></div>
            <div className="doc-line"><span>Indexed text</span><strong>{formatBytes(stats.data?.total_chars || 0)}</strong></div>
          </div>
        </div>
        <div className="panel">
          <h2>Embeddings & Types</h2>
          <div className="stack">
            {Object.entries(stats.data?.doc_type_breakdown || {}).map(([key, value]) => (
              <div className="doc-line" key={key}><span>{key === "qna" ? "QnA" : "General"} documents</span><strong>{value}</strong></div>
            ))}
            {(stats.data?.embedding_models || []).map((item) => (
              <div className="doc-line" key={item.embedding_model}><span>{item.embedding_model}</span><strong>{item.chunks} chunks</strong></div>
            ))}
            {!stats.loading && !Object.keys(stats.data?.doc_type_breakdown || {}).length ? <div className="empty-state"><strong>No vector details</strong><span>Indexed chunks will populate this section.</span></div> : null}
          </div>
        </div>
      </div>

      {stats.data?.warnings?.length ? (
        <div className="panel warning-panel">
          <h2>Vector Warnings</h2>
          <div className="stack">
            {stats.data.warnings.map((warning) => (
              <div className="stack-row" key={`${warning.type}-${warning.message}`}>
                <strong>{warning.type}</strong>
                <span>{warning.message}</span>
                {warning.impact ? <span className="row-meta"><strong>Impact:</strong> {warning.impact}</span> : null}
                {warning.recommendation ? <span className="row-meta"><strong>Recommended:</strong> {warning.recommendation}</span> : null}
              </div>
            ))}
          </div>
        </div>
      ) : null}

      <div className="panel">
        <div className="split-header">
          <div>
            <h2>Vector Probe</h2>
            <p>Search Chroma, optionally run the reranker, and inspect the chunks that would be passed forward as retrieval context.</p>
          </div>
          <button className="button" type="button" onClick={clearProbe} disabled={!probe && !query}>Clear</button>
        </div>
        <div className="probe-grid">
          <div className="field">
            <label htmlFor="probe-query">Query</label>
            <textarea id="probe-query" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Ask a retrieval-style question" rows={4} />
          </div>
          <div className="field">
            <label htmlFor="probe-doc-search">Optional document filter</label>
            <input id="probe-doc-search" value={docSearch} onChange={(event) => setDocSearch(event.target.value)} placeholder="Search indexed docs" />
            <select value={selectedDocId} onChange={(event) => setSelectedDocId(event.target.value)}>
              <option value="">All indexed documents</option>
              {filteredDocs.slice(0, 80).map((document: IndexedWarehouseDocument) => (
                <option key={`${document.origin}-${document.id}`} value={document.id}>{document.filename} ({document.origin})</option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor="probe-top-k">Final top K</label>
            <input id="probe-top-k" type="number" min={1} max={20} value={topK} onChange={(event) => setTopK(Math.max(1, Math.min(20, Number(event.target.value) || 1)))} />
          </div>
          <div className="field">
            <label htmlFor="probe-candidate-k">Candidate K</label>
            <input id="probe-candidate-k" type="number" min={1} max={50} value={candidateK} onChange={(event) => setCandidateK(Math.max(1, Math.min(50, Number(event.target.value) || 1)))} />
          </div>
          <label className="toggle-row">
            <input type="checkbox" checked={rerank} onChange={(event) => setRerank(event.target.checked)} />
            <span>Run reranker</span>
          </label>
          <button className="button primary" type="button" disabled={probing || !query.trim()} onClick={() => void runProbe()}>{probing ? "Running probe" : "Run probe"}</button>
        </div>
        {probeError ? <p className="error">{probeError}</p> : null}
        {probing ? <SkeletonRows count={3} /> : null}
        {probe ? (
          <div className="probe-results">
            <div className="inline">
              <span className="badge neutral">Total {probe.latency_ms}ms</span>
              <span className="badge neutral">Embedding {probe.embedding_ms}ms</span>
              <span className="badge neutral">Vector {probe.vector_ms}ms</span>
              {probe.rerank_ms != null ? <span className="badge neutral">Rerank {probe.rerank_ms}ms</span> : null}
              {probe.reranker_model ? <span className="badge info">{probe.reranker_model}</span> : null}
            </div>
            <div className="tab-row">
              <button className={probeTab === "final" ? "active" : ""} type="button" onClick={() => setProbeTab("final")}>Final top K</button>
              <button className={probeTab === "candidates" ? "active" : ""} type="button" onClick={() => setProbeTab("candidates")}>Vector candidates</button>
              <button className={probeTab === "context" ? "active" : ""} type="button" onClick={() => setProbeTab("context")}>Model context</button>
            </div>
            {probeTab === "context" ? <pre className="chunk-content context-view">{probe.model_context}</pre> : (
              <div className="chunk-card-grid">
                {shownChunks.map((chunk, index) => <ChunkCard chunk={chunk} key={`${chunk.chunk_id}-${index}`} label={`${index + 1} of ${shownChunks.length}`} />)}
              </div>
            )}
          </div>
        ) : null}
      </div>
    </section>
  );
}
