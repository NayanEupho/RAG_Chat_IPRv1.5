import type { BatchStatus, DocumentStatus, VariantStatus } from "@/lib/types";

type Status = BatchStatus | DocumentStatus | VariantStatus | string;

const toneByStatus: Record<string, string> = {
  DRAFT: "badge neutral",
  SUBMITTED: "badge info",
  PARSING: "badge info",
  NORMALIZING: "badge info",
  REVIEW_PENDING: "badge warning",
  REVIEWING: "badge warning",
  CHUNKING: "badge info",
  PARTIALLY_COMPLETE: "badge warning",
  COMPLETE: "badge success",
  FAILED: "badge danger",
  UPLOADED: "badge neutral",
  PARSE_PENDING: "badge info",
  PARSE_RUNNING: "badge info",
  PARSE_FAILED: "badge danger",
  PARSE_COMPLETE: "badge success",
  NORMALIZE_PENDING: "badge info",
  NORMALIZE_RUNNING: "badge info",
  NORMALIZE_FAILED: "badge danger",
  NORMALIZE_COMPLETE: "badge success",
  REVIEW_IN_PROGRESS: "badge warning",
  REVIEW_APPROVED: "badge success",
  CHUNK_PENDING: "badge info",
  CHUNK_RUNNING: "badge info",
  CHUNK_FAILED: "badge danger",
  INDEXED: "badge success",
  PENDING: "badge info",
  RUNNING: "badge info"
};

export function StatusBadge({ status }: { status: Status }) {
  return <span className={toneByStatus[status] || "badge neutral"}>{status.replaceAll("_", " ")}</span>;
}

