"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { adminApi } from "@/lib/api";
import { compactStatus, formatBytes, formatDate, statusTone } from "@/lib/format";
import { useAdminData } from "@/components/use-admin-data";
import { SkeletonRows } from "@/components/loading-state";
import { BatchConfigDetails } from "@/components/batch-config-details";
import type { AdminDocument, Batch, IngestionType, RuntimeConfig } from "@/lib/types";

function fileKey(file: File): string {
  return `${file.name}:${file.size}:${file.lastModified}`;
}

interface StagedDocumentConfig {
  ingestion_type: IngestionType;
  parser: string;
  normalization_enabled: boolean;
  review_required: boolean;
}

type ConfigScope = "all" | "custom";
const ACCEPTED_EXTENSIONS = /\.(pdf|docx|txt|md|markdown|pptx|xlsx|html)$/i;
const ACCEPT_ATTRIBUTE = ".pdf,.docx,.txt,.md,.markdown,.pptx,.xlsx,.html";
type BatchTab = "draft" | "processing" | "completed";

interface BatchConfigPayload {
  default_parsers: string[];
  default_normalization_enabled: boolean;
  default_normalization_models: Array<{ model_id: string; endpoint: string; display_name: string }>;
  default_ingestion_type: IngestionType;
  review_required: boolean;
  per_document_overrides: Record<string, Record<string, unknown>>;
}

function ingestionLabel(value: IngestionType): string {
  return value === "qna" ? "QnA" : "General";
}

function docConfigFromEffective(document: AdminDocument): StagedDocumentConfig {
  return {
    ingestion_type: document.effective_config.ingestion_type,
    parser: document.effective_config.parsers?.[0] || "docling",
    normalization_enabled: Boolean(document.effective_config.normalization_enabled),
    review_required: document.effective_config.review_required ?? true
  };
}

function sameConfig(left: StagedDocumentConfig, right: StagedDocumentConfig): boolean {
  return left.ingestion_type === right.ingestion_type
    && left.parser === right.parser
    && left.normalization_enabled === right.normalization_enabled
    && left.review_required === right.review_required;
}

function configuredModels(runtime: RuntimeConfig | null, fallback: Array<{ model_id: string; endpoint: string; display_name: string }> = []) {
  if (runtime?.normalization.model_id && runtime.normalization.endpoint) {
    return [{
      model_id: runtime.normalization.model_id,
      endpoint: runtime.normalization.endpoint,
      display_name: runtime.normalization.display_name
    }];
  }
  return fallback;
}

function buildBatchConfigPayload(
  defaults: StagedDocumentConfig,
  documentConfigs: Record<string, StagedDocumentConfig>,
  documents: AdminDocument[],
  runtime: RuntimeConfig | null,
  existingModels: Array<{ model_id: string; endpoint: string; display_name: string }> = []
): BatchConfigPayload {
  const models = configuredModels(runtime, existingModels);
  const per_document_overrides: Record<string, Record<string, unknown>> = {};
  for (const document of documents) {
    const config = documentConfigs[document.document_id] || defaults;
    if (!sameConfig(config, defaults)) {
      per_document_overrides[document.document_id] = {
        parsers: [config.parser],
        normalization_enabled: config.normalization_enabled,
        normalization_models: config.normalization_enabled ? models : [],
        ingestion_type: config.ingestion_type,
        review_required: config.review_required
      };
    }
  }
  return {
    default_parsers: [defaults.parser],
    default_normalization_enabled: defaults.normalization_enabled,
    default_normalization_models: defaults.normalization_enabled ? models : [],
    default_ingestion_type: defaults.ingestion_type,
    review_required: defaults.review_required,
    per_document_overrides
  };
}

