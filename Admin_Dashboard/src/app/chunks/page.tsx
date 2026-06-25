"use client";

import { EmptyState } from "@/components/empty-state";
import { useAdminData } from "@/components/use-admin-data";
import { adminApi } from "@/lib/api";

export default function ChunksPage() {
  const chunks = useAdminData(() => adminApi.chunks(), 12000);

  return (
    <section className="page">
      <div className="page-header">
        <div>
          <h1>Chunks</h1>
          <p>Audit the text payloads and metadata mirrored from approved Chroma inserts.</p>
        </div>
      </div>
      <div className="panel">
        {!chunks.data?.items.length ? (
          <EmptyState title="No chunks indexed" detail="Approved documents will produce searchable chunk records here." />
        ) : (
          <table className="table">
            <thead><tr><th>Chunk</th><th>Section</th><th>Size</th><th>Source</th></tr></thead>
            <tbody>
              {chunks.data.items.map((chunk) => (
                <tr key={chunk.chunk_id}>
                  <td>{chunk.content.slice(0, 220)}{chunk.content.length > 220 ? "..." : ""}</td>
                  <td>{chunk.section_path || "-"}</td>
                  <td>{chunk.token_count} tokens<br /><span className="muted">{chunk.char_count} chars</span></td>
                  <td>{chunk.indexed_at || chunk.embedding_model}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </section>
  );
}
