"use client";

import type { ChunkRecord, VectorProbeChunk } from "@/lib/types";

type ChunkLike = ChunkRecord | VectorProbeChunk;

function metadataFor(chunk: ChunkLike): Record<string, unknown> {
  if ("metadata" in chunk && chunk.metadata) return chunk.metadata;
  return {
    document_id: "document_id" in chunk ? chunk.document_id : null,
    batch_id: "batch_id" in chunk ? chunk.batch_id : null,
    chunk_index: "chunk_index" in chunk ? chunk.chunk_index : null,
    section_path: "section_path" in chunk ? chunk.section_path : null,
    page_numbers: "page_numbers" in chunk ? chunk.page_numbers : [],
    embedding_model: "embedding_model" in chunk ? chunk.embedding_model : null,
    chroma_id: "chroma_id" in chunk ? chunk.chroma_id : null
  };
}

function contentFor(chunk: ChunkLike): string {
  return "content" in chunk ? chunk.content : "";
}

function chunkIndex(chunk: ChunkLike): number | string {
  const value = "chunk_index" in chunk ? chunk.chunk_index : null;
  return value ?? ("rank" in chunk && chunk.rank ? chunk.rank : "N/A");
}

function score(value?: number | null): string | null {
  if (value == null || Number.isNaN(Number(value))) return null;
  return Number(value).toFixed(4);
}

async function copyText(value: string) {
  await navigator.clipboard.writeText(value);
}

export function ChunkCard({ chunk, active = false, label }: { chunk: ChunkLike; active?: boolean; label?: string }) {
  const metadata = metadataFor(chunk);
  const content = contentFor(chunk);
  const similarity = "similarity" in chunk ? score(chunk.similarity) : null;
  const rerankScore = "rerank_score" in chunk ? score(chunk.rerank_score) : null;
  return (
    <article className={`chunk-card ${active ? "active" : ""}`}>
      <header>
        <div>
          <span className="eyebrow">{label || `Chunk ${chunkIndex(chunk)}`}</span>
          <h3>{String(metadata.filename || ("filename" in chunk ? chunk.filename : "") || metadata.document_id || "Indexed chunk")}</h3>
        </div>
        <div className="inline">
          {"doc_type" in chunk && chunk.doc_type ? <span className="badge info">{chunk.doc_type === "qna" ? "QnA" : "General"}</span> : null}
          {similarity ? <span className="badge success">Sim {similarity}</span> : null}
          {rerankScore ? <span className="badge warning">Rerank {rerankScore}</span> : null}
        </div>
      </header>
      <div className="chunk-meta-grid">
        <span><strong>Index</strong>{chunkIndex(chunk)}</span>
        <span><strong>Tokens</strong>{"token_count" in chunk ? chunk.token_count : "N/A"}</span>
        <span><strong>Chars</strong>{"char_count" in chunk ? chunk.char_count : content.length}</span>
        <span><strong>Section</strong>{String(metadata.section_path || "Not recorded")}</span>
      </div>
      <pre className="chunk-content">{content}</pre>
      <details className="metadata-drawer">
        <summary>Metadata</summary>
        <pre>{JSON.stringify(metadata, null, 2)}</pre>
      </details>
      <div className="actions">
        <button className="button" type="button" onClick={() => void copyText(content)}>Copy chunk</button>
        <button className="button" type="button" onClick={() => void copyText(JSON.stringify(metadata, null, 2))}>Copy metadata</button>
      </div>
    </article>
  );
}