function DraftBatchEditor({
  batch,
  parserOptions,
  runtime,
  onStart,
  onDelete,
  onSaved
}: {
  batch: Batch;
  parserOptions: RuntimeConfig["parser_options"];
  runtime: RuntimeConfig | null;
  onStart: (batchId: string) => Promise<void>;
  onDelete: (batchId: string) => Promise<void>;
  onSaved: () => Promise<void>;
}) {
  const documents = batch.documents || [];
  const config = batch.config as Partial<BatchConfigPayload>;
  const initialDefaults: StagedDocumentConfig = {
    ingestion_type: (config.default_ingestion_type as IngestionType) || "general",
    parser: config.default_parsers?.[0] || "docling",
    normalization_enabled: Boolean(config.default_normalization_enabled),
    review_required: config.review_required ?? true
  };
  const [defaults, setDefaults] = useState<StagedDocumentConfig>(initialDefaults);
  const [documentConfigs, setDocumentConfigs] = useState<Record<string, StagedDocumentConfig>>(() => Object.fromEntries(
    documents.map((document) => [document.document_id, docConfigFromEffective(document)])
  ));
  const [scope, setScope] = useState<ConfigScope>(() => {
    const configs = documents.map((document) => docConfigFromEffective(document));
    return configs.every((item) => sameConfig(item, initialDefaults)) ? "all" : "custom";
  });
  const [busy, setBusy] = useState<"save" | "start" | "delete" | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  function patchDefaults(patch: Partial<StagedDocumentConfig>) {
    setDefaults((current) => {
      const next = { ...current, ...patch };
      if (scope === "all") {
        setDocumentConfigs(Object.fromEntries(documents.map((document) => [document.document_id, next])));
      }
      return next;
    });
  }

  function patchDocument(documentId: string, patch: Partial<StagedDocumentConfig>) {
    setScope("custom");
    setDocumentConfigs((current) => ({
      ...current,
      [documentId]: {
        ...(current[documentId] || defaults),
        ...patch
      }
    }));
  }

  function applyDefaultsToAll() {
    setDocumentConfigs(Object.fromEntries(documents.map((document) => [document.document_id, defaults])));
    setScope("all");
  }

  async function saveDraft(): Promise<boolean> {
    setBusy("save");
    setMessage(null);
    try {
      const existingModels = (config.default_normalization_models || []) as Array<{ model_id: string; endpoint: string; display_name: string }>;
      await adminApi.updateBatchConfig(batch.batch_id, buildBatchConfigPayload(defaults, documentConfigs, documents, runtime, existingModels));
      setMessage("Saved");
      await onSaved();
      return true;
    } catch (caught) {
      setMessage(caught instanceof Error ? caught.message : "Unable to save draft.");
      return false;
    } finally {
      setBusy(null);
      window.setTimeout(() => setMessage(null), 2400);
    }
  }

  async function startDraft() {
    setBusy("start");
    setMessage(null);
    try {
      const saved = await saveDraft();
      if (!saved) return;
      await onStart(batch.batch_id);
    } finally {
      setBusy(null);
    }
  }

  async function deleteDraft() {
    if (!window.confirm(`Delete draft batch "${batch.name}" and its uploaded source files?`)) return;
    setBusy("delete");
    setMessage(null);
    try {
      await onDelete(batch.batch_id);
    } catch (caught) {
      setMessage(caught instanceof Error ? caught.message : "Unable to delete draft.");
    } finally {
      setBusy(null);
    }
  }

  return (
    <details className="stack-row">
      <summary>
        <span>
          <span className="row-title">
            <strong>{batch.name}</strong>
            <span className={`badge ${statusTone(batch.status)}`}>{compactStatus(batch.status)}</span>
            <span className="badge info">{String(batch.ingestion_label || "general_docs").replace("_docs", "").replace("qna", "QnA")}</span>
            <span className={scope === "all" ? "badge success" : "badge warning"}>{scope === "all" ? "All documents" : "Custom"}</span>
          </span>
          <div className="row-meta">{batch.total_documents} docs - created {formatDate(batch.created_at)}</div>
        </span>
        <div className="actions">
          <button className="button primary" type="button" disabled={busy !== null} onClick={(event) => { event.preventDefault(); void startDraft(); }}>{busy === "start" ? "Starting..." : "Start"}</button>
        </div>
      </summary>
      <div className="row-detail">
        <div className="grid cols-4">
          <div className="field">
            <label>Batch type</label>
            <select value={defaults.ingestion_type} onChange={(event) => patchDefaults({ ingestion_type: event.target.value as IngestionType })}>
              <option value="general">General</option>
              <option value="qna">QnA</option>
            </select>
          </div>
          <div className="field">
            <label>Parser</label>
            <select value={defaults.parser} onChange={(event) => patchDefaults({ parser: event.target.value })}>
              {parserOptions.map((option) => <option value={option.value} disabled={!option.available} key={option.value}>{option.label}{option.available ? "" : " (not configured)"}</option>)}
            </select>
          </div>
          <div className="field">
            <label>LLM normalization</label>
            <select value={defaults.normalization_enabled ? "true" : "false"} onChange={(event) => patchDefaults({ normalization_enabled: event.target.value === "true" })}>
              <option value="false">False</option>
              <option value="true">True</option>
            </select>
          </div>
          <div className="field">
            <label>Audit / review</label>
            <select value={defaults.review_required ? "true" : "false"} onChange={(event) => patchDefaults({ review_required: event.target.value === "true" })}>
              <option value="true">True</option>
              <option value="false">False</option>
            </select>
          </div>
        </div>
        <div className="actions">
          <button className="button" type="button" onClick={applyDefaultsToAll}>Apply batch config to all documents</button>
          <span className={scope === "all" ? "badge success" : "badge warning"}>{scope === "all" ? "All document settings match batch config" : "Custom per-document settings active"}</span>
        </div>
        <div className="stack">
          {documents.map((document) => {
            const docConfig = documentConfigs[document.document_id] || defaults;
            return (
              <div className="stack-row row-main" key={document.document_id}>
                <span>
                  <strong>{document.original_filename}</strong>
                  <div className="row-meta">{document.document_id}</div>
                </span>
                <div className="document-config-grid">
                  <label>
                    Type
                    <select value={docConfig.ingestion_type} onChange={(event) => patchDocument(document.document_id, { ingestion_type: event.target.value as IngestionType })}>
                      <option value="general">General</option>
                      <option value="qna">QnA</option>
                    </select>
                  </label>
                  <label>
                    Parser
                    <select value={docConfig.parser} onChange={(event) => patchDocument(document.document_id, { parser: event.target.value })}>
                      {parserOptions.map((option) => <option value={option.value} disabled={!option.available} key={option.value}>{option.label}{option.available ? "" : " (not configured)"}</option>)}
                    </select>
                  </label>
                  <label>
                    LLM
                    <select value={docConfig.normalization_enabled ? "true" : "false"} onChange={(event) => patchDocument(document.document_id, { normalization_enabled: event.target.value === "true" })}>
                      <option value="false">False</option>
                      <option value="true">True</option>
                    </select>
                  </label>
                  <label>
                    Review
                    <select value={docConfig.review_required ? "true" : "false"} onChange={(event) => patchDocument(document.document_id, { review_required: event.target.value === "true" })}>
                      <option value="true">True</option>
                      <option value="false">False</option>
                    </select>
                  </label>
                </div>
              </div>
            );
          })}
        </div>
        <div className="actions">
          <button className="button" type="button" disabled={busy !== null} onClick={() => void saveDraft()}>{busy === "save" ? "Saving..." : "Save changes"}</button>
          <button className="button primary" type="button" disabled={busy !== null} onClick={() => void startDraft()}>{busy === "start" ? "Starting..." : "Save and start"}</button>
          <button className="button danger" type="button" disabled={busy !== null} onClick={() => void deleteDraft()}>{busy === "delete" ? "Deleting..." : "Delete draft"}</button>
          {message ? <span className={message === "Saved" ? "badge success" : "badge danger"}>{message}</span> : null}
        </div>
      </div>
    </details>
  );
}

