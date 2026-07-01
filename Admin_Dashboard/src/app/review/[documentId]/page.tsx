"use client";

import { useEffect, useMemo, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { adminApi, adminEventsUrl } from "@/lib/api";
import { compactStatus, formatDate, statusTone } from "@/lib/format";
import { useAdminData } from "@/components/use-admin-data";
import { SkeletonRows } from "@/components/loading-state";

function typeLabel(value?: string | null): string {
  return value === "qna" ? "QnA" : "General";
}

function escapeHtml(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function inlineMarkdown(value: string): string {
  return escapeHtml(value)
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/\*([^*]+)\*/g, "<em>$1</em>");
}

function renderMarkdown(markdown: string): string {
  const html: string[] = [];
  let inCode = false;
  let inList = false;
  for (const rawLine of markdown.split(/\r?\n/)) {
    const line = rawLine.trimEnd();
    if (line.startsWith("```")) {
      if (inList) {
        html.push("</ul>");
        inList = false;
      }
      html.push(inCode ? "</code></pre>" : "<pre><code>");
      inCode = !inCode;
      continue;
    }
    if (inCode) {
      html.push(`${escapeHtml(rawLine)}\n`);
      continue;
    }
    if (!line.trim()) {
      if (inList) {
        html.push("</ul>");
        inList = false;
      }
      continue;
    }
    const heading = /^(#{1,4})\s+(.+)$/.exec(line);
    if (heading) {
      if (inList) {
        html.push("</ul>");
        inList = false;
      }
      const level = heading[1].length;
      html.push(`<h${level}>${inlineMarkdown(heading[2])}</h${level}>`);
      continue;
    }
    const bullet = /^\s*[-*]\s+(.+)$/.exec(rawLine);
    if (bullet) {
      if (!inList) {
        html.push("<ul>");
        inList = true;
      }
      html.push(`<li>${inlineMarkdown(bullet[1])}</li>`);
      continue;
    }
    if (inList) {
      html.push("</ul>");
      inList = false;
    }
    html.push(`<p>${inlineMarkdown(line)}</p>`);
  }
  if (inCode) html.push("</code></pre>");
  if (inList) html.push("</ul>");
  return html.join("");
}

export default function ReviewDetailPage() {
  const params = useParams<{ documentId: string }>();
  const router = useRouter();
  const documentId = params.documentId;
  const documentState = useAdminData(() => adminApi.document(documentId), 0, `document:${documentId}`);
  const [parsedContent, setParsedContent] = useState("");
  const [targetContent, setTargetContent] = useState("");
  const [source, setSource] = useState<"parsed" | "target">("target");
  const [mode, setMode] = useState<"raw" | "visual">("raw");
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [loadingContent, setLoadingContent] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const document = documentState.data;
  const parse = document?.parse_variants.find((variant) => variant.status === "COMPLETE");
  const norm = parse?.norm_variants.find((variant) => variant.status === "COMPLETE");
  const hasNormalization = Boolean(norm);
  const targetLabel = hasNormalization ? "Normalized markdown" : "Parsed markdown";
  const activeContent = source === "parsed" && hasNormalization ? parsedContent : targetContent;
  const editable = source === "target";
  const rendered = useMemo(() => renderMarkdown(activeContent), [activeContent]);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      if (!document || !parse) return;
      setLoadingContent(true);
      setError(null);
      try {
        if (!document.review) {
          await adminApi.selectVariant(document.document_id, parse.variant_id, norm?.norm_variant_id || null);
          await documentState.refresh();
        }
        const [parsed, review] = await Promise.all([
          adminApi.reviewContent(document.document_id, "parsed"),
          adminApi.reviewContent(document.document_id, "review")
        ]);
        if (cancelled) return;
        setParsedContent(parsed.content);
        setTargetContent(review.content);
        setDirty(false);
        setSource(hasNormalization ? "target" : "target");
      } catch (caught) {
        if (!cancelled) setError(caught instanceof Error ? caught.message : "Unable to load review content.");
      } finally {
        if (!cancelled) setLoadingContent(false);
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [document?.document_id, document?.review, parse?.variant_id, norm?.norm_variant_id, hasNormalization]);

  async function save() {
    setBusy(true);
    setError(null);
    try {
      await adminApi.saveReview(documentId, targetContent);
      setDirty(false);
      await documentState.refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to save markdown.");
    } finally {
      setBusy(false);
    }
  }

  async function approve() {
    if (!parse) return;
    setBusy(true);
    setError(null);
    try {
      if (dirty) {
        await adminApi.saveReview(documentId, targetContent);
        setDirty(false);
      }
      await adminApi.approve(documentId, parse.variant_id, norm?.norm_variant_id || null);
      router.push("/review");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to approve document.");
    } finally {
      setBusy(false);
    }
  }

  async function reject() {
    const confirmed = window.confirm(
      `Reject "${document?.original_filename || documentId}"?\n\nThis document will not be indexed. Its source file, generated markdown, metadata artifacts, and intermediate outputs will be deleted automatically. The batch history will keep an audit record.`
    );
    if (!confirmed) return;
    setBusy(true);
    setError(null);
    try {
      await adminApi.reject(documentId, "Rejected from document review page.");
      router.push("/review");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to reject document.");
    } finally {
      setBusy(false);
    }
  }

  async function replace(file: File | null) {
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      await adminApi.uploadReviewMarkdown(documentId, file);
      const review = await adminApi.reviewContent(documentId, "review");
      setTargetContent(review.content);
      setDirty(false);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to replace markdown.");
    } finally {
      setBusy(false);
    }
  }

  function downloadCurrent() {
    const blob = new Blob([activeContent], { type: "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const anchor = window.document.createElement("a");
    anchor.href = url;
    anchor.download = `${document?.original_filename.replace(/\.[^.]+$/, "") || "document"}-${source === "parsed" && hasNormalization ? "parsed" : "review"}.md`;
    anchor.click();
    URL.revokeObjectURL(url);
  }

  if (!document) {
    return (
      <section className="page">
        <div className="panel">
          {documentState.error ? <p className="error">{documentState.error}</p> : <SkeletonRows count={5} />}
        </div>
      </section>
    );
  }

  const fileBase = `${adminEventsUrl().replace(/\/events$/, "")}/documents/${encodeURIComponent(documentId)}/files`;

  return (
    <section className="page">
      <div className="page-header">
        <div>
          <h1>{document.original_filename}</h1>
          <p>Batch {document.batch_id} - uploaded {formatDate(document.uploaded_at)}</p>
        </div>
        <div className="actions">
          <span className={`badge ${statusTone(document.status)}`}>{compactStatus(document.status)}</span>
          <button className="button" type="button" onClick={() => setMode(mode === "raw" ? "visual" : "raw")}>{mode === "raw" ? "Visualize" : "Raw markdown"}</button>
          <button className="button" type="button" onClick={downloadCurrent} disabled={!activeContent}>Download current</button>
        </div>
      </div>
      {error ? <p className="error">{error}</p> : null}

      <div className="grid cols-2 review-grid">
        <div className="panel">
          <h2>Document Details</h2>
          <div className="stack">
            <div className="doc-line"><span>Parser</span><strong>{parse?.parser_type || "Unknown"}</strong></div>
            <div className="doc-line"><span>Ingestion type</span><strong>{typeLabel(document.ingestion_type || document.effective_config.ingestion_type)}</strong></div>
            <div className="doc-line"><span>Normalization</span><strong>{norm ? norm.model_config.display_name : "Not selected"}</strong></div>
            <div className="doc-line"><span>Review target</span><strong>{targetLabel}</strong></div>
          </div>

          <div className="source-tabs" role="tablist" aria-label="Markdown source">
            {hasNormalization ? (
              <button className={source === "parsed" ? "active" : ""} type="button" onClick={() => setSource("parsed")}>Parsed MD</button>
            ) : null}
            <button className={source === "target" ? "active" : ""} type="button" onClick={() => setSource("target")}>{targetLabel}</button>
          </div>

          <div className="actions" style={{ marginTop: 14 }}>
            <a className="button" href={`${fileBase}/parsed?download=true`}>Download parsed</a>
            {norm ? <a className="button" href={`${fileBase}/normalized?download=true`}>Download normalized original</a> : null}
            <label className={`button${!editable ? " disabled" : ""}`}>
              Replace review target
              <input type="file" accept=".md,.markdown" hidden disabled={!editable || busy} onChange={(event) => void replace(event.target.files?.[0] || null)} />
            </label>
            <button className="button" type="button" disabled={busy || !dirty} onClick={() => void save()}>Save</button>
            <button className="button primary" type="button" disabled={busy || !parse} onClick={() => void approve()}>Approve and index</button>
            <button className="button danger" type="button" disabled={busy} onClick={() => void reject()}>Reject</button>
          </div>
        </div>

        <div className="panel">
          <h2>{mode === "raw" ? `${editable ? "Editable" : "Read-only"} Markdown` : "Rendered Preview"}</h2>
          {loadingContent ? <SkeletonRows count={8} /> : null}
          {!loadingContent && mode === "raw" ? (
            editable ? (
              <textarea
                className="markdown-box"
                value={targetContent}
                onChange={(event) => {
                  setTargetContent(event.target.value);
                  setDirty(true);
                }}
              />
            ) : (
              <pre className="markdown-box readonly">{parsedContent}</pre>
            )
          ) : null}
          {!loadingContent && mode === "visual" ? (
            <div className="markdown-render markdown-box" dangerouslySetInnerHTML={{ __html: rendered }} />
          ) : null}
        </div>
      </div>
    </section>
  );
}
