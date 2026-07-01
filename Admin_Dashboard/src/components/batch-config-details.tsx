import type { AdminDocument, Batch, IngestionType } from "@/lib/types";

function typeLabel(value?: string | null): string {
  return value === "qna" ? "QnA" : "General";
}

function boolLabel(value?: boolean | null): string {
  return value ? "True" : "False";
}

function documentConfig(document: AdminDocument) {
  return {
    ingestion_type: document.effective_config?.ingestion_type || document.ingestion_type || "general",
    parser: document.effective_config?.parsers?.[0] || "docling",
    normalization_enabled: Boolean(document.effective_config?.normalization_enabled),
    review_required: document.effective_config?.review_required ?? true
  };
}

function defaultsFromBatch(batch: Batch) {
  const config = batch.config as {
    default_ingestion_type?: IngestionType;
    default_parsers?: string[];
    default_normalization_enabled?: boolean;
    review_required?: boolean;
  };
  return {
    ingestion_type: config.default_ingestion_type || "general",
    parser: config.default_parsers?.[0] || "docling",
    normalization_enabled: Boolean(config.default_normalization_enabled),
    review_required: config.review_required ?? true
  };
}

function sameConfig(left: ReturnType<typeof documentConfig>, right: ReturnType<typeof defaultsFromBatch>): boolean {
  return left.ingestion_type === right.ingestion_type
    && left.parser === right.parser
    && left.normalization_enabled === right.normalization_enabled
    && left.review_required === right.review_required;
}

export function BatchConfigDetails({ batch }: { batch: Batch }) {
  const documents = batch.documents || [];
  const defaults = defaultsFromBatch(batch);
  const hasCustom = documents.some((document) => !sameConfig(documentConfig(document), defaults));
  const models = ((batch.config as { default_normalization_models?: Array<{ display_name?: string; model_id?: string; endpoint?: string }> }).default_normalization_models || []);
  const modelLabel = models.length ? models.map((model) => model.display_name || model.model_id).join(", ") : "None";

  return (
    <div className="batch-config-detail">
      <div className="inline">
        <span className={hasCustom ? "badge warning" : "badge success"}>{hasCustom ? "Custom document config" : "Batch config applies to all"}</span>
        <span className="badge info">{typeLabel(defaults.ingestion_type)}</span>
        <span className="badge neutral">{defaults.parser}</span>
        <span className="badge neutral">LLM {boolLabel(defaults.normalization_enabled)}</span>
        <span className="badge neutral">Review {boolLabel(defaults.review_required)}</span>
      </div>
      {!hasCustom ? (
        <div className="doc-line">
          <span>Batch normalization model</span>
          <strong>{defaults.normalization_enabled ? modelLabel : "Not selected"}</strong>
        </div>
      ) : (
        <div className="stack">
          {documents.map((document) => {
            const config = documentConfig(document);
            return (
              <div className="doc-line" key={document.document_id}>
                <span>
                  <strong>{document.original_filename}</strong>
                  <div className="row-meta">{document.document_id}</div>
                </span>
                <span className="inline">
                  <span className="badge info">{typeLabel(config.ingestion_type)}</span>
                  <span className="badge neutral">{config.parser}</span>
                  <span className="badge neutral">LLM {boolLabel(config.normalization_enabled)}</span>
                  <span className="badge neutral">Review {boolLabel(config.review_required)}</span>
                </span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