export default function IngestionPage() {
  const router = useRouter();
  const batches = useAdminData(() => adminApi.batches("&include_documents=true"), 0, "batchesWithDocuments");
  const runtime = useAdminData(() => adminApi.runtimeConfig(), 0, "runtimeConfig");
  const [files, setFiles] = useState<File[]>([]);
  const [name, setName] = useState("");
  const [batchIngestionType, setBatchIngestionType] = useState<IngestionType>("general");
  const [parser, setParser] = useState("docling");
  const [normalization, setNormalization] = useState(false);
  const [reviewRequired, setReviewRequired] = useState(true);
  const [configScope, setConfigScope] = useState<ConfigScope>("all");
  const [batchTab, setBatchTab] = useState<BatchTab>("draft");
  const [documentConfigs, setDocumentConfigs] = useState<Record<string, StagedDocumentConfig>>({});
  const [saving, setSaving] = useState<"draft" | "submit" | null>(null);
  const [error, setError] = useState<string | null>(null);

  const totalBytes = useMemo(() => files.reduce((sum, file) => sum + file.size, 0), [files]);
  const stagedTypes = files.map((file) => documentConfigs[fileKey(file)]?.ingestion_type || batchIngestionType);
  const stagedTypeSet = new Set(stagedTypes);
  const stagedBatchLabel = stagedTypeSet.size > 1 ? "Mix" : ingestionLabel(stagedTypes[0] || batchIngestionType);
  const parserOptions = runtime.data?.parser_options?.length
    ? runtime.data.parser_options
    : [
        { value: "auto", label: "Auto", description: "Quality-gated parser fallback chain.", available: true },
        { value: "docling", label: "Docling", description: "Standard Docling parser.", available: true },
        { value: "docling_vision", label: "Docling OCR", description: "Forced OCR through Docling.", available: true },
        { value: "pymupdf4llm", label: "PyMuPDF4LLM", description: "Fast digital PDF parser.", available: true },
        { value: "pymupdf", label: "PyMuPDF", description: "Local PyMuPDF parser.", available: true },
        { value: "vision_llm", label: "VLM", description: "Uses RAG_VLM_MODEL from .env.", available: false }
      ];
  const selectedParser = parserOptions.find((option) => option.value === parser);
  const allBatches = batches.data?.items || [];
  const draftBatches = allBatches.filter((batch) => batch.status === "DRAFT");
  const terminalBatchStatuses = ["COMPLETE", "PARTIALLY_COMPLETE", "FAILED", "CANCELLED"];
  const processingBatches = allBatches.filter((batch) => !["DRAFT", ...terminalBatchStatuses].includes(batch.status));
  const completedBatches = allBatches.filter((batch) => terminalBatchStatuses.includes(batch.status));
  const tabItems: Array<{ id: BatchTab; label: string; count: number }> = [
    { id: "draft", label: "Saved (TBS)", count: draftBatches.length },
    { id: "processing", label: "Processing", count: processingBatches.length },
    { id: "completed", label: "Completed", count: completedBatches.length }
  ];

  function currentDefaultConfig(): StagedDocumentConfig {
    return {
      ingestion_type: batchIngestionType,
      parser,
      normalization_enabled: normalization,
      review_required: reviewRequired
    };
  }

  function updateFiles(next: FileList | null) {
    const selected = Array.from(next || []);
    const accepted = selected.filter((file) => ACCEPTED_EXTENSIONS.test(file.name));
    const rejected = selected.filter((file) => !ACCEPTED_EXTENSIONS.test(file.name));
    if (rejected.length) {
      setError(`Unsupported file type: ${rejected.map((file) => file.name).join(", ")}`);
    } else {
      setError(null);
    }
    setFiles(accepted);
    setDocumentConfigs((current) => {
      const nextConfigs: Record<string, StagedDocumentConfig> = {};
      accepted.forEach((file) => {
        const key = fileKey(file);
        nextConfigs[key] = current[key] || {
          ingestion_type: batchIngestionType,
          parser,
          normalization_enabled: normalization,
          review_required: reviewRequired
        };
      });
      return nextConfigs;
    });
  }

  function applyBatchType(value: IngestionType) {
    setBatchIngestionType(value);
    if (configScope === "all") {
      setDocumentConfigs((current) => Object.fromEntries(files.map((file) => {
        const key = fileKey(file);
        return [key, { ...(current[key] || { parser, normalization_enabled: normalization, review_required: reviewRequired }), ingestion_type: value }];
      })));
    }
  }

  function applyBatchParser(value: string) {
    setParser(value);
    if (configScope === "all") {
      setDocumentConfigs((current) => Object.fromEntries(files.map((file) => {
        const key = fileKey(file);
        return [key, { ...(current[key] || { ingestion_type: batchIngestionType, normalization_enabled: normalization, review_required: reviewRequired }), parser: value }];
      })));
    }
  }

  function applyBatchNormalization(value: boolean) {
    setNormalization(value);
    if (configScope === "all") {
      setDocumentConfigs((current) => Object.fromEntries(files.map((file) => {
        const key = fileKey(file);
        return [key, { ...(current[key] || { ingestion_type: batchIngestionType, parser, review_required: reviewRequired }), normalization_enabled: value }];
      })));
    }
  }

  function applyBatchReview(value: boolean) {
    setReviewRequired(value);
    if (configScope === "all") {
      setDocumentConfigs((current) => Object.fromEntries(files.map((file) => {
        const key = fileKey(file);
        return [key, { ...(current[key] || { ingestion_type: batchIngestionType, parser, normalization_enabled: normalization }), review_required: value }];
      })));
    }
  }

  function setDocumentConfig(file: File, patch: Partial<StagedDocumentConfig>) {
    const key = fileKey(file);
    setConfigScope("custom");
    setDocumentConfigs((current) => ({
      ...current,
      [key]: {
        ...(current[key] || {
          ingestion_type: batchIngestionType,
          parser,
          normalization_enabled: normalization,
          review_required: reviewRequired
        }),
        ...patch
      }
    }));
  }

  function applyBatchConfigToAllDocuments() {
    const defaults = currentDefaultConfig();
    setDocumentConfigs(Object.fromEntries(files.map((file) => [fileKey(file), defaults])));
    setConfigScope("all");
  }

  async function createBatch(submit: boolean) {
    if (!name.trim() || files.length === 0) {
      setError("Batch name and at least one supported document are required.");
      return;
    }
    setSaving(submit ? "submit" : "draft");
    setError(null);
    try {
      const form = new FormData();
      form.append("batch_name", name.trim());
      form.append("parser", parser);
      form.append("ingestion_type", batchIngestionType);
      const defaults = currentDefaultConfig();
      const perDocumentConfigs = files.map((file) => (configScope === "all" ? defaults : documentConfigs[fileKey(file)] || defaults));
      form.append("document_configs_json", JSON.stringify(perDocumentConfigs));
      form.append("document_types_json", JSON.stringify(perDocumentConfigs.map((config) => config.ingestion_type)));
      form.append("normalization_enabled", String(normalization));
      form.append("review_required", String(reviewRequired));
      if (perDocumentConfigs.some((config) => config.normalization_enabled) && runtime.data?.normalization.model_id && runtime.data.normalization.endpoint) {
        form.append("normalization_model_id", runtime.data.normalization.model_id);
        form.append("normalization_endpoint", runtime.data.normalization.endpoint);
        form.append("normalization_display_name", runtime.data.normalization.display_name);
      }
      files.forEach((file) => form.append("files", file));
      const batch = await adminApi.createBatch(form);
      if (submit) {
        await adminApi.submitBatch(batch.batch_id);
        router.push(`/monitoring?batchId=${encodeURIComponent(batch.batch_id)}`);
      } else {
        setFiles([]);
        setDocumentConfigs({});
        setName("");
        setConfigScope("all");
        await batches.refresh();
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to create batch.");
    } finally {
      setSaving(null);
    }
  }

  async function submitDraft(batchId: string) {
    setError(null);
    try {
      await adminApi.submitBatch(batchId);
      router.push(`/monitoring?batchId=${encodeURIComponent(batchId)}`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to submit draft.");
    }
  }

  async function deleteDraft(batchId: string) {
    setError(null);
    try {
      await adminApi.deleteBatch(batchId);
      await batches.refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to delete draft.");
    }
  }

  return (
    <section className="page">
      <div className="page-header">
        <div>
          <h1>Ingestion</h1>
          <p>Stage documents locally, create a named batch, then save it as a draft or start ingestion.</p>
        </div>
      </div>

      <div className="grid cols-2">
        <div className="panel">
          <h2>Create Batch</h2>
          <div className="form">
            <div className="field">
              <label htmlFor="batch-name">Batch name</label>
              <input id="batch-name" value={name} onChange={(event) => setName(event.target.value)} placeholder="Quarterly policy updates" />
            </div>

              <label className="dropzone">
              <span>
                <strong>Drop supported documents here</strong>
                <br />
                <span className="muted">Files remain local until you save or start the batch.</span>
              </span>
              <input type="file" multiple accept={ACCEPT_ATTRIBUTE} onChange={(event) => updateFiles(event.target.files)} hidden />
            </label>

            <div className="grid cols-3">
              <div className="field">
                <label htmlFor="ingestion-type">Batch type</label>
                <select id="ingestion-type" value={batchIngestionType} onChange={(event) => applyBatchType(event.target.value as IngestionType)} required>
                  <option value="general">General</option>
                  <option value="qna">QnA</option>
                </select>
              </div>
              <div className="field">
                <label htmlFor="parser">Parser</label>
                <select id="parser" value={parser} onChange={(event) => applyBatchParser(event.target.value)} required>
                  {parserOptions.map((option) => (
                    <option value={option.value} disabled={!option.available} key={option.value}>
                      {option.label}{option.available ? "" : " (not configured)"}
                    </option>
                  ))}
                </select>
              </div>
              <div className="field">
                <label htmlFor="normalization">LLM normalization</label>
                <select id="normalization" value={normalization ? "true" : "false"} onChange={(event) => applyBatchNormalization(event.target.value === "true")} required>
                  <option value="false">False</option>
                  <option value="true">True</option>
                </select>
              </div>
              <div className="field">
                <label htmlFor="review">Audit / review</label>
                <select id="review" value={reviewRequired ? "true" : "false"} onChange={(event) => applyBatchReview(event.target.value === "true")} required>
                  <option value="true">True</option>
                  <option value="false">False</option>
                </select>
              </div>
            </div>

            <div className="empty-state">
              <strong>{selectedParser?.label || parser}</strong>
              <span>{selectedParser?.description || "Parser mode selected for every PDF in this batch."}</span>
              <span>{stagedBatchLabel} batch: General documents use the structure-aware chunker; QnA documents use Q&A pair chunking and QnA normalization instructions.</span>
              <span className={configScope === "all" ? "badge success" : "badge warning"}>{configScope === "all" ? "Batch config applies to all documents" : "Custom per-document settings active"}</span>
              {parser === "vision_llm" ? (
                <span>VLM model: {runtime.data?.vision.model_id || "not configured"} at {runtime.data?.vision.endpoint || "not configured"}</span>
              ) : null}
              <span>DOCX files are parsed through the Docling non-PDF pipeline regardless of PDF parser mode.</span>
            </div>

            {normalization ? (
              <div className="empty-state">
                <strong>Normalization model</strong>
                <span>{runtime.data?.normalization.display_name || "No runtime normalization model configured"}</span>
              </div>
            ) : null}

            {files.length > 0 ? (
              <div className="stack">
                <div className="actions">
                  <button className="button" type="button" onClick={applyBatchConfigToAllDocuments}>Apply batch config to all documents</button>
                  <span className={configScope === "all" ? "badge success" : "badge warning"}>{configScope === "all" ? "All" : "Custom"}</span>
                </div>
                {files.map((file) => (
                  <div className="stack-row" key={`${file.name}-${file.size}`}>
                    <span>
                      <strong>{file.name}</strong>
                      <div className="row-meta">{formatBytes(file.size)}</div>
                    </span>
                    <div className="document-config-grid">
                      <label>
                        Type
                        <select value={documentConfigs[fileKey(file)]?.ingestion_type || batchIngestionType} onChange={(event) => setDocumentConfig(file, { ingestion_type: event.target.value as IngestionType })} aria-label={`Set ingestion type for ${file.name}`}>
                          <option value="general">General</option>
                          <option value="qna">QnA</option>
                        </select>
                      </label>
                      <label>
                        Parser
                        <select value={documentConfigs[fileKey(file)]?.parser || parser} onChange={(event) => setDocumentConfig(file, { parser: event.target.value })} aria-label={`Set parser for ${file.name}`}>
                          {parserOptions.map((option) => (
                            <option value={option.value} disabled={!option.available} key={option.value}>
                              {option.label}{option.available ? "" : " (not configured)"}
                            </option>
                          ))}
                        </select>
                      </label>
                      <label>
                        LLM
                        <select value={(documentConfigs[fileKey(file)]?.normalization_enabled ?? normalization) ? "true" : "false"} onChange={(event) => setDocumentConfig(file, { normalization_enabled: event.target.value === "true" })} aria-label={`Set normalization for ${file.name}`}>
                          <option value="false">False</option>
                          <option value="true">True</option>
                        </select>
                      </label>
                      <label>
                        Review
                        <select value={(documentConfigs[fileKey(file)]?.review_required ?? reviewRequired) ? "true" : "false"} onChange={(event) => setDocumentConfig(file, { review_required: event.target.value === "true" })} aria-label={`Set review for ${file.name}`}>
                          <option value="true">True</option>
                          <option value="false">False</option>
                        </select>
                      </label>
                    </div>
                  </div>
                ))}
              </div>
            ) : null}

            <div className="inline">
              <span className="badge neutral">{files.length} files</span>
              <span className="badge neutral">{formatBytes(totalBytes)}</span>
              <span className="badge info">{stagedBatchLabel}</span>
            </div>
            {error ? <p className="error">{error}</p> : null}
            <div className="actions">
              <button className="button" type="button" onClick={() => void createBatch(false)} disabled={saving !== null}>
                {saving === "draft" ? "Saving..." : "Save draft"}
              </button>
              <button className="button primary" type="button" onClick={() => void createBatch(true)} disabled={saving !== null}>
                {saving === "submit" ? "Starting..." : "Start ingestion"}
              </button>
              <button className="button" type="button" onClick={() => setFiles([])} disabled={saving !== null}>Clear queue</button>
            </div>
          </div>
        </div>

        <div className="panel">
          <div className="page-header">
            <div>
              <h2>Batch Workbench</h2>
              <p>Inspect saved drafts, edit TBS settings, and track active or completed batches.</p>
            </div>
          </div>
          <div className="source-tabs" role="tablist" aria-label="Batch status tabs">
            {tabItems.map((item) => (
              <button
                className={batchTab === item.id ? "active" : ""}
                type="button"
                onClick={() => setBatchTab(item.id)}
                key={item.id}
              >
                {item.label} <span className="badge neutral">{item.count}</span>
              </button>
            ))}
          </div>
          <div className="stack scroll-stack" style={{ marginTop: 14 }}>
            {batches.loading && !batches.data ? <SkeletonRows count={4} /> : null}
            {batchTab === "draft" ? (
              <>
                {draftBatches.map((batch) => (
                  <DraftBatchEditor
                    batch={batch}
                    parserOptions={parserOptions}
                    runtime={runtime.data}
                    onStart={submitDraft}
                    onDelete={deleteDraft}
                    onSaved={batches.refresh}
                    key={batch.batch_id}
                  />
                ))}
                {!batches.loading && !draftBatches.length ? <div className="empty-state"><strong>No saved TBS drafts</strong><span>Draft batches that have not started ingestion will appear here.</span></div> : null}
              </>
            ) : null}
            {batchTab === "processing" ? (
              <>
                {processingBatches.map((batch) => (
                  <details className="stack-row" key={batch.batch_id}>
                    <summary>
                      <span>
                        <span className="row-title"><strong>{batch.name}</strong><span className={`badge ${statusTone(batch.status)}`}>{compactStatus(batch.status)}</span><span className="badge info">{String(batch.ingestion_label || "general_docs").replace("_docs", "").replace("qna", "QnA")}</span></span>
                        <div className="row-meta">{batch.total_documents} docs - triggered {formatDate(batch.submitted_at)}</div>
                      </span>
                      <button className="button" type="button" onClick={(event) => { event.preventDefault(); router.push(`/monitoring?batchId=${encodeURIComponent(batch.batch_id)}`); }}>Monitor</button>
                    </summary>
                    <div className="row-detail">
                      <BatchConfigDetails batch={batch} />
                    </div>
                  </details>
                ))}
                {!batches.loading && !processingBatches.length ? <div className="empty-state"><strong>No processing batches</strong><span>Started ingestion batches will appear here until they complete.</span></div> : null}
              </>
            ) : null}
            {batchTab === "completed" ? (
              <>
                {completedBatches.map((batch) => (
                  <details className="stack-row" key={batch.batch_id}>
                    <summary>
                      <span>
                        <span className="row-title"><strong>{batch.name}</strong><span className={`badge ${statusTone(batch.status)}`}>{compactStatus(batch.status)}</span><span className="badge info">{String(batch.ingestion_label || "general_docs").replace("_docs", "").replace("qna", "QnA")}</span></span>
                        <div className="row-meta">{batch.total_documents} docs - completed {formatDate(batch.completed_at)}</div>
                      </span>
                      <button className="button" type="button" onClick={(event) => { event.preventDefault(); router.push("/past-jobs"); }}>Past jobs</button>
                    </summary>
                    <div className="row-detail">
                      <BatchConfigDetails batch={batch} />
                    </div>
                  </details>
                ))}
                {!batches.loading && !completedBatches.length ? <div className="empty-state"><strong>No completed batches</strong><span>Finished, failed, and partially indexed batches will appear here.</span></div> : null}
              </>
            ) : null}
          </div>
        </div>
      </div>
    </section>
  );
}
